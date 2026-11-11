"""The pit and EDGAR nanosecond helpers use the engine's ``dt_to_unix_nanos``.

Source: ``nautechsystems/nautilus_trader@v2.0.0rc8``
``d53849b216e20f2c122ca01b4dd0da377638b186``,
``python/nautilus_trader/core/datetime.py:81-104`` (``dt_to_unix_nanos``;
the private path reads a naive value as UTC at ``:123-125``).  This is the
data half of LEAD-1105 section 2.  Both call sites use that function as is;
``edgar_feed`` keeps its own aware-only guard because a naive read-as-UTC
value is a point-in-time hazard.  These tests are the RED witness: on the old
arithmetic the delegation tests fail, and only the engine import can make
them pass.
"""

import inspect
from datetime import datetime
from pathlib import Path
from types import ModuleType
from zoneinfo import ZoneInfo

import pytest
from nautilus_trader.core.datetime import dt_to_unix_nanos

from sextant.data import edgar_feed, pit

ET = ZoneInfo("America/New_York")

# Each side of both 2026 America/New_York DST changes (the fall change's
# repeated 01:00 hour is pinned with fold=1), a microsecond-bearing instant,
# and an instant before the 1970 epoch.  Literals are computed independently
# of the two helpers.
_CASES: tuple[tuple[str, datetime, int], ...] = (
    (
        "spring-before-0200",
        datetime(2026, 3, 8, 1, 59, 59, 999999, tzinfo=ET),
        1772953199999999000,
    ),
    (
        "spring-after-0300",
        datetime(2026, 3, 8, 3, 0, 0, tzinfo=ET),
        1772953200000000000,
    ),
    (
        "fall-before-0200",
        datetime(2026, 11, 1, 1, 59, 59, 999999, tzinfo=ET),
        1793512799999999000,
    ),
    (
        "fall-after-0100-fold1",
        datetime(2026, 11, 1, 1, 0, 0, tzinfo=ET, fold=1),
        1793512800000000000,
    ),
    (
        "fall-after-0200",
        datetime(2026, 11, 1, 2, 0, 0, tzinfo=ET),
        1793516400000000000,
    ),
    (
        "microsecond-bearing",
        datetime(2026, 6, 15, 12, 34, 56, 789012, tzinfo=ET),
        1781541296789012000,
    ),
    (
        "before-1970",
        datetime(1969, 7, 20, 20, 17, 40, 123456, tzinfo=ET),
        -14168539876544000,
    ),
)

_HELPERS: tuple[tuple[str, ModuleType, str], ...] = (
    ("pit._to_ns", pit, "_to_ns"),
    ("edgar_feed._to_ns", edgar_feed, "_to_ns"),
)


def test_the_function_is_the_installed_engines_module_member() -> None:
    assert dt_to_unix_nanos.__module__ == "nautilus_trader.core.datetime"
    provenance = inspect.getsourcefile(dt_to_unix_nanos)
    assert provenance is not None
    assert Path(provenance).parts[-4:] == (
        "site-packages",
        "nautilus_trader",
        "core",
        "datetime.py",
    )


@pytest.mark.parametrize(
    ("helper", "module", "helper_name"),
    _HELPERS,
    ids=[helper for helper, _, _ in _HELPERS],
)
@pytest.mark.parametrize(
    ("value", "expected_ns"),
    [(value, expected_ns) for _, value, expected_ns in _CASES],
    ids=[case_id for case_id, _, _ in _CASES],
)
def test_each_helper_equals_the_engine(
    helper: object,
    module: ModuleType,
    helper_name: str,
    value: datetime,
    expected_ns: int,
) -> None:
    assert dt_to_unix_nanos(value) == expected_ns
    assert getattr(module, helper_name)(value) == expected_ns


@pytest.mark.parametrize(
    ("module", "helper_name"),
    [(module, helper_name) for _, module, helper_name in _HELPERS],
    ids=[helper for helper, _, _ in _HELPERS],
)
def test_each_helper_gets_its_value_from_the_engine(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    helper_name: str,
) -> None:
    assert module.dt_to_unix_nanos is dt_to_unix_nanos
    sentinel = 7_012_345_678_901_234_567
    monkeypatch.setattr(module, "dt_to_unix_nanos", lambda _value: sentinel)
    value = _CASES[0][1]
    assert getattr(module, helper_name)(value) == sentinel


def test_the_edgar_helper_still_refuses_a_naive_instant() -> None:
    naive = datetime(2026, 6, 15, 12, 34, 56)
    with pytest.raises(ValueError, match="timezone-aware"):
        edgar_feed._to_ns(naive)


def test_the_engine_alone_reads_a_naive_instant_as_utc() -> None:
    # The guard above is load-bearing: without it this naive value would pass
    # as 2026-06-15T12:34:56Z, four hours before the Eastern wall clock.
    naive = datetime(2026, 6, 15, 12, 34, 56)
    assert dt_to_unix_nanos(naive) == 1781526896000000000
