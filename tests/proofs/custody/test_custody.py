"""Catch owner-order takeover, duplicate exits and false flat or writer receipts."""

import subprocess
import sys
from decimal import Decimal as D

import pytest

from sextant.execution.custody import AccountScope, Custody, CustodyError, WriterLease

from .conftest import IID, SCOPE, SEC, custody, order, snapshot


def test_owner_orders_stay_untouched_and_reserve_only_unfilled_quantity(tmp_path):
    book = custody(tmp_path)
    original = order("owner-limit", qty="40", filled="10", owner=True, venue="owner-v")
    assert book.observe(snapshot(original, net="90"), now=SEC)
    assert not book.may_cancel("owner-limit")
    assert not book.may_replace("owner-limit")
    assert book.available_exit(IID) == D("60")
    assert book.owner_reserved(IID) == D("30")
    assert book.snapshot is not None
    assert original == book.snapshot.orders[0]
    with pytest.raises(CustodyError, match="owner"):
        book.register("owner-limit", IID, "SELL", D("40"), source="TEST")


def test_one_exit_per_quantity_includes_pending_cancel_and_unknown(tmp_path):
    book = custody(tmp_path)
    book.register("house-exit", IID, "SELL", D("100"), source="TEST")
    book.link("house-exit", "venue-1")
    assert book.observe(snapshot(order(status="PENDING_CANCEL")), now=SEC)
    assert book.available_exit(IID) == 0
    assert book.may_cancel("house-exit")
    assert not book.may_replace("house-exit")
    assert book.observe(snapshot(order(status="UNKNOWN"), epoch=2), now=SEC)
    assert book.available_exit(IID) == 0
    assert IID in book.frozen
    assert book.flat_receipt() is None


def test_partial_fill_terminal_cancel_frees_only_current_broker_residual(tmp_path):
    book = custody(tmp_path)
    book.register("house-exit", IID, "SELL", D("100"), source="TEST")
    book.link("house-exit", "venue-1")
    book.observe(snapshot(order(filled="30", status="PENDING_CANCEL"), net="70"), now=SEC)
    assert book.available_exit(IID) == 0
    book.observe(snapshot(order(filled="40", status="CANCELED"), net="60", epoch=2), now=SEC)
    assert book.available_exit(IID) == D("60")
    assert book.flat_receipt() is None


def test_foreign_or_mismatched_order_freezes_symbol(tmp_path):
    book = custody(tmp_path)
    book.observe(snapshot(order("foreign")), now=SEC)
    assert IID in book.frozen
    assert book.available_exit(IID) == 0
    book.register("house-exit", IID, "SELL", D("100"), source="TEST")
    book.link("house-exit", "venue-1")
    book.observe(snapshot(order(side="BUY"), epoch=2), now=SEC)
    assert IID in book.frozen
    assert not book.may_cancel("house-exit")


def test_broker_report_alone_never_grants_position_custody(tmp_path):
    book = custody(tmp_path)
    book.observe(snapshot(managed=False), now=SEC)
    assert book.available_exit(IID) == 0
    assert IID in book.frozen


def test_missing_registered_order_retains_possible_fill_exposure(tmp_path):
    book = custody(tmp_path)
    book.register("house-exit", IID, "SELL", D("100"), source="TEST")
    book.observe(snapshot(), now=SEC)
    assert book.available_exit(IID) == 0
    assert IID in book.frozen


def test_registration_reserves_before_the_next_account_observation(tmp_path):
    book = custody(tmp_path)
    book.observe(snapshot(), now=SEC)
    book.register("queued-exit", IID, "SELL", D("100"), source="TEST")
    assert book.available_exit(IID) == 0
    assert not book.submission_ready(IID)
    assert book.submission_ready(IID, exclude_client_id="queued-exit")
    assert book.available_exit(IID, exclude_client_id="queued-exit") == D("100")


def test_unrecognized_owner_order_state_is_unknown_and_freezes_the_symbol(tmp_path):
    book = custody(tmp_path)
    book.observe(snapshot(order("owner", side="BUY", owner=True, status="UNRECOGNIZED")), now=SEC)
    assert IID in book.frozen
    assert book.available_exit(IID) == 0


