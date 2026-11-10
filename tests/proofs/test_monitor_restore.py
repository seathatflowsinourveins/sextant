"""Proofs for the D-37 monitor scheduler and Grafana staleness rule."""

import ast
import json
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SYSTEMD = ROOT / "deploy/monitor/systemd"
ALERTING = ROOT / "deploy/monitor/lgtm/alerting"
SERVICE, TIMER = SYSTEMD / "sextant-monitor.service", SYSTEMD / "sextant-monitor.timer"
PARAMS, INSTALL = SYSTEMD / "parameters.json", SYSTEMD / "install.sh"
RULE = ALERTING / "sextant-monitor-staleness.yaml"
COMPOSE = ROOT / "deploy/monitor/lgtm/compose.yaml"
L7_RULES = ROOT / "deploy/monitor/l7/rules.yaml"
L7_PARAMS = ROOT / "deploy/monitor/l7/parameters.json"
L7_README = ROOT / "deploy/monitor/l7/README.md"
START, DOCTOR = ROOT / "docs/start.md", ROOT / "scripts/dsh_profile_doctor.py"
L3, EVIDENCE = ROOT / "scripts/monitor_l3_l4.py", ROOT / "scripts/monitor_evidence.py"
HEARTBEAT = "sextant_monitor_last_success_timestamp_seconds"
BRIDGES = {L3: ["--otlp", "--dsh-home"], EVIDENCE: ["--otlp"]}


def _dsh_home():
    one = re.search(r"DSH_HOME=~/([A-Za-z0-9._-]+)", START.read_text(encoding="utf-8"))
    two = re.search(r'Path\.home\(\) / "([^"]+)"', DOCTOR.read_text(encoding="utf-8"))
    assert one and two, "docs/start.md or dsh_profile_doctor.py lost the home"
    assert one.group(1) == two.group(1)
    return one.group(1)


def _strings(path, function):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function:
            return {
                n.value
                for n in ast.walk(node)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            }
    raise AssertionError(f"{path.name}: missing {function}()")


def _parse_unit(path):
    sections, current = {}, None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, [])
        else:
            assert current is not None, f"{path.name}: setting outside a section"
            key, sep, value = line.partition("=")
            assert sep, f"{path.name}: not a setting: {line}"
            sections[current].append((key.strip(), value.strip()))
    return sections


def _one(entries, key):
    values = [value for name, value in entries if name == key]
    assert len(values) == 1, f"expected one {key}, got {values}"
    return values[0]


def _exec_starts(service):
    entries = [value for name, value in service["Service"] if name == "ExecStart"]
    assert len(entries) == 2
    assert all(entry.startswith("-") for entry in entries)
    return [entry[1:].split() for entry in entries]


def test_scheduler_units_are_checked_in_and_name_the_bridge_scripts():
    for path in (SERVICE, TIMER, PARAMS, INSTALL):
        assert path.is_file(), f"missing {path.relative_to(ROOT)}"
    service = _parse_unit(SERVICE)
    assert _one(service["Service"], "Type") == "oneshot"
    assert _one(service["Service"], "WorkingDirectory") == "%h/sextant"
    assert _one(service["Service"], "TimeoutStartSec") == "5min"
    by_script = {}
    for parts in _exec_starts(service):
        assert parts[:2] == ["/usr/bin/python3", "-I"]
        script = Path(parts[2].replace("%h/sextant", str(ROOT)))
        assert script in BRIDGES, f"unknown bridge {parts[2]}"
        by_script[script] = parts[3:]
    home = _dsh_home()
    assert by_script[L3] == ["--otlp", "--dsh-home", f"%h/{home}"]
    assert by_script[EVIDENCE] == ["--otlp"]
    for path in (SERVICE, TIMER):
        assert "monitor_github.py" not in path.read_text(encoding="utf-8")
    for script, function in ((L3, "metric_rows"), (EVIDENCE, "_gauges")):
        assert HEARTBEAT in _strings(script, function), script.name
    timer = _parse_unit(TIMER)
    assert _one(timer["Timer"], "Unit") == "sextant-monitor.service"
    assert _one(timer["Timer"], "AccuracySec") == "1s"
    params = json.loads(PARAMS.read_text(encoding="utf-8"))
    period = {row["name"]: row for row in params["rows"]}["monitor_bridge_period_seconds"]
    assert (period["value"], period["unit"]) == (60, "seconds")
    assert period["status"] == "UNCALIBRATED"
    assert "OTEL_METRIC_EXPORT_INTERVAL" in period["source"]
    assert "60000" in period["source"] and "read 2026-11-10" in period["source"]
    assert _one(timer["Timer"], "OnStartupSec") == "60s"
    assert _one(timer["Timer"], "OnUnitActiveSec") == "60s"
    l7 = json.loads(L7_PARAMS.read_text(encoding="utf-8"))
    stale_max = {row["name"]: row for row in l7["rows"]}["monitor_staleness_seconds_max"]
    assert period["value"] < int(stale_max["value"])
    check = subprocess.run(
        ["bash", "-n", str(INSTALL)], capture_output=True, text=True, check=False
    )
    assert check.returncode == 0, check.stderr
    install = INSTALL.read_text(encoding="utf-8")
    assert all(
        text in install for text in ("sextant-monitor.timer", "daemon-reload", "enable --now")
    )
    readme = (SYSTEMD / "README.md").read_text(encoding="utf-8")
    for text in (
        "two `ExecStart` lines",
        "%h/.dsh-full",
        "Roster ops",
        "apply-after-merge",
    ):
        assert text in readme, text


