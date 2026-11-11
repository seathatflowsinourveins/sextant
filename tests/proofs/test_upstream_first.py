"""Upstream first: a code brief names what the official upstream ships before anything is built."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
CHECK = ROOT / "scripts/brief_check.py"
AGENTS = (ROOT / "AGENTS.md").read_text()
RULE_ONE = AGENTS.split("## Rule 1:", 1)[1].split("## Rule 2:", 1)[0]

FILLED = """# A task

## Upstream first
- Shipped piece: nautechsystems/nautilus_trader@v2.0.0rc8 crates/live/src/node/mod.rs:1430-1462
- Verdict: use as is
- Where searched: the engine's live node and its config, terms "inflight", "open_check"

## Deliverable
"""


def _check(text: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(CHECK), "-"], input=text, capture_output=True, text=True
    )


def test_a_filled_section_passes() -> None:
    assert _check(FILLED).returncode == 0


def test_a_brief_without_the_section_is_refused() -> None:
    result = _check("# A task\n\n## Deliverable\n- build it\n")
    assert result.returncode == 1
    assert "Upstream first" in result.stderr


def test_each_empty_field_is_refused_by_name() -> None:
    for field in ("Shipped piece", "Verdict", "Where searched"):
        lines = [
            f"- {field}:" if line.startswith(f"- {field}:") else line for line in FILLED.splitlines()
        ]
        result = _check("\n".join(lines))
        assert result.returncode == 1, field
        assert field in result.stderr


def test_the_verdict_is_one_of_the_three() -> None:
    for verdict in ("use as is", "Build on: ours adds the ledger line", "KEEP OURS"):
        assert _check(FILLED.replace("use as is", verdict)).returncode == 0, verdict
    result = _check(FILLED.replace("use as is", "rewrite it"))
    assert result.returncode == 1
    assert "Verdict" in result.stderr


def test_agents_rule_one_states_upstream_first_and_the_candidate_rule() -> None:
    assert "names what the official upstream already ships" in RULE_ONE
    assert "use as is, build on, or keep ours" in RULE_ONE
    assert "is re-scoped to use it" in RULE_ONE
    assert "is a candidate until a recorded end-to-end run and evaluation" in RULE_ONE
    assert "(owner, 2026-11-11)" in RULE_ONE


def test_template_and_manifest_carry_the_practice() -> None:
    template = (ROOT / ".github/pull_request_template.md").read_text()
    references = template.split("## Upstream references", 1)[1].split("## How verified", 1)[0]
    assert "file:line at the pinned commit" in references
    assert "use as is, build on or keep ours" in references
    manifest = (ROOT / "docs/manifest.md").read_text()
    row = next(line for line in manifest.splitlines() if line.startswith("| Upstream-first brief |"))
    assert "2026-11-11" in row and "review-rules.md" in row and "test_upstream_first.py" in row
