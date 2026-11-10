"""Proofs for the D-37 monitor scheduler and Grafana staleness rule."""

from __future__ import annotations

import json
import re
import stat
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SYSTEMD = ROOT / "deploy/monitor/systemd"
ALERTING = ROOT / "deploy/monitor/lgtm/alerting"
SERVICE = SYSTEMD / "sextant-monitor.service"
TIMER = SYSTEMD / "sextant-monitor.timer"
PARAMS = SYSTEMD / "parameters.json"
INSTALL = SYSTEMD / "install.sh"
RULE = ALERTING / "sextant-monitor-staleness.yaml"
COMPOSE = ROOT / "deploy/monitor/lgtm/compose.yaml"
L7_RULES = ROOT / "deploy/monitor/l7/rules.yaml"
L7_PARAMS = ROOT / "deploy/monitor/l7/parameters.json"
L7_README = ROOT / "deploy/monitor/l7/README.md"
BRIDGES = {
    ROOT / "scripts/monitor_l3_l4.py": ["--otlp", "--dsh-home", "%h/.dsh"],
    ROOT / "scripts/monitor_github.py": [],
    ROOT / "scripts/monitor_evidence.py": ["--otlp"],
}


def _parse_unit(path: Path) -> dict[str, list[tuple[str, str]]]:
    """Parse a systemd unit into ordered (key, value) entries per section.

    configparser cannot represent the repeated ExecStart key, so the proof
    reads the unit shape directly.
    """
    sections: dict[str, list[tuple[str, str]]] = {}
    current = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            assert current, f"{path.name}: empty section header"
            sections.setdefault(current, [])
            continue
        assert current is not None, f"{path.name}: setting outside a section"
        key, sep, value = line.partition("=")
        assert sep, f"{path.name}: not a setting: {line}"
        sections[current].append((key.strip(), value.strip()))
    return sections


def _one(entries: list[tuple[str, str]], key: str) -> str:
    values = [value for name, value in entries if name == key]
    assert len(values) == 1, f"expected one {key}, got {values}"
    return values[0]


def _exec_starts(service: dict[str, list[tuple[str, str]]]) -> list[list[str]]:
    entries = [value for name, value in service["Service"] if name == "ExecStart"]
    assert len(entries) == 3
    argv = []
    for entry in entries:
        assert entry.startswith("-"), "one failing bridge must not stop the rest"
        argv.append(entry[1:].split())
    return argv


def test_scheduler_units_are_checked_in_and_name_the_bridge_scripts() -> None:
    for path in (SERVICE, TIMER, PARAMS, INSTALL):
        assert path.is_file(), f"missing {path.relative_to(ROOT)}"

    service = _parse_unit(SERVICE)
    assert set(service) >= {"Unit", "Service", "Install"}
    assert _one(service["Service"], "Type") == "oneshot"
    assert _one(service["Service"], "WorkingDirectory") == "%h/sextant"
    assert _one(service["Service"], "TimeoutStartSec") == "5min"

    by_script: dict[Path, list[str]] = {}
    for parts in _exec_starts(service):
        assert parts[0] == "/usr/bin/python3"
        assert parts[1] == "-I"
        script = Path(parts[2].replace("%h/sextant", str(ROOT)))
        assert script in BRIDGES, f"unknown bridge {parts[2]}"
        by_script[script] = parts[3:]
    assert set(by_script) == set(BRIDGES)
    for script, expected in BRIDGES.items():
        assert by_script[script] == expected, script.name

    timer = _parse_unit(TIMER)
    assert set(timer) >= {"Unit", "Timer", "Install"}
    assert _one(timer["Timer"], "Unit") == "sextant-monitor.service"
    assert _one(timer["Timer"], "AccuracySec") == "1s"
    assert _one(timer["Install"], "WantedBy") == "timers.target"

    params = json.loads(PARAMS.read_text(encoding="utf-8"))
    assert params["version"] == 1
    rows = {row["name"]: row for row in params["rows"]}
    period = rows["monitor_bridge_period_seconds"]
    assert period["value"] == 60
    assert period["unit"] == "seconds"
    assert period["status"] == "UNCALIBRATED"
    assert "OTEL_METRIC_EXPORT_INTERVAL" in period["source"]
    assert "60000" in period["source"]
    assert "read 2026-11-10" in period["source"]
    assert _one(timer["Timer"], "OnStartupSec") == f"{period['value']}s"
    assert _one(timer["Timer"], "OnUnitActiveSec") == f"{period['value']}s"

    l7 = json.loads(L7_PARAMS.read_text(encoding="utf-8"))
    stale_max = {row["name"]: row for row in l7["rows"]}["monitor_staleness_seconds_max"]
    assert stale_max["status"] == "UNCALIBRATED"
    assert int(period["value"]) < int(stale_max["value"])

    assert INSTALL.stat().st_mode & stat.S_IXUSR
    check = subprocess.run(
        ["bash", "-n", str(INSTALL)], capture_output=True, text=True, check=False
    )
    assert check.returncode == 0, check.stderr
    install_text = INSTALL.read_text(encoding="utf-8")
    assert "sextant-monitor.timer" in install_text
    assert "daemon-reload" in install_text
    assert "enable --now" in install_text


