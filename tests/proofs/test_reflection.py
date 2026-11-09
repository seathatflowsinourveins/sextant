"""The verified reflection: an Orca automation run only after a session ended or a PR merged."""

import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).parents[2]
WSL = ROOT / "deploy" / "wsl"
SETUP = WSL / "reflection.sh"
PRECHECK = WSL / "reflection-precheck.sh"
PROMPT = (WSL / "reflection-prompt.md").read_text()
FAKE = """#!/usr/bin/env bash
echo "${0##*/} $*" >> "$FAKE_LOG"
case "${0##*/} $*" in
  "orca-ide automations list --json")
    if [ -f "$FAKE_STATE" ]; then
      echo '{"result": {"automations": [{"id": "r1", "name": "Verified reflection"}]}}'
    else echo '{"result": {"automations": []}}'; fi ;;
  "orca-ide automations create"*) touch "$FAKE_STATE" ;;
  "gh pr list"*) echo "${FAKE_MERGED:-0}" ;;
  "gh repo view --json defaultBranchRef --jq .defaultBranchRef.name") echo gate ;;
  "git worktree list --porcelain") printf 'worktree %s\\n' "$FAKE_MAIN" ;;
esac
"""


def _env(tmp: Path, *names: str) -> dict[str, str]:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in names:
        (bin_dir / name).write_text(FAKE)
        (bin_dir / name).chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_LOG": str(tmp / "calls"),
        "FAKE_STATE": str(tmp / "created"),
        "FAKE_MAIN": str(ROOT),
        "HOME": str(tmp),
        "XDG_STATE_HOME": str(tmp / "state"),
        "CLAUDE_CONFIG_DIR": str(tmp / ".claude"),
    }


def _transcript(tmp: Path, session: str, first_prompt: str) -> Path:
    path = tmp / ".claude" / "projects" / "-home-sextant-lane" / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"type": "summary"},
        {"type": "user", "message": {"content": [{"type": "text", "text": first_prompt}]}},
        {"type": "user", "message": {"content": "sextant-verified-reflection, quoted later"}},
    ]
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return path


def test_the_reflection_is_a_marked_proposal_only_run() -> None:
    for script in (SETUP, PRECHECK):
        assert subprocess.run(["bash", "-n", str(script)], check=False).returncode == 0, script
    # The marker opens the prompt, so the precheck can tell a reflection's own transcript apart.
    assert PROMPT.startswith("sextant-verified-reflection.")
    assert "do not append to or rewrite docs/handbook/lessons.jsonl yourself" in PROMPT
    assert "northstar.handbook.lesson/1" in PROMPT and "never write the registry" in PROMPT
    assert "#91" in PROMPT and "Never merge" in PROMPT
    setup = SETUP.read_text()
    # A fresh worktree per run, created disabled: enabling it is the lead's call.
    assert "--workspace-mode new-per-run" in setup and "--disabled" in setup
    assert "--enabled" not in setup and "reflection-precheck.sh" in setup
    assert "\nreflection:\n" in (ROOT / "justfile").read_text()


def test_setting_up_the_reflection_twice_makes_one_and_never_enables_it(tmp_path: Path) -> None:
    env = _env(tmp_path, "orca-ide", "gh")
    for _ in range(2):
        run = subprocess.run(["bash", str(SETUP)], env=env, capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
    calls = (tmp_path / "calls").read_text().splitlines()
    creates = [call for call in calls if call.startswith("orca-ide automations create")]
    edits = [call for call in calls if call.startswith("orca-ide automations edit r1 ")]
    assert len(creates) == 1 and "--disabled" in creates[0]
    assert len(edits) == 1 and "reflection-precheck.sh" in edits[0] and "--prompt" in edits[0]
    assert "--base-branch origin/gate" in edits[0] and "--base-branch origin/gate" in creates[0]
    assert "--repo path:" in edits[0] and "--repo path:" in creates[0]
    assert not any("--enabled" in call for call in calls)


def test_the_precheck_runs_only_after_an_ended_session_or_a_merge(tmp_path: Path) -> None:
    env = _env(tmp_path, "gh")
    stamp = tmp_path / "state" / "sextant" / "reflection-precheck"

    def precheck(merged: int = 0) -> int:
        run_env = {**env, "FAKE_MERGED": str(merged)}
        return subprocess.run(["bash", str(PRECHECK)], env=run_env, check=False).returncode

    def rewind() -> None:
        old = time.time() - 3600
        os.utime(stamp, (old, old))

    assert precheck() == 1, "nothing happened: skip"
    assert stamp.exists()

    rewind()
    sessions = tmp_path / ".claude" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "4242.json").write_text(json.dumps({"sessionId": "running", "pid": 4242}))
    _transcript(tmp_path, "running", "a lane task")
    assert precheck() == 1, "a session still running has not ended"

    _transcript(tmp_path, "reflection", "sextant-verified-reflection. Run verified reflection")
    assert precheck() == 1, "a reflection's own end never schedules the next"

    _transcript(tmp_path, "ended", "a lane task that quotes sextant-verified-reflection later")
    assert precheck() == 0, "an ended session runs it"
    assert precheck() == 1, "the pass moves the stamp, so the same session runs it once"

    rewind()
    for path in (tmp_path / ".claude" / "projects").rglob("*.jsonl"):
        os.utime(path, (time.time() - 7200, time.time() - 7200))
    assert precheck(merged=1) == 0, "a merged PR runs it"
    assert precheck(merged=0) == 1
    calls = (tmp_path / "calls").read_text()
    assert "gh pr list --state merged --search merged:>=" in calls
