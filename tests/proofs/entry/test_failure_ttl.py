"""N4 expiry must keep protecting an owned entry after data admission has failed."""

from decimal import Decimal as D

import pytest
from nautilus_trader.execution import StaticLatencyModel
from nautilus_trader.trading import Strategy

from sextant.entry.replay import CANCEL_ATTEMPTS, _guarded, _ReplayEntry
from sextant.entry.signals import EntryState, Surge

from .conftest import IID, SEC, START, quote, trade
from .test_replay import replay


def ttl_tape(phase, extra, tail=None):
    data = [trade(-200, "10.00", size=10000), quote(0, "10.00", "10.02")]
    data += [trade(at, "10.01", size=10000) for at in (0, 1, 2)]
    data += [quote("2.1", "10.49", "10.50")]
    if phase == "pending-update":
        data += [quote(3, "10.02", "10.03"), quote("3.1", "10.03", "10.04")]
    # Keep the book above the limit until after expiry, including on the faulting print.
    data += extra
    if tail is not None:
        return [*data, *tail]
    if phase == "pending-submit":
        return [*data, quote(12, "10.49", "10.50"), quote(13, "10.00", "10.01")]
    return [*data, quote(9, "10.00", "10.01")]


def ttl_latency(phase, cancel=0):
    return StaticLatencyModel(
        insert_latency_nanos=10 * SEC if phase == "pending-submit" else 500_000_000,
        update_latency_nanos=5 * SEC if phase == "pending-update" else 0,
        cancel_latency_nanos=cancel,
    )


# A non-marketable book every second after the TTL, so later events exist to re-request on.
LATER = [quote(at, "10.49", "10.50") for at in range(8, 31)]
CROSS = [quote(31, "10.00", "10.01")]
PHASES = ["accepted", "pending-submit", "pending-update"]


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

    def cancel_fault(self, now):
        calls.append(now)
        if len(calls) == 1:
            raise ValueError("before the cancel")
        cancel(self, now)

    monkeypatch.setattr(EntryState, "on_trade", data_fault)
    if site == "cancel-row":
        monkeypatch.setattr(_ReplayEntry, "_record", row_fault)
    else:
        monkeypatch.setattr(_ReplayEntry, "_cancel", cancel_fault)
    tape = ttl_tape(phase, [trade("3.2", "10.40"), quote(8, "10.49", "10.50")])
    result = replay(instrument, tmp_path, tape, latency_model=ttl_latency(phase))
    assert result.failure_reason == "MemoryError: first fault", result.events
    assert [o["status"] for o in result.orders] == ["CANCELED"], result.events
    assert result.orders[0]["filled_qty"] == "0"
    # The failing TTL callback never re-requests; the next event (t8, or the t12 acceptance) does.
    resent = START + (12 if phase == "pending-submit" else 8) * SEC
    cancels = [e["ts"] for e in result.events if e["action"] == "CANCEL"]
    assert cancels == ([] if site == "cancel-row" else [resent]), result.events
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


def test_a_first_leg_at_its_exact_window_end_is_refused_before_submit(instrument, tmp_path):
    # Round 11 P2: an inclusive end is ready (N1), but its lifetime is zero. Submitting would
    # cancel inside submit_order's borrow and mark the replay failed; refuse instead.
    surge = Surge(IID, "fixture-segment", START, START, START, START + 300 * SEC, D("10"), "TEST")
    data = [quote(0, "10.00", "10.02")]
    data += [trade(at, "10.01", size=10000) for at in (116, 117, 118)]
    data += [quote(120, "10.49", "10.50")]
    result = replay(instrument, tmp_path, data, surge=surge)
    assert not result.failed, result.events
    assert result.orders == [], result.events
    assert [(e["action"], e["reason"]) for e in result.events if e["action"] == "REFUSE"] == [
        ("REFUSE", "first_leg_window_s")
    ], result.events


def failing_cache(monkeypatch, failures):
    calls, descriptor = [], Strategy.cache

    class FaultyCache:
        def __init__(self, strategy):
            self._strategy = strategy
            self._cache = descriptor.__get__(strategy, _ReplayEntry)

        def order(self, client_order_id):
            if not getattr(self._strategy, "_in_cancel", False):
                return self._cache.order(client_order_id)
            calls.append(self._strategy.clock.timestamp_ns())
            if len(calls) <= failures:
                raise RuntimeError("cache.order returned Err")
            return self._cache.order(client_order_id)

        def __getattr__(self, name):
            return getattr(self._cache, name)

    def cache(self):
        faulty = self.__dict__.get("_faulty_cache")
        if faulty is None:
            faulty = FaultyCache(self)
            self._faulty_cache = faulty
        return faulty

    original = _ReplayEntry._cancel

    def cancel(self, now):
        self._in_cancel = True
        try:
            return original(self, now)
        finally:
            self._in_cancel = False

    monkeypatch.setattr(_ReplayEntry, "cache", property(cache))
    monkeypatch.setattr(_ReplayEntry, "_cancel", cancel)
    return calls


def failing_cancels(monkeypatch, failures):
    calls, cancel = [], _ReplayEntry.cancel_order

    def cancel_order(self, client_order_id, *args, **kwargs):
        calls.append(self.clock.timestamp_ns())
        if len(calls) <= failures:
            raise RuntimeError("cancel_order returned Err")
        return cancel(self, client_order_id, *args, **kwargs)

    monkeypatch.setattr(_ReplayEntry, "cancel_order", cancel_order)
    return calls


