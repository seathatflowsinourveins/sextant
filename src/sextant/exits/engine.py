"""The exit engine as a Nautilus strategy: protect the native position from its first fill, raise
the trigger on every event, sell on the first persisted breach and chase the managed LIMIT.

Policy: sextant.exits.policy (ADR-0005 X2-X6). Seams: nautechsystems/nautilus_trader@v2.0.0rc7
55c0e82053142bce3a5cba4de4221d3929c2d3bc: `Strategy.subscribe_quotes`, `subscribe_trades` and
`subscribe_bars`; `order_factory.limit` as in examples/live/architect_ax/strategies.py
(OrderBookImbalance.on_quote); `Strategy.modify_order` per docs/concepts/strategies.md. That
method raises on an unchanged price, so the engine amends only a changed level, one at a time.
Internal 1-minute bars come from eligible trades. Replay and sim only: this module places no
broker order and holds no key.

The protected quantity is the native position (R86, #129), read with `Cache.position` in
`on_position_opened/changed/closed` (docs/concepts/cache.md:659-672, strategies.md:229-234). Each
position event follows its `OrderFilled` (docs/concepts/events/index.md:123-160).
- A fill of the position's opening order (`OrderFilled.client_order_id` equal to its
  `opening_order_id`) grows the protection, so a partly filled entry is protected in full.
- A BUY from any other order is an add, which pauses the symbol and pages (ADR-0007:17). Nothing
  here clears a pause. Owner custody and reservations stay house logic (design row 8).
- A close resets the protection, so a re-entry is protected afresh.
- The basis is the opening order's `Order.avg_px`, a Decimal (MIGRATION_V2.md:480). rc7's
  `Position.avg_px_open` is an f64, and Decimal only from rc8 (#87).
- The managed sell is a reduce-only LIMIT for the whole position. If a later fill of the same entry
  lands while it rests, the venue resizes it to the position: rc7's "Backtest reduce-only
  resizing", docs/concepts/orders/advanced.md:228-231.

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
    PositionChanged,
    PositionClosed,
    PositionId,
    PositionOpened,
    PositionSide,
    Price,
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
        one_tick: Decimal | None = None,
        arm_bar_type: str | None = None,
        range_estimable: bool = True,
        **_kwargs: object,
    ) -> None:
        """`round_trip_cost` is ADR-0005's c_RT override; `session` is "rth" (breach on bids) or
        "outside" (breach on eligible trades). `one_tick` is the broker tick when the instrument's
        increment is a lossless matching precision (trading@8256c16c b_gain_protection.py:411-415);
        `arm_bar_type` names the completed 1-minute bars for arming (default: internal from trades);
        `range_estimable=False` drops R_w where the data cannot estimate it (#98)."""
        super().__init__()
        if session not in {"rth", "outside"}:
            raise ValueError("session must be rth or outside")
        self.instrument_id = instrument_id
        self.params = params
        self.round_trip_cost = round_trip_cost
        self.session = session
        self.one_tick = one_tick
        self.arm_bar_type = arm_bar_type
        self.range_estimable = range_estimable


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
        self.cfg = config
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
        self.position_id: PositionId | None = None
        self.entry_order_id: ClientOrderId | None = None
        self.sell_id: ClientOrderId | None = None
        self.one_tick = Decimal(0)
        self.amended_ns = 0
        self.paused = False
        self.pages: list[str] = []
        self.events: list[dict[str, str]] = []

    def on_start(self) -> None:
        instrument_id = self.instrument_id
        instrument = self.cache.instrument(instrument_id)
        assert instrument is not None
        self.one_tick = self.cfg.one_tick or instrument.price_increment.as_decimal()
        self.subscribe_quotes(instrument_id)
        self.subscribe_trades(instrument_id)
        bar_type = self.cfg.arm_bar_type or f"{instrument_id}-1-MINUTE-LAST-INTERNAL"
        self.subscribe_bars(BarType.from_str(bar_type))

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

    # Fills classify; the position events that follow each fill carry the quantity.
    def on_order_filled(self, event: OrderFilled) -> None:
        px, qty = event.last_px.as_decimal(), event.last_qty.as_decimal()
        if event.order_side != OrderSide.BUY:
            self._record(event.ts_event, "sell_fill", price=px, qty=qty)
        elif self.entry_order_id is not None and event.client_order_id != self.entry_order_id:
            # ADR-0007:17: an add to a held symbol from another order pauses it and pages.
            self._pause_and_page(event.ts_event, "owner_add", qty=qty)
        elif self.entry_order_id is not None:  # the same entry order, filling further
            if self.protection is not None:
                self.protection.high = max(self.protection.high, px)
            self._record(event.ts_event, "entry_fill", price=px, qty=qty)
        # A first fill opens the native position, and on_position_opened protects it.

    def on_position_opened(self, event: PositionOpened) -> None:
        if event.instrument_id != self.instrument_id:
            return
        ts = event.ts_event
        if self.paused:  # a page stands until a person clears it (ADR-0007:17)
            self._record(ts, "paused_unprotected", qty=event.quantity.as_decimal())
            return
        if self.position_id is not None or event.side != PositionSide.LONG:
            self._pause_and_page(ts, "quantity_mismatch", qty=event.quantity.as_decimal())
            return
        self.position_id, self.entry_order_id = event.position_id, event.opening_order_id
        entry, qty = self._basis(), self._held()
        self.protection = Protection(entry=entry, qty=qty, high=event.last_px.as_decimal())
        self._record(ts, "protected_from_fill", entry=entry, qty=qty)
        ok = self.bid is not None and self._quote_ok(ts)
        self._step(ts, (self.bid if ok else None) if self.rth else self.last)

    def on_position_changed(self, event: PositionChanged) -> None:
        p = self.protection
        if p is None or self.paused or event.position_id != self.position_id:
            return
        p.qty, p.entry = self._held(), self._basis()
        self._record(event.ts_event, "protected_qty", qty=p.qty, entry=p.entry)

    def on_position_closed(self, event: PositionClosed) -> None:
        if event.position_id != self.position_id:
            return
        self._record(event.ts_event, "flat")
        self.protection, self.position_id, self.entry_order_id = None, None, None
        self.sell_id, self.arming, self.breach = None, Bar1mArming(), BreachRun()

    # One step of X2-X5 on an eligible observation (bid in RTH, trade outside).
    def _step(self, ts: int, observed: Decimal | None) -> None:
        p = self.protection
        if p is None or self.paused or observed is None or self.bid is None or self.ask is None:
            return
        spread = self.ask - self.bid
        buf = policy.buffer(
            self.one_tick,
            spread,
            p.entry,
            self._range(ts),
            self.p,
            range_estimable=self.cfg.range_estimable,
        )
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
        """One managed LIMIT for the whole native position: one exit per quantity (ADR-0007:19)."""
        assert self.bid is not None and p.trigger is not None and self.position_id is not None
        position = self.cache.position(self.position_id)
        assert position is not None and position.is_open
        # With either chase row unavailable (#98) the fast sell rests at the bid: chase off.
        last = self.last if self.p.chase_on else None
        order = self.order_factory.limit(
            instrument_id=self.instrument_id,
            order_side=OrderSide.SELL,
            quantity=position.quantity,
            price=self._price(policy.chase_limit(self.bid, last, self.p)),
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        self.sell_id = order.client_order_id
        self.amended_ns = ts
        self.submit_order(order)
        kind = "breach_sell_gain_lock" if self.arming.armed else "breach_sell_prearm"
        qty = position.quantity.as_decimal()
        self._record(ts, kind, trigger=p.trigger, limit=order.price.as_decimal(), qty=qty)

    def _chase(self, ts: int) -> None:
        if self.sell_id is None or not self.p.chase_on:
            return
        assert self.p.chase_min_interval_s is not None
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

    def _held(self) -> Decimal:
        """The protected native position's quantity, from the cache."""
        assert self.position_id is not None
        position = self.cache.position(self.position_id)
        assert position is not None
        return position.quantity.as_decimal()

    def _basis(self) -> Decimal:
        """The opening order's `Order.avg_px`. While unpaused, every fill in the position is its."""
        assert self.entry_order_id is not None
        order = self.cache.order(self.entry_order_id)
        assert order is not None and isinstance(order.avg_px, Decimal)
        return order.avg_px

    def _pause_and_page(self, ts: int, reason: str, **values: Decimal) -> None:
        """ADR-0007:17-19: stop managing the symbol and page a person, once per reason."""
        self.paused = True
        if reason not in self.pages:
            self.pages.append(reason)
        kind = "add_paused" if reason == "owner_add" else "pause_and_page"
        self._record(ts, kind, reason=reason, **values)

    def _price(self, value: Decimal) -> Price:
        """Round a sell limit up to the tick, so it never lands below the bid."""
        ticks = (value / self.one_tick).to_integral_value(rounding=ROUND_CEILING)
        return Price.from_str(str(ticks * self.one_tick))

    def _record(self, ts: int, event: str, **values: Decimal | str) -> None:
        self.events.append({"ts": str(ts), "event": event} | {k: str(v) for k, v in values.items()})
