"""AO runs only a handed-off lane PR's fix-CI and review loop, at its pin, and never merges."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
AO = ROOT / "deploy" / "wsl" / "ao.sh"
PIN = "033d597032e448a0ea16c298350e36b099f74106"
REPO = "https://github.com/seathatflowsinourveins/sextant"
# Stand-ins: `gh` answers the PR view from $FAKE_PR and the repository's default branch from
# $FAKE_DEFAULT_BRANCH; each gh and ao call is recorded.
FAKE_GH = """#!/usr/bin/env bash
printf 'gh %s\\n' "$*" >> "$FAKE_LOG"
case "$*" in
  "pr view "*) cat "$FAKE_PR" ;;
  "repo view "*) echo "$FAKE_DEFAULT_BRANCH" ;;
  *) exit 2 ;;
esac
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


# `project` recreates AO's record and clone through AO's own commands; these stand-ins keep AO's
# project state in a file and answer git from the fixture, so no daemon and no real repo is touched.
FAKE_AO_PROJECT = """#!/usr/bin/env bash
printf 'ao %s\\n' "$*" >> "$FAKE_LOG"
case "$1 $2" in
  "project get")
    [[ -s "$FAKE_AO_STATE" ]] || exit 1
    cat "$FAKE_AO_STATE"
    ;;
  "project rm")
    : > "$FAKE_AO_STATE"
    ;;
  "project add")
    path= prev=
    for arg in "$@"; do
      [[ "$prev" == --path ]] && path=$arg
      prev=$arg
    done
    jq -n --arg path "$path" \
      '{status: "ok", project: {id: "sextant", path: $path, config: {worker: {agent: "codex"}}}}' \
      > "$FAKE_AO_STATE"
    ;;
  "project set-config")
    prev= config=
    for arg in "$@"; do
      [[ "$prev" == --config-json ]] && config=$arg
      prev=$arg
    done
    jq --argjson config "$config" '.project.config = $config' "$FAKE_AO_STATE" \
      > "$FAKE_AO_STATE.next"
    mv "$FAKE_AO_STATE.next" "$FAKE_AO_STATE"
    ;;
esac
"""

FAKE_GIT = """#!/usr/bin/env bash
printf 'git %s\\n' "$*" >> "$FAKE_LOG"
if [[ "$1" == clone ]]; then
  last=
  for arg in "$@"; do last=$arg; done
  mkdir -p "$last/.git"
  exit 0
fi
if [[ "$1" == -C ]]; then
  if [[ "$3 $4 $5" == "remote get-url origin" ]]; then
    case "$2" in
      *"/.ao/repos/sextant" | *"/.ao/repos/sextant/") echo "$FAKE_ARCHIVE_URL" ;;
      *) echo "$FAKE_REPO_URL" ;;
    esac
  fi
  exit 0
fi
exit 1
"""


