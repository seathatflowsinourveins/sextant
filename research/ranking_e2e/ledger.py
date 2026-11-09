"""TrialLog reservation for a detection-only arm; append stays refused.

The K3 protocol's ledger binding is NOT_RUN until the writer/custodian answers
(U5).  Building the row is allowed; appending without a ruling is not, and no
second ledger or schema fork exists here.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sextant.validation.trials import TrialLog, snapshot_hash

TIER = "MODELED"
REQUIRED_IDENTITY = (
    "arm_id",
    "arm_run_id",
    "implementation_sha",
    "factor_mask",
    "sandbox_config",
    "sandbox_config_hash",
    "evidence_weights",
    "evidence_weights_hash",
    "params_hash",
    "tier",
    "block_set_id",
    "funding_divergent_session_count",
    "funding_unverified_session_count",
    "condition_returns",
)


class LedgerRefused(RuntimeError):
    """The ledger writer or custodian has not ruled."""


def detection_row(
    *,
    arm_id: str,
    arm_run_id: str,
    implementation_sha: str,
    block_set_id: str,
    session_list_sha256: str,
) -> dict[str, Any]:
    """A 13-column reservation whose merit columns are explicitly empty."""
    if len(implementation_sha) != 40 or any(
        c not in "0123456789abcdef" for c in implementation_sha
    ):
        raise ValueError("implementation_sha must be a 40-hex commit")
    if not arm_id or not arm_run_id or not block_set_id or not session_list_sha256:
        raise ValueError("explicit arm, run, block and session-list identity required")
    sandbox = {"mode": "bar-close replay", "memory_cap": "8G", "swap": "0"}
    params: dict[str, Any] = {
        "arm_id": arm_id,
        "arm_run_id": arm_run_id,
        "tier": TIER,
        "block_set_id": block_set_id,
        "session_list_sha256": session_list_sha256,
        "detection_only": True,
    }
    config: dict[str, Any] = {
        "arm_id": arm_id,
        "arm_run_id": arm_run_id,
        "implementation_sha": implementation_sha,
        "factor_mask": [],
        "sandbox_config": sandbox,
        "sandbox_config_hash": snapshot_hash(sandbox),
        "evidence_weights": {},
        "evidence_weights_hash": snapshot_hash({}),
        "params_hash": snapshot_hash(params),
        "tier": TIER,
        "block_set_id": block_set_id,
        "session_list_sha256": session_list_sha256,
        "funding_divergent_session_count": None,
        "funding_unverified_session_count": None,
        "condition_returns": {},
    }
    missing = set(REQUIRED_IDENTITY) - config.keys()
    if missing:  # pragma: no cover - guards a future edit
        raise ValueError(f"missing ledger identity: {sorted(missing)}")
    return {
        "strategy": "ranking_e2e",
        "state": "COMPLETE",
        "days": [],
        "daily_net_returns": [],
        "fold_scores": [],
        "objective": None,
        "tier": TIER,
        "params": params,
        "config": config,
    }


def append(
    row: Mapping[str, Any],
    *,
    path: Path | None,
    custodian_ruling: str | None,
) -> int:
    if not custodian_ruling:
        raise LedgerRefused("ledger binding NOT_RUN: the TrialLog custodian has not ruled")
    if path is None:
        raise LedgerRefused("a concrete TrialLog path is required")
    if row.get("days") or row.get("daily_net_returns") or row.get("fold_scores"):
        raise LedgerRefused("detection-only rows must leave merit columns empty")
    if row.get("objective") is not None:
        raise LedgerRefused("detection-only rows carry a null objective")
    log = TrialLog(Path(path))
    return log.append(
        str(row["strategy"]),
        row["params"],
        row["config"],
        seed=None,
        state=str(row["state"]),
        days=(),
        daily_net_returns=(),
        fold_scores=(),
        objective=None,
    )
