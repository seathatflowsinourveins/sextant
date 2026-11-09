"""One test per row of docs/manifest.md. `just prove` runs them; CI publishes the count."""

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
REPO = "repos/seathatflowsinourveins/sextant-next"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _run(*command: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, env=env, timeout=120)


def _gh(path: str) -> Any:
    return json.loads(_run("gh", "api", path).stdout)


def test_sandbox_is_the_upstream_template() -> None:
    assert _sha(_read(".devcontainer/post_install.py")) == (
        "30614d41a891768032f65d583fee4423c402d144402203a0189fcb169a8fedb9"
    )
    assert _sha(_read(".devcontainer/.zshrc")) == (
        "0788e061b87afde6d0e7243e1aa2b93952c1fcdc82125278f5ac503142a5bec2"
    )
    # FROM lines are left out, because Dependabot moves those pins.
    upstream_part = _read(".devcontainer/Dockerfile").split("# --- Sextant layer")[0]
    body = "".join(line for line in upstream_part.splitlines(True) if not line.startswith("FROM "))
    assert _sha(body) == "61fb7595307fc4d9ab69de9ab3048555d9d3f13314c96097b2901842f38c7b42"


def test_template_read_only_binds_are_kept() -> None:
    config = json.loads(_read(".devcontainer/devcontainer.json"))
    mounts = " ".join(config["mounts"])
    for target in ("/workspace/.devcontainer", "/workspace/.git/config", "/workspace/.git/hooks"):
        assert f"target={target},type=bind,readonly" in mounts
    assert config["remoteUser"] != "root"


@pytest.mark.container
def test_firewall_blocks_private_ranges_not_the_web() -> None:
    gateway = _run("ip", "route", "show", "default").stdout.split()[2]
    blocked = _run("curl", "-v", "--max-time", "5", f"http://{gateway}:1/")
    # A closed port on an open route would say "Connection refused". The firewall rejects first.
    assert blocked.returncode != 0
    assert "Connection refused" not in blocked.stderr
    assert (
        _run("curl", "-fsS", "--max-time", "15", "-o", "/dev/null", "https://github.com").returncode
        == 0
    )


@pytest.mark.container
def test_sudo_runs_only_the_firewall() -> None:
    assert _run("sudo", "-n", "true").returncode != 0
    assert _run("sudo", "-n", "/usr/local/bin/init-firewall.sh").returncode == 0


@pytest.mark.container
def test_runtimes_match_their_pins() -> None:
    assert "2.1.318" in _run("claude", "--version").stdout
    agents = json.loads(_read(".devcontainer/agents/package.json"))["dependencies"]
    assert agents["@openai/codex"] in _run("codex", "--version").stdout
    assert agents["@deepseek-ai/dsh"] in _run("dsh", "--version").stdout


def test_source_rule_is_enforced() -> None:
    assert "--dangerfile dangerfile.js --failOnErrors" in _read(".github/workflows/gate.yml")
    assert "Self-invention" in _read(".github/workflows/shared/review-rules.md")


def test_review_uses_upstream_actions_and_posts_required_statuses() -> None:
    import yaml

    gate = yaml.safe_load(_read(".github/workflows/gate.yml"))
    assert gate.get("on", gate.get(True)) == {
        "workflow_run": {"workflows": ["ci"], "types": ["completed"]}
    }
    assert {"source", "dsh", "codex", "claude", "result"} == set(gate["jobs"])
    adapter = _read(".github/gate/gate.cjs")
    assert "createCommitStatus" in adapter
    assert "'source'" in adapter and "'review'" in adapter
    assert not list(WORKFLOWS.glob("*.lock.yml"))


def test_rubric_is_verbatim_upstream() -> None:
    assert _sha(_read(".github/review/rubric.md")) == (
        "ec60e7f36a1d1c2679ce095c0205ecc56f7dd8fb57707a13ef362072390f219f"
    )


def test_ci_gives_pr_code_no_repository_secret() -> None:
    from test_public_gate import test_ci_runs_the_complete_check_without_repository_secrets

    test_ci_runs_the_complete_check_without_repository_secrets()
    ci = _read(".github/workflows/ci.yml")
    assert ci.count("persist-credentials: false") == ci.count("actions/checkout@")


def test_every_action_is_pinned() -> None:
    from test_public_gate import test_every_action_in_workflows_and_composites_has_a_full_pin

    test_every_action_in_workflows_and_composites_has_a_full_pin()
    setup = _read("deploy/wsl/setup.sh")
    assert "pin=ACTIONLINT_VERSION" in setup and "key=al" in setup
    assert '"$checksum" "$tool_archive" | sha256sum -c -' in setup


