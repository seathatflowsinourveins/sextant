"""The issue #62 roster: release age, artifact identity and native Orca support."""

import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
RUNTIMES = ROOT / "deploy/wsl/lane-runtimes"
NAMES = ("pi", "omp", "opencode2", "hermes", "openhands-sdk", "antigravity")


@pytest.mark.parametrize("name", NAMES)
def test_runtime_has_an_eligible_pinned_artifact_and_an_honest_launch_scope(name: str) -> None:
    pins = json.loads((RUNTIMES / "pins.json").read_text())
    assert set(pins["runtimes"]) == set(NAMES)
    row = pins["runtimes"][name]
    assert re.fullmatch(r"[0-9a-f]{40}", row["commit"])
    published = datetime.fromisoformat(row["published_at"].replace("Z", "+00:00"))
    checked = datetime.fromisoformat(pins["checked_at"].replace("Z", "+00:00"))
    assert checked.tzinfo == UTC
    assert checked - published >= timedelta(days=14)
    assert row["install_source"] and row["convergence"]
    if name == "openhands-sdk":
        assert row["orca_agent"] is None, "Orca 1.4.251 has no OpenHands SDK agent ID"
    else:
        assert row["orca_agent"] == name
    if "npm_package" in row:
        lock = json.loads((RUNTIMES / "package-lock.json").read_text())
        package = lock["packages"]["node_modules/" + row["npm_package"]]
        assert package["version"] == row["version"]
        assert package["integrity"].startswith("sha512-")
    if "sha256" in row:
        assert re.fullmatch(r"[0-9a-f]{64}", row["sha256"])


def test_fresh_router_is_pinned_and_has_no_old_campaign_endpoint() -> None:
    pins = json.loads((RUNTIMES / "pins.json").read_text())
    assert pins["omniroute"]["version"] == "3.8.53"
    assert pins["omniroute"]["commit"] == "191dce8d534ceb56c28a08e71381284a9a87838f"
    router = (RUNTIMES / "router-start.sh").read_text()
    assert "127.0.0.1:22128" in router
    for port in (20128, 20129, 20130):
        assert str(port) not in router
    assert "with-keys.sh" in router and "OMNIROUTE_STORAGE_ENCRYPTION_KEY" in router


@pytest.mark.parametrize(
    ("name", "flags", "arguments"),
    (
        ("pi", "--provider omniroute", ("--help",)),
        ("omp", "--yolo", ("--help",)),
        ("opencode2", "--auto", ("--help",)),
        ("opencode2", "run --standalone --auto", ("run", "--help")),
    ),
)
def test_native_launch_uses_key_injection_inside_the_runtime_process(
    tmp_path: Path, name: str, flags: str, arguments: tuple[str, ...]
) -> None:
    # The CLI control flow is real; the external key store and agent are stand-ins.
    prefix = tmp_path / "installed"
    prefix.mkdir()
    launcher = prefix / "api-launch.sh"
    shutil.copyfile(RUNTIMES / "api-launch.sh", launcher)
    launcher.chmod(0o755)
    (prefix / "repository-path").write_text(str(tmp_path / "repo") + "\n")
    key_command = tmp_path / "repo/scripts/with-keys.sh"
    key_command.parent.mkdir(parents=True)
    store_name = {"pi": "PI", "omp": "OMP", "opencode2": "OPENCODE"}[name]
    key_command.write_text(
        '#!/bin/sh\n[ "$1 $2 $3 $4" = "--strict -k '
        f'OMNIROUTE_KEY_{store_name}:OMNIROUTE_API_KEY --" ] || exit 9\n'
        'shift 4\nexec "$@"\n'
    )
    key_command.chmod(0o755)
    binary = prefix / ("bin/omp" if name == "omp" else f"node_modules/.bin/{name}")
    binary.parent.mkdir(parents=True)
    binary.write_text(
        '#!/bin/sh\n[ -z "${CLAUDE_CODE_OAUTH_TOKEN+x}" ] || exit 10\nprintf "%s\\n" "$*"\n'
    )
    binary.chmod(0o755)
    (prefix / "profiles").mkdir()
    (prefix / "profiles/opencode.json").write_text("{}")
    command = tmp_path / name
    command.symlink_to(launcher)
    result = subprocess.run(
        [str(command), *arguments],
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": "fixture"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert flags in result.stdout


def test_profiles_use_environment_keys_and_keep_max_effort_request(tmp_path: Path) -> None:
    result = subprocess.run(
        ["python3", str(RUNTIMES / "configure.py"), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    pi = json.loads((tmp_path / "profiles/pi/models.json").read_text())
    provider = pi["providers"]["omniroute"]
    assert provider["baseUrl"] == "http://127.0.0.1:22128/v1"
    assert provider["apiKey"] == "${OMNIROUTE_API_KEY}"
    assert provider["models"][0]["id"] == "sextant-gpt"
    assert provider["models"][0]["thinkingLevelMap"] == {"max": "max"}
    opencode = json.loads((tmp_path / "profiles/opencode.json").read_text())
    assert opencode["model"] == "omniroute/sextant-gpt"
    hermes = json.loads((tmp_path / "profiles/hermes/config.yaml").read_text())
    sdk = json.loads((tmp_path / "profiles/openhands.json").read_text())
    assert hermes["model"]["base_url"] == sdk["base_url"] == provider["baseUrl"]
    assert hermes["agent"]["reasoning_effort"] == sdk["reasoning_effort"] == "max"


def test_model_policy_keeps_the_approved_google_interim_and_native_claude() -> None:
    policy = json.loads((RUNTIMES / "model-policy.json").read_text())
    assert policy["read_date"] == "2026-11-06"
    assert policy["comparison_source"] == "https://artificialanalysis.ai/models"
    assert policy["gpt"]["model"] == "gpt-6.1-sol" and policy["gpt"]["effort"] == "max"
    assert policy["google"]["antigravity"] == "gemini-4-argon-high"
    assert policy["google"]["effort"] == "high"
    assert policy["google"]["router_connections"] == ["agy", "antigravity"]
    assert policy["google"]["status"].startswith("interim: Carbon not in this account's catalog")
    claude = json.loads((ROOT / ".claude/settings.json").read_text())
    assert claude["model"] == "claude-opus-5-5"
    assert claude["env"]["CLAUDE_CODE_EFFORT_LEVEL"] == "max"
    assert "effortLevel" not in claude, "persistent max uses the upstream environment setting"
