"""Morning baseline refresh and raw calibration inputs; no orders or width adoption.

Reuse AlpacaHistory's response capture/pacing and alpaca-py's complete pagination.
Source: alpaca-py@cc4cb3b7ba50ae250e621983c2779047fb16bb28,
 alpaca/data/historical/stock.py:get_stock_quotes/get_stock_bars.
"""

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from datetime import time as daytime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq
from alpaca.common.enums import Sort
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.requests import StockBarsRequest, StockQuotesRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from sextant.data.alpaca_history import (
    AlpacaHistory,
    _land_pages,
    nanos,
    publish_once,
    timestamp,
)
from sextant.data.baseline_bars import BarsClient, prior_xnys_sessions
from sextant.data.baseline_recipe import MANIFEST_NAME, coverage_line, load_universe, run
from sextant.paper.sessions import ET
from sextant.ranking.baseline import segment_start


def window(day: date, feed: str) -> tuple[datetime, datetime]:
    """Inclusive microsecond bounds, matching the existing history fetcher."""
    if feed == "boats":
        start = datetime.combine(day - timedelta(days=1), daytime(20), ET)
        stop = datetime.combine(day, daytime(4), ET)
    elif feed == "sip":
        start = datetime.combine(day, daytime(4), ET)
        stop = datetime.combine(day, daytime(20), ET)
    else:
        raise ValueError("calibration feed must be sip or boats")
    return start, stop - timedelta(microseconds=1)


class CalibrationHistory(AlpacaHistory):
    """Only request construction is new; upstream owns all HTTP and pagination."""

    def fetch_window(self, symbol: str, day: date, kind: str, feed: str) -> tuple[str, ...]:
        start, end = window(day, feed)
        fields: dict[str, Any] = dict(
            symbol_or_symbols=symbol,
            start=start,
            end=end,
            feed=DataFeed(feed),
            sort=Sort.ASC,
            asof=day.isoformat(),
        )
        self.pages = []
        if kind == "quotes":
            self.get_stock_quotes(StockQuotesRequest(**fields))
        elif kind == "bars":
            self.get_stock_bars(
                StockBarsRequest(
                    **fields,
                    timeframe=TimeFrame(1, TimeFrameUnit("Min")),
                    adjustment=Adjustment.RAW,
                )
            )
        else:
            raise ValueError("calibration kind must be quotes or bars")
        return tuple(self.pages)


def parameters(path: Path) -> tuple[int, Decimal, str]:
    raw = path.read_bytes()
    rows = json.loads(raw)["rows"]
    for name in ("prior_sessions", "calls_per_minute", "on_calendar"):
        row = rows.get(name, {})
        if not row.get("source") or row.get("status") != "UNCALIBRATED" or "value" not in row:
            raise ValueError(f"{name} requires registry authority and status")
    count = rows["prior_sessions"]["value"]
    if type(count) is not int or count <= 0:
        raise ValueError("prior_sessions must be a positive integer")
    rate = Decimal(str(rows["calls_per_minute"]["value"]))
    if not rate.is_finite() or not 0 < rate <= 10000:
        raise ValueError("calls_per_minute must be positive and at most 10000")
    return count, rate, hashlib.sha256(raw).hexdigest()


def _rows(text: str, symbol: str, kind: str, start: datetime, end: datetime) -> int:
    payload = json.loads(text, parse_float=Decimal)
    if not isinstance(payload, dict) or "next_page_token" not in payload:
        raise ValueError("history response lacks a continuation receipt")
    if kind not in payload:
        raise ValueError("history response lacks its requested payload kind")
    values = payload[kind]
    if values is None:
        values = {}
    if not isinstance(values, dict) or set(values) - {symbol}:
        raise ValueError("history response has unexpected symbols or shape")
    rows = values.get(symbol, [])
    if not isinstance(rows, list):
        raise ValueError("history rows must be a list")
    required = {"t", "bp", "ap", "bs", "as"} if kind == "quotes" else {"t", "o", "h", "l", "c", "v"}
    for row in rows:
        if not isinstance(row, dict) or not required <= row.keys():
            raise ValueError("history row lacks source fields")
        if not start <= timestamp(row["t"]) <= end:
            raise ValueError("history row escaped its requested window")
    return len(rows)


def _complete(pages: Sequence[str]) -> None:
    if not pages:
        raise ValueError("history response is incomplete")
    seen: set[str] = set()
    for index, text in enumerate(pages):
        payload = json.loads(text)
        if not isinstance(payload, dict) or "next_page_token" not in payload:
            raise ValueError("history response lacks a continuation receipt")
        token = payload["next_page_token"]
        if index == len(pages) - 1:
            if token is not None:
                raise ValueError("history response is incomplete")
        elif not isinstance(token, str) or not token:
            raise ValueError("history response has a broken continuation chain")
        elif token in seen:
            raise ValueError("history response has a repeated continuation token")
        else:
            seen.add(token)


