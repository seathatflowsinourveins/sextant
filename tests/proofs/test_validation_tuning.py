"""Proofs for the reusable ``sextant.validation.tuning`` engine: CPCV scoring and purge, the
cumulative trial ledger, one untouched holdout, and the deflated-Sharpe/PBO statistics.

These tests are restored unchanged from ``tests/proofs/test_b_tuning.py`` at 5830f0e, whose
B-specific adapter and replay tests continue on the tagged research branch
``research/b-replay-5830f0e`` at ``b-replay-2026-11-10``. ``PARAMETERS`` is the six-row search
space those tests ran with, kept here as test support because the adapter that defined it
archived with the study.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from sextant.validation import tuning


def _sessions(count: int = 60) -> tuple[str, ...]:
    start = date(2020, 1, 1)
    return tuple((start + timedelta(days=31 * index)).isoformat() for index in range(count))


_WEIGHTS = {
    "native_trail_fraction": 400.0,
    "first_leg_window_s": 0.01,
    "first_leg_trades_count": 1.0,
    "first_leg_span_s": 0.5,
    "first_leg_max_move": 100.0,
    "max_data_age_s": 0.2,
}


_TRAIL = "docs/adr/0025-gain-protection-and-fast-exit.md B scope (0.025 cap)"
_N = "northstar-trading@8256c16c31dc "
_E = "entry-parameters.json:"
_WINDOW = f"{_E}first_leg_window_s; {_N}profiles.yaml:114"
_TRADES = f"{_E}first_leg_trades_count; {_N}profiles.yaml:126"
_SPAN = f"{_E}first_leg_span_s; {_N}profiles.yaml:138"
_MOVE = f"{_E}first_leg_max_move; {_N}profiles.yaml:162 and ADR-0024"
_AGE = f"{_E}max_data_age_s; {_N}profiles.yaml:174 and base.py:144"


def _float(name: str, low: float, high: float, step: float, source: str) -> tuning.FloatParameter:
    return tuning.FloatParameter(name, low, high, step=step, source=source)


def _int(name: str, low: int, high: int, step: int, source: str) -> tuning.IntParameter:
    return tuning.IntParameter(name, low, high, step=step, source=source)


PARAMETERS = (
    _float("native_trail_fraction", 0.0025, 0.025, 0.0025, _TRAIL),
    _int("first_leg_window_s", 30, 300, 30, _WINDOW),
    _int("first_leg_trades_count", 2, 10, 1, _TRADES),
    _int("first_leg_span_s", 0, 10, 1, _SPAN),
    _float("first_leg_max_move", 0.01, 0.03, 0.0025, _MOVE),
    _int("max_data_age_s", 1, 30, 1, _AGE),
)


def _spec(**changes: object) -> tuning.StudySpec:
    base: dict[str, object] = dict(
        name="b-parameters",
        symbol_class="mover",
        arm="2-slot",
        parameters=PARAMETERS,
        n_trials=100,
        n_folds=4,
        n_test_folds=2,
        label_horizon=1,
        seed=20261109,
    )
    base.update(changes)
    return tuning.StudySpec(**base)  # type: ignore[arg-type]


def _evaluate(sessions: tuple[str, ...], holdout: tuple[str, ...] = ()):
    """A deterministic monotone series: better parameters mean better sessions."""

    def evaluate(params, days):
        score = sum(float(params[name]) * weight for name, weight in _WEIGHTS.items())
        observations = []
        for index, day in enumerate(sessions):
            if day not in days:
                continue
            value = 0.0005 + 0.00002 * score + ((index * 37) % 11 - 5) * 1e-6
            if day in holdout:
                value = -abs(value)
            observations.append(tuning.Observation(day, f"case-{index}", value))
        return tuple(observations)

    return evaluate


def test_sharpe_is_the_upstream_annualized_ratio() -> None:
    values = [0.01, 0.02, -0.005]
    expected = float(np.mean(values) / np.std(values, ddof=0) * np.sqrt(252))
    assert tuning.sharpe(values) == pytest.approx(expected)
    assert tuning.sharpe([0.01, 0.01, 0.01]) == 0.0


def test_session_series_equal_weights_the_cases_in_a_session() -> None:
    observations = (
        tuning.Observation("2026-11-09", "aaa", 0.01),
        tuning.Observation("2026-11-09", "bbb", -0.01),
        tuning.Observation("2026-11-10", "ccc", 0.02),
    )
    days, returns = tuning.session_series(observations, ("2026-11-09", "2026-11-10"))
    assert days == ["2026-11-09", "2026-11-10"]
    assert returns == [0.0, 0.02]


def test_cpcv_paths_cover_every_session_once_with_purge_and_embargo() -> None:
    folds = tuning.cpcv_folds(16, n_folds=4, n_test_folds=2, label_horizon=1)
    assert len(folds) == 6
    held_out: Counter[int] = Counter()
    for fold in folds:
        assert not set(fold.train) & set(fold.test)
        assert fold.train == tuple(sorted(fold.train))
        assert fold.test == tuple(sorted(fold.test))
        assert len(fold.test) == 8
        if fold.test[0] > 0:
            assert fold.test[0] - 1 not in fold.train
        if fold.test[-1] + 1 < 16:
            assert fold.test[-1] + 1 not in fold.train
        held_out.update(fold.test)
    # Every block is held out by the same number of combinatorial splits.
    assert held_out == Counter({index: 3 for index in range(16)})


def test_the_objective_is_the_lower_quartile_of_the_fold_scores() -> None:
    returns = [(-0.02 if index < 4 else 0.01) for index in range(16)]
    folds = tuning.cpcv_folds(16, n_folds=4, n_test_folds=2, label_horizon=1)
    scores, objective = tuning.score_folds(returns, folds)
    assert len(scores) == 6
    assert objective == pytest.approx(float(np.quantile(scores, 0.25)))


def test_thin_sessions_refuse_before_creating_a_trial(tmp_path: Path) -> None:
    result = tuning.run_study(
        _spec(),
        _evaluate(_sessions()),
        sessions=("2026-11-09",),
        holdout_days=(),
        log_path=tmp_path / "trials.parquet",
    )
    assert result.decision == "NOT_EVALUABLE"
    assert "holdout" in result.reason
    assert result.n_trials == 0
    assert result.n_trades == 0
    assert not (tmp_path / "trials.parquet").exists()


def test_the_search_never_evaluates_a_holdout_session(tmp_path: Path) -> None:
    sessions = _sessions()
    holdout = sessions[-13:]
    train = sessions[:-13]
    calls: list[tuple[str, ...]] = []

    def evaluate(params, days):
        calls.append(tuple(days))
        return _evaluate(sessions)(params, days)

    result = tuning.run_study(
        _spec(),
        evaluate,
        sessions=sessions,
        holdout_days=holdout,
        log_path=tmp_path / "trials.parquet",
    )
    assert result.decision == "NOT_ADMISSIBLE"
    assert result.holdout == "MISSING"
    assert calls and all(call == train for call in calls)
    assert not any(
        json.loads(record["config"])["arm_id"].endswith(":holdout")
        for record in tuning.TrialLog(tmp_path / "trials.parquet").records
    )


def test_a_duplicated_holdout_date_is_rejected_before_any_trial(tmp_path: Path) -> None:
    sessions = _sessions()
    holdout = sessions[-13:]
    calls: list[tuple[str, ...]] = []

    def evaluate(params, days):
        calls.append(tuple(days))
        return _evaluate(sessions)(params, days)

    result = tuning.run_study(
        _spec(),
        evaluate,
        sessions=sessions + holdout,
        holdout_days=holdout,
        log_path=tmp_path / "trials.parquet",
    )
    assert result.decision == "NOT_EVALUABLE"
    assert "unique" in result.reason or "overlap" in result.reason
    assert calls == []
    assert not (tmp_path / "trials.parquet").exists()


def test_a_supported_series_is_stamped_not_admissible_and_never_adopts(tmp_path: Path) -> None:
    sessions = _sessions()
    holdout = sessions[-13:]
    train = sessions[:-13]
    log_path = tmp_path / "trials.parquet"
    report_path = tmp_path / "proposals.json"

    def evaluate(params, days):
        assert all(day in train for day in days), "holdout evaluated"
        return _evaluate(sessions)(params, days)

    result = tuning.run_study(
        _spec(),
        evaluate,
        sessions=sessions,
        holdout_days=holdout,
        log_path=log_path,
    )
    assert result.decision == "NOT_ADMISSIBLE"
    assert "5833241132" in result.reason
    assert "refuses after the DSR, PBO and merit gates" in result.reason
    assert "PR 2 removes this stamp" in result.reason
    assert result.proposals == ()
    assert result.holdout == "MISSING"
    assert result.holdout_sharpe is None
    assert result.merit == "OK"
    assert result.dsr > 0.95
    assert result.pbo is not None and result.pbo <= 0.05
    assert result.n_sessions == len(sessions)
    assert result.n_holdout_sessions == len(holdout)
    assert result.n_trials == 100
    assert result.best_params is not None

    records = tuning.TrialLog(log_path).records
    assert len(records) == 100
    assert {record["state"] for record in records} <= {"COMPLETE", "PRUNED"}
    assert result.n_complete >= 1
    assert all(json.loads(record["config"])["tier"] == "MODELED" for record in records)
    assert not any(
        json.loads(record["config"])["arm_id"].endswith(":holdout") for record in records
    )
    assert all(len(record["fold_scores"]) == 6 for record in records)
    assert all(
        not any(isinstance(value, float) for value in json.loads(record["params"]).values())
        for record in records
    )
    assert all(record["days"] == list(sessions[:-13]) for record in records)
    assert all(record["days"] != list(holdout) for record in records)

    tuning.write_report(report_path, [result])
    payload = json.loads(report_path.read_text())
    assert payload["schema"] == "b-tuning.study/1"
    assert payload["results"][0]["adoption"] == "none"
    assert payload["results"][0]["decision"] == "NOT_ADMISSIBLE"
    assert payload["results"][0]["proposals"] == []


def test_a_negative_holdout_cannot_be_evaluated_while_the_stamp_holds(tmp_path: Path) -> None:
    sessions = _sessions()
    holdout = sessions[-13:]
    train = sessions[:-13]
    calls: list[tuple[str, ...]] = []

    def evaluate(params, days):
        calls.append(tuple(days))
        assert all(day in train for day in days), "holdout evaluated"
        return _evaluate(sessions, holdout=holdout)(params, days)

    result = tuning.run_study(
        _spec(),
        evaluate,
        sessions=sessions,
        holdout_days=holdout,
        log_path=tmp_path / "trials.parquet",
    )
    assert result.decision == "NOT_ADMISSIBLE"
    assert result.holdout == "MISSING"
    assert result.holdout_sharpe is None
    assert result.proposals == ()
    assert calls and all(call == train for call in calls)


def test_a_failed_trial_is_logged_and_the_study_continues(tmp_path: Path) -> None:
    sessions = _sessions()
    holdout = sessions[-13:]
    calls = Counter()

    def evaluate(params, days):
        calls.update(days)
        if params["native_trail_fraction"] <= 0.0025:
            raise RuntimeError("replay refused this parameter set")
        return _evaluate(sessions)(params, days)

    result = tuning.run_study(
        _spec(),
        evaluate,
        sessions=sessions,
        holdout_days=holdout,
        log_path=tmp_path / "trials.parquet",
    )
    records = tuning.TrialLog(tmp_path / "trials.parquet").records
    failed = [record for record in records if record["state"] == "FAIL"]
    assert failed
    assert "replay refused" in failed[0]["error"]
    assert result.n_failed == len(failed)
    assert result.n_trials == len(records)


def test_deflated_sharpe_is_a_probability() -> None:
    rng = np.random.default_rng(7)
    strong = rng.normal(0.002, 0.004, 60)
    weak = rng.normal(0.0, 0.004, 60)
    assert tuning.deflated_sharpe([0.01] * 20, trials=100) == 0.0
    assert 0.0 <= tuning.deflated_sharpe(list(weak), trials=100) < 0.95
    assert tuning.deflated_sharpe(list(strong), trials=100) > tuning.deflated_sharpe(
        list(weak), trials=100
    )


def test_pbo_detects_a_dominant_trial_and_needs_enough_blocks() -> None:
    matrix = np.zeros((8, 16))
    matrix[:, 3] = np.linspace(0.009, 0.011, 8)
    assert tuning.pbo_cscv(matrix, s=4) == 0.0
    assert tuning.pbo_cscv(matrix[:, :5], s=4) is None


def test_pbo_ranks_by_sharpe_not_mean() -> None:
    a = (0.009, 0.011, -0.10, 0.12)
    b = (-0.10, 0.14, 0.019, 0.021)
    matrix = np.array([a, a, b, b], dtype=float).T
    assert tuning.pbo_cscv(matrix, s=2) == 1.0


def test_deflated_sharpe_counts_the_cumulative_ledger(tmp_path: Path) -> None:
    sessions = _sessions()
    holdout = sessions[-13:]
    log_path = tmp_path / "trials.parquet"
    log = tuning.TrialLog(log_path)
    spec = _spec()
    for index in range(100):
        config = tuning._trial_config(spec, arm_id=f"prior-{index}", sha="a" * 40)
        config["params_hash"] = tuning.snapshot_hash({})
        log.append(
            spec.name,
            {},
            config,
            spec.seed,
            state="COMPLETE",
            days=("2020-01-01",),
            daily_net_returns=(0.0,),
            fold_scores=(0.0,),
            objective=0.0,
        )

    def evaluate(params, days):
        values = [0.016 if index % 2 == 0 else -0.004 for index in range(len(days))]
        return tuple(
            tuning.Observation(day, f"case-{index}", value)
            for index, (day, value) in enumerate(zip(days, values, strict=True))
        )

    result = tuning.run_study(
        spec,
        evaluate,
        sessions=sessions,
        holdout_days=holdout,
        log_path=log_path,
    )
    assert result.dsr < 0.95
    assert result.decision == "NOT_ADMISSIBLE"


def test_the_wilcoxon_pruner_can_stop_a_bad_trial(tmp_path: Path) -> None:
    sessions = _sessions()
    holdout = sessions[-13:]
    seen: list[int] = []

    def evaluate(params, days):
        if params["native_trail_fraction"] <= 0.0025:
            # No observations: every fold is flat, the worst possible run.
            return ()
        seen.append(1)
        return _evaluate(sessions)(params, days)

    result = tuning.run_study(
        _spec(n_trials=300),
        evaluate,
        sessions=sessions,
        holdout_days=holdout,
        log_path=tmp_path / "trials.parquet",
    )
    records = tuning.TrialLog(tmp_path / "trials.parquet").records
    assert any(record["state"] == "PRUNED" for record in records)
    assert result.n_pruned >= 1
    assert seen


def test_pbo_uses_average_ranks_for_tied_trials() -> None:
    a = (0.009, 0.011, -0.10, 0.12)
    b = (-0.10, 0.14, 0.019, 0.021)
    matrix = np.array([a, a, a, b], dtype=float).T
    assert tuning.pbo_cscv(matrix, s=2) == 1.0


def test_a_stamped_run_does_not_consume_the_holdout(tmp_path: Path) -> None:
    sessions = _sessions()
    holdout = sessions[-13:]
    train = sessions[:-13]
    log_path = tmp_path / "trials.parquet"
    first = tuning.run_study(
        _spec(),
        _evaluate(sessions),
        sessions=sessions,
        holdout_days=holdout,
        log_path=log_path,
    )
    assert first.decision == "NOT_ADMISSIBLE"
    assert first.holdout == "MISSING"
    records = tuning.TrialLog(log_path).records
    assert len(records) == 100
    assert all(record["days"] == list(train) for record in records)
    assert not any(
        json.loads(record["config"])["arm_id"].endswith(":holdout") for record in records
    )
    calls: list[tuple[str, ...]] = []

    def evaluate(params, days):
        calls.append(tuple(days))
        return _evaluate(sessions)(params, days)

    second = tuning.run_study(
        _spec(),
        evaluate,
        sessions=sessions,
        holdout_days=holdout,
        log_path=log_path,
    )
    assert second.decision == "NOT_ADMISSIBLE"
    assert "already consumed" not in second.reason
    records = tuning.TrialLog(log_path).records
    assert len(records) == 200
    assert all(record["days"] == list(train) for record in records)
    assert calls and all(call == train for call in calls)


def test_the_holdout_stage_is_not_a_switch() -> None:
    assert "OPEN_HOLDOUT_REVIEW" not in vars(tuning)


def test_sibling_arms_share_the_multiple_testing_correction(tmp_path: Path) -> None:
    spec = _spec()
    log = tuning.TrialLog(tmp_path / "trials.parquet")
    config = tuning._trial_config(spec, arm_id=f"{spec.name}:sibling:trial-0", sha="a" * 40)
    config["sandbox_config"]["arm"] = "sibling"
    config["sandbox_config_hash"] = tuning.snapshot_hash(config["sandbox_config"])
    config["block_set_id"] = f"{spec.name}:{spec.symbol_class}:sibling"
    config["params_hash"] = tuning.snapshot_hash({})
    log.append(
        spec.name,
        {},
        config,
        spec.seed,
        state="COMPLETE",
        days=("2020-01-01",),
        daily_net_returns=(0.0,),
        fold_scores=(0.0,),
        objective=0.0,
    )
    assert tuning._prior_attempts(log, spec) == 1
