"""Native state/callback exceptions fail closed while clean controls still buy."""

import pytest

from sextant.entry.signals import EntryState, _Setup

from .conftest import quote, trade
from .test_replay import replay
from .test_signals import arm, feed, state


@pytest.mark.parametrize("stage", ["state", "callback"])
@pytest.mark.parametrize("fault", [None, MemoryError, ValueError], ids=["clean", "memory", "value"])
def test_native_failure_is_latched_and_visible(instrument, tmp_path, monkeypatch, stage, fault):
    target, name = (_Setup, "advance") if stage == "state" else (EntryState, "on_trade")
    original = getattr(target, name)

    def interrupted(self, tick, *args, **kwargs):
        result = original(self, tick, *args, **kwargs)
        if str(tick.price) == "9.95" and fault:
            raise fault("injected state/callback failure")
        return result

    monkeypatch.setattr(target, name, interrupted)
    result = replay(
        instrument,
        tmp_path,
        [quote(0, "10.00", "10.01")]
        + [
            trade(at, price, size=10000)
            for at, price in [
                (0, "10.01"),
                ("0.2", "10.02"),
                ("0.4", "9.95"),
                ("0.6", "10.03"),
                ("0.8", "10.04"),
                (1, "10.05"),
                ("1.6", "10.06"),
            ]
        ]
        + [quote("1.65", "10.05", "10.06")],
    )
    assert result.failed is bool(fault)
    if fault:
        assert result.orders == [], result.events
        assert result.failure_reason.startswith(fault.__name__ + ":")
        assert sum(e["action"] == "FAIL" for e in result.events) == 1
    else:
        assert len(result.orders) == 1
        assert sum(e["action"] == "SUBMIT" for e in result.events) == 1


def test_failed_fresh_reset_preserves_active_state_and_latches(monkeypatch):
    s = state()
    arm(s)
    feed(s, 0, "10.01")
    active, segment = s.setup, s.segment

    def allocation_failure(self, params):
        raise MemoryError("new segment allocation failed")

    with monkeypatch.context() as patch:
        patch.setattr(_Setup, "__init__", allocation_failure)
        s.reset_segment("next", start_ns=s.segment_start_ns)
    assert s.setup is active and s.segment == segment
    assert s.failure == "MemoryError: new segment allocation failed"
    assert not feed(s, 1, "10.02")