def test_grafana_provisions_one_staleness_rule_with_a_healthy_zero_path() -> None:
    assert RULE.is_file(), "missing deploy/monitor/lgtm/alerting rule"
    document = yaml.safe_load(RULE.read_text(encoding="utf-8"))
    assert document["apiVersion"] == 1
    assert "contactPoints" not in document
    assert len(document["groups"]) == 1
    group = document["groups"][0]
    assert group["orgId"] == 1
    assert group["name"] == "sextant-monitor"
    assert group["folder"] == "Sextant"
    params = json.loads(PARAMS.read_text(encoding="utf-8"))
    period = {row["name"]: row for row in params["rows"]}["monitor_bridge_period_seconds"]
    assert group["interval"] == f"{period['value']}s"
    assert len(group["rules"]) == 1
    rule = group["rules"][0]
    assert rule["uid"] == "sextant-monitor-evidence-stale"
    assert len(rule["uid"]) <= 40
    assert re.fullmatch(r"[A-Za-z0-9_-]+", rule["uid"])
    assert rule["title"] == "MonitorEvidenceStale"
    assert rule["condition"] == "C"
    assert rule["noDataState"] == "Alerting"
    assert rule["execErrState"] == "Alerting"
    assert rule["for"] == "5m"
    assert rule["isPaused"] is False

    data = {item["refId"]: item for item in rule["data"]}
    assert list(data) == ["A", "B", "C"]
    assert data["A"]["datasourceUid"] == "prometheus"
    assert data["A"]["model"]["instant"] is True
    expr = data["A"]["model"]["expr"]
    assert "absent(sextant_monitor_last_success_timestamp_seconds)" in expr
    assert "time() - sextant_monitor_last_success_timestamp_seconds" in expr
    assert "> 900" in expr
    assert expr.endswith("or on() vector(0)"), "healthy silence must yield 0, not No Data"
    assert data["B"]["datasourceUid"] == "__expr__"
    assert data["B"]["model"]["type"] == "reduce"
    assert data["B"]["model"]["expression"] == "A"
    assert data["C"]["datasourceUid"] == "__expr__"
    assert data["C"]["model"]["type"] == "threshold"
    assert data["C"]["model"]["expression"] == "B"
    assert data["C"]["model"]["conditions"][0]["evaluator"]["params"] == [0]

    assert rule["labels"]["delivery"] == "informational"
    assert rule["labels"]["action"] == "proposal-only"
    l7 = json.loads(L7_PARAMS.read_text(encoding="utf-8"))
    stale_max = {row["name"]: row for row in l7["rows"]}["monitor_staleness_seconds_max"]
    assert rule["labels"]["threshold_ref"] == "monitor_staleness_seconds_max"
    assert rule["labels"]["threshold_value"] == str(stale_max["value"])
    assert f"> {stale_max['value']}" in expr
    assert rule["labels"]["source_series"] == "sextant_monitor_last_success_timestamp_seconds"
    assert rule["labels"]["producer_status"] == "produced"
    assert rule["annotations"]["runbook"] == "deploy/monitor/lgtm/alerting/README.md"
    assert "alertmanager" not in json.dumps(document).lower()


def test_compose_mounts_the_alerting_directory_read_only_once() -> None:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = compose["services"]
    assert "alertmanager" not in services
    volumes = services["lgtm"]["volumes"]
    mounts = [
        volume for volume in volumes if "/otel-lgtm/grafana/conf/provisioning/alerting" in volume
    ]
    assert mounts == ["./alerting:/otel-lgtm/grafana/conf/provisioning/alerting:ro"]
    assert services["lgtm"]["ports"] == [
        "127.0.0.1:3000:3000",
        "127.0.0.1:4317:4317",
        "127.0.0.1:4318:4318",
    ]


def test_l7_leaves_staleness_to_the_grafana_rule() -> None:
    rules = L7_RULES.read_text(encoding="utf-8")
    assert "MonitorEvidenceStale" not in rules
    assert "sextant:monitor_staleness:seconds" not in rules
    assert "absent(sextant_monitor_last_success_timestamp_seconds)" not in rules
    readme = L7_README.read_text(encoding="utf-8")
    assert "Grafana" in readme
    assert "deploy/monitor/lgtm/alerting/" in readme
