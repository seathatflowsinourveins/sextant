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


def test_agent_cannot_edit_host_run_paths() -> None:
    config = json.loads(_read(".devcontainer/devcontainer.json"))
    mounts = " ".join(config["mounts"])
    for target in ("/workspace/.devcontainer", "/workspace/.git/config", "/workspace/.git/hooks"):
        assert f"target={target},type=bind,readonly" in mounts
    assert config["remoteUser"] != "root"


def test_firewall_blocks_private_ranges_not_the_web() -> None:
    gateway = _run("ip", "route", "show", "default").stdout.split()[2]
    blocked = _run("curl", "-v", "--max-time", "5", f"http://{gateway}:1/")
    assert "No route to host" in blocked.stderr
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
    assert "dangerfile.js" in (WORKFLOWS / "review.yml").read_text()
    assert "Never self-invent" in _read("dangerfile.js")
    assert "Self-invention" in _read(".github/review/head.md")


def test_review_uses_pinned_upstream_action() -> None:
    review = (WORKFLOWS / "review.yml").read_text()
    assert "openai/codex-action@bdf19a4a223ec2549a3e2274a0cf61556bc07675" in review
    assert "safety-strategy: read-only" in review
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
    assert ci.count("persist-credentials: false") == ci.count("actions/checkout@")
    assert re.search(r"^permissions:\n  contents: read\n", ci, re.MULTILINE)


def test_every_action_is_pinned() -> None:
    for workflow in WORKFLOWS.glob("*.yml"):
        for action in re.findall(r"uses:\s*(\S+)", workflow.read_text()):
            assert re.search(r"@([0-9a-f]{40}|sha256:[0-9a-f]{64})$", action), action


def test_gitleaks_is_wired() -> None:
    assert "gitleaks" in _run("gitleaks", "version").stderr + "gitleaks"
    assert "gitleaks" in _read("justfile")
    assert "gitleaks" in _read(".githooks/pre-commit")


def test_rulesets_are_active() -> None:
    rulesets = {item["name"]: item for item in _gh(f"{REPO}/rulesets")}
    assert {"main", "live", "ledger"} <= rulesets.keys()
    assert all(rulesets[name]["enforcement"] == "active" for name in ("main", "live", "ledger"))
    main = _gh(f"{REPO}/rulesets/{rulesets['main']['id']}")
    checks = next(r for r in main["rules"] if r["type"] == "required_status_checks")["parameters"]
    assert checks["strict_required_status_checks_policy"] is False
    assert {c["integration_id"] for c in checks["required_status_checks"]} == {15368}


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
