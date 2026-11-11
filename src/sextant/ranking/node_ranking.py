"""The node entry's ranking mode, for the entry path (LEAD-0115 6, part N2b-2b).

``python -m sextant.ranking.node_ranking`` builds the same data-only live node as the capacity
entry (``node_main``: no execution client, the Alpaca data client through
``LiveNodeBuilder``) with the RankingActor over a ``SegmentedHost``, N1e's ``StreamFacts`` and
the node heartbeat. Every argument is required. Priming inputs come only from files an
existing job on main writes (DESIGN-N2B2-BUILD section 6): the K2 universe artifact
(``paper.c_universe``), the calibration job's per-segment baselines with their manifest, and
the committed K2 ranking registry. An input with no producer on main refuses the start before
the lease and before any node, naming it: today the prior close and the asset security type.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nautilus_trader.live import LiveNode, LiveNodeBuilder, LiveNodeConfig
from nautilus_trader.model import InstrumentId, Symbol

from sextant.alpaca.config import AlpacaDataClientConfig
from sextant.alpaca.constants import VENUE
from sextant.alpaca.factories import AlpacaDataClientFactory
from sextant.alpaca.stream_facts import StreamFacts
from sextant.data.baseline_recipe import (
    FEEDS,
    MANIFEST_NAME,
    load_universe,
    verified_baseline_text,
)
from sextant.ranking.baseline import BaselineTable, load_baseline, segment_start
from sextant.ranking.engine import Segment
from sextant.ranking.node_actor import RankingActor, RankingActorConfig
from sextant.ranking.node_main import (
    CLIENT_NAME,
    NODE_NAME,
    MarketDataLease,
    node_config,
    refuse_order_paths,
)
from sextant.ranking.node_main import _positive as positive
from sextant.ranking.node_session import SegmentedHost, SegmentInputs
from sextant.ranking.registry import Registry

SEGMENTS = ("pre", "rth", "post", "overnight")  # the calibration job's baseline files
# Inputs the entry path needs that no job on main writes to a file (DESIGN-N2B2-BUILD 6).
MISSING = (
    "prior close: no job on main writes an official split-adjusted completed close",
    "asset security type: the K2 universe artifact carries none",
)


class RankingRefused(ValueError):
    """The ranking mode will not start; the message names every missing or invalid input."""


@dataclass(frozen=True)
class RankingArguments:
    universe: tuple[str, ...]
    universe_source: str
    baselines: dict[str, BaselineTable]
    registry: Registry
    duration_s: int
    receipt_dir: Path
    page_window_s: int
    status_snapshot_window_s: int
    data: AlpacaDataClientConfig


def parse(argv: list[str] | None = None) -> tuple[RankingArguments, argparse.Namespace]:
    parser = argparse.ArgumentParser(
        prog="python -m sextant.ranking.node_ranking", allow_abbrev=False
    )
    required = parser.add_argument_group("required")
    for flag, kind in (
        ("--universe-artifact", Path),
        ("--baseline-dir", Path),
        ("--registry", Path),
        ("--duration-s", positive),
        ("--receipt-dir", Path),
        ("--page-window-s", positive),
        ("--status-snapshot-window-s", positive),
        ("--feed", str),
        ("--api-key-env", str),
        ("--api-secret-env", str),
        ("--lease-root", Path),
        ("--paper-slot", int),
        ("--existing-streams", int),
        ("--lease-source", str),
    ):
        required.add_argument(flag, type=kind, required=True)
    raw = parser.parse_args(argv)
    if raw.feed != "sip":
        raise RankingRefused("the ranking mode ranks the sip feed's PRE, RTH and POST only")
    return load_inputs(raw), raw


def load_inputs(raw: argparse.Namespace) -> RankingArguments:
    from sextant.tradingview.prestage import load_registry

    loaded: dict[str, Any] = {}
    failures: list[str] = []
    for name, load in (
        ("universe", lambda: load_universe(raw.universe_artifact)),
        ("baselines", lambda: _baselines(raw.baseline_dir, loaded.get("universe"))),
        ("registry", lambda: load_registry(raw.registry)),
    ):
        try:
            loaded[name] = load()
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    if failures:
        raise RankingRefused("invalid priming inputs: " + "; ".join(failures))
    symbols, digest = loaded["universe"]
    return RankingArguments(
        tuple(symbols),
        f"K2 universe artifact {digest['path']} sha256 {digest['sha256']}; NOT PIT",
        loaded["baselines"],
        loaded["registry"],
        raw.duration_s,
        raw.receipt_dir,
        raw.page_window_s,
        raw.status_snapshot_window_s,
        AlpacaDataClientConfig(
            api_key_env=raw.api_key_env, api_secret_env=raw.api_secret_env, feed=raw.feed
        ),
    )


def _baselines(directory: Path, universe: Any) -> dict[str, BaselineTable]:
    """The four files, once the manifest ties them to the selected universe artifact (the
    calibration job writes its digest: calibration_job.py ``universe=universe``) and each file
    to its segment's feed (baseline_recipe ``FEEDS``), all before the lease (Codex r1)."""
    if universe is None:
        raise ValueError("no valid universe artifact to tie the baseline manifest to")
    manifest = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    tied = manifest.get("universe") if isinstance(manifest, dict) else None
    if not isinstance(tied, dict) or tied.get("sha256") != universe[1]["sha256"]:
        raise ValueError("the baseline manifest's universe digest is not the selected artifact's")
    tables = {
        name.upper(): load_baseline(verified_baseline_text(directory / f"{name}.json"))
        for name in SEGMENTS
    }
    wrong = sorted(name for name, table in tables.items() if table.feed != FEEDS[name])
    if wrong:
        raise ValueError(f"baseline files of another feed: {', '.join(wrong)}")
    return tables


