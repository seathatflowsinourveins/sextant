"""N2 segment boundaries and exact deduplication without a segment-sized heap."""

import gc
import tracemalloc
from decimal import Decimal as D

import pytest

from .conftest import SEC, START, trade
from .test_signals import arm, feed, state


@pytest.mark.parametrize("lag", [2 * SEC, 600 * SEC], ids=["late", "stale"])
def test_prior_segment_straggler_cannot_change_new_segment_vwap(lag):
    s = state()
    feed(s, 98, "10.00")
    s.reset_segment("next-segment", start_ns=START + 100 * SEC)
    for at in (101, 102):
        feed(s, at, "10.00")
    old = trade(99, "8.00", size=50000, lag=lag)
    assert not s.on_trade(old, now=max(old.ts_init, START + 103 * SEC))
    assert s.volume == 200 and s.vwap == D("10.00")


def test_segment_start_is_inclusive_and_resets_identity_scope():
    s = state()
    tick = trade(100, "10.00")
    assert s.on_trade(tick, now=tick.ts_init)
    s.reset_segment("next-segment", start_ns=tick.ts_event)
    assert s.on_trade(tick, now=tick.ts_init)
    assert not s.on_trade(tick, now=tick.ts_init)
    assert s.volume == 100


def test_full_segment_dedup_does_not_keep_each_print_on_the_python_heap(record_property):
    s = state()
    gc.collect()
    tracemalloc.start()
    try:
        for i in range(20000):
            tick = trade(str(D(i) / 100000), "10.00", identity=f"memory-{i}")
            assert s.on_trade(tick, now=tick.ts_init)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # Fixture ceiling covers Python bookkeeping; the SQLite runtime supplies its pager cache.
    assert peak < 8_000_000, peak
    record_property("peak_python_bytes", peak)
    first = trade(0, "10.00", identity="memory-0")
    feed(s, 200, "10.00")
    assert not s.on_trade(first, now=START + 201 * SEC)
    assert s.volume == D("2000100")


def test_compact_first_leg_keeps_its_true_origin_and_count_span():
    s = state()
    arm(s)
    for i in range(100):
        feed(s, str(D(i) / 10), "10.01")
    assert s.first_leg_ready(D("10.01"), START + 10 * SEC)
    assert s.run[0].ts_event == START
    assert len(s.run) <= s.params["first_leg_trades_count"] + 1
