"""The Phase 2 identity cutover: AO, the lane runtimes, hard-lines and dsh each follow sextant-next.

Source: OrchestratorInc/agent-orchestrator@v0.14.10 `033d597032e448a0ea16c298350e36b099f74106`:
`docs/cli/README.md` and `docs/scm-observer.md` (`ao spawn --claim-pr`, AO's own PR ownership) and
`scripts/setup-self-hosted.sh` (its install-only path), the sources `deploy/wsl/ao.sh:4-11` records;
the approved cutover plan (lead, 2026-11-09), Phase 2; GitHub's "Renaming a repository", read
2026-11-09: the old location's clone redirects, so a runtime that names the repository must name the
new one itself.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
AO = ROOT / "deploy/wsl/ao.sh"
RUNTIMES = ROOT / "deploy/wsl/lane-runtimes"
HARD_LINES = ROOT / "deploy/wsl/hard-lines"
# P2.3 moves the lane-runtimes README's two issue links to the archive and P2.7 owns
# deploy/wsl/github-app.json. Neither is this cutover's config, so the audit skips them.
OTHER_ROWS = {"README.md"}
OLD = re.compile(r"seathatflowsinourveins/sextant-archive")
ROW = (
    "Multi-runtime identity: AO names sextant-next, lane runtimes derive their checkout, "
    "hard-lines and dsh carry no repo URL"
)


def _files(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in OTHER_ROWS and "__pycache__" not in path.parts
    ]


def test_ao_names_the_new_repo_and_its_claim_reads_through_it() -> None:
    text = AO.read_text()
    assert "project=sextant" in text
    assert 'clone="$HOME/.ao/repos/sextant-next"' in text
    assert "repo_url=https://github.com/seathatflowsinourveins/sextant\n" in text
    assert 'gh pr view "$pr" --repo "$repo_url"' in text
    assert "!$here/github-app/bin/gh auth git-credential" in text


def test_lane_runtimes_name_no_sextant_repo_url() -> None:
    for path in _files(RUNTIMES):
        text = path.read_text(errors="replace")
        assert not OLD.search(text), f"{path.relative_to(ROOT)} names the old repository"
    pins = json.loads((RUNTIMES / "pins.json").read_text())
    repositories = [row["repository"] for row in pins["runtimes"].values()]
    assert repositories and not any("seathatflowsinourveins" in row for row in repositories)
    # parity.py builds a clone URL from the lock row's `repo` alone, and every lock row is a
    # third-party plugin, skill or LSP source; the Sextant checkout comes from repository-path.
    lock = json.loads((ROOT / ".claude/shelf.lock.json").read_text())
    rows = [*lock["plugins"].values(), lock["skills"], lock["lsp"]]
    repos = [row["repo"] for row in rows]
    assert repos and not any("seathatflowsinourveins" in repo for repo in repos)
    install = (RUNTIMES / "install.sh").read_text()
    assert 'git -C "$here" rev-parse' in install
    assert "$prefix/repository-path" in install
    assert "repository-path" in (RUNTIMES / "parity.py").read_text()


def test_hard_lines_names_no_repository_url() -> None:
    for path in _files(HARD_LINES):
        text = path.read_text(errors="replace")
        assert not OLD.search(text), f"{path.relative_to(ROOT)} names the old repository"
        assert "github.com" not in text, f"{path.relative_to(ROOT)} names a repository URL"


def test_dsh_pre_push_review_runs_from_its_dsh_home() -> None:
    start = (ROOT / "docs/start.md").read_text()
    assert "DSH_HOME=~/.dsh-full" in start
    doctor = (ROOT / "scripts/dsh_profile_doctor.py").read_text()
    assert 'Path.home() / ".dsh-full" / "profiles" / "dsh-tui" / "package.json"' in doctor
    host_tools = json.loads((ROOT / "deploy/wsl/dsh/package.json").read_text())
    assert "repository" not in host_tools


def test_manifest_records_the_multi_runtime_identity_audit() -> None:
    rows = [
        line
        for line in (ROOT / "docs/manifest.md").read_text().splitlines()
        if line.startswith(f"| {ROW} |")
    ]
    assert len(rows) == 1
    assert "033d597032e448a0ea16c298350e36b099f74106" in rows[0]
    for name in (
        "test_ao_names_the_new_repo_and_its_claim_reads_through_it",
        "test_lane_runtimes_name_no_sextant_repo_url",
        "test_hard_lines_names_no_repository_url",
        "test_dsh_pre_push_review_runs_from_its_dsh_home",
    ):
        assert name in rows[0]
