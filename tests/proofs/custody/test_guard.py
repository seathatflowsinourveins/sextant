"""Catch lost owner kills, false release and paper P&L entry vetoes."""

import json
from decimal import Decimal as D

import pytest

from sextant.risk.gates import Gates
from sextant.risk.guard import Guard, GuardState

from .conftest import IID, SCOPE, SEC, controls, custody, order, snapshot


def active_guard(tmp_path):
    book = custody(tmp_path)
    book.observe(snapshot(net="0"), now=SEC)
    guard = Guard(SCOPE, tmp_path / "guard.json", tmp_path / "kill", controls(), mode="paper")
    guard.initialize(book.flat_receipt())
    return guard, book


def test_kill_cancels_only_house_entries_and_preserves_owner_orders_and_protection(tmp_path):
    guard, book = active_guard(tmp_path)
    book.register("entry", IID, "BUY", D("10"), source="TEST")
    book.link("entry", "entry-v")
    book.register("protect", IID, "SELL", D("10"), source="TEST")
    book.link("protect", "protect-v")
    owner = order("owner-buy", side="BUY", qty="7", owner=True, venue="owner-v")
    entry = order("entry", side="BUY", qty="10", venue="entry-v")
    protection = order("protect", qty="10", venue="protect-v")
    book.observe(snapshot(owner, entry, protection, net="10", epoch=2), now=SEC)
    guard.kill("manual", now=SEC)
    intents = guard.step(book, now=SEC)
    assert [i.client_order_id for i in intents if i.kind == "CANCEL_ENTRY"] == ["entry"]
    assert guard.state is GuardState.HALTED
    assert not guard.entry_allowed()
    assert book.snapshot is not None
    assert owner in book.snapshot.orders
    assert protection in book.snapshot.orders


def test_ten_second_cancel_window_then_reduces_only_unreserved_broker_net(tmp_path):
    guard, book = active_guard(tmp_path)
    book.register("entry", IID, "BUY", D("10"), source="TEST")
    book.link("entry", "entry-v")
    book.observe(
        snapshot(
            order(
                "entry", side="BUY", qty="10", filled="5", status="PENDING_CANCEL", venue="entry-v"
            ),
            net="5",
            epoch=2,
        ),
        now=SEC,
    )
    guard.kill("manual", now=SEC)
    guard.step(book, now=SEC)
    assert not any(i.kind == "FLATTEN" for i in guard.step(book, now=10 * SEC))
    actions = guard.step(book, now=11 * SEC)
    closes = [i for i in actions if i.kind == "FLATTEN"]
    assert len(closes) == 1 and closes[0].quantity == D("5")
    assert guard.state is GuardState.REDUCING
    assert not any(i.kind == "FLATTEN" for i in guard.step(book, now=12 * SEC))
    assert any(i.kind == "FLATTEN" for i in guard.step(book, now=13 * SEC))


def test_flat_halt_is_latched_and_a_late_fill_cannot_release_it(tmp_path):
    guard, book = active_guard(tmp_path)
    guard.kill("manual", now=SEC)
    guard.step(book, now=SEC)
    assert guard.state is GuardState.HALTED
    assert guard.flattened
    old_flat = book.flat_receipt()
    book.observe(snapshot(net="3", epoch=2, known_at=2 * SEC), now=2 * SEC)
    actions = guard.step(book, now=2 * SEC)
    assert [i.quantity for i in actions if i.kind == "FLATTEN"] == [D("3")]
    assert not guard.release("manual", old_flat, now=2 * SEC)
    assert not guard.entry_allowed()


def test_unknown_state_stays_halted_and_corrupt_bytes_are_retained(tmp_path):
    path = tmp_path / "guard.json"
    path.write_text("{")
    guard = Guard(SCOPE, path, tmp_path / "kill", controls(), mode="paper")
    book = custody(tmp_path)
    book.observe(snapshot(net="0"), now=SEC)
    assert guard.state is GuardState.UNKNOWN
    assert not guard.loaded
    with pytest.raises(ValueError):
        guard.initialize(book.flat_receipt())
    guard.kill("manual", now=SEC)
    guard.step(book, now=SEC)
    assert not guard.release("manual", book.flat_receipt(), now=SEC)
    assert not guard.entry_allowed()
    assert path.read_text() == "{"


def test_kill_marker_precedes_fallible_save_and_restart_remains_halted(tmp_path, monkeypatch):
    guard, _book = active_guard(tmp_path)
    marker = tmp_path / "kill"

    def failed_save(*_args):
        assert marker.exists()
        raise OSError("TEST disk failure")

    with monkeypatch.context() as patch:
        patch.setattr("sextant.risk.guard.write_atomic", failed_save)
        guard.kill("manual", now=SEC)
    assert marker.exists()
    assert not guard.entry_allowed()
    restarted = Guard(SCOPE, tmp_path / "guard.json", marker, controls(), mode="paper")
    assert not restarted.entry_allowed()
    assert "owner_kill" in restarted.reasons


