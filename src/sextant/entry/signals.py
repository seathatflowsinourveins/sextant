"""ADR-0004 N1/N2, with the source pins and late-data deviations in docs/manifest.md."""

from bisect import bisect_right
from collections import namedtuple
from collections.abc import Mapping
from copy import copy
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


Surge = namedtuple(
    "Surge", "instrument_id segment first_print_ts known_at expires_ts quiet_price source"
)
TradeCoverage = namedtuple(
    "TradeCoverage",
    "instrument_id segment start_ns end_ns known_at source counts",
    defaults=(None,),
)


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
                self.reclaim_started = self.reclaim_started if self.reclaim_count else at
                self.reclaim_count += 1
                self.high = max(self.high or price, price)
                self.confirmed = self.reclaim_count >= p[
                    "reclaim_trades_count"
                ] and at - self.reclaim_started >= p.ns("reclaim_trades_span_s")
            return
        assert self.high is not None
        consumed, low, held = self.reclaim_consumed_price, self.trough, self.hold_started
        if consumed is not None and low is None and price >= consumed:
            self.high = max(self.high, price)
            return
        if low is not None and held is not None:
            if (
                price > low
                and at - held >= p.ns("reclaim_hold_s")
                and low >= level
                and low > self.touch[1]
            ):
                self.reclaim_event_ns = at if eligible else None
                self.reclaim_consumed_price = price
                self.trough, self.hold_started = None, None
                self.high = max(self.high, price)
                return
        if price > self.high:
            self.high, self.trough, self.hold_started = price, None, None
        elif (
            price < self.high
            and (self.trough is None or price < self.trough)
            and (eligible or self.trough is not None)
        ):
            self.trough, self.hold_started = price, at


class _Fold(_Reclaim):
    def __init__(self, params):
        super().__init__(params)
        self.ordered = _Reclaim(params)
        self.surge = None
        self.run = ()
        self.previous = self.vwap = self.last_atr = None
        self.dollars = self.volume = Decimal(0)
        self.extension = Extension.UNKNOWN

    def checkpoint(self):
        point = copy(self)
        point.ordered = copy(self.ordered)
        return point

    def _advance(self, tick, eligible, atr) -> None:
        price, size = tick.price.as_decimal(), tick.size.as_decimal()
        self.dollars += price * size
        self.volume += size
        self.vwap = self.dollars / self.volume
        self.last_atr = atr
        self.extension = classify(
            price, self.vwap, atr, self.params["entry_max_vwap_extension_atr"]
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
                self.run = ()
            if eligible and in_window:
                self.run += (tick,)
                if len(self.run) > self.params["first_leg_trades_count"] + 1:
                    self.run = self.run[:1] + self.run[2:]
        self.previous = price
        self._reclaim(tick, self.vwap, self.extension, eligible=eligible)
        self.ordered._reclaim(tick, self.vwap, self.extension)
        if self.reclaim_event_ns != self.ordered.reclaim_event_ns:
            self.reclaim_event_ns = None


class EntryState:
    def __init__(
        self, instrument_id: InstrumentId, params: EntryParameters, segment: str, *, start_ns: int
    ):
        self.instrument_id, self.params = instrument_id, params
        self.atr = DecimalATR(params["atr_period"])
        self.bar_type = BarType.from_str(
            f"{instrument_id}-{params['atr_bar_minutes']}-MINUTE-LAST-EXTERNAL"
        )
        self.last_bar_ns = -1
        self.atr_times, self.atrs = [], []
        self.history_ns = max(
            params.ns(name) * (60 if name.endswith("_min") else 1)
            for name in params.values
            if name.endswith(("_s", "_min"))
        )
        self.tape = Tape(_Fold(params))
        self.reset_segment(segment, start_ns=start_ns)

    def __getattr__(self, name):
        return getattr(self.fold, name)

    def reset_segment(self, segment: str, *, start_ns: int) -> None:
        if not segment or type(start_ns) is not int or start_ns < 0:
            raise ValueError("segment identity and event-time start required")
        old = self.tape
        self.segment, self.segment_start_ns = segment, start_ns
        self.failure = None
        self.last = None
        self.fold = _Fold(self.params)
        self.tape = Tape(self.fold)
        self.tape.floor = self.prune_at = start_ns
        if start_ns < old.floor:
            self.failure = "segment start precedes retained history"
            return
        for tick, eligible, atr in old.rows(start_ns):
            folded = self.tape.add(tick, eligible, atr, self.surge)
            assert folded is not None
            self.fold, self.last = folded, tick
        self.fold.reclaim_event_ns = None

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
        if self.surge is None and self.failure is None:
            if surge.first_print_ts < self.tape.floor:
                self.failure = "surge precedes retained history"
                return
            self.fold = self.tape.rebuild(surge)
            self.fold.reclaim_event_ns = None

    def on_bar(self, bar: Bar, *, now: int) -> bool:
        if (
            self.failure
            or bar.bar_type != self.bar_type
            or not self.last_bar_ns < bar.ts_event <= bar.ts_init <= now
        ):
            return False
        self.atr.handle_bar(bar)
        if self.atr.value is not None:
            self.atr_times.append(now)
            self.atrs.append(self.atr.value)
        self.last_bar_ns = bar.ts_event
        return True

    def on_trade(self, tick: TradeTick, *, now: int) -> bool:
        if (
            self.failure
            or tick.instrument_id != self.instrument_id
            or not self.segment_start_ns <= tick.ts_event <= tick.ts_init <= now
            or tick.price.as_decimal() <= 0
            or tick.size.as_decimal() <= 0
        ):
            return False
        eligible = (
            self.last is None or tick.ts_event >= self.last.ts_event
        ) and now - tick.ts_event <= self.params.ns("max_data_age_s")
        try:
            index = bisect_right(self.atr_times, tick.ts_event) - 1
            atr = None if index < 0 else self.atrs[index]
            folded = self.tape.add(tick, eligible, atr, self.surge)
            if folded is None:
                return False
            self.fold = folded
            if self.last is None or tick.ts_event >= self.last.ts_event:
                self.last = tick
            if self.last.ts_event >= self.prune_at:
                self.tape.prune(self.last.ts_event - self.history_ns)
                self.prune_at = self.last.ts_event + self.params.ns("max_data_age_s")
                index = max(0, bisect_right(self.atr_times, self.tape.floor) - 1)
                del self.atr_times[:index], self.atrs[:index]
            if not eligible:
                self.fold.reclaim_event_ns = None
            return eligible
        except Exception as exc:
            self.failure = f"{type(exc).__name__}: {exc}"
            return False

    def fresh(self, now: int) -> bool:
        return (
            not self.failure
            and self.last is not None
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
