# Carried from seathatflowsinourveins/northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:
# src/northstar_trading/catalysts/pit.py, verbatim (ADR-0013 clocks).
"""Pure backfill visibility policies, returning integer UTC nanoseconds.

Upstream checked: pandas@3.0.6:pandas/tseries/holiday.py:628
(`USFederalHolidayCalendar`; `holidays(start, end)` is at line 496).
Exceptional SEC closures supplement that recurring federal calendar.

Policy and evidence: docs/research/2026-10-22-plan-catalyst-backfill-93i3.md
(Task 2, amendments A1/A4/A14/A16), 2026-10-22-edgar-acceptance-times.md
(E10-E15), and 2026-10-22-alpaca-news-provider-mix.md (N17).
These estimates are unverified for historical availability: callers must set
attrs["pit_verified"] = "false" on policy-timed rows (Global Constraints).
"""

from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from zoneinfo import ZoneInfo

from pandas.tseries.holiday import USFederalHolidayCalendar

_NS = 10**9
_ET = ZoneInfo("America/New_York")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Interim: E10's one observed 06:00 batch ended 06:03:36 ET (5 s polling granularity).
BATCH_END_ET = time(6, 10)
# Interim E10: 126 filings drained 06:00:48-06:03:36, about 45/min in one batch.
BATCH_DRAIN_PER_MIN = 45
# Conservative policy margin beyond the estimated drain, pending more batches.
BATCH_MARGIN_MIN = 5
# Interim: E13's outage-filtered Atom lag had p99 120.8 s, max 183.2 s; 180 s failed.
INTRADAY_MARGIN_S = 300

# E11, 17 CFR 232.13(a)(4): 3/4/5 (2003) and Schedule 14N (2010) predate this backfill.
# Form 144: FR 2023-03931, effective 2023-03-20.
# Schedules 13D/13G: FR 2023-22678, effective 2024-02-05, under both EDGAR spellings.
_BASE_TEN_PM_SINCE = {
    "3": date.min,
    "4": date.min,
    "5": date.min,
    "SC 14N": date.min,
    "SCHEDULE 14N": date.min,
    "144": date(2023, 3, 20),
    "SC 13D": date(2024, 2, 5),
    "SCHEDULE 13D": date(2024, 2, 5),
    "SC 13G": date(2024, 2, 5),
    "SCHEDULE 13G": date(2024, 2, 5),
}
TEN_PM_SINCE: dict[str, date] = {
    form + suffix: since for form, since in _BASE_TEN_PM_SINCE.items() for suffix in ("", "/A")
}
TEN_PM_FORMS: frozenset[str] = frozenset(TEN_PM_SINCE)

# A4; SEC notices checked in facts-gpt-search.md section A (read 2026-10-22).
# Update from https://www.sec.gov/submit-filings/edgar-news-announcements
# Missing future closures are calendar data bugs; these exceptions do not recur.
EDGAR_CLOSURES: frozenset[date] = frozenset(
    {
        # https://www.sec.gov/newsroom/whats-new/edgar-be-closed-wednesday-december-5-2018
        date(2018, 12, 5),
        # https://www.sec.gov/newsroom/whats-new/december-24-2018-federal-holiday-edgar-filing-purposes
        date(2018, 12, 24),
        # https://www.sec.gov/newsroom/whats-new/edgar-will-be-closed-tuesday-december-24-2019-wednesday-december-25-2019
        date(2019, 12, 24),
        # https://www.sec.gov/filergroup/announcements-old/edgar-holiday-closure-2020
        date(2020, 12, 24),
        # https://www.sec.gov/newsroom/whats-new/edgar-closed-24-25-december-2024
        date(2024, 12, 24),
        # https://www.sec.gov/newsroom/whats-new/edgar-closed-january-9-2025
        date(2025, 1, 9),
        # https://www.sec.gov/newsroom/whats-new/edgar-will-be-closed-december-24-2025-through-december-26-2025
        date(2025, 12, 24),
        # https://www.sec.gov/newsroom/whats-new/edgar-will-be-closed-december-24-2025-through-december-26-2025
        date(2025, 12, 26),
    }
)

# Interim, N17 (one session, 2026-10-22): Benzinga REST publication follows this grid.
NEWS_BATCH_S = 300
# N17: measured first sight was at most 18.2 s after the grid mark.
NEWS_BATCH_MARGIN_S = 60
# N17: fiscal.ai's measured maximum lag was 110 s (stream).
NEWS_MIN_LAG_S = 180


