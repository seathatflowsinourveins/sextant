#!/usr/bin/env python3
"""Read-only L3/L4 bridge for the monitor: OmniRoute, dsh v4, Orca and AO.

Usage:
    python3 -I scripts/monitor_l3_l4.py [--write PATH] [--otlp [URL]]

The bridge never writes a router, AO or runtime file. It opens both SQLite
databases with ``mode=ro`` and reads only the metadata columns allowlisted below,
never request/response bodies, prompts, terminal text, logs or credentials.
Orca is called only through the fixed metadata command list; OTLP goes only to a
loopback endpoint. Missing evidence is reported as unavailable, never zero.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PARAMS = ROOT / "deploy" / "monitor" / "l3-l4.params.json"
AO_LAUNCHER = ROOT / "deploy" / "wsl" / "ao.sh"
DEFAULT_OTLP = "http://127.0.0.1:4318/v1/metrics"
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})

# ---------------------------------------------------------------------------
# Metadata column allowlists. Every SELECT is built from these tuples; a name
# outside its table's tuple is refused before SQLite sees it.

CALL_LOG_COLUMNS = (
    "timestamp",
    "model",
    "provider",
    "status",
    "error_type",
    "duration",
    "ttft_ms",
    "queue_wait_ms",
    "reasoning_duration_ms",
    "tokens_in",
    "tokens_out",
    "reasoning_effort_upstream",
    "detail_state",
)
QUOTA_COLUMNS = (
    "provider",
    "connection_id",
    "window_key",
    "remaining_percentage",
    "is_exhausted",
    "next_reset_at",
    "window_duration_ms",
    "created_at",
)
COST_COLUMNS = (
    "timestamp",
    "provider",
    "model",
    "tokens_input",
    "tokens_output",
    "tokens_cache_read",
    "tokens_cache_creation",
    "unit_price_input",
    "unit_price_output",
    "amount_usd",
    "service_tier",
    "success",
)
CONNECTION_COLUMNS = (
    "id",
    "provider",
    "display_name",
    "is_active",
    "rate_limited_until",
    "last_used_at",
    "priority",
)
BREAKER_COLUMNS = ("name", "state", "failure_count", "last_failure_time")
RESET_COLUMNS = (
    "provider",
    "connection_id",
    "window_key",
    "window_resets_at",
    "observed_at",
    "new_remaining_percentage",
)
LEASE_COLUMNS = ("provider", "connection_id", "state", "expires_at")

AO_SESSION_COLUMNS = (
    "id",
    "num",
    "issue_id",
    "kind",
    "harness",
    "activity_state",
    "activity_last_at",
    "is_terminated",
    "branch",
    "created_at",
    "updated_at",
    "model",
    "effort",
    "terminated_at",
    "session_mode",
)
AO_USAGE_COLUMNS = (
    "provider_id",
    "model_id",
    "usage_measurement_kind",
    "input_tokens",
    "cached_input_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "created_at",
    "input_cost_nanos",
    "cached_input_cost_nanos",
    "output_cost_nanos",
    "estimated_cost_nanos",
    "pricing_version",
)
AO_PR_COLUMNS = (
    "url",
    "session_id",
    "number",
    "pr_state",
    "review_decision",
    "ci_state",
    "updated_at",
    "head_sha",
    "title",
    "additions",
    "deletions",
    "changed_files",
    "review_partial",
)
AO_CHECK_COLUMNS = ("pr_url", "name", "commit_hash", "status", "conclusion", "created_at")
AO_REVIEW_COLUMNS = (
    "pr_url",
    "review_id",
    "author",
    "state",
    "is_bot",
    "submitted_at",
    "target_sha",
)
AO_THREAD_COLUMNS = ("pr_url", "thread_id", "path", "line", "resolved", "is_bot", "updated_at")
AO_MEASUREMENT_COLUMNS = (
    "pr_key",
    "historical",
    "historical_merged",
    "associated_reported",
    "merged_reported",
    "closed_reported",
    "merged_via",
)
AO_TELEMETRY_COLUMNS = ("session_id", "created_by", "waiting_input_count", "end_claimed")

ALLOWED_COLUMNS: dict[str, frozenset[str]] = {
    "call_logs": frozenset(CALL_LOG_COLUMNS),
    "quota_snapshots": frozenset(QUOTA_COLUMNS),
    "request_cost_ledger": frozenset(COST_COLUMNS),
    "provider_connections": frozenset(CONNECTION_COLUMNS),
    "domain_circuit_breakers": frozenset(BREAKER_COLUMNS),
    "provider_quota_reset_events": frozenset(RESET_COLUMNS),
    "exclusive_connection_leases": frozenset(LEASE_COLUMNS),
    "sessions": frozenset(AO_SESSION_COLUMNS),
    "model_usage_events": frozenset(AO_USAGE_COLUMNS),
    "pr": frozenset(AO_PR_COLUMNS),
    "pr_checks": frozenset(AO_CHECK_COLUMNS),
    "pr_reviews": frozenset(AO_REVIEW_COLUMNS),
    "pr_review_threads": frozenset(AO_THREAD_COLUMNS),
    "usage_pr_measurement": frozenset(AO_MEASUREMENT_COLUMNS),
    "session_telemetry": frozenset(AO_TELEMETRY_COLUMNS),
}

# Bodies, prompts, terminal/log tails and credentials. These names must never
# appear in a built SELECT, whether as a table or a column.
FORBIDDEN_COLUMNS = frozenset(
    {
        "request_detail_logs",
        "artifact_relpath",
        "artifact_size_bytes",
        "artifact_sha256",
        "request_summary",
        "has_request_body",
        "has_response_body",
        "access_token",
        "refresh_token",
        "api_key",
        "id_token",
        "provider_specific_data",
        "email",
        "prompt",
        "latest_user_prompt",
        "latest_assistant_update",
        "native_transcript_path",
        "log_tail",
        "details",
        "body",
        "provider_usage_json",
        "raw_data",
        "client_request",
        "translated_request",
        "provider_response",
        "client_response",
    }
)

QUOTA_LATEST_TAIL = (
    " AS q WHERE NOT EXISTS ("
    "SELECT 1 FROM quota_snapshots AS n "
    "WHERE n.provider = q.provider AND n.connection_id = q.connection_id "
    "AND n.window_key = q.window_key "
    "AND (n.created_at > q.created_at "
    "OR (n.created_at = q.created_at AND n.id > q.id))) "
    "ORDER BY q.provider, q.connection_id, q.window_key"
)

CALL_LOG_SQL = "SELECT " + ", ".join(CALL_LOG_COLUMNS) + " FROM call_logs ORDER BY timestamp"  # noqa: S608
QUOTA_SQL = "SELECT " + ", ".join(QUOTA_COLUMNS) + " FROM quota_snapshots" + QUOTA_LATEST_TAIL  # noqa: S608
COST_SQL = "SELECT " + ", ".join(COST_COLUMNS) + " FROM request_cost_ledger"  # noqa: S608
CONNECTION_SQL = "SELECT " + ", ".join(CONNECTION_COLUMNS) + " FROM provider_connections"  # noqa: S608
BREAKER_SQL = "SELECT " + ", ".join(BREAKER_COLUMNS) + " FROM domain_circuit_breakers"  # noqa: S608
RESET_SQL = "SELECT " + ", ".join(RESET_COLUMNS) + " FROM provider_quota_reset_events"  # noqa: S608
LEASE_SQL = "SELECT " + ", ".join(LEASE_COLUMNS) + " FROM exclusive_connection_leases"  # noqa: S608

AO_SESSIONS_SQL = (
    "SELECT harness, kind, activity_state, COUNT(*) AS rows FROM sessions "
    "GROUP BY harness, kind, activity_state"
)
AO_MODELS_SQL = "SELECT model, effort, COUNT(*) AS rows FROM sessions GROUP BY model, effort"
AO_USAGE_SQL = (
    "SELECT provider_id, model_id, usage_measurement_kind, "
    "SUM(input_tokens) AS input_tokens, SUM(cached_input_tokens) AS cached_input_tokens, "
    "SUM(uncached_input_tokens) AS uncached_input_tokens, SUM(output_tokens) AS output_tokens, "
    "SUM(input_cost_nanos) AS input_cost_nanos, "
    "SUM(cached_input_cost_nanos) AS cached_input_cost_nanos, "
    "SUM(output_cost_nanos) AS output_cost_nanos, "
    "SUM(estimated_cost_nanos) AS estimated_cost_nanos, "
    "COUNT(*) AS rows FROM model_usage_events "
    "GROUP BY provider_id, model_id, usage_measurement_kind"
)
AO_PR_SQL = (
    "SELECT pr_state, ci_state, review_decision, COUNT(*) AS rows FROM pr "
    "GROUP BY pr_state, ci_state, review_decision"
)
AO_CHECKS_SQL = "SELECT status, COUNT(*) AS rows FROM pr_checks GROUP BY status"
AO_REVIEWS_SQL = "SELECT state, is_bot, COUNT(*) AS rows FROM pr_reviews GROUP BY state, is_bot"
AO_THREADS_SQL = "SELECT resolved, COUNT(*) AS rows FROM pr_review_threads GROUP BY resolved"
AO_MEASUREMENTS_SQL = (
    "SELECT SUM(historical) AS historical, SUM(historical_merged) AS historical_merged, "
    "SUM(associated_reported) AS associated_reported, SUM(merged_reported) AS merged_reported, "
    "SUM(closed_reported) AS closed_reported, COUNT(*) AS rows FROM usage_pr_measurement"
)
AO_TELEMETRY_SQL = (
    "SELECT SUM(waiting_input_count) AS waiting_input_count, COUNT(*) AS rows "
    "FROM session_telemetry"
)

ORCA_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("status",),
    ("worktree", "ps", "--json"),
    ("terminal", "list", "--json"),
    ("orchestration", "task-list", "--json"),
    ("orchestration", "worker-list", "--json"),
    ("orchestration", "gate-list", "--json"),
    ("diagnostics", "memory", "--json"),
)
FORBIDDEN_ORCA = (
    ("search",),
    ("terminal", "read"),
    ("terminal", "show"),
    ("terminal", "send"),
)

DEEPSEEK_REQUIRED = (
    "deepseek_cny_per_usd",
    "deepseek_input_usd_per_mtok",
    "deepseek_output_usd_per_mtok",
    "deepseek_cache_read_usd_per_mtok",
    "monitor_otlp_endpoint",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def _metadata(table: str, columns: Iterable[str]) -> list[str]:
    """Refuse any column that is not on its table's allowlist, or is forbidden."""
    if table not in ALLOWED_COLUMNS:
        raise ValueError(f"table not in metadata allowlist: {table}")
    allowed = ALLOWED_COLUMNS[table]
    out: list[str] = []
    for column in columns:
        if column in FORBIDDEN_COLUMNS or column not in allowed:
            raise ValueError(f"column not in metadata allowlist: {column}")
        out.append(column)
    return out