def page(stage: str, kind: str) -> None:
    """The mode's pager: one line on stderr, the unit's journal, as main's display loop pages
    (tradingview/loop.py ``_page``). Neither the data-only entry nor main's ranking host has a
    transport, and no alert route reads this line yet."""
    print(f"ranking page {stage}: {kind}", file=sys.stderr, flush=True)


def build(
    args: RankingArguments,
    *,
    inputs: Callable[[Segment], SegmentInputs | None],
    factory: Any = AlpacaDataClientFactory,
    config: LiveNodeConfig | None = None,
    segment_of: Callable[[int], Segment | None] = lambda ts: segment_start(ts)[0],
) -> tuple[LiveNode, RankingActor]:
    config = node_config() if config is None else config
    refuse_order_paths(config)
    node = (
        LiveNodeBuilder.from_config(NODE_NAME, config)
        .add_data_client(CLIENT_NAME, factory, args.data)
        .build()
    )
    sessions: list[SegmentedHost] = []

    def host() -> SegmentedHost:  # on the node thread, in the Actor's on_start
        sessions.append(
            SegmentedHost(
                feed=args.data.feed,
                universe=args.universe,
                universe_source=args.universe_source,
                registry=args.registry,
                inputs=inputs,
                segment_of=segment_of,
                clock=actor.clock.timestamp_ns,
                receipt_dir=args.receipt_dir,
                evidence=actor.evidence,
            )
        )
        return sessions[-1]

    actor = RankingActor(
        RankingActorConfig(
            instrument_ids=tuple(InstrumentId(Symbol(name), VENUE) for name in args.universe),
            feed=args.data.feed,
            host_factory=host,
            priming=lambda: sessions[-1].actor_priming(),
            page_window_s=args.page_window_s,
            page=page,
            trade_facts=StreamFacts(args.data.feed),
            status_snapshot_window_s=args.status_snapshot_window_s,
            heartbeat_registry=args.registry,
        )
    )
    node.add_actor(actor)
    return node, actor


def run(
    args: RankingArguments,
    *,
    lease: MarketDataLease | None,
    inputs: Callable[[Segment], SegmentInputs | None],
    factory: Any = AlpacaDataClientFactory,
    config: LiveNodeConfig | None = None,
) -> Path:
    """Hold the lease, run for the duration, then dispose; receipts land per segment."""
    if lease is None:
        raise ValueError("the market-data lease is required: no lease, no start")
    with lease:
        node, _ = build(args, inputs=inputs, factory=factory, config=config)
        timer = threading.Timer(args.duration_s, node.handle().stop)
        timer.daemon = True
        try:
            timer.start()
            node.run()
        finally:
            timer.cancel()
            node.dispose()
    return args.receipt_dir


def main(argv: list[str] | None = None) -> Path:
    parse(argv)  # every argument and every input that has a producer is checked first
    raise RankingRefused("missing priming inputs: " + "; ".join(MISSING))


if __name__ == "__main__":
    main()
