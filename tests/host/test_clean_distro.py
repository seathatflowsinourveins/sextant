"""Acceptance of the clean distro. `just accept` runs this inside it; nowhere else can answer it."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
AGENTS = json.loads((ROOT / ".devcontainer" / "agents" / "package.json").read_text())[
    "dependencies"
]
DOCKERFILE = (ROOT / ".devcontainer" / "Dockerfile").read_text()


def _run(*command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _pin(pattern: str) -> str:
    found = re.search(pattern, DOCKERFILE, re.MULTILINE)
    assert found, pattern
    return found[1]


def test_new_york_time_and_not_the_windows_clock() -> None:
    assert _run("timedatectl", "show", "-p", "Timezone", "--value").stdout.strip() == (
        "America/New_York"
    )
    assert "useWindowsTimezone=false" in Path("/etc/wsl.conf").read_text()


def test_systemd_and_services_outlive_a_logout() -> None:
    assert Path("/proc/1/comm").read_text().strip() == "systemd"
    assert _run("loginctl", "show-user", "sextant", "-p", "Linger").stdout.strip() == "Linger=yes"


def test_the_user_is_not_the_old_lanes_user() -> None:
    assert _run("id", "-un").stdout.strip() == "sextant"
    assert os.getuid() == 1500
    assert not os.access("/mnt/wsl/ns-scanner", os.W_OK)


def test_nothing_here_waits_on_a_prompt() -> None:
    assert _run("sudo", "-n", "true").returncode == 0
    settings = json.loads((Path.home() / ".claude" / "settings.json").read_text())
    assert settings["permissions"]["defaultMode"] == "bypassPermissions"
    assert settings["skipDangerousModePermissionPrompt"] is True
    # Claude Code stays at the pin; bumps come by PR.
    assert settings["env"]["DISABLE_AUTOUPDATER"] == "1"
    login = _run("gh", "auth", "status").stdout
    assert "'workflow'" in login and "'user'" in login


def test_no_old_rules_or_hooks_load() -> None:
    claude_home = Path.home() / ".claude"
    for name in ("CLAUDE.md", "AGENTS.global.md", "rules"):
        assert not (claude_home / name).exists(), name


def test_windows_programs_are_off_path_and_metrics_off() -> None:
    assert shutil.which("wsl.exe") is None
    assert _run("ubuntu-insights", "consent", "wsl_setup").stdout.strip() == "wsl_setup: false"


def test_tools_match_this_repos_pins() -> None:
    assert _pin(r"^FROM ghcr\.io/astral-sh/uv:([0-9.]+)@") in _run("uv", "--version").stdout
    assert _run("node", "--version").stdout.startswith("v" + _pin(r"^ARG NODE_VERSION=(\S+)"))
    assert _pin(r"^ARG JUST_VERSION=(\S+)") in _run("just", "--version").stdout
    assert _pin(r"^RUN claude install (\S+)") in _run("claude", "--version").stdout
    assert AGENTS["@openai/codex"] in _run("codex", "--version").stdout
    assert AGENTS["@deepseek-ai/dsh"] in _run("dsh", "--version").stdout


def test_orca_serves_this_project_on_its_own_port() -> None:
    assert _run("systemctl", "--user", "is-active", "orca-serve").stdout.strip() == "active"
    assert ":6771 " in _run("ss", "-Hltn", "sport = :6771").stdout
    repos = json.loads(_run("orca-ide", "repo", "list", "--json").stdout)["result"]["repos"]
    assert [repo["path"] for repo in repos] == [str(ROOT)]


def _without_path(unit: str) -> list[str]:
    return [line for line in unit.splitlines() if not line.startswith("Environment=PATH=")]


def test_orca_is_at_the_pin_and_runs_as_its_own_service() -> None:
    user_data = (ROOT / "deploy" / "wsl" / "sextant.user-data").read_text()
    pin = re.search(r"releases/download/v(\d+\.\d+\.\d+)/", user_data)
    assert pin and _run("orca-ide", "--version").stdout.strip() == pin[1], "run `just orca-update`"
    service = ("orca-ide", "serve", "service")
    status = json.loads(_run(*service, "status", "--json").stdout)["result"]
    assert status["verdict"] == "live"
    want = json.loads(_run(*service, "install", "--port", "6771", "--dry-run", "--json").stdout)[
        "result"
    ]["content"]
    assert _without_path(Path(status["unitPath"]).read_text()) == _without_path(want)
    environment = _run("systemctl", "--user", "show", "orca-serve", "-p", "Environment").stdout
    assert "ORCA_TERMINAL_MEMORY_MAX=16G" in environment
    assert "ORCA_TERMINAL_MEMORY_SWAP_MAX=0" in environment


def test_the_claude_shelf_is_installed_here() -> None:
    """`just shelf`: each plugin the settings enable is installed and on; OMC stays off."""
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
    want = {name for name, on in settings["enabledPlugins"].items() if on}
    listed = json.loads(_run("claude", "plugin", "list", "--json").stdout)
    have = {plugin["id"] for plugin in listed if plugin["enabled"] and plugin["scope"] != "session"}
    assert want <= have, "run `just shelf`"
    assert "oh-my-claudecode@omc" not in have
    known = json.loads(
        (Path.home() / ".claude" / "plugins" / "known_marketplaces.json").read_text()
    )
    assert known["sextant-lsp"]["source"]["path"] == str(ROOT / ".claude" / "lsp")
