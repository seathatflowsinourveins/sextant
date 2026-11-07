"""Native sim custody/handover witnesses. No live-node external fill claim is exercised."""

import json
from dataclasses import replace
from decimal import Decimal as D

import pytest


def run_case(tmp_path, **case):
    from sextant.backtest.owner_b_witness import run_case as run

    return run(tmp_path, **case)


@pytest.mark.parametrize("missing", ["chase_cap_fraction", "chase_min_interval_s"])
@pytest.mark.parametrize("session", ["rth", "outside"])
def test_missing_chase_parameters_refuse_before_adoption(missing, session):
    from sextant.backtest.exit_witness import FIXTURE
    from sextant.backtest.owner_b_witness import B_FIXTURE, EQUITY
    from sextant.exits.owner_b_sim import BManager, BManagerConfig

    params = replace(FIXTURE, **{missing: None})
    with pytest.raises(ValueError, match="explicit chase parameters"):
        BManager(
            BManagerConfig(
                instrument_id=EQUITY.id,
                params=params,
                round_trip_cost=D(0),
                session=session,
                b_params=B_FIXTURE,
                owner_order_ids=(),
            )
        )


def test_option_b_waits_for_terminal_cancel_and_measures_both_gaps(tmp_path):
    r = run_case(tmp_path, scenario="normal")
    assert r["sold"] == "8" and r["residual"] == "2"
    assert r["max_house_exits"] == 1 and r["reservation_violations"] == []
    assert r["cancel_ack_ns"] < r["limit_accepted_ns"] < r["first_fill_ns"]
    # The pinned engine services latency at the next data event on this one-second grid.
    assert r["gap1_ns"] == 1_000_000_000
    assert r["gap2_ns"] > 0
    assert not any(o["reduce_only"] for o in r["house_orders"])
    assert all(o["quantity"] == "2" and o["status"] == "ACCEPTED" for o in r["owner_exits"])
    assert r["owner_mutations"] == []


@pytest.mark.parametrize(
    "point, sold, residual",
    [
        ("after_cancel_ack", "0", "8"),
        ("after_limit_accept", "3", "5"),
    ],
)
def test_engine_stop_and_start_in_sim_not_a_process_death_and_not_broker_reconciliation(
    tmp_path,
    point,
    sold,
    residual,
):
    """engine stop and start in sim; not a process death and not broker reconciliation."""
    r = run_case(tmp_path, scenario=point)
    assert r["stops"] == 1 and r["restarts"] == 1
    assert r["sold"] == sold
    assert len(r["resting_trails"]) == 1
    assert r["resting_trails"][0]["leaves"] == residual
    assert r["max_house_exits"] == 1 and r["reservation_violations"] == []
    assert r["limit_submissions"] == (0 if point == "after_cancel_ack" else 1)
    assert r["owner_mutations"] == []
    assert r["recovery_label"] == (
        "engine stop and start in sim; not a process death and not broker reconciliation"
    )


def test_unfilled_chase_ends_by_cancel_then_rearming_the_fresh_residual(tmp_path):
    r = run_case(tmp_path, scenario="unfilled")
    assert r["sold"] == "0" and r["gap2_ns"] is None
    assert r["limit_submissions"] == 1 and len(r["resting_trails"]) == 1
    assert r["resting_trails"][0]["leaves"] == "8"
    assert r["reservation_violations"] == []


def test_owner_add_pauses_the_manager_and_pages_without_touching_owner_orders(tmp_path):
    r = run_case(tmp_path, scenario="owner_add")
    assert r["paused"] and r["pages"] == ["owner_add"]
    assert r["limit_submissions"] == 0 and r["owner_mutations"] == []


def test_adopted_below_trigger_sells_on_the_first_persisted_breach(tmp_path):
    r = run_case(tmp_path, scenario="adopted_below")
    adoption = next(e for e in r["events"] if e["event"] == "adoption")
    assert D(adoption["entry"]) == D("100.02")
    assert D(adoption["high"]) == D(98)
    assert D(adoption["trigger"]) == D("99.81996")
    assert r["exit_reason"] == "adopted-below-trigger" and r["sold"] == "8"


def test_outside_rth_uses_native_bid_ask_emulation_and_one_limit_release(tmp_path):
    r = run_case(tmp_path, scenario="outside")
    assert r["emulations"] == 1 and r["releases"] == 1
    assert r["sold"] == "8" and r["owner_mutations"] == []
    assert r["max_house_exits"] == 1 and r["reservation_violations"] == []


def test_run_ledger_appends_every_arm_and_keeps_tiers_separate(tmp_path):
    from sextant.backtest.owner_b_witness import run

    run(tmp_path)
    run(tmp_path)
    rows = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert len(rows) == 6
    assert [r["arm"] for r in rows] == ["option-b", "native-trail-o0", "hold"] * 2
    assert [r["tier"] for r in rows] == ["SIMULATED", "SIMULATED", "MODELED"] * 2
    assert all(r["params_hash"] and r["data_hash"] and r["run_id"] for r in rows)
    assert len({r["run_id"] for r in rows}) == 2


def test_each_individual_attempt_is_ledgered_with_its_actual_latency(tmp_path):
    run_case(tmp_path, scenario="normal", latency_ns=1_200_000_000)
    rows = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["latency_ns"] == 1_200_000_000
    assert rows[0]["gap1_ns"] == 2_000_000_000
    assert rows[0]["gap2_ns"] is None and rows[0]["status"] == "completed"
    assert rows[0]["code_hash"] and rows[0]["arm_run_id"]


def test_full_owner_reservation_alerts_then_freed_quantity_gets_one_trail(tmp_path):
    r = run_case(tmp_path, scenario="owner_reserved")
    assert not r["paused"] and "owner_reserved_unprotected" in r["pages"]
    assert len(r["resting_trails"]) == 1
    assert r["resting_trails"][0]["leaves"] == "10"
    assert r["max_house_exits"] == 1 and r["reservation_violations"] == []
    assert r["gross_pnl_usd"] is None  # Custody drills are not matched economic arms.


def test_unknown_scenario_is_refused_and_the_failed_attempt_is_not_erased(tmp_path):
    with pytest.raises(ValueError, match="unknown scenario"):
        run_case(tmp_path, scenario="misspelled-scenario")
    rows = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["status"] == "failed"
