"""Hosted dsh worker invariants.

One dispatched ``dsh`` headless job edits the checked-out workspace, then
``create-pull-request`` opens a PR into the repository's default branch. The
job is owner-only, runs only on that default branch, has minimal write
permissions, never receives a broker/paper/live key, loads the repository
hard-lines bundle, and mints its pull-request token from the
``hosted-workers`` environment's App installation.

Sources: GitHub workflow_dispatch/permissions/concurrency documentation and the
``github`` context's ``repository.default_branch`` field, read 2026-11-09;
PerryLink/dsh-github@2fc0009c:action.yml:51-62,118-161 and
scripts/action-patch.mjs:49-152; peter-evans/create-pull-request@v8.1.1
README.md:50-95; actions/create-github-app-token@v3.3.0 action.yml.
"""

import json
import re
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github/workflows/dsh-worker.yml"
BRIEFS = ROOT / ".github/dsh-workers/briefs"


def _workflow() -> dict[str, Any]:
    data = yaml.safe_load(WORKFLOW.read_text())
    assert isinstance(data, dict)
    return cast(dict[str, Any], data)


def _job() -> dict[str, Any]:
    return _workflow()["jobs"]["worker"]


def _step(name: str) -> dict[str, Any]:
    return next(step for step in _job()["steps"] if step.get("name") == name)


def test_one_hosted_job_per_owner_dispatch_on_the_default_branch() -> None:
    workflow = _workflow()
    if "on" in workflow:
        events = workflow["on"]
    else:
        events = cast(dict[Any, Any], workflow)[True]
    assert isinstance(events, dict)
    assert list(events) == ["workflow_dispatch"]
    assert set(events["workflow_dispatch"]["inputs"]) == {"brief", "slug"}
    job = _job()
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["environment"] == "hosted-workers"
    assert job["if"] == (
        "${{ github.actor == github.repository_owner && "
        "github.ref == format('refs/heads/{0}', github.event.repository.default_branch) }}"
    )
    # No branch is named in the file: the only ref is the default-branch placeholder, so the
    # gate-to-main rename needs no edit here.
    assert re.search(r"refs/heads/(?!\{0\})", WORKFLOW.read_text()) is None
    assert job["permissions"] == {"contents": "write", "pull-requests": "write"}
    assert job["concurrency"] == {
        "group": "dsh-worker-${{ inputs.slug }}",
        "cancel-in-progress": False,
    }
    assert len(workflow["jobs"]) == 1
    assert "pull_request_target" not in workflow
    assert "pull_request" not in events


def test_worker_never_receives_paper_live_or_broker_keys() -> None:
    text = WORKFLOW.read_text()
    assert "environment: hosted-workers" in text
    assert "environment: paper" not in text
    assert "environment: live" not in text
    for forbidden in (
        "ALPACA_API_KEY",
        "ALPACA_SECRET",
        "APCA_API",
        "IBKR_",
        "IB_GATEWAY",
        "BROKER_",
        "PAPER_",
        "LIVE_",
    ):
        assert forbidden not in text
    assert set(re.findall(r"secrets\.([A-Z0-9_]+)", text)) == {
        "DEEPSEEK_API_KEY",
        "SEXTANT_APP_PRIVATE_KEY",
    }
    assert "github.token" not in text
    assert "vars.SEXTANT_APP_ID" in text
    assert "contents: write" in text
    assert "pull-requests: write" in text


def test_deepseek_key_reaches_only_the_dsh_step() -> None:
    carriers = [step for step in _job()["steps"] if "DEEPSEEK_API_KEY" in step.get("env", {})]
    assert [step.get("id") for step in carriers] == ["worker"]
    assert carriers[0]["env"]["DEEPSEEK_API_KEY"] == "${{ secrets.DEEPSEEK_API_KEY }}"
    for step in _job()["steps"]:
        if "run" in step:
            assert "echo" not in step["run"].lower() or step.get("id") != "worker"


