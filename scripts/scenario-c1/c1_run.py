"""C1 step 4: native Nautilus simulated fills on the pulled SIP catalog, no broker, no live.

The managed arm is the production `ExitEngine` (#214 + PR2) with a witness entry: one share,
market buy at the first quote at or after 09:30:00 ET on the entry session. Controls are marked
from the same tape (bid) at their documented exit times. Nothing here writes the ledger.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time as daytime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType,
    BarType,
    Currency,
    InstrumentId,
    Money,
    OmsType,
    OrderSide,
    Quantity,
    TimeInForce,
    Venue,
)
from nautilus_trader.persistence import ParquetDataCatalog
from nautilus_trader.trading import Strategy, StrategyConfig

from sextant.data.alpaca_history import NY, nanos
from sextant.exits.engine import ExitEngine, ExitEngineConfig
from sextant.exits.policy import ExitParams

ROOT = Path.home() / "sextant-data" / "c1-scenario"
CATALOG = ROOT / "catalog"
RUN = ROOT / "run"
NS = 1_000_000_000
QD = Decimal("0.0001")

CASES: dict[str, dict[str, Any]] = {
    "a": {
        "symbol": "PARA",
        "entry_day": date(2026, 11, 3),
        "start": datetime(2026, 11, 3, 4, 0, tzinfo=NY),
        "end": datetime(2026, 11, 4, 20, 0, tzinfo=NY),
        "flat": datetime(2026, 11, 3, 15, 55, tzinfo=NY),
        "mark": datetime(2026, 11, 4, 15, 55, tzinfo=NY),
    },
    "b": {
        "symbol": "PARA",
        "entry_day": date(2026, 10, 27),
        "start": datetime(2026, 10, 27, 4, 0, tzinfo=NY),
        "end": datetime(2026, 10, 27, 20, 0, tzinfo=NY),
        "flat": datetime(2026, 10, 27, 15, 55, tzinfo=NY),
        "mark": datetime(2026, 10, 27, 15, 55, tzinfo=NY),
    },
    "c": {
        "symbol": "SPCX",
        "entry_day": date(2026, 10, 21),
        "start": datetime(2026, 10, 21, 4, 0, tzinfo=NY),
        "end": datetime(2026, 10, 22, 20, 0, tzinfo=NY),
        "flat": datetime(2026, 10, 21, 15, 55, tzinfo=NY),
        "mark": datetime(2026, 10, 22, 15, 55, tzinfo=NY),
    },
}


def ns(value: datetime) -> int:
    return nanos(value)


def case_meta(name: str) -> dict[str, Any]:
    case = dict(CASES[name])
    opened = datetime.combine(case["entry_day"], daytime(9, 30), tzinfo=NY)
    case["entry_ns"] = ns(opened)
    case["flat_ns"] = ns(case["flat"])
    case["mark_ns"] = ns(case["mark"])
    case["start_ns"] = ns(case["start"])
    case["end_ns"] = ns(case["end"])
    return case


class C1Exit(ExitEngine):
    """Production exit policy on a witness entry; nothing else is added."""

    def arm(self, *, entry_ns: int, qty: int) -> None:
        self.entry_ns = entry_ns
        self.qty = qty
        self.entered = False

    def on_quote(self, quote) -> None:
        if quote.instrument_id != self.instrument_id:
            return
        if not self.entered and quote.ts_event >= self.entry_ns:
            self.entered = True
            order = self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=OrderSide.BUY,
                quantity=Quantity.from_int(self.qty),
                time_in_force=TimeInForce.GTC,
            )
            self.entry_order_id = order.client_order_id
            self.submit_order(order)
            self._record(quote.ts_event, "witness_entry_submitted")
        super().on_quote(quote)


class FlatControl(Strategy):
    """Buy at the witness time; sell (market) at `flat_ns`, or hold when it is None."""

    def arm(self, *, instrument_id, entry_ns: int, flat_ns: int | None, qty: int = 1) -> None:
        self.instrument_id = instrument_id
        self.entry_ns = entry_ns
        self.flat_ns = flat_ns
        self.qty = qty
        self.entered = self.exited = False
        self.entry_px: str | None = None
        self.exit_px: str | None = None
        self.entry_ts: int | None = None
        self.exit_ts: int | None = None

    def on_start(self) -> None:
        self.subscribe_quotes(self.instrument_id)

    def on_quote(self, quote) -> None:
        if quote.instrument_id != self.instrument_id:
            return
        if not self.entered and quote.ts_event >= self.entry_ns:
            self.entered = True
            self.entry_ts = quote.ts_event
            self.submit_order(
                self.order_factory.market(
                    instrument_id=self.instrument_id,
                    order_side=OrderSide.BUY,
                    quantity=Quantity.from_int(self.qty),
                    time_in_force=TimeInForce.GTC,
                )
            )
        if self.flat_ns is not None and not self.exited and quote.ts_event >= self.flat_ns:
            self.exited = True
            self.exit_ts = quote.ts_event
            self.submit_order(
                self.order_factory.market(
                    instrument_id=self.instrument_id,
                    order_side=OrderSide.SELL,
                    quantity=Quantity.from_int(self.qty),
                    time_in_force=TimeInForce.GTC,
                )
            )

    def on_order_filled(self, event) -> None:
        if event.instrument_id != self.instrument_id:
            return
        if event.order_side == OrderSide.BUY:
            # first buy fill only
            if self.entry_px is None:
                self.entry_px = str(event.last_px)
                self.entry_ts = event.ts_event
        else:
            self.exit_px = str(event.last_px)
            self.exit_ts = event.ts_event


def build_engine() -> BacktestEngine:
    engine = BacktestEngine(BacktestEngineConfig(bypass_logging=True, run_analysis=False))
    engine.add_venue(
        venue=Venue("ALPACA"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=Currency.from_str("USD"),
        starting_balances=[Money.from_str("1000000 USD")],
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
        use_reduce_only=True,
        liquidity_consumption=True,
        bar_execution=True,
    )
    return engine


def load(catalog: ParquetDataCatalog, symbol: str, start_ns: int, end_ns: int):
    iid = f"{symbol}.ALPACA"
    quotes = catalog.query_quote_ticks(identifiers=[iid], start=start_ns, end=end_ns)
    trades = catalog.query_trade_ticks(identifiers=[iid], start=start_ns, end=end_ns)
    bar_type = f"{iid}-1-MINUTE-LAST-EXTERNAL"
    bars = catalog.query_bars(identifiers=[bar_type], start=start_ns, end=end_ns)
    quotes.sort(key=lambda x: x.ts_init)
    trades.sort(key=lambda x: x.ts_init)
    bars.sort(key=lambda x: x.ts_init)
    return quotes, trades, bars, bar_type


def run_engine(case: dict[str, Any], *, mode: str, catalog: ParquetDataCatalog) -> dict[str, Any]:
    symbol = case["symbol"]
    iid = InstrumentId.from_str(f"{symbol}.ALPACA")
    quotes, trades, bars, bar_type = load(catalog, symbol, case["start_ns"], case["end_ns"])
    engine = build_engine()
    try:
        instrument = catalog.instruments(instrument_ids=[f"{symbol}.ALPACA"])[0]
        engine.add_instrument(instrument)
        engine.add_data(quotes)
        engine.add_data(trades)
        engine.add_data(bars)
        out: dict[str, Any] = {"case": case["name"], "mode": mode, "symbol": symbol}
        if mode == "exit":
            strategy = C1Exit(
                ExitEngineConfig(
                    instrument_id=iid,
                    params=ExitParams.starts(),
                    round_trip_cost=instrument.price_increment.as_decimal(),
                    session="rth",
                    arm_bar_type=bar_type,
                )
            )
            strategy.arm(entry_ns=case["entry_ns"], qty=1)
        else:
            flat_ns = case["flat_ns"] if mode == "hold1555" else case["mark_ns"]
            strategy = FlatControl(StrategyConfig())
            strategy.arm(
                instrument_id=iid, entry_ns=case["entry_ns"], flat_ns=flat_ns, qty=1
            )
        engine.add_strategy(strategy)
        engine.run()
        cache = engine.cache
        fills = cache.fills(instrument_id=iid) if hasattr(cache, "fills") else []
        fill_rows = [
            {
                "ts": str(int(f.ts_event)),
                "side": str(f.order_side),
                "qty": str(f.last_qty),
                "price": str(f.last_px),
                "cid": str(f.client_order_id),
            }
            for f in fills
        ]
        out["fills"] = fill_rows
        if mode == "exit":
            out["events"] = strategy.events
            out["pages"] = strategy.pages
            out["entered"] = strategy.entered
        else:
            out["entered"] = strategy.entered
            out["entry_px"] = strategy.entry_px
            out["exit_px"] = strategy.exit_px
            out["entry_ts"] = strategy.entry_ts
            out["exit_ts"] = strategy.exit_ts
        out["counts"] = {
            "quotes": len(quotes),
            "trades": len(trades),
            "bars": len(bars),
        }
        return out
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=sorted(CASES))
    parser.add_argument("mode", choices=("exit", "hold1555", "holdflat"))
    parser.add_argument("--end", help="override the window end (ISO local time)")
    args = parser.parse_args()
    case = case_meta(args.case)
    case["name"] = args.case
    if args.end:
        case["end"] = datetime.fromisoformat(args.end).replace(tzinfo=NY)
        case["end_ns"] = ns(case["end"])
    catalog = ParquetDataCatalog(str(CATALOG.resolve()))
    out = run_engine(case, mode=args.mode, catalog=catalog)
    out["entry_ns"] = case["entry_ns"]
    out["flat_ns"] = case["flat_ns"]
    out["mark_ns"] = case["mark_ns"]
    path = RUN / args.case / f"{args.mode}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, sort_keys=True))
    print(json.dumps({"path": str(path), "fills": out["fills"], "counts": out["counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
