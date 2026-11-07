"""A partial segment reconstruction must never become eligible state."""

from decimal import Decimal as D

import pytest

from sextant.entry.signals import Surge
from sextant.entry.tape import Tape

from .conftest import IID, SEC, START
from .test_signals import feed, state


@pytest.mark.parametrize("fault", [None, MemoryError, ValueError], ids=["clean", "memory", "value"])
def test_reset_installs_only_a_complete_new_segment(monkeypatch, fault):
    s = state()
    for at, price in [
        (98, "9.00"),
        (100, "10.01"),
        ("100.2", "10.02"),
        ("100.4", "9.95"),
        ("100.6", "10.03"),
        ("100.8", "10.04"),
    ]:
        assert feed(s, at, price)
    fold, last, tape, segment = s.fold, s.last, s.tape, s.segment
    original, visits = Tape.add, 0

    def interrupted(self, *args):
        nonlocal visits
        visits += 1
        if fault and visits == 3:  # Interrupt immediately before the lower-price veto.
            raise fault("reset reconstruction failed")
        return original(self, *args)

    with monkeypatch.context() as patch:
        patch.setattr(Tape, "add", interrupted)
        try:
            s.reset_segment("next", start_ns=START + 100 * SEC)
        except (MemoryError, ValueError):
            pass  # Native dispatchers/callers may swallow the exception.
    if fault:
        assert s.failure == f"{fault.__name__}: reset reconstruction failed"
        assert s.fold is fold and s.last is last and s.tape is tape and s.segment == segment
        assert not s.fresh(START + 101 * SEC)
        assert not feed(s, 101, "10.05")
        s.reset_segment("next", start_ns=START + 100 * SEC)
    assert s.failure is None and s.segment == "next"
    assert feed(s, 101, "10.05")
    s.arm(
        Surge(IID, "next", START + 100 * SEC, START + 100 * SEC, START + 160 * SEC, D(10), "TEST")
    )
    # Complete control retains the veto: its subsequent rising run spans only 0.4 seconds.
    assert not s.first_leg_ready(D("10.05"), START + 101 * SEC)
