"""The post-ADR-0030 roster: retained pins, retired absence, and the router contract."""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
RUNTIMES = ROOT / "deploy/wsl/lane-runtimes"
RETAINED = ("antigravity",)
RETIRED = ("pi", "omp", "opencode2", "hermes", "openhands-sdk")
REMOVED_FILES = (
    "api-launch.sh",
    "configure.py",
    "openhands-lane.py",
    "openhands-requirements.txt",
    "package.json",
    "package-lock.json",
)


@pytest.mark.parametrize("name", RETAINED)
def test_retained_runtime_has_an_eligible_pinned_artifact(name: str) -> None:
    pins = json.loads((RUNTIMES / "pins.json").read_text())
    assert set(pins["runtimes"]) == set(RETAINED)
    row = pins["runtimes"][name]
    assert re.fullmatch(r"[0-9a-f]{40}", row["commit"])
    published = datetime.fromisoformat(row["published_at"].replace("Z", "+00:00"))
    checked = datetime.fromisoformat(pins["checked_at"].replace("Z", "+00:00"))
    assert checked.tzinfo == UTC
    assert checked - published >= timedelta(days=14)
    assert row["install_source"] and row["convergence"]
    assert row["orca_agent"] == name
    assert re.fullmatch(r"[0-9a-f]{64}", row["sha256"])


@pytest.mark.parametrize("name", RETIRED)
def test_retired_runtime_keeps_its_pin_in_history_with_its_authority(name: str) -> None:
    pins = json.loads((RUNTIMES / "pins.json").read_text())
    assert name not in pins["runtimes"], "a retired runtime is not installed"
    row = pins["retired_runtimes"][name]
    assert row["retired_on"] == "2026-11-08"
    assert "ADR-0030" in row["authority"]
    cited = re.search(r"docs/adr/0030-latest-sota-models\.md:(\d+)", row["authority"])
    assert cited, "the authority cites ADR-0030 by line"
    adr = (ROOT / "docs/adr/0030-latest-sota-models.md").read_text().splitlines()
    assert adr[int(cited[1]) - 1].startswith("Retired from routing:"), cited[0]
    assert re.fullmatch(r"[0-9a-f]{40}", row["commit"])


def test_openhands_reject_records_the_report_and_its_reopen_trigger() -> None:
    row = json.loads((RUNTIMES / "pins.json").read_text())["retired_runtimes"]["openhands-sdk"]
    assert row["reason"].startswith("REJECT")
    assert "f91990d0b2b5bfd4843d09c68693c50fb47747bd339b5e2d4d1afa084f32eb9b" in row["reason"]
    assert "maintained OpenHands headless or ACP worker" in row["reopen"]
    assert "max-effort control" in row["reopen"]
    assert "14 days old" in row["reopen"]


def test_the_installer_installs_no_retired_runtime() -> None:
    install = (RUNTIMES / "install.sh").read_text()
    for name in RETIRED:
        assert not re.search(rf"\b{re.escape(name)}\b", install), f"installs {name}"
        assert f".local/bin/{name}" not in install
    for name in REMOVED_FILES:
        assert not (RUNTIMES / name).exists(), f"{name} is a retired install input"
    assert 'cp "$here/package.json"' not in install
    for path in RUNTIMES.glob("*.sh"):
        assert "api-launch.sh" not in path.read_text(), f"{path.name} points at a deleted launcher"


def test_installers_link_only_the_retained_launchers() -> None:
    link = re.compile(r"\$HOME/\.local/bin/([A-Za-z0-9_.-]+)")
    install = link.findall((RUNTIMES / "install.sh").read_text())
    assert sorted(install) == ["agy", "sextant-codex", "sextant-codex-review"]
    parity = link.findall((RUNTIMES / "parity.sh").read_text())
    assert sorted(parity) == ["agy", "dsh", "muse", "sextant-dsh"]


def test_fresh_router_is_pinned_and_has_no_old_campaign_endpoint() -> None:
    pins = json.loads((RUNTIMES / "pins.json").read_text())
    assert pins["omniroute"]["version"] == "3.8.53"
    assert pins["omniroute"]["commit"] == "191dce8d534ceb56c28a08e71381284a9a87838f"
    router = (RUNTIMES / "router-start.sh").read_text()
    assert "127.0.0.1:22128" in router
    for port in (20128, 20129, 20130):
        assert str(port) not in router
    assert "with-keys.sh" in router and "OMNIROUTE_STORAGE_ENCRYPTION_KEY" in router


