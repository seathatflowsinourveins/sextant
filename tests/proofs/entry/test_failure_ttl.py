"""N4 expiry must keep protecting an owned entry after data admission has failed."""

import pytest
from nautilus_trader.execution import StaticLatencyModel

from sextant.entry.signals import EntryState

from .conftest import SEC, START, quote, trade
from .test_replay import replay


@pytest.mark.parametrize("phase", ["accepted", "pending-submit", "pending-update"])
@pytest.mark.parametrize("fault_kind", ["clean", "memory", "old-print", "pruned-duplicate"])
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
    data = [trade(-200, "10.00", size=10000), quote(0, "10.00", "10.02")]
    data += [trade(at, "10.01", size=10000) for at in (0, 1, 2)]
    data += [quote("2.1", "10.49", "10.50")]
    if phase == "pending-update":
        data += [quote(3, "10.02", "10.03"), quote("3.1", "10.03", "10.04")]
    # Keep the book above the limit until after expiry, including on the faulting print.
    if fault_kind == "old-print":
        data += [trade(-150, "10.00", lag=153 * SEC)]
    elif fault_kind == "pruned-duplicate":
        data += [trade(-200, "10.00", size=10000, lag=203 * SEC)]
    else:
        data += [trade("3.2", "10.40")]
    if phase == "pending-submit":
        data += [quote(12, "10.49", "10.50"), quote(13, "10.00", "10.01")]
    else:
        data += [quote(9, "10.00", "10.01")]
    result = replay(
        instrument,
        tmp_path,
        data,
        latency_model=StaticLatencyModel(
            insert_latency_nanos=10 * SEC if phase == "pending-submit" else 500_000_000,
            update_latency_nanos=5 * SEC if phase == "pending-update" else 0,
        ),
    )
    assert result.failed is (fault_kind != "clean")
    if fault_kind in {"old-print", "pruned-duplicate"}:
        assert result.failure_reason == "ValueError: print precedes retained history"
    assert len(result.orders) == 1, result.events
    assert result.orders[0]["status"] == "CANCELED", result.events
    assert result.orders[0]["filled_qty"] == "0"
    assert result.orders[0]["quantity"] == "95"
    cancels = [e["ts"] for e in result.events if e["action"] == "CANCEL"]
    deadline = START + (12 if phase == "pending-submit" else 7) * SEC
    assert cancels and cancels[0] == deadline, result.events
    assert sum(e["action"] == "SUBMIT" for e in result.events) == 1
    assert any(e["action"] == "MODIFY" for e in result.events) is (phase == "pending-update")
