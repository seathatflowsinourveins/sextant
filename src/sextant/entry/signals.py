"""ADR-0004 N1/N2; first-leg run adapted from pinned first_leg.py::_run.

The pinned entry ADR supplies the house extension/retest policy, not an edge.
The rc7 ATR/RMA formulas consume native completed bars in Decimal arithmetic.
A quote never changes an episode or its touch.
"""

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from nautilus_trader.model import Bar, BarType, InstrumentId, TradeTick

from sextant.entry.indicators import DecimalATR
from sextant.entry.parameters import EntryParameters, number


class Extension(StrEnum):
    UNKNOWN = "UNKNOWN"
    NOT_EXTENDED = "NOT_EXTENDED"
    EXTENDED = "EXTENDED"


@dataclass(frozen=True)
class Surge:
    instrument_id: InstrumentId
    segment: str
    first_print_ts: int
    known_at: int
    expires_ts: int
    quiet_price: Decimal
    source: str


@dataclass(frozen=True)
class TradeCoverage:
    """Producer's complete eligible-trade interval, read only as of known_at."""

    instrument_id: InstrumentId
    segment: str
    start_ns: int
    end_ns: int
    known_at: int
    source: str


class EntryState:
    def __init__(self, instrument_id: InstrumentId, params: EntryParameters, segment: str):
        self.instrument_id, self.params = instrument_id, params
        self.atr = DecimalATR(params["atr_period"])
        self.bar_type = BarType.from_str(
            f"{instrument_id}-{params['atr_bar_minutes']}-MINUTE-LAST-EXTERNAL"
        )
        self.last_bar_ns = -1
        self.trades: deque[TradeTick] = deque()
        self.identities: set[tuple] = set()
        self.reset_segment(segment)

    def reset_segment(self, segment: str) -> None:
        self.segment = segment
        self.surge: Surge | None = None
        self.run: list[TradeTick] = []
        self.last: TradeTick | None = None
        self.trades.clear()
        self.identities.clear()
        self.dollars = self.volume = Decimal(0)
        self.vwap: Decimal | None = None
        self.extension = Extension.UNKNOWN
        self.episode_started: int | None = None
        self.touch: tuple[int, Decimal] | None = None
        self._clear_retest()

    def _clear_retest(self) -> None:
        self.reclaim_run: list[TradeTick] = []
        self.confirmed = False
        self.high: Decimal | None = None
        self.trough: Decimal | None = None
        self.hold_started: int | None = None
        self.reclaim_event_ns: int | None = None
        self.reclaim_consumed_price: Decimal | None = None

    def arm(self, surge: Surge) -> None:
        if (
            surge.instrument_id != self.instrument_id
            or surge.segment != self.segment
            or not 0 <= surge.first_print_ts <= surge.known_at < surge.expires_ts
            or not surge.source
        ):
            raise ValueError("invalid surge identity, segment, clocks or source")
        number(surge.quiet_price, "quiet_price")
        if self.surge is not None:
            return  # An episode cannot renew its first anchor.
        self.surge = surge
        for tick in self.trades:
            self._first_leg(tick)

    def on_bar(self, bar: Bar, *, now: int) -> bool:
        if (
            bar.bar_type != self.bar_type
            or not self.last_bar_ns < bar.ts_event <= bar.ts_init <= now
        ):
            return False
        self.atr.handle_bar(bar)
        self.last_bar_ns = bar.ts_event
        return True

    def on_trade(self, tick: TradeTick, *, now: int) -> bool:
        identity = (str(tick.trade_id), tick.ts_event, tick.price, tick.size)
        if (
            tick.instrument_id != self.instrument_id
            or identity in self.identities
            or not 0 <= tick.ts_event <= tick.ts_init <= now
            or now - tick.ts_event > self.params.ns("max_data_age_s")
            or (self.last is not None and tick.ts_event < self.last.ts_event)
            or tick.price.as_decimal() <= 0
            or tick.size.as_decimal() <= 0
        ):
            return False
        self.last = tick
        self.trades.append(tick)
        self.identities.add(identity)
        retain = max(
            self.params.ns("flow_share_window_s"),
            self.params.ns("first_leg_window_s"),
            self.params.ns("covered_flow_baseline_min") * 60,
        )
        while self.trades and self.trades[0].ts_event < tick.ts_event - retain:
            old = self.trades.popleft()
            self.identities.discard((str(old.trade_id), old.ts_event, old.price, old.size))
        price, size = tick.price.as_decimal(), tick.size.as_decimal()
        self.dollars += price * size
        self.volume += size
        self.vwap = self.dollars / self.volume
        self.extension = self._extension(price)
        self._first_leg(tick)
        self._reclaim(tick)
        return True

    def _extension(self, price: Decimal) -> Extension:
        if self.vwap is None or not self.atr.initialized:
            return Extension.UNKNOWN
        atr = self.atr.value
        assert atr is not None
        if not atr.is_finite() or atr <= 0:
            return Extension.UNKNOWN
        return (
            Extension.EXTENDED
            if price - self.vwap > self.params["entry_max_vwap_extension_atr"] * atr
            else Extension.NOT_EXTENDED
        )

    def not_extended_at_ask(self, ask: Decimal) -> bool:
        return bool(
            self.last is not None
            and self.extension is Extension.NOT_EXTENDED
            and self._extension(max(self.last.price.as_decimal(), ask)) is Extension.NOT_EXTENDED
        )

    def _first_leg(self, tick: TradeTick) -> None:
        if self.surge is None:
            return
        price = tick.price.as_decimal()
        if tick.ts_event < self.surge.first_print_ts or price <= self.surge.quiet_price:
            self.run = []
        elif self.run and price < self.run[-1].price.as_decimal():
            self.run = [tick]
        else:
            self.run.append(tick)

    def fresh(self, now: int) -> bool:
        return bool(
            self.last is not None
            and self.last.ts_init <= now
            and now - self.last.ts_event <= self.params.ns("max_data_age_s")
        )

    def first_leg_ready(self, ask: Decimal, now: int) -> bool:
        flag, p, run = self.surge, self.params, self.run
        return bool(
            flag
            and self.fresh(now)
            and ask.is_finite()
            and ask > 0
            and flag.known_at <= now < flag.expires_ts
            and now - flag.first_print_ts <= p.ns("first_leg_window_s")
            and len(run) >= p["first_leg_trades_count"]
            and run[-1].ts_event - run[0].ts_event >= p.ns("first_leg_span_s")
            and max(ask, run[-1].price.as_decimal())
            <= flag.quiet_price * (1 + p["first_leg_max_move"])
        )

    def _reclaim(self, tick: TradeTick) -> None:
        price, at, level, p = tick.price.as_decimal(), tick.ts_event, self.vwap, self.params
        self.reclaim_event_ns = None
        if self.extension is Extension.UNKNOWN or level is None:
            self.touch = None
            self._clear_retest()
            return
        if self.extension is Extension.EXTENDED:
            if self.episode_started is None:
                self.episode_started, self.touch = at, None
                self._clear_retest()
            return
        if self.episode_started is not None:
            if price <= level and at > self.episode_started:
                self.touch, self.episode_started = (at, price), None
                self._clear_retest()
            return
        if self.touch is None:
            return
        if at - self.touch[0] > p.ns("reclaim_lookback_s") or price < level:
            self.touch = None
            self._clear_retest()
            return
        if price == level and not self.confirmed:
            self._clear_retest()
            return
        if not self.confirmed:
            self.reclaim_run.append(tick)
            self.high = max(self.high or price, price)
            self.confirmed = len(self.reclaim_run) >= p[
                "reclaim_trades_count"
            ] and at - self.reclaim_run[0].ts_event >= p.ns("reclaim_trades_span_s")
            return
        assert self.high is not None
        if self.reclaim_consumed_price is not None and self.trough is None:
            if price >= self.reclaim_consumed_price:
                self.high = max(self.high, price)
                return
            self.trough, self.hold_started = price, at
            return
        if self.trough is not None and self.hold_started is not None:
            if (
                price > self.trough
                and at - self.hold_started >= p.ns("reclaim_hold_s")
                and self.trough > self.touch[1]
                and self.trough >= level
            ):
                self.reclaim_event_ns = at
                self.reclaim_consumed_price = price
                self.trough, self.hold_started = None, None
                self.high = max(self.high, price)
                return  # Consume this retest even when the caller cannot enter.
            elif price > self.high:
                self.trough, self.hold_started = None, None
        if price > self.high:
            self.high = price
        elif price < self.high and (self.trough is None or price < self.trough):
            self.trough, self.hold_started = price, at

    def reclaim_ready(self, ask: Decimal, buffer: Decimal, now: int, *, covered_flow=False) -> bool:
        return bool(
            covered_flow
            and self.fresh(now)
            and self.last is not None
            and self.reclaim_event_ns == self.last.ts_event
            and self.vwap is not None
            and ask.is_finite()
            and buffer.is_finite()
            and buffer > 0
            and self.vwap <= ask <= self.vwap + self.params["reclaim_max_above_buffers"] * buffer
        )

    def covered_flow(self, now: int, coverage: TradeCoverage | None) -> bool:
        baseline_ns = self.params.ns("covered_flow_baseline_min") * 60
        window_ns = self.params.ns("covered_flow_window_s")
        if (
            coverage is None
            or coverage.instrument_id != self.instrument_id
            or coverage.segment != self.segment
            or not coverage.source
            or not 0 <= coverage.start_ns <= now - baseline_ns
            or not now <= coverage.end_ns <= coverage.known_at <= now
        ):
            return False
        baseline = sum(now - baseline_ns < t.ts_event <= now for t in self.trades)
        recent = sum(now - window_ns < t.ts_event <= now for t in self.trades)
        return bool(
            baseline > 0
            and recent * baseline_ns >= baseline * window_ns * self.params["covered_flow_ratio"]
        )
