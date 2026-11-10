"""AO runs only a handed-off lane PR's fix-CI and review loop, at its pin, and never merges."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
AO = ROOT / "deploy" / "wsl" / "ao.sh"
PIN = "033d597032e448a0ea16c298350e36b099f74106"
# Stand-ins: `gh` answers with the PR in $FAKE_PR, `ao` records each call.
FAKE_GH = """#!/usr/bin/env bash
cat "$FAKE_PR"
"""
FAKE_AO = """#!/usr/bin/env bash
all="$*"
printf '%s\\n' "${all//$'\\n'/ }" >> "$FAKE_LOG"
[[ "$1" == version ]] && echo "${FAKE_VERSION:-0.14.10 commit 033d597032e4 built 2026-11-06}"
if [[ "$1" == spawn ]]; then
  # AO's own resolution: an omitted --agent is the project's worker.agent, an omitted --mode the
  # daemon default (backend/internal/cli/spawn.go:224-236).
  agent=${FAKE_WORKER:-} mode=${FAKE_DEFAULT_MODE:-chat}
  while (($#)); do
    case "$1" in
      --agent | --harness) agent=$2; shift ;;
      --mode) mode=$2; shift ;;
    esac
    shift
  done
  echo "session agent=$agent mode=$mode" >> "$FAKE_LOG"
fi
exit 0
"""
HANDED_OFF = {
    "state": "OPEN",
    "isDraft": False,
    "baseRefName": "main",
    "headRefName": "lane-x",
    "headRefOid": "a" * 40,
    "autoMergeRequest": {"mergeMethod": "SQUASH"},
    "statusCheckRollup": [{"name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"}],
}


def _run(
    tmp: Path,
    *args: str,
    pr: dict | None = None,
    version: str | None = None,
    worker: str | None = None,
    default_mode: str | None = None,
):
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("gh", FAKE_GH), ("ao", FAKE_AO)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    (tmp / "pr.json").write_text(json.dumps(pr or HANDED_OFF))
    env = {
        "HOME": os.environ["HOME"],
        "PATH": f"{bin_dir}:{os.defpath}",
        "FAKE_PR": str(tmp / "pr.json"),
        "FAKE_LOG": str(tmp / "calls"),
    }
    if worker:
        env["FAKE_WORKER"] = worker
    if default_mode:
        env["FAKE_DEFAULT_MODE"] = default_mode
    # Shell startup hooks can pin an installed AO over the PATH stand-in.
    env.pop("BASH_ENV", None)
    if version:
        env["FAKE_VERSION"] = version
    run = subprocess.run(["bash", str(AO), *args], env=env, capture_output=True, text=True)
    calls = (tmp / "calls").read_text().splitlines() if (tmp / "calls").exists() else []
    return run, calls


def test_ao_is_pinned_and_claims_only_a_handed_off_pr(tmp_path: Path) -> None:
    script = AO.read_text()
    assert subprocess.run(["bash", "-n", str(AO)], check=False).returncode == 0
    # AO's own installer, from the pinned commit, without its LAN listener or tunnel.
    assert "agent-orchestrator/$pin_commit/scripts/setup-self-hosted.sh" in script
    assert f"pin_commit={PIN}" in script and "--install-only" in script
    assert "--tunnel" not in script and "remote-host" not in script
    # Off AO's default port, which another distro holds in the shared namespace.
    assert "port=3301" in script and "AO_TELEMETRY_REMOTE=off" in script
    # Phase 2's active identity is sextant-next; AO's project id stays `sextant`.
    assert 'clone="$HOME/.ao/repos/sextant-next"' in script
    assert "repo_url=https://github.com/seathatflowsinourveins/sextant\n" in script
    assert "project=sextant" in script
    assert "\nao *args:\n" in (ROOT / "justfile").read_text()
    assert PIN in (ROOT / "docs" / "manifest.md").read_text()

    run, calls = _run(tmp_path, "claim", "57")
    assert run.returncode == 0, run.stderr
    spawn = next(call for call in calls if call.startswith("spawn "))
    assert "--claim-pr 57 --no-takeover" in spawn and "--branch lane-x" in spawn
    assert "--agent codex" in spawn and "--harness" not in spawn
    assert "Never merge" in spawn and "a" * 40 in spawn
    # The worker pushes the way .codex/rules/default.rules allows: plain git push, its upstream.
    assert "with plain git push" in spawn


@pytest.mark.parametrize("default_mode", ["chat", "tui"])
@pytest.mark.parametrize("worker", ["claude-code", "codex", "deepseek-harness", "muse"])
def test_claim_names_codex_and_its_chat_interface_for_any_project_worker(
    tmp_path: Path, worker: str, default_mode: str
) -> None:
    """The fake ao resolves the session as AO does: the project's worker.agent unless --agent names
    one, the daemon default unless --mode does. Whatever the worker, claude-code among them (the
    lead, 2026-11-08), and whatever the default, which the lead moves to tui, claim's session is
    Codex in chat, its own app-server, so no Claude runs in chat's claude-agent-acp."""
    run, calls = _run(tmp_path, "claim", "57", worker=worker, default_mode=default_mode)
    assert run.returncode == 0, run.stderr
    spawn = next(call for call in calls if call.startswith("spawn ")).split()
    assert spawn.count("--agent") == 1 and spawn.count("--mode") == 1
    assert "session agent=codex mode=chat" in calls
    # Nor is AO pointed at a Claude ACP runtime: its two overrides (claudeacp/driver.go:541-551).
    script = AO.read_text()
    assert "AO_CLAUDE_ACP_COMMAND" not in script and "AO_ACP_RUNTIME_DIR" not in script


