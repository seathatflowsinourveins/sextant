"""The monitor bridge reads L3/L4 metadata only, read-only, and never a body or prompt."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "monitor_l3_l4", ROOT / "scripts" / "monitor_l3_l4.py"
)
assert SPEC and SPEC.loader
mon = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mon)

NOW = datetime(2026, 11, 9, 4, 0, tzinfo=UTC)


def _router_db(path: Path) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE call_logs (
            id INTEGER PRIMARY KEY,
            timestamp TEXT, model TEXT, provider TEXT, status INTEGER,
            error_type TEXT, duration INTEGER, ttft_ms INTEGER,
            queue_wait_ms INTEGER, reasoning_duration_ms INTEGER,
            tokens_in INTEGER, tokens_out INTEGER,
            reasoning_effort_upstream TEXT, detail_state TEXT,
            request_summary TEXT, artifact_relpath TEXT, artifact_sha256 TEXT,
            has_request_body INTEGER, client_session_id TEXT
        );
        CREATE TABLE quota_snapshots (
            id INTEGER PRIMARY KEY, provider TEXT, connection_id TEXT,
            window_key TEXT, remaining_percentage REAL, is_exhausted INTEGER,
            next_reset_at TEXT, window_duration_ms INTEGER, raw_data TEXT,
            created_at TEXT
        );
        CREATE TABLE request_cost_ledger (
            id INTEGER PRIMARY KEY, timestamp TEXT, provider TEXT, model TEXT,
            tokens_input INTEGER, tokens_output INTEGER, tokens_cache_read INTEGER,
            tokens_cache_creation INTEGER, unit_price_input REAL,
            unit_price_output REAL, amount_usd REAL, service_tier TEXT,
            success INTEGER
        );
        CREATE TABLE provider_connections (
            id TEXT PRIMARY KEY, provider TEXT, display_name TEXT, is_active INTEGER,
            rate_limited_until TEXT, last_used_at TEXT, priority INTEGER,
            access_token TEXT, refresh_token TEXT, api_key TEXT, email TEXT
        );
        CREATE TABLE domain_circuit_breakers (
            name TEXT PRIMARY KEY, state TEXT, failure_count INTEGER,
            last_failure_time TEXT, options TEXT
        );
        CREATE TABLE provider_quota_reset_events (
            id INTEGER PRIMARY KEY, provider TEXT, connection_id TEXT,
            window_key TEXT, window_resets_at TEXT, observed_at TEXT,
            new_remaining_percentage REAL, raw_data TEXT
        );
        CREATE TABLE exclusive_connection_leases (
            id INTEGER PRIMARY KEY, provider TEXT, connection_id TEXT, state TEXT,
            expires_at TEXT, lease_owner_hash TEXT
        );
        CREATE TABLE request_detail_logs (
            id INTEGER PRIMARY KEY, call_log_id INTEGER, timestamp TEXT,
            client_request TEXT, client_response TEXT
        );
        """
    )
    connection.executemany(
        "INSERT INTO call_logs (timestamp, model, provider, status, duration, ttft_ms,"
        " queue_wait_ms, reasoning_duration_ms, tokens_in, tokens_out,"
        " reasoning_effort_upstream, detail_state, request_summary, artifact_relpath,"
        " artifact_sha256, has_request_body) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                "2026-11-09T03:00:00Z",
                "gpt-6.1-sol",
                "codex",
                200,
                2000,
                500,
                10,
                100,
                1000,
                500,
                "max",
                "ready",
                "CANARY_SUMMARY",
                "CANARY_ARTIFACT",
                "CANARY_SHA",
                1,
            ),
            (
                "2026-11-09T03:05:00Z",
                "gemini-3.8-flash",
                "agy",
                429,
                None,
                None,
                None,
                None,
                0,
                0,
                None,
                "absent",
                None,
                None,
                None,
                0,
            ),
        ],
    )
    connection.executemany(
        "INSERT INTO quota_snapshots (provider, connection_id, window_key,"
        " remaining_percentage, is_exhausted, next_reset_at, window_duration_ms,"
        " raw_data, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (
                "codex",
                "c1",
                "weekly",
                10.0,
                0,
                "2026-11-11T00:00:00Z",
                604800000,
                "CANARY_RAW",
                "2026-11-09T00:00:00Z",
            ),
            (
                "codex",
                "c1",
                "weekly",
                90.0,
                0,
                "2026-11-11T00:00:00Z",
                604800000,
                None,
                "2026-11-09T01:00:00Z",
            ),
            (
                "codex",
                "c1",
                "weekly",
                95.0,
                0,
                "2026-11-11T00:00:00Z",
                604800000,
                None,
                "2026-11-09T01:00:00Z",
            ),
            (
                "agy",
                "c2",
                "gemini_session",
                50.0,
                0,
                "2026-11-09T05:00:00Z",
                3600000,
                None,
                "2026-11-09T02:00:00Z",
            ),
        ],
    )
    connection.executemany(
        "INSERT INTO request_cost_ledger (timestamp, provider, model, tokens_input,"
        " tokens_output, tokens_cache_read, tokens_cache_creation, unit_price_input,"
        " unit_price_output, amount_usd, service_tier, success) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                "2026-11-09T03:00:00Z",
                "codex",
                "gpt-6.1-sol",
                1000,
                500,
                0,
                0,
                0.3,
                1.2,
                1.5,
                "default",
                1,
            ),
            (
                "2026-11-09T03:05:00Z",
                "agy",
                "gemini-3.8-flash",
                10,
                10,
                0,
                0,
                0,
                0,
                0.5,
                "default",
                1,
            ),
        ],
    )
    connection.execute(
        "INSERT INTO provider_connections (id, provider, display_name, is_active,"
        " rate_limited_until, last_used_at, priority, access_token, refresh_token,"
        " api_key, email) VALUES ('c1','codex','Codex',1,'2026-11-09T05:00:00Z',"
        " '2026-11-09T03:00:00Z',1,'CANARY_TOKEN','CANARY_REFRESH','CANARY_KEY','x@y')"
    )
    connection.execute(
        "INSERT INTO domain_circuit_breakers (name, state, failure_count,"
        " last_failure_time, options) VALUES ('codex','OPEN',3,'2026-11-09T03:10:00Z','x')"
    )
    connection.execute(
        "INSERT INTO provider_quota_reset_events (provider, connection_id, window_key,"
        " window_resets_at, observed_at, new_remaining_percentage, raw_data)"
        " VALUES ('codex','c1','weekly','2026-11-11T00:00:00Z','2026-11-09T01:00:00Z',90.0,'x')"
    )
    connection.execute(
        "INSERT INTO exclusive_connection_leases (provider, connection_id, state,"
        " expires_at, lease_owner_hash) VALUES ('codex','c1','active',"
        " '2026-11-09T05:00:00Z','x')"
    )
    connection.execute(
        "INSERT INTO request_detail_logs (call_log_id, timestamp, client_request,"
        " client_response) VALUES (1,'2026-11-09T03:00:00Z','CANARY_BODY','CANARY_REPLY')"
    )
    connection.commit()
    connection.close()
    return path


