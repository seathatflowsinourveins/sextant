"""#98: our exit engine against hold-to-15:55 on #41's exact inputs, with per-arm attribution.

CI checks the committed rows. The full rerun (about 4 minutes) needs the exact inputs and an opt-in:
SEXTANT_RERUN_98=1, with the inputs in ~/sextant-data/exit-study-41 or SEXTANT_EXIT_STUDY_41.
"""

import dataclasses
import json
import os
from decimal import Decimal as D
from pathlib import Path

import pytest

from sextant.backtest.exit_witness import FIXTURE, run
from sextant.exits import policy
from sextant.exits.policy import REGISTRY, ExitParams
from sextant.research.exit_econ_98 import LABELS, trial_rows
from sextant.research.exit_econ_98 import run as rerun
from sextant.research.exit_study_41 import DEFAULT_INPUTS, INPUTS

ROOT = Path(__file__).parents[2]
EVIDENCE = ROOT / "docs" / "research" / "2026-11-06-exit-econ-98"
STUDY_41 = ROOT / "docs" / "research" / "2026-11-06-exit-study-41" / "trials.jsonl"
INPUT_DIR = Path(os.environ.get("SEXTANT_EXIT_STUDY_41", str(DEFAULT_INPUTS)))


def _rows(path: Path) -> dict[str, dict]:
    return {r["arm"]: r for r in map(json.loads, path.read_text().splitlines())}


def _report() -> dict:
    return json.loads((EVIDENCE / "report.json").read_text())


def test_every_start_is_sourced_and_both_chase_rows_stay_unavailable() -> None:
    p = ExitParams.starts()
    assert p.chase_min_interval_s is None and p.chase_cap_fraction is None and not p.chase_on
    rows = {r.name: r for r in REGISTRY}
    assert "no authority" in rows["chase_cap_fraction"].source
    assert all(r.start is not None for r in REGISTRY if r.name not in policy.CHASE)
    assert all("@" in r.source or "adr" in r.source for r in REGISTRY)


def test_with_no_chase_interval_the_fast_sell_rests_at_the_bid(tmp_path: Path) -> None:
    _m, _c, events = run(tmp_path, dataclasses.replace(FIXTURE, chase_min_interval_s=None))
    sell = next(e for e in events if e["event"].startswith("breach_sell"))
    assert "chase" not in [e["event"] for e in events]
    assert D(sell["limit"]) <= D(sell["trigger"])


def test_a_missing_chase_cap_alone_also_turns_the_chase_off(tmp_path: Path) -> None:
    p = dataclasses.replace(FIXTURE, chase_cap_fraction=None)
    assert not p.chase_on
    assert policy.chase_limit(D("9.98"), D(10), p) == D("9.98")
    _m, _c, events = run(tmp_path, p)
    assert "chase" not in [e["event"] for e in events]


def test_the_range_term_drops_only_where_it_is_not_estimable() -> None:
    p = ExitParams.starts()
    one_tick, spread, entry = D("0.01"), D("0.02"), D(10)
    assert policy.buffer(one_tick, spread, entry, None, p) is None
    assert policy.buffer(one_tick, spread, entry, None, p, range_estimable=False) == D("0.10")
    assert policy.buffer(one_tick, spread, entry, D(1), p, range_estimable=False) == D("0.10")


def test_both_controls_equal_the_67_rows() -> None:
    ours, old = _rows(EVIDENCE / "trials.jsonl"), _rows(STUDY_41)
    for arm, kept in (("hold_flat", "hold_flat"), ("C5-n22-k3-R-OFF-study", "C5-n22-k3-R-OFF")):
        for cost in ("mean_bps_3", "mean_bps_6"):
            assert D(ours[arm][cost]) == D(old[kept][cost]), (arm, cost)


def test_the_attribution_adds_up_to_each_arms_gap_against_holding() -> None:
    report = _report()
    for key, groups in report["attribution"].items():
        _arm, cost = key.rsplit("/", 1)
        gap = D(report["arms"][key]["mean_bps"]) - D(
            report["arms"][f"hold_flat/{cost}"]["mean_bps"]
        )
        total = sum((D(g["gap_contribution_bps"]) for g in groups.values()), D(0))
        assert abs(total - gap) < D("1e-18"), key
        assert sum(g["n"] for g in groups.values()) == report["cohort"]
        if "flat_1555" in groups:
            assert D(groups["flat_1555"]["gap_contribution_bps"]) == 0


def test_rows_are_modeled_bound_to_their_inputs_and_none_is_selected() -> None:
    rows = _rows(EVIDENCE / "trials.jsonl")
    assert set(rows) == set(LABELS)
    assert {r["tier"] for r in rows.values()} == {"MODELED"}
    assert {r["execution_model"] for r in rows.values()} == {"minute-bar-approximate"}
    assert all(r["inputs"] == INPUTS and r["n"] == 1025 for r in rows.values())
    assert not any(r["selected"] for r in rows.values())
    assert list(rows.values()) == trial_rows(_report())


@pytest.mark.skipif(
    os.environ.get("SEXTANT_RERUN_98") != "1"
    or not all((INPUT_DIR / name).exists() for name in INPUTS),
    reason="opt-in (SEXTANT_RERUN_98=1) and the exact inputs of #41 are needed (about 4 minutes)",
)
def test_full_rerun_regenerates_the_committed_rows(tmp_path: Path) -> None:
    report = rerun(INPUT_DIR, tmp_path)
    kept = _report()
    assert report["arms"] == kept["arms"]
    assert report["attribution"] == kept["attribution"]
