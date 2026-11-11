"""The ranking node's window rows (review F7): each value from its registry row, never a flag.

``deploy/ranking-node/parameters.json`` follows the deploy parameter pattern (a schema, then rows
with value, unit, status and source). A sourced row is UNCALIBRATED; a window with no source is
UNAVAILABLE with a null value, and the caller decides what the node does without it. A command
flag is only an explicit override, and the resolution, with each value's origin, is written as
``parameters-receipt.json`` beside the run's other receipts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sextant.execution.state import write_atomic

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "deploy/ranking-node/parameters.json"
SCHEMA = "sextant.ranking-node.parameters/1"
RECEIPT = "parameters-receipt.json"


@dataclass(frozen=True)
class Row:
    value: int | None
    status: str
    source: str


def load(path: Path = DEFAULT_PATH) -> dict[str, Row]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema") != SCHEMA or not isinstance(raw.get("rows"), dict):
        raise ValueError(f"{path} is not a {SCHEMA} registry")
    rows = {}
    for name, item in raw["rows"].items():
        value, status, source = item.get("value"), item.get("status"), item.get("source")
        sourced = status in {"UNCALIBRATED", "CALIBRATED"}
        if (
            not isinstance(source, str)
            or not source.strip()
            or not (
                (sourced and type(value) is int and value > 0)
                or (status == "UNAVAILABLE" and value is None)
            )
        ):
            raise ValueError(
                f"the {name} row needs a positive int with its source, or null as UNAVAILABLE"
            )
        rows[name] = Row(value, status, source)
    return rows


def resolve(rows: dict[str, Row], name: str, override: int | None) -> tuple[int | None, str]:
    """The override when given, else the row's value; an unavailable row stays None."""
    if override is not None:
        return override, "override"
    row = rows[name]
    return (None, "unavailable") if row.value is None else (row.value, "registry")


def write_receipt(directory: Path, resolved: dict[str, tuple[int | None, str]]) -> Path:
    path = Path(directory) / RECEIPT
    write_atomic(
        path,
        {name: {"value": value, "origin": origin} for name, (value, origin) in resolved.items()},
    )
    return path
