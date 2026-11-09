"""PR-4 proofs: Optuna TPE with CPCV and one untouched holdout, on registry parameters only.

The sources are Optuna 5.0.0's multivariate TPE and ``WilcoxonPruner``
(``optuna/optuna@v5.0.0 01ddd17ab9f36c3d2817aed9afe376e1cb047d35``), skfolio 1.12.5's
``CombinatorialPurgedCV``, and northstar-trading@8256c16c31dc
``src/northstar_trading/validation/cv.py:26-84`` (path ids, purge and embargo),
``stats.py:43-50`` (annualized Sharpe) and ``contract_gates.py:510-626`` (every CPCV path covers
every observation exactly once). Every trial is a cumulative MODELED TrialLog row; proposals
never edit a registry row.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import numpy as np
import pytest

from sextant.backtest import b_e2e_cohort
from sextant.backtest.b_e2e import EntryRule
from sextant.research import b_tuning
from sextant.validation import tuning

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests/fixtures/b-e2e-cohort.json"


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


def _spec(**changes: object) -> tuning.StudySpec:
    base: dict[str, object] = dict(
        name="b-parameters",
        symbol_class="mover",
        arm="2-slot",
        parameters=b_tuning.PARAMETERS,
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
    assert calls[:-1] and all(call == train for call in calls[:-1])
    assert calls[-1] == holdout


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
    log_path = tmp_path / "trials.parquet"
    report_path = tmp_path / "proposals.json"
    result = tuning.run_study(
        _spec(),
        _evaluate(sessions),
        sessions=sessions,
        holdout_days=holdout,
        log_path=log_path,
    )
    assert result.decision == "NOT_ADMISSIBLE"
    assert "5833241132" in result.reason
    assert result.proposals == ()
    assert result.holdout == "PASS"
    assert result.merit == "OK"
    assert result.dsr > 0.95
    assert result.pbo is not None and result.pbo <= 0.05
    assert result.n_sessions == len(sessions)
    assert result.n_holdout_sessions == len(holdout)
    assert result.n_trials == 100
    assert result.best_params is not None

    records = tuning.TrialLog(log_path).records
    assert len(records) == 101
    assert {record["state"] for record in records} <= {"COMPLETE", "PRUNED"}
    assert result.n_complete >= 1
    assert all(json.loads(record["config"])["tier"] == "MODELED" for record in records)
    assert all(len(record["fold_scores"]) == 6 for record in records[:-1])
    assert all(
        not any(isinstance(value, float) for value in json.loads(record["params"]).values())
        for record in records
    )
    assert all(record["days"] == list(sessions[:-13]) for record in records[:-1])
    assert records[-1]["days"] == list(holdout)
    assert records[-1]["fold_scores"] == []

    tuning.write_report(report_path, [result])
    payload = json.loads(report_path.read_text())
    assert payload["schema"] == "b-tuning.study/1"
    assert payload["results"][0]["adoption"] == "none"
    assert payload["results"][0]["decision"] == "NOT_ADMISSIBLE"
    assert payload["results"][0]["proposals"] == []


def test_a_negative_holdout_stops_the_proposal(tmp_path: Path) -> None:
    sessions = _sessions()
    holdout = sessions[-13:]
    result = tuning.run_study(
        _spec(),
        _evaluate(sessions, holdout=holdout),
        sessions=sessions,
        holdout_days=holdout,
        log_path=tmp_path / "trials.parquet",
    )
    assert result.decision == "NO_PROPOSAL"
    assert result.holdout == "FAIL"
    assert result.holdout_sharpe is not None and result.holdout_sharpe < 0
    assert result.proposals == ()


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
    assert result.n_trials == len(records) - 1


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
    assert result.decision == "NO_PROPOSAL"


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


def test_the_search_space_is_registry_parameters_and_excludes_k2_and_k3() -> None:
    names = {parameter.name for parameter in b_tuning.PARAMETERS}
    assert names == {
        "native_trail_fraction",
        "first_leg_window_s",
        "first_leg_trades_count",
        "first_leg_span_s",
        "first_leg_max_move",
        "max_data_age_s",
    }
    assert 5 <= len(names) <= 8
    assert "mover_min_move" not in names
    assert "premarket_gap" not in names
    trail = next(
        parameter for parameter in b_tuning.PARAMETERS if parameter.name == "native_trail_fraction"
    )
    assert Decimal(str(trail.high)) <= Decimal("0.025")
    assert all(parameter.source for parameter in b_tuning.PARAMETERS)


def test_the_adapter_threads_the_tuned_rule_into_the_cohort_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = b_e2e_cohort.load_cases(FIXTURE)
    seen: list[dict[str, object]] = []

    def fake_run_arms(
        cases, *, capacity, rotation, arm=None, rule=None, trail_fraction=None, max_age_s=None
    ):
        seen.append(
            dict(
                capacity=capacity,
                rotation=rotation,
                arm=arm,
                rule=rule,
                trail_fraction=trail_fraction,
                max_age_s=max_age_s,
            )
        )
        return tuple(
            SimpleNamespace(
                case=SimpleNamespace(case=case.case),
                state="COMPLETE",
                walked=SimpleNamespace(protected=0.01),
            )
            for case in cases
        )

    monkeypatch.setattr(b_e2e_cohort, "run_arms", fake_run_arms)
    params = {
        "native_trail_fraction": 0.0125,
        "first_leg_window_s": 90,
        "first_leg_trades_count": 4,
        "first_leg_span_s": 3,
        "first_leg_max_move": 0.02,
        "max_data_age_s": 2,
    }
    evaluate = b_tuning.replay_for(
        cases,
        arm=b_tuning.MOVER_ARMS[0],
        session_of={case.case: "2026-11-09" for case in cases},
    )
    observations = evaluate(params, ("2026-11-09",))
    assert len(observations) == len(cases)
    assert seen[0]["capacity"] == 2
    assert seen[0]["rotation"] is False
    assert seen[0]["arm"] == "2-slot"
    rule = cast(EntryRule, seen[0]["rule"])
    assert rule.window_s == 90
    assert rule.trades == 4
    assert rule.span_s == 3
    assert rule.max_move == Decimal("0.02")
    assert seen[0]["trail_fraction"] == Decimal("0.0125")
    assert seen[0]["max_age_s"] == 2


def test_the_cohort_trail_takes_a_fraction_and_keeps_the_default() -> None:
    case = b_e2e_cohort.load_cases(FIXTURE)[0]
    entry = b_e2e_cohort.Entry(
        ts_ns=case.trades[2].ts_ns, price=case.trades[2].price, quote_ts_ns=case.trades[2].ts_ns
    )
    default = b_e2e_cohort.trail(case, entry)
    tight = b_e2e_cohort.trail(case, entry, trail_fraction=Decimal("0.01"))
    assert default.level == default.high * (1 - Decimal("0.025"))
    assert tight.level == tight.high * (1 - Decimal("0.01"))


def test_proposals_never_write_a_registry(tmp_path: Path) -> None:
    paths = (
        REPO / "lanes/sim/entry-parameters.json",
        REPO / "src/sextant/paper/b_protector.py",
    )
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    result = tuning.StudyResult(
        spec=_spec(),
        decision="PROPOSED",
        reason="test",
        merit="OK",
        holdout="PASS",
        holdout_sharpe=1.0,
        n_sessions=60,
        n_train_sessions=47,
        n_holdout_sessions=13,
        n_trials=100,
        n_complete=100,
        n_failed=0,
        n_pruned=0,
        n_trades=47,
        best_params=(("p0", "3"),),
        best_objective=1.0,
        dsr=0.99,
        pbo=0.0,
        proposals=(
            tuning.Proposal(
                registry="lanes/sim/entry-parameters.json",
                row="first_leg_window_s",
                current="120",
                proposed="90",
                source="test",
                evidence="test",
            ),
        ),
    )
    tuning.write_report(tmp_path / "proposals.json", [result])
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert before == after


def test_the_real_cohort_is_not_evaluable_and_writes_no_trial_row(tmp_path: Path) -> None:
    cases = b_e2e_cohort.load_cases(FIXTURE)
    results = b_tuning.run_mover_study(
        cases,
        session_of={case.case: "2026-11-09" for case in cases},
        sessions=("2026-11-09",),
        log_path=tmp_path / "trials.parquet",
        report_path=tmp_path / "proposals.json",
        n_trials=100,
    )
    assert len(results) == len(b_tuning.MOVER_ARMS)
    assert all(result.decision == "NOT_EVALUABLE" for result in results)
    assert all(result.n_trials == 0 for result in results)
    assert not (tmp_path / "trials.parquet").exists()
    payload = json.loads((tmp_path / "proposals.json").read_text())
    assert payload["results"] and all(row["proposals"] == [] for row in payload["results"])


def test_pbo_uses_average_ranks_for_tied_trials() -> None:
    a = (0.009, 0.011, -0.10, 0.12)
    b = (-0.10, 0.14, 0.019, 0.021)
    matrix = np.array([a, a, a, b], dtype=float).T
    assert tuning.pbo_cscv(matrix, s=2) == 1.0


def test_a_consumed_holdout_is_not_reused(tmp_path: Path) -> None:
    sessions = _sessions()
    holdout = sessions[-13:]
    log_path = tmp_path / "trials.parquet"
    first = tuning.run_study(
        _spec(),
        _evaluate(sessions),
        sessions=sessions,
        holdout_days=holdout,
        log_path=log_path,
    )
    assert first.decision == "NOT_ADMISSIBLE"
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
    assert second.decision == "NOT_EVALUABLE"
    assert "holdout" in second.reason
    assert calls == []


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
