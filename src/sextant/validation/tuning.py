"""Optuna's multivariate TPE over CPCV folds and one untouched holdout.

Every study is a cumulative MODELED TrialLog arm. The objective is the lower-quartile Sharpe of
the combinatorial purged folds; the search never reads a holdout session; a proposal is admissible
only when the holdout confirms the sign and the deflated Sharpe and PBO gates pass. The registry
is read-only; ``write_report`` writes proposals, never an adoption.

Sources: Optuna 5.0.0 commit 01ddd17ab9f36c3d2817aed9afe376e1cb047d35 (multivariate
``TPESampler``, experimental ``WilcoxonPruner``); skfolio 1.12.5
``model_selection/_combinatorial.py:71`` (``CombinatorialPurgedCV``);
northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa
``validation/cv.py:26-84``, ``stats.py:43-50`` and ``contract_gates.py:510-626``; ADR-0015
(5-8 parameters, 100-300 trials, DSR > 0.95, PBO <= 0.05, one 12-24 month holdout).
"""

from __future__ import annotations

import json
import math
import subprocess
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from itertools import combinations
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import optuna

from sextant.validation.trials import TrialLog, snapshot_hash

REPO = Path(__file__).resolve().parents[3]
SCHEMA = "b-tuning.study/1"
MIN_PARAMETERS, MAX_PARAMETERS = 5, 8
MIN_TRIALS, MAX_TRIALS = 100, 300
MIN_HOLDOUT_DAYS, MAX_HOLDOUT_DAYS = 365, 730
FOLD_QUANTILE = 0.25
TRADING_DAYS = 252
WILCOXON_P_THRESHOLD = 0.1
TRAIL_CAP = "0.025"


@dataclass(frozen=True)
class FloatParameter:
    name: str
    low: float
    high: float
    step: float | None = None
    log: bool = False
    source: str = ""


@dataclass(frozen=True)
class IntParameter:
    name: str
    low: int
    high: int
    step: int = 1
    source: str = ""


Parameter = FloatParameter | IntParameter


@dataclass(frozen=True)
class StudySpec:
    name: str
    symbol_class: str
    arm: str
    parameters: tuple[Parameter, ...]
    n_trials: int = MIN_TRIALS
    n_folds: int = 4
    n_test_folds: int = 2
    label_horizon: int = 1
    seed: int = 0


@dataclass(frozen=True)
class Observation:
    day: str
    key: str
    net_return: float


@dataclass(frozen=True)
class CpcvFold:
    train: tuple[int, ...]
    test: tuple[int, ...]


@dataclass(frozen=True)
class Proposal:
    registry: str
    row: str
    current: str
    proposed: str
    source: str
    evidence: str


@dataclass(frozen=True)
class StudyResult:
    spec: StudySpec
    decision: str
    reason: str
    merit: str = "INSUFFICIENT_N"
    holdout: str = "MISSING"
    holdout_sharpe: float | None = None
    n_sessions: int = 0
    n_train_sessions: int = 0
    n_holdout_sessions: int = 0
    n_trials: int = 0
    n_complete: int = 0
    n_failed: int = 0
    n_pruned: int = 0
    n_trades: int = 0
    best_params: tuple[tuple[str, str], ...] | None = None
    best_objective: float | None = None
    dsr: float = 0.0
    pbo: float | None = None
    proposals: tuple[Proposal, ...] = ()

    def payload(self) -> dict[str, Any]:
        body = asdict(self) | {"study": self.spec.name, "symbol_class": self.spec.symbol_class}
        body.pop("spec")
        return body | {
            "arm": self.spec.arm,
            "adoption": "none",
            "best_params": dict(self.best_params) if self.best_params else None,
            "proposals": [asdict(proposal) | {"adoption": "none"} for proposal in self.proposals],
        }


@dataclass(frozen=True)
class _Eligibility:
    train: tuple[str, ...]
    holdout: tuple[str, ...]
    folds: tuple[CpcvFold, ...]
    reason: str = ""


def sharpe(values: Sequence[float]) -> float:
    """Annualized Sharpe with upstream's zero-range guard (northstar stats.py:43-50)."""
    array = np.asarray(values, dtype=float)
    if array.size < 2 or float(np.ptp(array)) == 0.0:
        return 0.0
    return float(array.mean() / array.std(ddof=0) * math.sqrt(TRADING_DAYS))