def test_lint_covers_every_non_lock_workflow_with_shellcheck() -> None:
    """Hosted ci's lint job runs just lint, which discovers every workflow with ShellCheck."""
    ci = _read(".github/workflows/ci.yml")
    just = _read("justfile")
    dockerfile = _read(".devcontainer/Dockerfile")
    install = _read(".github/actions/ci-tools/install.sh")
    assert "run: just lint" in ci
    assert "bash .github/actions/ci-tools/install.sh actionlint shellcheck just" in ci
    assert "shellcheck .github/actions/ci-tools/install.sh" in just
    assert "ci: sync lint test secrets" in just
    assert "find .github/workflows -maxdepth 1 -type f" in just
    assert '-shellcheck shellcheck "${workflows[@]}"' in just
    version = re.search(r"SHELLCHECK_VERSION: (\S+)", ci)
    digest = re.search(r"SHELLCHECK_SHA256: (\S+)", ci)
    assert version is not None and digest is not None
    assert f"ARG SHELLCHECK_VERSION={version.group(1)}" in dockerfile
    assert f"sc_sha={digest.group(1)}" in dockerfile
    assert "sc_arch=linux.aarch64; sc_sha=" in dockerfile
    assert 'member="shellcheck-v${version}/shellcheck"' in install
    assert '--strip-components=1 "$member"' in install


@pytest.mark.local
def test_gitleaks_is_wired() -> None:
    assert _run("gitleaks", "version").returncode == 0
    assert "gitleaks" in _read("justfile")
    assert "gitleaks" in _read(".githooks/pre-commit")
    setup = _read("deploy/wsl/setup.sh")
    assert "pin=GITLEAKS_VERSION" in setup and "key=gl" in setup
    assert "git config core.hooksPath .githooks" in setup


@pytest.mark.local
def test_rulesets_are_active() -> None:
    rulesets = {item["name"]: item for item in _gh(f"{REPO}/rulesets")}
    assert all(rulesets[name]["enforcement"] == "active" for name in ("main", "live", "ledger"))

    def rules(name: str) -> dict:
        full = _gh(f"{REPO}/rulesets/{rulesets[name]['id']}")
        return {rule["type"]: rule.get("parameters", {}) for rule in full["rules"]}

    def checks(name: str) -> set[tuple[str, int]]:
        required = rules(name)["required_status_checks"]
        assert required["strict_required_status_checks_policy"] is False
        return {(c["context"], c["integration_id"]) for c in required["required_status_checks"]}

    required = {("ci", 15368), ("review", 15368), ("source", 15368)}
    assert checks("main") == required
    assert checks("live") == required | {("promotion-record", 15368)}
    assert {"update", "deletion", "non_fast_forward"} <= rules("ledger").keys()
    for name in ("main", "live"):
        assert {"pull_request", "deletion", "non_fast_forward"} <= rules(name).keys()


def test_main_ruleset_turns_off_extra_approval_for_unattributed_changes() -> None:
    """At zero required approvals the live ruleset kept this on and held unattributed PRs."""
    ruleset = json.loads(_read(".github/rulesets/main.json"))
    pull_request = next(rule for rule in ruleset["rules"] if rule["type"] == "pull_request")
    parameters = pull_request["parameters"]
    assert parameters["required_approving_review_count"] == 0
    assert parameters["require_extra_approval_for_unattributed_changes"] is False


@pytest.mark.local
def test_environments_restrict_branches() -> None:
    for name, branch in (("review", "main"), ("paper", "main"), ("live", "live")):
        policies = _gh(f"{REPO}/environments/{name}/deployment-branch-policies")
        assert [p["name"] for p in policies["branch_policies"]] == [branch]


def test_dependabot_covers_every_ecosystem() -> None:
    import yaml

    dependabot = _read(".github/dependabot.yml")
    config = yaml.safe_load(dependabot)
    for ecosystem in ("npm", "uv", "docker", "github-actions", "devcontainers"):
        assert f"package-ecosystem: {ecosystem}" in dependabot
    assert len(config["updates"]) == 7
    for update in config["updates"]:
        assert update["cooldown"] == {"default-days": 14}
    npm = [update for update in config["updates"] if update["package-ecosystem"] == "npm"]
    assert [update["directories"] for update in npm if "directories" in update] == [
        ["/.devcontainer/agents", "/config/dsh"]
    ]
    assert sorted(update["directory"] for update in npm if "directory" in update) == [
        "/.devcontainer/qmd",
        "/deploy/wsl/dsh",
    ]
    dsh = next(update for update in npm if update.get("directory") == "/deploy/wsl/dsh")
    assert dsh["schedule"] == {"interval": "daily"}
    assert dsh["open-pull-requests-limit"] == 2
    # pnpm is pinned to exactly dsh-tui's 11.21.0, so every update type is ignored there.
    assert dsh["ignore"] == [{"dependency-name": "pnpm"}]
    assert all("update-types" not in rule for rule in dsh["ignore"])
    assert "# pnpm moves only with dsh-tui's toolchain" in dependabot


