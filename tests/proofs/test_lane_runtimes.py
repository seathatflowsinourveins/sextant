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
    assert "docs/adr/0030-latest-sota-models.md:35" in row["authority"]
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
    assert policy["read_date"] == "2026-11-06"
    assert policy["comparison_source"] == "https://artificialanalysis.ai/models"
    assert policy["gpt"]["model"] == "gpt-6.1-sol" and policy["gpt"]["effort"] == "max"
    assert policy["google"]["antigravity"] == "gemini-4-argon-high"
    assert policy["google"]["effort"] == "high"
    assert policy["google"]["router_connections"] == ["agy", "antigravity"]
    assert policy["google"]["status"].startswith("interim: Carbon not in this account's catalog")
    # The policy register moves on ADR-0030's measured gap; the project settings keep Opus 5.5 until
    # the hard-lines receipt is regenerated on the host (test_hard_lines.py binds receipt["model"]
    # to this file, and only a real Claude engine can re-record it).
    assert policy["claude"]["model"] == "claude-fable-5-2" and policy["claude"]["effort"] == "max"
    claude = json.loads((ROOT / ".claude/settings.json").read_text())
    assert claude["model"] == "claude-opus-5-5"
    assert claude["env"]["CLAUDE_CODE_EFFORT_LEVEL"] == "max"
    assert "effortLevel" not in claude, "persistent max uses the upstream environment setting"
