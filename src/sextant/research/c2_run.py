"""C2 step 4: modeled exit arms on C1's landed SIP tapes, no broker, no key, no live.

Every arm starts from the same witness entry: one share, market buy submitted on the first SIP
trade print at or after 09:30:00 ET on the entry session (BRIEF-C2.md; C1 protocol 904747d4...).
Arm 1 is the pinned production `ExitEngine` (#214 98f1043 + exit PR 2 09e579f) unchanged; its
only difference from C1's wrapper is that the entry order is submitted on the first trade print
rather than the first quote. Arms 2, 3, 7 and 8 are fixed trailing stops; arm 4 is the ATR22
(5-minute, Wilder) chandelier at k=3; arm 5 holds to 15:55 of the final session; arm 6 holds no
position.

Fixed trails use Alpaca's RTH trailing-stop semantics: stop = high-water mark * (1 - p), high
water mark kept since the order was submitted (docs.alpaca.markets/docs/orders-at-alpaca, read
2026-11-07); on a trade print at or below the stop the arm sells at market. Outside RTH (never
reached by these cases before the stop) the B code's emulated stop-limit is the citation:
`src/sextant/exits/owner_b_sim.py:195`. No re-entry. Nothing here writes the ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime
from datetime import time as daytime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType,
    Bar,
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
from sextant.paper.sessions import Session, session_at

ROOT = Path.home() / "sextant-data" / "c2-scenario"
CATALOG = Path.home() / "sextant-data" / "c1-scenario" / "catalog"
RUN = ROOT / "run"
NS = 1_000_000_000
QD = Decimal("0.0001")

CASES: dict[str, dict[str, Any]] = {
    "a": {
        "symbol": "PARA",
        "cusip": "06682J803",
        "entry_day": date(2026, 11, 3),
        "start": datetime(2026, 11, 3, 4, 0, tzinfo=NY),
        "end": datetime(2026, 11, 4, 20, 0, tzinfo=NY),
        "mark": datetime(2026, 11, 4, 15, 55, tzinfo=NY),
    },
    "b": {
        "symbol": "PARA",
        "cusip": "06682J803",
        "entry_day": date(2026, 10, 27),
        "start": datetime(2026, 10, 27, 4, 0, tzinfo=NY),
        "end": datetime(2026, 10, 27, 20, 0, tzinfo=NY),
        "mark": datetime(2026, 10, 27, 15, 55, tzinfo=NY),
    },
    "c": {
        "symbol": "SPCX",
        "cusip": "unavailable",
        "entry_day": date(2026, 10, 21),
        "start": datetime(2026, 10, 21, 4, 0, tzinfo=NY),
        "end": datetime(2026, 10, 22, 20, 0, tzinfo=NY),
        "mark": datetime(2026, 10, 22, 15, 55, tzinfo=NY),
    },
}

# arm -> (kind, fraction or multiplier)
ARMS: dict[str, tuple[str, Decimal | None]] = {
    "exit-engine-p2": ("engine", None),
    "trail-0.5": ("trail", Decimal("0.005")),
    "trail-2.5": ("trail", Decimal("0.025")),
    "trail-0.25": ("trail", Decimal("0.0025")),
    "trail-0.1": ("trail", Decimal("0.001")),
    "atr-trail-3": ("atr", Decimal("3")),
    "hold-1555": ("hold", None),
    "hold-flat": ("flat", None),
}
TRAIL_LABEL = {
    "trail-0.5": "fixed_trail_0.5",
    "trail-2.5": "fixed_trail_2.5",
    "trail-0.25": "fixed_trail_0.25",
    "trail-0.1": "fixed_trail_0.1",
    "atr-trail-3": "atr_trail_3",
}


def ns(value: datetime) -> int:
    return nanos(value)


def case_meta(name: str) -> dict[str, Any]:
    case = dict(CASES[name])
    opened = datetime.combine(case["entry_day"], daytime(9, 30), tzinfo=NY)
    case["name"] = name
    case["entry_ns"] = ns(opened)
    case["mark_ns"] = ns(case["mark"])
    case["start_ns"] = ns(case["start"])
    case["end_ns"] = ns(case["end"])
    return case


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_DATA_HASH_CACHE: dict[tuple[str, tuple[str, ...]], dict[str, str]] = {}


def data_hashes(symbol: str, start_ns: int, end_ns: int) -> dict[str, str]:
    """SHA-256 of the parquet files the run read, keyed by relative name.

    File names carry the UTC window; a run window touches at most the start date and the end
    date (the A case ends 20:00 ET = 01:00Z on the next UTC day).
    """
    import datetime as _dt

    start = _dt.datetime.fromtimestamp(start_ns / NS, _dt.UTC).date()
    end = _dt.datetime.fromtimestamp(end_ns / NS, _dt.UTC).date()
    dates = {start.isoformat(), end.isoformat()}
    key = (symbol, tuple(sorted(dates)))
    if key in _DATA_HASH_CACHE:
        return dict(_DATA_HASH_CACHE[key])
    out: dict[str, str] = {}
    dirs = (
        CATALOG / "data" / "quotes" / f"{symbol}.ALPACA",
        CATALOG / "data" / "trades" / f"{symbol}.ALPACA",
        CATALOG / "data" / "bars" / f"{symbol}.ALPACA-1-MINUTE-LAST-EXTERNAL",
    )
    for folder in dirs:
        for path in sorted(folder.glob("*.parquet")):
            if path.name[:10] not in dates:
                continue
            out[str(path.relative_to(CATALOG))] = digest_file(path)
    _DATA_HASH_CACHE[key] = dict(out)
    return out


class FiveMinuteAtr:
    """Wilder ATR on 5-minute bars built from completed 1-minute external bars (RTH only)."""

    def __init__(self, period: int = 22) -> None:
        self.period = period
        self.prev_close: Decimal | None = None
        self.trs: list[Decimal] = []
        self.atr: Decimal | None = None
        self._idx: int | None = None
        self._bars: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []

    def on_minute(
        self, close_dt: datetime, o: Decimal, h: Decimal, lo: Decimal, c: Decimal
    ) -> bool:
        minute = close_dt.hour * 60 + close_dt.minute
        if not 571 <= minute <= 960:  # 09:31 .. 16:00 ET
            return False
        idx = (minute - 571) // 5
        changed = self._idx is not None and idx != self._idx
        if self._idx is None:
            self._idx = idx
        if changed:
            self._finalize()
            self._idx = idx
        self._bars.append((o, h, lo, c))
        return self._finalize() if close_dt.minute % 5 == 0 and close_dt.second == 0 else False

    def _finalize(self) -> bool:
        if not self._bars:
            return False
        h = max(b[1] for b in self._bars)
        lo = min(b[2] for b in self._bars)
        c = self._bars[-1][3]
        self._bars = []
        tr = h - lo
        if self.prev_close is not None:
            tr = max(tr, abs(h - self.prev_close), abs(lo - self.prev_close))
        self.prev_close = c
        self.trs.append(tr)
        if self.atr is None and len(self.trs) == self.period:
            self.atr = sum(self.trs) / Decimal(self.period)
            return True
        if self.atr is not None and len(self.trs) > self.period:
            self.atr = (self.atr * Decimal(self.period - 1) + tr) / Decimal(self.period)
            return True
        return False


class TrailBase(Strategy):
    """Market buy on the first trade print; trail the high-water mark; market sell on breach."""

    def arm(
        self,
        *,
        instrument_id: InstrumentId,
        entry_ns: int,
        exit_ns: int,
        kind: str,
        value: Decimal | None,
        bar_type: str | None,
        qty: int = 1,
    ) -> None:
        self.instrument_id = instrument_id
        self.entry_ns = entry_ns
        self.exit_ns = exit_ns
        self.kind = kind
        self.value = value
        self.bar_type = bar_type
        self.qty = qty
        self.entered = False
        self.buy_filled = False
        self.sell_submitted = False
        self.long = False
        self.entry_px: Decimal | None = None
        self.exit_px: Decimal | None = None
        self.entry_ts: int | None = None
        self.exit_ts: int | None = None
        self.hwm: Decimal | None = None
        self.stop: Decimal | None = None
        self.trigger_px: Decimal | None = None
        self.trigger_ts: int | None = None
        self.exit_reason: str | None = None
        self.last_bid: Decimal | None = None
        self.last_ask: Decimal | None = None
        self.entry_bid: Decimal | None = None
        self.entry_ask: Decimal | None = None
        self.anchor_px: Decimal | None = None
        self.anchor_ts: int | None = None
        self.min_px: Decimal | None = None
        self.max_px: Decimal | None = None
        self.atr = FiveMinuteAtr(22) if kind == "atr" else None
        self.atr_ready_ts: int | None = None
        self.events: list[dict[str, Any]] = []

    def _log(self, ts: int, event: str, **values: Any) -> None:
        row: dict[str, Any] = {"ts": str(ts), "event": event}
        for key, value in values.items():
            row[key] = str(value) if isinstance(value, Decimal) else value
        self.events.append(row)

    def on_start(self) -> None:
        self.subscribe_quotes(self.instrument_id)
        self.subscribe_trades(self.instrument_id)
        if self.bar_type:
            self.subscribe_bars(BarType.from_str(self.bar_type))

    def on_quote(self, quote) -> None:
        if quote.instrument_id != self.instrument_id:
            return
        self.last_bid = quote.bid_price.as_decimal()
        self.last_ask = quote.ask_price.as_decimal()
        if (
            self.long
            and not self.sell_submitted
            and self.stop is not None
            and session_at(quote.ts_event) != Session.RTH
            and self.last_bid <= self.stop
        ):
            self._sell(quote.ts_event, self.last_bid, "trail_stop_outside")

    def on_trade(self, trade) -> None:
        if trade.instrument_id != self.instrument_id:
            return
        price = trade.price.as_decimal()
        if not self.entered and trade.ts_event >= self.entry_ns:
            self.entered = True
            self.anchor_px, self.anchor_ts = price, trade.ts_event
            self.hwm = price
            self.entry_bid, self.entry_ask = self.last_bid, self.last_ask
            self.submit_order(
                self.order_factory.market(
                    instrument_id=self.instrument_id,
                    order_side=OrderSide.BUY,
                    quantity=Quantity.from_int(self.qty),
                    time_in_force=TimeInForce.GTC,
                )
            )
            self._log(trade.ts_event, "witness_entry_submitted", price=price)
        if self.long and not self.sell_submitted:
            if price > self.hwm:
                self.hwm = price
            if self.min_px is None or price < self.min_px:
                self.min_px = price
            if self.max_px is None or price > self.max_px:
                self.max_px = price
            if self.kind == "trail" and self.value is not None:
                self.stop = self.hwm * (Decimal(1) - self.value)
            if (
                self.stop is not None
                and session_at(trade.ts_event) == Session.RTH
                and price <= self.stop
            ):
                self._sell(trade.ts_event, price, TRAIL_LABEL[self.arm_name])

    def on_bar(self, bar: Bar) -> None:
        if self.kind != "atr" or self.atr is None or not self.long or self.sell_submitted:
            return
        ts = bar.ts_event
        close_dt = datetime.fromtimestamp(ts // NS, NY)
        ready = self.atr.on_minute(
            close_dt,
            bar.open.as_decimal(),
            bar.high.as_decimal(),
            bar.low.as_decimal(),
            bar.close.as_decimal(),
        )
        if ready and self.atr.atr is not None:
            if self.atr_ready_ts is None:
                self.atr_ready_ts = ts
                self._log(ts, "atr_ready", atr=self.atr.atr)
            candidate = self.hwm - self.value * self.atr.atr
            self.stop = candidate if self.stop is None else max(self.stop, candidate)

    def _sell(self, ts: int, price: Decimal, reason: str) -> None:
        if self.sell_submitted:
            return
        self.sell_submitted = True
        self.trigger_px, self.trigger_ts, self.exit_reason = price, ts, reason
        self._log(ts, "sell_submitted", price=price, reason=reason)
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
        px = event.last_px.as_decimal()
        if event.order_side == OrderSide.BUY and not self.buy_filled:
            self.buy_filled = True
            self.long = True
            self.entry_px, self.entry_ts = px, event.ts_event
            self.min_px = self.max_px = px
            self._log(event.ts_event, "entry_fill", price=px)
        elif event.order_side == OrderSide.SELL:
            self.long = False
            self.exit_px, self.exit_ts = px, event.ts_event
            self._log(event.ts_event, "sell_fill", price=px)
        else:
            self._log(event.ts_event, "partial_entry_fill", price=px)


class HoldTo1555(TrailBase):
    """Buy on the witness entry; market sell at 15:55 ET of the final session (or hold)."""

    def on_trade(self, trade) -> None:
        if trade.instrument_id != self.instrument_id:
            return
        price = trade.price.as_decimal()
        if not self.entered and trade.ts_event >= self.entry_ns:
            self.entered = True
            self.anchor_px, self.anchor_ts = price, trade.ts_event
            self.entry_bid, self.entry_ask = self.last_bid, self.last_ask
            self.submit_order(
                self.order_factory.market(
                    instrument_id=self.instrument_id,
                    order_side=OrderSide.BUY,
                    quantity=Quantity.from_int(self.qty),
                    time_in_force=TimeInForce.GTC,
                )
            )
            self._log(trade.ts_event, "witness_entry_submitted", price=price)
        if self.long and not self.sell_submitted:
            if self.min_px is None or price < self.min_px:
                self.min_px = price
            if self.max_px is None or price > self.max_px:
                self.max_px = price
            if self.exit_ns is not None and trade.ts_event >= self.exit_ns:
                self._sell(trade.ts_event, price, "hold_to_1555")

    def on_quote(self, quote) -> None:
        if quote.instrument_id != self.instrument_id:
            return
        self.last_bid = quote.bid_price.as_decimal()
        self.last_ask = quote.ask_price.as_decimal()
        if self.long and not self.sell_submitted and self.exit_ns is not None:
            if quote.ts_event >= self.exit_ns:
                self._sell(quote.ts_event, self.last_bid, "hold_to_1555")


class C2Exit(ExitEngine):
    """The pinned ExitEngine, with the brief's trade-print witness entry and MAE/MFE tracking."""

    def arm(self, *, entry_ns: int, qty: int) -> None:
        self.entry_ns = entry_ns
        self.qty = qty
        self.entered = False
        self.entry_px: Decimal | None = None
        self.exit_px: Decimal | None = None
        self.entry_ts: int | None = None
        self.exit_ts: int | None = None
        self.entry_bid: Decimal | None = None
        self.entry_ask: Decimal | None = None
        self.min_px: Decimal | None = None
        self.max_px: Decimal | None = None
        self.tracking = False

    def on_quote(self, quote) -> None:
        if quote.instrument_id != self.instrument_id:
            return
        if not self.entered and quote.ts_event >= self.entry_ns:
            self.bid = quote.bid_price.as_decimal()
            self.ask = quote.ask_price.as_decimal()
            self.entry_bid, self.entry_ask = self.bid, self.ask
        super().on_quote(quote)

    def on_trade(self, trade) -> None:
        if trade.instrument_id != self.instrument_id:
            return
        if not self.entered and trade.ts_event >= self.entry_ns:
            self.entered = True
            order = self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=OrderSide.BUY,
                quantity=Quantity.from_int(self.qty),
                time_in_force=TimeInForce.GTC,
            )
            self.entry_order_id = order.client_order_id
            self.submit_order(order)
            self._record(trade.ts_event, "witness_entry_submitted", price=trade.price.as_decimal())
        super().on_trade(trade)
        if self.tracking and self.entry_px is not None:
            px = trade.price.as_decimal()
            if self.min_px is None or px < self.min_px:
                self.min_px = px
            if self.max_px is None or px > self.max_px:
                self.max_px = px

    def on_order_filled(self, event) -> None:
        super().on_order_filled(event)
        if event.instrument_id != self.instrument_id:
            return
        px = event.last_px.as_decimal()
        if event.order_side == OrderSide.BUY and self.entry_px is None:
            self.entry_px, self.entry_ts = px, event.ts_event
            self.min_px = self.max_px = px
            self.tracking = True
        elif event.order_side == OrderSide.SELL:
            self.exit_px, self.exit_ts = px, event.ts_event
            self.tracking = False


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


