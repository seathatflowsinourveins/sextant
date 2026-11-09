from decimal import Decimal

import pytest

from sextant.entry.slots import Allocation, Candidate, SlotPool


def _candidates(count: int, unqualified: frozenset[int] = frozenset()) -> tuple[Candidate, ...]:
    return tuple(
        Candidate(
            symbol=f"S{index}",
            first_moved_ns=index,
            qualified=index not in unqualified,
        )
        for index in range(count)
    )


@pytest.mark.parametrize(
    ("count", "expected"),
    (
        (-1, 0),
        (0, 0),
        (1, 1),
        (2, 1),
        (3, 2),
        (4, 2),
        (5, 2),
        (6, 3),
        (7, 3),
        (8, 4),
        (9, 4),
        (10, 4),
        (20, 8),
    ),
)
def test_the_recorded_share_rounds_up(count: int, expected: int):
    assert SlotPool().slots(count) == expected


def test_allocation_uses_the_ceiling_rounded_reservation():
    assert SlotPool().allocate(_candidates(7), custody_open=0) == Allocation(
        ("S0", "S1", "S2"), 3, "filled"
    )


def test_custody_counts_first_and_the_pool_is_shared():
    pool = SlotPool()
    five = pool.allocate(_candidates(5), custody_open=2)
    assert five == Allocation((), 2, "pass")
    twenty = pool.allocate(_candidates(20), custody_open=2)
    assert twenty.slots == 8
    assert len(twenty.armed) == 6


def test_unknown_or_invalid_custody_arms_nothing():
    pool = SlotPool()
    assert pool.allocate(_candidates(5), custody_open=None).reason == "custody_unknown"
    assert pool.allocate(_candidates(5), custody_open=-1).reason == "custody_invalid"


@pytest.mark.parametrize(
    ("best_qualified", "expected"),
    ((True, ("BEST", "SECOND")), (False, ("SECOND", "LOW"))),
)
def test_the_callers_ranking_is_preserved_over_first_moved_order(
    best_qualified: bool, expected: tuple[str, ...]
):
    pool = SlotPool()
    candidates = (
        Candidate("BEST", first_moved_ns=30, qualified=best_qualified),
        Candidate("SECOND", first_moved_ns=40),
        Candidate("LOW", first_moved_ns=10),
        Candidate("LOWER", first_moved_ns=20),
        Candidate("LAST", first_moved_ns=50),
    )
    assert pool.allocate(candidates, custody_open=0).armed == expected


def test_unqualified_and_unused_slots_pass_over():
    pool = SlotPool()
    candidates = _candidates(5, frozenset({0}))
    allocation = pool.allocate(candidates, custody_open=0)
    assert allocation.armed == ("S1", "S2")
    assert pool.allocate((), custody_open=0) == Allocation((), 0, "pass")


def test_the_share_is_decimal_not_float():
    assert SlotPool().share == Decimal("0.4")
