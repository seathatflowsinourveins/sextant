"""The workflow_run gate accepts the existing App's PR heads without an actor-family shortcut."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]


def test_api_reviewers_allow_the_existing_app_bot() -> None:
    bot = json.loads((ROOT / "deploy/wsl/github-app.json").read_text())["app_slug"] + "[bot]"
    workflow = yaml.safe_load((ROOT / ".github/workflows/gate.yml").read_text())
    for family, key in (("codex", "allow-bot-users"), ("claude", "allowed_bots")):
        step = next(
            step for step in workflow["jobs"][family]["steps"] if step.get("id") == "review"
        )
        assert bot in step["with"][key].split(",")


def test_default_dsh_review_has_no_actor_membership_shortcut() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/gate.yml").read_text())
    assert workflow["jobs"]["dsh"]["if"] == "needs.source.outputs.ready == 'true'"
    source = (ROOT / ".github/gate/gate.cjs").read_text()
    assert "run.workflow_id" in source and "pr.head.sha === run.head_sha" in source
