"""N4 expiry must keep protecting an owned entry after data admission has failed."""

import pytest
from nautilus_trader.execution import StaticLatencyModel

from sextant.entry.replay import _guarded, _ReplayEntry
from sextant.entry.signals import EntryState

from .conftest import SEC, START, quote, trade
from .test_replay import replay


def ttl_tape(phase, extra):
    data = [trade(-200, "10.00", size=10000), quote(0, "10.00", "10.02")]
    data += [trade(at, "10.01", size=10000) for at in (0, 1, 2)]
    data += [quote("2.1", "10.49", "10.50")]
    if phase == "pending-update":
        data += [quote(3, "10.02", "10.03"), quote("3.1", "10.03", "10.04")]
    # Keep the book above the limit until after expiry, including on the faulting print.
    data += extra
    if phase == "pending-submit":
        return [*data, quote(12, "10.49", "10.50"), quote(13, "10.00", "10.01")]
    return [*data, quote(9, "10.00", "10.01")]


def ttl_latency(phase):
    return StaticLatencyModel(
        insert_latency_nanos=10 * SEC if phase == "pending-submit" else 500_000_000,
        update_latency_nanos=5 * SEC if phase == "pending-update" else 0,
    )


@pytest.mark.parametrize("phase", ["accepted", "pending-submit", "pending-update"])
@pytest.mark.parametrize(
    "fault_kind", ["clean", "memory", "late-void", "old-print", "pruned-duplicate"]
)
def test_data_failure_preserves_ttl_and_late_acceptance_cancel(
    instrument, tmp_path, monkeypatch, phase, fault_kind
):
    original = EntryState.on_trade

    def fault(self, tick, *, now):
        if str(tick.price) == "10.40":
            raise MemoryError("data fault while an owned entry remains outstanding")
        return original(self, tick, now=now)

    if fault_kind == "memory":
        monkeypatch.setattr(EntryState, "on_trade", fault)
    extra = {
        "late-void": trade(1, "10.01", lag=2_200_000_000),
        "old-print": trade(-150, "10.00", lag=153 * SEC),
        "pruned-duplicate": trade(-200, "10.00", size=10000, lag=203 * SEC),
    }.get(fault_kind, trade("3.2", "10.40"))
    result = replay(
        instrument, tmp_path, ttl_tape(phase, [extra]), latency_model=ttl_latency(phase)
    )
    assert result.failed is (fault_kind == "memory")
    late = fault_kind in {"late-void", "old-print", "pruned-duplicate"}
    assert any(e["action"] == "VOID" for e in result.events) is late
    assert len(result.orders) == 1, result.events
    assert result.orders[0]["status"] == "CANCELED", result.events
    assert result.orders[0]["filled_qty"] == "0"
    assert result.orders[0]["quantity"] == "95"
    cancels = [e["ts"] for e in result.events if e["action"] == "CANCEL"]
    deadline = START + (12 if phase == "pending-submit" else 7) * SEC
    assert cancels and cancels[0] == deadline, result.events
    assert sum(e["action"] == "SUBMIT" for e in result.events) == 1
    assert any(e["action"] == "MODIFY" for e in result.events) is (phase == "pending-update")


@pytest.mark.parametrize("phase", ["accepted", "pending-submit", "pending-update"])
@pytest.mark.parametrize("site", ["cancel-row", "before-cancel"])
def test_a_retirement_fault_still_cancels_and_keeps_the_first_reason(
    instrument, tmp_path, monkeypatch, phase, site
):
    on_trade, record, cancel = EntryState.on_trade, _ReplayEntry._record, _ReplayEntry._cancel
    calls = []

    def data_fault(self, tick, *, now):
        if str(tick.price) == "10.40":
            raise MemoryError("first fault")
        return on_trade(self, tick, now=now)

    def row_fault(self, action, **terms):
        if action == "CANCEL":
            raise ValueError("CANCEL journal row")
        record(self, action, **terms)

    def cancel_fault(self):
        calls.append(self)
        if len(calls) == 1:
            raise ValueError("before the cancel")
        cancel(self)

    monkeypatch.setattr(EntryState, "on_trade", data_fault)
    if site == "cancel-row":
        monkeypatch.setattr(_ReplayEntry, "_record", row_fault)
    else:
        monkeypatch.setattr(_ReplayEntry, "_cancel", cancel_fault)
    tape = ttl_tape(phase, [trade("3.2", "10.40")])
    result = replay(instrument, tmp_path, tape, latency_model=ttl_latency(phase))
    assert result.failure_reason == "MemoryError: first fault", result.events
    assert [o["status"] for o in result.orders] == ["CANCELED"], result.events
    assert result.orders[0]["filled_qty"] == "0"
    deadline = START + (12 if phase == "pending-submit" else 7) * SEC
    cancels = [e["ts"] for e in result.events if e["action"] == "CANCEL"]
    assert cancels == ([] if site == "cancel-row" else [deadline]), result.events
    second = "ValueError: " + (
        "CANCEL journal row" if site == "cancel-row" else "before the cancel"
    )
    fails = [e["reason"] for e in result.events if e["action"] == "FAIL"]
    assert fails == ["MemoryError: first fault", second], result.events


@pytest.mark.parametrize("kind", ["OrderInitialized", "OrderPendingUpdate", "OrderPendingCancel"])
def test_a_fault_inside_nested_order_dispatch_keeps_its_fail_row(
    instrument, tmp_path, monkeypatch, kind
):
    closure = _ReplayEntry.on_order_event.__closure__  # the guarded original
    assert closure is not None
    inner = closure[0].cell_contents

    def on_order_event(self, event):
        if type(event).__name__ == kind:
            raise ValueError(f"fault in {kind}")
        inner(self, event)

    monkeypatch.setattr(_ReplayEntry, "on_order_event", _guarded(on_order_event))
    phase = "pending-update" if kind == "OrderPendingUpdate" else "accepted"
    tape = ttl_tape(phase, [trade("3.2", "10.40")])
    result = replay(instrument, tmp_path, tape, latency_model=ttl_latency(phase))
    assert result.failure_reason == f"ValueError: fault in {kind}"
    assert [e["reason"] for e in result.events if e["action"] == "FAIL"] == [result.failure_reason]
    assert [(o["status"], o["filled_qty"]) for o in result.orders] == [("CANCELED", "0")]


def test_a_first_leg_entry_never_rests_past_its_window(instrument, tmp_path):
    # Northstar _expire_first_leg: the deadline is min(submit + TTL, window end).
    data = [quote("115.9", "10.00", "10.02")]
    data += [trade(at, "10.01", size=10000) for at in (116, 117, 118)]
    data += [quote("118.1", "10.49", "10.50"), quote(121, "10.00", "10.01")]
    latency = StaticLatencyModel(insert_latency_nanos=500_000_000)
    result = replay(instrument, tmp_path, data, latency_model=latency)
    marks = [(e["action"], e["ts"]) for e in result.events if e["action"] in {"SUBMIT", "CANCEL"}]
    assert marks == [("SUBMIT", START + 118 * SEC), ("CANCEL", START + 120 * SEC)], result.events
    assert [(o["status"], o["filled_qty"]) for o in result.orders] == [("CANCELED", "0")]
