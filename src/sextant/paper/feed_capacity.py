"""Read-only capacity analyzer for the feed-tap sidecar: the pre-registered gate, with numbers.

The tap (``sextant.paper.feed_tap``) writes one JSON line per wall-clock second while the C
lane's single SIP socket runs: per-second own-symbol trade and quote counts plus the extra
full-universe measurement trades and quotes, distinct symbols, the wall-clock receipt lag
(count, p99, p99.9 and exact max), handler service time (sum and max), and feed failures; its
final line carries aggregate per-symbol freshness as counts and a maximum, never ticker names.
The capacity figures count every delivered message, own and extra, and report own, extra and
total separately; the receipt-lag and service statistics stay own-symbol-only because the
tap's lag histogram and service samples cover only the feed's own handlers. This module reads
that file and nothing else: it opens no socket,
calls no broker, writes no file and prints no price or symbol name. Section 5 of the entry-ages
screen fixed the six criteria and the overload rule before the open; this module applies them
unchanged: a 1 s p99.9 receipt-lag bound with p99 inside the ruled ``entry_input_max_age_s``, a
50 ms handler-service and sub-1 utilization bound, no monotone lag rise over 09:30-09:35 and
the first RTH hour, a per-symbol maximum gap inside the entry bound, zero feed failures and
reconnects, and the publication criterion reported NOT-APPLICABLE until the ranking publisher
runs in-process.

Two conventions keep the verdicts honest. The tap reports each percentile as its 1 ms bin's
lower edge, so a 999 ms p99.9 is a lag in [999, 1000) ms and a 1000 ms figure is at or over
the 1 s bound, never below it. And a field the tap could not observe is UNKNOWN, never zero:
missing lag samples, missing service samples, a partial per-symbol gap census, a reconnect
count the tap cannot see, and a bounded queue that dropped seconds all fail closed.

The trend tests use the Mann-Kendall S statistic with the tie-corrected variance (Mann 1945;
Kendall 1975), one-sided at alpha 0.05, computed with the standard library only because the
repo pins no statistics dependency beyond it. A trend window is judged only when every second
of it is present in the sidecar; a fragmented or short run is UNKNOWN, not a pass. The
overload rule is any failed criterion, a rising fully observed 180 s window anywhere in the
measurement, or three consecutive seconds whose entry lag exceeds the entry bound after a
stall.

Usage::

    python -m sextant.paper.feed_capacity reports/paper-c/<stamp>/feed-tap.jsonl \\
        --entry-input-max-age-s 5

Exit code 0 passes, 1 fails or overloads, 2 could not decide from the sidecar alone.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from statistics import NormalDist
from typing import Any
from zoneinfo import ZoneInfo

__all__ = ["Check", "GateReport", "Rate", "Second", "Sidecar", "evaluate", "load", "main"]

_ET = ZoneInfo("America/New_York")
_NS_PER_S = 1_000_000_000
_NS_PER_MS = 1_000_000
_OK = "PASS"
_BAD = "FAIL"
_UNDECIDED = "UNKNOWN"
_INERT = "NOT-APPLICABLE"

# The pre-registered gate, section 5 of the entry-ages screen (fixed before the open).
_MAX_RECEIPT_LAG_NS = 1 * _NS_PER_S
_MAX_SERVICE_NS = 50 * _NS_PER_MS
_MAX_UTILIZATION = 1.0
_ALPHA = 0.05
_OPEN_WINDOW_S = 5 * 60
_FIRST_HOUR_S = 60 * 60
_MIN_TREND_SAMPLES = 30
_MIN_SUSTAINED_SAMPLES = 150
_TREND_WINDOW_S = 180
_TREND_STEP_S = 30
_STALE_BURST_S = 3
_CAPACITY_WINDOW_S = 60


@dataclass(frozen=True, slots=True)
class Second:
    """One aggregated wall-clock second from the sidecar."""

    second: int
    trades: int
    quotes: int
    extra_trades: int
    extra_quotes: int
    symbols_seen: int
    lag_p99_ns: int | None
    lag_p999_ns: int | None
    lag_max_ns: int | None
    lag_count: int
    service_sum_ns: int | None
    service_max_ns: int | None
    failures: int | None
    partial: bool

    @property
    def own_messages(self) -> int:
        """Messages on the feed's own symbols; the lag and service samples cover these."""
        return self.trades + self.quotes

    @property
    def extra_messages(self) -> int:
        """Full-universe measurement messages the tap counted beside the own-symbol ones."""
        return self.extra_trades + self.extra_quotes

    @property
    def messages(self) -> int:
        """Every message the tap delivered: own-symbol plus the measurement extras."""
        return self.own_messages + self.extra_messages