def session_series(
    observations: Sequence[Observation], sessions: Sequence[str]
) -> tuple[list[str], list[float]]:
    """Equal-weight the cases within each session; a session with no case is a flat 0."""
    ordered = tuple(sessions)
    if not ordered or ordered != tuple(sorted(ordered)) or len(set(ordered)) != len(ordered):
        raise ValueError("sessions must be unique and chronological")
    buckets: dict[str, list[float]] = defaultdict(list)
    allowed = set(ordered)
    for observation in observations:
        if observation.day not in allowed:
            raise ValueError(f"observation outside the study's sessions: {observation.day}")
        if not math.isfinite(float(observation.net_return)):
            raise ValueError(f"non-finite return on {observation.day}: {observation.net_return}")
        buckets[observation.day].append(float(observation.net_return))
    return list(ordered), [float(np.mean(buckets[day])) if buckets[day] else 0.0 for day in ordered]


def cpcv_folds(
    n_samples: int,
    *,
    n_folds: int = 4,
    n_test_folds: int = 2,
    label_horizon: int = 1,
) -> tuple[CpcvFold, ...]:
    """Combinatorial splits; each fold holds out both of its purged test blocks.

    Upstream's ``cpcv_gate`` refits the estimator and scores a path's recombined out-of-sample
    blocks. A tuning trial is one fixed parameter set, so every path Sharpe would be the same
    full-series number; scoring each split's held-out blocks keeps the combinatorial design and
    gives the lower quartile real variation.
    """
    if n_samples < n_folds:
        raise ValueError(f"{n_samples} samples cannot fill {n_folds} folds")
    from skfolio.model_selection import CombinatorialPurgedCV

    cv = CombinatorialPurgedCV(
        n_folds=n_folds,
        n_test_folds=n_test_folds,
        purged_size=label_horizon,
        embargo_size=label_horizon,
    )
    return tuple(
        CpcvFold(
            train=tuple(sorted(int(index) for index in train)),
            test=tuple(sorted(int(index) for block in tests for index in block)),
        )
        for train, tests in cv.split(np.empty((n_samples, 1)))
    )


def score_folds(
    returns: Sequence[float], folds: Sequence[CpcvFold]
) -> tuple[tuple[float, ...], float]:
    """The fold Sharpes and their lower quartile, the study's objective."""
    scores = tuple(sharpe([returns[index] for index in fold.test]) for fold in folds)
    return scores, float(np.quantile(scores, FOLD_QUANTILE))


def deflated_sharpe(returns: Sequence[float], trials: int) -> float:
    """Bailey-Lopez de Prado's DSR under the variance-of-the-Sharpe-estimator null."""
    array = np.asarray(returns, dtype=float)
    if array.size < 2:
        return 0.0
    deviation = float(array.std(ddof=0))
    if np.ptp(array) == 0 or deviation == 0.0:
        return 0.0
    ratio = float(array.mean() / deviation)
    count = max(int(trials), 1)
    normal = NormalDist()
    gamma = 0.5772156649015329
    expected = 0.0
    if count > 1:
        expected = math.sqrt(1.0 / (array.size - 1)) * (
            (1.0 - gamma) * normal.inv_cdf(1.0 - 1.0 / count)
            + gamma * normal.inv_cdf(1.0 - 1.0 / (count * math.e))
        )
    z = (array - array.mean()) / deviation
    skew, kurtosis = float((z**3).mean()), float((z**4).mean())
    denominator = math.sqrt(max(1e-12, 1.0 - skew * ratio + (kurtosis - 1.0) / 4.0 * ratio * ratio))
    return float(normal.cdf((ratio - expected) * math.sqrt(array.size - 1) / denominator))


def _block_sharpe(block: np.ndarray) -> np.ndarray:
    """Per-trial Sharpe on one block; the constant series is flat, not undefined."""
    means = block.mean(axis=0)
    deviations = block.std(axis=0, ddof=0)
    scores = np.zeros(means.shape, dtype=float)
    varying = deviations > 0
    scores[varying] = means[varying] / deviations[varying]
    return scores


