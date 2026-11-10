"""One tracked recipe for C's four per-segment baseline files.

A single run fetches the overnight table from the boats feed and the daytime
table from sip through the reviewed fetchers in :mod:`sextant.data.baseline_bars`,
splits them into one segment per file, verifies that every file carries the
baseline schema and all requested symbols, and publishes the four files before a
``manifest.json`` that records the command, ``as_of``, symbol list, window, feeds
and each file's sha256. The manifest is written last: a reader treats it as the
commit record and checks the digests before using the files.

``--universe`` takes the K2 ranked universe artifact written by
``python -m sextant.paper.c_universe --out PATH``; this recipe never re-ranks.
Only :func:`main` reads the environment or builds a client.

Symbols are bare vendor tickers: a venue-qualified instrument ID such as
``AAPL.ALPACA`` is refused before any request. A segment that is zero across
its whole window, or thinner than the schema floor, is named under
``zero_filled`` or ``sparse`` in the manifest and the run exits non-zero
instead of publishing an unremarkable zero-filled baseline.

Upstream: alpacahq/alpaca-py@v0.44.0 ``alpaca/data/requests.py:StockBarsRequest``
and ``alpaca/data/client.py:get_stock_bars``, called as ``baseline_bars`` does.
"""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, cast

from sextant.data.alpaca_history import environment_credentials, symbol_name
from sextant.data.baseline_bars import (
    BarsClient,
    fetch_baseline,
    fetch_overnight_baseline,
    prior_xnys_sessions,
)
from sextant.ranking.baseline import BaselineTable, dump_baseline, load_baseline, segment_start

RECIPE_SEGMENTS = ("OVERNIGHT", "PRE", "RTH", "POST")
SEGMENT_FILES = {
    "OVERNIGHT": "overnight.json",
    "PRE": "pre.json",
    "RTH": "rth.json",
    "POST": "post.json",
}
FEEDS = {"OVERNIGHT": "boats", "PRE": "sip", "RTH": "sip", "POST": "sip"}
MANIFEST_NAME = "manifest.json"
MIN_SAMPLES_PER_SESSION = 2  # the schema's start and end sample for one session


def _symbols(symbols: Iterable[str]) -> tuple[str, ...]:
    names: list[str] = []
    for symbol in symbols:
        if symbol.endswith(".ALPACA"):
            raise ValueError(
                "baseline symbols are bare vendor tickers, not instrument IDs: "
                f"{symbol} (pass {symbol.removesuffix('.ALPACA')})"
            )
        names.append(symbol_name(symbol))
    if not names:
        raise ValueError("at least one symbol is required")
    return tuple(dict.fromkeys(names))


def segment_table(table: BaselineTable, name: str) -> BaselineTable:
    """One segment's samples, keeping the source, known_at and feed."""
    samples = tuple(sample for sample in table.samples if sample.segment == name)
    if not samples:
        raise ValueError(f"the {name} baseline holds no samples")
    return BaselineTable(samples, table.provenance, table.known_at, table.feed)


def build(
    client: BarsClient,
    symbols: Sequence[str],
    *,
    as_of: date,
    known_at: int,
    prior_sessions: int = 20,
) -> dict[str, BaselineTable]:
    """Fetch both feeds once and split the results into one table per segment."""
    names = _symbols(symbols)
    overnight = fetch_overnight_baseline(
        client, names, as_of=as_of, known_at=known_at, prior_sessions=prior_sessions
    )
    daytime = fetch_baseline(
        client, names, as_of=as_of, known_at=known_at, feed="sip", prior_sessions=prior_sessions
    )
    tables = {"OVERNIGHT": segment_table(overnight, "OVERNIGHT")}
    for name in ("PRE", "RTH", "POST"):
        tables[name] = segment_table(daytime, name)
    return tables


