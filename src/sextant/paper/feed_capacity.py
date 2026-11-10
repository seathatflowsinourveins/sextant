"""Read-only capacity analyzer for the feed-tap sidecar: the pre-registered gate, with numbers.

The tap (``sextant.paper.feed_tap``) writes one JSON line per wall-clock second while the C
lane's single SIP socket runs: per-second trade and quote counts, distinct symbols, the
wall-clock receipt lag (count, p99, p99.9 and exact max), handler service time (sum and max),
feed failures, and per symbol the last ``ts_event`` and the longest inter-arrival gap. This
module reads that file and nothing else: it opens no socket, calls no broker, writes no file
and prints no price or symbol name. Section 5 of the entry-ages screen fixed the six criteria
and the overload rule before the open; this module applies them unchanged: a 1 s p99.9
receipt-lag bound with p99 inside the ruled ``entry_input_max_age_s``, a 50 ms handler-service
and sub-1 utilization bound, no monotone lag rise over 09:30-09:35 and the first RTH hour, a
per-symbol maximum gap inside the entry bound, zero feed failures and reconnects, and the
publication criterion reported NOT-APPLICABLE until the ranking publisher runs in-process.

The trend tests use the Mann-Kendall S statistic with the tie-corrected variance (Mann 1945;
Kendall 1975), one-sided at alpha 0.05, computed with the standard library only because the
repo pins no statistics dependency beyond it. The overload rule is any failed criterion, a
rising 180 s window anywhere in the measurement, or three consecutive seconds whose entry lag
exceeds the entry bound after a stall. Missing measurements fail closed: a field the tap could
not observe yields UNKNOWN, never a pass.

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

__all__ = ["Check", "GateReport", "Second", "Sidecar", "SymbolFlow", "evaluate", "load", "main"]

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
    symbols_seen: int
    lag_p99_ns: int | None
    lag_p999_ns: int | None
    lag_max_ns: int | None
    lag_count: int
    service_sum_ns: int
    service_max_ns: int | None
    failures: int
    partial: bool

    @property
    def messages(self) -> int:
        return self.trades + self.quotes


@dataclass(frozen=True, slots=True)
class SymbolFlow:
    """One symbol's whole-run freshness from the sidecar's final line."""

    last_ts_event_ns: int | None
    max_gap_ns: int | None


@dataclass(frozen=True, slots=True)
class Sidecar:
    """A parsed tap sidecar: seconds in time order, per-symbol freshness, torn-line count."""

    seconds: tuple[Second, ...]
    symbols: Mapping[str, SymbolFlow]
    malformed_lines: int = 0
    reconnects: int | None = None


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
    peak_mps: float
    sustained_mps: float
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
            f"capacity: peak {self.peak_mps:.1f} messages/s, "
            f"sustained {self.sustained_mps:.1f} messages/s over {_CAPACITY_WINDOW_S} s"
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


def _parse_second(record: Mapping[str, Any]) -> Second:
    lag = _mapping(record.get("lag_ns"))
    service = _mapping(record.get("service_ns"))
    return Second(
        second=int(record["second"]),
        trades=_int(record.get("trades")),
        quotes=_int(record.get("quotes")),
        symbols_seen=_int(record.get("symbols_seen")),
        lag_p99_ns=_opt_int(lag.get("p99")),
        lag_p999_ns=_opt_int(lag.get("p999")),
        lag_max_ns=_opt_int(lag.get("max")),
        lag_count=_int(lag.get("count")),
        service_sum_ns=_int(service.get("sum")),
        service_max_ns=_opt_int(service.get("max")),
        failures=_int(record.get("failures")),
        partial=bool(record.get("partial", False)),
    )


def _parse_symbols(record: Mapping[str, Any]) -> dict[str, SymbolFlow]:
    symbols: dict[str, SymbolFlow] = {}
    for name, flow in _mapping(record.get("symbols")).items():
        data = _mapping(flow)
        symbols[str(name)] = SymbolFlow(
            last_ts_event_ns=_opt_int(data.get("last_ts_event_ns")),
            max_gap_ns=_opt_int(data.get("max_gap_ns")),
        )
    return symbols


def load(path: str | Path) -> Sidecar:
    """Read a tap sidecar; a torn final line is skipped and counted, never fatal."""
    seconds: dict[int, Second] = {}
    symbols: dict[str, SymbolFlow] = {}
    reconnects: int | None = None
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
                    # A clock step back writes a second twice; its largest bucket is the
                    # real one, the fragment is the spill.
                    prior = seconds.get(second.second)
                    if prior is None or second.messages > prior.messages:
                        seconds[second.second] = second
                elif record.get("kind") == "symbols":
                    symbols = _parse_symbols(record)
                    reconnects = _opt_int(record.get("reconnects"))
                else:
                    malformed += 1
            except (KeyError, TypeError, ValueError):
                malformed += 1
    return Sidecar(
        seconds=tuple(seconds[second] for second in sorted(seconds)),
        symbols=symbols,
        malformed_lines=malformed,
        reconnects=reconnects,
    )


def _measured(seconds: Sequence[Second]) -> list[Second]:
    """Closed seconds that actually carried traffic; a partial second is a fragment."""
    return [second for second in seconds if not second.partial and second.messages > 0]


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


def _trend(seconds: Sequence[Second], start: int, end: int) -> tuple[str, str]:
    window = [
        value
        for second in seconds
        if start <= second.second < end and not second.partial
        for value in (second.lag_p99_ns,)
        if value is not None
    ]
    if len(window) < _MIN_TREND_SAMPLES:
        return _UNDECIDED, f"n={len(window)} (needs {_MIN_TREND_SAMPLES})"
    statistic, z, p = _mann_kendall(window)
    verdict = _BAD if statistic > 0 and p < _ALPHA else _OK
    return verdict, f"n={len(window)}, S={statistic}, Z={z:.2f}, p={p:.4f}"


def _check_receipt_lag(seconds: Sequence[Second], bound_ns: int) -> Check:
    measured = _measured(seconds)
    if not measured:
        return Check(1, "receipt-lag", _UNDECIDED, "no closed second with traffic")
    unmeasured = [
        second
        for second in measured
        if second.lag_count == 0 or second.lag_p99_ns is None or second.lag_p999_ns is None
    ]
    if unmeasured:
        return Check(
            1,
            "receipt-lag",
            _UNDECIDED,
            f"{len(unmeasured)} of {len(measured)} measured seconds carry no receipt lag; "
            "the tap must be running",
        )
    p99 = max(second.lag_p99_ns or 0 for second in measured)
    p999 = max(second.lag_p999_ns or 0 for second in measured)
    inside = p999 < _MAX_RECEIPT_LAG_NS and p99 < bound_ns
    verdict = _OK if inside else _BAD
    detail = (
        f"worst per-second p99 {p99 / _NS_PER_MS:.1f} ms and p99.9 {p999 / _NS_PER_MS:.1f} ms "
        f"over {len(measured)} measured seconds "
        f"(bounds {_MAX_RECEIPT_LAG_NS / _NS_PER_S:.1f} s tail and "
        f"{bound_ns / _NS_PER_S:.1f} s entry)"
    )
    return Check(1, "receipt-lag", verdict, detail)


def _check_service(seconds: Sequence[Second]) -> Check:
    measured = _measured(seconds)
    if not measured:
        return Check(2, "handler-service", _UNDECIDED, "no closed second with traffic")
    unmeasured = [second for second in measured if second.service_max_ns is None]
    if unmeasured:
        return Check(
            2,
            "handler-service",
            _UNDECIDED,
            f"{len(unmeasured)} of {len(measured)} measured seconds carry no service sample",
        )
    worst_service = max(second.service_max_ns or 0 for second in measured)
    worst_utilization = max(second.service_sum_ns / _NS_PER_S for second in measured)
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


def _check_symbol_gap(symbols: Mapping[str, SymbolFlow], bound_ns: int) -> Check:
    if not symbols:
        return Check(4, "symbol-gap", _UNDECIDED, "no per-symbol line in the sidecar")
    evidence = [flow for flow in symbols.values() if flow.max_gap_ns is not None]
    if not evidence:
        return Check(
            4,
            "symbol-gap",
            _UNDECIDED,
            "no symbol carried two messages, so no gap is measurable",
        )
    over = [flow for flow in evidence if (flow.max_gap_ns or 0) > bound_ns]
    worst = max(flow.max_gap_ns or 0 for flow in evidence)
    verdict = _BAD if over else _OK
    detail = (
        f"{len(evidence)}/{len(symbols)} symbols carried a measurable gap, {len(over)} over "
        f"{bound_ns / _NS_PER_S:.1f} s, worst {worst / _NS_PER_S:.1f} s"
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


def _check_feed_health(
    seconds: Sequence[Second], open_s: int | None, bound_ns: int, reconnects: int | None
) -> Check:
    failures = sum(second.failures for second in seconds)
    silent = _largest_silent_span(seconds, open_s)
    if failures:
        return Check(
            5,
            "feed-health",
            _BAD,
            f"{failures} feed.failure event(s); any stream or handler error is an overload",
        )
    if reconnects is not None and reconnects > 0:
        return Check(
            5,
            "feed-health",
            _BAD,
            f"{reconnects} stream reconnect(s); a reconnect is an overload",
        )
    if silent is not None and silent * _NS_PER_S > bound_ns:
        return Check(
            5,
            "feed-health",
            _UNDECIDED,
            f"no feed.failure, but a {silent} s whole-socket silence in the first hour; a "
            "reconnect is invisible to the tap, so the stream log must decide",
        )
    silence = "none" if silent is None else f"{silent} s"
    if reconnects is None:
        return Check(
            5,
            "feed-health",
            _UNDECIDED,
            f"0 feed.failure events and largest first-hour silence {silence}; reconnects are "
            "not observable from handlers, so the stream log must decide",
        )
    return Check(
        5,
        "feed-health",
        _OK,
        f"0 feed.failure events, 0 reconnects; largest first-hour silence {silence}",
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
        window = [
            value
            for second in seconds
            if start <= second.second < start + _TREND_WINDOW_S and not second.partial
            for value in (second.lag_p99_ns,)
            if value is not None
        ]
        if len(window) >= _MIN_SUSTAINED_SAMPLES:
            statistic, _, p = _mann_kendall(window)
            if statistic > 0 and p < _ALPHA:
                return True, (
                    f"3-minute lag rise sustained from {_clock_label(start)} "
                    f"(n={len(window)}, S={statistic}, p={p:.4f})"
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


def _capacity(seconds: Sequence[Second]) -> tuple[float, float]:
    closed = [second for second in seconds if not second.partial]
    if not closed:
        return 0.0, 0.0
    peak = float(max(second.messages for second in closed))
    traffic = {second.second: second.messages for second in closed}
    sustained = 0.0
    for second in closed:
        total = sum(
            traffic.get(anchor, 0)
            for anchor in range(second.second, second.second + _CAPACITY_WINDOW_S)
        )
        sustained = max(sustained, total / _CAPACITY_WINDOW_S)
    return peak, sustained


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
        _check_symbol_gap(sidecar.symbols, bound_ns),
        _check_feed_health(sidecar.seconds, open_s, bound_ns, sidecar.reconnects),
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
    peak, capacity = _capacity(sidecar.seconds)
    return GateReport(
        checks=checks,
        overload=bool(reasons),
        overload_reasons=tuple(reasons),
        peak_mps=peak,
        sustained_mps=capacity,
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
    print(
        f"sidecar: {len(sidecar.seconds)} seconds, {len(sidecar.symbols)} symbols, "
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
