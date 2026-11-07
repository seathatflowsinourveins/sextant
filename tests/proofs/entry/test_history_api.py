"""n1n2ctl API-level probes at 1aacf97 (no in-PR caller exercises these paths)."""

from decimal import Decimal as D

from sextant.entry.signals import Surge

from .conftest import IID, SEC, START, trade
from .test_signals import extended_state, feed, state


def test_probe_reset_after_first_new_segment_prints_drops_them_from_vwap():
    """reset_segment(start_ns) deletes every retained print, including prints whose event
    time is at/after start_ns.  Same-segment prints then enter VWAP only if they arrive
    after the reset call (as late prints), never if they arrived before it."""
    s = state()
    feed(s, 98, "9.00", size=5000)
    early = [trade("100", "10.00", size=1000), trade("100.01", "10.00", size=1000)]
    for t in early:  # new-segment prints that arrive just before the boundary handler runs
        assert s.on_trade(t, now=t.ts_init)
    s.reset_segment("next-segment", start_ns=START + 100 * SEC)
    feed(s, "100.02", "11.00", size=100)
    late_same_segment = trade("100.005", "10.00", size=1000, lag=25_000_000)
    s.on_trade(late_same_segment, now=late_same_segment.ts_init)
    exact = (D("10.00") * 3000 + D("11.00") * 100) / 3100
    print("PROBE reset vwap", s.vwap, "volume", s.volume, "exact over event-time segment", exact)
    assert s.vwap == exact, s.vwap


def test_probe_arm_after_late_print_resurrects_a_consumed_reclaim_event():
    """E1 motif: the late 10.02 @ t6.5 arriving at t9.5 makes t9 the time-ordered first chance;
    on_trade nulls the event.  A later arm() rebuild sets reclaim_event_ns back to t9."""
    s = extended_state()
    for at, price in [(3, "10.03"), (4, "10.04"), (5, "10.05")] + [
        (at, "10.03") for at in (6, 7, 8, 9)
    ]:
        feed(s, at, price)
    late = trade("6.5", "10.02", lag=3_000_000_000)
    assert not s.on_trade(late, now=late.ts_init)
    now = START + int(D("9.6") * SEC)
    before = s.reclaim_ready(D("10.03"), D("0.10"), now, covered_flow=True)
    s.arm(
        Surge(
            IID,
            "fixture-segment",
            START + 9 * SEC,
            START + 9 * SEC,
            START + 60 * SEC,
            D("10"),
            "TEST",
        )
    )
    after = s.reclaim_ready(D("10.03"), D("0.10"), now, covered_flow=True)
    print(
        "PROBE arm resurrect: event",
        s.reclaim_event_ns and (s.reclaim_event_ns - START) / SEC,
        before,
        after,
    )
    assert not after
