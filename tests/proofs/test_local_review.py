"""Three-family review adopts main's local JIT profiles without weakening routing.

Source: gh-aw v1.0.1 reference/self-hosted-runners.md and ARC/DinD references;
ADR-0001 records #201's superseding local-compute decision. These proofs inspect
actual compiled job selections and evaluate source and compiled routing gates.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
TEMPLATE = (ROOT / ".github/pull_request_template.md").read_text()


@pytest.mark.parametrize("name", ["review", "review-claude", "review-codex"])
def test_review_agent_uses_docker_and_framework_jobs_use_sealed(name: str) -> None:
    compiled = yaml.safe_load((WORKFLOWS / f"{name}.lock.yml").read_text())
    jobs = compiled["jobs"]
    assert {"agent", "pre_activation", "activation", "safe_outputs", "conclusion"} <= jobs.keys(), (
        name
    )
    assert jobs["agent"]["runs-on"] == ["self-hosted", "linux", "x64", "sextant-jit-docker"]
    for job_name, job in jobs.items():
        if job_name != "agent":
            assert job["runs-on"] == ["self-hosted", "linux", "x64", "sextant-jit-sealed"], (
                f"{name}/{job_name}: framework jobs must use the Docker-free sealed JIT profile"
            )


def test_codex_review_uses_adr_0030_model_policy() -> None:
    """ADR-0030 (#97): the owner's workhorse, max effort, and no model fallback."""
    source = (WORKFLOWS / "review-codex.md").read_text()
    compiled = (WORKFLOWS / "review-codex.lock.yml").read_text()
    assert re.search(r"(?m)^model: gpt-6\.1-sol$", source)
    metadata = json.loads(compiled.splitlines()[0].removeprefix("# gh-aw-metadata: "))
    assert metadata["agent_model"] == "gpt-6.1-sol"
    runtime_model = re.search(r"(?m)^ +GH_AW_MODEL_AGENT_CODEX: (.+)$", compiled)
    assert runtime_model
    assert runtime_model[1] == "gpt-6.1-sol"
    config = re.search(r"GH_AW_CODEX_CONFIG_JSON: '([^\n]+)'", compiled)
    assert config
    assert json.loads(config[1])["overrides"]["model_reasoning_effort"] == "max"
    native = json.loads((ROOT / ".devcontainer/agents/package.json").read_text())
    assert metadata["engine_versions"]["codex"] == native["dependencies"]["@openai/codex"]
    fallback = re.search(r'\\"modelFallback\\":(\{[^}]+\})', compiled)
    assert fallback
    assert json.loads(fallback[1].replace('\\"', '"')) == {"enabled": False}


@pytest.mark.parametrize("name", ["review", "review-claude", "review-codex"])
def test_daily_credit_quota_cannot_skip_an_authorised_review(name: str) -> None:
    """ADR-0030 #5: the compiler's inherited daily-5000 gate must not block review."""
    compiled = yaml.safe_load((WORKFLOWS / f"{name}.lock.yml").read_text())
    activation = compiled["jobs"]["activation"]
    environments = [compiled.get("env", {}), activation.get("env", {})]
    environments.extend(step.get("env", {}) for step in activation["steps"])
    assert not any(env.get("GH_AW_MAX_DAILY_AI_CREDITS") for env in environments)
    guards = [
        step
        for step in activation["steps"]
        if step.get("id") == "daily-ai-credits-workflow-guardrail"
    ]
    assert all("env.GH_AW_MAX_DAILY_AI_CREDITS != ''" in step["if"] for step in guards)


def test_pr_code_and_source_checks_use_the_sealed_jit_profile() -> None:
    for name in ("ci", "source"):
        workflow = yaml.safe_load((WORKFLOWS / f"{name}.yml").read_text())
        selections = [job.get("runs-on") for job in workflow["jobs"].values()]
        assert selections, name
        assert all(
            selection == ["self-hosted", "linux", "x64", "sextant-jit-sealed"]
            for selection in selections
        ), name


def test_required_review_remains_bound_to_the_actions_app() -> None:
    for name in ("main", "live"):
        rules = json.loads((ROOT / ".github" / "rulesets" / f"{name}.json").read_text())
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
        ("Agent-Family dsh", ["claude"]),
        ("Agent-Family codex\nReview-Family dsh", ["dsh"]),
        ("Agent-Family codex\nReview-Family claude", ["claude"]),
        ("Agent-Family claude\nReview-Family dsh", ["dsh"]),
        ("Agent-Family claude\nReview-Family codex", ["codex"]),
        ("Agent-Family dsh\nReview-Family claude", ["claude"]),
        ("Agent-Family dsh\nReview-Family codex", ["codex"]),
        ("Agent-Family codex\nReview-Family codex", []),
        ("Agent-Family claude\nReview-Family claude", []),
        ("Agent-Family dsh\nReview-Family dsh", []),
        ("Agent-Family codex\nReview-Family dsh\nReview-Family claude", []),
        ("Agent-Family dsh\nReview-Family claude\nReview-Family codex", []),
        ("Agent-Family claude\nReview-Family codex\nReview-Family dsh", []),
        ("Agent-Family CODEX\nReview-Family CLAUDE", ["claude"]),
        ("Review-Family codex", []),
        ("Review-Family claude", []),
        ("Review-Family dsh", []),
        ("Agent-Family: dsh", []),
        ("Agent-Family  dsh", []),
        ("Agent-Family\u00a0dsh", []),
        (TEMPLATE, []),
        (
            re.sub(r"(?m)^Review-Family .*$", "Review-Family claude", TEMPLATE),
            [],
        ),
        (re.sub(r"(?m)^Agent-Family .*$", "Agent-Family codex", TEMPLATE), []),
        (
            re.sub(
                r"(?m)^Review-Family .*$",
                "Review-Family claude",
                re.sub(r"(?m)^Agent-Family .*$", "Agent-Family codex", TEMPLATE),
            ),
            ["claude"],
        ),
        ("Agent-Family codex\nReview-Family: claude", []),
        ("Agent-Family claude\nReview-Family  codex", []),
        ("Agent-Family dsh\nReview-Family\u00a0codex", []),
        ("Agent-Family codex\nReview-Family opus", []),
        ("Review-Family opus", []),
        ("Agent-Family dsh\nAgent-Family codex", []),
        ("Agent-Family dsh\nAgent-Family claude", []),
        ("Agent-Family claude\nAgent-Family codex", []),
        ("Agent-Family codex\nAgent-Family claude\nReview-Family dsh", []),
        ("Agent-Family dsh\nAgent-Family codex\nReview-Family claude", []),
        ("Agent-Family dsh\nAgent-Family claude\nReview-Family codex", []),
        ("Agent-Family codex\nAgent-Family claude\nReview-Family codex", []),
        ("Agent-Family codex\nAgent-Family claude\nReview-Family claude", []),
        ("Agent-Family dsh\nAgent-Family codex\nReview-Family dsh", []),
        ("Agent-Family dsh\nAgent-Family codex\nReview-Family codex", []),
        ("Agent-Family dsh\nAgent-Family claude\nReview-Family dsh", []),
        ("Agent-Family dsh\nAgent-Family claude\nReview-Family claude", []),
        ("Agent-Family codex\nAgent-Family claude\nAgent-Family dsh", []),
    ],
)
def test_one_reviewer_outside_the_author_family(body: str, expected: list[str]) -> None:
    expressions = {"authored": {}, "pre_activation": {}, "activation": {}}
    for family, name in (("dsh", "review"), ("claude", "review-claude"), ("codex", "review-codex")):
        source = WORKFLOWS / f"{name}.md"
        assert source.is_file(), f"missing reviewer: {name}"
        expression = re.search(r"(?m)^if: (.+)$", source.read_text())
        assert expression, f"missing reviewer condition: {name}"
        expressions["authored"][family] = (
            expression[1].strip('"').removeprefix("${{").removesuffix("}}")
        )
        compiled = yaml.safe_load((WORKFLOWS / f"{name}.lock.yml").read_text())
        for stage in ("pre_activation", "activation"):
            expressions[stage][family] = compiled["jobs"][stage]["if"].strip()
    # These conditions use only GitHub's contains, !, && and ||. Evaluate the actual
    # authored expressions, with contains' documented case-insensitive string semantics.
    done = subprocess.run(
        [
            "node",
            "-e",
            "const fs = require('node:fs'), vm = require('node:vm');"
            "const {body, expressions} = JSON.parse(fs.readFileSync(0, 'utf8'));"
            "const select = activated => {"
            "const context = {github: {event: {pull_request: {body}}},"
            "needs: {pre_activation: {outputs: {activated}}},"
            "contains: (a, b) => String(a).toLowerCase().includes(String(b).toLowerCase())};"
            "return Object.fromEntries(Object.entries(expressions).map("
            "([stage, conditions]) => [stage, Object.keys(conditions).filter(family =>"
            "vm.runInNewContext(conditions[family], context))])); };"
            "console.log(JSON.stringify({active: select('true'), denied: select('false')}));",
        ],
        input=json.dumps({"body": body, "expressions": expressions}),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert json.loads(done.stdout) == {
        "active": {stage: expected for stage in expressions},
        "denied": {**{stage: expected for stage in expressions}, "activation": []},
    }


@pytest.mark.parametrize("name", ["review", "review-claude", "review-codex"])
def test_only_opening_or_a_new_head_selects_a_reviewer(name: str) -> None:
    compiled = yaml.safe_load((WORKFLOWS / f"{name}.lock.yml").read_text())
    # PyYAML resolves an unquoted YAML 1.1 `on` key to True.
    events = compiled.get("on", compiled.get(True))
    assert set(events["pull_request_target"]["types"]) == {"opened", "synchronize"}
