"""B's sourced entry dependencies (LEAD-1452 part 4); no order or balance implementation.

BUILD ON Sextant@7252b0f5 exits/policy.py:69-115, alpaca/commission.py:67-94 and
entry/sizing.py:17-50. KEEP OURS for B's row/path admission: searched those packages and
nautilus_trader@d53849b2 / alpaca-py@cc4cb3b7; neither ships B's parameters. The native
sizer takes a Decimal rate (rc8 python/nautilus_trader/risk/__init__.pyi:18-28;
crates/risk/src/sizing.rs:132-153). USD/fill is not that rate; only a sourced zero model
is representable as one constant zero rate, independent of price, quantity and fill count.
"""

from collections.abc import Mapping, Sequence
from dataclasses import fields
from datetime import date
from typing import Any

from sextant.entry.parameters import number
from sextant.exits.policy import CHASE, ExitParams

SCOPE = "alpaca-paper-b"
EXIT_FIELDS = {f.name for f in fields(ExitParams)} - set(CHASE)
EXIT_ROWS = EXIT_FIELDS | {"chase_min_interval_s", "round_trip_cost"}


def _indexed(rows: Sequence[Mapping[str, Any]], expected: set[str]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for row in rows:
        name = row.get("name")
        if name not in expected or name in found:
            raise ValueError(f"{name}: unknown or duplicate row")
        found[name] = row
    if missing := expected - found.keys():
        raise ValueError(f"missing rows: {sorted(missing)}")
    return found


def _authority(row: Mapping[str, Any]) -> None:
    name = row["name"]
    if row.get("scope") != SCOPE:
        raise ValueError(f"{name}: scope must be {SCOPE}")
    if any(
        not isinstance(row.get(k), str) or not row[k].strip()
        for k in ("source", "unit", "last_change")
    ):
        raise ValueError(f"{name}: source/unit/last_change required")
    try:
        date.fromisoformat(row["last_change"])
    except ValueError:
        raise ValueError(f"{name}: last_change must be an ISO date") from None


def load_exit_params(rows: Sequence[Mapping[str, Any]]) -> ExitParams:
    """B's file only, with unavailable cost/interval and no entry-to-exit chase fallback."""
    found = _indexed(rows, EXIT_ROWS)
    values: dict[str, Any] = {name: None for name in CHASE}
    for name, row in found.items():
        _authority(row)
        value, state = row.get("value"), row.get("calibration_state")
        if name in {"round_trip_cost", "chase_min_interval_s"}:
            if value is not None or state != "UNAVAILABLE":
                raise ValueError(f"{name}: must remain UNAVAILABLE for B")
            continue
        if value is None or state not in {"UNCALIBRATED", "CALIBRATED"}:
            raise ValueError(f"{name}: no sourced value")
        if name == "breach_persist_count":
            if type(value) is not int or value < 1:
                raise ValueError(f"{name}: positive integer required")
            values[name] = value
        else:
            values[name] = number(value, name, zero=True)
    return ExitParams(**values)
