"""PR-M1: the local LGTM store is loopback-only, passwordless and redacting.

Static contracts only: starting the container is a host step between B
bursts, and no proof here starts a service, a container or a collector.
"""

import json
import re
import shutil
import stat
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).parents[2]
LGTM = "deploy/monitor/lgtm"

KEPT_NAMES = {"skill_name", "mcp_server_name", "mcp_tool_name", "subagent_type", "hook_name"}
DELETED_KEYS = {
    "tool_input",
    "tool_parameters",
    "full_command",
    "bash_command",
    "file_path",
    "arguments",
    "output",
}
SECRET_VALUES = {
    "sk-[A-Za-z0-9_-]{16,}",
    "gh[pousr]_[A-Za-z0-9_]{20,}",
    "github_pat_[A-Za-z0-9_]{20,}",
    "AIza[0-9A-Za-z_-]{35}",
    "AKIA[0-9A-Z]{16}",
    "PK[0-9A-Z]{18,}",
    "(?i)(bearer|token|key|secret|password)[=: ]+['\"]?[A-Za-z0-9._~+/=-]{16,}",
}


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def _yaml(path: str) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(_read(path))
    return loaded


def _compose() -> dict[str, Any]:
    service: dict[str, Any] = _yaml(f"{LGTM}/compose.yaml")["services"]["lgtm"]
    return service


def _collector() -> dict[str, Any]:
    return _yaml(f"{LGTM}/otelcol-config.yaml")


def _m1_files() -> list[str]:
    return [
        f"{LGTM}/compose.yaml",
        f"{LGTM}/otelcol-config.yaml",
        f"{LGTM}/run-grafana.sh",
        f"{LGTM}/start.sh",
        f"{LGTM}/genai-mapping.md",
        f"{LGTM}/README.md",
        "deploy/monitor/upstream-ui-map.md",
    ]


def test_lgtm_publishes_only_loopback_otlp_and_grafana() -> None:
    service = _compose()
    assert service["ports"] == [
        "127.0.0.1:3000:3000",
        "127.0.0.1:4317:4317",
        "127.0.0.1:4318:4318",
    ]
    assert "privileged" not in service and "network_mode" not in service
    assert "pid" not in service and "ENABLE_OBI" not in service["environment"]
    # Image pinned by version and digest, never a floating tag.
    assert re.fullmatch(r"grafana/otel-lgtm:0\.38\.0@sha256:[a-f0-9]{64}", service["image"])
    assert "LGTM_CONTAINER_MEMORY" in service["mem_limit"]
    volumes = service["volumes"]
    assert "./otelcol-config.yaml:/otel-lgtm/otelcol-config.yaml:ro" in volumes
    assert "./run-grafana.sh:/otel-lgtm/run-grafana.sh:ro" in volumes
    assert "sextant-lgtm-data:/data" in volumes


def test_grafana_is_passwordless_viewer_only_with_telemetry_off() -> None:
    env: dict[str, Any] = _compose()["environment"]
    assert env["GF_ANALYTICS_REPORTING_ENABLED"] == "false"
    assert env["GF_ANALYTICS_CHECK_FOR_UPDATES"] == "false"
    assert env["GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES"] == "false"
    # Anonymous access is Viewer-only, with no login form and no basic-auth
    # API path left to reach an admin account through.
    assert env["GF_AUTH_ANONYMOUS_ENABLED"] == "true"
    assert env["GF_AUTH_ANONYMOUS_ORG_ROLE"] == "Viewer"
    assert env["GF_AUTH_DISABLE_LOGIN_FORM"] == "true"
    assert env["GF_AUTH_BASIC_ENABLED"] == "false"
    # The admin password is required only by first-run creation; it is an
    # environment name interpolated fail-closed, never a literal or default.
    assert env["GF_SECURITY_ADMIN_PASSWORD"].startswith("${GF_SECURITY_ADMIN_PASSWORD:?")
    compose = _read(f"{LGTM}/compose.yaml")
    assert "GF_PLUGINS_PREINSTALL" not in compose
    assert "admin/admin" not in compose and "keys.sh" not in compose


def test_run_grafana_override_downloads_no_plugin_and_defaults_to_viewer() -> None:
    script = _read(f"{LGTM}/run-grafana.sh")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert "grafana-llm-app" not in code and "GF_PLUGINS_PREINSTALL" not in code
    assert "Admin" not in code and ":-Viewer}" in code
    # The rest of the upstream launcher shape is kept.
    assert "refresh_stale_managed_plugins" in code
    assert "./bin/grafana server" in code
    assert stat.S_IXUSR & (ROOT / LGTM / "run-grafana.sh").stat().st_mode


def test_start_generates_a_throwaway_admin_password_without_recording_it() -> None:
    start = _read(f"{LGTM}/start.sh")
    assert "/dev/urandom" in start and "GF_SECURITY_ADMIN_PASSWORD" in start
    assert "docker compose up -d" in start and "LGTM_CONTAINER_MEMORY" in start
    # Generated inside the start command only: never printed or stored.
    assert not re.search(r"\b(echo|printf|tee)\b", start)
    assert "set -x" not in start and "keys.sh" not in start
    assert stat.S_IXUSR & (ROOT / LGTM / "start.sh").stat().st_mode


