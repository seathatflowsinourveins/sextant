from decimal import Decimal

import pytest

from sextant.entry.slots import Allocation, Candidate, SlotPool


def _candidates(
    count: int, unqualified: frozenset[int] = frozenset(), *, prefix: str = "S"
) -> tuple[Candidate, ...]:
    return tuple(
        Candidate(
            symbol=f"{prefix}{index:02}",
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
    allocation = SlotPool().allocate(
        _candidates(7),
        max_armed_symbols=7,
        potential=_candidates(4, prefix="P"),
        retained=frozenset(),
        mover_armed=frozenset(),
    )
    assert allocation.slots == 3
    assert allocation.armed == ("P00", "P01", "P02", "P03", "S00", "S01", "S02")


def test_five_slot_account_must_not_arm_eight():
    allocation = SlotPool().allocate(
        _candidates(20, prefix="M"),
        max_armed_symbols=5,
        potential=(),
        retained=frozenset(),
        mover_armed=frozenset(),
    )
    assert allocation.armed == ("M00", "M01", "M02", "M03", "M04")
    assert len(allocation.chosen) == 5
    assert allocation.slots == 2
    assert allocation.mover_armed == frozenset({"M00", "M01", "M02", "M03", "M04"})


def test_five_slot_pool_two_retained_potential_no_new_potential():
    allocation = SlotPool().allocate(
        _candidates(5, prefix="M"),
        max_armed_symbols=5,
        potential=(),
        retained=frozenset({"P00", "P01"}),
        mover_armed=frozenset(),
    )
    assert allocation.armed == ("M00", "M01", "M02")
    assert allocation.chosen == frozenset({"P00", "P01", "M00", "M01", "M02"})
    assert allocation.mover_armed == frozenset({"M00", "M01", "M02"})


@pytest.mark.parametrize(
    ("retained", "mover_armed", "reason"),
    (
        (None, frozenset(), "custody_unknown"),
        (frozenset(), None, "custody_unknown"),
        (-1, frozenset(), "custody_invalid"),
        (frozenset(), -1, "custody_invalid"),
    ),
)
def test_unknown_or_invalid_custody_arms_nothing(retained, mover_armed, reason):
    allocation = SlotPool().allocate(
        _candidates(5),
        max_armed_symbols=5,
        potential=_candidates(5, prefix="P"),
        retained=retained,
        mover_armed=mover_armed,
    )
    assert allocation == Allocation((), 0, reason, frozenset(), frozenset())
    assert not allocation


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
    allocation = pool.allocate(
        candidates,
        max_armed_symbols=5,
        potential=_candidates(3, prefix="P"),
        retained=frozenset(),
        mover_armed=frozenset(),
    )
    assert allocation.armed[:3] == ("P00", "P01", "P02")
    assert allocation.armed[3:] == expected


def test_unqualified_and_unused_slots_pass_over():
    pool = SlotPool()
    candidates = _candidates(5, frozenset({0}))
    allocation = pool.allocate(
        candidates,
        max_armed_symbols=5,
        potential=_candidates(2, frozenset({0, 1}), prefix="P"),
        retained=frozenset(),
        mover_armed=frozenset(),
    )
    assert allocation.armed == ("S01", "S02", "S03", "S04")
    assert pool.allocate(
        (), max_armed_symbols=5, potential=(), retained=frozenset(), mover_armed=frozenset()
    ) == Allocation((), 2, "pass", frozenset(), frozenset())


@pytest.mark.parametrize(
    ("potential_count", "mover_count", "retained", "mover_armed", "expected", "expected_movers"),
    (
        (5, 5, (), (), ("P00", "P01", "P02", "M00", "M01"), ("M00", "M01")),
        (2, 5, (), (), ("P00", "P01", "M00", "M01", "M02"), ("M00", "M01", "M02")),
        (5, 1, (), (), ("P00", "P01", "P02", "M00", "P03"), ("M00",)),
        (5, 0, (), (), ("P00", "P01", "P02", "P03", "P04"), ()),
        (5, 5, ("M00",), ("M00",), ("P00", "P01", "P02", "M01"), ("M00", "M01")),
        (5, 5, ("P00", "M00"), ("M00",), ("P01", "P02", "M01"), ("M00", "M01")),
        (
            5,
            5,
            ("M00", "M01", "M02"),
            ("M00", "M01", "M02"),
            ("P00", "P01"),
            ("M00", "M01", "M02"),
        ),
        (5, 5, ("P00", "P01", "P02", "P03"), (), ("M00",), ("M00",)),
        (
            5,
            5,
            ("P00", "P01", "P02", "M00", "M01", "M02"),
            ("M00", "M01", "M02"),
            (),
            ("M00", "M01", "M02"),
        ),
        (5, 5, (), ("OLD",), ("P00", "P01", "P02", "M00", "M01"), ("M00", "M01")),
        (1, 1, (), (), ("P00", "M00"), ("M00",)),
        (0, 0, ("P00", "M00"), ("M00",), (), ("M00",)),
    ),
    ids=(
        "both-quotas",
        "potential-to-mover-pass-over",
        "mover-to-potential-pass-over",
        "potential-takes-all-unused-mover-places",
        "retained-mover-charged-to-mover-pool",
        "mixed-retained-membership",
        "retained-movers-over-quota",
        "retained-potential-over-quota",
        "retained-over-total-capacity",
        "previously-armed-but-not-retained",
        "both-pools-sparse",
        "retained-without-candidates",
    ),
)
def test_the_sourced_two_pool_contract(
    potential_count, mover_count, retained, mover_armed, expected, expected_movers
):
    allocation = SlotPool().allocate(
        _candidates(mover_count, prefix="M"),
        max_armed_symbols=5,
        potential=_candidates(potential_count, prefix="P"),
        retained=frozenset(retained),
        mover_armed=frozenset(mover_armed),
    )
    assert allocation.armed == expected
    assert allocation.chosen == frozenset(retained) | frozenset(expected)
    assert allocation.mover_armed == frozenset(expected_movers)


def test_overlapping_and_duplicate_candidates_consume_only_one_place():
    allocation = SlotPool().allocate(
        tuple(Candidate(symbol, 0) for symbol in ("M00", "M01", "M01", "M02", "M03")),
        max_armed_symbols=5,
        potential=tuple(Candidate(symbol, 0) for symbol in ("P00", "P00", "M00", "P01")),
        retained=frozenset(),
        mover_armed=frozenset(),
    )
    assert allocation.armed == ("P00", "M00", "P01", "M01", "M02")
    assert len(allocation.chosen) == 5
    assert allocation.mover_armed == frozenset({"M01", "M02"})


def test_retained_mover_in_potential_candidates_keeps_its_pool():
    allocation = SlotPool().allocate(
        _candidates(5, prefix="M"),
        max_armed_symbols=5,
        potential=(Candidate("M00", 0), *_candidates(3, prefix="P")),
        retained=frozenset({"M00"}),
        mover_armed=frozenset({"M00"}),
    )
    assert allocation.armed == ("P00", "P01", "P02", "M01")
    assert allocation.mover_armed == frozenset({"M00", "M01"})


def test_retained_membership_survives_unqualified_current_candidates():
    allocation = SlotPool().allocate(
        (Candidate("M00", 0, qualified=False),),
        max_armed_symbols=5,
        potential=(Candidate("P00", 0, qualified=False),),
        retained=frozenset({"P00", "M00"}),
        mover_armed=frozenset({"M00"}),
    )
    assert allocation.armed == ()
    assert allocation.chosen == frozenset({"P00", "M00"})
    assert allocation.mover_armed == frozenset({"M00"})


@pytest.mark.parametrize(
    ("released", "expected", "expected_movers"),
    (("P02", ("P03",), ("M00", "M01")), ("M01", ("M02",), ("M00", "M02"))),
)
def test_pool_membership_round_trips_between_refreshes(released, expected, expected_movers):
    pool = SlotPool()
    first = pool.allocate(
        _candidates(2, prefix="M"),
        max_armed_symbols=5,
        potential=_candidates(3, prefix="P"),
        retained=frozenset(),
        mover_armed=frozenset(),
    )
    second = pool.allocate(
        (Candidate("M02", 0),),
        max_armed_symbols=5,
        potential=(Candidate("P03", 0),),
        retained=first.chosen - {released},
        mover_armed=first.mover_armed,
    )
    assert second.armed == expected
    assert second.mover_armed == frozenset(expected_movers)
    assert second.chosen == first.chosen - {released} | frozenset(expected)


def test_the_share_is_decimal_not_float():
    assert SlotPool().share == Decimal("0.4")