def test_owner_marker_created_between_checks_engages_flattening(tmp_path):
    guard, book = active_guard(tmp_path)
    book.observe(snapshot(net="3", epoch=2), now=SEC)
    (tmp_path / "kill").touch()
    actions = guard.step(book, now=SEC)
    assert [i.quantity for i in actions if i.kind == "FLATTEN"] == [D("3")]
    assert not guard.entry_allowed()


def test_explicit_release_requires_latest_positive_terminal_flat_receipt(tmp_path):
    guard, book = active_guard(tmp_path)
    guard.kill("manual", now=SEC)
    guard.step(book, now=SEC)
    assert guard.release("manual", book.flat_receipt(), now=SEC)
    assert guard.entry_allowed()
    assert not (tmp_path / "kill").exists()
    state = json.loads((tmp_path / "guard.json").read_text())
    assert state["state"] == "ACTIVE"


def test_inconsistent_active_or_unanchored_money_state_is_unknown(tmp_path):
    _guard, _book = active_guard(tmp_path)
    path = tmp_path / "guard.json"
    state = json.loads(path.read_text())
    state["flattened"] = True
    path.write_text(json.dumps(state))
    restarted = Guard(SCOPE, path, tmp_path / "kill", controls(), mode="paper")
    assert not restarted.loaded
    assert not restarted.entry_allowed()


def test_unknown_persisted_operational_counter_state_cannot_restore_active(tmp_path):
    _guard, _book = active_guard(tmp_path)
    path = tmp_path / "guard.json"
    state = json.loads(path.read_text())
    state["oer"] = {"day": "2026-11-06", "actions": "unknown", "fills": 0, "requests": 2}
    path.write_text(json.dumps(state))
    restarted = Guard(SCOPE, path, tmp_path / "kill", controls(), mode="paper")
    assert not restarted.loaded
    assert not restarted.entry_allowed()


def test_day_equity_oer_and_economic_high_water_mark_survive_restart_without_reset(tmp_path):
    guard, _book = active_guard(tmp_path)
    guard.record_evidence(
        trading_day="2026-11-06",
        day_start_equity=D("10000"),
        economic_hwm=D("11000"),
        oer={"day": "2026-11-06", "actions": 12, "fills": 2, "requests": 15},
    )
    restarted = Guard(SCOPE, tmp_path / "guard.json", tmp_path / "kill", controls(), mode="paper")
    assert restarted.day_start_equity == "10000"
    assert restarted.economic_hwm == "11000"
    assert restarted.oer["actions"] == 12
    restarted.record_evidence(
        trading_day="2026-11-09",
        day_start_equity=D("9500"),
        economic_hwm=D("9500"),
        oer={"day": "2026-11-09", "actions": 0, "fills": 0, "requests": 0},
    )
    assert restarted.economic_hwm == "11000"


def test_paper_house_safeguards_observe_but_owner_kill_and_unknown_id_enforce(caplog):
    paper, other = Gates("paper", controls()), Gates("sim", controls())
    assert not paper.trigger("guard.daily_loss", now=SEC, value=D("1000"), limit=D("10"))
    assert other.trigger("guard.daily_loss", now=SEC, value=D("1000"), limit=D("10"))
    assert paper.trigger("guard.owner_kill", now=SEC)
    assert paper.trigger("unknown.gate", now=SEC)
    assert "ERROR" in caplog.text and "unknown.gate" in caplog.text


def test_observations_keep_crossing_material_change_reminder_and_clear():
    gates = Gates("paper", controls())
    gates.trigger("guard.daily_loss", now=SEC, value=D("100"), limit=D("100"))
    gates.trigger("guard.daily_loss", now=2 * SEC, value=D("100.50"), limit=D("100"))
    assert len(gates.events) == 1
    gates.trigger("guard.daily_loss", now=3 * SEC, value=D("101"), limit=D("100"))
    assert len(gates.events) == 2
    gates.trigger("guard.daily_loss", now=303 * SEC, value=D("101"), limit=D("100"))
    assert len(gates.events) == 3
    gates.trigger("guard.daily_loss", now=304 * SEC, cleared=True)
    assert gates.events[-1]["detail"] == {"cleared": True}
    gates.trigger("guard.daily_loss", now=305 * SEC, cleared=True)
    assert len(gates.events) == 4


def test_loss_warning_retains_the_source_text_and_prunes_retired_instrument_edges(caplog):
    gates = Gates("paper", controls())
    gates.trigger("guard.daily_loss", now=SEC, value=D("100"), limit=D("10"), instrument=IID)
    assert "loss limit observed (paper, not enforced): daily_loss 100 >= 10" in caplog.text
    gates.prune(set())
    assert gates.to_state() == []
