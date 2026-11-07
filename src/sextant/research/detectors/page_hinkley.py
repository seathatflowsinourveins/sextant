"""Direct River adapter; a drift is not a bullish extreme-mover entry signal.

upstream checked: online-ml/river@0.26.1
64285b9dd6c606804753235fe992bcf25b9856ee:river/drift/page_hinkley.py,
river/stats/mean.py and river/base/drift_detector.py. No algorithm port.
Constructor defaults are NOT authorized market parameters (ADR-0018, #130).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from river.drift import PageHinkley

from .common import Observation, Parameter, SequenceClock, decimal, digest

SOURCE = (
    "https://github.com/online-ml/river/blob/"
    "64285b9dd6c606804753235fe992bcf25b9856ee/river/drift/page_hinkley.py"
)
UNITS = {
    "min_instances": "observations",
    "delta": "dimensionless input units",
    "threshold": "dimensionless input units",
    "alpha": "forgetting factor",
    "mode": "direction",
}
# Each authority is deliberately missing. Nothing adopts River's constructor defaults.
PARAMETERS = tuple(
    Parameter(name, unit, None, SOURCE, "UNAVAILABLE", date(2026, 11, 6))
    for name, unit in UNITS.items()
)


@dataclass(frozen=True)
class Drift:
    observation: Observation
    params_hash: str
    detected: bool | None
    reason: str


class PageHinkleyArm:
    def __init__(self, rows: tuple[Parameter, ...], *, observation_source: str | None):
        if observation_source is not None and not isinstance(observation_source, str):
            raise ValueError("text observation-source specification required")
        if len(rows) != len(UNITS) or {r.name for r in rows} != UNITS.keys():
            raise ValueError("each River parameter must occur exactly once")
        for row in rows:
            if row.unit != UNITS[row.name]:
                raise ValueError("River parameter unit mismatch")
            if row.value is None:
                continue
            value = row.value
            if row.name == "mode":
                if value not in {"up", "down", "both"}:
                    raise ValueError("invalid River mode")
            elif row.name == "min_instances":
                if type(value) is not int or value < 1:
                    raise ValueError("positive integer min_instances required")
            else:
                if not isinstance(value, Decimal):
                    raise ValueError("finite Decimal parameter required")
                decimal(value)
                if value < 0 or (row.name == "threshold" and value == 0):
                    raise ValueError("invalid River parameter")
                if row.name == "alpha" and value > 1:
                    raise ValueError("alpha outside [0, 1]")
                converted = float(value)
                if not math.isfinite(converted) or (value != 0 and converted == 0):
                    raise ValueError("parameter exceeds River numeric range")
        self.params_hash = digest(
            {
                "rows": [r.identity for r in sorted(rows, key=lambda r: r.name)],
                "observation_source": observation_source,
            }
        )
        self.clock = SequenceClock()
        self._detector = None
        self._seen = 0
        self._minimum = 0
        if (
            all(r.value is not None for r in rows)
            and observation_source
            and observation_source.strip()
        ):
            values = {r.name: r.value for r in rows}
            self._minimum = int(str(values["min_instances"]))
            self._detector = PageHinkley(
                min_instances=self._minimum,
                delta=float(str(values["delta"])),
                threshold=float(str(values["threshold"])),
                alpha=float(str(values["alpha"])),
                mode=str(values["mode"]),
            )

    def update(self, observation: Observation, *, as_of_ns: int) -> Drift:
        reason = self.clock.reason(observation, as_of_ns)
        if reason:
            return Drift(observation, self.params_hash, None, reason)
        if self._detector is None:
            return Drift(
                observation, self.params_hash, None, "parameter_or_observation_authority_missing"
            )
        value = float(str(observation.value))  # Only dimensionless statistical input, never money.
        if not math.isfinite(value) or (observation.value != 0 and value == 0):
            raise ValueError("observation exceeds River numeric range")
        if self._detector.drift_detected:
            self._seen = 0  # River resets on the observation AFTER a detection, not on detection.
        self._detector.update(value)
        self._seen += 1
        self.clock.last = observation
        ready = self._seen >= self._minimum
        return Drift(
            observation,
            self.params_hash,
            self._detector.drift_detected if ready else None,
            "updated" if ready else "warmup",
        )