def test_deepseek_harness_is_documented_for_explicit_spawns_only() -> None:
    readme = (ROOT / "deploy/wsl/lane-runtimes/README.md").read_text()
    manifest_rows = [
        line
        for line in (ROOT / "docs/manifest.md").read_text().splitlines()
        if line.startswith("| AO runs one job:")
    ]
    # The union driver keeps both sides' rows; name the one row this proof reads instead of
    # silently testing whichever row a stale conflict resolution put first.
    assert len(manifest_rows) == 1, "docs/manifest.md must hold exactly one AO row"
    manifest_row = manifest_rows[0]
    for surface in (readme, manifest_row):
        assert "ao spawn --project sextant --harness deepseek-harness" in surface
        assert "deepseekharness.go:59" in surface and "codex/codex.go:95" in surface
        assert "spawn.go:224" in surface
        assert "opencode-v2" not in surface and "[deepseek-harness" not in surface
    assert "[harness]" not in AO.read_text()


def test_claim_refuses_a_pr_its_worker_still_holds(tmp_path: Path) -> None:
    for change in (
        {"isDraft": True},
        {"state": "MERGED"},
        {"autoMergeRequest": None},
        {"baseRefName": "live"},
        {"statusCheckRollup": [{"name": "ci", "status": "IN_PROGRESS", "conclusion": None}]},
    ):
        run, calls = _run(tmp_path, "claim", "57", pr={**HANDED_OFF, **change})
        assert run.returncode == 1, change
        assert not any(call.startswith("spawn ") for call in calls), change


def test_the_daemon_refuses_any_version_but_the_pin(tmp_path: Path) -> None:
    run, calls = _run(tmp_path, "daemon", version="0.14.11 commit 0123456789ab built x")
    assert run.returncode == 1 and "not the pin" in run.stderr
    assert "daemon" not in calls


@pytest.mark.parametrize("customization", ["exported_function", "startup_file"])
def test_fixture_ignores_parent_shell_customizations(tmp_path, monkeypatch, customization):
    monkeypatch.delenv("BASH_ENV", raising=False)
    if customization == "exported_function":
        monkeypatch.setenv("BASH_FUNC_ao%%", "() { return 93; }")
    else:
        startup = tmp_path / "startup.sh"
        startup.write_text("ao() { return 93; }\n")
        monkeypatch.setenv("BASH_ENV", str(startup))
    run, calls = _run(tmp_path, "daemon")
    assert run.returncode == 0, run.stderr
    assert calls == ["version", "daemon"]


def test_fixture_ignores_shell_startup(tmp_path: Path, monkeypatch) -> None:
    startup = tmp_path / "startup.sh"
    startup.write_text("exit 97\n")
    monkeypatch.setenv("BASH_ENV", str(startup))
    run, calls = _run(tmp_path, "claim", "57")
    assert run.returncode == 0, run.stderr
    assert any(call.startswith("spawn ") for call in calls)