def _ao_db(path: Path) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, num INTEGER, issue_id TEXT, kind TEXT, harness TEXT,
            activity_state TEXT, activity_last_at TEXT, is_terminated INTEGER,
            branch TEXT, created_at TEXT, updated_at TEXT, model TEXT, effort TEXT,
            terminated_at TEXT, session_mode TEXT, prompt TEXT,
            latest_user_prompt TEXT, latest_assistant_update TEXT
        );
        CREATE TABLE model_usage_events (
            id INTEGER PRIMARY KEY, provider_id TEXT, model_id TEXT,
            usage_measurement_kind TEXT, input_tokens INTEGER,
            cached_input_tokens INTEGER, uncached_input_tokens INTEGER,
            output_tokens INTEGER, created_at TEXT, input_cost_nanos INTEGER,
            cached_input_cost_nanos INTEGER, output_cost_nanos INTEGER,
            estimated_cost_nanos INTEGER, pricing_version TEXT,
            provider_usage_json TEXT
        );
        CREATE TABLE pr (
            url TEXT PRIMARY KEY, session_id TEXT, number INTEGER, pr_state TEXT,
            review_decision TEXT, ci_state TEXT, updated_at TEXT, head_sha TEXT,
            title TEXT, additions INTEGER, deletions INTEGER, changed_files INTEGER,
            review_partial INTEGER
        );
        CREATE TABLE pr_checks (
            pr_url TEXT, name TEXT, commit_hash TEXT, status TEXT, conclusion TEXT,
            created_at TEXT, log_tail TEXT, details TEXT
        );
        CREATE TABLE pr_reviews (
            pr_url TEXT, review_id TEXT, author TEXT, state TEXT, is_bot INTEGER,
            submitted_at TEXT, target_sha TEXT, body TEXT
        );
        CREATE TABLE pr_review_threads (
            pr_url TEXT, thread_id TEXT, path TEXT, line INTEGER, resolved INTEGER,
            is_bot INTEGER, updated_at TEXT
        );
        CREATE TABLE usage_pr_measurement (
            pr_key TEXT PRIMARY KEY, historical INTEGER, historical_merged INTEGER,
            associated_reported INTEGER, merged_reported INTEGER,
            closed_reported INTEGER, merged_via TEXT
        );
        CREATE TABLE session_telemetry (
            session_id TEXT, created_by TEXT, waiting_input_count INTEGER,
            end_claimed INTEGER
        );
        """
    )
    connection.execute(
        "INSERT INTO sessions VALUES ('s1',1,'9','worker','claude-code','active',"
        "'2026-11-09T03:00:00Z',0,'lane-x','2026-11-09T01:00:00Z',"
        "'2026-11-09T03:00:00Z','claude-opus-5-5','max',NULL,'chat',"
        "'CANARY_PROMPT','CANARY_USER','CANARY_ASSISTANT')"
    )
    connection.execute(
        "INSERT INTO model_usage_events VALUES (1,'anthropic','claude-opus-5-5',"
        "'native_reported',100,10,90,20,'2026-11-09T03:00:00Z',1,2,3,6,'v1',"
        "'CANARY_USAGE_JSON')"
    )
    connection.execute(
        "INSERT INTO pr VALUES ('https://github.com/o/r/pull/1','s1',1,'merged',"
        "'APPROVED','passed','2026-11-09T03:00:00Z','a','title',1,2,3,0)"
    )
    connection.execute(
        "INSERT INTO pr_checks VALUES ('https://github.com/o/r/pull/1','ci','a',"
        "'passed','SUCCESS','2026-11-09T03:00:00Z','CANARY_LOG','CANARY_DETAILS')"
    )
    connection.execute(
        "INSERT INTO pr_reviews VALUES ('https://github.com/o/r/pull/1','r1','bot',"
        "'APPROVED',1,'2026-11-09T03:00:00Z','a','CANARY_REVIEW_BODY')"
    )
    connection.execute(
        "INSERT INTO pr_review_threads VALUES ('https://github.com/o/r/pull/1','t1',"
        "'x.py',3,1,1,'2026-11-09T03:00:00Z')"
    )
    connection.execute("INSERT INTO usage_pr_measurement VALUES ('p1',1,1,1,1,0,'squash')")
    connection.execute("INSERT INTO session_telemetry VALUES ('s1','lead',2,0)")
    connection.commit()
    connection.close()
    return path


def _dsh_root(root: Path) -> Path:
    session = root / "sessions" / "work" / "uuid"
    session.mkdir(parents=True)
    lines = [
        {"type": "session", "version": 4, "id": "s1"},
        {
            "type": "model/selection",
            "time": 900,
            "data": {
                "provider": "deepseek-official",
                "model": "deepseek-flash",
                "reasoningEffort": "max",
            },
        },
        {"type": "step/start", "time": 1000, "data": {"turn": 1, "step": 1}},
        {
            "type": "assistant/message",
            "time": 2200,
            "data": {
                "turn": 1,
                "step": 1,
                "message": {"role": "assistant"},
                "usage": {
                    "inputTokens": 100,
                    "outputTokens": 20,
                    "cacheReadTokens": 5,
                    "cacheWriteTokens": 0,
                },
                "stream": [
                    {"type": "chunk", "time": 1100, "chunk": {}},
                    {"type": "chunk", "time": 2100, "chunk": {}},
                ],
            },
        },
        {"type": "step/start", "time": 3000, "data": {"turn": 1, "step": 2}},
        {
            "type": "assistant/message",
            "time": 3100,
            "data": {
                "turn": 1,
                "step": 2,
                "message": {"role": "assistant"},
                "usage": {
                    "inputTokens": 10,
                    "outputTokens": 5,
                    "cacheReadTokens": 0,
                    "cacheWriteTokens": 0,
                },
                "stream": [],
            },
        },
    ]
    (session / "session.v4.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return root


def _params() -> dict[str, dict[str, Any]]:
    return mon.load_params()


def test_sqlite_is_opened_with_uri_mode_ro_and_a_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _router_db(tmp_path / "storage.sqlite")
    seen: dict[str, Any] = {}
    real_connect = sqlite3.connect

    def spy(database: str, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        seen["database"] = database
        seen["uri"] = kwargs.get("uri")
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(mon.sqlite3, "connect", spy)
    connection = mon.connect_readonly(db)
    try:
        assert seen["uri"] is True
        assert seen["database"].startswith("file:")
        assert "mode=ro" in seen["database"]
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO provider_connections (id) VALUES ('x')")
    finally:
        connection.close()


def test_selects_only_allowlisted_metadata_columns(tmp_path: Path) -> None:
    snapshot = mon.router_snapshot(_router_db(tmp_path / "storage.sqlite"))
    text = json.dumps(snapshot)
    assert "CANARY" not in text
    assert snapshot["available"] is True

    for table, column in (
        ("call_logs", "request_summary"),
        ("call_logs", "artifact_sha256"),
        ("provider_connections", "access_token"),
        ("provider_connections", "email"),
        ("request_detail_logs", "client_request"),
    ):
        with pytest.raises(ValueError):
            mon.select_sql(table, (column,))

    queries = (
        mon.CALL_LOG_SQL,
        mon.QUOTA_SQL,
        mon.COST_SQL,
        mon.CONNECTION_SQL,
        mon.BREAKER_SQL,
        mon.RESET_SQL,
        mon.LEASE_SQL,
        mon.AO_SESSIONS_SQL,
        mon.AO_USAGE_SQL,
        mon.AO_PR_SQL,
        mon.AO_CHECKS_SQL,
        mon.AO_REVIEWS_SQL,
        mon.AO_THREADS_SQL,
        mon.AO_MEASUREMENTS_SQL,
        mon.AO_TELEMETRY_SQL,
    )
    for query in queries:
        lowered = query.lower()
        for forbidden in mon.FORBIDDEN_COLUMNS:
            assert forbidden not in lowered


def test_router_otlp_counts_each_call_once(tmp_path: Path) -> None:
    router = mon.router_snapshot(_router_db(tmp_path / "storage.sqlite"))
    rows = mon.metric_rows({"router": router}, _params(), NOW)
    metrics = mon.otlp_payload(rows, NOW)["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
    metric = next(metric for metric in metrics if metric["name"] == "sextant.router.call.count")
    points = metric["gauge"]["dataPoints"]
    assert sum(point["asDouble"] for point in points) == router["calls"]["count"] == 2
    assert {
        tuple(
            (attribute["key"], attribute["value"]["stringValue"])
            for attribute in point["attributes"]
        ): point["asDouble"]
        for point in points
    } == {
        (("provider", "agy"), ("status", "429")): 1.0,
        (("provider", "codex"), ("status", "200")): 1.0,
    }


def test_quota_snapshots_keep_the_latest_row_per_window(tmp_path: Path) -> None:
    snapshot = mon.router_snapshot(_router_db(tmp_path / "storage.sqlite"))
    quotas = snapshot["quota"]
    assert len(quotas) == 2
    by_key = {(row["provider"], row["connection_id"], row["window_key"]): row for row in quotas}
    codex = by_key[("codex", "c1", "weekly")]
    agy = by_key[("agy", "c2", "gemini_session")]
    assert codex["remaining_percentage"] == 95.0
    assert agy["remaining_percentage"] == 50.0
    assert sorted(row["remaining_percentage"] for row in quotas) == [50.0, 95.0]


def test_ao_telemetry_requires_the_file_policy_launcher_and_env(tmp_path: Path) -> None:
    ao_dir = tmp_path / ".ao" / "data"
    ao_dir.mkdir(parents=True)
    (ao_dir / "telemetry_opt_out").write_text("1")
    (ao_dir / "telemetry_policy.json").write_text('{"events_enabled": false}')
    launcher = tmp_path / "ao.sh"
    launcher.write_text("AO_TELEMETRY_REMOTE=off exec ao daemon\n")

    state = mon.ao_telemetry(ao_dir, launcher, env={})
    assert state["effective"] is True
    assert state["opt_out_file"] is True
    assert state["policy_events_enabled"] is False
    assert (
        mon.ao_telemetry(ao_dir, launcher, env={"AO_TELEMETRY_REMOTE": "on"})["effective"] is False
    )

    (ao_dir / "telemetry_opt_out").write_text("0")
    assert mon.ao_telemetry(ao_dir, launcher, env={})["effective"] is False
    (ao_dir / "telemetry_opt_out").write_text("1")
    (ao_dir / "telemetry_policy.json").write_text('{"events_enabled": true}')
    assert mon.ao_telemetry(ao_dir, launcher, env={})["effective"] is False
    (ao_dir / "telemetry_policy.json").write_text('{"events_enabled": false}')
    launcher.write_text("exec ao daemon\n")
    assert mon.ao_telemetry(ao_dir, launcher, env={})["effective"] is False


def _orca_stdout(command: tuple[str, ...]) -> str:
    """Mirror the pinned Orca CLI: YAML without --json, an envelope with it."""
    if command == ("status",):
        return "appRunning: true\nruntimeState: ready\n"
    envelopes: dict[tuple[str, ...], dict[str, Any]] = {
        ("status", "--json"): {
            "id": "local-status",
            "ok": True,
            "result": {"app": {"running": True}, "runtime": {"state": "ready"}},
        },
        ("worktree", "ps", "--json"): {
            "id": "worktrees",
            "ok": True,
            "result": {"worktrees": [{"path": "/a"}, {"path": "/b"}], "totalCount": 2},
        },
        ("terminal", "list", "--json"): {
            "id": "terminals",
            "ok": True,
            "result": {"terminals": [{"id": "1"}, {"id": "2"}, {"id": "3"}]},
        },
        ("orchestration", "task-list", "--json"): {
            "ok": False,
            "error": {"code": "run_required"},
        },
        ("orchestration", "worker-list", "--json"): {
            "id": "workers",
            "ok": True,
            "result": {"workers": [{"id": "1"}]},
        },
        ("orchestration", "gate-list", "--json"): {
            "ok": False,
            "error": {"code": "run_required"},
        },
        ("diagnostics", "memory", "--json"): {
            "id": "memory",
            "ok": True,
            "result": {"worktrees": [{"path": "/a"}, {"path": "/b"}]},
        },
    }
    return json.dumps(envelopes[command])


def test_orca_status_uses_the_json_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout=_orca_stdout(tuple(argv[1:])))

    monkeypatch.setattr(mon.subprocess, "run", fake_run)
    snapshot = mon.orca_snapshot(tmp_path / "orca")
    assert "status --json" in snapshot["commands"]
    assert snapshot["commands"]["status --json"]["ok"] is True
    assert snapshot["commands"]["status --json"]["ready"] is True


def test_orca_counts_unwrap_the_result_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout=_orca_stdout(tuple(argv[1:])))

    monkeypatch.setattr(mon.subprocess, "run", fake_run)
    commands = mon.orca_snapshot(tmp_path / "orca")["commands"]
    assert commands["worktree ps --json"]["count"] == 2
    assert commands["terminal list --json"]["count"] == 3
    assert commands["orchestration worker-list --json"]["count"] == 1
    assert commands["diagnostics memory --json"]["count"] == 2
    assert commands["orchestration task-list --json"] == {
        "ok": False,
        "error": "orca_not_ok",
        "count": None,
    }


def test_orca_runs_only_metadata_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for command in (
        ("search", "x"),
        ("terminal", "read", "x"),
        ("terminal", "show", "x"),
        ("terminal", "send", "x"),
    ):
        assert mon.orca_allowed(command) is False
        with pytest.raises(ValueError):
            mon.run_orca(command, tmp_path / "orca")

    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=_orca_stdout(tuple(argv[1:])))

    monkeypatch.setattr(mon.subprocess, "run", fake_run)
    snapshot = mon.orca_snapshot(tmp_path / "orca")
    assert snapshot["available"] is True
    assert len(calls) == len(mon.ORCA_COMMANDS)
    for argv in calls:
        command = tuple(argv[1:])
        assert command in mon.ORCA_COMMANDS
        assert command[0] != "search"
        assert command[:2] not in {("terminal", "read"), ("terminal", "show")}
    for command in mon.ORCA_COMMANDS:
        assert isinstance(snapshot["commands"][" ".join(command)]["ok"], bool)


@pytest.mark.parametrize("dsh_home", [None, ".dsh", ".dsh-enhanced"])
def test_dsh_collection_is_off_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    dsh_home: str | None,
) -> None:
    _dsh_root(tmp_path / ".dsh")
    _dsh_root(tmp_path / ".dsh-enhanced")
    monkeypatch.setattr(mon.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(mon.shutil, "which", lambda name: None)
    monkeypatch.setenv("SEXTANT_OMNIROUTE_DB", str(_router_db(tmp_path / "storage.sqlite")))
    monkeypatch.setenv("SEXTANT_AO_DB", str(_ao_db(tmp_path / "ao.db")))
    monkeypatch.setenv("SEXTANT_ORCA", str(tmp_path / "no-orca"))
    if dsh_home is None:
        monkeypatch.delenv("DSH_HOME", raising=False)
    else:
        monkeypatch.setenv("DSH_HOME", str(tmp_path / dsh_home))

    def no_dsh(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("dsh collection must require explicit opt-in")

    monkeypatch.setattr(mon, "dsh_snapshot", no_dsh)
    assert mon.default_paths()["dsh_root"] is None
    snapshot = mon.snapshot(params=_params(), env={}, now=NOW)
    assert snapshot["sources"]["dsh"] == {"root": None, "available": False}
    assert "disabled" in snapshot["dsh"]["error"]
    assert snapshot["dsh"]["deepseek"] is None
    assert snapshot["router"]["available"] is True
    assert snapshot["ao"]["available"] is True
    assert not any(
        row["name"].startswith("sextant.dsh.") for row in mon.metric_rows(snapshot, _params(), NOW)
    )
    assert mon.main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["sources"]["dsh"] == {"root": None, "available": False}
    assert "disabled" in output["dsh"]["error"]


def test_dsh_collection_requires_an_explicit_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _dsh_root(tmp_path / ".dsh")
    monkeypatch.setattr(
        mon,
        "default_paths",
        lambda: {"router_db": None, "ao_db": None, "dsh_root": None, "orca": None},
    )
    assert mon.main(["--dsh-home", str(root)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["sources"]["dsh"] == {"root": str(root), "available": True}
    assert output["dsh"]["calls"] == 1
    assert output["dsh"]["by_model"][0]["tokens"] == {
        "input": 110,
        "output": 25,
        "cache_read": 5,
        "cache_write": 0,
    }


def test_dsh_v4_derives_ttft_and_decode_rate(tmp_path: Path) -> None:
    root = _dsh_root(tmp_path)
    path = root / "sessions" / "work" / "uuid" / "session.v4.jsonl"
    session = mon.read_dsh_session(path)
    assert session["provider"] == "deepseek-official"
    assert session["model"] == "deepseek-flash"
    assert session["effort"] == "max"
    assert len(session["calls"]) == 1
    call = session["calls"][0]
    assert call["ttft_ms"] == 100.0
    assert call["decode_ms"] == 1000.0
    assert call["decode_tokens_per_second"] == 20.0
    assert session["tokens"] == {"input": 110, "output": 25, "cache_read": 5, "cache_write": 0}

    snapshot = mon.dsh_snapshot(root, _params())
    assert snapshot["available"] is True
    assert snapshot["calls"] == 1
    assert snapshot["deepseek"] is not None
    assert snapshot["deepseek"]["cny_per_usd"] == 6.7188
    assert snapshot["deepseek"]["cny"] == pytest.approx(snapshot["deepseek"]["usd"] * 6.7188)


@pytest.mark.parametrize(
    ("model", "effort"), [("gpt-6.1-sol", "xhigh"), ("deepseek-flash", "high")]
)
def test_dsh_selection_does_not_relabel_existing_usage(
    tmp_path: Path, model: str, effort: str
) -> None:
    root = _dsh_root(tmp_path)
    before = mon.dsh_snapshot(root, _params())
    path = root / "sessions" / "work" / "uuid" / "session.v4.jsonl"
    selection = {
        "type": "model/selection",
        "time": 4000,
        "data": {"provider": "fixture", "model": model, "reasoningEffort": effort},
    }
    with path.open("a") as stream:
        stream.write(json.dumps(selection) + "\n")
    after = mon.dsh_snapshot(root, _params())
    assert after["by_model"] == before["by_model"]
    assert after["deepseek"] == before["deepseek"]
    assert after["calls"] == before["calls"] == 1


@pytest.mark.parametrize(
    ("model", "effort"), [("gpt-6.1-sol", "xhigh"), ("deepseek-flash", "high")]
)
def test_dsh_messages_keep_their_model_and_effort(tmp_path: Path, model: str, effort: str) -> None:
    root = _dsh_root(tmp_path)
    before = mon.dsh_snapshot(root, _params())
    path = root / "sessions" / "work" / "uuid" / "session.v4.jsonl"
    events = [
        {
            "type": "model/selection",
            "time": 4000,
            "data": {"provider": "fixture", "model": model, "reasoningEffort": effort},
        },
        {"type": "step/start", "time": 5000, "data": {"turn": 2, "step": 1}},
        {
            "type": "assistant/message",
            "time": 6200,
            "data": {
                "turn": 2,
                "step": 1,
                "usage": {
                    "inputTokens": 3,
                    "outputTokens": 7,
                    "cacheReadTokens": 0,
                    "cacheWriteTokens": 0,
                },
                "stream": [
                    {"type": "chunk", "time": 5500},
                    {"type": "chunk", "time": 6000},
                ],
            },
        },
    ]
    with path.open("a") as stream:
        stream.write("\n".join(json.dumps(event) for event in events) + "\n")
    snapshot = mon.dsh_snapshot(root, _params())
    by_model = {(row["model"], row["effort"]): row for row in snapshot["by_model"]}
    assert by_model[("deepseek-flash", "max")] == before["by_model"][0]
    added = by_model[(model, effort)]
    assert added["tokens"] == {"input": 3, "output": 7, "cache_read": 0, "cache_write": 0}
    assert added["ttft_ms"] == {"p50": 500.0, "p95": 500.0, "samples": 1}
    assert added["decode_tokens_per_second"] == {"p50": 14.0, "p95": 14.0, "samples": 1}
    assert snapshot["calls"] == 2
    tokens = {"input": 110, "output": 25, "cache_read": 5}
    if model.startswith("deepseek"):
        tokens["input"] += 3
        tokens["output"] += 7
    assert snapshot["deepseek"] == mon.deepseek_cost(tokens, _params())


@pytest.mark.parametrize("output_tokens", [None, 0])
def test_dsh_missing_output_tokens_stay_unavailable(
    tmp_path: Path, output_tokens: int | None
) -> None:
    root = _dsh_root(tmp_path)
    path = root / "sessions" / "work" / "uuid" / "session.v4.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    usage = events[3]["data"]["usage"]
    if output_tokens is None:
        del usage["outputTokens"]
    else:
        usage["outputTokens"] = output_tokens
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n")
    session = mon.read_dsh_session(path)
    call = session["calls"][0]
    assert call["output_tokens"] == output_tokens
    assert call["decode_tokens_per_second"] == output_tokens
    assert call["ttft_ms"] == 100.0
    snapshot = mon.dsh_snapshot(root, _params())
    row = snapshot["by_model"][0]
    assert row["tokens"]["input"] == 110
    assert row["tokens"]["output"] == (None if output_tokens is None else 5)
    assert row["ttft_ms"]["samples"] == 1
    metrics = mon.metric_rows({"dsh": snapshot}, _params(), NOW)
    output_metrics = [
        metric
        for metric in metrics
        if metric["name"] == "sextant.dsh.tokens" and metric["attributes"]["kind"] == "output"
    ]
    if output_tokens is None:
        assert row["decode_tokens_per_second"] == {"p50": None, "p95": None, "samples": 0}
        assert snapshot["deepseek"] is None
        assert output_metrics == []
        assert not any("decode_tokens_per_second" in metric["name"] for metric in metrics)
        assert not any("cost" in metric["name"] for metric in metrics)
    else:
        assert row["decode_tokens_per_second"] == {"p50": 0.0, "p95": 0.0, "samples": 1}
        assert snapshot["deepseek"] is not None
        assert output_metrics[0]["value"] == 5


def test_dsh_zstd_path_uses_the_injected_decompressor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "dsh"
    session = root / "sessions" / "work" / "uuid"
    session.mkdir(parents=True)
    (session / "session.v4.jsonl.zstd").write_bytes(b"compressed")
    payload = (
        b'{"type":"step/start","time":1000,"data":{"turn":1,"step":1}}\n'
        b'{"type":"assistant/message","time":1200,"data":{"turn":1,"step":1,'
        b'"usage":{"inputTokens":1,"outputTokens":2,"cacheReadTokens":0,'
        b'"cacheWriteTokens":0},"stream":[{"type":"chunk","time":1100},'
        b'{"type":"chunk","time":2100}]}}\n'
    )
    monkeypatch.setattr(mon, "decompress_zstd", lambda data: payload)
    parsed = mon.read_dsh_session(session / "session.v4.jsonl.zstd")
    assert parsed["calls"][0]["ttft_ms"] == 100.0
    assert parsed["calls"][0]["decode_tokens_per_second"] == 2.0


def test_deepseek_yuan_uses_the_dated_registry_constant() -> None:
    params = _params()
    row = params["deepseek_cny_per_usd"]
    assert row["calibration"] == "UNCALIBRATED"
    assert row["value"] == 6.7188
    assert "2026-11-09" in row["source"]
    cost = mon.deepseek_cost(
        {"input": 1_000_000, "output": 1_000_000, "cache_read": 1_000_000}, params
    )
    assert cost["usd"] == pytest.approx(1.506)
    assert cost["cny"] == pytest.approx(1.506 * 6.7188)
    assert cost["calibration"] == "UNCALIBRATED"


def test_otlp_is_loopback_only_and_never_opens_a_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for url in (
        "http://example.com/v1/metrics",
        "file:///tmp/metrics",
        "http://10.0.0.1:4318/v1/metrics",
    ):
        with pytest.raises(ValueError):
            mon.check_endpoint(url)
    assert mon.check_endpoint("http://127.0.0.1:4318/v1/metrics").startswith("http://127.0.0.1")

    snapshot = mon.snapshot(
        {
            "router_db": _router_db(tmp_path / "storage.sqlite"),
            "ao_db": _ao_db(tmp_path / "ao.db"),
            "dsh_root": _dsh_root(tmp_path / "dsh"),
            "orca": None,
        },
        _params(),
        env={"AO_TELEMETRY_REMOTE": "off"},
        now=NOW,
    )
    rows = mon.metric_rows(snapshot, _params())
    payload = mon.otlp_payload(rows, NOW)
    names = {
        metric["name"] for metric in payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
    }
    assert "sextant.ao.telemetry.opt_out" in names
    assert "sextant.dsh.call.ttft_ms" in names
    assert "sextant.router.quota.remaining" in names

    def no_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("no socket may open")

    monkeypatch.setattr(mon.urllib.request, "urlopen", no_network)
    with pytest.raises(ValueError):
        mon.emit_otlp(rows, "http://example.com/v1/metrics", NOW)


def test_snapshot_reads_all_four_sources_without_body_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dsh_root(tmp_path / "dsh")
    ao_dir = tmp_path / "ao"
    ao_dir.mkdir()
    (ao_dir / "telemetry_opt_out").write_text("1")
    (ao_dir / "telemetry_policy.json").write_text('{"events_enabled": false}')
    launcher = tmp_path / "ao.sh"
    launcher.write_text("AO_TELEMETRY_REMOTE=off exec ao daemon\n")
    monkeypatch.setattr(mon, "AO_LAUNCHER", launcher)

    def fake_run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout='{"worktrees": [], "terminals": []}')

    monkeypatch.setattr(mon.subprocess, "run", fake_run)
    snapshot = mon.snapshot(
        {
            "router_db": _router_db(tmp_path / "storage.sqlite"),
            "ao_db": _ao_db(ao_dir / "ao.db"),
            "dsh_root": tmp_path / "dsh",
            "orca": tmp_path / "orca",
        },
        _params(),
        env={"AO_TELEMETRY_REMOTE": "off"},
        now=NOW,
    )
    assert snapshot["generated_at"] == NOW.isoformat()
    assert snapshot["sources"]["router"]["available"] is True
    assert snapshot["sources"]["ao"]["available"] is True
    assert snapshot["sources"]["dsh"]["available"] is True
    assert snapshot["sources"]["orca"]["available"] is True
    assert snapshot["ao"]["telemetry"]["effective"] is True
    text = json.dumps(snapshot)
    assert "CANARY" not in text
    assert snapshot["ao"]["sessions"][0]["rows"] == 1
    assert snapshot["ao"]["measurements"]["merged_reported"] == 1
    assert snapshot["router"]["calls"]["count"] == 2
