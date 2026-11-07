"""Late near-tail facts must not replay the segment; stale in-order facts fold once."""

from time import perf_counter

from sextant.entry.signals import _Fold

from .conftest import SEC, START, trade
from .test_signals import state


def test_late_suffix_and_stale_in_order_work_stay_local(monkeypatch, record_property):
    s = state()
    for i in range(50000):
        t = trade(str(i / 1000), "10.00", identity=f"prefix-{i}")
        assert s.on_trade(t, now=t.ts_init)
    steps = 0
    original = _Fold._advance

    def advance(self, *args):
        nonlocal steps
        steps += 1
        original(self, *args)

    monkeypatch.setattr(_Fold, "_advance", advance)
    started = perf_counter()
    for i in range(50):
        late = trade("49.98", "10.00", identity=f"late-{i}", lag=50_000_000)
        assert not s.on_trade(late, now=late.ts_init)
    assert steps <= 50 * 21, steps
    record_property("suffix_steps", steps)
    record_property("suffix_wall_ms", round((perf_counter() - started) * 1000, 3))
    steps = 0
    stale = trade(50, "10.00", lag=6 * SEC)
    assert not s.on_trade(stale, now=stale.ts_init)
    assert steps == 1 and s.volume == 5005100
    assert not s.fresh(START + 56 * SEC)
