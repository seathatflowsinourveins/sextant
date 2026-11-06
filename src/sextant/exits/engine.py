"""The exit engine as a Nautilus strategy: protect the position from its first fill, raise the
trigger on every event, sell on the first persisted breach and chase the managed LIMIT.

Policy: sextant.exits.policy (ADR-0005 X2-X6). Seams: nautechsystems/nautilus_trader@v2.0.0rc7
55c0e82053142bce3a5cba4de4221d3929c2d3bc: `Strategy.subscribe_quotes`, `subscribe_trades` and
`subscribe_bars`; `order_factory.limit` as in examples/live/architect_ax/strategies.py
(OrderBookImbalance.on_quote); `Strategy.modify_order` per docs/concepts/strategies.md. That
method raises on an unchanged price, so the engine amends only a changed level, one at a time.
Internal 1-minute bars come from eligible trades. Replay and sim only: this module places no
broker order and holds no key.

Scope of this slice: the take-profit and backstop are computed as desired levels and reported. They
are venue orders (Alpaca OCO/bracket, ADR-0005 X6), placed later by the custody row, not here.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import (
    Bar,
    BarType,
    ClientOrderId,
    InstrumentId,
    OrderFilled,
    OrderSide,
    Price,
    Quantity,
    QuoteTick,
    TimeInForce,
    TradeTick,
)
from nautilus_trader.trading import Strategy

from sextant.exits import policy
from sextant.exits.policy import Bar1mArming, BreachRun, ExitParams

NS = 1_000_000_000


class ExitEngineConfig(StrategyConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        params: ExitParams,
        round_trip_cost: Decimal,
        session: str,
        **_kwargs: object,
    ) -> None:
        """`round_trip_cost` is ADR-0005's c_RT override; `session` is "rth" (breach on bids) or
        "outside" (breach on eligible trades)."""
        super().__init__()
        if session not in {"rth", "outside"}:
            raise ValueError("session must be rth or outside")
        self.instrument_id = instrument_id
        self.params = params
        self.round_trip_cost = round_trip_cost
        self.session = session


@dataclass
class Protection:
    entry: Decimal
    qty: Decimal
    high: Decimal
    trigger: Decimal | None = None
    setup_gap: Decimal | None = None
    take_profit: Decimal | None = None
    tp_anchor: Decimal | None = None
    backstop: Decimal | None = None


class ExitEngine(Strategy):
    def __init__(self, config: ExitEngineConfig) -> None:
        super().__init__(config)
        self.instrument_id = config.instrument_id
        self.p = config.params
        self.c_rt = config.round_trip_cost
        self.rth = config.session == "rth"
        self.bid: Decimal | None = None
        self.ask: Decimal | None = None
        self.quote_ns = 0
        self.last: Decimal | None = None
        self.trades: deque[tuple[int, Decimal]] = deque()
        self.arming = Bar1mArming()
        self.breach = BreachRun()
        self.protection: Protection | None = None
        self.sell_id: ClientOrderId | None = None
        self.one_tick = Decimal(0)
        self.amended_ns = 0
        self.paused = False
        self.events: list[dict[str, str]] = []

    def on_start(self) -> None:
        instrument_id = self.instrument_id
        instrument = self.cache.instrument(instrument_id)
        assert instrument is not None
        self.one_tick = instrument.price_increment.as_decimal()
        self.subscribe_quotes(instrument_id)
        self.subscribe_trades(instrument_id)
        self.subscribe_bars(BarType.from_str(f"{instrument_id}-1-MINUTE-LAST-INTERNAL"))

    # Market data. Pre-entry ticks warm the range and the last quote/trade, never H or a breach.
    def on_quote(self, quote: QuoteTick) -> None:
        self.bid, self.ask = quote.bid_price.as_decimal(), quote.ask_price.as_decimal()
        self.quote_ns = quote.ts_event
        if self.rth:
            self._step(quote.ts_event, self.bid if self._quote_ok(quote.ts_event) else None)

    def on_trade(self, trade: TradeTick) -> None:
        price = trade.price.as_decimal()
        self.last = price
        self.trades.append((trade.ts_event, price))
        if self.protection is not None:
            self.protection.high = max(self.protection.high, price)
        if not self.rth:
            self._step(trade.ts_event, price)

    def on_bar(self, bar: Bar) -> None:
        if self.protection is not None and self.bid is not None and self.ask is not None:
            floor = policy.noise_floor(self.one_tick, self.ask - self.bid)
            level = self.protection.entry + self.c_rt + floor
            self.arming.on_bar_close(bar.close.as_decimal(), level)

    def on_order_filled(self, event: OrderFilled) -> None:
        px, qty = event.last_px.as_decimal(), event.last_qty.as_decimal()
        if event.order_side == OrderSide.BUY:
            if self.protection is None:
                self.protection = Protection(entry=px, qty=qty, high=px)
                self._record(event.ts_event, "protected_from_fill", entry=px)
                self._step(event.ts_event, self.bid if self.rth else self.last)
            else:  # ADR-0007: an add to a managed symbol pauses it; custody is row 8
                self.paused = True
                self._record(event.ts_event, "add_paused", qty=qty)
        else:
            self._record(event.ts_event, "sell_fill", price=px, qty=qty)

    # One step of X2-X5 on an eligible observation (bid in RTH, trade outside).
    def _step(self, ts: int, observed: Decimal | None) -> None:
        p = self.protection
        if p is None or self.paused or observed is None or self.bid is None or self.ask is None:
            return
        spread = self.ask - self.bid
        buf = policy.buffer(self.one_tick, spread, p.entry, self._range(ts), self.p)
        if buf is not None:
            if p.trigger is None:
                p.trigger, p.setup_gap = p.entry - buf, buf
                self._record(ts, "initial_trigger", trigger=p.trigger, buffer=buf)
            assert p.setup_gap is not None
            floor = policy.noise_floor(self.one_tick, spread)
            lock = policy.gain_lock(p.entry, self.c_rt, p.high, floor, self.p)
            if not self.arming.armed:
                armed_trigger = policy.next_trigger(p.trigger, p.high, buf, lock)
                executable = self.bid if self.rth else self.last
                if executable is not None and self.arming.try_arm(executable, armed_trigger):
                    self._record(ts, "armed", gain_lock=lock)
            trail = buf if self.arming.armed else max(buf, p.setup_gap)
            p.trigger = policy.next_trigger(
                p.trigger, p.high, trail, lock if self.arming.armed else None
            )
            p.take_profit, p.tp_anchor = policy.take_profit(
                p.take_profit, p.tp_anchor, p.high, self.p
            )
            p.backstop = policy.backstop(p.backstop, p.trigger, self.bid, self.p)
        if p.trigger is None:
            return
        if self.sell_id is None:
            if self.breach.observe(observed, p.trigger, ts, self.p):
                self._sell(ts, p)
        else:
            self._chase(ts)

    def _sell(self, ts: int, p: Protection) -> None:
        assert self.bid is not None and p.trigger is not None
        order = self.order_factory.limit(
            instrument_id=self.instrument_id,
            order_side=OrderSide.SELL,
            quantity=Quantity.from_str(str(p.qty)),
            price=self._price(policy.chase_limit(self.bid, self.last, self.p)),
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        self.sell_id = order.client_order_id
        self.amended_ns = ts
        self.submit_order(order)
        self._record(ts, "breach_sell", trigger=p.trigger, limit=order.price.as_decimal())

    def _chase(self, ts: int) -> None:
        if self.sell_id is None:
            return
        order = self.cache.order(self.sell_id)
        interval = int(self.p.chase_min_interval_s * NS)
        if order is None or not order.is_open or order.is_pending_update or self.bid is None:
            return
        if ts - self.amended_ns < interval:
            return
        price = self._price(policy.chase_limit(self.bid, self.last, self.p))
        if price != order.price:
            self.amended_ns = ts
            self.modify_order(order.client_order_id, price=price)
            self._record(ts, "chase", limit=price.as_decimal())

    def _quote_ok(self, ts: int) -> bool:
        assert self.bid is not None and self.ask is not None
        age_ok = ts - self.quote_ns <= int(self.p.quote_max_age_s * NS)
        return self.bid > 0 and self.ask > self.bid and age_ok

    def _range(self, ts: int) -> Decimal | None:
        start = ts - int(self.p.prearm_range_window_s * NS)
        while self.trades and self.trades[0][0] < start:
            self.trades.popleft()
        if not self.trades:
            return None
        prices = [price for _, price in self.trades]
        return max(prices) - min(prices)

    def _price(self, value: Decimal) -> Price:
        """Round a sell limit up to the tick, so it never lands below the bid."""
        ticks = (value / self.one_tick).to_integral_value(rounding=ROUND_CEILING)
        return Price.from_str(str(ticks * self.one_tick))

    def _record(self, ts: int, event: str, **values: Decimal) -> None:
        self.events.append({"ts": str(ts), "event": event} | {k: str(v) for k, v in values.items()})