def test_owner_classification_and_filled_terminal_are_strict(tmp_path):
    with pytest.raises(ValueError):
        order(owner="false")
    with pytest.raises(ValueError):
        order(status="FILLED", filled="0")


def test_flat_requires_positive_complete_account_and_all_terminal_lineage(tmp_path):
    book = custody(tmp_path)
    book.register("house-exit", IID, "SELL", D("100"), source="TEST")
    book.link("house-exit", "old")
    book.link("house-exit", "new", predecessor="old")
    book.observe(snapshot(order(venue="new", status="CANCELED"), net="0"), now=SEC)
    assert book.flat_receipt() is None  # The older generation could still be live.
    old = order(venue="old", status="REPLACED")
    new = order(venue="new", status="CANCELED")
    book.observe(snapshot(old, new, net="0", epoch=2, complete=False), now=SEC)
    assert book.flat_receipt() is None
    book.observe(snapshot(old, new, net="0", epoch=3), now=SEC)
    receipt = book.flat_receipt()
    assert receipt is not None
    assert receipt.scope == SCOPE
    assert set(receipt.terminal_venue_ids) == {"old", "new"}


def test_stale_snapshot_cannot_erase_new_fill_or_release_reservation(tmp_path):
    book = custody(tmp_path)
    book.register("house-exit", IID, "SELL", D("100"), source="TEST")
    book.link("house-exit", "venue-1")
    book.observe(snapshot(order(filled="10"), net="90", epoch=2), now=SEC)
    assert not book.observe(snapshot(order(status="CANCELED"), net="0", epoch=1), now=SEC)
    assert book.snapshot is not None
    assert book.snapshot.positions[IID] == D("90")
    assert book.flat_receipt() is None


def test_corrupt_custody_state_is_unavailable_and_not_overwritten(tmp_path):
    path = tmp_path / "custody.json"
    path.write_text("{")
    book = Custody(SCOPE, path, create=True)
    assert not book.loaded
    assert not book.observe(snapshot(net="0"), now=SEC)
    with pytest.raises(CustodyError):
        book.register("house", IID, "SELL", D(1), source="TEST")
    assert path.read_text() == "{"


def test_durable_lineage_survives_restart_and_rejects_account_drift(tmp_path):
    book = custody(tmp_path)
    book.register("house-exit", IID, "SELL", D("100"), source="TEST")
    book.link("house-exit", "venue-1")
    again = Custody(SCOPE, tmp_path / "custody.json")
    again.observe(snapshot(order()), now=SEC)
    assert again.may_cancel("house-exit")
    other = Custody(AccountScope("ALPACA", "other"), tmp_path / "custody.json")
    assert not other.loaded
    assert other.flat_receipt() is None


def test_account_lock_enforces_one_writer_across_lane_names(tmp_path):
    first = WriterLease(SCOPE, tmp_path, "B-manager")
    second = WriterLease(SCOPE, tmp_path, "entry-writer")
    first.acquire()
    try:
        with pytest.raises(CustodyError, match="writer"):
            second.acquire()
        assert first.held
        assert not second.held
    finally:
        first.close()
    second.acquire()
    assert second.held
    second.close()


def test_another_process_cannot_acquire_the_same_account_writer(tmp_path):
    first = WriterLease(SCOPE, tmp_path, "first-process")
    first.acquire()
    program = """
import sys
from pathlib import Path
from sextant.execution.custody import AccountScope, CustodyError, WriterLease
lease = WriterLease(AccountScope('ALPACA', 'fixture-paper-b'), Path(sys.argv[1]), 'other-process')
try:
    lease.acquire()
except CustodyError:
    sys.exit(23)
lease.close()
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", program, str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 23, result.stderr
    finally:
        first.close()


@pytest.mark.parametrize("qty", [D("NaN"), D("-1"), 10.0])
def test_invalid_quantities_never_enter_custody(tmp_path, qty):
    book = custody(tmp_path)
    with pytest.raises((ValueError, CustodyError)):
        book.register("house", IID, "SELL", qty, source="TEST")