@pytest.mark.parametrize("phase", PHASES)
def test_a_single_cancel_fault_is_retried_at_once_and_never_fills(
    instrument, tmp_path, monkeypatch, phase
):
    # ADDENDUM-68R11-2: a failed TTL cancel retries at once, inside K + 1 = 4 attempts, and
    # pages the one failure without latching. Waiting for the next event let the entry fill.
    calls = failing_cancels(monkeypatch, failures=1)
    tape = ttl_tape(phase, [], tail=LATER + CROSS)
    result = replay(instrument, tmp_path, tape, latency_model=ttl_latency(phase))
    first = 12 if phase == "pending-submit" else 7  # the TTL, or the late acceptance
    assert calls == [START + first * SEC, START + first * SEC], result.events
    pages = [(e["ts"], e["reason"]) for e in result.events if e["action"] == "PAGE"]
    assert pages == [
        (START + first * SEC, "TTL cancel failed: RuntimeError: cancel_order returned Err")
    ], result.events
    assert not [e for e in result.events if e["action"] == "FAIL"], result.events
    assert [(o["status"], o["filled_qty"]) for o in result.orders] == [("CANCELED", "0")]


@pytest.mark.parametrize("phase", PHASES)
def test_four_cancel_faults_latch_without_filling(instrument, tmp_path, monkeypatch, phase):
    # ADDENDUM-68R11-2: after K + 1 failed attempts the symbol latches for the owner and no
    # further cancel is sent; the order is never filled and on_stop reports it still open.
    calls = failing_cancels(monkeypatch, failures=CANCEL_ATTEMPTS)
    tape = ttl_tape(phase, [], tail=LATER)
    result = replay(instrument, tmp_path, tape, latency_model=ttl_latency(phase))
    first = 12 if phase == "pending-submit" else 7
    assert calls == [START + first * SEC] * CANCEL_ATTEMPTS, result.events
    first_page = "TTL cancel failed: RuntimeError: cancel_order returned Err"
    pages = [(e["ts"], e["reason"]) for e in result.events if e["action"] == "PAGE"]
    assert pages[:CANCEL_ATTEMPTS] == [(START + first * SEC, first_page)] * CANCEL_ATTEMPTS
    assert pages[CANCEL_ATTEMPTS] == (
        START + first * SEC,
        f"TTL cancel failed {CANCEL_ATTEMPTS} times: owner attention",
    )
    assert pages[-1][1] == "entry still open at the window end"
    assert result.failed and result.failure_reason == pages[CANCEL_ATTEMPTS][1]
    assert result.orders[0]["filled_qty"] == "0" and result.orders[0]["status"] != "CANCELED"


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("faults", [1, 2, 3, 4, 5])
def test_cache_lookup_faults_follow_the_k_plus_one_bound(
    instrument, tmp_path, monkeypatch, phase, faults
):
    # #88 at b69ec1b: a cache.order fault before the retry loop escaped _cancel, wrote a FAIL
    # and latched, so the marketable quote at t9/t13 filled. The lookup is now retried inside
    # the same K + 1 = 4 bound, and each failed lookup pages.
    failing_cache(monkeypatch, failures=faults)
    result = replay(instrument, tmp_path, ttl_tape(phase, []), latency_model=ttl_latency(phase))
    due = START + 7 * SEC
    page = "TTL cancel failed: RuntimeError: cache.order returned Err"
    pages = [(e["ts"], e["reason"]) for e in result.events if e["action"] == "PAGE"]
    attempts = min(faults, CANCEL_ATTEMPTS)
    assert pages[:attempts] == [(due, page)] * attempts, result.events
    if faults < CANCEL_ATTEMPTS:
        assert len(pages) == faults, result.events
        assert not [e for e in result.events if e["action"] == "FAIL"], result.events
        assert [(o["status"], o["filled_qty"]) for o in result.orders] == [("CANCELED", "0")]
        deadline = START + (12 if phase == "pending-submit" else 7) * SEC
        assert [e["ts"] for e in result.events if e["action"] == "CANCEL"] == [deadline]
    else:
        assert pages[attempts] == (
            due,
            f"TTL cancel failed {CANCEL_ATTEMPTS} times: owner attention",
        ), result.events
        assert result.failed and result.failure_reason == pages[attempts][1]
        assert not [e for e in result.events if e["action"] == "CANCEL"], result.events


def test_a_pending_cancel_is_never_sent_twice(instrument, tmp_path, monkeypatch):
    # rc8 cancel_order sends nothing while mark_order_pending_cancel is false (mod.rs:629-631),
    # and _cancel skips a pending cancel too: re-requests during a 12 s cancel latency send none.
    calls = failing_cancels(monkeypatch, failures=0)
    tape = ttl_tape("accepted", [], tail=LATER + CROSS)
    latency = ttl_latency("accepted", cancel=12 * SEC)
    result = replay(instrument, tmp_path, tape, latency_model=latency)
    assert calls == [START + 7 * SEC], result.events
    assert [e["ts"] for e in result.events if e["action"] == "CANCEL"] == calls
    assert [(o["status"], o["filled_qty"]) for o in result.orders] == [("CANCELED", "0")]
