"""N2b-2b: the node entry's ranking mode, its producer-only inputs and its refusal.

The live proof runs the real Alpaca data client over N1e's stand-in socket (rows through the
SDK's own ``_consume``) inside the mode's own data-only node.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest
from alpaca.data.enums import DataFeed
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.live import LiveNodeConfig
from nautilus_trader.live.clients import DataClientFactory
from nautilus_trader.model import Venue
from test_alpaca_data import ProofProvider
from test_alpaca_stream_facts import DROP, Stream
from test_ranking_inputs import Daily, staged

from sextant.alpaca.data import AlpacaDataClient
from sextant.data import ranking_inputs
from sextant.ranking import node_ranking
from sextant.ranking.baseline import BaselineSample, BaselineTable, dump_baseline
from sextant.ranking.engine import ReferencePrices, Segment
from sextant.ranking.node_session import SegmentInputs
from sextant.ranking.publisher import AssetState

ROOT = Path(__file__).parents[2]
REGISTRY = ROOT / "lanes/tradingview/k2-ranking.params.json"
NS = 1_000_000_000


def table(feed: str) -> BaselineTable:
    return BaselineTable(
        tuple(
            BaselineSample("AAPL", segment, "2026-11-09", offset, D(dollars), D(count))
            for segment in ("PRE", "RTH", "POST", "OVERNIGHT")
            for offset, dollars, count in ((0, 0, 0), (600, 100, 100))
        ),
        "fixture explicit complete curves",
        0,
        feed,
    )


def produced_files(tmp_path: Path) -> dict[str, Path]:
    """The shapes main's producers write: the K2 artifact and the baseline files + manifest."""
    artifact = tmp_path / "universe.json"
    artifact.write_text(json.dumps({"rows": [{"symbol": "AAPL"}]}))
    baselines = tmp_path / "baselines"
    baselines.mkdir()
    files = {}
    for name in node_ranking.SEGMENTS:
        text = dump_baseline(table("boats" if name == "overnight" else "sip"))
        (baselines / f"{name}.json").write_text(text)
        files[f"{name}.json"] = {"sha256": hashlib.sha256(text.encode()).hexdigest()}
    universe = {"path": str(artifact), "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}
    (baselines / "manifest.json").write_text(json.dumps({"files": files, "universe": universe}))
    inputs = tmp_path / "ranking-inputs"  # what sextant.data.ranking_inputs writes (N2b-3)
    ranking_inputs.produce(
        inputs,
        universe_artifact=artifact,
        listings_dir=staged(tmp_path),
        session=date(2026, 11, 11),
        daily=Daily({"AAPL": D("10.50")}),
    )
    return {"artifact": artifact, "baselines": baselines, "inputs": inputs}


def argv(tmp_path: Path, *drop: str) -> list[str]:
    files = produced_files(tmp_path)
    values = {
        "--universe-artifact": str(files["artifact"]),
        "--baseline-dir": str(files["baselines"]),
        "--ranking-inputs-dir": str(files["inputs"]),
        "--registry": str(REGISTRY),
        "--duration-s": "600",
        "--receipt-dir": str(tmp_path / "receipts"),
        "--page-window-s": "60",
        "--status-snapshot-window-s": "60",
        "--feed": "sip",
        "--api-key-env": "FIXTURE_KEY_NAME",
        "--api-secret-env": "FIXTURE_SECRET_NAME",
        "--lease-root": str(tmp_path / "locks"),
        "--paper-slot": "2",
        "--existing-streams": "0",
        "--lease-source": "fixture: no stream exists",
    }
    out: list[str] = []
    for flag, value in values.items():
        if flag not in drop:
            out += [flag, value]
    return out


def test_the_mode_refuses_without_verified_ranking_inputs(tmp_path) -> None:
    args = argv(tmp_path)
    (tmp_path / "ranking-inputs" / "manifest.json").unlink()  # no commit record
    with pytest.raises(node_ranking.RankingRefused, match="ranking inputs"):
        node_ranking.main(args)
    assert not (tmp_path / "locks").exists() and not (tmp_path / "receipts").exists()


def test_the_inputs_prime_pre_and_rth_of_their_session_only(tmp_path) -> None:
    args, _ = node_ranking.parse(argv(tmp_path))
    inputs = node_ranking.file_inputs(args)

    def segment(name: str, day: date) -> Segment:
        return Segment(name, day, 1_000 * NS, 2_000 * NS, "fixture")

    pre = inputs(segment("PRE", date(2026, 11, 11)))
    assert pre is not None and pre.references["AAPL"].prior_close == D("10.50")
    assert pre.references["AAPL"].known_at == args.inputs.known_at
    assert pre.assets["AAPL"].security_type == "common" and pre.assets["AAPL"].halted is None
    assert inputs(segment("RTH", date(2026, 11, 11))) is not None
    assert inputs(segment("POST", date(2026, 11, 11))) is None  # its close is not known yet
    assert inputs(segment("PRE", date(2026, 11, 12))) is None  # another session's inputs


def test_the_inputs_that_have_producers_are_loaded_and_checked(tmp_path) -> None:
    args, raw = node_ranking.parse(argv(tmp_path))
    assert args.universe == ("AAPL",) and set(args.baselines) == {"PRE", "RTH", "POST", "OVERNIGHT"}
    assert "sha256" in args.universe_source and "NOT PIT" in args.universe_source
    (tmp_path / "baselines" / "rth.json").write_text("{}")  # outside its manifest commit
    with pytest.raises(node_ranking.RankingRefused, match="baselines"):
        node_ranking.load_inputs(raw)


@pytest.mark.parametrize(
    "flag",
    [
        "--universe-artifact",
        "--baseline-dir",
        "--ranking-inputs-dir",
        "--registry",
        "--duration-s",
        "--receipt-dir",
        "--page-window-s",
        "--status-snapshot-window-s",
        "--feed",
        "--api-key-env",
        "--api-secret-env",
        "--lease-root",
        "--paper-slot",
        "--existing-streams",
        "--lease-source",
    ],
)
def test_every_argument_is_required(tmp_path, flag: str) -> None:
    with pytest.raises(SystemExit):
        node_ranking.parse(argv(tmp_path, flag))


def test_an_abbreviated_option_or_another_feed_is_refused(tmp_path) -> None:
    args = argv(tmp_path)
    with pytest.raises(SystemExit):
        node_ranking.parse([a.replace("--page-window-s", "--page-window") for a in args])
    args[args.index("--feed") + 1] = "iex"
    with pytest.raises(node_ranking.RankingRefused, match="sip"):
        node_ranking.parse(args)


def test_the_node_ranks_from_the_stream_and_writes_its_segment_receipt(tmp_path) -> None:
    args, _ = node_ranking.parse(argv(tmp_path))
    now = time.time_ns()
    started = Segment("PRE", args_session_date(now), now - 3600 * NS, now + 3600 * NS, "fixture")
    refs = ReferencePrices(D("10"), now - 7200 * NS, "fixture official close")
    asset = AssetState(now - 7200 * NS, started.end_ns, None, "common", "fixture vendor")
    stream = Stream([[(1, ["@"]), DROP], [(2, ["@"])]])

    def inputs(segment: Segment) -> SegmentInputs:
        return SegmentInputs(table("sip"), {"AAPL": refs}, {"AAPL": asset})

    class Factory(DataClientFactory):
        @staticmethod
        def create(*, name, config, cache, clock):
            return AlpacaDataClient(
                name=name,
                config=config,
                cache=cache,
                clock=clock,
                instrument_provider=ProofProvider(InstrumentProviderConfig(load_all=True)),
                stream=stream,
                feed=DataFeed.SIP,
                venue=Venue.from_str("ALPACA"),
            )

    async def drive() -> Any:
        node, actor = node_ranking.build(
            args,
            inputs=inputs,
            factory=Factory,
            config=LiveNodeConfig(delay_post_stop_secs=0),
            segment_of=lambda ts: started,
        )
        handle, task = node.handle(), asyncio.create_task(node.run_async())
        try:
            for _ in range(200):  # both trades and the gap between them
                await asyncio.sleep(0.05)
                if actor.stream_gaps == 1 and actor.evidence()["cleared_by_print"] == 2:
                    break
        finally:
            handle.stop()
            try:
                await asyncio.wait_for(task, timeout=10)
            finally:
                node.dispose()
        return actor

    actor = asyncio.run(drive())
    assert actor.stream_gaps == 1 and actor.errors == {}
    name = f"ranking-{started.session_date.isoformat()}-PRE.json"
    body = json.loads((tmp_path / "receipts" / name).read_text())
    assert body["observed"] is False and body["gaps"] == 1  # attached mid-segment, then a gap
    assert body["names_ranked"] == 0 and body["primed"] is True


def args_session_date(now: int):
    from datetime import UTC, datetime

    return datetime.fromtimestamp(now // NS, tz=UTC).date()