@dataclass(frozen=True, slots=True)
class Rate:
    """A measured messages-per-second rate, split by delivery source."""

    own_mps: float
    extra_mps: float
    total_mps: float


@dataclass(frozen=True, slots=True)
class Sidecar:
    """A parsed tap sidecar: seconds in time order plus the aggregate final line."""

    seconds: tuple[Second, ...]
    symbols_seen: int | None = None
    symbols_with_gap: int | None = None
    max_gap_ns: int | None = None
    reconnects: int | None = None
    dropped_buckets: int | None = None
    write_errors: int | None = None
    init_errors: int | None = None
    malformed_lines: int = 0


@dataclass(frozen=True, slots=True)
class Check:
    """One pre-registered criterion and the numbers behind its verdict."""

    criterion: int
    name: str
    verdict: str
    detail: str


@dataclass(frozen=True, slots=True)
class GateReport:
    """The six verdicts plus the overload rule and the measured rates."""

    checks: tuple[Check, ...]
    overload: bool
    overload_reasons: tuple[str, ...]
    peak: Rate
    sustained: Rate
    entry_input_max_age_s: float

    @property
    def overall(self) -> str:
        verdicts = [check.verdict for check in self.checks]
        if _BAD in verdicts:
            return _BAD
        if _UNDECIDED in verdicts:
            return _UNDECIDED
        return _OK

    def lines(self) -> list[str]:
        lines = [
            f"criterion {check.criterion} {check.name}: {check.verdict} — {check.detail}"
            for check in self.checks
        ]
        lines.append(f"overall: {self.overall}")
        lines.append(
            f"capacity: peak messages/s own {self.peak.own_mps:.1f}, "
            f"extra {self.peak.extra_mps:.1f}, total {self.peak.total_mps:.1f}; "
            f"sustained over {_CAPACITY_WINDOW_S} s own {self.sustained.own_mps:.1f}, "
            f"extra {self.sustained.extra_mps:.1f}, total {self.sustained.total_mps:.1f}"
        )
        if self.overload:
            lines.append("overload: YES — " + "; ".join(self.overload_reasons))
        else:
            lines.append("overload: none")
        return lines


def _int(value: Any, default: int = 0) -> int:
    return value if isinstance(value, int) else default


def _opt_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _max_optional(left: int | None, right: int | None) -> int | None:
    values = [value for value in (left, right) if value is not None]
    return max(values) if values else None


