"""The clean start: loaded from GitHub, at the pins this repo already holds."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
USER_DATA = (ROOT / "deploy" / "wsl" / "sextant.user-data").read_text()
SETUP = ROOT / "deploy" / "wsl" / "setup.sh"


def test_the_distro_loads_this_repo_from_github() -> None:
    assert USER_DATA.startswith("#cloud-config\n")
    assert "gh repo clone seathatflowsinourveins/sextant" in USER_DATA
    assert "deploy/wsl/setup.sh" in USER_DATA
    assert "sha256sum -c -" in USER_DATA
    assert "timezone: America/New_York" in USER_DATA
    assert "useWindowsTimezone=false" in USER_DATA
    assert "sudo: ALL=(ALL) NOPASSWD:ALL" in USER_DATA
    assert "--scopes workflow,user" in USER_DATA
    assert "bypassPermissions" in SETUP.read_text()
    assert "uid: 1500" in USER_DATA and "defaultUid = 1500" in USER_DATA
    assert "appendWindowsPath=false" in USER_DATA
    start = (ROOT / "docs" / "start.md").read_text()
    for step in ("--no-launch", "cloud-init status --wait", "wsl --terminate sextant"):
        assert step in start, step


def test_a_stopped_login_retries_and_leaves_a_readable_log() -> None:
    script = USER_DATA.split("sextant-first-login.sh\n", 1)[1].split("content: |\n", 1)[1]
    block = script.split("\n\n", 1)[0]
    lines = [line.removeprefix("    ") for line in block.splitlines() if line.startswith("    ")]
    shell = subprocess.run(["bash", "-n"], input="\n".join(lines), text=True, check=False)
    assert shell.returncode == 0
    assert "until sextant_first_login" in block
    assert "pull --ff-only" in block
    setup = SETUP.read_text()
    assert "first-login.log" in setup
    assert "SECONDS - began" in setup, "a server that never started must stop setup"
    for line in setup.splitlines():
        if "tee -a" in line:
            assert "serve" not in line and "account add" not in line, line


def test_setup_reads_every_pin_from_the_repo() -> None:
    assert subprocess.run(["bash", "-n", str(SETUP)], check=False).returncode == 0
    dockerfile = (ROOT / ".devcontainer" / "Dockerfile").read_text()
    for pattern in (
        r"^FROM ghcr\.io/astral-sh/uv:[0-9.]+@",
        r"^ARG NODE_VERSION=\S+",
        r"^ARG JUST_VERSION=\S+",
        r"^RUN claude install \S+",
    ):
        assert re.search(pattern, dockerfile, re.MULTILINE), pattern
    # Three-part versions only, so an address such as the loopback one is not a pin.
    assert not re.search(r"(?<![\d.])\d+\.\d+\.\d+(?![\d.])", SETUP.read_text()), (
        "pins live in the repo's own files"
    )
