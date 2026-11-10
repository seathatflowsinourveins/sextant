"""The standard AO Codex hand-off keeps a Claude PR's default review outside both families.

Source: AO v0.14.10 033d597032e448a0ea16c298350e36b099f74106 and the
2026-11-09 owner key policy. All git, gh and ao calls are offline stubs.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from test_local_review import test_owner_key_policy_routing as assert_reviewers

ROOT = Path(__file__).parents[2]
STUB = (
    f"#!{sys.executable}\n"
    + """
import json, os, sys
from pathlib import Path
tool, args = Path(sys.argv[0]).name, sys.argv[1:]
with open(os.environ['FIXTURE_LOG'], 'a') as log:
    log.write(json.dumps({'tool': tool, 'args': args}) + '\\n')
if tool == 'git':
    target = args[-1] if args[0] == 'clone' else args[1]
    assert Path(target).is_relative_to(Path(os.environ['HOME'])), args
if tool == 'ao' and args[:2] == ['project', 'get']:
    sys.exit(0 if os.environ['FIXTURE_PROJECT_EXISTS'] == '1' else 1)
if tool == 'gh' and args[:2] == ['repo', 'view']:
    assert args[3:] == ['--json', 'defaultBranchRef', '--jq', '.defaultBranchRef.name'], args
    print('main')
elif tool == 'gh':
    assert args[:2] == ['pr', 'view'], args
    fields = args[args.index('--json') + 1].split(',')
    pr = json.loads(Path(os.environ['FIXTURE_PR']).read_text())
    print(json.dumps({field: pr[field] for field in fields}))
"""
)


def _handoff(tmp_path: Path, body: str, existing_project: bool = False):
    bins = tmp_path / "bin"
    bins.mkdir()
    unavailable_python = bins / "python3"
    unavailable_python.write_text("#!/bin/sh\nexit 127\n")
    unavailable_python.chmod(0o755)
    for tool in ("git", "gh", "ao"):
        binary = bins / tool
        binary.write_text(STUB)
        binary.chmod(0o755)
    pr_file, log = tmp_path / "pr.json", tmp_path / "calls.jsonl"
    pr_file.write_text(
        json.dumps(
            {
                "state": "OPEN",
                "isDraft": False,
                "baseRefName": "main",
                "headRefName": "claude-lane",
                "headRefOid": "a" * 40,
                "autoMergeRequest": {"mergeMethod": "SQUASH"},
                "statusCheckRollup": [{"name": "ci", "status": "COMPLETED"}],
                "body": body,
            }
        )
    )
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "PATH": f"{bins}:{os.defpath}",
        "FIXTURE_PR": str(pr_file),
        "FIXTURE_LOG": str(log),
        "FIXTURE_PROJECT_EXISTS": "1" if existing_project else "0",
    }
    for args in (("project",), ("claim", "65")):
        done = subprocess.run(
            ["bash", str(ROOT / "deploy/wsl/ao.sh"), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if args == ("project",):
            assert done.returncode == 0, done.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return done, calls


@pytest.mark.parametrize("existing_project", [False, True])
def test_ao_codex_handoff_of_a_claude_pr_defaults_to_dsh(tmp_path: Path, existing_project) -> None:
    body = "Agent-Family claude"
    done, calls = _handoff(tmp_path, body, existing_project)
    assert done.returncode == 0, done.stderr
    registrations = [c["args"] for c in calls if c["args"][:2] == ["project", "add"]]
    assert len(registrations) == (0 if existing_project else 1)
    if registrations:
        registration = registrations[0]
        assert registration[registration.index("--worker-agent") + 1] == "codex"
    spawn = next(c["args"] for c in calls if c["args"][0] == "spawn")
    assert spawn[spawn.index("--claim-pr") + 1] == "65"
    assert spawn[spawn.index("--branch") + 1] == "claude-lane"
    assert spawn[spawn.index("--agent") + 1] == "codex"
    prompt = spawn[spawn.index("--prompt") + 1]
    assert "Never alter the PR body's Agent-Family or Review-Family markers." in prompt
    view = next(c["args"] for c in calls if c["tool"] == "gh")
    assert "body" in view[view.index("--json") + 1].split(",")
    # A fix push uses the same author body and the installed App actor. Its new head
    # must select dsh, outside the original Claude author and the AO Codex worker.
    # The gh stand-in rejects edits instead of pretending a fixture reread proves this.
    config = yaml.safe_load((ROOT / ".github/workflows/gate.yml").read_text())
    assert config.get("on", config.get(True))["workflow_run"]["workflows"] == ["ci"]
    assert_reviewers(body, ["dsh"])


@pytest.mark.parametrize(
    "body",
    [
        "Agent-Family claude\nReview-Family codex",
        "Agent-Family dsh\nReview-Family codex",
        "Agent-Family CLAUDE\nReview-Family CODEX",
        "Agent-Family claude\n<!-- Review-Family codex -->",
    ],
)
def test_ao_codex_worker_refuses_a_codex_reviewer(tmp_path: Path, body: str) -> None:
    done, calls = _handoff(tmp_path, body)
    assert done.returncode == 1, done.stderr
    assert "reviewer" in done.stderr and "Codex" in done.stderr
    assert not any(c["args"][0] == "spawn" for c in calls)
