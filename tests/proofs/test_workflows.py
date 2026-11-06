"""Saved Workflows: adopt the pinned upstream parser, routing and failure checks.

Source: northstar@b384d298d217d3f8d9aa83356994629536a34795:
evals/workflows/{check-syntax.sh,check-models.mjs,mock-runtime.mjs,run-scenarios.mjs}.
These are offline proofs; they do not run Claude Code or certify trading merit.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
PROOFS = ROOT / "tests" / "proofs"
NAMES = ("research-plan-build", "adversarial-verify", "backtest-tournament")
OBSOLETE = re.compile(
    r"(?:/Users/|/home/|~/Developer/)[^\s'\"`]*northstar"
    r"|\bbeads\b|\bbd\s+(?:create|list|show|close|update|ready|memories)\b"
    r"|\bns-(?:lane|runtime)\b|reports/verify/|verify-record"
)
CHECK_MODELS = """
import { readFileSync } from 'node:fs';
import { check, agentCalls } from './tests/proofs/workflow-models.mjs';
const src = readFileSync(process.argv[1], 'utf8');
const problems = check(src);
if (!agentCalls(src).length) problems.push('no agent() calls checked');
if (problems.length) throw new Error(problems.join('\\n'));
"""


@pytest.mark.parametrize("name", NAMES)
def test_saved_workflows(name: str, tmp_path: Path) -> None:
    path = ROOT / ".claude" / "workflows" / f"{name}.js"
    assert path.is_file(), f"missing saved workflow: {name}"
    source = path.read_text()
    assert source.startswith("export const meta = {\n"), name
    assert not OBSOLETE.search(source), name
    assert not re.search(r"Date\.now\(\)|Math\.random\(\)|new Date\(\)", source), name
    # The saved format has both export-meta and an async body with top-level return.
    # Parse it in the same wrapper as the source's check-syntax.sh, not as an ES module.
    wrapped = tmp_path / "workflow.mjs"
    wrapped.write_text(
        "async function __wf(agent, parallel, pipeline, phase, log, args, budget, workflow) {\n"
        + source.replace("export const meta", "const meta", 1)
        + "\n}\n"
    )
    for command in (
        ["node", "--check", str(wrapped)],
        ["node", "--input-type=module", "-e", CHECK_MODELS, str(path)],
    ):
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
        assert done.returncode == 0, done.stdout + done.stderr


def test_workflow_agent_budget() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
    assert settings["env"].get("CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS") == "8"


def test_workflow_failures_stay_visible() -> None:
    done = subprocess.run(
        ["node", "--test", str(PROOFS / "workflow-scenarios.mjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stdout + done.stderr
