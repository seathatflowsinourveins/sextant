"""The weekly consolidation report (#215): one default-branch comment on dead code and duplicates.

Sources: jendrikseipp/vulture@v2.16 `b0f67ba0044693aa9ec0d38fe460590facc98004` and
pylint-dev/pylint@v4.1.3 `e75de10c69103381c875601f638d4b977ff0fcaf` (duplicate-code, R0801),
named by the workflow and pinned in the locked `consolidation` group.
"""

import json
import os
import re
import subprocess
import sys
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "consolidation.yml"
HOSTED = "ubuntu-24.04"

# Canned tool output, smallest first like vulture's --sort-by-size. The 90% item is safe; the 60%
# and 65% items are review, which the workflow must rank largest first.
VULTURE = """src/sextant/small.py:1: unused class 'Small' (60% confidence, 2 lines)
src/sextant/big.py:1: unused class 'Big' (65% confidence, 41 lines)
src/sextant/dead.py:7: unused function 'gone' (90% confidence, 3 lines)
"""
PYLINT = json.dumps(
    {
        "messages": [
            {
                "symbol": "duplicate-code",
                "message": (
                    "Similar lines in 2 files\n"
                    "==sextant.alpha.one:[1:10]\n"
                    "==sextant.beta.two:[3:12]\n"
                    "    A = 1\n"
                ),
            }
        ]
    }
)
RUFF = (
    "src/sextant/alpha/one.py:1:1: F401 'os' imported but unused\n"
    "src/sextant/beta/two.py:2:1: F841 local variable 'x' is assigned to but never used\n"
)


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _job() -> dict:
    return _workflow()["jobs"]["report"]


def _compose() -> str:
    return next(step["run"] for step in _job()["steps"] if step.get("name") == "Compose the report")


