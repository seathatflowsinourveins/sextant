"""PR-M2: real launchers with inert children; no runtime, collector or home is activated."""

import importlib.util
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
RUNTIMES = ROOT / "deploy/wsl/lane-runtimes"
ENDPOINT = "http://127.0.0.1:4317"
CONTENT = (
    "OTEL_LOG_USER_PROMPTS",
    "OTEL_LOG_ASSISTANT_RESPONSES",
    "OTEL_LOG_RAW_API_BODIES",
    "OTEL_LOG_TOOL_CONTENT",
)
CLAUDE_ENV = {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
    "ENABLE_BETA_TRACING_DETAILED": "0",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_TRACES_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
    "OTEL_EXPORTER_OTLP_ENDPOINT": ENDPOINT,
    "OTEL_LOG_TOOL_DETAILS": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY": "1",
}
SIGNAL_OVERRIDES = tuple(
    f"OTEL_EXPORTER_OTLP_{signal}_{suffix}"
    for signal in ("METRICS", "LOGS", "TRACES")
    for suffix in ("ENDPOINT", "PROTOCOL", "HEADERS")
)
UNSET = (*CONTENT, *SIGNAL_OVERRIDES, "BETA_TRACING_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS")
OBSERVED = (*CLAUDE_ENV, *UNSET, "OTEL_RESOURCE_ATTRIBUTES",
            "DSH_TELEMETRY_DISABLED", "DSH_TELEMETRY_MODE")  # fmt: skip


