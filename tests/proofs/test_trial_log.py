"""Cumulative source schema, one-writer lease, recovery and explicit unverified provenance."""

import json
import signal
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from sextant.validation.trials import SCHEMA, WITNESS_PATH, TrialLog, snapshot_hash


def config(run: str, **changes: object) -> dict:
    settings = {"optimizer_run": "first", "version": "v1"}
    weights = {"ema_cross": "1"}
    return {
        "arm_id": "ema-seed",
        "arm_run_id": run,
        "implementation_sha": "a" * 40,
        "factor_mask": ["ema_cross"],
        "sandbox_config": settings,
        "sandbox_config_hash": snapshot_hash(settings),
        "evidence_weights": weights,
        "evidence_weights_hash": snapshot_hash(weights),
        "params_hash": snapshot_hash({"fast": 10}),
        "tier": "MODELED",
        "block_set_id": "development-1",
        "funding_divergent_session_count": None,
        "funding_unverified_session_count": None,
        "condition_returns": {},
        **changes,
    }


def append(log: TrialLog, run: str, state: str = "COMPLETE", **changes: object) -> int:
    return log.append("EMA", {"fast": 10}, config(run, **changes), 7, state)


def test_schema_keeps_all_thirteen_legacy_columns() -> None:
    assert SCHEMA.names == [
        "trial_id",
        "strategy",
        "config",
        "params",
        "seed",
        "state",
        "error",
        "days",
        "daily_net_returns",
        "fold_scores",
        "objective",
        "n_trials",
        "effective_n",
    ]
    assert [str(field.type) for field in SCHEMA] == [
        "int64",
        "string",
        "string",
        "string",
        "int64",
        "string",
        "string",
        "list<item: string>",
        "list<item: double>",
        "list<item: double>",
        "double",
        "int64",
        "double",
    ]


def test_reruns_rejections_and_failures_retain_immutable_counts(tmp_path: Path) -> None:
    log = TrialLog(tmp_path / WITNESS_PATH)
    append(log, "first")
    first = deepcopy(log.records[0])
    for run, state in [("rerun", "COMPLETE"), ("rejected", "PRUNED"), ("failed", "FAIL")]:
        append(TrialLog(log.path), run, state)
    rows = TrialLog(log.path).records
    assert rows[0] == first
    assert [r["n_trials"] for r in rows] == [1, 2, 3, 4]
    assert all(r["effective_n"] is None for r in rows)
    assert [r["state"] for r in rows] == ["COMPLETE", "COMPLETE", "PRUNED", "FAIL"]


@pytest.mark.parametrize(
    "changes",
    [
        {"sandbox_config_hash": "0" * 64},
        {"params_hash": "0" * 64},
        {"evidence_weights_hash": "0" * 64},
        {"implementation_sha": None},
        {"implementation_sha": "g" * 40},
        {"implementation_sha": "a" * 40 + "\n"},
        {"buying_power": 0.1},
    ],
)
def test_identity_and_float_refusals_cannot_write(tmp_path: Path, changes: dict) -> None:
    log = TrialLog(tmp_path / WITNESS_PATH)
    with pytest.raises(ValueError):
        append(log, "bad", **changes)
    assert log.records == []


def test_same_arm_run_cannot_be_appended_twice(tmp_path: Path) -> None:
    log = TrialLog(tmp_path / WITNESS_PATH)
    append(log, "first")
    with pytest.raises(ValueError, match="arm_run_id"):
        append(log, "first")
    assert TrialLog(log.path).n_trials == 1


def test_whole_run_lease_blocks_other_raw_writers_without_reaping_live_rows(tmp_path: Path) -> None:
    path = tmp_path / WITNESS_PATH
    first, other = TrialLog(path), TrialLog(path)
    with first.attempts({"fixture": {}}, {}, {"tier": "MODELED", "block_set_id": "test"}):
        with pytest.raises(BlockingIOError):
            append(other, "intruder")
        with (
            pytest.raises(BlockingIOError),
            other.attempts({"intruder": {}}, {}, {"tier": "MODELED", "block_set_id": "test"}),
        ):
            pass
        assert TrialLog(path).records[0]["state"] == "RUNNING"
    assert TrialLog(path).records[0]["state"] == "COMPLETE"