def net(entry: Decimal, exit_px: Decimal, bps: int) -> str:
    c = Decimal(bps) / Decimal(10_000)
    return str((exit_px / entry) * (Decimal(1) - c) - (Decimal(1) + c))


def run_arm(case: dict[str, Any], arm: str, catalog: ParquetDataCatalog) -> dict[str, Any]:
    kind, value = ARMS[arm]
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
        if kind == "engine":
            strategy = C2Exit(
                ExitEngineConfig(
                    instrument_id=iid,
                    params=ExitParams.starts(),
                    round_trip_cost=instrument.price_increment.as_decimal(),
                    session="rth",
                    arm_bar_type=bar_type,
                )
            )
            strategy.arm(entry_ns=case["entry_ns"], qty=1)
        elif kind == "hold":
            strategy = HoldTo1555(StrategyConfig())
            strategy.arm(
                instrument_id=iid,
                entry_ns=case["entry_ns"],
                exit_ns=case["mark_ns"],
                kind="hold",
                value=None,
                bar_type=None,
                qty=1,
            )
        else:
            strategy = TrailBase(StrategyConfig())
            strategy.arm(
                instrument_id=iid,
                entry_ns=case["entry_ns"],
                exit_ns=None,
                kind=kind,
                value=value,
                bar_type=bar_type if kind == "atr" else None,
                qty=1,
            )
            strategy.arm_name = arm
        engine.add_strategy(strategy)
        engine.run()
        if kind == "engine":
            entry_event = next((e for e in strategy.events if e["event"] == "entry_fill"), None)
            exit_event = next(
                (e for e in reversed(strategy.events) if e["event"] == "sell_fill"), None
            )
            entry_px = entry_event["price"] if entry_event else None
            exit_px = exit_event["price"] if exit_event else None
            entry_ts = int(entry_event["ts"]) if entry_event else None
            exit_ts = int(exit_event["ts"]) if exit_event else None
            fill_rows = []
            if entry_event:
                fill_rows.append(
                    {"ts": entry_event["ts"], "side": "BUY", "qty": "1", "price": entry_px}
                )
            if exit_event:
                fill_rows.append(
                    {"ts": exit_event["ts"], "side": "SELL", "qty": "1", "price": exit_px}
                )
        else:
            entry_px = str(strategy.entry_px) if strategy.entry_px is not None else None
            exit_px = str(strategy.exit_px) if strategy.exit_px is not None else None
            entry_ts = strategy.entry_ts
            exit_ts = strategy.exit_ts
            fill_rows = []
            if entry_px:
                fill_rows.append(
                    {"ts": str(entry_ts), "side": "BUY", "qty": "1", "price": entry_px}
                )
            if exit_px:
                fill_rows.append(
                    {"ts": str(exit_ts), "side": "SELL", "qty": "1", "price": exit_px}
                )
        out: dict[str, Any] = {
            "case": case["name"],
            "arm": arm,
            "symbol": symbol,
            "cusip": case["cusip"],
            "entry_session": str(case["entry_day"]),
            "entry_ns": case["entry_ns"],
            "mark_ns": case["mark_ns"],
            "fills": fill_rows,
            "counts": {"quotes": len(quotes), "trades": len(trades), "bars": len(bars)},
            "entry_px": entry_px,
            "exit_px": exit_px,
            "entry_ts_ns": entry_ts,
            "exit_ts_ns": exit_ts,
            "net_1x": net(Decimal(entry_px), Decimal(exit_px), 3) if entry_px and exit_px else None,
            "net_2x": net(Decimal(entry_px), Decimal(exit_px), 6) if entry_px and exit_px else None,
        }
        if kind == "engine":
            out["events"] = strategy.events
            out["pages"] = strategy.pages
            out["exit_reason"] = (
                "breach_sell_gain_lock"
                if any(e["event"] == "crossed" for e in strategy.events)
                else "exit_engine"
            )
            out["entry_bid"] = str(strategy.entry_bid) if strategy.entry_bid else None
            out["entry_ask"] = str(strategy.entry_ask) if strategy.entry_ask else None
            out["min_px"] = str(strategy.min_px) if strategy.min_px else None
            out["max_px"] = str(strategy.max_px) if strategy.max_px else None
            out["trigger_px"] = None
            out["trigger_ts_ns"] = None
            out["stop_final"] = None
            out["hwm"] = None
            out["atr_final"] = None
        else:
            out["events"] = strategy.events
            out["exit_reason"] = strategy.exit_reason or (
                "hold_to_1555" if kind == "hold" else "open_at_end"
            )
            out["entry_bid"] = str(strategy.entry_bid) if strategy.entry_bid else None
            out["entry_ask"] = str(strategy.entry_ask) if strategy.entry_ask else None
            out["min_px"] = str(strategy.min_px) if strategy.min_px else None
            out["max_px"] = str(strategy.max_px) if strategy.max_px else None
            out["trigger_px"] = str(strategy.trigger_px) if strategy.trigger_px else None
            out["trigger_ts_ns"] = strategy.trigger_ts
            out["stop_final"] = str(strategy.stop) if strategy.stop else None
            out["hwm"] = str(strategy.hwm) if strategy.hwm else None
            out["atr_final"] = (
                str(strategy.atr.atr) if strategy.atr is not None and strategy.atr.atr else None
            )
            out["atr_ready_ts_ns"] = strategy.atr_ready_ts
        if entry_px and exit_px:
            out["held_seconds"] = str(
                (Decimal(exit_ts - entry_ts) / Decimal(NS)).quantize(Decimal("0.000001"))
            )
            out["mae"] = str(Decimal(out["min_px"]) / Decimal(entry_px) - 1)
            out["mfe"] = str(Decimal(out["max_px"]) / Decimal(entry_px) - 1)
        if out["entry_bid"] and out["entry_ask"]:
            bid, ask = Decimal(out["entry_bid"]), Decimal(out["entry_ask"])
            out["spread_at_entry"] = str(ask - bid)
            out["spread_at_entry_bps"] = str(
                ((ask - bid) / ((ask + bid) / 2) * Decimal(10_000)).quantize(Decimal("0.01"))
            )
        out["data_sha256"] = data_hashes(symbol, case["start_ns"], case["end_ns"])
        return out
    finally:
        engine.dispose()


