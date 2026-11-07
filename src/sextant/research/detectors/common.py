"""Source-only value/clock seams, not the coordinator's compute-admission gate.

upstream checked: ADR-0018 L3 and sextant.ranking.registry.RegistryRow;
NautilusTrader@55c0e82053142bce3a5cba4de4221d3929c2d3bc native InstrumentId.
Historical close/receipt clocks follow sextant.data.catalog, never inferred here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from nautilus_trader.model import InstrumentId


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def decimal(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("finite Decimal required")
    return value


@dataclass(frozen=True)
class Parameter:
    name: str
    unit: str
    value: Decimal | int | str | None
    source: str
    calibration_state: str
    last_change: date

    def __post_init__(self) -> None:
        if not all(isinstance(x, str) and x.strip() for x in (self.name, self.unit, self.source)):
            raise ValueError("parameter name, unit and source required")
        if type(self.last_change) is not date:
            raise ValueError("parameter change date required")
        if self.calibration_state not in {"UNAVAILABLE", "UNCALIBRATED", "PUBLISHED"}:
            raise ValueError("no calibration evidence admitted")
        if (self.value is None) != (self.calibration_state == "UNAVAILABLE"):
            raise ValueError("missing authority stays UNAVAILABLE")
        if self.value is not None:
            if isinstance(self.value, Decimal):
                decimal(self.value)
            elif type(self.value) not in {int, str}:
                raise ValueError("parameter must be Decimal, int or text, never float/bool")
            elif isinstance(self.value, str) and not self.value.strip():
                raise ValueError("empty parameter specification")

    @property
    def identity(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Observation:
    """One scalar per completion timestamp, not raw ticks or normalized prices."""

    instrument_id: InstrumentId
    ts_event: int
    ts_init: int
    value: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise ValueError("native InstrumentId required")
        if any(type(t) is not int or t < 0 for t in (self.ts_event, self.ts_init)):
            raise ValueError("nonnegative nanosecond clocks required")
        if self.ts_init < self.ts_event:
            raise ValueError("availability precedes event/completion")
        if self.value is not None:
            decimal(self.value)


class SequenceClock:
    """One series per adapter; no reorder, revision overwrite or future observation."""

    def __init__(self) -> None:
        self.last: Observation | None = None

    def reason(self, observation: Observation, as_of_ns: int) -> str | None:
        if type(as_of_ns) is not int or as_of_ns < 0:
            raise ValueError("nonnegative as-of nanoseconds required")
        if observation.ts_init > as_of_ns:
            return "not_yet_available"
        if self.last is not None:
            if observation.instrument_id != self.last.instrument_id:
                raise ValueError("one instrument per adapter")
            if (
                observation.ts_event <= self.last.ts_event
                or observation.ts_init < self.last.ts_init
            ):
                raise ValueError("duplicate, revised or out-of-order observation")
        return "missing_observation" if observation.value is None else None
