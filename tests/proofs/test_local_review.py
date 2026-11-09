"""Owner key policy through the actual adapter and workflow job conditions, 2026-11-09.

Replaces the retired gh-aw/JIT routing proofs. Upstream action contracts and sources
are recorded in .github/gate/upstreams.json; no provider or GitHub call runs here.
"""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[2]
WORKFLOWS = ROOT / ".github/workflows"


def _gate() -> dict:
    return yaml.safe_load((WORKFLOWS / "gate.yml").read_text())


@pytest.mark.parametrize("family", ["dsh", "codex", "claude"])
def test_review_jobs_use_hosted_runners_and_have_execution_bounds(family: str) -> None:
    job = _gate()["jobs"][family]
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == 30
    assert "daily" not in json.dumps(job)


def test_codex_review_uses_adr_0030_model_policy() -> None:
    job = _gate()["jobs"]["codex"]
    inputs = next(step for step in job["steps"] if step.get("id") == "review")["with"]
    assert inputs["model"] == "gpt-6.1-sol"
    assert inputs["effort"] == "max"
    assert inputs["permission-profile"] == ":read-only"
    native = json.loads((ROOT / ".devcontainer/agents/package.json").read_text())
    assert inputs["codex-version"] == native["dependencies"]["@openai/codex"]


def test_required_review_remains_bound_to_the_actions_app() -> None:
    for name in ("main", "live"):
        rules = json.loads((ROOT / ".github/rulesets" / f"{name}.json").read_text())
        required = next(rule for rule in rules["rules"] if rule["type"] == "required_status_checks")
        review = [
            check
            for check in required["parameters"]["required_status_checks"]
            if check["context"] == "review"
        ]
        assert review == [{"context": "review", "integration_id": 15368}]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("", ["dsh"]),
        ("Agent-Family codex", ["dsh"]),
        ("Agent-Family claude", ["dsh"]),
        ("Agent-Family muse", ["dsh"]),
        ("Agent-Family agy", ["dsh"]),
        ("Agent-Family dsh", ["dsh", "codex"]),
        ("Agent-Family dsh\nReview-Family claude", ["dsh", "claude"]),
        ("Agent-Family dsh\nReview-Family codex", ["dsh", "codex"]),
        ("Agent-Family codex\nReview-Family dsh", ["dsh"]),
        ("Agent-Family codex\nReview-Family claude", []),
        ("Agent-Family claude\nReview-Family codex", []),
        ("Agent-Family dsh\nReview-Family dsh", []),
        ("Agent-Family codex\nReview-Family codex", []),
        ("Agent-Family dsh\nAgent-Family codex", []),
        ("Review-Family claude", []),
        ("Agent-Family: dsh", []),
        ("Agent-Family  dsh", []),
        ("Agent-Family dsh\nReview-Family opus", []),
    ],
)
def test_owner_key_policy_routing(body: str, expected: list[str]) -> None:
    conditions = {family: _gate()["jobs"][family]["if"] for family in ("dsh", "codex", "claude")}
    done = subprocess.run(
        [
            "node",
            "-e",
            "const fs=require('node:fs'), vm=require('node:vm');"
            "const {body, conditions}=JSON.parse(fs.readFileSync(0,'utf8'));"
            "const gate=require('./.github/gate/gate.cjs'); let active=[], denied=[];"
            "try {const route=gate.route(body, []);"
            "const select=ready=>Object.entries(conditions).filter(([family,expression])=>"
            "vm.runInNewContext(expression,{needs:{source:{outputs:{ready,quality:route.quality}}}}))"
            ".map(([family])=>family); active=select('true');denied=select('false');} catch {}"
            "console.log(JSON.stringify({active,denied}));",
        ],
        cwd=ROOT,
        input=json.dumps({"body": body, "conditions": conditions}),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert json.loads(done.stdout) == {"active": expected, "denied": []}


def test_routing_is_selected_only_from_a_completed_ci_run() -> None:
    workflow = _gate()
    assert workflow.get("on", workflow.get(True)) == {
        "workflow_run": {"workflows": ["ci"], "types": ["completed"]}
    }
