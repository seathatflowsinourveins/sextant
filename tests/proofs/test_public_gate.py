"""Public gate invariants; GitHub workflow_run/REST and upstream composite contracts.

Sources: .github/gate/upstreams.json and google/eng-practices@3bb3ec25:
review/reviewer/standard.md:31-34,72,88-90; review/developer/small-cls.md:175.
"""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
WORKFLOWS = ROOT / ".github/workflows"


def _gate() -> dict:
    return yaml.safe_load((WORKFLOWS / "gate.yml").read_text())


def test_no_workflow_requests_a_local_runner_or_privileged_pr_trigger() -> None:
    for path in (*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")):
        workflow = yaml.safe_load(path.read_text())
        events = workflow.get("on", workflow.get(True))
        assert "pull_request_target" not in events, path
        for job in workflow["jobs"].values():
            assert job["runs-on"] == "ubuntu-24.04", path


def test_gate_runs_only_after_ci_from_the_default_branch() -> None:
    gate = _gate()
    assert gate.get("on", gate.get(True)) == {
        "workflow_run": {"workflows": ["ci"], "types": ["completed"]}
    }
    for job in gate["jobs"].values():
        for step in job["steps"]:
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"] == {
                    "ref": "${{ github.sha }}",
                    "persist-credentials": False,
                }


def test_danger_reads_api_data_and_never_checks_out_the_head() -> None:
    source = _gate()["jobs"]["source"]
    danger = next(step for step in source["steps"] if step.get("id") == "danger")
    assert "--dangerfile dangerfile.js --failOnErrors" in danger["run"]
    assert danger["env"]["DANGER_EVENT_PATH"] == "${{ steps.prepare.outputs.danger_event }}"
    assert danger["run"].startswith('GITHUB_EVENT_PATH="$DANGER_EVENT_PATH" ')
    assert not any("run" in step and "checkout" in step["run"] for step in source["steps"])


def test_dangers_native_provider_accepts_the_api_only_event(tmp_path: Path) -> None:
    """Danger 14.1.0 GitHubActions constructor/useEventDSL, without network calls."""
    executable = shutil.which("danger")
    assert executable is not None
    event = tmp_path / "danger-event.json"
    event.write_text(
        json.dumps({"pull_request": {"number": 7, "base": {"repo": {"full_name": "owner/repo"}}}})
    )
    done = subprocess.run(
        [
            "node",
            "-e",
            "const {createRequire}=require('node:module');"
            "const load=createRequire(process.argv[1]);"
            "const {GitHubActions}=load('danger/distribution/ci_source/providers/GitHubActions');"
            "const source=new GitHubActions({GITHUB_EVENT_PATH:process.argv[2],"
            "GITHUB_WORKFLOW:'gate'});"
            "process.stdout.write(JSON.stringify([source.useEventDSL,"
            "source.pullRequestID,source.repoSlug]));",
            str(Path(executable).resolve()),
            str(event),
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [False, 7, "owner/repo"]


def test_every_action_in_workflows_and_composites_has_a_full_pin() -> None:
    paths = [*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")]
    paths += list((ROOT / ".github/actions").rglob("action.y*ml"))
    for path in paths:
        data = yaml.safe_load(path.read_text())
        groups = [data["runs"]] if "runs" in data else data["jobs"].values()
        for group in groups:
            for step in group.get("steps", []):
                action = step.get("uses", "")
                if action and not action.startswith("./"):
                    assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", action), (path, action)


def test_ci_runs_the_complete_check_without_repository_secrets() -> None:
    text = (WORKFLOWS / "ci.yml").read_text()
    ci = yaml.safe_load(text)
    assert set(ci.get("on", ci.get(True))) == {"pull_request"}
    assert ci["permissions"] == {"contents": "read"}
    assert any(step.get("run") == "just ci" for step in ci["jobs"]["ci"]["steps"])
    assert "secrets." not in text
    assert "enable-cache: false" in text and "package-manager-cache: false" in text


def test_fork_pr_workflows_never_bind_repository_secrets() -> None:
    """GitHub events-that-trigger-workflows#pull_request, fork PR secrets, read 2026-11-09.

    Owner ruling 00:58 replaces the live fork run with this static proof and the
    all_external_contributors API receipt in the handoff scratch/receipts directory.
    """
    found = []
    for path in (*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")):
        text = path.read_text()
        workflow = yaml.safe_load(text)
        events = workflow.get("on", workflow.get(True))
        if "pull_request" in events:
            found.append(path.name)
            assert "secrets." not in text, path
    assert "ci.yml" in found


def test_parity_set_has_twenty_four_bundles_and_no_memory_plugins() -> None:
    profile = json.loads((ROOT / ".github/gate/dsh-profile.json").read_text())
    assert len(profile["bundles"]) == 24
    names = {row["package"] for row in profile["bundles"]}
    assert "@deepseek-ai/dsh-headless" in names
    assert not any(re.search(r"memento|engram|openviking", name, re.I) for name in names)
    assert profile["engine_authority"] == "reuses main's dsh pin (lead ruling 2026-11-09)"


def test_dsh_github_scripts_are_unchanged_at_the_qualifying_upstream_pin() -> None:
    expected = {
        "action-patch.mjs": "a897b80da6c1a42f32261e54a92e2bd1163dd075e0574edc4c336b96ceb3e797",
        "action-post.mjs": "f8df0a576aefe1ff68e2c45caae276bf06ecae6eeba5648346a7ff0cf0981875",
    }
    for filename, digest in expected.items():
        script = ROOT / ".github/actions/dsh-github/scripts" / filename
        assert hashlib.sha256(script.read_bytes()).hexdigest() == digest


def test_landing_standard_and_fail_on_error_are_wired_into_the_verdict() -> None:
    rules = (WORKFLOWS / "shared/review-rules.md").read_text().split("## Report", 1)[1]
    for required in (
        "3bb3ec25b3b0199f4940b1aa75f0ac5c5753301c",
        "standard.md:31-34,72,88-90",
        "small-cls.md:175",
        "concrete failing witness at the exact head",
        "input or state",
        "wrong output, crash or failing test",
        "speculative or unwitnessed",
        "From the third reviewed commit, only a P0 blocks",
        "ONE follow-up issue per PR",
        "fail-on: error",
    ):
        assert required in rules
    dsh = _gate()["jobs"]["dsh"]
    review = next(step for step in dsh["steps"] if step.get("id") == "review")
    assert review["with"]["blocking"] == "true"
    assert review["with"]["fail-on"] == "error"
    adapter = (ROOT / ".github/gate/gate.cjs").read_text()
    assert ".github/workflows/shared/review-rules.md" in adapter


def test_key_policy_and_failure_paths_execute_against_the_actual_adapter() -> None:
    done = subprocess.run(
        ["node", "--test", "tests/proofs/public-gate.test.cjs"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert done.returncode == 0, done.stdout + done.stderr