def _sum_optional(left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None
    return left + right


def _parse_second(record: Mapping[str, Any]) -> Second:
    lag = _mapping(record.get("lag_ns"))
    service = _mapping(record.get("service_ns"))
    return Second(
        second=int(record["second"]),
        trades=_int(record.get("trades")),
        quotes=_int(record.get("quotes")),
        extra_trades=_int(record.get("extra_trades")),
        extra_quotes=_int(record.get("extra_quotes")),
        symbols_seen=_int(record.get("symbols_seen")),
        lag_p99_ns=_opt_int(lag.get("p99")),
        lag_p999_ns=_opt_int(lag.get("p999")),
        lag_max_ns=_opt_int(lag.get("max")),
        lag_count=_int(lag.get("count")),
        service_sum_ns=_opt_int(service.get("sum")),
        service_max_ns=_opt_int(service.get("max")),
        failures=_opt_int(record.get("failures")),
        partial=bool(record.get("partial", False)),
    )


def _merge(left: Second, right: Second) -> Second:
    """Join disjoint fragments of one second without losing a counter or a maximum."""
    return Second(
        second=left.second,
        trades=left.trades + right.trades,
        quotes=left.quotes + right.quotes,
        extra_trades=left.extra_trades + right.extra_trades,
        extra_quotes=left.extra_quotes + right.extra_quotes,
        symbols_seen=max(left.symbols_seen, right.symbols_seen),
        lag_p99_ns=_max_optional(left.lag_p99_ns, right.lag_p99_ns),
        lag_p999_ns=_max_optional(left.lag_p999_ns, right.lag_p999_ns),
        lag_max_ns=_max_optional(left.lag_max_ns, right.lag_max_ns),
        lag_count=left.lag_count + right.lag_count,
        service_sum_ns=_sum_optional(left.service_sum_ns, right.service_sum_ns),
        service_max_ns=_max_optional(left.service_max_ns, right.service_max_ns),
        failures=_sum_optional(left.failures, right.failures),
        partial=left.partial or right.partial,
    )


def load(path: str | Path) -> Sidecar:
    """Read a tap sidecar; a torn final line is skipped and counted, never fatal."""
    seconds: dict[int, Second] = {}
    aggregate: dict[str, int | None] = {
        "symbols_seen": None,
        "symbols_with_gap": None,
        "max_gap_ns": None,
        "reconnects": None,
        "dropped_buckets": None,
        "write_errors": None,
        "init_errors": None,
    }
    malformed = 0
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(record, dict):
                malformed += 1
                continue
            try:
                if record.get("kind") == "second":
                    second = _parse_second(record)
                    # A clock step back can split one second across two lines; the tap's
                    # buckets are disjoint, so merge rather than discard a fragment.
                    prior = seconds.get(second.second)
                    seconds[second.second] = second if prior is None else _merge(prior, second)
                elif record.get("kind") == "symbols":
                    for key in aggregate:
                        aggregate[key] = _opt_int(record.get(key))
                else:
                    malformed += 1
            except (KeyError, TypeError, ValueError):
                malformed += 1
    return Sidecar(
        seconds=tuple(seconds[second] for second in sorted(seconds)),
        symbols_seen=aggregate["symbols_seen"],
        symbols_with_gap=aggregate["symbols_with_gap"],
        max_gap_ns=aggregate["max_gap_ns"],
        reconnects=aggregate["reconnects"],
        dropped_buckets=aggregate["dropped_buckets"],
        write_errors=aggregate["write_errors"],
        init_errors=aggregate["init_errors"],
        malformed_lines=malformed,
    )


def _measured(seconds: Sequence[Second]) -> list[Second]:
    """Closed seconds with own-symbol traffic; extras have no lag or service sample."""
    return [second for second in seconds if not second.partial and second.own_messages > 0]


def _open_second(seconds: Sequence[Second]) -> int | None:
    if not seconds:
        return None
    day = datetime.fromtimestamp(seconds[0].second, tz=_ET).date()
    return int(datetime.combine(day, time(9, 30), tzinfo=_ET).timestamp())


def _clock_label(second: int) -> str:
    return datetime.fromtimestamp(second, tz=_ET).strftime("%H:%M:%S ET")


def _mann_kendall(values: Sequence[float]) -> tuple[int, float, float]:
    """Return S, its normal Z and the one-sided p for a rising trend."""
    n = len(values)
    statistic = 0
    for index in range(n - 1):
        left = values[index]
        for right in values[index + 1 :]:
            if right > left:
                statistic += 1
            elif right < left:
                statistic -= 1
    variance = n * (n - 1) * (2 * n + 5)
    for count in Counter(values).values():
        if count > 1:
            variance -= count * (count - 1) * (2 * count + 5)
    variance /= 18
    if variance <= 0:
        return statistic, 0.0, 1.0
    root = math.sqrt(variance)
    if statistic > 0:
        z = (statistic - 1) / root
    elif statistic < 0:
        z = (statistic + 1) / root
    else:
        z = 0.0
    return statistic, z, 1.0 - NormalDist().cdf(z)


def _window(seconds: Sequence[Second], start: int, end: int) -> tuple[list[int], bool]:
    """Return the lag series in [start, end) and whether every second of it was observed."""
    found = {
        second.second: second
        for second in seconds
        if start <= second.second < end and not second.partial
    }
    complete = all(
        (second := found.get(moment)) is not None and second.lag_p99_ns is not None
        for moment in range(start, end)
    )
    values = [found[moment].lag_p99_ns or 0 for moment in range(start, end) if moment in found]
    return values, complete


def _trend(seconds: Sequence[Second], start: int, end: int) -> tuple[str, str]:
    values, complete = _window(seconds, start, end)
    if not complete:
        return _UNDECIDED, f"covered {len(values)}/{end - start} seconds of the window"
    if len(values) < _MIN_TREND_SAMPLES:
        return _UNDECIDED, f"n={len(values)} (needs {_MIN_TREND_SAMPLES})"
    statistic, z, p = _mann_kendall(values)
    verdict = _BAD if statistic > 0 and p < _ALPHA else _OK
    return verdict, f"n={len(values)}, S={statistic}, Z={z:.2f}, p={p:.4f}"


def _check_receipt_lag(seconds: Sequence[Second], bound_ns: int) -> Check:
    measured = _measured(seconds)
    if not measured:
        return Check(1, "receipt-lag", _UNDECIDED, "no closed second with traffic")
    unmeasured = [
        second
        for second in measured
        if second.lag_count != second.own_messages
        or second.lag_p99_ns is None
        or second.lag_p999_ns is None
    ]
    if unmeasured:
        return Check(
            1,
            "receipt-lag",
            _UNDECIDED,
            f"{len(unmeasured)} of {len(measured)} measured seconds lack a receipt lag for every "
            "message; the tap must be running",
        )
    p99 = max(second.lag_p99_ns or 0 for second in measured)
    p999 = max(second.lag_p999_ns or 0 for second in measured)
    inside = p999 < _MAX_RECEIPT_LAG_NS and p99 < bound_ns
    verdict = _OK if inside else _BAD
    detail = (
        f"worst per-second p99 {p99 / _NS_PER_MS:.1f} ms and p99.9 {p999 / _NS_PER_MS:.1f} ms "
        f"over {len(measured)} measured seconds, percentiles reported at their bin's lower edge "
        f"(bounds {_MAX_RECEIPT_LAG_NS / _NS_PER_S:.1f} s tail and "
        f"{bound_ns / _NS_PER_S:.1f} s entry)"
    )
    return Check(1, "receipt-lag", verdict, detail)


def _check_service(seconds: Sequence[Second]) -> Check:
    measured = _measured(seconds)
    if not measured:
        return Check(2, "handler-service", _UNDECIDED, "no closed second with traffic")
    unmeasured = [
        second
        for second in measured
        if second.service_max_ns is None or second.service_sum_ns is None
    ]
    if unmeasured:
        return Check(
            2,
            "handler-service",
            _UNDECIDED,
            f"{len(unmeasured)} of {len(measured)} measured seconds carry no service sample",
        )
    worst_service = max(second.service_max_ns or 0 for second in measured)
    worst_utilization = max((second.service_sum_ns or 0) / _NS_PER_S for second in measured)
    verdict = (
        _OK if worst_service < _MAX_SERVICE_NS and worst_utilization < _MAX_UTILIZATION else _BAD
    )
    detail = (
        f"max {worst_service / _NS_PER_MS:.1f} ms, utilization {worst_utilization:.2f}, "
        f"headroom {1.0 - worst_utilization:.2f} over {len(measured)} measured seconds "
        f"(bounds {_MAX_SERVICE_NS / _NS_PER_MS:.1f} ms and {_MAX_UTILIZATION:.2f})"
    )
    return Check(2, "handler-service", verdict, detail)


def _check_trend(seconds: Sequence[Second], open_s: int | None) -> Check:
    if open_s is None:
        return Check(3, "lag-trend", _UNDECIDED, "no seconds in the sidecar")
    first = _trend(seconds, open_s, open_s + _OPEN_WINDOW_S)
    hour = _trend(seconds, open_s, open_s + _FIRST_HOUR_S)
    verdicts = (first[0], hour[0])
    if _BAD in verdicts:
        verdict = _BAD
    elif _UNDECIDED in verdicts:
        verdict = _UNDECIDED
    else:
        verdict = _OK
    detail = f"09:30-09:35: {first[0]} ({first[1]}); first hour: {hour[0]} ({hour[1]})"
    return Check(3, "lag-trend", verdict, detail)


def _check_symbol_gap(sidecar: Sidecar, bound_ns: int) -> Check:
    observed, gaps = sidecar.symbols_seen, sidecar.symbols_with_gap
    if observed is None or gaps is None:
        return Check(4, "symbol-gap", _UNDECIDED, "no aggregate symbol line in the sidecar")
    if observed == 0:
        return Check(4, "symbol-gap", _UNDECIDED, "the sidecar saw no symbol")
    if gaps < observed:
        return Check(
            4,
            "symbol-gap",
            _UNDECIDED,
            f"{gaps}/{observed} symbols carried a measurable gap; the rest are missing, not zero",
        )
    if sidecar.max_gap_ns is None:
        return Check(
            4, "symbol-gap", _UNDECIDED, "no gap value, though every symbol has two messages"
        )
    verdict = _BAD if sidecar.max_gap_ns > bound_ns else _OK
    detail = (
        f"{gaps}/{observed} symbols carried a measurable gap, worst "
        f"{sidecar.max_gap_ns / _NS_PER_S:.3f} s (bound {bound_ns / _NS_PER_S:.1f} s)"
    )
    return Check(4, "symbol-gap", verdict, detail)


def _largest_silent_span(seconds: Sequence[Second], open_s: int | None) -> int | None:
    if open_s is None:
        return None
    first_hour = [
        second.second
        for second in seconds
        if open_s <= second.second < open_s + _FIRST_HOUR_S and not second.partial
    ]
    if len(first_hour) < 2:
        return None
    return max(
        first_hour[index + 1] - first_hour[index] - 1 for index in range(len(first_hour) - 1)
    )


def _check_feed_health(sidecar: Sidecar, open_s: int | None, bound_ns: int) -> Check:
    seconds = sidecar.seconds
    if any(second.failures is None for second in seconds):
        return Check(5, "feed-health", _UNDECIDED, "a second carries no failure counter")
    failures = sum(second.failures or 0 for second in seconds)
    silent = _largest_silent_span(seconds, open_s)
    silence = "none" if silent is None else f"{silent} s"
    if failures:
        return Check(
            5,
            "feed-health",
            _BAD,
            f"{failures} feed.failure event(s); any stream or handler error is an overload",
        )
    if sidecar.reconnects is None:
        return Check(
            5,
            "feed-health",
            _UNDECIDED,
            f"0 feed.failure events and largest first-hour silence {silence}; reconnects are "
            "not observable from handlers, so the stream log must decide",
        )
    if sidecar.reconnects > 0:
        return Check(
            5,
            "feed-health",
            _BAD,
            f"{sidecar.reconnects} stream reconnect(s); a reconnect is an overload",
        )
    if sidecar.dropped_buckets is None or sidecar.write_errors is None:
        return Check(
            5, "feed-health", _UNDECIDED, "the aggregate line lacks the tap's loss counters"
        )
    if sidecar.dropped_buckets:
        return Check(
            5,
            "feed-health",
            _UNDECIDED,
            f"the bounded queue dropped {sidecar.dropped_buckets} second(s); "
            "the window is incomplete",
        )
    if sidecar.write_errors:
        return Check(
            5,
            "feed-health",
            _UNDECIDED,
            f"the sidecar failed to write {sidecar.write_errors} record(s)",
        )
    if silent is not None and silent * _NS_PER_S > bound_ns:
        return Check(
            5,
            "feed-health",
            _UNDECIDED,
            f"no feed.failure, but a {silent} s whole-socket silence in the first hour; a "
            "reconnect is invisible to the tap, so the stream log must decide",
        )
    return Check(
        5,
        "feed-health",
        _OK,
        f"0 feed.failure events, 0 reconnects, no dropped seconds; "
        f"largest first-hour silence {silence}",
    )


def _check_publication() -> Check:
    return Check(
        6,
        "publication-health",
        _INERT,
        "the ranking publisher does not run in-process; counter 6 applies once it does",
    )


def _sustained_rise(seconds: Sequence[Second], open_s: int | None) -> tuple[bool, str | None]:
    if open_s is None or not seconds:
        return False, None
    end = max(second.second for second in seconds)
    start = open_s
    while start + _TREND_WINDOW_S <= end + 1:
        values, complete = _window(seconds, start, start + _TREND_WINDOW_S)
        if complete and len(values) >= _MIN_SUSTAINED_SAMPLES:
            statistic, _, p = _mann_kendall(values)
            if statistic > 0 and p < _ALPHA:
                return True, (
                    f"3-minute lag rise sustained from {_clock_label(start)} "
                    f"(n={len(values)}, S={statistic}, p={p:.4f})"
                )
        start += _TREND_STEP_S
    return False, None


def _stale_burst(seconds: Sequence[Second], bound_ns: int) -> str | None:
    burst = 0
    previous: int | None = None
    for second in seconds:
        stale = (
            not second.partial and second.lag_p99_ns is not None and second.lag_p99_ns > bound_ns
        )
        if stale and previous is not None and second.second == previous + 1:
            burst += 1
        elif stale:
            burst = 1
        else:
            burst = 0
        previous = second.second
        if burst == _STALE_BURST_S:
            return (
                f"{_STALE_BURST_S} stale seconds in a row from "
                f"{_clock_label(second.second - _STALE_BURST_S + 1)}"
            )
    return None


def _sustained_mps(seconds: Sequence[Second], counts: Mapping[int, int]) -> float:
    """The best rolling _CAPACITY_WINDOW_S average of a per-second message count."""
    best = 0.0
    for second in seconds:
        window = range(second.second, second.second + _CAPACITY_WINDOW_S)
        best = max(best, sum(counts.get(anchor, 0) for anchor in window) / _CAPACITY_WINDOW_S)
    return best


def _capacity(seconds: Sequence[Second]) -> tuple[Rate, Rate]:
    closed = [second for second in seconds if not second.partial]
    if not closed:
        return Rate(0.0, 0.0, 0.0), Rate(0.0, 0.0, 0.0)
    own = {second.second: second.own_messages for second in closed}
    extra = {second.second: second.extra_messages for second in closed}
    total = {second.second: second.messages for second in closed}
    peak = Rate(
        own_mps=float(max(own.values())),
        extra_mps=float(max(extra.values())),
        total_mps=float(max(total.values())),
    )
    return peak, Rate(
        own_mps=_sustained_mps(closed, own),
        extra_mps=_sustained_mps(closed, extra),
        total_mps=_sustained_mps(closed, total),
    )


def evaluate(sidecar: Sidecar, *, entry_input_max_age_s: float) -> GateReport:
    """Apply the pre-registered gate to one sidecar; the entry bound has no default."""
    if entry_input_max_age_s <= 0:
        raise ValueError("entry_input_max_age_s must be positive")
    bound_ns = int(entry_input_max_age_s * _NS_PER_S)
    open_s = _open_second(sidecar.seconds)
    checks = (
        _check_receipt_lag(sidecar.seconds, bound_ns),
        _check_service(sidecar.seconds),
        _check_trend(sidecar.seconds, open_s),
        _check_symbol_gap(sidecar, bound_ns),
        _check_feed_health(sidecar, open_s, bound_ns),
        _check_publication(),
    )
    reasons = [
        f"criterion {check.criterion} ({check.name}) failed"
        for check in checks
        if check.verdict == _BAD
    ]
    sustained, reason = _sustained_rise(sidecar.seconds, open_s)
    if sustained and reason is not None:
        reasons.append(reason)
    stale = _stale_burst(sidecar.seconds, bound_ns)
    if stale is not None:
        reasons.append(stale)
    peak, sustained = _capacity(sidecar.seconds)
    return GateReport(
        checks=checks,
        overload=bool(reasons),
        overload_reasons=tuple(reasons),
        peak=peak,
        sustained=sustained,
        entry_input_max_age_s=entry_input_max_age_s,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="read-only feed capacity gate over a tap sidecar")
    parser.add_argument("sidecar", type=Path, help="the feed-tap.jsonl path")
    parser.add_argument(
        "--entry-input-max-age-s",
        type=float,
        required=True,
        help="the ruled entry_input_max_age_s, in seconds (the analyzer has no default)",
    )
    args = parser.parse_args(argv)
    sidecar = load(args.sidecar)
    report = evaluate(sidecar, entry_input_max_age_s=args.entry_input_max_age_s)
    seen = "missing" if sidecar.symbols_seen is None else str(sidecar.symbols_seen)
    gaps = "missing" if sidecar.symbols_with_gap is None else str(sidecar.symbols_with_gap)
    print(
        f"sidecar: {len(sidecar.seconds)} seconds, {seen} symbols ({gaps} with a measured gap), "
        f"{sidecar.malformed_lines} malformed lines"
    )
    for line in report.lines():
        print(line)
    if report.overall == _BAD or report.overload:
        return 1
    if report.overall == _UNDECIDED:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
