"""TrialLog writer slice from northstar-trading@8256c16c31dc:validation/trials.py.

Original row schema, identity checks, count refresh and fsync publication; lease from runner.py.
No inference or merit calculator (#147). Canonical custody: `ledger`, via scripts/ledger-append.sh.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import subprocess
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from socket import gethostname
from typing import Any
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from sextant.persist import fsync_dir, full_fsync

WITNESS_PATH = Path("reports/research/trials.parquet")
TIERS = frozenset({"MODELED", "SIMULATED", "BROKER-PAPER"})
# n_trials and effective_n are rewritten on every row at each commit (source _refresh_counts,
# trials.py:233-236): n_trials is the file's current N over every tier, not the count when the
# row was written; effective_n is float(N), the upstream no-discount fallback,
# never a measured effective count. Inference freezes its own N snapshot (ADR-0019 N); nothing
# reads these as measured (test_trial_log.py), and recorded history keeps them as written.
SCHEMA = pa.schema(
    [
        ("trial_id", pa.int64()),
        ("strategy", pa.string()),
        ("config", pa.string()),
        ("params", pa.string()),
        ("seed", pa.int64()),
        ("state", pa.string()),
        ("error", pa.string()),
        ("days", pa.list_(pa.string())),
        ("daily_net_returns", pa.list_(pa.float64())),
        ("fold_scores", pa.list_(pa.float64())),
        ("objective", pa.float64()),
        ("n_trials", pa.int64()),
        ("effective_n", pa.float64()),
    ]
)


def _no_floats(value: Any) -> None:
    if isinstance(value, float):
        raise ValueError("no float anywhere in merit inputs; use Decimal strings")
    if isinstance(value, Mapping):
        for item in value.values():
            _no_floats(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _no_floats(item)


def snapshot_hash(value: Any) -> str:
    """Source sim_lanes/registry.py: finite JSON, independent of insertion order."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _returns(days: Sequence[str], values: Sequence[float]) -> None:
    if list(days) != sorted(set(days)) or any(date.fromisoformat(d).isoformat() != d for d in days):
        raise ValueError("unique chronological ISO session days required")
    if len(days) != len(values) or not all(math.isfinite(v) for v in values):
        raise ValueError("returns must be finite and aligned to days")


def _arm_run_id(record: Mapping[str, Any]) -> str | None:
    """Source `.get` (trials.py:466,565): L9's legacy replay rows carry no arm-run identity."""
    return json.loads(record["config"]).get("arm_run_id")


