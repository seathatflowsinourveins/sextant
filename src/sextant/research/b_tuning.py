"""B's PR-4 adapter: tune the first-leg arms and the trail on PR-3's MODELED rows.

K2's thresholds are not tuned (paired arms only); K3's premarket-gap arm waits for its freeze.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from sextant.backtest.b_e2e_cohort import CaseData
from sextant.validation import tuning

STUDY = "b-parameters"
SEED = 20261109


@dataclass(frozen=True)
class Arm:
    name: str
    capacity: int
    rotation: bool


# ADR-0024's 2/5 and 8/20 slots, then ADR-0006's flat-slot rotation; the same three arms PR-3
# replayed. The first pair is the reviewed default, so it leads.
MOVER_ARMS = (
    Arm("2-slot", 2, False),
    Arm("8-slot", 8, False),
    Arm("2-slot-rotation", 2, True),
)

_N = "northstar-trading@8256c16c31dc "
_E = "entry-parameters.json:"
_TRAIL = "src/sextant/exits/owner_b.py:17-21 (ADR-0025 B scope, 2.5% cap)"
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


def replay_for(
    cases: Sequence[CaseData],
    *,
    arm: Arm,
    session_of: Mapping[str, str],
):
    """A fold evaluator: one arm's replay of the cases in the requested sessions."""

    def evaluate(params: Mapping[str, Any], days: Sequence[str]) -> tuple[tuning.Observation, ...]:
        from sextant.backtest.b_e2e_cohort import EntryRule, run_arms

        requested = set(days)
        selected = tuple(case for case in cases if session_of[case.case] in requested)
        if not selected:
            return ()
        rule = EntryRule(
            window_s=int(params["first_leg_window_s"]),
            trades=int(params["first_leg_trades_count"]),
            span_s=int(params["first_leg_span_s"]),
            max_move=Decimal(str(params["first_leg_max_move"])),
        )
        rows = run_arms(
            selected,
            capacity=arm.capacity,
            rotation=arm.rotation,
            arm=arm.name,
            rule=rule,
            trail_fraction=Decimal(str(params["native_trail_fraction"])),
            max_age_s=int(params["max_data_age_s"]),
        )
        return tuple(
            tuning.Observation(
                session_of[row.case.case], row.case.case, float(row.walked.protected)
            )
            for row in rows
            if row.state == "COMPLETE"
            and row.walked is not None
            and row.walked.protected is not None
        )

    return evaluate


def run_mover_study(
    cases: Sequence[CaseData],
    *,
    session_of: Mapping[str, str],
    sessions: Sequence[str],
    log_path: str | Path,
    report_path: str | Path,
    n_trials: int = tuning.MIN_TRIALS,
) -> tuple[tuning.StudyResult, ...]:
    """Run one study per mover arm; the real rows have no 12-24 month holdout yet."""
    results = []
    for arm in MOVER_ARMS:
        spec = tuning.StudySpec(
            name=STUDY,
            symbol_class="mover",
            arm=arm.name,
            parameters=PARAMETERS,
            n_trials=n_trials,
            n_folds=4,
            n_test_folds=2,
            label_horizon=1,
            seed=SEED,
        )
        results.append(
            tuning.run_study(
                spec,
                replay_for(cases, arm=arm, session_of=session_of),
                sessions=sessions,
                holdout_days=(),
                log_path=log_path,
            )
        )
    tuning.write_report(report_path, results)
    return tuple(results)