def verify(tables: Mapping[str, BaselineTable], symbols: Sequence[str]) -> None:
    """Refuse a file set that is not one segment over exactly the requested symbols."""
    expected = frozenset(_symbols(symbols))
    for name in RECIPE_SEGMENTS:
        table = tables.get(name)
        if table is None:
            raise ValueError(f"the {name} baseline is missing")
        segments = {sample.segment for sample in table.samples}
        if segments != {name}:
            raise ValueError(f"the {name} baseline must hold one segment, found {sorted(segments)}")
        covered = {sample.symbol for sample in table.samples}
        if covered != expected:
            raise ValueError(f"the {name} baseline does not cover {sorted(expected - covered)}")
        feed = FEEDS[name]
        if table.feed != feed:
            raise ValueError(f"the {name} baseline must use the {feed} feed, found {table.feed}")


def render(tables: Mapping[str, BaselineTable]) -> dict[str, str]:
    """Each segment as baseline JSON, proven to load back to the same identity."""
    texts: dict[str, str] = {}
    for name in RECIPE_SEGMENTS:
        table = tables.get(name)
        if table is None:
            raise ValueError(f"the {name} baseline is missing")
        text = dump_baseline(table) + "\n"
        if load_baseline(text).identity != table.identity:
            raise ValueError(f"the {name} baseline does not round-trip through its schema")
        texts[SEGMENT_FILES[name]] = text
    return texts


def survey(
    tables: Mapping[str, BaselineTable],
    symbols: Sequence[str],
    sessions: Sequence[date],
) -> dict[str, dict[str, list[str]]]:
    """Name each segment file that is zero-filled or thinner than the schema floor.

    The fetchers keep their empty-response semantics: a quiet window is a
    complete window. This recipe still has to say so out loud, because a table
    whose samples are all zero is indistinguishable from a missing baseline and
    must never arm a slot silently.
    """
    expected = [session.isoformat() for session in sessions]
    flags: dict[str, dict[str, list[str]]] = {"zero_filled": {}, "sparse": {}}
    for name in RECIPE_SEGMENTS:
        table = tables[name]
        zero: list[str] = []
        sparse: list[str] = []
        for symbol in symbols:
            samples = [sample for sample in table.samples if sample.symbol == symbol]
            present = {sample.session for sample in samples}
            if len(samples) < MIN_SAMPLES_PER_SESSION * len(expected):
                sparse.append(symbol)
            elif set(expected) - present:
                sparse.append(symbol)
            if samples and all(
                sample.dollar_volume == 0 and sample.trade_count == 0 for sample in samples
            ):
                zero.append(symbol)
        if zero:
            flags["zero_filled"][name] = zero
        if sparse:
            flags["sparse"][name] = sparse
    return flags