def test_sigkill_is_recovered_without_deleting_the_attempt(tmp_path: Path) -> None:
    path = tmp_path / WITNESS_PATH
    child = """
import os, signal, sys
from pathlib import Path
from sextant.validation.trials import TrialLog
log = TrialLog(Path(sys.argv[1]))
with log.attempts({"killed": {}}, {}, {"tier":"MODELED", "block_set_id":"test"}):
    os.kill(os.getpid(), signal.SIGKILL)
"""
    killed = subprocess.run([sys.executable, "-c", child, str(path)], check=False, timeout=30)
    assert killed.returncode == -signal.SIGKILL
    before = TrialLog(path).records[0]
    assert before["state"] == "RUNNING"
    with TrialLog(path).attempts({"rerun": {}}, {}, {"tier": "MODELED", "block_set_id": "test"}):
        pass
    rows = TrialLog(path).records
    assert [r["state"] for r in rows] == ["FAIL", "COMPLETE"]
    assert "abandoned" in rows[0]["error"]
    assert rows[0]["trial_id"] == before["trial_id"] and rows[0]["config"] == before["config"]
    assert [r["n_trials"] for r in rows] == [1, 2]


def test_second_registration_failure_terminalizes_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = TrialLog(tmp_path / WITNESS_PATH)
    real = log.append
    calls = 0

    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("second registration failed")
        return real(*args, **kwargs)

    monkeypatch.setattr(log, "append", fail)
    with (
        pytest.raises(OSError, match="second registration"),
        log.attempts({"first": {}, "second": {}}, {}, {"tier": "MODELED", "block_set_id": "test"}),
    ):
        pytest.fail("engine must not start")
    rows = TrialLog(log.path).records
    assert len(rows) == 1 and rows[0]["state"] == "FAIL"


def test_no_caller_can_claim_committed_binding(tmp_path: Path) -> None:
    log = TrialLog(tmp_path / WITNESS_PATH)
    append(log, "unverified", code_binding="COMMITTED")
    assert json.loads(log.records[0]["config"])["code_binding"] == "UNVERIFIED"


def test_legacy_schema_metadata_and_rows_survive_append(tmp_path: Path) -> None:
    log = TrialLog(tmp_path / WITNESS_PATH)
    append(log, "legacy")
    original = deepcopy(log.records[0])
    pq.write_table(
        pa.Table.from_pylist(log.records, schema=SCHEMA.with_metadata({b"frozen": b"receipt"})),
        log.path,
    )
    append(TrialLog(log.path), "later")
    assert TrialLog(log.path).records[0] == original
    assert pq.read_schema(log.path).metadata[b"frozen"] == b"receipt"


def test_failed_fsync_keeps_the_previous_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sextant.validation.trials as trials

    log = TrialLog(tmp_path / WITNESS_PATH)
    append(log, "first")
    original = log.path.read_bytes()

    def fail(_fd: int) -> None:
        raise OSError("fixture disk failure")

    monkeypatch.setattr(trials, "full_fsync", fail)
    with pytest.raises(OSError, match="disk failure"):
        append(log, "uncommitted")
    assert log.path.read_bytes() == original
    assert TrialLog(log.path).n_trials == 1


def test_foreign_or_legacy_running_owner_is_never_guessed_dead(tmp_path: Path) -> None:
    log = TrialLog(tmp_path / WITNESS_PATH)
    append(log, "unknown-owner", "RUNNING")
    original = log.path.read_bytes()
    with (
        pytest.raises(ValueError, match="liveness unknown"),
        log.attempts({"rerun": {}}, {}, {"tier": "MODELED", "block_set_id": "test"}),
    ):
        pytest.fail("unknown owner must block execution")
    assert log.path.read_bytes() == original
    assert TrialLog(log.path).records[0]["state"] == "RUNNING"


def test_nested_run_cannot_reap_its_own_live_owner(tmp_path: Path) -> None:
    log = TrialLog(tmp_path / WITNESS_PATH)
    with log.attempts({"outer": {}}, {}, {"tier": "MODELED", "block_set_id": "test"}):
        with (
            pytest.raises(ValueError, match="already owns"),
            log.attempts({"inner": {}}, {}, {"tier": "MODELED", "block_set_id": "test"}),
        ):
            pytest.fail("nested engine must not start")
        assert TrialLog(log.path).records[0]["state"] == "RUNNING"
    assert TrialLog(log.path).records[0]["state"] == "COMPLETE"
