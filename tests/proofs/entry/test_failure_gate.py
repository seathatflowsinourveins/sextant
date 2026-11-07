"""A native callback fault must flag the replay and latch refusal before entry."""

import sqlite3

import pytest

from sextant.entry.signals import EntryState, _Fold
from sextant.entry.tape import Tape

from .conftest import quote, trade
from .test_replay import replay


@pytest.mark.parametrize("stage", ["store", "callback"])
def test_native_failure_is_latched_and_visible(instrument, tmp_path, monkeypatch, stage):
    # The old storage fault and a callback fault must never yield a normal buy.
    target, name = (Tape, "add") if stage == "store" else (EntryState, "on_trade")
    original = getattr(target, name)

    def fault(self, tick, *args, **kwargs):
        if str(tick.price) == "9.95":
            if stage == "callback":
                original(self, tick, *args, **kwargs)
            with sqlite3.connect(":memory:") as db:
                db.execute("PRAGMA max_page_count=1")
                db.execute("CREATE TABLE veto (price)")  # Real SQLITE_FULL.
        return original(self, tick, *args, **kwargs)

    monkeypatch.setattr(target, name, fault)
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
    assert result.orders == [], result.events
    assert result.failed
    assert any(event["action"] == "FAIL" for event in result.events)


@pytest.mark.parametrize("fault", ["interrupt", "memory"])
def test_mid_rebuild_fault_keeps_the_active_prefix_and_refuses(
    instrument, tmp_path, monkeypatch, fault
):
    advance, ingest = _Fold._advance, EntryState.on_trade
    visits, failed_states = 0, []

    def interrupt(self, tick, *args):
        nonlocal visits
        advance(self, tick, *args)
        if str(tick.price) == "9.95":
            visits += 1
            if visits == 2:  # A real veto has been folded again after the late insertion.
                if fault == "memory":
                    raise MemoryError("checkpoint allocation failed")
                with sqlite3.connect(":memory:") as db:
                    db.set_progress_handler(lambda: 1, 1)
                    db.execute("SELECT 1")  # Real SQLITE_INTERRUPT, not a fabricated message.

    def observe(self, tick, *, now):
        fold, last = self.fold, self.last
        accepted = ingest(self, tick, now=now)
        if self.failure:
            assert self.fold is fold and self.last is last
            assert not self.fresh(now)
            failed_states.append(self.failure)
        return accepted

    monkeypatch.setattr(_Fold, "_advance", interrupt)
    monkeypatch.setattr(EntryState, "on_trade", observe)
    data = [quote(0, "10.00", "10.01")]
    data += [
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
    data += [trade("0.1", "10.00", lag=800_000_000), quote("1.65", "10.05", "10.06")]
    data.sort(key=lambda event: event.ts_init)
    result = replay(instrument, tmp_path, data)
    assert result.orders == [] and result.failed, result.events
    expected = "OperationalError: interrupted" if fault == "interrupt" else "MemoryError:"
    assert failed_states and result.failure_reason.startswith(expected)
    assert sum(event["action"] == "FAIL" for event in result.events) == 1