def flat_row(case: dict[str, Any], arm: str) -> dict[str, Any]:
    return {
        "case": case["name"],
        "arm": arm,
        "symbol": case["symbol"],
        "cusip": case["cusip"],
        "entry_session": str(case["entry_day"]),
        "entry_px": None,
        "exit_px": None,
        "entry_ts_ns": None,
        "exit_ts_ns": None,
        "net_1x": "0",
        "net_2x": "0",
        "exit_reason": "hold_flat",
        "mae": "0",
        "mfe": "0",
        "held_seconds": "0",
        "fills": [],
        "events": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=sorted(CASES))
    parser.add_argument("arm", choices=sorted(ARMS))
    parser.add_argument("--out", help="output directory (default: <ROOT>/run/arms)")
    parser.add_argument("--smoke-window", help="ISO start,end for a non-case mechanics check")
    args = parser.parse_args()
    case = case_meta(args.case)
    if args.smoke_window:
        start, end = (
            datetime.fromisoformat(x).replace(tzinfo=NY)
            for x in args.smoke_window.split(",")
        )
        case["start"], case["end"] = start, end
        case["start_ns"], case["end_ns"] = ns(start), ns(end)
        case["entry_day"] = start.date()
        case["entry_ns"] = ns(datetime.combine(start.date(), daytime(9, 30), tzinfo=NY))
    catalog = ParquetDataCatalog(str(CATALOG.resolve()))
    if ARMS[args.arm][0] == "flat":
        out = flat_row(case, args.arm)
    else:
        out = run_arm(case, args.arm, catalog)
    path = Path(args.out) if args.out else RUN / "arms" / f"case-{args.case}"
    path.mkdir(parents=True, exist_ok=True)
    target = path / f"{args.arm}.json"
    target.write_text(json.dumps(out, indent=2, sort_keys=True, default=str))
    summary = {
        "path": str(target),
        "entry_px": out.get("entry_px"),
        "exit_px": out.get("exit_px"),
        "net_1x": out.get("net_1x"),
        "exit_reason": out.get("exit_reason"),
        "fills": len(out.get("fills", [])),
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