def _to_ns(instant: datetime) -> int:
    delta = instant.astimezone(UTC) - _EPOCH
    return (delta.days * 86400 + delta.seconds) * _NS + delta.microseconds * 1000


def _eastern_date(instant_ns: int) -> date:
    # Whole seconds suffice to select a local calendar date, even for negative ns.
    return (_EPOCH + timedelta(seconds=instant_ns // _NS)).astimezone(_ET).date()


def _at_et(day: date, clock: time) -> int:
    return _to_ns(datetime.combine(day, clock, tzinfo=_ET))


def et_local_to_ns(text: str, fmt: str = "%Y%m%d%H%M%S") -> int:
    """Parse Eastern header text; choose fold=0 (EDT) and reject DST gaps."""
    local = datetime.strptime(text, fmt).replace(tzinfo=_ET, fold=0)
    round_trip = local.astimezone(UTC).astimezone(_ET)
    if round_trip.replace(tzinfo=None) != local.replace(tzinfo=None):
        raise ValueError(f"Nonexistent Eastern local time: {text}")
    return _to_ns(local)


@cache
def _federal_holidays(year: int) -> frozenset[date]:
    # Explicit year bounds include holidays observed across a year boundary.
    holidays = USFederalHolidayCalendar().holidays(start=date(year, 1, 1), end=date(year, 12, 31))
    return frozenset(holiday.date() for holiday in holidays)


def sec_business_day(d: date) -> bool:
    """Exclude weekends, recurring federal holidays and dated EDGAR closures."""
    return d.weekday() < 5 and d not in EDGAR_CLOSURES and d not in _federal_holidays(d.year)


def next_sec_business_day(d: date) -> date:
    """Return the first SEC business day strictly after d."""
    candidate = d + timedelta(days=1)
    while not sec_business_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def batch_end_for(late_count: int) -> time:
    """Estimate the 06:00 batch's end from its size, keeping the 06:10 floor."""
    drain_minutes = -(-late_count // BATCH_DRAIN_PER_MIN)
    hour, minute = divmod(6 * 60 + drain_minutes + BATCH_MARGIN_MIN, 60)
    return max(BATCH_END_ET, time(hour, minute))


def sec_backfill(
    acceptance_ns: int, form: str, disseminated: date, *, batch_end: time | None = None
) -> tuple[int, str]:
    """Apply the SEC window, batch margin, then the index-file dissemination floor.

    Cutoffs are inclusive. ``disseminated`` is the daily index file's date,
    never the Date Filed column or the acceptance date (A1).
    ``batch_end`` defaults to the historical 06:10 estimate when omitted.
    """
    day = _eastern_date(acceptance_ns)
    business_day = sec_business_day(day)
    batch_end = BATCH_END_ET if batch_end is None else batch_end
    batch_ns = _at_et(day, batch_end)
    since = TEN_PM_SINCE.get(form)
    cutoff = time(22) if since is not None and day >= since else time(17, 30)
    margined_ns = acceptance_ns + INTRADAY_MARGIN_S * _NS

    if business_day and batch_ns <= acceptance_ns <= _at_et(day, cutoff):
        visible_ns, rule = margined_ns, "acceptance_plus_5m"
    else:
        if not business_day or acceptance_ns > batch_ns:
            batch_ns = _at_et(next_sec_business_day(day), batch_end)
        visible_ns, rule = max(margined_ns, batch_ns), "late_next_bd"

    if _eastern_date(visible_ns) < disseminated:
        return _at_et(disseminated, time(23, 59, 59)), "disseminated_eod"
    return visible_ns, rule


def alpaca_news_backfill(updated_ns: int) -> int:
    """Wait for both the next REST batch plus its margin and the minimum lag."""
    batch_ns = NEWS_BATCH_S * _NS
    next_batch_ns = -(-updated_ns // batch_ns) * batch_ns
    return max(next_batch_ns + NEWS_BATCH_MARGIN_S * _NS, updated_ns + NEWS_MIN_LAG_S * _NS)


def fred_vintage_ts_init(realtime_start: date) -> int:
    """Estimate vintage visibility at 23:59:59 ET of the next SEC business day."""
    return _at_et(next_sec_business_day(realtime_start), time(23, 59, 59))


def finra_si_ts(publication: date) -> int:
    """Return publication 16:40 ET, shared by short-interest event and init times."""
    return _at_et(publication, time(16, 40))


def regsho_ts(trade_date: date) -> int:
    """Return 18:00 ET on the original Reg SHO file's trade date."""
    return _at_et(trade_date, time(18))