def test_grafana_provisions_one_staleness_rule_with_a_healthy_zero_path():
    document = yaml.safe_load(RULE.read_text(encoding="utf-8"))
    group = document["groups"][0]
    rule = group["rules"][0]
    assert (rule["uid"], rule["title"], rule["condition"]) == (
        "sextant-monitor-evidence-stale",
        "MonitorEvidenceStale",
        "C",
    )
    assert (rule["noDataState"], rule["execErrState"]) == ("Alerting", "Alerting")
    assert rule["for"] == "5m"
    assert all("relativeTimeRange" not in item for item in rule["data"])
    data = {item["refId"]: item for item in rule["data"]}
    a = data["A"]
    assert (a["datasourceUid"], a["model"]["instant"]) == ("prometheus", True)
    expr = a["model"]["expr"]
    for text in (
        "absent(sextant_monitor_last_success_timestamp_seconds)",
        "time() - sextant_monitor_last_success_timestamp_seconds",
        "> 900",
    ):
        assert text in expr
    assert expr.endswith("or on() vector(0)")
    b, c = data["B"], data["C"]
    assert b["datasourceUid"] == "__expr__"
    assert (b["model"]["type"], b["model"]["expression"]) == ("reduce", "A")
    assert c["datasourceUid"] == "__expr__"
    assert (c["model"]["type"], c["model"]["expression"]) == ("threshold", "B")
    assert c["model"]["conditions"][0]["evaluator"]["params"] == [0]
    labels = rule["labels"]
    assert (labels["delivery"], labels["action"]) == ("informational", "proposal-only")
    l7 = json.loads(L7_PARAMS.read_text(encoding="utf-8"))
    stale_max = {row["name"]: row for row in l7["rows"]}["monitor_staleness_seconds_max"]
    assert labels["threshold_ref"] == "monitor_staleness_seconds_max"
    assert labels["threshold_value"] == str(stale_max["value"])
    assert f"> {stale_max['value']}" in expr
    assert labels["source_series"] == HEARTBEAT
    assert labels["producer_status"] == "produced"
    readme = (ALERTING / "README.md").read_text(encoding="utf-8")
    for text in ("`for: 5m`", "l7/rules.yaml", "relativeTimeRange"):
        assert text in readme, text


def test_compose_mounts_the_alerting_directory_read_only_once():
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    assert "alertmanager" not in services
    volumes = services["lgtm"]["volumes"]
    mounts = [
        volume for volume in volumes if "/otel-lgtm/grafana/conf/provisioning/alerting" in volume
    ]
    assert mounts == ["./alerting:/otel-lgtm/grafana/conf/provisioning/alerting:ro"]


def test_l7_leaves_staleness_to_the_grafana_rule():
    rules = L7_RULES.read_text(encoding="utf-8")
    assert "MonitorEvidenceStale" not in rules
    assert "sextant:monitor_staleness:seconds" not in rules
    assert "absent(sextant_monitor_last_success_timestamp_seconds)" not in rules
    readme = L7_README.read_text(encoding="utf-8")
    assert "Grafana" in readme and "deploy/monitor/lgtm/alerting/" in readme
