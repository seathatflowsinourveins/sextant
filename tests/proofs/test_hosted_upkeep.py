"""Hosted upkeep invariants.

Three ``schedule:`` crons (model freshness, dependency evidence, the weekly
upkeep panel) plus a manual dispatch run one ``dsh`` headless job each on a
free GitHub-hosted runner, in ``.github/workflows/dsh-worker.yml``'s shape.
The job reads GitHub through a read-only App token, resolves the brief by
event, and either opens a pull request through the write App token or
comments a receipt on one tracker issue; the devc-only staging machinery from
the closed lane-harness-t2 branch is not ported.

Sources: GitHub, "Events that trigger workflows: schedule" and the ``github``
context's ``event.schedule`` / ``repository.default_branch`` fields, read
2026-11-09; PerryLink/dsh-github@2fc0009c:action.yml:51-62,118-161 and
scripts/action-patch.mjs:49-152; peter-evans/create-pull-request@v8.1.1
README.md:50-95; actions/create-github-app-token@v3.3.0 action.yml:1-40;
renovatebot/renovate@44.181.5 d58ffdb10f533fa86c3fa2c46f4f6b6a72c60f85
lib/modules/platform/local/readme.md and lib/config/options/index.ts.
No agent, schedule, credential store or GitHub writer is started here.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github/workflows/upkeep.yml"
BRIEFS = ROOT / ".github/dsh-workers/briefs"
UPKEEP = ROOT / "deploy" / "upkeep"
RENOVATE_PIN = "44.181.5"
CRONS = {
    "0 9 * * *": "upkeep-models",
    "17 5 * * *": "upkeep-dependencies",
    "25 17 * * 1": "upkeep-panel",
}


def _workflow() -> dict[str, Any]:
    data = yaml.safe_load(WORKFLOW.read_text())
    assert isinstance(data, dict)
    return cast(dict[str, Any], data)


def _events() -> dict[str, Any]:
    workflow = _workflow()
    events = workflow["on"] if "on" in workflow else cast(dict[Any, Any], workflow)[True]
    assert isinstance(events, dict)
    return cast(dict[str, Any], events)


def _job() -> dict[str, Any]:
    return _workflow()["jobs"]["upkeep"]


def _step(name: str) -> dict[str, Any]:
    return next(step for step in _job()["steps"] if step.get("name") == name)


def _text() -> str:
    return WORKFLOW.read_text()


def test_three_schedules_resolve_to_the_three_briefs() -> None:
    events = _events()
    assert set(events) == {"schedule", "workflow_dispatch"}
    crons = [row["cron"] for row in events["schedule"]]
    assert crons == list(CRONS), "one cron per upkeep brief, in declaration order"
    dispatch = events["workflow_dispatch"]["inputs"]["brief"]
    assert dispatch["type"] == "choice"
    assert dispatch["options"] == list(CRONS.values())
    resolve = _step("Resolve the upkeep brief")["run"]
    for cron, brief in CRONS.items():
        assert f"'{cron}') brief={brief} ;;" in resolve
    assert 'brief="${INPUT_BRIEF}"' in resolve
    # A schedule the case does not know must fail closed, never fall through to a brief.
    assert 'echo "::error::no upkeep brief for schedule' in resolve
    assert re.search(r"upkeep-models\|upkeep-dependencies\|upkeep-panel", resolve)
    for brief in CRONS.values():
        assert (BRIEFS / f"{brief}.md").is_file(), brief


def test_job_is_default_branch_only_with_least_privilege() -> None:
    job = _job()
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["environment"] == "hosted-workers"
    assert job["permissions"] == {"contents": "read", "issues": "write"}
    assert job["concurrency"] == {"group": "upkeep", "cancel-in-progress": False}
    assert len(_workflow()["jobs"]) == 1
    guard = job["if"]
    # Pre-cutover the default branch is `gate`, after cutover it is `main`; one
    # guard has to hold across both, so it reads the default branch, never a literal.
    assert "github.event.repository.default_branch" in guard
    assert "format('refs/heads/{0}'" in guard
    assert "github.actor == github.repository_owner" in guard
    assert "github.event_name == 'schedule'" in guard
    text = _text()
    assert "refs/heads/main" not in text
    assert "refs/heads/gate" not in text
    assert "pull_request" not in _events()


def test_worker_gets_a_read_only_token_and_no_write_token() -> None:
    read = _step("Mint the read-only evidence token")
    assert read["id"] == "read-token"
    assert read["with"]["permission-contents"] == "read"
    assert read["with"]["permission-pull-requests"] == "read"
    assert "permission-issues" not in read["with"], "the App token never asks for issue access"
    assert not any(key.endswith("write") for key in read["with"] if key.startswith("permission-"))
    worker = _step("Run the dsh headless upkeep worker")
    assert worker["env"]["GH_TOKEN"] == "${{ steps.read-token.outputs.token }}"  # noqa: S105
    assert worker["env"]["DEEPSEEK_API_KEY"] == "${{ secrets.DEEPSEEK_API_KEY }}"
    assert "dsh --profile headless --patch" in worker["run"]
    assert worker["env"]["DSH_PERMISSION_MODE"] == "workspace-write"
    assert worker["env"]["UPKEEP_PREVIOUS_RECEIPT"] == ".upkeep/previous-receipt.md"
    # The automatic job token may comment, but it never reaches the worker.
    assert "${{ secrets.GITHUB_TOKEN }}" not in json.dumps(worker.get("env", {}))
    holders = [
        step.get("name")
        for step in _job()["steps"]
        if "${{ secrets.GITHUB_TOKEN }}" in json.dumps(step.get("env", {}))
    ]
    assert holders == ["Fetch the previous run receipt", "Comment the run receipt"]
    assert set(re.findall(r"secrets\.([A-Z0-9_]+)", _text())) == {
        "DEEPSEEK_API_KEY",
        "GITHUB_TOKEN",
        "SEXTANT_APP_PRIVATE_KEY",
    }
    for forbidden in ("ALPACA_", "APCA_API", "IBKR_", "BROKER_", "PAPER_KEY", "LIVE_KEY"):
        assert forbidden not in _text()


def test_the_previous_receipt_is_filtered_to_the_selected_brief() -> None:
    fetch = _step("Fetch the previous run receipt")
    assert fetch["env"]["UPKEEP_BRIEF"] == "${{ steps.brief.outputs.brief }}"
    assert "--arg brief" in fetch["run"]
    assert "startswith" in fetch["run"]
    assert ".comments[-1]" not in fetch["run"], "a newer other-brief receipt must not win"


def test_pr_path_uses_the_app_token_and_the_default_branch_base() -> None:
    mint = _step("Mint the pull-request app token")
    assert mint["id"] == "app-token"
    assert mint["with"]["app-id"] == "${{ vars.SEXTANT_APP_ID }}"
    assert mint["with"]["private-key"] == "${{ secrets.SEXTANT_APP_PRIVATE_KEY }}"
    assert mint["with"]["permission-contents"] == "write"
    assert mint["with"]["permission-pull-requests"] == "write"
    assert mint["with"]["permission-workflows"] == "write"
    assert "permission-issues" not in mint["with"], "the App token never gains issue writes"
    cpr = _step("Open or update the upkeep pull request")
    assert cpr["with"]["token"] == "${{ steps.app-token.outputs.token }}"  # noqa: S105
    assert cpr["with"]["branch"] == "upkeep/${{ steps.brief.outputs.brief }}"
    assert cpr["with"]["base"] == "${{ github.event.repository.default_branch }}"
    assert cpr["with"]["body"] == "${{ steps.outcome.outputs.pr_body }}"
    assert cpr["with"]["delete-branch"] is True
    assert "github.token" not in _text()
    # A changed tree with no pull request is a failed run, not a silent receipt.
    failed = _step("Fail when the pull request was not created")
    assert "pull-request-number == ''" in json.dumps(failed)
    assert "exit 1" in failed["run"]


def test_no_change_runs_comment_one_tracker_issue() -> None:
    comment = _step("Comment the run receipt")
    assert comment["if"] == "${{ steps.outcome.outputs.path == 'report' }}"
    run = comment["run"]
    assert "Hosted upkeep receipts" in run
    assert "gh issue list" in run and "gh issue create" in run and "gh issue comment" in run
    assert "--body-file" in run
    # One issue, found by title, created only when absent: no hand-made anchor.
    assert "select(.title ==" in run
    assert "#4" not in run, "the goal issue stays for the goal"
    collect = _step("Collect the worker outcome")["run"]
    assert "rm -rf .upkeep" in collect
    assert ".upkeep/pr-body.md" in collect and ".upkeep/report.md" in collect


def test_briefs_carry_the_outcome_contract_and_guardrails() -> None:
    for brief in CRONS.values():
        text = (BRIEFS / f"{brief}.md").read_text()
        assert ".upkeep/report.md" in text, brief
        assert "Agent-Family dsh" in text, brief
        assert "Review-Family" not in text, brief
        for guard in ("Never run `git push`", "Do not read or print environment variables"):
            assert guard in text, (brief, guard)
        assert "unavailable" in text, brief
    models = (BRIEFS / "upkeep-models.md").read_text()
    assert "artificialanalysis.ai" in models
    assert "at least 3" in models and "gpt-6.1-sol" in models
    dependencies = (BRIEFS / "upkeep-dependencies.md").read_text()
    assert "deploy/upkeep/renovate.sh" in dependencies
    assert "14 days" in dependencies
    panel = (BRIEFS / "upkeep-panel.md").read_text()
    assert "users/seathatflowsinourveins/starred" in panel
    # ADR-0001's first rule, never self-invent, is what a replacement has to satisfy.
    assert "ADR-0001" in panel and "names its upstream source" in panel


def test_pins_are_full_sha_and_renovate_ignores_install_scripts() -> None:
    uses = [step["uses"] for step in _job()["steps"] if "uses" in step]
    assert len(uses) == 5
    for reference in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", reference), reference
    assert [reference.split("@")[1] for reference in uses] == [
        "3d3c42e5aac5ba805825da76410c181273ba90b1",
        "949feb2413d6458794dcd2491c4babbbce0c15c1",
        "64ab729a6294000f5aa4a4bc0b73d1f32bc45510",
        "64ab729a6294000f5aa4a4bc0b73d1f32bc45510",
        "5f6978faf089d4d20b00c7766989d076bb2fc7f1",
    ]
    text = _text()
    assert f"RENOVATE_VERSION: {RENOVATE_PIN}" in text
    assert "renovate@${RENOVATE_VERSION}" in text
    assert "--ignore-scripts" in text
    assert "config/dsh/mcp/max-effort.cordis.yml" in text
    assert ".github/gate/headless-services.cordis.yml" in text
    assert "python3 .github/gate/parity-entry.py" in text
    guards = _step("Disable the review-only guards and set the upkeep persona")["run"]
    assert "- id: sextant-gate-api-only" in guards
    assert "- id: dsh-github" in guards
    assert guards.count("disabled: true") == 2
    assert "upkeep worker" in guards


def test_renovate_runs_the_local_platform_without_credentials(tmp_path: Path) -> None:
    runner = UPKEEP / "renovate.sh"
    bins = tmp_path / "bin"
    bins.mkdir()
    output = tmp_path / "invocation.json"
    version = tmp_path / "version"
    version.write_text(RENOVATE_PIN)
    behaviour = tmp_path / "behaviour"
    behaviour.write_text("write")
    fake = (
        f"#!{sys.executable}\nimport json, os, sys\nfrom pathlib import Path\n"
        "if sys.argv[1:] == ['--version']:\n"
        f"    print(Path({str(version)!r}).read_text())\n    raise SystemExit(0)\n"
        # The environment it started with, before Python sets its own (PEP 538).
        "start = Path('/proc/self/environ').read_text().split('\\0')\n"
        "env = dict(x.split('=', 1) for x in start if x)\n"
        f"Path({str(output)!r}).write_text(json.dumps({{'program': Path(sys.argv[0]).name, "
        "'args': sys.argv[1:], 'env': env, 'cwd': os.getcwd()}))\n"
        "report = next(a.split('=', 1)[1] for a in sys.argv if a.startswith('--report-path='))\n"
        f"how = Path({str(behaviour)!r}).read_text()\n"
        "if how != 'none':\n    Path(report).write_text(json.dumps({'fixture': True}))\n"
        "raise SystemExit(1 if how == 'write-fail' else 0)\n"
    )
    # A global Renovate install puts one binary on PATH; npx is a tripwire.
    for name in ("npx", "renovate"):
        tool = bins / name
        tool.write_text(fake)
        tool.chmod(0o755)
    env = {
        "HOME": os.environ["HOME"],
        "PATH": f"{bins}:{os.defpath}",
        "TMPDIR": str(tmp_path),
        "RENOVATE_VERSION": RENOVATE_PIN,
        "GH_TOKEN": "public-fixture-only",
        "RENOVATE_TOKEN": "public-fixture-only",
    }

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(runner)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30
        )

    done = run()
    assert done.returncode == 0, done.stderr
    invocation = json.loads(output.read_text())
    report = Path(invocation["args"][-1].removeprefix("--report-path="))
    assert invocation["program"] == "renovate"
    assert invocation["args"] == [
        "--platform=local",
        "--onboarding=false",
        "--dry-run=lookup",
        "--report-type=file",
        f"--report-path={report}",
    ]
    started = invocation["env"]
    assert set(started) == {"PATH", "RENOVATE_CONFIG_FILE"}, "only PATH and an empty global config"
    assert invocation["cwd"] == str(ROOT.resolve())
    config = Path(started["RENOVATE_CONFIG_FILE"])
    assert config.parent == report.parent and json.loads(config.read_text()) == {}
    assert report.is_absolute() and not report.is_relative_to(ROOT)
    assert report.stat().st_mode & 0o077 == 0
    assert report.parent.stat().st_mode & 0o077 == 0
    assert done.stdout.strip() == str(report)
    metadata = report.with_name("renovate-version.json")
    assert json.loads(metadata.read_text()) == {"running": RENOVATE_PIN, "pinned": RENOVATE_PIN}
    assert metadata.stat().st_mode & 0o077 == 0
    assert "public-fixture-only" not in done.stdout + done.stderr

    behaviour.write_text("write-fail")
    failed = run()
    assert failed.returncode == 1, "Renovate's error exit carries through"
    failed_report = Path(failed.stdout.strip())
    assert failed_report.is_file(), "and its report is still printed"
    assert json.loads(failed_report.with_name("renovate-version.json").read_text()) == {
        "running": RENOVATE_PIN,
        "pinned": RENOVATE_PIN,
    }

    behaviour.write_text("none")
    missing = run()
    assert missing.returncode != 0 and "report" in missing.stderr.lower()
    missing_report = Path(json.loads(output.read_text())["args"][-1].removeprefix("--report-path="))
    assert not missing_report.parent.exists(), "no report means no retained scratch directory"
    assert not missing.stdout.strip()

    behaviour.write_text("write")
    version.write_text("0.0.1")
    stale = run()
    assert stale.returncode == 0, "a version that answers is recorded even when it differs"
    assert "0.0.1" in stale.stderr and RENOVATE_PIN in stale.stderr


def test_renovate_config_keeps_its_age_and_scope_rules() -> None:
    config = json.loads((ROOT / "renovate.json").read_text())
    assert config["minimumReleaseAge"] == "14 days"
    assert config["minimumReleaseAgeBehaviour"] == "timestamp-required"
    # Renovate globs every file when git can't list them, so ignored directories stay out by name.
    assert {
        "**/.venv/**",
        ".superpowers/**",
        "reports/**",
        ".claude/skills/**",
        ".claude/lsp/**",
        ".github/workflows/*.lock.yml",
    } <= set(config["ignorePaths"])
    rules = config["packageRules"]

    def rule(key: str, value: list[str]) -> dict[str, object]:
        return next(r for r in rules if r.get(key) == value)

    assert rule("matchUpdateTypes", ["major"])["enabled"] is False
    assert rule("matchPackageNames", ["nautilus-trader", "alpaca-py"])["enabled"] is False
    pins = json.loads((ROOT / "deploy" / "wsl" / "lane-runtimes" / "pins.json").read_text())
    assert config["minimumReleaseAge"] == f"{pins['release_cooldown_days']} days"
    assert not any("minimumReleaseAge" in r for r in rules), (
        "one global age covers every managed file; a per-path rule can only repeat or weaken it"
    )
    assert not any(".devcontainer/renovate" in str(r.get("matchFileNames", [])) for r in rules), (
        "the devc Renovate lock is not ported, so nothing owns it"
    )
    (manager,) = config["customManagers"]
    assert manager["managerFilePatterns"] == ["/^\\.claude/settings\\.json$/"]
    named = re.compile(manager["matchStrings"][0].replace("(?<", "(?P<"))
    settings = (ROOT / ".claude" / "settings.json").read_text()
    found = [match["currentValue"] for match in named.finditer(settings)]
    assert len(found) == len(re.findall(r'"ref"\s*:', settings)), "every marketplace ref"
    versioning = re.compile(
        manager["versioningTemplate"].removeprefix("regex:").replace("(?<", "(?P<")
    )
    assert all(versioning.fullmatch(value) for value in found)
    prefixed = versioning.fullmatch("compound-engineering-v3.36.0")
    assert prefixed and prefixed["compatibility"] == "compound-engineering-"


def test_devc_only_automation_machinery_is_gone() -> None:
    assert not (ROOT / "deploy" / "automations").exists()
    assert not (ROOT / ".devcontainer" / "renovate").exists()
    assert "/opt/renovate" not in (ROOT / ".devcontainer" / "Dockerfile").read_text()
    dependabot = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    directories = [
        path
        for update in dependabot["updates"]
        for path in (update.get("directories") or [update.get("directory", "")])
    ]
    assert "/.devcontainer/renovate" not in json.dumps(directories)
    for path in UPKEEP.rglob("*"):
        if path.is_file():
            assert "orca-ide automations" not in path.read_text(), path
    assert "devc" not in (UPKEEP / "renovate.sh").read_text()
    readme = (UPKEEP / "README.md").read_text()
    assert "Verified reflection" in readme, "the one job that stays local is named"


def test_manifest_rows_name_the_hosted_upkeep_and_its_proofs() -> None:
    manifest = (ROOT / "docs" / "manifest.md").read_text()
    for name, proofs in (
        (
            "Hosted upkeep schedules: three crons, one headless dsh job shape",
            (
                "test_three_schedules_resolve_to_the_three_briefs",
                "test_job_is_default_branch_only_with_least_privilege",
            ),
        ),
        (
            "Dependency evidence through Renovate's local platform on a hosted runner",
            (
                "test_renovate_runs_the_local_platform_without_credentials",
                "test_renovate_config_keeps_its_age_and_scope_rules",
            ),
        ),
        (
            "Model freshness and the weekly upkeep panel as grounded hosted jobs",
            ("test_briefs_carry_the_outcome_contract_and_guardrails",),
        ),
    ):
        assert f"| {name} |" in manifest, name
        row = next(line for line in manifest.splitlines() if line.startswith(f"| {name} |"))
        for proof in proofs:
            assert f"test_hosted_upkeep.py::{proof}" in row, proof
    assert "2026-10-24T21:48:02.355Z" in manifest, "the Renovate pin's npm publish time"
    assert "test_hosted_upkeep.py::test_devc_only_automation_machinery_is_gone" in manifest


def test_outcome_scratch_stays_out_of_git() -> None:
    assert ".upkeep/" in (ROOT / ".gitignore").read_text().splitlines()
