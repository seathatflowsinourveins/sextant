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


# E11, 17 CFR 232.13(a)(4): 3/4/5 (2003) and Schedule 14N (2010) predate this backfill.
# Form 144: FR 2023-03931, effective 2023-03-20.

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


def _at_et(day: date, clock: time) -> int:
    return _to_ns(datetime.combine(day, clock, tzinfo=_ET))


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
