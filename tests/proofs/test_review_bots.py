"""Every gh-aw reviewer lets the Sextant App's pushes activate the required review.

Source: github/gh-aw@v1.0.1 `0627fdbe4beb5f3b71aa569f8d97150b87f2111a`:
`actions/setup/js/check_membership.cjs` lines 227-258, "Allow trusted bots other than
Dependabot to synchronize same-repository PRs they did not open", fed by the frontmatter's
`on.bots` (`GH_AW_ALLOWED_BOTS`). AO pushes with the App's installation token
(deploy/wsl/github-app.sh). Without the allowlist, gh-aw treats that push as a confused
deputy and skips the review agent, so the required `review` check never appears
(measured on #144, run 42280695135).
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
REVIEWERS = sorted(WORKFLOWS.glob("review*.md"))


def _app_bot() -> str:
    app = json.loads((ROOT / "deploy" / "wsl" / "github-app.json").read_text())
    return f"{app['app_slug']}[bot]"


def _bots(workflow: Path) -> list[str]:
    frontmatter = workflow.read_text().split("---\n", 2)[1]
    found = re.search(r"^  bots: (\[.*\])$", frontmatter, re.MULTILINE)
    assert found, f"{workflow.name} sets no on.bots"
    return json.loads(found.group(1))


def test_every_reviewer_allowlists_the_app_bot() -> None:
    assert REVIEWERS, "no gh-aw reviewer found"
    for workflow in REVIEWERS:
        assert _app_bot() in _bots(workflow), workflow.name


def test_the_compiled_locks_carry_the_allowlist() -> None:
    for workflow in REVIEWERS:
        lock = workflow.with_suffix(".lock.yml").read_text()
        allowed = re.findall(r'GH_AW_ALLOWED_BOTS: "([^"]*)"', lock)
        assert allowed, f"{workflow.name}: recompile with gh aw compile"
        assert all(_app_bot() in entry.split(",") for entry in allowed), workflow.name