def test_model_policy_keeps_the_approved_google_interim_and_native_claude() -> None:
    policy = json.loads((RUNTIMES / "model-policy.json").read_text())
    assert policy["read_date"] == "2026-11-09"
    assert policy["comparison_source"] == "https://artificialanalysis.ai/models"
    assert policy["gpt"]["model"] == "gpt-6.1-sol" and policy["gpt"]["effort"] == "max"
    # ADR-0030's 2026-11-09 second amendment, GPT by task: the installed sextant-codex
    # launcher keeps its owner pin; the dispatcher's rows are uncalibrated starting values
    # until the sweep's GPT arm and the known-defect measurement (#180) report.
    assert policy["gpt"]["effort_by_task"] == {
        "writer": "high",
        "review_protected": "max",
        "review_other": "xhigh",
        "lookup": "medium",
    }
    assert policy["gpt"]["effort_calibration"] == "uncalibrated"
    assert "developers.openai.com/api/docs/guides/reasoning" in policy["gpt"]["effort_source"]
    assert policy["google"]["antigravity"] == "gemini-4-argon-high"
    assert policy["google"]["effort"] == "high"
    assert policy["google"]["router_connections"] == ["agy", "antigravity"]
    assert policy["google"]["status"].startswith("interim: Carbon not in this account's catalog")
    # ADR-0030's 2026-11-09 second amendment: the blanket environment pin gives way to the
    # project default, and the lead, the dispatcher/lander/tracker roles, the worker tabs and
    # the reflection automation all run high. Only the API reviewer and the reflection pass
    # their level explicitly, because they run outside the interactive project settings.
    # test_hard_lines.py binds the hard-lines receipt to these settings, and only a host
    # engine run re-records it.
    worker, lead = policy["claude"], policy["claude_lead"]
    roles = policy["claude_roles"]
    reviewer, reflection = policy["claude_reviewer"], policy["claude_reflection"]
    assert (worker["model"], worker["effort"]) == ("claude-opus-5-5", "high")
    assert (roles["model"], roles["effort"]) == ("claude-sonnet-5-5", "high")
    assert roles["launch"] == "python3 scripts/role_launch.py <dispatcher|lander|tracker>"
    assert "tracker" in roles["pinned_in"]
    assert (lead["model"], lead["effort"]) == ("claude-fable-5-2", "high")
    assert lead["launch"] == "python3 scripts/role_launch.py lead"
    assert (reviewer["model"], reviewer["effort"]) == ("claude-fable-5-2", "high")
    assert (reflection["model"], reflection["effort"]) == ("claude-fable-5-2", "high")
    for entry in (worker, roles, lead, reviewer, reflection):
        assert "ADR-0030, 2026-11-09 amendment" in entry["authority"]
    claude = json.loads((ROOT / ".claude/settings.json").read_text())
    assert claude["model"] == worker["model"]
    assert "CLAUDE_CODE_EFFORT_LEVEL" not in claude["env"], (
        "the blanket environment pin gives way to the project default"
    )
    assert claude["effortLevel"] == worker["effort"] == "high"


def _model_mix_rows() -> dict[str, list[str]]:
    lines = (ROOT / "docs/handbook/ecosystem.md").read_text().splitlines()
    start = lines.index("### The model mix")
    rows: dict[str, list[str]] = {}
    for line in lines[start + 1 :]:
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] == "Work" or all(cell.startswith("-") for cell in cells):
            continue
        rows[cells[0]] = cells[1:]
    return rows


def test_the_model_mix_table_matches_the_settings_and_launches() -> None:
    rows = _model_mix_rows()
    policy = json.loads((RUNTIMES / "model-policy.json").read_text())
    settings = json.loads((ROOT / ".claude/settings.json").read_text())

    lead = rows["Lead: orchestration, rulings"]
    assert lead == ["Claude Fable 5.2", "high"]
    assert (policy["claude_lead"]["model"], policy["claude_lead"]["effort"]) == (
        "claude-fable-5-2",
        "high",
    )
    assert policy["claude_lead"]["launch"] == "python3 scripts/role_launch.py lead"
    lead_line = next(
        line
        for line in (ROOT / "docs/start.md").read_text().splitlines()
        if "**The lead's launch:**" in line
    )
    assert "`python3 scripts/role_launch.py lead`" in lead_line and "--effort max" not in lead_line

    review = rows[
        "`/code-review` of protection, custody, gate, hard-line or live-promotion changes"
    ]
    assert review[0].startswith("Claude Fable 5.2") and review[1].startswith("high")
    assert (policy["claude_reviewer"]["model"], policy["claude_reviewer"]["effort"]) == (
        "claude-fable-5-2",
        "high",
    )
    assert (
        "--model claude-fable-5-2 --effort high"
        in (ROOT / ".github/workflows/gate.yml").read_text()
    )

    hard = rows["Hard writer tasks and hard reviews where the situation needs Claude"]
    assert hard[0] == "Claude Opus 5.5" and hard[1].startswith("high")
    assert (policy["claude"]["model"], policy["claude"]["effort"]) == ("claude-opus-5-5", "high")

    roles = rows["Role sessions: dispatcher, lander, tracker"]
    assert roles == ["Claude Sonnet 5.5", "high"]
    assert (policy["claude_roles"]["model"], policy["claude_roles"]["effort"]) == (
        "claude-sonnet-5-5",
        "high",
    )
    assert policy["claude_roles"]["launch"] == (
        "python3 scripts/role_launch.py <dispatcher|lander|tracker>"
    )

    lookups = rows["Lookups, inventories"]
    assert "Haiku 5.5 or Sonnet 5.5" in lookups[0] and ".claude/agents/<role>.md" in lookups[0]
    assert lookups[1] == "low or medium"
    assert settings["effortLevel"] == "high" and "CLAUDE_CODE_EFFORT_LEVEL" not in settings["env"]

    writers = rows["Writers on well-specified briefs; bulk and delta reviews"]
    assert "GPT through Codex (`gpt-6.1-sol`) and dsh" in writers[0]
    assert writers[1] == "per LEAD-2345"
    assert policy["gpt"]["effort_by_task"] == {
        "writer": "high",
        "review_protected": "max",
        "review_other": "xhigh",
        "lookup": "medium",
    }

    screens = rows["Independent screens and second-family checks"]
    assert "dsh, Muse, agy (Google)" in screens[0]
    assert screens[1] == "the runtime's pin"
    assert (policy["google"]["antigravity"], policy["google"]["effort"]) == (
        "gemini-4-argon-high",
        "high",
    )
    assert (policy["meta"]["model"], policy["meta"]["effort"]) == ("muse-wonder-full-1.0", "max")
    assert "reasoningEffort: max" in (ROOT / "config/dsh/mcp/max-effort.cordis.yml").read_text()

    assert "docs/handbook/ecosystem.md#the-model-mix" in (ROOT / "AGENTS.md").read_text()
