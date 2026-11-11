"""Round-410 proofs: one stable cumulative ledger and per-arm attempt records."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_trial_log import without_counts

from sextant.validation.trials import WITNESS_PATH, TrialLog

REPOSITORY = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "run_factor_screen", REPOSITORY / "scripts" / "run_factor_screen.py"
)
assert _SPEC is not None and _SPEC.loader is not None
runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runner)
fs = runner.fs


def _result(arm: str) -> dict:
    spec = fs.ARMS[arm]
    return {
        "arm": arm,
        "state": "COMPLETE",
        "kind": spec["kind"],
        "source": spec["source"],
        "error": "",
        "sample_state": "INSUFFICIENT_N",
        "costs": {
            "1x": {"mean_net_bps": 0.0, "n_trades": 0, "session_returns": {}},
            "2x": {"mean_net_bps": 0.0, "n_trades": 0, "session_returns": {}},
        },
        "days": [],
        "daily_net_returns": [],
        "condition_returns": {},
    }


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ledger = tmp_path / "trials.parquet"
    seen: list[Path] = []
    real = TrialLog

    def factory(path: Path) -> TrialLog:
        seen.append(Path(path))
        return real(ledger)

    monkeypatch.setattr(runner, "TrialLog", factory)
    monkeypatch.setattr(runner, "verify", lambda inputs, catalog: {})
    monkeypatch.setattr(runner, "load", lambda catalog: ({}, {"X": [SimpleNamespace(ts_event=0)]}))
    monkeypatch.setattr(runner, "plan_for", lambda arm, rows: {})
    monkeypatch.setattr(
        runner, "arm_result", lambda arm, plan, bars, instruments, days: _result(arm)
    )
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    (catalog / "replay-catalog.json").write_text("{}\n")
    return ledger, seen, catalog


def _run(catalog: Path, out: Path) -> int:
    return runner.main(["--inputs", str(catalog), "--catalog", str(catalog), "--out", str(out)])


def test_second_run_continues_the_one_cumulative_ledger(env) -> None:
    ledger, seen, catalog = env
    assert _run(catalog, catalog.parent / "out-1") == 0
    first = TrialLog(ledger).records
    assert len(first) == 12
    assert [(row["n_trials"], row["effective_n"]) for row in first] == [(12, 12.0)] * 12
    assert _run(catalog, catalog.parent / "out-2") == 0
    both = TrialLog(ledger).records
    assert len(both) == 24
    assert [(row["n_trials"], row["effective_n"]) for row in both] == [(24, 24.0)] * 24
    assert [row["trial_id"] for row in both] == list(range(24))
    assert len(set(seen)) == 1
    assert seen[0] == REPOSITORY / WITNESS_PATH


def test_reused_output_directory_is_still_refused(env) -> None:
    ledger, _seen, catalog = env
    out = catalog.parent / "out-1"
    assert _run(catalog, out) == 0
    with pytest.raises(FileExistsError):
        _run(catalog, out)
    assert len(TrialLog(ledger).records) == 12


def test_interrupted_arm_leaves_three_attempts(env, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger, _seen, catalog = env

    def boom(arm, plan, bars, instruments, days):
        if arm == "k2_bar_proxy":
            raise RuntimeError("engine exploded")
        return _result(arm)

    monkeypatch.setattr(runner, "arm_result", boom)
    out = catalog.parent / "out-interrupted"
    with pytest.raises(RuntimeError, match="engine exploded"):
        _run(catalog, out)
    rows = TrialLog(ledger).records
    assert len(rows) == 3
    assert [row["state"] for row in rows] == ["COMPLETE", "COMPLETE", "FAIL"]
    assert rows[2]["error"] == "RuntimeError"


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_plan_failure_is_recorded_before_arm_work(env, monkeypatch, failure) -> None:
    ledger, _seen, catalog = env

    def fail_plan(arm, rows):
        if arm == "k2_bar_proxy":
            raise failure("plan construction failed")
        return {}

    monkeypatch.setattr(runner, "plan_for", fail_plan)
    with pytest.raises(failure, match="plan construction failed"):
        _run(catalog, catalog.parent / "plan-failure")
    rows = TrialLog(ledger).records
    assert len(rows) == 3, [(row["strategy"], row["state"]) for row in rows]
    assert rows[-1]["strategy"] == "k2_bar_proxy"
    assert rows[-1]["state"] == "FAIL"
    assert rows[-1]["error"] == failure.__name__


def test_trial_mask_describes_only_its_executed_arm(env) -> None:
    ledger, _seen, catalog = env
    assert _run(catalog, catalog.parent / "identity") == 0
    for row in TrialLog(ledger).records:
        identity = json.loads(row["config"])
        expected = [row["strategy"]] if fs.ARMS[row["strategy"]]["kind"] == "factor" else []
        assert identity["factor_mask"] == expected, {
            "arm": row["strategy"],
            "actual": identity["factor_mask"],
            "expected": expected,
        }


def test_not_ready_arm_is_durable_when_append_is_interrupted(env, monkeypatch) -> None:
    ledger, _seen, catalog = env
    real_append = TrialLog.append
    evaluated: list[str] = []

    class ArmSpec(dict):
        def __getitem__(self, key):
            if key == "state":
                evaluated.append(self["_arm"])
            return super().__getitem__(key)

    monkeypatch.setattr(
        fs, "ARMS", {arm: ArmSpec({**spec, "_arm": arm}) for arm, spec in fs.ARMS.items()}
    )

    def interrupted_append(log, *args, **kwargs):
        trial_id = real_append(log, *args, **kwargs)
        if len(log.records) == 5:
            raise KeyboardInterrupt("between rejected arms")
        return trial_id

    monkeypatch.setattr(TrialLog, "append", interrupted_append)
    with pytest.raises(KeyboardInterrupt, match="between rejected arms"):
        _run(catalog, catalog.parent / "rejected-interrupt")
    rows = TrialLog(ledger).records
    recorded = {row["strategy"] for row in rows}
    assert set(evaluated) <= recorded, sorted(set(evaluated) - recorded)


def test_engine_keyboard_interrupt_is_finalized_and_recovered(env, monkeypatch) -> None:
    ledger, _seen, catalog = env

    def interrupt(arm, plan, bars, instruments, days):
        if arm == "k2_bar_proxy":
            raise KeyboardInterrupt("engine interruption")
        return _result(arm)

    monkeypatch.setattr(runner, "arm_result", interrupt)
    with pytest.raises(KeyboardInterrupt, match="engine interruption"):
        _run(catalog, catalog.parent / "keyboard-interrupt")
    rows = TrialLog(ledger).records
    assert [row["state"] for row in rows] == ["COMPLETE", "COMPLETE", "FAIL"]
    assert rows[-1]["error"] == "KeyboardInterrupt"
    monkeypatch.setattr(runner, "arm_result", lambda arm, *args: _result(arm))
    assert _run(catalog, catalog.parent / "after-keyboard-interrupt") == 0
    continued = TrialLog(ledger).records
    assert len(continued) == 15
    assert list(map(without_counts, continued[:3])) == list(map(without_counts, rows))
    assert [(row["n_trials"], row["effective_n"]) for row in continued] == [(15, 15.0)] * 15
