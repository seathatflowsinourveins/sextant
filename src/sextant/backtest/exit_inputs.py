"""#41's input pin and catalog writer, kept on main for the recorded-bar replay.

The study's driver and its proofs live on ``research/exit-study-5fe0977`` at the
annotated tag ``exit-study-2026-11-10`` (row 46). The recorded-bar replay in
``src/sextant/backtest/replay.py`` still needs these pieces, so they stay here
byte-for-byte from the driver: the write-up's input hashes, the verifier that
refuses a changed byte, and the Nautilus ParquetDataCatalog writer (v2.0.0rc7
``55c0e820``). The upstream pin and the exact source path are row 48's
docs/manifest.md entry.

What this module adds, and nothing else: the input pin, its verifier and the
catalog writer. The catalog carries one Equity and one 1-minute EXTERNAL bar
series per symbol, stamped at bar close; ``Bar`` has no VWAP, so a reader joins
``vw`` from the same hash-checked file. The study's own replay, trial rows and
tables stay on the ref.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader.model import (
    Bar,
    BarType,
    Currency,
    Equity,
    InstrumentId,
    Price,
    Quantity,
    Symbol,
)
from nautilus_trader.persistence import ParquetDataCatalog

BARS, FILLS, OWNER = (
    "minute-bars-2026-10-26_29.jsonl",
    "fills-2026-10-26_29.jsonl",
    "b-owner-first-orders.json",
)
INPUTS = {  # the write-up's own table, docs/research/2026-10-29-b-exit-replay.md lines 23-25
    BARS: "105caeee0645455aa0e1de23a1720639347062061944ea3d49eedb6d99a86a69",
    FILLS: "55eee2b64506c19e23d4c421c803be687daf06ebb39a2b84f621ea2a90618c0f",
    OWNER: "5e95de9eaefd9e24cfbd96850ab499fdfa6505e83dcf205ca485584ad5d9e6d3",
}
DEFAULT_INPUTS = Path.home() / "sextant-data" / "exit-study-41"
VENUE = "ALPACA"
PRICE_PRECISION, SIZE_PRECISION = 4, 1
MINUTE_NS = 60 * 1_000_000_000


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inputs(folder: Path) -> dict[str, str]:
    found = {name: sha256(folder / name) for name in INPUTS}
    if found != INPUTS:
        raise ValueError(f"inputs differ from the study's recorded SHA-256: {found}")
    return found


def _rows(bars_path: Path) -> list[dict[str, Any]]:
    with bars_path.open() as stream:
        return [json.loads(line, parse_float=Decimal) for line in stream if line.strip()]


def _open_ns(text: str) -> int:
    return int(datetime.fromisoformat(text).timestamp()) * 1_000_000_000


def _text(value: object, places: int) -> str:
    """Exact text at the instrument's precision; refuses a value that would need rounding."""
    exact = Decimal(str(value))
    text = f"{exact:.{places}f}"
    if Decimal(text) != exact:
        raise ValueError(f"{value} does not fit {places} decimals")
    return text


def write_catalog(bars_path: Path, root: Path) -> ParquetDataCatalog:
    """One Equity and one 1-minute EXTERNAL bar series per symbol, stamped at bar close."""
    root.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(root))
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows(bars_path):
        by_symbol[row["symbol"]].append(row)
    for symbol, rows in sorted(by_symbol.items()):
        instrument_id = InstrumentId.from_str(f"{symbol}.{VENUE}")
        catalog.write_instruments(
            [
                Equity(
                    instrument_id,
                    Symbol(symbol),
                    Currency.from_str("USD"),
                    PRICE_PRECISION,
                    Price.from_str("0.0001"),
                    0,
                    0,
                )
            ]
        )
        bar_type = BarType.from_str(f"{symbol}.{VENUE}-1-MINUTE-LAST-EXTERNAL")
        bars = []
        for row in sorted(rows, key=lambda r: r["t"]):
            close_ns = _open_ns(row["t"]) + MINUTE_NS
            o, h, low, c = (_text(row[k], PRICE_PRECISION) for k in "ohlc")
            bars.append(
                Bar(
                    bar_type,
                    Price.from_str(o),
                    Price.from_str(h),
                    Price.from_str(low),
                    Price.from_str(c),
                    Quantity.from_str(_text(row["v"], SIZE_PRECISION)),
                    close_ns,
                    close_ns,
                )
            )
        catalog.write_bars(bars)
    return catalog
