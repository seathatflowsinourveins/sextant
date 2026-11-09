"""Detection-only arms never write TrialLog rows.

The K3 custodian ruling (ADR-0019:26) is explicit: only arms that trade, run
through N1 and then B's protection, write MODELED rows with their returns.
Detection-only measurements stay in the hashed session report.  No zero
imputation, no empty merit columns and no second ledger exist here.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any


class LedgerRefused(RuntimeError):
    """A detection-only arm has no admissible TrialLog row."""


def detection_row(**_: object) -> dict[str, Any]:
    """Refuse to build a detection-only TrialLog row (custodian ruling)."""
    raise LedgerRefused(
        "detection-only measurements stay in the hashed report; only trading arms "
        "through N1 then B protection write MODELED rows with returns"
    )


def append(
    row: Mapping[str, Any],
    *,
    path: Path | None,
    custodian_ruling: str | None,
) -> int:
    """Refuse every detection-only append, with or without a ruling."""
    raise LedgerRefused(
        "detection-only rows are inadmissible under ADR-0019:26; the hashed report "
        "carries the measurement and no zero/empty merit row is written"
    )
