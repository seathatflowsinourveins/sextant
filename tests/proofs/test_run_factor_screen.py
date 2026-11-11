"""Round-410 proofs: one stable cumulative ledger and per-arm attempt records."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    assert [row["n_trials"] for row in first] == list(range(1, 13))
    assert _run(catalog, catalog.parent / "out-2") == 0
    both = TrialLog(ledger).records
    assert len(both) == 24
    assert [row["n_trials"] for row in both] == list(range(1, 25))
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
