"""PR-3's historical end-to-end proof: the owner's fill, then B's broker-held protection.

The tape is a committed fixture (tests/fixtures/b-e2e-owner-fill.json) whose digest is
pinned here, so a change to the tape fails before any replay runs. The strategy is the
NautilusTrader trailing-stop example's shape with the entry changed to the owner's fill
at time T; the protection is the same entry-level stop B's live protector submitted for
the owner's PARA fill (tests/fixtures/b-trades.jsonl, trail_percent 2.5).

These tests name behaviour, not implementation:
- an owner's fill enters once and the broker trail exits at the first print below H - 2.5%;
- the catalyst arm enters at the first print at or after EDGAR knowable_at;
- the first-leg arm enters on five non-decreasing prints within first_leg_max_move;
- a missing catalyst is a FAILED MODELED row that names its reason;
- every run writes MODELED rows to the one cumulative trial ledger.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from sextant.backtest.b_e2e import load_spec, run_case

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "b-e2e-owner-fill.json"
FIXTURE_SHA256 = "87fc4a24a654f26466a07058bbf3d63c2e61254274e05677768997463f26636a"


def _spec():
    return load_spec(FIXTURE)


def test_fixture_tape_is_pinned():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA256


def test_owner_fill_entry_arms_the_trail_and_exits_at_the_first_breach(tmp_path):
    result = run_case(_spec(), tmp_path, arms=("reference",))["reference"]

    assert result.state == "COMPLETE"
    assert result.entry_price == Decimal("100.000000000")
    assert result.high == Decimal("120.000000000")
    assert result.trail_level == Decimal("117.000000000")
    assert result.exit_price == Decimal("117.000000000")
    assert result.protected == pytest.approx(0.17)
    assert result.hold_flat == pytest.approx(0.169)


def test_catalyst_arm_enters_at_the_first_print_at_or_after_knowable_at(tmp_path):
    result = run_case(_spec(), tmp_path, arms=("catalyst",))["catalyst"]

    assert result.state == "COMPLETE"
    assert result.trigger is not None
    assert result.trigger.arm == "catalyst"
    assert result.entry_price == Decimal("100.000000000")
    assert result.exit_price == Decimal("117.000000000")


def test_first_leg_arm_enters_on_five_rising_prints_within_three_percent(tmp_path):
    result = run_case(_spec(), tmp_path, arms=("first_leg",))["first_leg"]

    assert result.state == "COMPLETE"
    assert result.trigger is not None
    assert result.entry_price == Decimal("103.000000000")
    assert result.exit_price == Decimal("117.000000000")
    assert result.protected == pytest.approx(float(Decimal("117") / Decimal("103") - 1))


def test_a_rejected_arm_is_a_failed_row_that_names_its_reason(tmp_path):
    spec = replace(_spec(), catalyst_ns=None)
    log = tmp_path / "trials.parquet"
    result = run_case(spec, tmp_path, arms=("catalyst",), log=log)["catalyst"]

    assert result.state == "FAIL"
    assert "catalyst" in result.reason
    rows = pq.read_table(log).to_pylist()
    assert len(rows) == 1
    assert rows[0]["state"] == "FAIL"
    assert "catalyst" in rows[0]["error"]
    assert rows[0]["config"] is not None


def test_every_arm_writes_one_modeled_trial_log_row(tmp_path):
    log = tmp_path / "trials.parquet"
    results = run_case(_spec(), tmp_path, arms=("reference", "catalyst", "first_leg"), log=log)

    assert {arm: result.state for arm, result in results.items()} == {
        "reference": "COMPLETE",
        "catalyst": "COMPLETE",
        "first_leg": "COMPLETE",
    }
    rows = pq.read_table(log).to_pylist()
    assert len(rows) == 4  # three arms plus the hold-flat control
    assert {row["strategy"] for row in rows} == {"b_e2e", "b_e2e_hold_flat"}
    for row in rows:
        config = __import__("json").loads(row["config"])
        assert config["tier"] == "MODELED"
        assert config["block_set_id"] == "2026-01-05"
        assert row["state"] == "COMPLETE"
