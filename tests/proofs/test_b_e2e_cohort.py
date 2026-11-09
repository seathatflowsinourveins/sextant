"""PR-3's six-mover cohort proof: the first-leg entry, B's trail, and ADR-0024 slots.

The committed tape (``tests/fixtures/b-e2e-cohort.json``) is pinned here, so a change to the
fixture fails before any replay runs. The fixture is synthetic (AAA/BBB/CCC/DDD) and small by
design; the real six-mover run reads today's SIP tapes and the e2e-omh K2 ranks.

The behaviour under proof:
- the first leg is five non-decreasing prints above the quiet price, inside
  ``first_leg_window_s`` and ``first_leg_max_move``;
- entry fills at the fresh ask at run completion and a stale ask is refused, never loosened;
- B's 2.5% trail exits at the first print below the high minus 2.5%;
- the control arm's busy slot refuses the next run, and ADR-0006's flat-slot rotation gives
  the freed slot to the best-ranked pending name with no lift;
- every arm writes MODELED rows to the one cumulative ledger, refusals included.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from sextant.backtest.b_e2e import reviewed_rule
from sextant.backtest.b_e2e_cohort import (
    entry,
    find_run,
    load_cases,
    run_arms,
    trail,
    write_rows,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "b-e2e-cohort.json"
FIXTURE_SHA256 = "7b0c1d88a255424ae0a9da586d98fb8c29fd5fa73258e506351fb800adcebcf6"


def _cases():
    return {case.case: case for case in load_cases(FIXTURE)}


def _run(name: str):
    run = find_run(_cases()[name].trades, reviewed_rule())
    assert run is not None, name
    return run


def test_fixture_tape_is_pinned():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA256


def test_first_leg_finds_five_non_decreasing_prints_within_the_cap():
    run = _run("aaa")

    assert run.quiet == Decimal("5.40")
    assert run.last == Decimal("5.50")
    assert run.n == 5
    assert run.span_ns >= 2_000_000_000
    assert run.flag_ns == run.start_ns
    assert run.confirm_ns == run.start_ns + 4_000_000_000


def test_entry_fills_at_the_fresh_ask_and_a_stale_quote_is_refused():
    cases = _cases()
    aaa = cases["aaa"]
    filled, reason = entry(aaa, _run("aaa"), reviewed_rule())
    assert reason == ""
    assert filled is not None
    assert filled.price == Decimal("5.41")
    assert filled.ts_ns == _run("aaa").flag_ns

    ddd = cases["ddd"]
    refused, refusal = entry(ddd, _run("ddd"), reviewed_rule())
    assert refused is None
    assert "fresh" in refusal


def test_the_trail_exits_at_the_first_print_below_high_minus_2_5_percent():
    aaa = _cases()["aaa"]
    filled, _ = entry(aaa, _run("aaa"), reviewed_rule())
    assert filled is not None
    walked = trail(aaa, filled)

    assert walked.high == Decimal("5.60")
    assert walked.level == Decimal("5.46")
    assert walked.exit_price == Decimal("5.40")
    assert walked.exit_ts_ns == filled.ts_ns + 9_000_000_000
    assert walked.protected == pytest.approx(float(Decimal("5.40") / Decimal("5.41") - 1))
    assert walked.hold_flat == pytest.approx(float(Decimal("5.60") / Decimal("5.41") - 1))


def test_a_busy_slot_refuses_every_later_run_in_the_control_arm():
    rows = run_arms(list(_cases().values())[:3], capacity=1, rotation=False)
    states = {row.case.case: (row.state, row.reason) for row in rows}

    assert states["aaa"][0] == "COMPLETE"
    assert states["bbb"] == ("FAIL", "no slot under this arm")
    assert states["ccc"] == ("FAIL", "no slot under this arm")


def test_rotation_fills_a_flat_slot_with_the_best_pending_name():
    rows = run_arms(list(_cases().values())[:3], capacity=1, rotation=True)
    states = {row.case.case: row for row in rows}

    assert states["bbb"].state == "COMPLETE"
    assert states["bbb"].entry is not None
    assert states["bbb"].entry.price == Decimal("10.50")
    assert states["bbb"].slot == 1
    assert "rotate" in states["bbb"].reason
    assert states["ccc"].state == "COMPLETE"


def test_eight_slots_take_every_quotable_entry_and_refusals_stay_failed():
    rows = run_arms(list(_cases().values()), capacity=8, rotation=False)
    states = {row.case.case: row.state for row in rows}

    assert states == {"aaa": "COMPLETE", "bbb": "COMPLETE", "ccc": "COMPLETE", "ddd": "FAIL"}
    ddd = next(row for row in rows if row.case.case == "ddd")
    assert "fresh" in ddd.reason


def test_every_arm_writes_one_modeled_row_per_case(tmp_path):
    cases = list(_cases().values())
    rows = run_arms(cases, capacity=8, rotation=False)
    log = tmp_path / "trials.parquet"
    write_rows(rows, cases, log, session="2026-11-09")

    written = pq.read_table(log).to_pylist()
    assert len(written) == len(cases) + len(rows)
    assert {row["strategy"] for row in written} == {
        "b_e2e_cohort",
        "b_e2e_cohort_hold_flat",
    }
    for row in written:
        config = json.loads(row["config"])
        assert config["tier"] == "MODELED"
        assert config["block_set_id"] == "2026-11-09"
    failed = [row for row in written if row["state"] == "FAIL"]
    assert len(failed) == 1
    assert "fresh" in failed[0]["error"]
