"""Proof: a role is a checked-in launch definition.

Source: code.claude.com/docs/en/sub-agents.md, "Define agents" and "Use the
agent"; code.claude.com/docs/en/cli-reference.md, `--agent`, `--name` and
`--autocompact`; code.claude.com/docs/en/model-config.md, `autoCompactWindow`;
code.claude.com/docs/en/settings-reference.md, `idleCompaction`. All read
2026-11-09. Authority: LEAD-2228 section N2; LEAD-2313 item 2.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/role_launch.py"
POLICY = ROOT / "deploy/wsl/lane-runtimes/model-policy.json"
AGENTS = ROOT / ".claude/agents"
ROLES = ("lead", "dispatcher", "lander", "tracker", "worker")
COORDINATION = ("lead", "dispatcher", "lander", "tracker")
POLICY_KEY = {
    "lead": "claude_lead",
    "dispatcher": "claude_roles",
    "lander": "claude_roles",
    "tracker": "claude_roles",
    "worker": "claude",
}
STATE_POINTERS = {
    "lead": "~/sextant-data/handoffs/LEAD-STATE.md",
    "dispatcher": "~/sextant-data/roster-ops/claude-successor",
    "lander": "~/sextant-data/landing",
    "tracker": "~/sextant-data/handoffs/practice-tracker",
    "worker": "~/sextant-data/handoffs/tasks",
}
KEYS = {"name", "description", "model", "initialPrompt"}


def _module():
    spec = importlib.util.spec_from_file_location("role_launch", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _policy() -> dict:
    return json.loads(POLICY.read_text())


def _minimal_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".claude").mkdir(parents=True)
    (root / "deploy/wsl/lane-runtimes").mkdir(parents=True)
    shutil.copy(POLICY, root / "deploy/wsl/lane-runtimes/model-policy.json")
    shutil.copy(ROOT / ".claude/settings.json", root / ".claude/settings.json")
    return root


def test_every_role_definition_matches_the_model_policy() -> None:
    assert _module().check(ROOT) == []


def test_each_definition_has_the_probed_keys_an_empty_body_and_its_model() -> None:
    module = _module()
    policy = _policy()
    for role in ROLES:
        meta, body = module.read_definition(AGENTS / f"{role}.md")
        assert set(meta) == KEYS
        assert body.strip() == ""
        assert meta["name"] == role
        assert meta["description"]
        assert meta["model"] == policy[POLICY_KEY[role]]["model"]
        assert STATE_POINTERS[role] in meta["initialPrompt"]


def test_the_launcher_uses_the_agent_definition_and_names_the_session() -> None:
    module = _module()
    assert module.argv("lead") == [
        "claude",
        "--agent",
        "lead",
        "--name",
        "lead",
        "--autocompact",
        "200000",
    ]
    assert module.argv("worker") == ["claude", "--agent", "worker", "--name", "worker"]
    for role in ROLES:
        built = module.argv(role)
        assert "--model" not in built
        assert "--effort" not in built
        assert "--settings" not in built
        assert "--advisor" not in built


def test_the_four_coordination_roles_take_the_window_and_workers_keep_the_default() -> None:
    module = _module()
    for role in COORDINATION:
        assert module.argv(role)[-2:] == ["--autocompact", "200000"]
    assert "--autocompact" not in module.argv("worker")


def test_the_policy_records_every_launch_value_the_definitions_use() -> None:
    policy = _policy()
    lead, roles, worker = policy["claude_lead"], policy["claude_roles"], policy["claude"]
    assert (lead["launch"], lead["session_name"]) == (
        "python3 scripts/role_launch.py lead",
        "lead",
    )
    assert (lead["autocompact_window"], lead["autocompact_window_calibration"]) == (
        200000,
        "UNCALIBRATED",
    )
    assert lead["advisor"] is None and "model-config" in lead["autocompact_window_source"]
    assert (
        roles["launch"],
        roles["session_name"],
    ) == ("python3 scripts/role_launch.py <dispatcher|lander|tracker>", "<role>")
    assert (roles["autocompact_window"], roles["autocompact_window_calibration"]) == (
        200000,
        "UNCALIBRATED",
    )
    assert roles["advisor"] is None
    assert (worker["launch"], worker["session_name"]) == (
        "python3 scripts/role_launch.py worker",
        "worker",
    )
    assert worker["autocompact_window"] is None and worker["advisor"] is None


def test_the_session_start_check_is_wired() -> None:
    justfile = (ROOT / "justfile").read_text()
    session_start = justfile.split("session-start:", 1)[1].split("\n\n", 1)[0]
    assert "python3 scripts/role_launch.py --check" in session_start


def test_check_names_a_missing_definition(tmp_path: Path) -> None:
    problems = _module().check(_minimal_root(tmp_path))
    assert len([problem for problem in problems if "missing" in problem]) == len(ROLES)


def test_check_rejects_a_frontmatter_key_the_probes_did_not_prove(tmp_path: Path) -> None:
    root = _minimal_root(tmp_path)
    shutil.copytree(AGENTS, root / ".claude/agents")
    path = root / ".claude/agents/lead.md"
    path.write_text(path.read_text().replace("model:", "effort: high\nmodel:", 1))
    problems = _module().check(root)
    assert any("lead" in problem and "effort" in problem for problem in problems)


def test_the_check_mode_prints_ok_and_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("ok:")


def test_an_unknown_role_is_a_usage_error() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "no-such-role"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "usage" in (result.stdout + result.stderr).lower()
