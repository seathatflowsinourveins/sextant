from decimal import Decimal

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


def test_the_recorded_share_gives_two_of_five_and_eight_of_twenty():
    pool = SlotPool()
    assert pool.slots(5) == 2
    assert pool.slots(20) == 8
    assert pool.slots(0) == 0
    assert pool.slots(7) == 2  # 2.8 floors to the recorded whole-slot count


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


def test_first_moved_order_is_the_fill_order():
    pool = SlotPool()
    candidates = (
        Candidate("LATE", first_moved_ns=30),
        Candidate("EARLY", first_moved_ns=10),
        Candidate("MIDDLE", first_moved_ns=20),
        Candidate("LATER", first_moved_ns=40),
        Candidate("LAST", first_moved_ns=50),
    )
    assert pool.allocate(candidates, custody_open=0).armed == ("EARLY", "MIDDLE")


def test_unqualified_and_unused_slots_pass_over():
    pool = SlotPool()
    candidates = _candidates(5, frozenset({0}))
    allocation = pool.allocate(candidates, custody_open=0)
    assert allocation.armed == ("S1", "S2")
    assert pool.allocate((), custody_open=0) == Allocation((), 0, "pass")


def test_the_share_is_decimal_not_float():
    assert SlotPool().share == Decimal("0.4")
