"""Explicit registry consumption, adapted from northstar-lanes contracts.Params.

Source pins and the unavailable deployment starts are in docs/manifest.md.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any

NAMES = frozenset(
    "first_leg_window_s first_leg_trades_count first_leg_span_s first_leg_max_move "
    "entry_max_vwap_extension_atr entry_chase_bps entry_ttl_s reclaim_lookback_s "
    "reclaim_trades_count reclaim_trades_span_s reclaim_hold_s reclaim_max_above_buffers "
    "atr_period atr_bar_minutes max_data_age_s bp_target_fraction stop_ref_fraction "
    "portfolio_slots stopout_size_decay stopout_size_floor confidence_size_floor "
    "chase_cap_fraction flow_share_cap flow_share_window_s covered_flow_window_s "
    "covered_flow_baseline_min covered_flow_ratio".split()
)
COUNTS = frozenset(
    {
        "first_leg_trades_count",
        "reclaim_trades_count",
        "atr_period",
        "atr_bar_minutes",
        "portfolio_slots",
    }
)
FRACTIONS = frozenset(
    "first_leg_max_move reclaim_max_above_buffers bp_target_fraction stop_ref_fraction "
    "stopout_size_decay stopout_size_floor confidence_size_floor "
    "chase_cap_fraction flow_share_cap".split()
)
ZERO_OK = frozenset(
    {"reclaim_max_above_buffers", "confidence_size_floor", "chase_cap_fraction", "entry_chase_bps"}
)
SEC = 1_000_000_000


def number(value: Any, name: str, *, zero: bool = False) -> Decimal:
    if type(value) not in (str, int, Decimal):
        raise ValueError(f"{name}: finite Decimal required")
    result = Decimal(value)
    if not result.is_finite() or result < 0 or (not zero and result == 0):
        raise ValueError(f"{name}: finite {'nonnegative' if zero else 'positive'} Decimal required")
    return result


@dataclass(frozen=True)
class EntryParameters:
    values: Mapping[str, Any]
    params_hash: str
    fixture: bool

    @classmethod
    def from_rows(cls, rows: Sequence[Mapping[str, Any]], *, fixture: bool = False):
        names = [row["name"] for row in rows]
        if set(names) != NAMES or len(names) != len(NAMES):
            raise ValueError("missing, duplicate or unknown entry registry row")
        values: dict[str, Any] = {}
        for row in rows:
            name = row["name"]
            for metadata in ("source", "unit", "last_change"):
                if not row.get(metadata):
                    raise ValueError(f"{name}: missing {metadata}")
            if row.get("value") is None or row.get("scope") == "UNAVAILABLE":
                raise ValueError(f"{name}: unavailable")
            if row.get("scope") == "FIXTURE_ONLY":
                if not fixture:
                    raise ValueError(f"{name}: fixture is not deployment authority")
            elif row.get("scope") != "REVIEWED":
                raise ValueError(f"{name}: unreviewed authority")
            if row.get("calibration") not in {"UNCALIBRATED", "CALIBRATED"}:
                raise ValueError(f"{name}: missing calibration state")
            value = row["value"]
            if name in COUNTS:
                if type(value) is not int or value <= 0:
                    raise ValueError(f"{name}: positive integer required")
            else:
                value = number(value, name, zero=name in ZERO_OK)
                if name in FRACTIONS and value > 1:
                    raise ValueError(f"{name}: fraction exceeds one")
                if name in {"first_leg_max_move", "chase_cap_fraction"} and value >= 1:
                    raise ValueError(f"{name}: fraction must be less than one")
                if name.endswith("_s") and value * SEC != (value * SEC).to_integral_value():
                    raise ValueError(f"{name}: not representable in nanoseconds")
            values[name] = value
        if values["entry_ttl_s"] > values["first_leg_window_s"]:
            raise ValueError("entry_ttl_s exceeds first_leg_window_s")
        payload = json.dumps(
            sorted((dict(row) for row in rows), key=lambda r: r["name"]),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return cls(MappingProxyType(values), hashlib.sha256(payload.encode()).hexdigest(), fixture)

    def __getitem__(self, name: str) -> Any:
        return self.values[name]

    def ns(self, name: str) -> int:
        return int(self[name] * SEC)
