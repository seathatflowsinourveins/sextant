"""One test per row of docs/manifest.md. `just prove` runs them; CI publishes the count."""

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
REPO = "repos/seathatflowsinourveins/sextant"


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


def test_sudo_runs_only_the_firewall() -> None:
    assert _run("sudo", "-n", "true").returncode != 0
    assert _run("sudo", "-n", "/usr/local/bin/init-firewall.sh").returncode == 0


def test_runtimes_match_their_pins() -> None:
    assert "2.1.318" in _run("claude", "--version").stdout
    agents = json.loads(_read(".devcontainer/agents/package.json"))["dependencies"]
    assert agents["@openai/codex"] in _run("codex", "--version").stdout
    assert agents["@deepseek-ai/dsh"] in _run("dsh", "--version").stdout


def test_source_rule_is_enforced() -> None:
    """tests/repo/test_dangerfile.py runs the rule itself. This row proves `review` runs it."""
    assert "--dangerfile dangerfile.js --failOnErrors" in (WORKFLOWS / "review.yml").read_text()
    assert "Self-invention" in _read(".github/review/head.md")


def test_review_uses_pinned_upstream_action() -> None:
    review = (WORKFLOWS / "review.yml").read_text()
    assert "anthropics/claude-code-action@c0949c50a78c1ec8ce2647db36629b870e715d0c" in review
    assert "--profile headless" in review
    assert "dorny/paths-filter@ceb8a2b8f2d89434be7ff52d3de7ec3738c5cc9d" in review
    assert "pull_request_target" in review


def test_rubric_is_verbatim_upstream() -> None:
    assert _sha(_read(".github/review/rubric.md")) == (
        "ec60e7f36a1d1c2679ce095c0205ecc56f7dd8fb57707a13ef362072390f219f"
    )


def test_ci_gives_pr_code_no_secret_and_no_cache() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text()
    assert "pull_request_target" in ci
    assert "runs-on: ubuntu-" in ci
    assert "secrets." not in ci
    assert "enable-cache: false" in ci
    assert "package-manager-cache: false" in ci
    assert ci.count("persist-credentials: false") == ci.count("actions/checkout@")
    assert re.search(r"^permissions:\n  contents: read\n", ci, re.MULTILINE)


def test_every_action_is_pinned() -> None:
    for workflow in WORKFLOWS.glob("*.yml"):
        for action in re.findall(r"uses:\s*(\S+)", workflow.read_text()):
            assert re.search(r"@([0-9a-f]{40}|sha256:[0-9a-f]{64})$", action), action


def test_gitleaks_is_wired() -> None:
    assert _run("gitleaks", "version").returncode == 0
    assert "gitleaks" in _read("justfile")
    assert "gitleaks" in _read(".githooks/pre-commit")


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

    assert checks("main") == {("ci", 15368), ("review", 15368)}
    assert checks("live") == {("ci", 15368), ("review", 15368), ("promotion-record", 15368)}
    assert {"update", "deletion", "non_fast_forward"} <= rules("ledger").keys()
    for name in ("main", "live"):
        assert {"pull_request", "deletion", "non_fast_forward"} <= rules(name).keys()


def test_environments_restrict_branches() -> None:
    for name, branch in (("review", "main"), ("paper", "main"), ("live", "live")):
        policies = _gh(f"{REPO}/environments/{name}/deployment-branch-policies")
        assert [p["name"] for p in policies["branch_policies"]] == [branch]


def test_dependabot_covers_every_ecosystem() -> None:
    dependabot = _read(".github/dependabot.yml")
    for ecosystem in ("npm", "uv", "docker", "github-actions", "devcontainers"):
        assert f"package-ecosystem: {ecosystem}" in dependabot
    assert dependabot.count("cooldown") == 5


def test_scoreboard_uses_upstream_actions() -> None:
    scoreboard = (WORKFLOWS / "scoreboard.yml").read_text()
    assert "github/issue-metrics@" in scoreboard
    assert "peter-evans/create-issue-from-file@" in scoreboard


def test_lessons_keep_their_seed_and_stay_append_only() -> None:
    lines = _read("docs/handbook/lessons.jsonl").splitlines(True)
    assert _sha("".join(lines[:130])) == (
        "c9c2dd40ff547fdc5625e59b8d286610b991317578390678277d775ebfa4d4d0"
    )
    assert {json.loads(line)["schema"] for line in lines} == {"northstar.handbook.lesson/1"}
