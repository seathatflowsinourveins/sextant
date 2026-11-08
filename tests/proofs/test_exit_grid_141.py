"""#141: the registered pre-arm noise grid and its one run, grid-1.

The first five proofs need no market data and run no cell. The rest check the committed run in
docs/research/2026-11-06-exit-grid-141/ against the registration, the ledger's reservation, #98's
evidence and its own sums. The per-cell rerun needs #41's exact inputs and an opt-in:
SEXTANT_RERUN_141=1, with the inputs in ~/sextant-data/exit-study-41 or SEXTANT_EXIT_STUDY_41.
Each cell is its own test (about 2 minutes), so separate processes can split the 27.
"""

import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from sextant.exits.policy import ExitParams
from sextant.research import exit_econ_98 as x98
from sextant.research import exit_grid_141 as grid
from sextant.research.exit_study_41 import DEFAULT_INPUTS, INPUTS

ROOT = Path(__file__).parents[2]
EVIDENCE = ROOT / "docs" / "research" / "2026-11-06-exit-grid-141"
E98 = ROOT / "docs" / "research" / "2026-11-06-exit-econ-98"
INPUT_DIR = Path(os.environ.get("SEXTANT_EXIT_STUDY_41", str(DEFAULT_INPUTS)))
# grid-1: registered on #141, reserved on `ledger` at 8f045fae (trials 112-138), closed via #102.
ATTEMPT = Path("/home/sextant/sextant-data/exit-141/grid-1")
RESERVED_SHA = "4656648c6ed174403ffc5490eec7f2136772c6c2"
REGISTRATION_SHA256 = "8302f7c34738260a56822205a617699f947d27409c8332c55be26398522285c6"
RESERVE = {
    "rows_sha256": "7c9ca6721673b502ac7fd783361c98ae878d012b42511755a55d5a3661f834fe",
    "manifest_sha256": "1e9fafbe5a71c1547902976ff01c9cf98a40dca4905a5bab14b3125e77921e83",
}
OUTCOME = {
    "rows_sha256": "2190e30922d1e43c7865b992840967bfb981507be3f03dcb0f3b1f58513f82b7",
    "manifest_sha256": "45ff64af778590dbed30f08311ac3e7587461a4518cab80416e38ac42a748d6f",
}
STARTS = "b0.01-m1-g0.1"
# Lead ruling (a), 2026-11-07: PR 2's engine run (attempt pr2-a8282a4, a late reservation on #102)
# sits beside the committed surface, which stays as history; the per-cell rerun reproduces it.
RUN = EVIDENCE / "run-a8282a4"
COSTS = ("3", "6")


def _report() -> dict[str, Any]:
    return json.loads((EVIDENCE / "report.json").read_text())


def _outcome() -> list[dict[str, Any]]:
    return [json.loads(x) for x in (EVIDENCE / "outcome.jsonl").read_text().splitlines()]


def _e98_entries() -> list[dict[str, Any]]:
    rows = map(json.loads, (E98 / "entries.jsonl").read_text().splitlines())
    return [r for r in rows if r["arm"] == "exit-engine-starts-rw-dropped"]


def _cell(arm_run_id: str) -> str:
    return arm_run_id.rsplit("#", 1)[1]


def test_the_grid_is_exactly_adr_0019s_documented_grids() -> None:
    assert grid.AXES == {
        "prearm_buffer_fraction": (D("0.005"), D("0.01"), D("0.02")),
        "prearm_range_multiple": (D("0.5"), D(1), D(2)),
        "gain_lock_giveback_fraction": (D(0), D("0.1"), D("0.25")),
    }
    cells = grid.cells()
    assert len(cells) == 27 and len({c for c, _ in cells}) == 27
    starts = ExitParams.starts()
    for _cid, p in cells:
        assert not p.chase_on  # both chase rows stay unavailable (#98)
        assert p.breach_persist_count == starts.breach_persist_count
        assert p.breach_persist_span_s == starts.breach_persist_span_s
    assert STARTS in {c for c, _ in cells}  # the recorded starts are one cell