def archive(
    client: CalibrationHistory,
    root: Path,
    symbol: str,
    day: date,
    kind: str,
    feed: str,
    known_at: int,
    *,
    now_ns: Callable[[], int] = time.time_ns,
) -> dict[str, Any]:
    start, end = window(day, feed)
    path = root / "calibration" / feed / kind / symbol / f"{day.isoformat()}.parquet"
    metadata = {
        "source": "alpaca",
        "feed": feed,
        "kind": kind,
        "symbol": symbol,
        "session": day.isoformat(),
        "asof": day.isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "adjustment": "raw" if kind == "bars" else "none",
        "interval": "1Min" if kind == "bars" else "tick",
    }
    if not path.exists():
        pages = client.fetch_window(symbol, day, kind, feed)
        _complete(pages)
        _land_pages(
            path,
            pages,
            metadata={**metadata, "known_at": str(now_ns()), "run_started_ns": str(known_at)},
            validate=lambda text: _rows(text, symbol, kind, start, end),
        )
    table = pq.read_table(path)
    saved = table.schema.metadata or {}
    if any(saved.get(key.encode()) != value.encode() for key, value in metadata.items()):
        raise ValueError("history partition has conflicting provenance")
    pages = table["response_json"].to_pylist()
    _complete(pages)
    count = sum(_rows(text, symbol, kind, start, end) for text in pages)
    return {
        "path": str(path.relative_to(root)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        **metadata,
        "known_at": int(saved[b"known_at"]),
        "pages": len(pages),
        "rows": count,
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[[], CalibrationHistory] | None = None,
    now_ns: Callable[[], int] = time.time_ns,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--parameters", type=Path, required=True)
    args = parser.parse_args(argv)
    arguments = list(sys.argv[1:] if argv is None else argv)
    count, rate, parameters_sha256 = parameters(args.parameters)
    symbols, universe = load_universe(args.universe)
    moment = now_ns()
    day = datetime.fromtimestamp(moment // 1_000_000_000, ET).date()
    # Calendar authority is the same XNYS segment resolver as the baseline recipe.
    segment, _, _ = segment_start(nanos(datetime.combine(day, daytime(4), ET)))
    if segment is None:
        print("calibration-data: closed XNYS session; skipped")
        return 0
    sessions = prior_xnys_sessions(day, count)
    client = client_factory() if client_factory else CalibrationHistory(rate)
    try:
        baseline = run(
            cast(BarsClient, client),
            symbols,
            args.data_dir / "baselines",
            command=["python", "-m", "sextant.data.calibration_job", *arguments],
            as_of=day,
            known_at=moment,
            prior_sessions=count,
            source="k2_universe",
            universe=universe,
        )
        manifest = args.data_dir / "baselines" / MANIFEST_NAME
        baseline_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
        print(f"calibration-data: {coverage_line(baseline)}", flush=True)
        files = [
            archive(client, args.data_dir, symbol, session, kind, feed, moment, now_ns=now_ns)
            for session in sessions
            for symbol in symbols
            for feed in ("sip", "boats")
            for kind in ("quotes", "bars")
        ]
        # An empty window is a fact about the symbol, not a failed read: each one is
        # a validated, fully paged zero-row partition, counted here per feed and kind.
        empty: dict[str, int] = {}
        for record in files:
            if record["rows"] == 0:
                key = f"{record['feed']}/{record['kind']}"
                empty[key] = empty.get(key, 0) + 1
        receipt = {
            "schema": "sextant.calibration-inputs/1",
            "status": "UNCALIBRATED",
            "as_of": day.isoformat(),
            "known_at": now_ns(),
            "run_started_ns": moment,
            "symbols": list(symbols),
            "universe": universe,
            "sessions": [value.isoformat() for value in sessions],
            "parameters_sha256": parameters_sha256,
            "prior_sessions": count,
            "calls_per_minute": str(rate),
            "baseline": baseline,
            "baseline_manifest_sha256": baseline_sha256,
            "files": files,
            "empty_windows": dict(sorted(empty.items())),
            "coverage": "vendor responses only; empty windows are not calibration evidence",
            "survivor_only": True,
            "pit_verified": False,
        }
        path = args.data_dir / "calibration/runs" / f"{day.isoformat()}-{moment}.json"
        publish_once(path, lambda target: target.write_text(json.dumps(receipt, indent=2) + "\n"))
        print(f"calibration-data: {len(files)} partitions; UNCALIBRATED")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