def test_pins_are_full_sha_and_upstream_parts_are_used() -> None:
    uses = [step["uses"] for step in _job()["steps"] if "uses" in step]
    assert len(uses) == 4
    for reference in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", reference), reference
    assert [reference.split("@")[1] for reference in uses] == [
        "3d3c42e5aac5ba805825da76410c181273ba90b1",
        "949feb2413d6458794dcd2491c4babbbce0c15c1",
        "64ab729a6294000f5aa4a4bc0b73d1f32bc45510",
        "5f6978faf089d4d20b00c7766989d076bb2fc7f1",
    ]
    generate = _step("Generate the worker overlay and task from the brief")
    assert generate["run"] == "node .github/actions/dsh-github/scripts/action-patch.mjs"
    assert generate["env"]["INPUT_TASK"] == "report"
    assert generate["env"]["INPUT_TASK_PROMPT"] == "${{ steps.brief.outputs.text }}"
    parity = _step("Compose the parity profile with the hard-lines bundle")
    assert "python3 .github/gate/parity-entry.py" in parity["run"]
    worker = _step("Run the dsh headless worker")
    assert "dsh --profile headless --patch" in worker["run"]


def test_hard_lines_load_and_review_guards_are_disabled() -> None:
    profile = json.loads((ROOT / ".github/gate/dsh-profile.json").read_text())
    assert "config/dsh/hard-lines" in {row["spec"] for row in profile["bundles"]}
    parity = (ROOT / ".github/gate/parity-entry.py").read_text()
    assert 'row["spec"].startswith(("config/", ".github/"))' in parity
    text = WORKFLOW.read_text()
    assert "config/dsh/mcp/max-effort.cordis.yml" in text
    assert ".github/gate/headless-services.cordis.yml" in text
    guards = _step("Disable the review-only guards and set the worker persona")["run"]
    assert "- id: sextant-gate-api-only" in guards
    assert "- id: dsh-github" in guards
    assert guards.count("disabled: true") == 2


def test_brief_is_repo_local_and_pr_body_is_sibling() -> None:
    validate = _step("Validate the brief and slug")["run"]
    assert '[[ "$BRIEF" != .github/dsh-workers/briefs/*.md ]]' in validate
    assert '*"/../"*' in validate
    assert 'PR_BODY="${BRIEF%.md}.pr.md"' in validate
    assert 'echo "pr_body=$PR_BODY"' in validate
    checkout = next(
        step for step in _job()["steps"] if step.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"] == {
        "ref": "${{ github.sha }}",
        "fetch-depth": 1,
        "persist-credentials": False,
    }


def test_cpr_uses_the_app_token() -> None:
    cpr = _step("Open the worker pull request")
    assert cpr["with"]["token"] == "${{ steps.app-token.outputs.token }}"  # noqa: S105
    assert cpr["with"]["base"] == "${{ github.event.repository.default_branch }}"
    assert cpr["with"]["branch"] == "dsh-worker/${{ inputs.slug }}"
    assert cpr["with"]["body-path"] == "${{ steps.brief.outputs.pr_body }}"
    mint = _step("Mint the pull-request app token")
    assert mint["id"] == "app-token"
    assert "if" not in mint
    assert mint["with"]["app-id"] == "${{ vars.SEXTANT_APP_ID }}"
    assert mint["with"]["private-key"] == "${{ secrets.SEXTANT_APP_PRIVATE_KEY }}"
    assert "github.token" not in WORKFLOW.read_text()


def test_noop_brief_and_body_exist() -> None:
    brief = BRIEFS / "noop-docs.md"
    body = BRIEFS / "noop-docs.pr.md"
    assert brief.is_file()
    assert body.is_file()
    assert "docs/handbook/worker-smoke.md" in brief.read_text()
    assert '"Hosted dsh workers: one dispatched headless job on a free public runner"' in (
        body.read_text()
    )
    assert body.read_text().startswith("Agent-Family dsh\nReview-Family codex\n")


def test_manifest_row_names_the_worker_and_its_proofs() -> None:
    manifest = (ROOT / "docs/manifest.md").read_text()
    name = "Hosted dsh workers: one dispatched headless job on a free public runner"
    assert f"| {name} |" in manifest
    row = next(line for line in manifest.splitlines() if line.startswith(f"| {name} |"))
    assert "test_dsh_worker.py::test_one_hosted_job_per_owner_dispatch_on_the_default_branch" in row
    assert "test_dsh_worker.py::test_cpr_uses_the_app_token" in row
    assert "PerryLink/dsh-github@v0.7.27" in row
    assert "peter-evans/create-pull-request@v8.1.1" in row