def select_sql(table: str, columns: Sequence[str], tail: str = "") -> str:
    """Build a SELECT from allowed metadata columns only."""
    return f"SELECT {', '.join(_metadata(table, columns))} FROM {table}{tail}"  # noqa: S608


def _aggregate(
    table: str,
    group: Sequence[str],
    sums: Sequence[str],
    tail: str = "",
) -> str:
    """Build an aggregate SELECT whose group and summed columns are allowlisted."""
    checked_group = _metadata(table, group)
    checked_sums = _metadata(table, sums)
    parts = list(checked_group) + [f"SUM({name}) AS {name}" for name in checked_sums]
    parts.append("COUNT(*) AS rows")
    sql = f"SELECT {', '.join(parts)} FROM {table}{tail}"  # noqa: S608
    if checked_group:
        sql += f" GROUP BY {', '.join(checked_group)}"
    return sql


def connect_readonly(path: Path) -> sqlite3.Connection:
    """Open a SQLite database read-only; a write must fail at SQLite itself."""
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _rows(connection: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql)]


def _sum_or_zero(value: Any) -> int:
    return int(value or 0)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def percentile(values: Sequence[float], quantile: float) -> float | None:
    """Nearest-rank percentile; no interpolation and no time-averaging."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _summary(
    groups: Mapping[tuple[Any, ...], list[float]],
    names: Sequence[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in sorted(groups, key=lambda item: tuple(str(part) for part in item)):
        values = groups[key]
        row = dict(zip(names, key, strict=True))
        row["p50"] = percentile(values, 0.5)
        row["p95"] = percentile(values, 0.95)
        row["samples"] = len(values)
        out.append(row)
    return out


def router_snapshot(db: Path) -> dict[str, Any]:
    """Read OmniRoute's metadata tables through a read-only connection."""
    try:
        connection = connect_readonly(db)
    except sqlite3.Error as exc:
        return {"path": str(db), "available": False, "error": type(exc).__name__}
    try:
        calls = _rows(connection, CALL_LOG_SQL)
        quotas = _rows(connection, QUOTA_SQL)
        spend = _rows(connection, COST_SQL)
        connections = _rows(connection, CONNECTION_SQL)
        breakers = _rows(connection, BREAKER_SQL)
        resets = _rows(connection, RESET_SQL)
        leases = _rows(connection, LEASE_SQL)
    except sqlite3.Error as exc:
        return {"path": str(db), "available": False, "error": type(exc).__name__}
    finally:
        connection.close()

    ttft: dict[tuple[Any, ...], list[float]] = {}
    durations: dict[tuple[Any, ...], list[float]] = {}
    queue: dict[tuple[Any, ...], list[float]] = {}
    reasoning: dict[tuple[Any, ...], list[float]] = {}
    decode: dict[tuple[Any, ...], list[float]] = {}
    statuses: Counter[str] = Counter()
    providers: Counter[str] = Counter()
    for row in calls:
        provider = str(row["provider"] or "unknown")
        model = str(row["model"] or "unknown")
        key = (provider, model)
        statuses[str(row["status"])] += 1
        providers[provider] += 1
        ttft_ms = _number(row["ttft_ms"])
        duration_ms = _number(row["duration"])
        tokens_out = _number(row["tokens_out"])
        if ttft_ms is not None and ttft_ms >= 0:
            ttft.setdefault(key, []).append(ttft_ms)
        if duration_ms is not None and duration_ms >= 0:
            durations.setdefault(key, []).append(duration_ms)
        queue_wait = _number(row["queue_wait_ms"])
        if queue_wait is not None and queue_wait >= 0:
            queue.setdefault(key, []).append(queue_wait)
        reasoning_ms = _number(row["reasoning_duration_ms"])
        if reasoning_ms is not None and reasoning_ms >= 0:
            reasoning.setdefault(key, []).append(reasoning_ms)
        if (
            ttft_ms is not None
            and duration_ms is not None
            and tokens_out is not None
            and duration_ms > ttft_ms
        ):
            decode.setdefault(key, []).append(tokens_out / ((duration_ms - ttft_ms) / 1000))

    spend_by: Counter[tuple[str, str]] = Counter()
    for row in spend:
        amount = _number(row["amount_usd"])
        if amount is not None:
            spend_by[(str(row["provider"] or "unknown"), str(row["model"] or "unknown"))] += amount

    reset_counts: Counter[tuple[str, str, str]] = Counter()
    for row in resets:
        reset_counts[
            (
                str(row["provider"] or "unknown"),
                str(row["connection_id"] or "unknown"),
                str(row["window_key"] or "unknown"),
            )
        ] += 1

    lease_counts: Counter[tuple[str, str]] = Counter()
    for row in leases:
        lease_counts[(str(row["provider"] or "unknown"), str(row["state"] or "unknown"))] += 1

    return {
        "path": str(db),
        "available": True,
        "calls": {
            "count": len(calls),
            "by_status": dict(sorted(statuses.items())),
            "by_provider": dict(sorted(providers.items())),
        },
        "percentiles": {
            "ttft_ms": _summary(ttft, ("provider", "model")),
            "duration_ms": _summary(durations, ("provider", "model")),
            "queue_wait_ms": _summary(queue, ("provider", "model")),
            "reasoning_duration_ms": _summary(reasoning, ("provider", "model")),
            "decode_tokens_per_second": _summary(decode, ("provider", "model")),
        },
        "quota": quotas,
        "spend": [
            {"provider": key[0], "model": key[1], "usd": amount}
            for key, amount in sorted(spend_by.items())
        ],
        "connections": connections,
        "circuit_breakers": breakers,
        "quota_resets": [
            {
                "provider": key[0],
                "connection_id": key[1],
                "window_key": key[2],
                "count": count,
            }
            for key, count in sorted(reset_counts.items())
        ],
        "leases": [
            {"provider": key[0], "state": key[1], "count": count}
            for key, count in sorted(lease_counts.items())
        ],
    }