def _run(
    tmp: Path,
    *args: str,
    pr: dict | None = None,
    version: str | None = None,
    worker: str | None = None,
    default_mode: str | None = None,
    default_branch: str = "main",
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
        "FAKE_DEFAULT_BRANCH": default_branch,
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


@pytest.mark.parametrize(
    ("default_branch", "base", "accepted"),
    [
        ("gate", "gate", True),  # gate is the repository's default branch today
        ("main", "main", True),  # and main after Phase 3's cutover
        ("gate", "main", False),  # the literal main is not a hand-off while gate is default
        ("main", "gate", False),  # nor gate after the cutover
    ],
)
def test_claim_reads_the_repository_default_branch(
    tmp_path: Path, default_branch: str, base: str, accepted: bool
) -> None:
    """The hand-off base is the repository's own default branch, read once, not the literal
    `main`: a gate PR hands off while gate is default, and the same check holds after the
    cutover. Fails before claim() reads the default branch, because the literal main refuses
    gate/gate, and it would fail if a non-default base were accepted."""
    run, calls = _run(
        tmp_path,
        "claim",
        "57",
        pr={**HANDED_OFF, "baseRefName": base},
        default_branch=default_branch,
    )
    assert run.returncode == (0 if accepted else 1), run.stderr
    assert any(call.startswith("spawn ") for call in calls) is accepted
    if not accepted:
        assert "default branch" in run.stderr
    # One read of the repository itself, through gh's own JSON and jq, per claim.
    repo_view = f"gh repo view {REPO} --json defaultBranchRef --jq .defaultBranchRef.name"
    assert calls.count(repo_view) == 1


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


PROJECT_CONFIG = {
    "agentConfig": {"model": "claude-opus-5-5", "effort": "max"},
    "worker": {"agent": "claude-code", "agentConfig": {}},
}
ARCHIVE = "https://github.com/seathatflowsinourveins/sextant-archive"


def _project(tmp_path: Path, path: Path, config: dict | None = PROJECT_CONFIG):
    """One `ao.sh project` run over a record at `path`, with offline ao and git."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("ao", FAKE_AO_PROJECT), ("git", FAKE_GIT)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    state = tmp_path / "ao-project.json"
    record = {"status": "ok", "project": {"id": "sextant", "path": str(path), "config": config}}
    state.write_text(json.dumps(record))
    env = {
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.defpath}",
        "FAKE_LOG": str(tmp_path / "calls"),
        "FAKE_AO_STATE": str(state),
        "FAKE_REPO_URL": REPO,
        "FAKE_ARCHIVE_URL": ARCHIVE,
    }
    env.pop("BASH_ENV", None)
    run = subprocess.run(["bash", str(AO), "project"], env=env, capture_output=True, text=True)
    calls = (tmp_path / "calls").read_text().splitlines()
    return run, calls, home, state, env


def test_project_recreates_the_record_and_the_clone_that_name_another_repository(
    tmp_path: Path,
) -> None:
    stale = tmp_path / "home" / ".ao" / "repos" / "sextant"
    stale.mkdir(parents=True)
    run, calls, home, state, env = _project(tmp_path, stale)
    assert run.returncode == 0, run.stderr
    clone = home / ".ao" / "repos" / "sextant-next"
    # The record and its clone are recreated in this repository, and the old clone is left alone.
    assert calls[0] == "ao project get sextant --json"
    assert f"git clone -q {REPO} {clone}" in calls
    assert f"git clone -q {REPO} {stale}" not in calls
    helper = "git -C {} config --local --add credential.https://github.com.helper !"
    assert any(call.startswith(helper.format(clone)) for call in calls), calls
    registered = (
        f"ao project add --path {clone} --id sextant --name Sextant (AO fix-CI/review) "
        "--worker-agent codex"
    )
    saved = json.dumps(PROJECT_CONFIG, separators=(",", ":"))
    restored = f"ao project set-config sextant --config-json {saved}"
    assert registered in calls and restored in calls

    def first(prefix: str) -> int:
        return next(index for index, call in enumerate(calls) if call.startswith(prefix))

    assert (
        first(f"git -C {clone} config")
        < calls.index("ao project rm sextant --yes")
        < calls.index(registered)
        < calls.index(restored)
    )
    # The lead-set worker, model and effort survive the recreation.
    assert json.loads(state.read_text())["project"]["config"] == PROJECT_CONFIG
    assert str(stale) in run.stdout and "not name" in run.stdout
    assert str(clone) not in run.stdout
    assert stale.is_dir(), "the script never removes the old clone itself"

    (tmp_path / "calls").unlink()
    again = subprocess.run(["bash", str(AO), "project"], env=env, capture_output=True, text=True)
    assert again.returncode == 0, again.stderr
    calls = (tmp_path / "calls").read_text().splitlines()
    assert calls[0] == "ao project get sextant --json"
    assert not [
        call
        for call in calls
        if call.startswith(
            ("git clone", "ao project rm", "ao project add", "ao project set-config")
        )
    ], calls
    assert str(stale) not in again.stdout, "the stale clone is reported once, not on every run"


def test_project_moves_a_record_that_points_outside_aos_clones_into_one(tmp_path: Path) -> None:
    outside = tmp_path / "home" / "work"
    outside.mkdir(parents=True)
    run, calls, home, _, _ = _project(tmp_path, outside)
    assert run.returncode == 0, run.stderr
    clone = home / ".ao" / "repos" / "sextant-next"
    # A checkout that names this repository but is not AO's own clone is reported, not written to.
    assert str(outside) in run.stdout and "left for the owner" in run.stdout
    assert not any(call.startswith(f"git -C {outside}") for call in calls)
    assert f"git clone -q {REPO} {clone}" in calls
    registered = (
        f"ao project add --path {clone} --id sextant --name Sextant (AO fix-CI/review) "
        "--worker-agent codex"
    )
    assert calls.index("ao project rm sextant --yes") < calls.index(registered)
    assert outside.is_dir()
