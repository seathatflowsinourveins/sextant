"""#102's single-writer inbox; this module never creates or writes a TrialLog.

Contracts: northstar-trading@8256c16c31dc validation/trials.py and the
owner-sanctioned sextant.ledger.handoff/1 (#110/#111 6691367354).
Canonical hash/identity shape follows TrialLog; publication follows the
existing fsync/no-overwrite replay receipts. Git reads only a posted ledger
commit in the protected ref's history, never an arbitrary local Parquet.
"""

import hashlib
import io
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


def _no_floats(value: Any):
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise ValueError("string identity keys required")
        for item in value.values():
            _no_floats(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _no_floats(item)
    elif value is not None and type(value) not in (str, int, bool):
        raise ValueError("identity/result values require Decimal strings, never floats")


def wire(value: Any) -> bytes:
    _no_floats(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else wire(value)).hexdigest()


def _reserve(row: dict):
    if set(row) != {"strategy", "params", "seed", "config"}:
        raise ValueError("reservation requires strategy/params/seed/config only")
    config = row["config"]
    required = {
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
    }
    if required - config.keys() or config["tier"] != "MODELED":
        raise ValueError("complete MODELED reservation identity required")
    if not re.fullmatch("[0-9a-f]{40}", config["implementation_sha"]):
        raise ValueError("concrete implementation commit required")
    if not all(
        isinstance(config[k], str) and config[k] for k in ("arm_id", "arm_run_id", "block_set_id")
    ):
        raise ValueError("explicit arm/run/block identities required")
    for name, value in (
        ("params", row["params"]),
        ("sandbox_config", config["sandbox_config"]),
        ("evidence_weights", config["evidence_weights"]),
    ):
        if config[f"{name}_hash"] != digest(value):
            raise ValueError(f"{name} hash mismatch")
    if config["condition_returns"] or not isinstance(config["factor_mask"], list):
        raise ValueError("reserved attempt has no returns and an explicit factor mask")


def _outcome(row: dict):
    if not row.get("arm_run_id") or row.get("state") not in {"COMPLETE", "FAIL", "PRUNED"}:
        raise ValueError("terminal arm-run outcome required")
    if row["state"] == "COMPLETE" and not row.get("result"):
        raise ValueError("complete outcome requires result")
    if row["state"] != "COMPLETE" and any(
        row.get(key) for key in ("days", "daily_net_returns", "condition_returns")
    ):
        raise ValueError("failed/pruned attempt cannot invent returns")
    if "result" in row and row["result"].get("tier") != "MODELED":
        raise ValueError("result must keep its MODELED reservation tier")


def stage_handoff(path: Path, *, kind: str, rows: list[dict]) -> dict:
    if kind not in {"reserve", "outcome"} or not rows:
        raise ValueError("nonempty reserve/outcome batch required")
    _no_floats(rows)
    seen = set()
    for row in rows:
        (_reserve if kind == "reserve" else _outcome)(row)
        identity = row["config"]["arm_run_id"] if kind == "reserve" else row["arm_run_id"]
        if identity in seen:
            raise ValueError("duplicate arm-run in handoff")
        seen.add(identity)
    raw = b"".join(wire(row) + b"\n" for row in rows)
    manifest = dict(
        format="sextant.ledger.handoff/1",
        lane="sandbox",
        issue=111,
        kind=kind,
        count=len(rows),
        rows_sha256=digest(raw),
        tier="MODELED",
    )
    path.mkdir(parents=True, exist_ok=False)
    for name, payload in (("rows.jsonl", raw), ("manifest.json", wire(manifest) + b"\n")):
        with (path / name).open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return manifest


def validate_reservation(records: list[dict], requested: dict) -> dict:
    _reserve(requested)
    matches = [
        record
        for record in records
        if json.loads(record["config"]).get("arm_run_id") == requested["config"]["arm_run_id"]
    ]
    if len(matches) != 1:
        raise ValueError("one canonical reserved attempt required")
    record = matches[0]
    if (
        record["state"] != "RUNNING"
        or json.loads(record["config"]) != requested["config"]
        or json.loads(record["params"]) != requested["params"]
        or record["strategy"] != requested["strategy"]
        or record["seed"] != requested["seed"]
    ):
        raise ValueError("canonical reservation identity/state changed")
    return record


def canonical_reservation(repo: Path, commit: str, requested: dict) -> dict:
    """Caller first fetches the posted reservation ref once; no polling/network here."""
    if not re.fullmatch("[0-9a-f]{40}", commit):
        raise ValueError("posted ledger commit required")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "origin/ledger"],
        cwd=repo,
        check=True,
        capture_output=True,
        timeout=30,
    )

    def read(ref):
        raw = subprocess.run(
            ["git", "show", f"{ref}:reports/research/sim-runner/trials.parquet"],
            cwd=repo,
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
        return validate_reservation(pq.read_table(io.BytesIO(raw)).to_pylist(), requested)

    reserved = read(commit)
    # An older RUNNING receipt cannot revive a terminal attempt on the fetched ref.
    read("origin/ledger")
    return reserved
