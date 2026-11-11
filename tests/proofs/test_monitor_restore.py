import json
import os
import re
import shutil
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
PROMTOOL = ROOT / "tests/proofs/monitor_staleness.promtool.yaml"
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


def _function_source(path, function):
    source = path.read_text(encoding="utf-8")
    assert f"def {function}(" in source
    return source.split(f"def {function}(", 1)[1].split("\ndef ", 1)[0]


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
            assert current is not None
            key, sep, value = line.partition("=")
            assert sep
            sections[current].append((key.strip(), value.strip()))
    return sections


def _exec_starts(service):
    entries = [value for name, value in service["Service"] if name == "ExecStart"]
    assert len(entries) == 2
    assert all(entry.startswith("-") for entry in entries)
    return [entry[1:].split() for entry in entries]


def test_scheduler_units_are_checked_in_and_name_the_bridge_scripts():
    for path in (SERVICE, TIMER, PARAMS, INSTALL):
        assert path.is_file()
    service = _parse_unit(SERVICE)
    assert dict(service["Service"])["Type"] == "oneshot"
    assert "TimeoutStartSec" not in {name for name, _ in service["Service"]}
    by_script = {}
    for parts in _exec_starts(service):
        assert parts[:2] == ["/usr/bin/python3", "-I"]
        script = Path(parts[2].replace("%h/sextant", str(ROOT)))
        assert script in BRIDGES
        by_script[script] = parts[3:]
    home = _dsh_home()
    assert by_script[L3] == ["--otlp", "--dsh-home", f"%h/{home}"]
    assert by_script[EVIDENCE] == ["--otlp"]
    for path in (SERVICE, TIMER):
        assert "monitor_github.py" not in path.read_text(encoding="utf-8")
    for script, function in ((L3, "metric_rows"), (EVIDENCE, "_gauges")):
        assert HEARTBEAT in _function_source(script, function)
    timer = _parse_unit(TIMER)
    assert dict(timer["Timer"])["Unit"] == "sextant-monitor.service"
    assert "AccuracySec" not in {name for name, _ in timer["Timer"]}
    params = json.loads(PARAMS.read_text(encoding="utf-8"))
    period = {row["name"]: row for row in params["rows"]}["monitor_bridge_period_seconds"]
    assert (period["value"], period["unit"]) == (60, "seconds")
    l7 = json.loads(L7_PARAMS.read_text(encoding="utf-8"))
    rows = {row["name"]: row for row in l7["rows"]}
    for name, value in (
        ("monitor_alert_hold_seconds", 60),
        ("monitor_alert_query_from_seconds", 600),
    ):
        assert rows[name]["value"] == value
        assert "v13.2" in rows[name]["source"]
    assert (SYSTEMD / "README.md").read_text(encoding="utf-8").count("%h/.dsh-full") == 1


def test_install_substitutes_the_repo_path_literally(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("install.sh", "sextant-monitor.service", "sextant-monitor.timer"):
        shutil.copy2(SYSTEMD / name, repo / name)
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    systemctl = bin_dir / "systemctl"
    systemctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    systemctl.chmod(0o755)
    literal = r"/work/a&b|c\d"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SEXTANT_REPO": literal,
    }
    subprocess.run(
        ["bash", str(repo / "install.sh")], check=True, env=env, capture_output=True, text=True
    )
    unit = (home / ".config/systemd/user/sextant-monitor.service").read_text(encoding="utf-8")
    assert f"WorkingDirectory={literal}" in unit
    assert "%h/sextant" not in unit


def test_grafana_provisions_one_staleness_rule_with_a_healthy_zero_path():
    rule = yaml.safe_load(RULE.read_text(encoding="utf-8"))["groups"][0]["rules"][0]
    assert (rule["uid"], rule["title"], rule["condition"]) == (
        "sextant-monitor-evidence-stale",
        "MonitorEvidenceStale",
        "C",
    )
    assert (rule["noDataState"], rule["execErrState"]) == ("Alerting", "Alerting")
    data = {item["refId"]: item for item in rule["data"]}
    assert set(data) == {"A", "B", "C"}
    a = data["A"]
    assert rule["for"] == "60s"
    assert a["relativeTimeRange"] == {"from": 600, "to": 0}
    expr = a["model"]["expr"]
    assert "time() - sextant_monitor_last_success_timestamp_seconds" in expr
    assert "> 900" in expr
    assert expr.endswith("or on() vector(0)")
    for bridge in ("l3_l4", "evidence"):
        assert f'absent({HEARTBEAT}{{bridge="{bridge}"}})' in expr
    labels = rule["labels"]
    stale_max = {
        row["name"]: row for row in json.loads(L7_PARAMS.read_text(encoding="utf-8"))["rows"]
    }["monitor_staleness_seconds_max"]
    assert labels["threshold_ref"] == "monitor_staleness_seconds_max"
    assert labels["threshold_value"] == str(stale_max["value"])
    assert f"> {stale_max['value']}" in expr


def test_promtool_unit_test_uses_the_rule_expression():
    document = yaml.safe_load(PROMTOOL.read_text(encoding="utf-8"))
    expr = yaml.safe_load(RULE.read_text(encoding="utf-8"))["groups"][0]["rules"][0]["data"][0][
        "model"
    ]["expr"]
    assert len(document["tests"]) == 4
    assert all(
        case["promql_expr_test"][0]["expr"] == f"({expr}) > bool 0" for case in document["tests"]
    )


def test_compose_mounts_the_alerting_directory_read_only_once():
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    assert "alertmanager" not in services
    mounts = [
        volume
        for volume in services["lgtm"]["volumes"]
        if "/otel-lgtm/grafana/conf/provisioning/alerting" in volume
    ]
    assert mounts == ["./alerting:/otel-lgtm/grafana/conf/provisioning/alerting:ro"]


def test_l7_leaves_staleness_to_the_grafana_rule():
    rules = L7_RULES.read_text(encoding="utf-8")
    assert "MonitorEvidenceStale" not in rules
    assert "sextant:monitor_staleness:seconds" not in rules
    assert "absent(sextant_monitor_last_success_timestamp_seconds)" not in rules