def test_the_report_runs_only_from_the_default_branch_on_a_hosted_runner() -> None:
    workflow = _workflow()
    # PyYAML reads the unquoted key `on:` as the boolean True.
    assert True in workflow
    triggers = workflow[True]
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert triggers["schedule"] == [{"cron": "23 7 * * 1"}]
    assert triggers["workflow_dispatch"] is None
    assert workflow["permissions"] == {}
    job = workflow["jobs"]["report"]
    assert job["permissions"] == {"contents": "read", "issues": "write"}
    assert job["if"] == (
        "${{ github.ref == format('refs/heads/{0}', github.event.repository.default_branch) }}"
    )
    assert job["runs-on"] == HOSTED
    assert "secrets." not in WORKFLOW.read_text()
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"]), step["uses"]
    checkout = next(step for step in job["steps"] if step["uses"].startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False
    assert job["env"]["REPORT_ISSUE"] == "215"


def test_the_consolidation_group_is_locked_with_exact_pins() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["dependency-groups"]["consolidation"] == [
        "vulture==2.16",
        "pylint==4.1.3",
        "mypy-extensions==1.1.0",
    ]
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    versions = {package["name"]: package["version"] for package in lock["package"]}
    assert versions["vulture"] == "2.16"
    assert versions["pylint"] == "4.1.3"
    assert versions["mypy-extensions"] == "1.1.0"
    root = next(package for package in lock["package"] if package["name"] == "sextant")
    requires = root["metadata"]["requires-dev"]["consolidation"]
    assert sorted((item["name"], item["specifier"]) for item in requires) == [
        ("mypy-extensions", "==1.1.0"),
        ("pylint", "==4.1.3"),
        ("vulture", "==2.16"),
    ]


def _git(repo: Path, *args: str, date: datetime | None = None) -> str:
    env = {**os.environ, "LC_ALL": "C"}
    if date is not None:
        stamp = date.isoformat()
        env |= {
            "GIT_AUTHOR_NAME": "consolidation",
            "GIT_AUTHOR_EMAIL": "consolidation@example.invalid",
            "GIT_COMMITTER_NAME": "consolidation",
            "GIT_COMMITTER_EMAIL": "consolidation@example.invalid",
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
        }
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


def _fixture(tmp_path: Path, *, week_old: bool) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    (repo / "tests" / "repo").mkdir(parents=True)
    (repo / "tests" / "repo" / "test_budgets.py").write_text(
        "def test_src():\n"
        '    assert sum(_lines(path) for path in (ROOT / "src").rglob("*.py")) < 100\n'
    )
    _git(repo, "init", "-q")
    source = repo / "src" / "sextant"
    (source / "alpha").mkdir(parents=True)
    (source / "beta").mkdir()
    (source / "alpha" / "one.py").write_text("A = 1\n")
    (source / "beta" / "two.py").write_text("B = 1\nC = 2\n")
    (source / "top.py").write_text("T = 1\n")
    now = datetime.now(UTC)
    _git(repo, "add", "-A")
    _git(
        repo,
        "commit",
        "-q",
        "-m",
        "fixture: base",
        date=now - timedelta(days=8 if week_old else 0),
    )
    week = _git(repo, "rev-parse", "HEAD")
    (source / "alpha" / "one.py").write_text("A = 1\nA2 = 2\nA3 = 3\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture: head", date=now)
    head = _git(repo, "rev-parse", "HEAD")
    return repo, head, week


def _fake_uv(bin_dir: Path, canned: Path) -> None:
    bin_dir.mkdir()
    script = f"""#!{sys.executable}
import sys
from pathlib import Path
tool = next((name for name in ("vulture", "pylint", "ruff") if name in sys.argv), None)
if tool is None:
    sys.exit(f"unexpected uv call: {{sys.argv[1:]}}")
print((Path({str(canned)!r}) / f"{{tool}}.txt").read_text(), end="")
"""
    (bin_dir / "uv").write_text(script)
    (bin_dir / "uv").chmod(0o755)


def _run_compose(tmp_path: Path, *, week_old: bool) -> tuple[str, str, str]:
    repo, head, week = _fixture(tmp_path, week_old=week_old)
    canned = tmp_path / "canned"
    canned.mkdir()
    (canned / "vulture.txt").write_text(VULTURE)
    (canned / "pylint.txt").write_text(PYLINT)
    (canned / "ruff.txt").write_text(RUFF)
    bin_dir = tmp_path / "bin"
    _fake_uv(bin_dir, canned)
    script = tmp_path / "compose.sh"
    script.write_text(_compose())
    run = subprocess.run(
        ["bash", str(script)],
        cwd=repo,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GITHUB_SHA": head,
            "LC_ALL": "C",
        },
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    return (repo / "report.md").read_text(), head, week


def test_the_compose_step_reports_every_section(tmp_path: Path) -> None:
    report, head, week = _run_compose(tmp_path, week_old=True)
    assert f"## Consolidation report: main {head[:7]}," in report
    assert (
        "**src:** 6 lines under a cap of 100, so 94 lines of headroom. "
        f"This week: 2 from main {week[:7]}."
    ) in report
    assert "| alpha | 3 | +2 |" in report
    assert "| beta | 2 | +0 |" in report
    assert "| (top level) | 1 | +0 |" in report
    assert "**Review, 60 to 79%:** 2 findings." in report
    assert report.index("'Big'") < report.index("'Small'")
    assert (
        "- `src/sextant/dead.py:7: unused function 'gone' (90% confidence, 3 lines)`: delete it."
    ) in report
    assert report.count("unused function 'gone'") == 1
    assert (
        "- `src/sextant/alpha/one.py:1-10` ~ `src/sextant/beta/two.py:3-12` (9 lines): "
        "fold into one helper."
    ) in report
    assert "2 findings. ci enforces these, so anything here is a regression." in report


def test_the_compose_step_marks_a_week_with_no_baseline(tmp_path: Path) -> None:
    report, head, _ = _run_compose(tmp_path, week_old=False)
    assert f"## Consolidation report: main {head[:7]}," in report
    assert (
        "**src:** 6 lines under a cap of 100, so 94 lines of headroom. "
        "No main commit is a week old yet."
    ) in report
    assert "| alpha | 3 | n/a |" in report