# ---------------------------------------------------------------------------
# dsh v4 stream timings


def decompress_zstd(data: bytes) -> bytes:
    """Decompress a v4 session frame with whatever the host already provides."""
    try:
        from compression import zstd  # Python 3.14 stdlib
    except ImportError:
        pass
    else:
        return zstd.decompress(data)
    try:
        import zstandard  # type: ignore[import-not-found]
    except ImportError:
        pass
    else:
        return zstandard.ZstdDecompressor().decompress(data)
    node = shutil.which("node")
    if node:
        script = (
            "const fs=require('fs'),z=require('zlib');"
            "process.stdout.write(z.zstdDecompressSync(fs.readFileSync(0)));"
        )
        result = subprocess.run(
            [node, "-e", script],
            input=data,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout
    raise RuntimeError("no zstd decompressor available")


def _stream_bounds(stream: Sequence[Any]) -> tuple[float | None, float | None]:
    first: float | None = None
    last: float | None = None
    for entry in stream:
        if not isinstance(entry, dict):
            continue
        start = entry.get("time", entry.get("time0"))
        end = entry.get("time")
        if end is None and entry.get("time0") is not None and isinstance(entry.get("dt"), list):
            delta = [value for value in entry["dt"] if isinstance(value, (int, float))]
            end = entry["time0"] + (sum(delta) if delta else 0)
        if isinstance(start, (int, float)) and (first is None or start < first):
            first = float(start)
        if isinstance(end, (int, float)) and (last is None or end > last):
            last = float(end)
    return first, last


def read_dsh_session(path: Path) -> dict[str, Any]:
    """Return per-message stream timings and token totals from one v4 session."""
    payload = path.read_bytes()
    if path.suffix == ".zstd":
        payload = decompress_zstd(payload)
    starts: dict[tuple[Any, Any], float] = {}
    calls: list[dict[str, Any]] = []
    tokens: Counter[str] = Counter()
    provider = "unknown"
    model = "unknown"
    effort = "unknown"
    for line in payload.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if kind == "model/selection":
            provider = str(data.get("provider") or provider)
            model = str(data.get("model") or model)
            effort = str(data.get("reasoningEffort") or effort)
        elif kind == "step/start":
            time = event.get("time")
            if isinstance(time, (int, float)):
                starts[(data.get("turn"), data.get("step"))] = float(time)
        elif kind == "assistant/message":
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            input_tokens = int(usage.get("inputTokens") or 0)
            output_tokens = int(usage.get("outputTokens") or 0)
            cache_read = int(usage.get("cacheReadTokens") or 0)
            cache_write = int(usage.get("cacheWriteTokens") or 0)
            tokens.update(
                {
                    "input": input_tokens,
                    "output": output_tokens,
                    "cache_read": cache_read,
                    "cache_write": cache_write,
                }
            )
            stream = data.get("stream")
            if not isinstance(stream, list) or not stream:
                continue
            first, last = _stream_bounds(stream)
            start = starts.get((data.get("turn"), data.get("step")))
            if first is None or start is None or first < start:
                continue
            decode_ms = (last - first) if last is not None and last >= first else None
            calls.append(
                {
                    "ttft_ms": first - start,
                    "decode_ms": decode_ms,
                    "output_tokens": output_tokens,
                    "decode_tokens_per_second": (
                        output_tokens / (decode_ms / 1000) if decode_ms else None
                    ),
                }
            )
    return {
        "path": str(path),
        "provider": provider,
        "model": model,
        "effort": effort,
        "calls": calls,
        "tokens": dict(tokens),
    }


def deepseek_cost(
    tokens: Mapping[str, int], params: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Published peak rates converted with the registry's dated CNY constant."""
    cny_per_usd = float(params["deepseek_cny_per_usd"]["value"])
    input_rate = float(params["deepseek_input_usd_per_mtok"]["value"])
    output_rate = float(params["deepseek_output_usd_per_mtok"]["value"])
    cache_rate = float(params["deepseek_cache_read_usd_per_mtok"]["value"])
    usd = (
        tokens.get("input", 0) * input_rate
        + tokens.get("output", 0) * output_rate
        + tokens.get("cache_read", 0) * cache_rate
    ) / 1_000_000
    return {
        "usd": usd,
        "cny": usd * cny_per_usd,
        "cny_per_usd": cny_per_usd,
        "cny_per_usd_source": str(params["deepseek_cny_per_usd"]["source"]),
        "calibration": str(params["deepseek_cny_per_usd"]["calibration"]),
    }


def dsh_snapshot(root: Path, params: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    files = sorted(root.glob("sessions/*/*/session.v4.jsonl*"))
    if not files:
        return {
            "root": str(root),
            "available": False,
            "error": "no session.v4 logs",
            "sessions": 0,
            "calls": 0,
            "by_model": [],
            "deepseek": None,
        }
    ttft: dict[tuple[Any, ...], list[float]] = {}
    decode: dict[tuple[Any, ...], list[float]] = {}
    tokens_by_model: dict[tuple[str, str], Counter[str]] = {}
    unreadable = 0
    parsed = 0
    calls = 0
    for path in files:
        try:
            session = read_dsh_session(path)
        except (OSError, RuntimeError, ValueError):
            unreadable += 1
            continue
        parsed += 1
        key = (str(session["model"]), str(session["effort"]))
        tokens_by_model.setdefault(key, Counter()).update(session["tokens"])
        for call in session["calls"]:
            calls += 1
            ttft.setdefault(key, []).append(float(call["ttft_ms"]))
            if call["decode_tokens_per_second"] is not None:
                decode.setdefault(key, []).append(float(call["decode_tokens_per_second"]))
    if not parsed:
        return {
            "root": str(root),
            "available": False,
            "error": "no readable session.v4 logs",
            "sessions": 0,
            "calls": 0,
            "by_model": [],
            "deepseek": None,
        }
    by_model: list[dict[str, Any]] = []
    for key in sorted(tokens_by_model, key=lambda item: tuple(str(part) for part in item)):
        model, effort = key
        tokens = tokens_by_model[key]
        by_model.append(
            {
                "model": model,
                "effort": effort,
                "ttft_ms": {
                    "p50": percentile(ttft.get(key, []), 0.5),
                    "p95": percentile(ttft.get(key, []), 0.95),
                    "samples": len(ttft.get(key, [])),
                },
                "decode_tokens_per_second": {
                    "p50": percentile(decode.get(key, []), 0.5),
                    "p95": percentile(decode.get(key, []), 0.95),
                    "samples": len(decode.get(key, [])),
                },
                "tokens": dict(tokens),
            }
        )
    total_deepseek = Counter[str]()
    for key, tokens in tokens_by_model.items():
        if key[0].startswith("deepseek"):
            total_deepseek.update(tokens)
    cost = deepseek_cost(total_deepseek, params) if sum(total_deepseek.values()) else None
    return {
        "root": str(root),
        "available": True,
        "sessions": parsed,
        "calls": calls,
        "unreadable": unreadable,
        "by_model": by_model,
        "deepseek": cost,
    }


# ---------------------------------------------------------------------------
# Orca CLI: fixed metadata commands only


def orca_allowed(command: Sequence[str]) -> bool:
    candidate = tuple(command)
    if candidate not in ORCA_COMMANDS:
        return False
    return not any(candidate[: len(prefix)] == prefix for prefix in FORBIDDEN_ORCA)


def run_orca(command: Sequence[str], binary: Path, timeout: int = 20) -> Any:
    """Run one allowlisted Orca metadata command and parse its JSON output."""
    if not orca_allowed(command):
        raise ValueError(f"Orca command is not metadata-only: {' '.join(command)}")
    result = subprocess.run(
        [str(binary), *command],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"orca exited {result.returncode}")
    text = result.stdout.strip()
    return json.loads(text) if text else None


def _count(payload: Any) -> int | None:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in (
            "worktrees",
            "terminals",
            "tasks",
            "workers",
            "gates",
            "sessions",
            "items",
            "rows",
            "results",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        for key in ("count", "total"):
            value = payload.get(key)
            if isinstance(value, int):
                return value
    return None


def orca_snapshot(binary: Path | None) -> dict[str, Any]:
    if binary is None:
        return {"binary": None, "available": False, "error": "no orca cli", "commands": {}}
    commands: dict[str, Any] = {}
    for command in ORCA_COMMANDS:
        key = " ".join(command)
        try:
            payload = run_orca(command, binary)
        except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            commands[key] = {"ok": False, "error": type(exc).__name__, "count": None}
            continue
        ready = payload.get("ready") if isinstance(payload, dict) else None
        commands[key] = {
            "ok": True,
            "count": _count(payload),
            "ready": ready if isinstance(ready, bool) else None,
        }
    return {"binary": str(binary), "available": True, "commands": commands}


# ---------------------------------------------------------------------------
# AO SQLite and its opt-out state


def ao_telemetry(
    ao_dir: Path,
    launcher: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    environment = os.environ if env is None else env
    launcher = AO_LAUNCHER if launcher is None else launcher
    try:
        opt_out_file = (ao_dir / "telemetry_opt_out").read_text().strip() == "1"
    except OSError:
        opt_out_file = False
    try:
        policy = json.loads((ao_dir / "telemetry_policy.json").read_text())
    except (OSError, json.JSONDecodeError):
        policy = {}
    events_enabled = policy.get("events_enabled") if isinstance(policy, dict) else None
    try:
        launcher_off = "AO_TELEMETRY_REMOTE=off" in launcher.read_text()
    except OSError:
        launcher_off = False
    remote = environment.get("AO_TELEMETRY_REMOTE", "off").strip().lower()
    effective = opt_out_file and events_enabled is False and launcher_off and remote == "off"
    return {
        "opt_out_file": opt_out_file,
        "policy_events_enabled": events_enabled,
        "launcher_remote_off": launcher_off,
        "env_remote": remote,
        "effective": effective,
    }


def ao_snapshot(
    db: Path,
    ao_dir: Path,
    launcher: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    telemetry = ao_telemetry(ao_dir, launcher, env)
    base: dict[str, Any] = {
        "path": str(db),
        "available": False,
        "telemetry": telemetry,
    }
    try:
        connection = connect_readonly(db)
    except sqlite3.Error as exc:
        base["error"] = type(exc).__name__
        return base
    try:
        sessions = _rows(connection, AO_SESSIONS_SQL)
        models = _rows(connection, AO_MODELS_SQL)
        usage = _rows(connection, AO_USAGE_SQL)
        prs = _rows(connection, AO_PR_SQL)
        checks = _rows(connection, AO_CHECKS_SQL)
        reviews = _rows(connection, AO_REVIEWS_SQL)
        threads = _rows(connection, AO_THREADS_SQL)
        measurements = _rows(connection, AO_MEASUREMENTS_SQL)
        session_telemetry = _rows(connection, AO_TELEMETRY_SQL)
    except sqlite3.Error as exc:
        base["error"] = type(exc).__name__
        return base
    finally:
        connection.close()
    base.update(
        {
            "available": True,
            "sessions": sessions,
            "models": models,
            "usage": usage,
            "prs": prs,
            "checks": checks,
            "reviews": reviews,
            "threads": threads,
            "measurements": measurements[0] if measurements else {},
            "session_telemetry": session_telemetry[0] if session_telemetry else {},
        }
    )
    return base


# ---------------------------------------------------------------------------
# Registry and snapshot assembly


def load_params(path: Path = PARAMS) -> dict[str, dict[str, Any]]:
    rows = json.loads(path.read_text())
    if not isinstance(rows, list):
        raise ValueError("parameter registry must be a list")
    params = {str(row["name"]): row for row in rows if isinstance(row, dict) and "name" in row}
    for name in DEEPSEEK_REQUIRED:
        if name not in params:
            raise ValueError(f"parameter registry is missing {name}")
        if not params[name].get("source"):
            raise ValueError(f"parameter registry row {name} has no source")
        if params[name].get("calibration") != "UNCALIBRATED":
            raise ValueError(f"parameter registry row {name} is not UNCALIBRATED")
    cny = params["deepseek_cny_per_usd"]["value"]
    if not isinstance(cny, (int, float)) or cny <= 0:
        raise ValueError("deepseek_cny_per_usd must be a positive number")
    endpoint = params["monitor_otlp_endpoint"]["value"]
    if not isinstance(endpoint, str):
        raise ValueError("monitor_otlp_endpoint must be a string")
    check_endpoint(endpoint)
    return params


def default_paths() -> dict[str, Path | None]:
    home = Path.home()
    router_candidates = [
        Path(value) if (value := os.environ.get("SEXTANT_OMNIROUTE_DB")) else None,
        home / ".local" / "share" / "sextant" / "omniroute" / "storage.sqlite",
        home / ".local" / "share" / "sextant-lane-runtimes" / "router-data" / "storage.sqlite",
    ]
    router = next(
        (candidate for candidate in router_candidates if candidate and candidate.exists()),
        next(candidate for candidate in router_candidates if candidate is not None),
    )
    ao_value = os.environ.get("SEXTANT_AO_DB")
    ao_db = Path(ao_value) if ao_value else home / ".ao" / "data" / "ao.db"
    dsh_value = os.environ.get("DSH_HOME")
    dsh_root = Path(dsh_value) if dsh_value else home / ".dsh-enhanced"
    orca_value = os.environ.get("SEXTANT_ORCA")
    orca = Path(orca_value) if orca_value else home / ".config" / "orca" / "cli" / "bin" / "orca"
    if not orca.exists():
        found = shutil.which("orca")
        orca = Path(found) if found else None
    return {"router_db": router, "ao_db": ao_db, "dsh_root": dsh_root, "orca": orca}


def snapshot(
    paths: Mapping[str, Path | None] | None = None,
    params: Mapping[str, Mapping[str, Any]] | None = None,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    chosen = default_paths() if paths is None else dict(paths)
    registry = load_params() if params is None else dict(params)
    router = (
        router_snapshot(chosen["router_db"])
        if chosen.get("router_db") is not None
        else {"path": None, "available": False, "error": "no router database"}
    )
    dsh = (
        dsh_snapshot(chosen["dsh_root"], registry)
        if chosen.get("dsh_root")
        else {
            "root": None,
            "available": False,
            "error": "no dsh home",
            "sessions": 0,
            "calls": 0,
            "by_model": [],
            "deepseek": None,
        }
    )
    orca = orca_snapshot(chosen.get("orca"))
    ao_db = chosen.get("ao_db")
    ao = (
        ao_snapshot(ao_db, ao_db.parent, env=env)
        if ao_db is not None
        else {
            "path": None,
            "available": False,
            "error": "no AO database",
            "telemetry": ao_telemetry(Path("."), env=env),
        }
    )
    return {
        "generated_at": (now or utc_now()).isoformat(),
        "window": "all",
        "sources": {
            "router": {"path": router.get("path"), "available": router.get("available")},
            "dsh": {"root": dsh.get("root"), "available": dsh.get("available")},
            "orca": {"binary": orca.get("binary"), "available": orca.get("available")},
            "ao": {"path": ao.get("path"), "available": ao.get("available")},
        },
        "router": router,
        "dsh": dsh,
        "orca": orca,
        "ao": ao,
    }


# ---------------------------------------------------------------------------
# OTLP/HTTP JSON, loopback only


def _moment(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def metric_rows(
    snap: Mapping[str, Any],
    params: Mapping[str, Mapping[str, Any]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current = now or utc_now()

    def add(name: str, value: Any, attributes: Mapping[str, Any], unit: str = "1") -> None:
        number = _number(value)
        if number is None:
            return
        rows.append({"name": name, "value": number, "unit": unit, "attributes": dict(attributes)})

    router = snap.get("router", {})
    if router.get("available"):
        for status, count in router["calls"]["by_status"].items():
            add("sextant.router.call.count", count, {"status": status})
        for provider, count in router["calls"]["by_provider"].items():
            add("sextant.router.call.count", count, {"provider": provider})
        units = {
            "ttft_ms": "ms",
            "duration_ms": "ms",
            "queue_wait_ms": "ms",
            "reasoning_duration_ms": "ms",
            "decode_tokens_per_second": "1/s",
        }
        for metric, unit in units.items():
            for row in router["percentiles"][metric]:
                attributes = {"provider": row["provider"], "model": row["model"]}
                add(
                    f"sextant.router.call.{metric}",
                    row["p50"],
                    {**attributes, "quantile": "0.50"},
                    unit,
                )
                add(
                    f"sextant.router.call.{metric}",
                    row["p95"],
                    {**attributes, "quantile": "0.95"},
                    unit,
                )
        for row in router["quota"]:
            add(
                "sextant.router.quota.remaining",
                row["remaining_percentage"],
                {
                    "provider": row["provider"],
                    "connection_id": row["connection_id"],
                    "window_key": row["window_key"],
                    "exhausted": row["is_exhausted"],
                },
                "%",
            )
        for row in router["spend"]:
            add(
                "sextant.router.cost.usd.notional",
                row["usd"],
                {"provider": row["provider"], "model": row["model"], "basis": "catalog"},
                "USD",
            )
        for row in router["connections"]:
            until = row["rate_limited_until"]
            moment = _moment(until)
            add(
                "sextant.router.connection.rate_limited",
                1 if moment is not None and moment > current else 0,
                {
                    "provider": row["provider"],
                    "connection_id": row["id"],
                    "active": row["is_active"],
                    "until": until or "none",
                },
            )
        breaker_state = {"CLOSED": 0, "OPEN": 1, "HALF_OPEN": 2}
        for row in router["circuit_breakers"]:
            state = str(row["state"] or "unknown")
            add(
                "sextant.router.circuit_breaker.state",
                breaker_state.get(state, -1),
                {"name": row["name"], "state": state},
            )
        for row in router["quota_resets"]:
            add(
                "sextant.router.quota_reset.count",
                row["count"],
                {
                    "provider": row["provider"],
                    "connection_id": row["connection_id"],
                    "window_key": row["window_key"],
                },
            )
        for row in router["leases"]:
            add(
                "sextant.router.lease.count",
                row["count"],
                {"provider": row["provider"], "state": row["state"]},
            )

    dsh = snap.get("dsh", {})
    if dsh.get("available"):
        for row in dsh["by_model"]:
            attributes = {"model": row["model"], "effort": row["effort"]}
            add(
                "sextant.dsh.call.ttft_ms",
                row["ttft_ms"]["p50"],
                {**attributes, "quantile": "0.50"},
                "ms",
            )
            add(
                "sextant.dsh.call.ttft_ms",
                row["ttft_ms"]["p95"],
                {**attributes, "quantile": "0.95"},
                "ms",
            )
            add(
                "sextant.dsh.call.decode_tokens_per_second",
                row["decode_tokens_per_second"]["p50"],
                {**attributes, "quantile": "0.50"},
                "1/s",
            )
            add(
                "sextant.dsh.call.decode_tokens_per_second",
                row["decode_tokens_per_second"]["p95"],
                {**attributes, "quantile": "0.95"},
                "1/s",
            )
            for kind, count in row["tokens"].items():
                add("sextant.dsh.tokens", count, {**attributes, "kind": kind}, "tokens")
        deepseek = dsh.get("deepseek")
        if deepseek:
            add(
                "sextant.dsh.deepseek.cost.usd.notional",
                deepseek["usd"],
                {"basis": "published-peak", "calibration": deepseek["calibration"]},
                "USD",
            )
            add(
                "sextant.dsh.deepseek.cost.cny.notional",
                deepseek["cny"],
                {
                    "basis": "published-peak",
                    "calibration": deepseek["calibration"],
                    "cny_per_usd": deepseek["cny_per_usd"],
                },
                "CNY",
            )

    orca = snap.get("orca", {})
    for command, result in orca.get("commands", {}).items():
        add("sextant.orca.command.ok", 1 if result["ok"] else 0, {"command": command})
        if result["count"] is not None:
            add("sextant.orca.command.count", result["count"], {"command": command})

    ao = snap.get("ao", {})
    if ao.get("telemetry"):
        add(
            "sextant.ao.telemetry.opt_out",
            1 if ao["telemetry"]["effective"] else 0,
            {"basis": "file+policy+env"},
        )
    if ao.get("available"):
        for row in ao["sessions"]:
            add(
                "sextant.ao.session.count",
                row["rows"],
                {
                    "harness": row["harness"],
                    "kind": row["kind"],
                    "activity_state": row["activity_state"],
                },
            )
        for row in ao["models"]:
            add(
                "sextant.ao.model.count",
                row["rows"],
                {"model": row["model"], "effort": row["effort"]},
            )
        for row in ao["usage"]:
            attributes = {
                "provider": row["provider_id"],
                "model": row["model_id"],
                "measurement_kind": row["usage_measurement_kind"],
            }
            for kind in ("input", "cached_input", "uncached_input", "output"):
                add(
                    "sextant.ao.tokens",
                    row[f"{kind}_tokens"],
                    {**attributes, "kind": kind},
                    "tokens",
                )
            add(
                "sextant.ao.cost.nanos.notional",
                row["estimated_cost_nanos"],
                attributes,
                "nanos",
            )
        for row in ao["prs"]:
            add(
                "sextant.ao.pr.count",
                row["rows"],
                {
                    "pr_state": row["pr_state"],
                    "ci_state": row["ci_state"],
                    "review_decision": row["review_decision"],
                },
            )
        for row in ao["checks"]:
            add("sextant.ao.pr_check.count", row["rows"], {"status": row["status"]})
        for row in ao["reviews"]:
            add(
                "sextant.ao.pr_review.count",
                row["rows"],
                {"state": row["state"], "is_bot": row["is_bot"]},
            )
        for row in ao["threads"]:
            add("sextant.ao.review_thread.count", row["rows"], {"resolved": row["resolved"]})
        measurements = ao.get("measurements") or {}
        for key in (
            "historical",
            "historical_merged",
            "associated_reported",
            "merged_reported",
            "closed_reported",
        ):
            add("sextant.ao.pr_measurement", measurements.get(key), {"kind": key}, "PRs")
        session_telemetry = ao.get("session_telemetry") or {}
        add(
            "sextant.ao.waiting_input.count",
            session_telemetry.get("waiting_input_count"),
            {},
        )

    return rows


def otlp_payload(rows: Sequence[Mapping[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    stamp = str(int((now or utc_now()).timestamp() * 1_000_000_000))
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        attributes = [
            {"key": str(key), "value": {"stringValue": str(value)}}
            for key, value in sorted(row["attributes"].items())
        ]
        point = {
            "asDouble": float(row["value"]),
            "timeUnixNano": stamp,
            "attributes": attributes,
        }
        grouped.setdefault((str(row["name"]), str(row["unit"])), []).append(point)
    metrics = [
        {"name": name, "unit": unit, "gauge": {"dataPoints": points}}
        for (name, unit), points in sorted(grouped.items())
    ]
    return {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": "sextant-monitor-l3-l4"},
                        }
                    ]
                },
                "scopeMetrics": [
                    {
                        "scope": {"name": "sextant.monitor.l3_l4"},
                        "metrics": metrics,
                    }
                ],
            }
        ]
    }


def check_endpoint(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in LOOPBACK:
        raise ValueError("OTLP endpoint must be a loopback http(s) URL")
    return url


def emit_otlp(
    rows: Sequence[Mapping[str, Any]],
    url: str = DEFAULT_OTLP,
    now: datetime | None = None,
) -> int:
    check_endpoint(url)
    payload = otlp_payload(rows, now)
    request = urllib.request.Request(  # noqa: S310
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as reply:  # noqa: S310
        return int(getattr(reply, "status", 0) or 0)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    params = load_params()
    endpoint = str(params["monitor_otlp_endpoint"]["value"])
    parser = argparse.ArgumentParser(description="Read-only L3/L4 monitor bridge")
    parser.add_argument("--write", type=Path, help="write the JSON snapshot here")
    parser.add_argument(
        "--otlp",
        nargs="?",
        const=endpoint,
        help=f"emit OTLP/HTTP JSON to this loopback URL (default {endpoint})",
    )
    args = parser.parse_args(argv)
    snap = snapshot(params=params)
    text = json.dumps(snap, indent=2, sort_keys=True)
    if args.write:
        _write(args.write, text)
    else:
        print(text)
    if args.otlp:
        rows = metric_rows(snap, params)
        status = emit_otlp(rows, args.otlp)
        print(f"otlp {len(rows)} points, http {status}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