def publish(
    out: Path,
    tables: Mapping[str, BaselineTable],
    *,
    command: Sequence[str],
    as_of: date,
    symbols: Sequence[str],
    sessions: Sequence[date],
    known_at: int,
    prior_sessions: int,
    source: str,
    universe: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Verify, then publish the four files and the manifest into ``out``."""
    names = _symbols(symbols)
    if not sessions:
        raise ValueError("at least one prior session is required")
    verify(tables, names)
    texts = render(tables)
    flags = survey(tables, names, sessions)
    manifest: dict[str, Any] = {
        "command": list(command),
        "as_of": as_of.isoformat(),
        "known_at": known_at,
        "symbols": list(names),
        "window": {
            "prior_sessions": prior_sessions,
            "first_session": sessions[0].isoformat(),
            "last_session": sessions[-1].isoformat(),
        },
        "source": source,
        "universe": dict(universe) if universe is not None else None,
        "zero_filled": flags["zero_filled"],
        "sparse": flags["sparse"],
        "files": {},
    }
    out.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".baseline-", dir=out))
    try:
        for name in RECIPE_SEGMENTS:
            filename = SEGMENT_FILES[name]
            staged = staging / filename
            staged.write_text(texts[filename], encoding="utf-8")
            manifest["files"][filename] = {
                "segment": name,
                "feed": tables[name].feed,
                "sha256": hashlib.sha256(staged.read_bytes()).hexdigest(),
                "samples": len(tables[name].samples),
                "symbols": sorted({sample.symbol for sample in tables[name].samples}),
            }
            staged.replace(out / filename)
        staged_manifest = staging / MANIFEST_NAME
        staged_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        staged_manifest.replace(out / MANIFEST_NAME)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return manifest


def run(
    client: BarsClient,
    symbols: Sequence[str],
    out: Path,
    *,
    command: Sequence[str],
    as_of: date,
    known_at: int,
    prior_sessions: int = 20,
    source: str = "symbols",
    universe: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build and publish one complete baseline set; any refusal leaves no output."""
    names = _symbols(symbols)
    sessions = prior_xnys_sessions(as_of, prior_sessions)
    tables = build(client, names, as_of=as_of, known_at=known_at, prior_sessions=prior_sessions)
    return publish(
        out,
        tables,
        command=command,
        as_of=as_of,
        symbols=names,
        sessions=sessions,
        known_at=known_at,
        prior_sessions=prior_sessions,
        source=source,
        universe=universe,
    )


def resolve_universe(path: Path) -> tuple[str, ...]:
    """The symbols the K2 scanner ranked, in the artifact's order; never re-ranked."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"the K2 universe artifact at {path} carries no rows")
    symbols: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("symbol"), str):
            raise ValueError("the K2 universe artifact rows must name a symbol")
        symbols.append(row["symbol"])
    return _symbols(symbols)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m sextant.data.baseline_recipe",
        description="Build C's four per-segment baseline files and their manifest in one run.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        metavar="DIR",
        help="directory receiving the four files and manifest.json",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--symbols", nargs="+", metavar="SYMBOL", help="explicit vendor symbols")
    source.add_argument(
        "--universe",
        type=Path,
        metavar="PATH",
        help="K2 ranked universe artifact from python -m sextant.paper.c_universe",
    )
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="session day whose prior sessions are baselined; default the current segment's date",
    )
    parser.add_argument(
        "--prior-sessions",
        type=int,
        default=20,
        metavar="N",
        help="prior XNYS sessions to baseline (default 20)",
    )
    return parser


def _default_client() -> BarsClient:
    from alpaca.data.historical import StockHistoricalDataClient

    api_key, secret_key = environment_credentials()
    # raw_data=True returns the flat {symbol: [bar, ...]} mapping the fetchers read.
    # alpaca-py names the parameter request_params; the fetchers call positionally.
    return cast(
        BarsClient,
        StockHistoricalDataClient(api_key=api_key, secret_key=secret_key, raw_data=True),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[[], BarsClient] | None = None,
    now_ns: Callable[[], int] = time.time_ns,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    args = parser.parse_args(arguments)
    command = ["python", "-m", "sextant.data.baseline_recipe", *arguments]
    moment = now_ns()
    symbols: tuple[str, ...]
    universe: dict[str, str] | None
    if args.symbols is not None:
        symbols = _symbols(part for value in args.symbols for part in value.split(","))
        source, universe = "symbols", None
    elif args.universe is not None:
        symbols = resolve_universe(args.universe)
        source = "k2_universe"
        universe = {
            "path": str(args.universe),
            "sha256": hashlib.sha256(args.universe.read_bytes()).hexdigest(),
        }
    else:
        parser.error("one of --symbols or --universe is required")
    as_of = args.as_of if args.as_of is not None else segment_start(moment)[1]
    factory = client_factory if client_factory is not None else _default_client
    manifest = run(
        factory(),
        symbols,
        args.out,
        command=command,
        as_of=as_of,
        known_at=moment,
        prior_sessions=args.prior_sessions,
        source=source,
        universe=universe,
    )
    print(f"wrote {len(manifest['files'])} baselines and {args.out / MANIFEST_NAME}", flush=True)
    flags = {key: manifest[key] for key in ("zero_filled", "sparse") if manifest[key]}
    if flags:
        print(
            f"warning: baseline flags {json.dumps(flags, sort_keys=True)}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