def pbo_cscv(matrix: np.ndarray, *, s: int = 16) -> float | None:
    """Probability of backtest overfitting, by CSCV over ``s`` contiguous blocks.

    The in-sample winner and the out-of-sample rank use Sharpe, the statistic the
    search maximizes; ranking means would let the gate miss overfitting (Bailey et al.,
    "The Probability of Backtest Overfitting", CSCV).
    """
    data = np.asarray(matrix, dtype=float)
    if data.ndim != 2:
        raise ValueError("the PBO matrix is observations by trials")
    observations, trials = data.shape
    if trials < 2 * s:
        return None
    usable = (observations // s) * s
    if usable == 0:
        return None
    data = data[-usable:]
    blocks = np.array_split(np.arange(usable), s)
    below = total = 0
    for chosen in combinations(range(s), s // 2):
        is_index = np.concatenate([blocks[index] for index in chosen])
        oos_index = np.concatenate([blocks[index] for index in range(s) if index not in chosen])
        in_sample = _block_sharpe(data[is_index])
        out_sample = _block_sharpe(data[oos_index])
        best = int(np.argmax(in_sample))
        rank = 1 + int((out_sample > out_sample[best]).sum())
        total += 1
        if rank > trials / 2:
            below += 1
    return below / total


def _implementation_sha() -> str:
    output = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True
    )
    return output.stdout.strip()


def _logged(params: Mapping[str, Any]) -> dict[str, Any]:
    """TrialLog takes strings or integers, never a float."""
    return {
        name: int(value) if isinstance(value, int) else str(value) for name, value in params.items()
    }


def _suggest(trial: optuna.Trial, parameter: Parameter) -> int | float:
    if isinstance(parameter, IntParameter):
        return trial.suggest_int(parameter.name, parameter.low, parameter.high, step=parameter.step)
    return trial.suggest_float(
        parameter.name, parameter.low, parameter.high, step=parameter.step, log=parameter.log
    )


def _validate(spec: StudySpec) -> None:
    count = len(spec.parameters)
    if not MIN_PARAMETERS <= count <= MAX_PARAMETERS:
        raise ValueError(
            f"ADR-0015 explores {MIN_PARAMETERS}-{MAX_PARAMETERS} parameters, not {count}"
        )
    if not MIN_TRIALS <= spec.n_trials <= MAX_TRIALS:
        raise ValueError(f"ADR-0015 runs {MIN_TRIALS}-{MAX_TRIALS} trials, not {spec.n_trials}")
    if spec.n_folds < 3 or not 2 <= spec.n_test_folds < spec.n_folds:
        raise ValueError("CPCV needs at least 3 folds and 2..n_folds-1 test folds")
    if spec.label_horizon < 1:
        raise ValueError("the purge and embargo need at least one session")
    names = [parameter.name for parameter in spec.parameters]
    if len(set(names)) != len(names):
        raise ValueError("a parameter name is repeated")


def _eligibility(
    spec: StudySpec, sessions: Sequence[str], holdout_days: Sequence[str]
) -> _Eligibility:
    ordered, holdout = tuple(sessions), tuple(holdout_days)
    if len(set(ordered)) != len(ordered) or ordered != tuple(sorted(ordered)):
        return _Eligibility((), holdout, (), "sessions must be unique and chronological")
    if not holdout:
        return _Eligibility(
            (), (), (), "holdout missing: ADR-0015 requires one untouched 12-24 month holdout"
        )
    if ordered[-len(holdout) :] != holdout or len(holdout) >= len(ordered):
        return _Eligibility(
            (), holdout, (), "the holdout is not the final untuned block of the sessions"
        )
    span = (date.fromisoformat(holdout[-1]) - date.fromisoformat(holdout[0])).days
    if not MIN_HOLDOUT_DAYS <= span <= MAX_HOLDOUT_DAYS:
        return _Eligibility(
            (), holdout, (), f"holdout spans {span} days, outside the 12-24 month rule"
        )
    train = ordered[: -len(holdout)]
    if set(train) & set(holdout):
        return _Eligibility((), holdout, (), "training and holdout sessions overlap")
    if len(train) < spec.n_folds:
        return _Eligibility(
            train,
            holdout,
            (),
            f"{len(train)} training sessions cannot fill {spec.n_folds} CPCV folds",
        )
    try:
        folds = cpcv_folds(
            len(train),
            n_folds=spec.n_folds,
            n_test_folds=spec.n_test_folds,
            label_horizon=spec.label_horizon,
        )
    except ValueError as error:
        return _Eligibility(train, holdout, (), str(error))
    return _Eligibility(train, holdout, folds)


def _trial_config(spec: StudySpec, *, arm_id: str, sha: str) -> dict[str, Any]:
    sandbox = {
        "study": spec.name,
        "symbol_class": spec.symbol_class,
        "arm": spec.arm,
        "n_folds": spec.n_folds,
        "n_test_folds": spec.n_test_folds,
        "label_horizon": spec.label_horizon,
        "seed": spec.seed,
        "n_trials": spec.n_trials,
    }
    return {
        "arm_id": arm_id,
        "arm_run_id": uuid.uuid4().hex,
        "implementation_sha": sha,
        "factor_mask": [],
        "sandbox_config": sandbox,
        "sandbox_config_hash": snapshot_hash(sandbox),
        "evidence_weights": {},
        "evidence_weights_hash": snapshot_hash({}),
        "params_hash": None,
        "tier": "MODELED",
        "block_set_id": f"{spec.name}:{spec.symbol_class}:{spec.arm}",
        "funding_divergent_session_count": 0,
        "funding_unverified_session_count": 0,
        "condition_returns": {},
    }


_N = "northstar-trading@8256c16c31dc"
_E = "lanes/sim/entry-parameters.json"
_PROPOSAL_ROWS = {
    "native_trail_fraction": (
        "src/sextant/exits/owner_b.py",
        "native_trail_fraction",
        "ADR-0025 B scope: the 2.5% cap",
    ),
    "first_leg_window_s": (_E, "first_leg_window_s", f"{_N} profiles.yaml:114"),
    "first_leg_trades_count": (_E, "first_leg_trades_count", f"{_N} profiles.yaml:126"),
    "first_leg_span_s": (_E, "first_leg_span_s", f"{_N} profiles.yaml:138"),
    "first_leg_max_move": (_E, "first_leg_max_move", f"{_N} profiles.yaml:162 and ADR-0024"),
    "max_data_age_s": (_E, "max_data_age_s", f"{_N} profiles.yaml:174 and base.py:144"),
}


def _current_value(registry: str, row: str) -> str:
    path = REPO / registry
    if path.suffix == ".json":
        for entry in json.loads(path.read_text()):
            if entry.get("name") == row:
                return str(entry.get("value"))
        raise ValueError(f"{row} is not a row of {registry}")
    if row == "native_trail_fraction":
        return TRAIL_CAP
    raise ValueError(f"no current value for {row} in {registry}")


def _proposals(
    spec: StudySpec, best: Mapping[str, Any], *, objective: float, holdout_sharpe: float
) -> tuple[Proposal, ...]:
    evidence = (
        f"CPCV lower-quartile fold Sharpe {objective:.4f} over "
        f"{spec.n_folds}/{spec.n_test_folds} folds; holdout Sharpe {holdout_sharpe:.4f}"
    )
    proposals = []
    for name, value in sorted(_logged(best).items()):
        if name not in _PROPOSAL_ROWS:
            continue
        registry, row, source = _PROPOSAL_ROWS[name]
        current = _current_value(registry, row)
        if current != value:
            proposals.append(
                Proposal(
                    registry=registry,
                    row=row,
                    current=current,
                    proposed=str(value),
                    source=source,
                    evidence=evidence,
                )
            )
    return tuple(proposals)


def _prior_attempts(log: TrialLog, spec: StudySpec) -> int:
    """MODELED attempts already in the cumulative ledger for this study and arm."""
    block = f"{spec.name}:{spec.symbol_class}:{spec.arm}"
    count = 0
    for record in log.records:
        try:
            config = json.loads(record["config"])
        except (TypeError, ValueError):
            continue
        if config.get("tier") != "MODELED" or config.get("block_set_id") != block:
            continue
        if str(config.get("arm_id", "")).endswith(":holdout"):
            continue
        count += 1
    return count


def run_study(
    spec: StudySpec,
    evaluate: Callable[[Mapping[str, Any], Sequence[str]], Sequence[Observation]],
    *,
    sessions: Sequence[str],
    holdout_days: Sequence[str],
    log_path: str | Path,
) -> StudyResult:
    """Run one study: TPE over the folds, then one holdout evaluation of the best trial."""
    _validate(spec)
    eligibility = _eligibility(spec, sessions, holdout_days)
    if eligibility.reason:
        return StudyResult(
            spec=spec,
            decision="NOT_EVALUABLE",
            reason=eligibility.reason,
            n_sessions=len(sessions),
            n_train_sessions=len(eligibility.train),
            n_holdout_sessions=len(eligibility.holdout),
        )
    train, holdout, folds = eligibility.train, eligibility.holdout, eligibility.folds
    log = TrialLog(Path(log_path))
    attempts = _prior_attempts(log, spec)
    sha = _implementation_sha()
    series: dict[int, list[float]] = {}

    def objective(trial: optuna.Trial) -> float:
        suggested = {parameter.name: _suggest(trial, parameter) for parameter in spec.parameters}
        logged = _logged(suggested)
        base = _trial_config(spec, arm_id=f"{spec.name}:{spec.arm}:trial-{trial.number}", sha=sha)
        base["params_hash"] = snapshot_hash(logged)
        try:
            observations = evaluate(suggested, train)
            days, returns = session_series(observations, train)
            scores, value = score_folds(returns, folds)
        except Exception as error:
            log.append(
                spec.name,
                logged,
                base,
                spec.seed,
                state="FAIL",
                error=f"{type(error).__name__}: {error}",
            )
            raise optuna.TrialPruned() from error
        series[trial.number] = returns
        for step, score in enumerate(scores):
            trial.report(score, step)
        pruned = bool(trial.should_prune())
        log.append(
            spec.name,
            logged,
            base,
            spec.seed,
            state="PRUNED" if pruned else "COMPLETE",
            days=days,
            daily_net_returns=returns,
            fold_scores=scores,
            objective=value,
            error="WilcoxonPruner: worse fold curve than the best trial" if pruned else "",
        )
        if pruned:
            raise optuna.TrialPruned()
        return value

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(multivariate=True, seed=spec.seed),
        pruner=optuna.pruners.WilcoxonPruner(p_threshold=WILCOXON_P_THRESHOLD),
    )
    study.optimize(objective, n_trials=spec.n_trials)
    records = log.records
    complete = sum(1 for record in records if record["state"] == "COMPLETE")
    failed = sum(1 for record in records if record["state"] == "FAIL")
    pruned = sum(1 for record in records if record["state"] == "PRUNED")
    try:
        best = study.best_trial
    except ValueError:
        best = None
    if best is None:
        return StudyResult(
            spec=spec,
            decision="NOT_EVALUABLE",
            reason="no trial completed a fold curve",
            n_sessions=len(sessions),
            n_train_sessions=len(train),
            n_holdout_sessions=len(holdout),
            n_trials=spec.n_trials,
            n_complete=complete,
            n_failed=failed,
            n_pruned=pruned,
        )
    best_suggested = dict(best.params)
    best_logged = _logged(best_suggested)
    best_returns = series[best.number]
    best_objective = float(best.value) if best.value is not None else None
    dsr = deflated_sharpe(best_returns, attempts + spec.n_trials)
    matrix = np.asarray(list(series.values()), dtype=float).T
    pbo = pbo_cscv(matrix, s=16) if matrix.shape[1] >= 32 else None

    holdout_state, holdout_error, holdout_label = "COMPLETE", "", "MISSING"
    try:
        holdout_observations = evaluate(best_suggested, holdout)
        holdout_days_used, holdout_returns = session_series(holdout_observations, holdout)
        holdout_sharpe: float | None = sharpe(holdout_returns)
        holdout_label = "PASS" if holdout_sharpe > 0 else "FAIL"
    except Exception as error:
        holdout_days_used, holdout_returns = [], []
        holdout_sharpe, holdout_state = None, "FAIL"
        holdout_error = f"{type(error).__name__}: {error}"

    holdout_config = _trial_config(spec, arm_id=f"{spec.name}:{spec.arm}:holdout", sha=sha)
    holdout_config["params_hash"] = snapshot_hash(best_logged)
    log.append(
        spec.name,
        best_logged,
        holdout_config,
        spec.seed,
        state=holdout_state,
        days=holdout_days_used,
        daily_net_returns=holdout_returns,
        objective=holdout_sharpe,
        error=holdout_error,
    )

    n_trades = len(best_returns)
    merit = "OK" if n_trades >= 30 else "INSUFFICIENT_N"
    admissible = (
        best_objective is not None
        and best_objective > 0
        and holdout_label == "PASS"
        and merit == "OK"
        and dsr > 0.95
        and pbo is not None
        and pbo <= 0.05
    )
    if admissible:
        decision = "PROPOSED"
        assert best_objective is not None
        proposals = _proposals(
            spec, best_suggested, objective=best_objective, holdout_sharpe=holdout_sharpe or 0.0
        )
        reason = "CPCV, holdout, DSR and PBO gates pass; the proposal is for review, never adoption"
    else:
        decision, proposals = "NO_PROPOSAL", ()
        reason = (
            f"best objective {best_objective}, holdout {holdout_label}, "
            f"DSR {dsr:.3f}, PBO {pbo}, merit {merit}"
        )
    return StudyResult(
        spec=spec,
        decision=decision,
        reason=reason,
        merit=merit,
        holdout=holdout_label,
        holdout_sharpe=holdout_sharpe,
        n_sessions=len(sessions),
        n_train_sessions=len(train),
        n_holdout_sessions=len(holdout),
        n_trials=spec.n_trials,
        n_complete=complete,
        n_failed=failed,
        n_pruned=pruned,
        n_trades=n_trades,
        best_params=tuple(sorted(best_logged.items())),
        best_objective=best_objective,
        dsr=dsr,
        pbo=pbo,
        proposals=proposals,
    )


def write_report(path: str | Path, results: Sequence[StudyResult]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": SCHEMA, "results": [result.payload() for result in results]}
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
