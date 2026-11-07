"""ADR-0004 N1/N2, with the source pins and late-data deviations in docs/manifest.md."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from nautilus_trader.model import Bar, BarType, InstrumentId, TradeTick

from sextant.entry.indicators import DecimalATR
from sextant.entry.parameters import EntryParameters, number
from sextant.entry.tape import Tape


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
    """Complete producer counts by horizon ns over (end_ns - horizon, end_ns]."""

    instrument_id: InstrumentId
    segment: str
    start_ns: int
    end_ns: int
    known_at: int
    source: str
    counts: Mapping[int, int] | None = None


def classify(price, level, atr, multiple) -> Extension:
    if level is None or atr is None or not atr.is_finite() or atr <= 0:
        return Extension.UNKNOWN
    return Extension.EXTENDED if price - level > multiple * atr else Extension.NOT_EXTENDED


class _Reclaim:
    def __init__(self, params: EntryParameters):
        self.params = params
        self.episode_started: int | None = None
        self.touch: tuple[int, Decimal] | None = None
        self._clear_retest()

    def _clear_retest(self) -> None:
        self.reclaim_count = self.reclaim_started = 0
        self.confirmed = False
        self.high: Decimal | None = None
        self.trough: Decimal | None = None
        self.hold_started: int | None = None
        self.reclaim_event_ns: int | None = None
        self.reclaim_consumed_price: Decimal | None = None

    def _reclaim(self, tick, level, extension, *, eligible=True) -> None:
        price, at, p = tick.price.as_decimal(), tick.ts_event, self.params
        self.reclaim_event_ns = None
        if extension is Extension.UNKNOWN or level is None:
            self.touch = None
            self._clear_retest()
            return
        if extension is Extension.EXTENDED:
            if self.episode_started is None:
                self.episode_started, self.touch = at if eligible else None, None
                self._clear_retest()
            return
        if self.episode_started is not None:
            if price <= level and at > self.episode_started:
                self.touch, self.episode_started = (at, price) if eligible else None, None
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
            if eligible:
                if not self.reclaim_count:
                    self.reclaim_started = at
                self.reclaim_count += 1
                self.high = max(self.high or price, price)
                self.confirmed = self.reclaim_count >= p[
                    "reclaim_trades_count"
                ] and at - self.reclaim_started >= p.ns("reclaim_trades_span_s")
            return
        assert self.high is not None
        if self.reclaim_consumed_price is not None and self.trough is None:
            if price >= self.reclaim_consumed_price:
                self.high = max(self.high, price)
                return
            if eligible:
                self.trough, self.hold_started = price, at
            return
        if self.trough is not None and self.hold_started is not None:
            if (
                price > self.trough
                and at - self.hold_started >= p.ns("reclaim_hold_s")
                and self.trough > self.touch[1]
                and self.trough >= level
            ):
                self.reclaim_event_ns = at if eligible else None
                self.reclaim_consumed_price = price
                self.trough, self.hold_started = None, None
                self.high = max(self.high, price)
                return
            if price > self.high:
                self.trough, self.hold_started = None, None
        if price > self.high:
            self.high = price
        elif (
            price < self.high
            and (self.trough is None or price < self.trough)
            and (eligible or self.trough is not None)
        ):
            self.trough, self.hold_started = price, at


class EntryState(_Reclaim):
    def __init__(
        self, instrument_id: InstrumentId, params: EntryParameters, segment: str, *, start_ns: int
    ):
        self.instrument_id, self.params = instrument_id, params
        self.atr = DecimalATR(params["atr_period"])
        self.bar_type = BarType.from_str(
            f"{instrument_id}-{params['atr_bar_minutes']}-MINUTE-LAST-EXTERNAL"
        )
        self.last_bar_ns = -1
        self.tape = Tape()
        self.reset_segment(segment, start_ns=start_ns)

    def reset_segment(self, segment: str, *, start_ns: int) -> None:
        if not segment or type(start_ns) is not int or start_ns < 0:
            raise ValueError("segment identity and event-time start required")
        self.segment, self.segment_start_ns = segment, start_ns
        self.tape.db.execute("DELETE FROM prints")
        self.surge: Surge | None = None
        self.last: TradeTick | None = None
        self._rebuild()

    def arm(self, surge: Surge) -> None:
        if (
            surge.instrument_id != self.instrument_id
            or surge.segment != self.segment
            or not self.segment_start_ns
            <= surge.first_print_ts
            <= surge.known_at
            < surge.expires_ts
            or not surge.source
        ):
            raise ValueError("invalid surge identity, segment, clocks or source")
        number(surge.quiet_price, "quiet_price")
        if self.surge is None:
            self.surge = surge
            self._rebuild()

    def on_bar(self, bar: Bar, *, now: int) -> bool:
        if (
            bar.bar_type != self.bar_type
            or not self.last_bar_ns < bar.ts_event <= bar.ts_init <= now
        ):
            return False
        self.atr.handle_bar(bar)
        if self.atr.value is not None:
            self.tape.db.execute(
                "INSERT OR REPLACE INTO atrs VALUES (?, ?)", (now, str(self.atr.value))
            )
        self.last_bar_ns = bar.ts_event
        return True

    def on_trade(self, tick: TradeTick, *, now: int) -> bool:
        if (
            tick.instrument_id != self.instrument_id
            or not self.segment_start_ns <= tick.ts_event <= tick.ts_init <= now
            or tick.price.as_decimal() <= 0
            or tick.size.as_decimal() <= 0
        ):
            return False
        eligible = (
            self.last is None or tick.ts_event >= self.last.ts_event
        ) and now - tick.ts_event <= self.params.ns("max_data_age_s")
        if not self.tape.add(tick, eligible, self.atr.value):
            return False
        if self.last is None or tick.ts_event >= self.last.ts_event:
            self.last = tick
        if eligible:
            self._advance(tick, True, self.atr.value, rebuilding=False)
        else:
            self._rebuild()
            self.reclaim_event_ns = None
        return eligible

    def _advance(self, tick, eligible, atr, *, rebuilding=True) -> None:
        price, size = tick.price.as_decimal(), tick.size.as_decimal()
        self.dollars += price * size
        self.volume += size
        self.vwap = self.dollars / self.volume
        self.extension = (
            classify(price, self.vwap, atr, self.params["entry_max_vwap_extension_atr"])
            if rebuilding
            else self._extension(price)
        )
        flag = self.surge
        if flag is not None:
            in_window = (
                flag.first_print_ts
                <= tick.ts_event
                <= min(flag.expires_ts, flag.first_print_ts + self.params.ns("first_leg_window_s"))
                and price > flag.quiet_price
            )
            if not in_window or (self.previous is not None and price < self.previous):
                self.run = []
            if eligible and in_window:
                self.run.append(tick)
                if len(self.run) > self.params["first_leg_trades_count"] + 1:
                    del self.run[1]
        self.previous = price
        self._reclaim(tick, self.vwap, self.extension, eligible=eligible)
        self.ordered._reclaim(tick, self.vwap, self.extension)
        if self.reclaim_event_ns != self.ordered.reclaim_event_ns:
            self.reclaim_event_ns = None

    def _rebuild(self) -> None:
        self.run: list[TradeTick] = []
        self.previous: Decimal | None = None
        self.dollars = self.volume = Decimal(0)
        self.vwap: Decimal | None = None
        self.extension = Extension.UNKNOWN
        _Reclaim.__init__(self, self.params)
        self.ordered = _Reclaim(self.params)
        for tick, eligible, atr in self.tape.rows():
            self._advance(tick, eligible, atr)
        if self.last is not None:
            self.extension = self._extension(self.last.price.as_decimal())

    def _extension(self, price: Decimal) -> Extension:
        return classify(
            price, self.vwap, self.atr.value, self.params["entry_max_vwap_extension_atr"]
        )

    def fresh(self, now: int) -> bool:
        return (
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
            and ask >= flag.quiet_price
            and flag.known_at <= now < flag.expires_ts
            and now - flag.first_print_ts <= p.ns("first_leg_window_s")
            and len(run) >= p["first_leg_trades_count"]
            and run[-1].ts_event - run[0].ts_event >= p.ns("first_leg_span_s")
            and max(ask, run[-1].price.as_decimal())
            <= flag.quiet_price * (1 + p["first_leg_max_move"])
        )

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
            or not isinstance(coverage.counts, Mapping)
            or not 0 <= coverage.start_ns <= now - max(baseline_ns, window_ns)
            or not now <= coverage.end_ns <= coverage.known_at <= now
        ):
            return False
        baseline = coverage.counts.get(baseline_ns)
        recent = coverage.counts.get(window_ns)
        observed_baseline = self.tape.count(now - baseline_ns, now)
        observed_recent = self.tape.count(now - window_ns, now)
        return bool(
            type(baseline) is int
            and type(recent) is int
            and baseline >= observed_baseline > 0
            and recent >= observed_recent >= 0
            and (window_ns >= baseline_ns or recent <= baseline)
            and (window_ns <= baseline_ns or recent >= baseline)
            and recent * baseline_ns >= baseline * window_ns * self.params["covered_flow_ratio"]
            and observed_recent * baseline_ns
            >= observed_baseline * window_ns * self.params["covered_flow_ratio"]
        )