class TrialLog:
    """Every attempt counts; no delete/reset API. Reopen under the stable writer lock."""

    def __init__(self, path: Path) -> None:
        if any(part.is_symlink() for part in (path, *path.parents)):  # source trials.py:181-183
            raise ValueError("TrialLog symlink paths refused")
        self.path = path
        self._local = threading.local()
        self._reload()

    @contextmanager
    def writer(self) -> Iterator[None]:
        if getattr(self._local, "held", False):
            yield
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_name(f".{self.path.name}.lock").open("a") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._local.held, self._local.lease = True, lease.fileno()
            try:
                yield
            finally:
                self._local.held = False

    def _reload(self) -> None:
        table = (
            pq.read_table(self.path)
            if self.path.exists()
            else pa.Table.from_pylist([], schema=SCHEMA)
        )
        if not table.schema.equals(SCHEMA):
            raise ValueError("TrialLog schema differs from the retained 13-column contract")
        if self.path.exists() and self.path.stat().st_nlink > 1:  # sqlite os_unix.c:1660
            raise ValueError("a hard-linked TrialLog would split at its next atomic replace")
        self._schema = table.schema
        self.records: list[dict[str, Any]] = table.to_pylist()

    @contextmanager
    def _writer(self) -> Iterator[None]:
        with self.writer():
            self._reload()
            try:
                yield
                self._checkpoint()
            except BaseException:
                self._reload()
                raise

    @property
    def n_trials(self) -> int:
        return len(self.records)

    @property
    def next_trial_id(self) -> int:
        return max((r["trial_id"] for r in self.records), default=-1) + 1

    def append(
        self,
        strategy: str,
        params: Mapping[str, Any],
        config: Mapping[str, Any],
        seed: int | None,
        state: str = "RUNNING",
        trial_id: int | None = None,
        days: Sequence[str] = (),
        daily_net_returns: Sequence[float] = (),
        fold_scores: Sequence[float] = (),
        objective: float | None = None,
        error: str = "",
    ) -> int:
        """Source append, with identity checks and atomic ID allocation for independent callers."""
        config = dict(config, code_binding="UNVERIFIED")
        _returns(days, daily_net_returns)
        if {"effective_n_snapshots", "effective_n_snapshot_hash"} & config.keys():
            raise ValueError("inference snapshots belong to TrialLog, not caller metadata")
        _no_floats(params)
        _no_floats({k: v for k, v in config.items() if k != "condition_returns"})
        if state not in {"COMPLETE", "PRUNED", "FAIL", "RUNNING"}:
            raise ValueError("invalid trial state")
        if objective is not None and not math.isfinite(objective):
            raise ValueError("objective must be finite")
        if not all(math.isfinite(v) for v in fold_scores):
            raise ValueError("fold scores must be finite")
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
        if required - config.keys():
            raise ValueError(f"missing trial identity: {sorted(required - config.keys())}")
        sha = config["implementation_sha"]
        if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
            raise ValueError("implementation_sha must be a concrete code SHA")
        if config["tier"] not in TIERS:
            raise ValueError("trial requires exactly one tier")
        if not all(
            isinstance(config[k], str) and config[k]
            for k in ("arm_id", "arm_run_id", "block_set_id")
        ):
            raise ValueError("nonempty arm/run/block identity required")
        if not isinstance(config["factor_mask"], (list, tuple)):
            raise ValueError("factor_mask must be explicit")
        for name in ("sandbox_config", "evidence_weights", "params"):
            value = params if name == "params" else config[name]
            if config[f"{name}_hash"] != snapshot_hash(value):
                raise ValueError(f"{name}_hash differs from frozen identity")
        for key in ("funding_divergent_session_count", "funding_unverified_session_count"):
            count = config[key]
            if count is not None and (type(count) is not int or count < 0):
                raise ValueError("funding uncertainty must be explicit nonnegative counts or null")
        for values in config["condition_returns"].values():
            _returns(days, values)
        with self._writer():
            if trial_id is None:
                trial_id = self.next_trial_id
            if any(r["trial_id"] == trial_id for r in self.records):
                raise ValueError(f"trial {trial_id} already logged")
            if any(_arm_run_id(r) == config["arm_run_id"] for r in self.records):
                raise ValueError("arm_run_id already logged; a rerun requires a fresh attempt")
            self.records.append(
                dict(
                    trial_id=trial_id,
                    strategy=strategy,
                    params=json.dumps(params, sort_keys=True, allow_nan=False),
                    config=json.dumps(config, sort_keys=True, allow_nan=False),
                    seed=seed,
                    state=state,
                    error=error,
                    days=list(days),
                    daily_net_returns=list(daily_net_returns),
                    fold_scores=list(fold_scores),
                    objective=objective,
                    n_trials=self.n_trials + 1,
                    effective_n=None,
                )
            )
        return trial_id

    def finish_arm_run(
        self,
        arm_run_id: str,
        *,
        state: str = "FAIL",
        error: str = "",
        days: Sequence[str] = (),
        daily_net_returns: Sequence[float] = (),
        condition_returns: Mapping[str, Sequence[float]] | None = None,
        result: Mapping[str, Any] | None = None,
    ) -> None:
        """Source RUNNING-to-terminal update; no new attempt or invented session returns.

        An inbox reservation's returns and result arrive once, with it; only COMPLETE carries
        returns, so a failure keeps them absent, never zero.
        """
        if state not in {"FAIL", "PRUNED", "COMPLETE"}:
            raise ValueError("terminal trial state required")
        if state != "COMPLETE" and (days or condition_returns):
            raise ValueError("only a complete attempt carries returns")
        for values in (daily_net_returns, *(condition_returns or {}).values()):
            _returns(days, values)
        _no_floats(dict(result or {}))
        with self._writer():
            record = self._running_arm(arm_run_id)
            if days and record["days"]:
                raise ValueError("a reserved attempt's returns arrive once")
            config = json.loads(record["config"])
            if condition_returns is not None:
                config["condition_returns"] = {k: list(v) for k, v in condition_returns.items()}
            if result is not None:
                config["result"] = dict(result)
            frozen = json.dumps(config, sort_keys=True, allow_nan=False)
            record.update(state=state, error=error, config=frozen)
            if days:
                record.update(days=list(days), daily_net_returns=list(daily_net_returns))

    def _running_arm(self, arm_run_id: str) -> dict[str, Any]:
        """Source `_running_arm` (trials.py:563-569): the one RUNNING attempt of an arm-run."""
        record = next((r for r in self.records if _arm_run_id(r) == arm_run_id), None)
        if record is None or record["state"] != "RUNNING":
            raise ValueError("unknown or terminal arm-run")
        return record

    def _checkpoint(self) -> None:
        if os.fstat(self._local.lease).st_nlink == 0:  # sqlite os_unix.c:1656, unlinked while open
            raise ValueError("writer lease lost: its lock file was removed; nothing published")
        for record in self.records:  # source _refresh_counts (trials.py:233-236); effective N = N
            record.update(n_trials=self.n_trials, effective_n=float(self.n_trials))
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            pq.write_table(
                pa.Table.from_pylist(self.records, schema=self._schema),
                temporary,
            )
            with temporary.open("rb") as handle:
                full_fsync(handle.fileno())
            temporary.replace(self.path)
            fsync_dir(self.path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    @contextmanager
    def attempts(
        self,
        arms: Mapping[str, Mapping[str, str]],
        params: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> Iterator[str]:
        if getattr(self._local, "in_run", False):
            raise ValueError("a live run already owns this writer")
        with self.writer():
            writer_key = f"{gethostname()}:{self.path.resolve()}"
            with self._writer():
                for row in self.records:
                    if row["state"] == "RUNNING":
                        if json.loads(row["config"]).get("writer_lock") != writer_key:
                            raise ValueError(
                                "RUNNING writer liveness unknown; owner resolution required"
                            )
                        row.update(state="FAIL", error="abandoned previous writer; no live lease")
            run_id, runs = str(uuid4()), []
            self._local.in_run = True
            try:
                sha = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[3], text=True
                ).strip()
                for arm, weights in arms.items():
                    identity = dict(
                        arm_id=arm,
                        arm_run_id=f"{run_id}-{arm}",
                        implementation_sha=sha,
                        factor_mask=list(weights),
                        sandbox_config=config,
                        sandbox_config_hash=snapshot_hash(config),
                        evidence_weights=weights,
                        evidence_weights_hash=snapshot_hash(weights),
                        params_hash=snapshot_hash(params),
                        tier=config["tier"],
                        block_set_id=config["block_set_id"],
                        funding_divergent_session_count=None,
                        funding_unverified_session_count=None,
                        condition_returns={},
                        writer_lock=writer_key,
                    )
                    self.append(arm, params, identity, None)
                    runs.append(identity["arm_run_id"])
                yield run_id
            except BaseException as exc:
                for run in runs:
                    self.finish_arm_run(run, error=type(exc).__name__)
                raise
            else:
                for run in runs:
                    self.finish_arm_run(run, state="COMPLETE")
            finally:
                self._local.in_run = False
