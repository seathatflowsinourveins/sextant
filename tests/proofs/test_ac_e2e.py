"""Proof that the A/C node's recorded-session e2e decides and protects by rule."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from sextant.backtest.ac_e2e import Point, append_trials, load_tape, run, run_case, trail
from sextant.paper.ac_node import entry_parameters, profiles
from sextant.validation.trials import TrialLog


@pytest.fixture(scope="module")
def report():
    return run()


def test_tape_is_todays_six_movers_and_the_recorded_catalyst():
    cases, witnesses = load_tape()
    assert [case.symbol for case in cases] == ["ONDS", "NWGL", "TTD", "MF", "OMH", "CKX", "SPCX"]
    assert {row["symbol"] for row in witnesses} == {"OMH", "PARA"}
    spcx = cases[-1]
    assert spcx.session == "2026-10-21"
    assert spcx.catalyst_at is not None


def test_only_the_catalyst_places_orders(report):
    assert len(report["orders"]) == 2
    assert {order["profile"] for order in report["orders"]} == {"a", "c"}
    assert {order["symbol"] for order in report["orders"]} == {"SPCX"}
    for order in report["orders"]:
        assert order["setup"] == "CATALYST"
        assert order["side"] == "BUY"
        assert order["order_type"] == "LIMIT"
        assert order["time_in_force"] == "DAY"
        assert order["tier"] == "MODELED"
        assert Decimal(order["limit"]) == Decimal("161.21")
        assert Decimal(order["quantity"]) == Decimal("1240")
        assert Decimal(order["stop"]) == Decimal("157.17975")
    assert report["orders"][0]["mode"] == "replay"
    assert report["orders"][1]["mode"] == "paper-slot-3"


def test_the_catalyst_reproduces_pr3(report):
    cases, _ = load_tape()
    spcx = cases[-1]
    assert spcx.pr3 is not None
    assert spcx.pr3["entry"] == "161.21"
    result = run_case(spcx, profiles()["a"], entry_parameters(fixture=True))
    assert result.accepted[0].accepted
    for order in report["orders"]:
        assert abs(Decimal(order["protected"]) - Decimal("-0.008312")) <= Decimal("0.0002")
        # PR-3's hold-flat is the 16:00 ET 1-minute close (159.27), not the exit print.
        assert abs(Decimal(order["hold_flat"]) - Decimal("-0.0120")) <= Decimal("0.0002")


def test_pre_risk_uses_the_half_risk_rule():
    cases, _ = load_tape()
    spcx = cases[-1]
    params = entry_parameters(fixture=True)
    result = run_case(spcx, profiles()["a"], params)
    plan = result.accepted[0].plan
    assert plan.planned_risk is not None
    assert plan.planned_risk.as_decimal() == Decimal("5000")
    assert plan.binding == "risk"
    assert plan.rank is None


def test_rank_armed_cases_refuse_on_the_recorded_tape(report):
    reasons = {
        (row["profile"], row["symbol"]): row["reason"]
        for row in report["trial_rows"]
        if row["state"] == "REFUSED"
    }
    assert len(reasons) == 12
    for profile in ("a", "c"):
        for symbol in ("ONDS", "TTD", "MF", "CKX"):
            assert "no K2 generation recorded" in reasons[(profile, symbol)]
        for symbol in ("NWGL", "OMH"):
            assert "first_leg_max_move" in reasons[(profile, symbol)]
    assert not any(row["symbol"] in {"NWGL", "OMH"} for row in report["orders"])


def test_witnesses_reproduce_pr3(report):
    witnesses = {row["symbol"]: row for row in report["witnesses"]}
    omh = witnesses["OMH"]
    assert omh["agrees"] is True
    assert Decimal(omh["high"]) == Decimal("14.9208")
    assert Decimal(omh["level"]) == Decimal("14.5477800")
    assert Decimal(omh["exit"]) == Decimal("14.30")
    assert abs(Decimal(omh["protected"]) - Decimal("-0.0396")) <= Decimal("0.0002")
    assert abs(Decimal(omh["hold_flat"]) - Decimal("1.6971")) <= Decimal("0.0002")
    para = witnesses["PARA"]
    assert para["agrees"] is None
    assert para["path_points"] == 0


def test_account_paths_show_the_fixed_and_compounding_bases(report):
    accounts = report["accounts"]
    assert accounts["a"]["mode"] == "fixed"
    assert accounts["c"]["mode"] == "current"
    assert accounts["a"]["end_equity"] == accounts["c"]["end_equity"] == "998338.40 USD"
    assert accounts["a"]["next_sizing_equity"] == "1000000.00 USD"
    assert accounts["c"]["next_sizing_equity"] == "998338.40 USD"
    assert Decimal(accounts["c"]["next_risk_budget"]) < Decimal(accounts["a"]["next_risk_budget"])


def test_every_arm_is_a_modeled_trial_row(report):
    rows = report["trial_rows"]
    assert len(rows) == 14
    assert {row["state"] for row in rows} == {"ACCEPTED", "REFUSED"}
    assert all(row["tier"] == "MODELED" for row in rows)
    assert all(len(row["params_hash"]) == 64 for row in rows)


def test_trail_is_the_25_percent_level_rule():
    entry = Decimal("10")
    path = (
        Point(1, Decimal("10.2")),
        Point(2, Decimal("10.5")),
        Point(3, Decimal("10.23")),
        Point(4, Decimal("9.5")),
    )
    outcome = trail(entry, path)
    assert outcome.high == Decimal("10.5")
    assert outcome.level == Decimal("10.2375")
    assert outcome.exit_price == Decimal("10.23")
    assert outcome.protected == Decimal("0.023")


def test_e2e_rows_append_to_the_cumulative_trial_log(tmp_path: Path):
    report = run()
    path = tmp_path / "trials.parquet"
    assert append_trials(report, path) == 14
    log = TrialLog(path)
    assert len(log.records) == 14
    assert {record["state"] for record in log.records} == {"COMPLETE", "FAIL"}
    identities = []
    for record in log.records:
        config = json.loads(record["config"])
        assert config["tier"] == "MODELED"
        assert config["factor_mask"]
        assert len(config["implementation_sha"]) == 40
        identities.append(config["arm_run_id"])
    assert len(set(identities)) == 14
    # A rerun is a fresh attempt: the ledger only grows, never rewrites.
    assert append_trials(report, path) == 14
    assert TrialLog(path).n_trials == 28
