"""Adams--MacKay run-length inference only; NO posterior-to-alarm rule.

upstream checked: arXiv:0710.3742v1, section 2, equations (3)--(4), (6)--(9),
Algorithm 1 steps 3--7. Its pluggable model boundary is preserved: the caller
supplies predictive densities from a separately sourced observation model and
H(r+1) for each old run length r (section 2.1's transition definition).
No Gaussian model, constant hazard, lambda=250, truncation or reset is adopted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .common import Observation, Parameter, SequenceClock, decimal, digest

SOURCE = "https://arxiv.org/abs/0710.3742v1"
PARAMETERS = tuple(
    Parameter(name, "specification", None, SOURCE, "UNAVAILABLE", date(2026, 11, 6))
    for name in ("hazard", "observation_model", "boundary_condition", "alarm_rule")
)
HAZARD_CONVENTION = Parameter(
    "hazard_index",
    "specification",
    "equation (4): H(r+1)",
    f"{SOURCE}; section 2.1 equation (4); Algorithm 1 prints H(r), not adopted here",
    "PUBLISHED",
    date(2026, 11, 6),
)


def normalize(weights: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    if not weights or any(decimal(w) < 0 for w in weights):
        raise ValueError("nonempty nonnegative finite weights required")
    evidence = sum(weights, Decimal(0))
    if not evidence:
        raise ValueError("zero predictive evidence; posterior unavailable")
    return tuple(w / evidence for w in weights)


def run_length_step(
    prior: tuple[Decimal, ...],
    predictive: tuple[Decimal, ...],
    hazards: tuple[Decimal, ...],
) -> tuple[Decimal, ...]:
    """Algorithm 1, steps 3--7; probabilities/densities, not market observations.

    predictive[r] = p(x_t | r_(t-1)=r, past data in that run).
    hazards[r] = H(r+1), following equation (4)'s elapsed-duration convention.
    Algorithm 1 prints H(r); that different indexing is not adopted here.
    Normalizing each step cancels the previous data-evidence scalar in (3).
    """
    if not (len(prior) == len(predictive) == len(hazards)):
        raise ValueError("one predictive density and hazard per old run length required")
    normalize(prior)  # Validate, without silently dropping any tail states.
    if any(decimal(p) < 0 for p in predictive):
        raise ValueError("predictive densities must be nonnegative")
    if any(not 0 <= decimal(h) <= 1 for h in hazards):
        raise ValueError("hazard outside [0, 1]")
    mass = tuple(p * pi for p, pi in zip(prior, predictive, strict=True))
    change = sum((m * h for m, h in zip(mass, hazards, strict=True)), Decimal(0))
    growth = tuple(m * (1 - h) for m, h in zip(mass, hazards, strict=True))
    return normalize((change, *growth))


@dataclass(frozen=True)
class Posterior:
    observation: Observation
    params_hash: str
    probabilities: tuple[Decimal, ...] | None
    reason: str
    # Deliberately no detected/alarm field. A constant hazard makes p(r_t=0) constant.


class BocpdArm:
    """Recurrence adapter, not a model implementation or a compute-admission token.

    Pass only PARAMETERS' three inference rows; alarm_rule stays unavailable.
    Caller owns model sufficient statistics (Algorithm 1 step 8) and must align
    its per-run densities with this posterior; hazard(tau) is evaluated at r+1.
    Missing inputs do not
    advance the state. No house starting boundary P(r_0=0)=1 is inferred.
    """

    def __init__(self, rows: tuple[Parameter, ...], *, initial: tuple[Decimal, ...] | None):
        inference = {"hazard", "observation_model", "boundary_condition"}
        if len(rows) != 3 or {r.name for r in rows} != inference:
            raise ValueError("hazard, observation_model and boundary_condition rows required")
        if any(r.unit != "specification" for r in rows):
            raise ValueError("BOCPD specification unit mismatch")
        for row in rows:
            if row.value is not None and (not isinstance(row.value, str) or not row.value.strip()):
                raise ValueError("explicit sourced BOCPD specification required")
        self.params_hash = digest(
            {
                "rows": [r.identity for r in sorted(rows, key=lambda r: r.name)],
                "initial": initial,
                "hazard_convention": HAZARD_CONVENTION.identity,
            }
        )
        self._posterior = None if initial is None else normalize(initial)
        self._available = all(r.value is not None for r in rows) and initial is not None
        self.clock = SequenceClock()

    def update(
        self,
        observation: Observation,
        *,
        as_of_ns: int,
        predictive: tuple[Decimal, ...] | None,
        hazard: Callable[[int], Decimal] | None,
    ) -> Posterior:
        reason = self.clock.reason(observation, as_of_ns)
        if reason:
            return Posterior(observation, self.params_hash, None, reason)
        if not self._available or self._posterior is None:
            return Posterior(
                observation, self.params_hash, None, "hazard_model_or_boundary_unavailable"
            )
        if predictive is None or hazard is None:
            return Posterior(
                observation, self.params_hash, None, "predictive_or_hazard_unavailable"
            )
        hazards = tuple(hazard(r + 1) for r in range(len(self._posterior)))
        posterior = run_length_step(self._posterior, predictive, hazards)
        self._posterior = posterior
        self.clock.last = observation
        return Posterior(observation, self.params_hash, posterior, "inference_only_no_alarm_rule")