def test_collector_deletes_tool_content_before_redaction_and_persistence() -> None:
    config = _collector()
    actions = config["processors"]["attributes"]["actions"]
    deleted = {a["key"] for a in actions if a["action"] == "delete"}
    assert DELETED_KEYS <= deleted
    assert not (deleted & KEPT_NAMES)
    pipelines = config["service"]["pipelines"]
    assert pipelines["traces"]["processors"] == [
        "transform",
        "attributes",
        "redaction",
        "batch",
    ]
    assert pipelines["logs"]["processors"] == [
        "transform",
        "attributes",
        "redaction",
        "batch",
    ]
    assert pipelines["metrics"]["processors"] == ["transform", "attributes", "batch"]
    endpoints = {e["endpoint"] for e in config["exporters"].values() if "endpoint" in e}
    assert endpoints == {
        "http://127.0.0.1:9090/api/v1/otlp",
        "http://127.0.0.1:4418",
        "http://127.0.0.1:3100/otlp",
        "http://127.0.0.1:4040",
    }
    assert config["extensions"]["health_check"]["endpoint"] == "127.0.0.1:13133"
    assert "cors" not in _read(f"{LGTM}/otelcol-config.yaml")


def test_redaction_masks_secret_shaped_keys_and_values() -> None:
    redaction = _collector()["processors"]["redaction"]
    assert redaction["allow_all_keys"] is True
    assert redaction["redact_all_types"] is True
    assert redaction["blocked_key_patterns"] == [
        "(?i).*(api_key|secret|token|password|authorization|credential).*"
    ]
    assert SECRET_VALUES <= set(redaction["blocked_values"])
    for pattern in [*redaction["blocked_key_patterns"], *redaction["blocked_values"]]:
        re.compile(pattern)


def test_invocation_names_are_extracted_not_deleted() -> None:
    transform = _collector()["processors"]["transform"]
    for signal in ("log_statements", "trace_statements", "metric_statements"):
        statements = " ".join(transform[signal])
        for kept in ("skill_name", "mcp_server_name", "mcp_tool_name"):
            assert f'["{kept}"]' in statements


def test_prompt_and_response_logging_is_never_enabled() -> None:
    enabled = re.compile(
        r"OTEL_LOG_(USER_PROMPTS|ASSISTANT_RESPONSES|RAW_API_BODIES|TOOL_CONTENT)\s*[:=]\s*\S"
    )
    for path in _m1_files():
        assert not enabled.search(_read(path)), path


def test_genai_mapping_is_pinned_and_keeps_vendor_series() -> None:
    mapping = _read(f"{LGTM}/genai-mapping.md")
    assert "9ffc7e00c639be7712e544e3e54331e885dccf84" in mapping
    assert "e10a930844c6951757a43b849d364f7d056ac32b" in mapping
    assert "Development" in mapping
    assert "gen_ai.client.inference.usage.input_tokens" in mapping
    assert "cacheRead" in mapping and "Add, never rename" in mapping
    assert "no source" in mapping  # Unknown stays unknown, never 0.
    # The collector derives attribute aliases only; it renames no metric.
    assert "set(metric.name" not in _read(f"{LGTM}/otelcol-config.yaml")


def test_tunables_are_registered_uncalibrated_and_match_compose() -> None:
    rows: list[dict[str, Any]] = json.loads(_read(f"{LGTM}/parameters.json"))
    by_name = {row["name"]: row for row in rows}
    for row in rows:
        assert {"name", "unit", "value", "source", "calibration_state", "last_change"} <= (set(row))
        assert row["calibration_state"] == "UNCALIBRATED"
        assert row["source"] and row["last_change"] == "2026-11-08"
    assert by_name["prometheus_retention"]["value"] == "90d"
    assert by_name["loki_retention"]["value"] == "90d"
    assert by_name["lgtm_container_memory"]["value"] == "2G"
    assert by_name["host_ram_floor_gb"]["value"] == "20"
    assert by_name["host_disk_floor_gb"]["value"] == "20"
    env: dict[str, Any] = _compose()["environment"]
    assert "--storage.tsdb.retention.time=90d" in env["PROMETHEUS_EXTRA_ARGS"]
    assert "-store.retention=90d" in env["LOKI_EXTRA_ARGS"]
    assert "LGTM_CONTAINER_MEMORY:-2G" in _read(f"{LGTM}/compose.yaml")


def test_host_meets_the_registered_ram_and_disk_floors() -> None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.is_file():
        pytest.skip("host RAM undeterminable without /proc/meminfo")
    total_kb = int(re.search(r"MemTotal:\s+(\d+)", meminfo.read_text()).group(1))  # type: ignore[union-attr]
    assert total_kb * 1024 / 1e9 > 20
    assert shutil.disk_usage(ROOT).free / 1e9 > 20


def test_upstream_ui_map_keeps_grafana_to_the_live_layer() -> None:
    ui_map = _read("deploy/monitor/upstream-ui-map.md")
    for needle in (
        "agentsview",
        "OmniRoute",
        "127.0.0.1:20128",
        "127.0.0.1:3001",
        "Orca",
        "gh aw audit",
        "127.0.0.1:3000",
        "Apache-2.0",
        "none licensed exists",
    ):
        assert needle in ui_map
    assert "Cross-runtime live layer only" in ui_map
