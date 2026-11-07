"""XNYS session slice from northstar-trading@8256c16c:sessions.py.

This describes the exchange schedule, never broker/instrument eligibility.
IB's narrower dated windows and maintenance are supplied by its account slice.
"""

from datetime import date, datetime, time, timedelta
from enum import StrEnum
from functools import cache
from zoneinfo import ZoneInfo

from exchange_calendars import get_calendar

ET = ZoneInfo("America/New_York")
SECOND = 1_000_000_000


class Session(StrEnum):
    OVERNIGHT = "overnight"
    PRE = "pre"
    RTH = "rth"
    POST = "post"
    CLOSED = "closed"


@cache
def _calendar(year: int):
    return get_calendar("XNYS", start=date(year - 1, 12, 1), end=date(year + 1, 1, 31), side="left")


def session_at(ts_ns: int) -> Session:
    """Half-open event-clock sessions, actual XNYS close, and 17:00 early post close."""
    if type(ts_ns) is not int or ts_ns < 0:
        raise ValueError("integer event nanoseconds required")
    local = datetime.fromtimestamp(ts_ns // SECOND, tz=ET)
    day = (local + timedelta(hours=4)).date()
    calendar = _calendar(day.year)
    if not calendar.is_session(day):
        return Session.CLOSED
    at = local.time()
    if at >= time(20) or at < time(4):
        return Session.OVERNIGHT
    if at < time(9, 30):
        return Session.PRE
    close = calendar.session_close(local.date()).tz_convert(ET).time()
    if at < close:
        return Session.RTH
    if close < time(16) and at >= time(17):
        return Session.CLOSED
    return Session.POST