def _stub(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


def _child(path: Path) -> None:
    # An explicit allowlist, never a dump of the test runner's environment or credentials.
    _stub(
        path,
        f"#!{sys.executable}\nimport json, os, sys\n"
        f"print(json.dumps({{'argv': sys.argv[1:], 'env': "
        f"{{key: os.environ.get(key) for key in {OBSERVED!r}}}}}))\n",
    )


def _run(command: list[str], home: Path, inherited: dict | None = None) -> dict:
    result = subprocess.run(
        command,
        env={
            "HOME": str(home),
            "PATH": f"{home / 'bin'}:{Path(sys.executable).parent}:/usr/bin:/bin",
            **(inherited or {}),
        },
        cwd=home,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("metadata", ({}, {"SEXTANT_LANE": "research", "SEXTANT_PR": "42"}))
def test_claude_launch_unsets_content_and_exports_only_to_loopback(
    tmp_path: Path, metadata: dict
) -> None:
    _child(tmp_path / "bin/claude")
    result = _run(
        ["bash", str(RUNTIMES / "claude-launch.sh"), "--version"],
        tmp_path,
        {
            **dict.fromkeys(CLAUDE_ENV, "wrong"),
            **dict.fromkeys(UNSET, "inherited"),
            "OTEL_RESOURCE_ATTRIBUTES": "sextant.pr=unrelated",
            **metadata,
        },
    )
    assert result["argv"] == ["--version"]
    actual = result["env"]
    assert {key: actual[key] for key in CLAUDE_ENV} == CLAUDE_ENV
    assert all(actual[key] is None for key in UNSET)
    attributes = dict(item.split("=", 1) for item in actual["OTEL_RESOURCE_ATTRIBUTES"].split(","))
    expected = {"sextant.runtime": "claude-code"}
    if metadata:
        expected.update({"sextant.lane": "research", "sextant.pr": "42"})
    assert attributes == expected


def test_claude_project_defaults_keep_redaction_and_operational_opt_outs() -> None:
    settings = json.loads((ROOT / ".claude/settings.json").read_text())["env"]
    assert {key: settings[key] for key in CLAUDE_ENV} == CLAUDE_ENV
    assert not set(CONTENT) & settings.keys()
    assert "BETA_TRACING_ENDPOINT" not in settings


def _config(home: Path) -> dict:
    spec = importlib.util.spec_from_file_location("monitor_parity", RUNTIMES / "parity.py")
    assert spec and spec.loader
    parity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parity)
    return tomllib.loads(parity.codex_toml(home))


@pytest.mark.parametrize("name", ("sextant-codex", "sextant-codex-review"))
def test_codex_config_and_launch_override_statsig_and_content(tmp_path: Path, name: str) -> None:
    prefix = tmp_path / ".local/share/sextant-lane-runtimes"
    prefix.mkdir(parents=True)
    launcher = prefix / "codex-launch.sh"
    shutil.copyfile(RUNTIMES / launcher.name, launcher)
    launcher.chmod(0o755)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / name).symlink_to(launcher)
    _child(tmp_path / ".local/share/sextant-agents/node_modules/.bin/codex")
    for source in ("routing.json", "model-policy.json"):
        shutil.copyfile(RUNTIMES / source, prefix / source)
    (prefix / "repository-path").write_text(f"{tmp_path}\n")
    _stub(
        tmp_path / "scripts/with-keys.sh",
        '#!/bin/sh\nwhile [ "$1" != -- ]; do shift; done\nshift\nexec "$@"\n',
    )
    _stub(tmp_path / "scripts/omni_receipt.py", "# No receipt or network in this proof.\n")
    # Existing lane files may be retained. CLI overrides must still implement the contract.
    lane = prefix / "codex-home"
    lane.mkdir()
    retained = '[analytics]\nenabled=true\n[otel]\nmetrics_exporter="statsig"\n'
    (lane / "config.toml").write_text(retained)
    result = _run(
        [str(tmp_path / "bin" / name), "exec"],
        tmp_path,
        {"SEXTANT_LANE": "research", "SEXTANT_PR": "42"},
    )
    argv = result["argv"]
    overrides = {}
    for index, value in enumerate(argv):
        if value == "-c":
            key, raw = argv[index + 1].split("=", 1)
            overrides[key] = tomllib.loads(f"value={raw}")["value"]
    config = _config(tmp_path)
    for key in ("analytics", "feedback"):
        assert config[key]["enabled"] is False
        assert overrides[f"{key}.enabled"] is False
    for key in (
        "log_user_prompt",
        "log_agent_responses",
        "log_guardian_assessments",
        "log_sse_deltas",
    ):
        assert config["otel"][key] is False
        assert overrides[f"otel.{key}"] is False
    for key in ("exporter", "trace_exporter", "metrics_exporter"):
        assert config["otel"][key] == {"otlp-grpc": {"endpoint": ENDPOINT}}
        assert overrides[f"otel.{key}"] == config["otel"][key]
    assert config["otel"]["span_attributes"] == {"sextant.runtime": "codex"}
    for key, value in (("runtime", "codex"), ("lane", "research"), ("pr", "42")):
        assert overrides[f'otel.span_attributes."sextant.{key}"'] == value
    assert (lane / "config.toml").read_text() == retained
    assert not (tmp_path / ".codex").exists()
    assert not (tmp_path / ".config/orca").exists()


@pytest.mark.parametrize("arguments", ([], ["--version"], ["--profile", "acp"]))
def test_dsh_launch_disables_both_telemetry_paths(tmp_path: Path, arguments: list[str]) -> None:
    prefix = tmp_path / "lane"
    prefix.mkdir()
    launcher = prefix / "dsh-launch.sh"
    shutil.copyfile(RUNTIMES / launcher.name, launcher)
    (prefix / "repository-path").write_text(f"{tmp_path}\n")
    _child(tmp_path / "sextant-agents/node_modules/@deepseek-ai/dsh/lib/bin.js")
    _stub(
        tmp_path / "scripts/with-keys.sh",
        '#!/bin/sh\nwhile [ "$1" != -- ]; do shift; done\nshift\nexec "$@"\n',
    )
    result = _run(
        ["bash", str(launcher), *arguments],
        tmp_path,
        {"DSH_TELEMETRY_DISABLED": "", "DSH_TELEMETRY_MODE": "FEEDBACK_ONLY"},
    )
    assert result["argv"] == arguments
    assert result["env"]["DSH_TELEMETRY_DISABLED"] == "1"
    assert result["env"]["DSH_TELEMETRY_MODE"] == "DISABLED"
