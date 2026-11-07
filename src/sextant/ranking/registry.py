"""ADR-0018 explicit registry, using upstream registry.py's checks and SHA identity.

Source: northstar-lanes@00203275944a22655b3e14b221cfde9a265d549a:
registry.py, contracts.py:358-398. No implicit starting values or operating registry.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

ROWS = {
    "mover_min_move": (Decimal, "fraction"),
    "mover_min_trades_accel": (Decimal, "ratio"),
    "mover_min_dvol_ratio": (Decimal, "ratio"),
    "move_1m_window_s": (int, "seconds"),
    "move_5m_window_s": (int, "seconds"),
    "trades_accel_window_s": (int, "seconds"),
    "trades_accel_baseline_min": (int, "minutes"),
    "publish_min_interval_s": (int, "seconds"),
    "generation_max_age_s": (int, "seconds"),
    "heartbeat_max_age_s": (int, "seconds"),
    "input_max_age_s": (int, "seconds"),
    "top_n": (int, "symbols"),
}


@dataclass(frozen=True, slots=True)
class RegistryRow:
    name: str
    unit: str
    value: Decimal | int
    source: str
    calibration_state: str
    last_change: date


@dataclass(frozen=True, slots=True)
class Registry:
    rows: tuple[RegistryRow, ...]
    params_hash: str = field(init=False)

    def __post_init__(self) -> None:
        names = {row.name for row in self.rows}
        if len(names) != len(self.rows) or names != ROWS.keys():
            raise ValueError("missing, duplicate or unknown registry rows")
        for row in self.rows:
            kind, unit = ROWS[row.name]
            if type(row.value) is not kind:
                raise TypeError(f"{row.name} must be {kind.__name__}, never float or bool")
            if not Decimal(row.value).is_finite() or row.value <= 0 or row.unit != unit:
                raise ValueError(f"invalid registry value/unit: {row.name}")
            if not row.source.strip() or type(row.last_change) is not date:
                raise ValueError("registry source and last change required")
            if row.calibration_state != "UNCALIBRATED":
                raise ValueError("this carry has no calibration evidence")
        ordered = tuple(sorted(self.rows, key=lambda r: r.name))
        object.__setattr__(self, "rows", ordered)
        payload = json.dumps(
            [asdict(row) for row in ordered], default=str, sort_keys=True, separators=(",", ":")
        )
        object.__setattr__(self, "params_hash", hashlib.sha256(payload.encode()).hexdigest())

    def __getattr__(self, name: str) -> Decimal | int:
        for row in self.rows:
            if row.name == name:
                return row.value
        raise AttributeError(name)

    def seconds(self, name: str) -> int:
        return int(getattr(self, name)) * 1_000_000_000