def test_scoreboard_uses_upstream_actions() -> None:
    scoreboard = (WORKFLOWS / "scoreboard.yml").read_text()
    assert "github/issue-metrics@" in scoreboard
    assert "peter-evans/create-issue-from-file@" in scoreboard


def test_scoreboard_runs_only_daily_or_on_dispatch() -> None:
    import yaml

    workflow = yaml.safe_load((WORKFLOWS / "scoreboard.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert "push" not in triggers
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert triggers["schedule"] == [{"cron": "17 6 * * *"}]
    assert workflow["jobs"]["scoreboard"]["if"] == (
        "${{ github.ref == format('refs/heads/{0}', github.event.repository.default_branch) }}"
    )


def test_scoreboard_measures_the_stop_rule_over_the_last_twenty_merges() -> None:
    text = (WORKFLOWS / "scoreboard.yml").read_text()
    assert "--state merged --limit 100" in text
    assert "sort:updated-desc" in text
    assert "sort_by(.mergedAt) | reverse | .[0:20]" in text
    assert "fromdateiso8601" in text
    assert "stop-rule.md" in text
    assert "Median merge time: ${median} h against a 1.00 h limit." in text


def test_lessons_keep_their_seed_and_stay_append_only() -> None:
    lines = _read("docs/handbook/lessons.jsonl").splitlines(True)
    assert _sha("".join(lines[:130])) == (
        "c9c2dd40ff547fdc5625e59b8d286610b991317578390678277d775ebfa4d4d0"
    )
    assert {json.loads(line)["schema"] for line in lines} == {"northstar.handbook.lesson/1"}


def test_ci_fans_out_into_parallel_jobs_and_the_fan_in_fails_closed() -> None:
    """GitHub workflow syntax `jobs` and `jobs.<job_id>.needs`, read 2026-11-09."""
    import os

    import yaml

    data = yaml.safe_load(_read(".github/workflows/ci.yml"))
    jobs = data["jobs"]
    assert data["permissions"] == {"contents": "read"}
    assert set(jobs) == {"lint", "tests", "budgets", "secrets", "ci"}
    fan_in = jobs["ci"]
    assert fan_in["needs"] == ["lint", "tests", "budgets", "secrets"]
    assert fan_in["if"] == "always()"
    runs = {
        name: " ".join(str(step.get("run", "")) for step in job["steps"])
        for name, job in jobs.items()
    }
    scripts = [step.get("run", "") for job in jobs.values() for step in job["steps"]]
    assert sum("bash .github/actions/ci-tools/install.sh" in script for script in scripts) == 4
    assert "just lint" in runs["lint"]
    assert "just test tests/proofs" in runs["tests"]
    assert "just test tests/repo" in runs["budgets"]
    assert "just secrets" in runs["secrets"]
    failed_step = "Fail unless every parallel job succeeded"
    check = next(step for step in fan_in["steps"] if step.get("name") == failed_step)
    script = check["run"]
    results = {name: {"result": "success"} for name in fan_in["needs"]}
    ok = subprocess.run(
        ["bash", "-e", "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "NEEDS": json.dumps(results)},
        timeout=60,
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr
    for bad in ("failure", "cancelled", "skipped"):
        broken = {**results, "tests": {"result": bad}}
        done = subprocess.run(
            ["bash", "-e", "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "NEEDS": json.dumps(broken)},
            timeout=60,
        )
        assert done.returncode != 0, bad
        assert "tests=" + bad in done.stdout + done.stderr


def test_pytest_runs_on_every_runner_core_with_a_cooled_down_pin() -> None:
    """pytest-xdist 3.8.0, uploaded 2025-07-01, against `release_cooldown_days: 14`."""
    assert "pytest-xdist==3.8.0" in _read("pyproject.toml").split("[dependency-groups]", 1)[1]
    just = _read("justfile")
    assert re.search(r"^test.*:\n    uv run --frozen pytest -n auto", just, re.MULTILINE)


def test_uv_dependency_cache_is_restored_for_ci_and_nowhere_else() -> None:
    """astral-sh/setup-uv README at the ci.yml pin: `enable-cache` and `save-cache`."""
    ci = _read(".github/workflows/ci.yml")
    assert "enable-cache: true" in ci
    assert "save-cache: false" in ci
    for name in ("gate.yml", "consolidation.yml"):
        text = _read(f".github/workflows/{name}")
        if "astral-sh/setup-uv@" in text:
            assert "enable-cache: false" in text, name