def test_the_registration_names_its_sources_and_selects_nothing() -> None:
    reg = grid.registration()
    assert set(reg["axis_sources"]) == set(grid.AXES)
    assert all(
        "7c5f852a2816bbaa5896241a93bab9de7cf7bb4f" in s for s in reg["axis_sources"].values()
    )
    assert reg["selection"].startswith("none")
    assert "chase not estimable on minute bars" in reg["sandbox"]["chase"]
    assert "not estimable" in reg["sandbox"]["range_term"]
    assert len(reg["cells"]) == 27


def test_reservations_follow_the_ledger_handoff(tmp_path: Path) -> None:
    rows = grid.reserve_rows(tmp_path / "reserve", "a" * 40)
    assert len(rows) == 27
    ids = [r["config"]["arm_run_id"] for r in rows]
    assert len(set(ids)) == 27
    for row in rows:
        config = row["config"]
        assert config["tier"] == "MODELED" and config["condition_returns"] == {}
        assert config["params_hash"] == grid.snapshot_hash(row["params"])
        assert config["sandbox_config_hash"] == grid.snapshot_hash(config["sandbox_config"])
        # The same block set as the ORB reservation on `ledger` (handoffs/templates/...).
        assert config["block_set_id"] == (
            "exit-study-41:e5248626a8c2a44b57c345c8caa9b86ddcf40f0589acf01d66f6fe97d8b0c9bf"
        )
    assert grid.snapshot_hash({}) == (
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )
    receipt = grid.write_batch(tmp_path / "reserve", "reserve", rows)
    raw = (tmp_path / "reserve" / "rows.jsonl").read_bytes()
    manifest = json.loads((tmp_path / "reserve" / "manifest.json").read_text())
    assert manifest["rows_sha256"] == hashlib.sha256(raw).hexdigest() == receipt["rows_sha256"]
    assert manifest["count"] == 27 and manifest["lane"] == "exit" and manifest["issue"] == 141


def test_the_run_refuses_a_head_that_was_not_reserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = tmp_path / "grid-x"
    rows = grid.reserve_rows(attempt / "reserve", "b" * 40)
    grid.write_batch(attempt / "reserve", "reserve", rows)
    monkeypatch.setattr(grid, "_git", lambda *a: "" if a[0] == "status" else "c" * 40)
    with pytest.raises(RuntimeError, match="reserved implementation commit"):
        grid.run(tmp_path, attempt, tmp_path / "out")


