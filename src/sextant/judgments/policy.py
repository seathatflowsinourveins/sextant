"""ADR-0017 J5's six starts, carried from northstar-trading@8256c16c31dc.

The row shape follows ADR-0018 L3; validation follows judgments/catalyst_screen.py.
Values and their authority must be supplied together. There are no fixture defaults.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, DecimalException
from pathlib import Path

NAMES = (
    "relevance_min",
    "negative_min",
    "positive_min",
    "priority_max",
    "request_budget_ms",
    "event_max_age_s",
)
UNITS = dict(
    zip(
        NAMES,
        (
            "probability",
            "probability",
            "probability",
            "priority multiplier",
            "milliseconds",
            "seconds",
        ),
        strict=True,
    )
)


def canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class Policy:
    relevance_min: Decimal
    negative_min: Decimal
    positive_min: Decimal
    priority_max: Decimal
    request_budget_ms: Decimal
    event_max_age_s: Decimal
    params_hash: str

    def __post_init__(self) -> None:
        for name in NAMES:
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{name}: finite Decimal required")
            if name in NAMES[:3] and not 0 < value <= 1:
                raise ValueError(f"{name}: probability outside (0, 1]")
            if name == "priority_max" and not 1 <= value <= 2:
                raise ValueError("priority_max: bound outside [1, 2]")
            if name in NAMES[4:] and value <= 0:
                raise ValueError(f"{name}: positive time required")
        if len(self.params_hash) != 64:
            raise ValueError("registry identity required")


def load_policy(path: Path) -> Policy:
    rows = json.loads(path.read_text())
    keys = {"name", "unit", "value", "source", "calibration_state", "last_change"}
    if not isinstance(rows, list) or len(rows) != len(NAMES):
        raise ValueError("six parameter registry rows required")
    for row in rows:
        if not isinstance(row, dict) or set(row) != keys:
            raise ValueError("complete parameter row required")
        if any(not isinstance(value, str) or not value.strip() for value in row.values()):
            raise ValueError("nonempty registry strings required")
        if row["calibration_state"] != "UNCALIBRATED":
            raise ValueError("no calibration evidence has been admitted")
        date.fromisoformat(row["last_change"])
        if row["unit"] != UNITS.get(row["name"]):
            raise ValueError("parameter unit differs from its consumer")
    if {row["name"] for row in rows} != set(NAMES):
        raise ValueError("each parameter must occur exactly once")
    try:
        values = {row["name"]: Decimal(row["value"]) for row in rows}
    except DecimalException:
        raise ValueError("registry value must be a Decimal string") from None
    return Policy(**values, params_hash=digest(sorted(rows, key=lambda row: row["name"])))
