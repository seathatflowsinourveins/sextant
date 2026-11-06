"""The lifecycle: git's upkeep and Orca's daily sweep leave no worktree or branch behind."""

import os
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parents[2]
WSL = ROOT / "deploy" / "wsl"
LIFECYCLE = WSL / "lifecycle.sh"
PRECHECK = WSL / "lifecycle-precheck.sh"
PROMPT = (WSL / "lifecycle-prompt.md").read_text()
# Stand-ins that record each call, so no test touches real git config, timers or an Orca server.
FAKE = """#!/usr/bin/env bash
echo "${0##*/} $*" >> "$FAKE_LOG"
case "${0##*/} $*" in
  "orca-ide automations list --json")
    if [ -f "$FAKE_STATE" ]; then echo '{"result": {"automations": [{"name": "Lifecycle sweep"}]}}'
    else echo '{"result": {"automations": []}}'; fi ;;
  "orca-ide automations create"*) touch "$FAKE_STATE" ;;
  "gh release view"*) echo "$FAKE_RELEASE" ;;
esac
"""


def _fakes(tmp: Path, *names: str) -> Path:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in names:
        (bin_dir / name).write_text(FAKE)
        (bin_dir / name).chmod(0o755)
    return bin_dir


def test_the_sweep_runs_in_place_and_never_forces() -> None:
    for script in (LIFECYCLE, PRECHECK):
        assert subprocess.run(["bash", "-n", str(script)], check=False).returncode == 0, script
    lifecycle = LIFECYCLE.read_text()
    assert "git config fetch.prune true" in lifecycle and "git maintenance start" in lifecycle
    # A workspace target, not a repo one, so no run creates a worktree of its own.
    assert "orca-ide automations create" in lifecycle and '--workspace "path:$PWD"' in lifecycle
    assert "--repo" not in lifecycle and "--precheck" in lifecycle
    assert "orca worktree rm --worktree branch:<branch> --delete-branch" in PROMPT
    assert "git branch -d <branch>" in PROMPT and "issue #35" in PROMPT
    assert re.findall(r"-D\b", PROMPT) == ["-D"] and "Never use `-D`." in PROMPT
    assert "bash deploy/wsl/lifecycle.sh" in (WSL / "setup.sh").read_text()
    assert "\nlifecycle:\n" in (ROOT / "justfile").read_text()


def test_setting_up_the_sweep_twice_makes_one(tmp_path: Path) -> None:
    bin_dir = _fakes(tmp_path, "git", "orca-ide")
    log = tmp_path / "calls"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_LOG": str(log),
        "FAKE_STATE": str(tmp_path / "created"),
    }
    for _ in range(2):
        run = subprocess.run(["bash", str(LIFECYCLE)], env=env, capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
    calls = log.read_text().splitlines()
    assert calls.count("git config fetch.prune true") == 2
    assert calls.count("git maintenance start") == 2
    assert sum(call.startswith("orca-ide automations create") for call in calls) == 1


def test_the_precheck_runs_the_sweep_only_when_there_is_work(tmp_path: Path) -> None:
    pin = re.search(r"/releases/download/(v[0-9.]+)/", (WSL / "sextant.user-data").read_text())
    assert pin
    clone = tmp_path / "clone"
    (clone / "deploy" / "wsl").mkdir(parents=True)
    for name in ("lifecycle-precheck.sh", "sextant.user-data"):
        shutil.copy(WSL / name, clone / "deploy" / "wsl" / name)
    env = {
        **os.environ,
        "PATH": f"{_fakes(tmp_path, 'gh')}:{os.environ['PATH']}",
        "FAKE_LOG": str(tmp_path / "calls"),
        "HOME": str(tmp_path),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(clone), *args], env=env, check=True, capture_output=True)

    def precheck(release: str) -> int:
        run_env = {**env, "FAKE_RELEASE": release}
        script = clone / "deploy" / "wsl" / "lifecycle-precheck.sh"
        return subprocess.run(["bash", str(script)], env=run_env, check=False).returncode

    origin = str(tmp_path / "origin.git")
    subprocess.run(["git", "init", "-q", "--bare", origin], env=env, check=True)
    git("init", "-q", "-b", "main")
    git("add", ".")
    git("commit", "-q", "-m", "start")
    git("remote", "add", "origin", origin)
    git("push", "-q", "-u", "origin", "main")
    old = (datetime.now(UTC) - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    new = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    assert precheck(f"{pin[1]} {old}") == 1, "a quiet day skips the sweep"
    assert precheck(f"v999.0.0 {new}") == 1, "a release inside the cooldown waits"
    assert precheck(f"v999.0.0 {old}") == 0, "a release past the cooldown runs it"
    git("worktree", "add", "-q", str(tmp_path / "task"), "-b", "task")
    assert precheck(f"{pin[1]} {old}") == 0, "a worktree left behind runs it"
    git("worktree", "remove", str(tmp_path / "task"))
    git("push", "-q", "-u", "origin", "task")
    git("push", "-q", "origin", "--delete", "task")
    assert precheck(f"{pin[1]} {old}") == 0, "a branch GitHub deleted runs it"