def test_the_run_glue_closes_every_reserved_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stubbed evaluate: no cell is evaluated, only the glue around it is checked."""
    attempt = tmp_path / "grid-x"
    sha = "d" * 40
    attempt.mkdir()
    (attempt / "registration.json").write_text("{}\n")
    grid.write_batch(attempt / "reserve", "reserve", grid.reserve_rows(attempt / "reserve", sha))
    monkeypatch.setattr(grid, "_git", lambda *a: "" if a[0] == "status" else sha)
    monkeypatch.setattr(grid.x98, "prepare", lambda *_a, **_k: {"hashes": {}, "cohort": 2})
    summary = {"n": 2, "mean_bps": "1", "median_bps": "1", "win_rate": "1", "pnl_units": "1"}

    def fake(_ctx: Any, _p: Any, **_k: Any) -> dict[str, Any]:
        rows = [
            {"day": "2026-10-26", "3": {"managed": "0.01"}, "6": {"managed": "0.005"}},
            {"day": "2026-10-27", "3": {"managed": "-0.01"}, "6": {"managed": "-0.02"}},
        ]
        return {
            "per_entry": rows,
            "arm": {"3": summary, "6": summary, "attribution": {"3": {}, "6": {}}},
            "controls": {"hold_flat": {"3": summary, "6": summary}},
        }

    monkeypatch.setattr(grid.x98, "evaluate", fake)
    report = grid.run(tmp_path, attempt, tmp_path / "out")
    assert report["selected"] is None and len(report["surface"]) == 27
    outcome = [json.loads(x) for x in (attempt / "outcome" / "rows.jsonl").read_text().splitlines()]
    assert [o["arm_run_id"] for o in outcome] == [
        r["config"]["arm_run_id"] for r in grid.reserve_rows(attempt / "reserve", sha)
    ]
    first = outcome[0]
    assert first["state"] == "COMPLETE" and first["days"] == ["2026-10-26", "2026-10-27"]
    assert first["condition_returns"] == {"1x": [0.01, -0.01], "2x": [0.005, -0.02]}
    assert first["result"]["selected"] is False and first["result"]["tier"] == "MODELED"


def test_the_committed_registration_is_the_registered_grid() -> None:
    raw = (EVIDENCE / "registration.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == REGISTRATION_SHA256
    assert _report()["registration_sha256"] == REGISTRATION_SHA256
    assert raw == (json.dumps(grid.registration(), indent=2, sort_keys=True) + "\n").encode()


def test_the_ledgers_reservation_is_this_grid_at_the_run_commit(tmp_path: Path) -> None:
    rows = grid.reserve_rows(ATTEMPT / "reserve", RESERVED_SHA)
    assert grid.write_batch(tmp_path / "reserve", "reserve", rows) == RESERVE
    assert _report()["implementation"] == RESERVED_SHA


def test_the_surface_is_every_registered_cell_and_nothing_is_selected() -> None:
    report = _report()
    registered = json.loads((EVIDENCE / "registration.json").read_text())["cells"]
    assert {c["cell"]: c["params"] for c in registered} == {
        cid: cell["params"] for cid, cell in report["surface"].items()
    }
    assert report["selected"] is None and report["tier"] == "MODELED"
    assert report["execution_model"] == x98.MODEL
    assert report["inputs"] == INPUTS and report["cohort"] == 1025


def test_the_range_multiple_is_inert_while_r_w_is_not_estimable() -> None:
    surface = _report()["surface"]
    for b in grid.AXES["prearm_buffer_fraction"]:
        for g in grid.AXES["gain_lock_giveback_fraction"]:
            same = [
                {k: v for k, v in surface[f"b{b}-m{m}-g{g}"].items() if k != "params"}
                for m in grid.AXES["prearm_range_multiple"]
            ]
            assert same[0] == same[1] == same[2], (b, g)


def test_the_starts_cell_reproduces_98s_arm_with_r_w_dropped() -> None:
    kept, cell = json.loads((E98 / "report.json").read_text()), _report()["surface"][STARTS]
    assert cell["params"] == kept["params"]
    for c in COSTS:
        assert cell[c] == kept["arms"][f"exit-engine-starts-rw-dropped/{c}"]
        assert cell["attribution"][c] == kept["attribution"][f"exit-engine-starts-rw-dropped/{c}"]
    # Its daily returns are #98's committed per-entry rows, averaged by day, recomputed here.
    row = next(r for r in _outcome() if _cell(r["arm_run_id"]) == STARTS)
    for c, returns in (("3", row["daily_net_returns"]), ("6", row["condition_returns"]["2x"])):
        by_day: dict[str, list[D]] = defaultdict(list)
        for entry in _e98_entries():
            by_day[entry["day"]].append(D(entry[c]["managed"]))
        assert sorted(by_day) == row["days"]
        assert [float(sum(v, D(0)) / len(v)) for _d, v in sorted(by_day.items())] == returns


def test_both_controls_equal_98s() -> None:
    kept, controls = json.loads((E98 / "report.json").read_text())["arms"], _report()["controls"]
    assert set(controls) == set(x98.CONTROLS)
    for name in x98.CONTROLS:
        for c in COSTS:
            assert controls[name][c] == kept[f"{name}/{c}"], (name, c)


def test_each_cells_attribution_adds_up_to_its_gap_against_holding() -> None:
    report = _report()
    for cid, cell in report["surface"].items():
        for c in COSTS:
            groups = cell["attribution"][c]
            gap = D(cell[c]["mean_bps"]) - D(report["controls"]["hold_flat"][c]["mean_bps"])
            total = sum((D(g["gap_contribution_bps"]) for g in groups.values()), D(0))
            assert abs(total - gap) < D("1e-18"), (cid, c)
            assert sum(g["n"] for g in groups.values()) == report["cohort"]
            if "flat_1555" in groups:
                assert D(groups["flat_1555"]["gap_contribution_bps"]) == 0


def test_the_outcome_closes_every_reserved_attempt_with_the_reported_numbers(
    tmp_path: Path,
) -> None:
    raw = (EVIDENCE / "outcome.jsonl").read_bytes()
    rows = _outcome()
    assert hashlib.sha256(raw).hexdigest() == OUTCOME["rows_sha256"]
    assert grid.write_batch(tmp_path / "outcome", "outcome", rows) == OUTCOME
    reserved = grid.reserve_rows(ATTEMPT / "reserve", RESERVED_SHA)
    assert [r["arm_run_id"] for r in rows] == [r["config"]["arm_run_id"] for r in reserved]
    surface = _report()["surface"]
    for row in rows:
        result, cell = row["result"], surface[_cell(row["arm_run_id"])]
        assert row["state"] == "COMPLETE"
        assert row["days"] == ["2026-10-26", "2026-10-27", "2026-10-28"]
        assert row["condition_returns"]["1x"] == row["daily_net_returns"]
        assert result["selected"] is False and result["tier"] == "MODELED"
        assert result["inputs"] == INPUTS and result["n"] == 1025
        assert result["params_hash"] == grid.snapshot_hash(cell["params"])
        assert result["attribution"] == cell["attribution"]
        for c in COSTS:
            assert all(result[f"{k}_{c}"] == cell[c][k] for k in x98.METRICS)


def test_each_cells_daily_returns_average_back_to_its_mean() -> None:
    """The float64 day means, weighted by the cohort's entries per day, give the Decimal mean."""
    per_day = Counter(entry["day"] for entry in _e98_entries())
    n = sum(per_day.values())
    surface = _report()["surface"]
    for row in _outcome():
        cell = surface[_cell(row["arm_run_id"])]
        for key, c in (("1x", "3"), ("2x", "6")):
            daily = row["condition_returns"][key]
            mean = sum(per_day[d] * v for d, v in zip(row["days"], daily, strict=True)) / n
            assert all(math.isfinite(v) for v in daily)
            expected = float(D(cell[c]["mean_bps"]) / 10000)
            assert math.isclose(mean, expected, rel_tol=1e-12, abs_tol=1e-15), (
                row["arm_run_id"],
                c,
            )


RERUN = os.environ.get("SEXTANT_RERUN_141") == "1" and all(
    (INPUT_DIR / name).exists() for name in INPUTS
)


@pytest.fixture(scope="module")
def ctx(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return x98.prepare(INPUT_DIR, tmp_path_factory.mktemp("rerun-141") / "catalog")


@pytest.mark.skipif(
    not RERUN,
    reason="opt-in (SEXTANT_RERUN_141=1) and the exact inputs of #41 are needed (2 minutes a cell)",
)
@pytest.mark.parametrize("cid", [c for c, _ in grid.cells()])
def test_each_cell_reruns_to_its_committed_surface(cid: str, ctx: dict[str, Any]) -> None:
    result = x98.evaluate(ctx, dict(grid.cells())[cid], range_estimable=False, arm=cid)
    report = json.loads((RUN / "report.json").read_text())
    assert {k: v for k, v in report["surface"][cid].items() if k != "params"} == result["arm"]
    assert result["controls"] == report["controls"]
