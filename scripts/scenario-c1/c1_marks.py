"""C1 measurements from the pulled tape: control marks, MAE/MFE, post-exit marks, nets.

Reads only the local catalog; no network, no broker. Numbers are Decimal strings.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time as daytime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader.persistence import ParquetDataCatalog

from sextant.data.alpaca_history import NY, nanos

ROOT = Path.home() / "sextant-data" / "c1-scenario"
CATALOG = ROOT / "catalog"
CASES: dict[str, dict[str, Any]] = {
    "a": {
        "symbol": "PARA",
        "entry": date(2026, 11, 3),
        "flat": datetime(2026, 11, 3, 15, 55, tzinfo=NY),
        "mark": datetime(2026, 11, 4, 15, 55, tzinfo=NY),
    },
    "b": {
        "symbol": "PARA",
        "entry": date(2026, 10, 27),
        "flat": datetime(2026, 10, 27, 15, 55, tzinfo=NY),
        "mark": datetime(2026, 10, 27, 15, 55, tzinfo=NY),
    },
    "c": {
        "symbol": "SPCX",
        "entry": date(2026, 10, 21),
        "flat": datetime(2026, 10, 21, 15, 55, tzinfo=NY),
        "mark": datetime(2026, 10, 22, 15, 55, tzinfo=NY),
    },
}
NS = 1_000_000_000


def bid_at(quotes, when_ns: int) -> tuple[str, int] | None:
    best = None
    for q in quotes:
        if q.ts_event <= when_ns:
            best = q
        else:
            break
    if best is None:
        return None
    return str(best.bid_price), best.ts_event


def main() -> int:
    catalog = ParquetDataCatalog(str(CATALOG.resolve()))
    out: dict[str, Any] = {}
    for name, case in CASES.items():
        symbol = case["symbol"]
        iid = f"{symbol}.ALPACA"
        opened = nanos(datetime.combine(case["entry"], daytime(9, 30), tzinfo=NY))
        end = nanos(case["mark"] + timedelta(hours=1))
        quotes = catalog.query_quote_ticks(identifiers=[iid], start=opened - 60 * NS, end=end)
        trades = catalog.query_trade_ticks(identifiers=[iid], start=opened - 60 * NS, end=end)
        quotes.sort(key=lambda q: q.ts_event)
        trades.sort(key=lambda t: t.ts_event)
        run = json.loads((ROOT / "run" / name / "exit.json").read_text())
        events = run.get("events", [])
        entry = next((e for e in events if e.get("event") == "entry_fill"), None)
        exit_ = next((e for e in events if e.get("event") == "sell_fill"), None)
        entry_px = Decimal(entry["price"]) if entry else None
        entry_ns = int(entry["ts"]) if entry else opened
        exit_px = Decimal(exit_["price"]) if exit_ else None
        exit_ns = int(exit_["ts"]) if exit_ else None
        window_end = nanos(case["mark"])
        held_trades = [t for t in trades if entry_ns <= t.ts_event <= (exit_ns or window_end)]
        held_high = max((t.price.as_decimal() for t in held_trades), default=None)
        held_low = min((t.price.as_decimal() for t in held_trades), default=None)
        flat = bid_at(quotes, nanos(case["flat"]))
        mark = bid_at(quotes, nanos(case["mark"]))
        # Post-exit marks: the bid 30 minutes after the managed exit, and at the window mark.
        post = None
        if exit_ns is not None:
            post = bid_at(quotes, exit_ns + 30 * 60 * NS)
        rec = {
            "symbol": symbol,
            "entry_px": str(entry_px),
            "entry_ns": entry_ns,
            "exit_px": str(exit_px) if exit_px is not None else None,
            "exit_ns": exit_ns,
            "held_high": str(held_high) if held_high is not None else None,
            "held_low": str(held_low) if held_low is not None else None,
            "hold1555_bid": flat[0] if flat else None,
            "hold1555_ns": flat[1] if flat else None,
            "holdflat_bid": mark[0] if mark else None,
            "holdflat_ns": mark[1] if mark else None,
            "post_exit_30m_bid": post[0] if post else None,
        }
        out[name] = rec
    path = ROOT / "run" / "marks.json"
    path.write_text(json.dumps(out, indent=2, sort_keys=True))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
