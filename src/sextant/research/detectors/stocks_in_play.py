"""Published local Stocks in Play screen, NOT top-20 selection or an ORB trade.

upstream checked: Zarattini--Barbon--Aziz, DOI 10.2139/ssrn.4729284,
author PDF SHA-256 9423012e9f0199e3f6925c500725815c236d7ddbdd7500d50d10bac2be745e91,
pp. 9, 14--15, 19, sections 2.1, 3, 4 and 5. RTH 09:30--09:35 ET only.
Native bars: NautilusTrader@55c0e82053142bce3a5cba4de4221d3929c2d3bc.
The coordinator owns calendar, dated universe, raw/action-qualified inputs,
prior-session identity, native daily ATR and the full candidate cross-section.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from nautilus_trader.model import Bar, BarAggregation, InstrumentId, PriceType

from .common import Parameter, decimal, digest

SOURCE = (
    "doi:10.2139/ssrn.4729284; "
    "pdf-sha256:9423012e9f0199e3f6925c500725815c236d7ddbdd7500d50d10bac2be745e91"
)
PARAMETERS = tuple(
    Parameter(name, unit, value, f"{SOURCE}; {section}", "PUBLISHED", date(2026, 11, 6))
    for name, unit, value, section in (
        ("opening_window", "minutes", 5, "sections 2.1/3"),
        ("lookback", "completed exchange sessions", 14, "sections 2.1/3"),
        ("open_above", "USD", Decimal(5), "section 4"),
        ("adv_at_least", "shares per day", Decimal(1_000_000), "section 4"),
        ("atr_above", "USD", Decimal("0.50"), "section 4"),
        ("rvol_at_least", "ratio", Decimal(1), "section 4"),
        ("top_n", "stocks (external cross-section)", 20, "section 4"),
    )
)
PARAMS_HASH = digest([r.identity for r in PARAMETERS])
NS = 1_000_000_000


@dataclass(frozen=True)
class OpeningWindow:
    instrument_id: InstrumentId
    session: date
    open: Decimal
    close: Decimal
    volume: Decimal
    known_at_ns: int

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId) or type(self.session) is not date:
            raise ValueError("native instrument and explicit session date required")
        if decimal(self.open) <= 0 or decimal(self.close) <= 0 or decimal(self.volume) < 0:
            raise ValueError("invalid opening window")
        closed = datetime.combine(self.session, time(9, 35), ZoneInfo("America/New_York"))
        if type(self.known_at_ns) is not int or self.known_at_ns < int(closed.timestamp()) * NS:
            raise ValueError("opening window cannot be known before 09:35 ET")


def opening_window(
    bars: tuple[Bar, ...],
    *,
    session_open_ns: int,
    as_of_ns: int,
    coverage_complete: bool | None,
) -> OpeningWindow | None:
    """Accept one native 5m bar or five native 1m bars, close-stamped per row 11.

    No synthetic trades, partial-window extrapolation, missing-minute zero fill,
    calendar lookup or native aggregation reimplementation. Receipt may lag close.
    coverage_complete is independent source evidence, never inferred from count.
    """
    if any(type(t) is not int or t < 0 for t in (session_open_ns, as_of_ns)):
        raise ValueError("nonnegative nanosecond clocks required")
    opened = datetime.fromtimestamp(session_open_ns // NS, ZoneInfo("America/New_York"))
    if (opened.hour, opened.minute, opened.second) != (9, 30, 0) or session_open_ns % NS:
        raise ValueError("published screen requires the 09:30 ET RTH open")
    if coverage_complete is not True or not bars:
        return None
    first = bars[0]
    spec = first.bar_type.spec
    if spec.aggregation != BarAggregation.MINUTE or spec.step not in (1, 5):
        raise ValueError("native 1m or 5m opening bars required")
    if spec.price_type != PriceType.LAST:
        raise ValueError("published share-volume screen requires LAST bars")
    interval = spec.step * 60 * NS
    if len(bars) * interval != 5 * 60 * NS:
        return None
    for i, bar in enumerate(bars, 1):
        if bar.bar_type != first.bar_type:
            raise ValueError("one instrument and bar type per opening window")
        if bar.ts_event != session_open_ns + i * interval:
            return None
        if bar.ts_init < bar.ts_event:
            raise ValueError("bar receipt precedes completion")
        if bar.ts_init > as_of_ns:
            return None
    return OpeningWindow(
        first.bar_type.instrument_id,
        opened.date(),
        first.open.as_decimal(),
        bars[-1].close.as_decimal(),
        sum((b.volume.as_decimal() for b in bars), Decimal(0)),
        max(b.ts_init for b in bars),
    )


@dataclass(frozen=True)
class DailyFacts:
    """Caller supplies ADV and native ATR for the SAME completed prior 14 sessions.

    Do not rebuild AverageTrueRange here. Native smoothing/initialization and any
    extra warm-up history must be resolved under #129 and bound at admission;
    citing Wilder does not by itself resolve the paper's precise implementation.
    Unknown or uninitialized ATR remains None, not zero.
    """

    instrument_id: InstrumentId
    sessions: tuple[date, ...]
    adv: Decimal | None
    atr: Decimal | None
    known_at_ns: int

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise ValueError("native instrument required")
        if type(self.known_at_ns) is not int or self.known_at_ns < 0:
            raise ValueError("nonnegative daily-facts availability required")
        if any(type(session) is not date for session in self.sessions):
            raise ValueError("explicit daily-facts session dates required")
        if self.sessions:
            closed = datetime.combine(
                max(self.sessions) + timedelta(days=1), time.min, ZoneInfo("America/New_York")
            )
            if self.known_at_ns < int(closed.timestamp()) * NS:
                raise ValueError("daily facts precede completed prior sessions (row 11)")
        for value in (self.adv, self.atr):
            if value is not None and decimal(value) < 0:
                raise ValueError("nonnegative daily facts required")


@dataclass(frozen=True)
class Screen:
    rvol: Decimal | None
    passes_local_filters: bool | None
    reason: str
    params_hash: str = PARAMS_HASH
    # No top-20 membership, breakout direction, entry, stop, risk or leverage.


def screen(
    current: OpeningWindow | None,
    prior: tuple[OpeningWindow, ...],
    *,
    expected_sessions: tuple[date, ...],
    facts: DailyFacts | None,
    as_of_ns: int,
) -> Screen:
    if current is None:
        return Screen(None, None, "opening_window_unavailable")
    if type(as_of_ns) is not int or as_of_ns < current.known_at_ns:
        return Screen(None, None, "not_yet_available")
    if (
        len(expected_sessions) != 14
        or tuple(sorted(set(expected_sessions))) != expected_sessions
        or expected_sessions[-1] >= current.session
        or tuple(w.session for w in prior) != expected_sessions
    ):
        return Screen(None, None, "prior_14_sessions_unavailable")
    for window in (current, *prior):
        if window.instrument_id != current.instrument_id:
            raise ValueError("mixed instruments")
        if window.known_at_ns > as_of_ns:
            return Screen(None, None, "not_yet_available")
        if decimal(window.volume) < 0 or decimal(window.open) <= 0 or decimal(window.close) <= 0:
            raise ValueError("invalid opening window")
    baseline = sum((w.volume for w in prior), Decimal(0)) / 14
    if baseline == 0:
        return Screen(None, None, "zero_opening_volume_baseline")
    rvol = current.volume / baseline
    if facts is None or facts.adv is None or facts.atr is None:
        return Screen(rvol, None, "daily_facts_unavailable")
    if facts.instrument_id != current.instrument_id or facts.sessions != expected_sessions:
        return Screen(rvol, None, "daily_facts_identity_mismatch")
    if facts.known_at_ns > as_of_ns:
        return Screen(rvol, None, "daily_facts_not_yet_available")
    if decimal(facts.adv) < 0 or decimal(facts.atr) < 0:
        raise ValueError("invalid daily facts")
    passed = (
        current.open > 5 and facts.adv >= 1_000_000 and facts.atr > Decimal("0.50") and rvol >= 1
    )
    return Screen(rvol, passed, "local_filters_only_top20_external")
