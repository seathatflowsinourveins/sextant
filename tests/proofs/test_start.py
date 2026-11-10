"""The clean start: loaded from GitHub, at the pins this repo already holds."""

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
USER_DATA = (ROOT / "deploy" / "wsl" / "sextant.user-data").read_text()
SETUP = ROOT / "deploy" / "wsl" / "setup.sh"
UPDATE = ROOT / "deploy" / "wsl" / "update-orca.sh"
VERSION = re.compile(r"(?<![\d.])\d+\.\d+\.\d+(?![\d.])")
# A stand-in for Orca's CLI: its version, its service's dry run and status, and a recorded install.
FAKE_ORCA = """#!/usr/bin/env bash
unit="$HOME/.config/systemd/user/orca-serve.service"
start='ExecStart=/usr/bin/orca-ide serve --supervise --no-pairing --port 6771'
body() { printf '[Service]\\nEnvironment=PATH=%s\\n%s\\n' "$1" "$start"; }
install='serve service install --port 6771'
case "$*" in
  --version) echo "$FAKE_ORCA_VERSION" ;;
  "$install --dry-run --json") jq -n --arg c "$(body "$PATH")" '{result: {content: $c}}' ;;
  "serve service status --json")
    if [ -f "$unit" ]; then echo '{"result": {"verdict": "live"}}'; else echo '{}'; fi ;;
  "$install")
    echo install >> "$FAKE_ORCA_LOG"
    mkdir -p "${unit%/*}"
    body "$PATH" > "$unit" ;;  # Orca writes the caller's PATH into its unit
  *) echo "unexpected: $*" >&2; exit 9 ;;
esac
"""


def test_the_distro_loads_this_repo_from_github() -> None:
    assert USER_DATA.startswith("#cloud-config\n")
    assert 'gh repo clone seathatflowsinourveins/sextant "$HOME/sextant"' in USER_DATA
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
    ):
        assert re.search(pattern, dockerfile, re.MULTILINE), pattern
    # Three-part versions only, so an address such as the loopback one is not a pin.
    for script in (SETUP, UPDATE):
        assert not VERSION.search(script.read_text()), (
            f"{script.name}: pins live in the repo's own files"
        )


# A stand-in for curl: it records its arguments and serves an installer that records its target.
FAKE_CURL = r"""#!/usr/bin/env bash
printf 'curl %s\n' "$*" >> "$FAKE_LOG"
cat <<'INSTALLER'
printf 'installer %s\n' "${1-}" >> "$FAKE_LOG"
INSTALLER
"""


def test_setup_installs_the_hosts_claude_code_on_its_latest_channel(tmp_path: Path) -> None:
    """ADR-0030's 2026-11-09 amendment: "The native installer accepts either a specific version
    number or a release channel (`latest` or `stable`). The channel you choose at install time
    becomes your default for auto-updates" (code.claude.com/docs/en/setup, read 2026-11-09). The
    host takes `latest`; the devcontainer image keeps its own pin."""
    lines = [line for line in SETUP.read_text().splitlines() if "claude.ai/install.sh" in line]
    assert len(lines) == 1, "setup runs Claude Code's installer once"
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "curl").write_text(FAKE_CURL)
    (tmp_path / "bin" / "curl").chmod(0o755)
    log = tmp_path / "log"
    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "FAKE_LOG": str(log)}
    done = subprocess.run(["bash", "-c", lines[0]], env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    want = ["curl -fsSL https://claude.ai/install.sh", "installer latest"]
    assert log.read_text().splitlines() == want
    dockerfile = (ROOT / ".devcontainer" / "Dockerfile").read_text()
    assert re.search(r"^RUN claude install \d+\.\d+\.\d+$", dockerfile, re.MULTILINE)


def _no_prompts(home: Path) -> dict:
    """Run setup.sh's own `no_prompts` on one settings home and return the settings it leaves."""
    function = re.search(r"^no_prompts\(\) \{\n.*?^\}\n", SETUP.read_text(), re.M | re.S)
    assert function, "setup.sh defines no_prompts"
    done = subprocess.run(
        ["bash", "-c", f'{function[0]}no_prompts "$1"', "no_prompts", str(home)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    return json.loads((home / "settings.json").read_text())


def test_setup_lets_claude_code_update_itself_on_latest(tmp_path: Path) -> None:
    """ADR-0030's 2026-11-09 amendment: Claude Code updates itself in the background on its
    latest channel (code.claude.com/docs/en/setup, read 2026-11-09), so a new model runs at the
    next launch. Setup names the channel and removes the updater switch an earlier run wrote."""
    fresh = _no_prompts(tmp_path / "fresh")
    assert fresh == {
        "permissions": {"defaultMode": "bypassPermissions"},
        "skipDangerousModePermissionPrompt": True,
        "autoUpdatesChannel": "latest",
    }
    removed = re.findall(r"del\(\.env\.(\w+)\)", SETUP.read_text())
    assert len(removed) == 1, "setup removes exactly one environment switch"
    home = tmp_path / "earlier"
    home.mkdir()
    earlier = {"env": {removed[0]: "1", "KEEP": "1"}, "autoUpdatesChannel": "stable"}
    (home / "settings.json").write_text(json.dumps({**earlier, "permissions": {"allow": ["Read"]}}))
    again = _no_prompts(home)
    assert again["env"] == {"KEEP": "1"} and again["autoUpdatesChannel"] == "latest"
    assert again["permissions"] == {"allow": ["Read"], "defaultMode": "bypassPermissions"}
    # Every settings home setup provisions: the user's own and each Orca-managed Claude profile.
    setup = SETUP.read_text()
    assert 'no_prompts "$HOME/.claude"' in setup
    assert 'for profile in "$HOME"/.config/orca/claude-profiles/*/home; do' in setup
    assert '[ -d "$profile" ] && no_prompts "$profile"' in setup


def test_orca_runs_as_its_own_service_at_the_pin() -> None:
    # Orca's `serve service install` writes the unit, so the repo keeps only its drop-in.
    assert not (ROOT / "deploy" / "wsl" / "orca-serve.service").exists()
    assert subprocess.run(["bash", "-n", str(UPDATE)], check=False).returncode == 0
    update = UPDATE.read_text()
    assert "orca-ide serve service install --port" in update and "sha256sum -c -" in update
    # One pin, in the user-data: the release tag and the file name are the same version.
    assert re.search(r"releases/download/v(\d+\.\d+\.\d+)/orca-ide_\1_amd64\.deb$", USER_DATA, re.M)
    assert re.search(r'^- echo "[0-9a-f]{64}  /tmp/orca-ide\.deb"', USER_DATA, re.M)
    limits = (ROOT / "deploy" / "wsl" / "orca-serve-limits.conf").read_text()
    for line in (
        "Environment=ORCA_TERMINAL_MEMORY_MAX=16G",
        "Environment=ORCA_TERMINAL_MEMORY_SWAP_MAX=0",
    ):
        assert line in limits, line
    setup = SETUP.read_text()
    assert "deploy/wsl/update-orca.sh" in setup and "orca-serve-limits.conf" in setup
    assert '"I reach this address through' in setup
    assert (
        "**I reach this address through an SSH tunnel**" in (ROOT / "docs" / "start.md").read_text()
    )


def test_orca_update_leaves_a_current_server_alone(tmp_path: Path) -> None:
    pin = re.search(r"releases/download/v(\d+\.\d+\.\d+)/", USER_DATA)
    assert pin
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "orca-ide").write_text(FAKE_ORCA)
    (bin_dir / "orca-ide").chmod(0o755)
    log = tmp_path / "installs"
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_ORCA_VERSION": pin[1],
        "FAKE_ORCA_LOG": str(log),
    }

    def update(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(UPDATE), *args], env=env, capture_output=True, text=True, check=False
        )

    # Before pairing there is no server, so nothing is installed.
    first = update()
    assert first.returncode == 0, first.stderr
    assert not log.exists()
    # Setup's call, after pairing: Orca's unit goes in, with the limits beside it.
    second = update("6771")
    assert second.returncode == 0, second.stderr
    assert log.read_text().splitlines() == ["install"]
    dropin = tmp_path / ".config" / "systemd" / "user" / "orca-serve.service.d" / "limits.conf"
    assert dropin.read_text() == (ROOT / "deploy" / "wsl" / "orca-serve-limits.conf").read_text()
    # `just orca-update` with everything current: the port comes from the unit, a different PATH
    # in it is not a change, and the server is not restarted.
    third = update()
    assert third.returncode == 0, third.stderr
    assert log.read_text().splitlines() == ["install"]


def _two_dsh(home: Path) -> tuple[Path, Path]:
    """sextant-agents' own dsh, and the keyed launcher parity.sh links in ~/.local/bin: as `dsh`,
    the one name AO's deepseek-harness adapter resolves, and as `sextant-dsh`, for every other
    launch."""
    agents = home / ".local/share/sextant-agents/node_modules/.bin"
    lane = home / ".local/bin"
    for directory in (agents, lane):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "dsh").write_text("#!/bin/sh\n")
        (directory / "dsh").chmod(0o755)
    (lane / "sextant-dsh").symlink_to(lane / "dsh")
    return agents, lane


def _resolve(path: str, name: str) -> str:
    found = subprocess.run(
        ["/bin/bash", "-c", f"command -v {name}"],
        env={"PATH": path}, capture_output=True, text=True, check=False,
    )  # fmt: skip
    return found.stdout.strip()


def test_orcas_unit_finds_the_keyed_lane_launchers_before_the_agents_own(tmp_path: Path) -> None:
    """Every Orca tab inherits the unit's PATH, which Orca takes from its caller. Setup's own PATH
    puts the agents' bin first, so the install call must put ~/.local/bin ahead of it."""
    pin = re.search(r"releases/download/v(\d+\.\d+\.\d+)/", USER_DATA)
    assert pin
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "orca-ide").write_text(FAKE_ORCA)
    (bin_dir / "orca-ide").chmod(0o755)
    agents, lane = _two_dsh(tmp_path)
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "PATH": f"{bin_dir}:{agents}:{lane}:{os.environ['PATH']}",  # setup.sh's order
        "FAKE_ORCA_VERSION": pin[1],
        "FAKE_ORCA_LOG": str(tmp_path / "installs"),
    }
    done = subprocess.run(
        ["bash", str(UPDATE), "6771"], env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    unit = (tmp_path / ".config/systemd/user/orca-serve.service").read_text()
    path = re.search(r"^Environment=PATH=(.*)$", unit, re.M)
    assert path
    for name in ("dsh", "sextant-dsh"):
        assert _resolve(path[1], name) == str(lane / name)
    # The distinct name needs no PATH order: it resolves from setup.sh's own, agents first.
    assert _resolve(f"{agents}:{lane}:/usr/bin:/bin", "sextant-dsh") == str(lane / "sextant-dsh")
    # The first server, at pairing, starts the terminal host that outlives it.
    assert 'env "${limits[@]}" PATH="$HOME/.local/bin:$PATH" orca-ide serve' in SETUP.read_text()


def test_a_login_shell_finds_the_keyed_lane_launchers_before_the_agents_own(tmp_path: Path) -> None:
    profile = USER_DATA.split("- path: /etc/profile.d/sextant-path.sh\n", 1)[1]
    export = next(line.strip() for line in profile.splitlines() if "export PATH=" in line)
    _, lane = _two_dsh(tmp_path)
    found = subprocess.run(
        ["/bin/bash", "-c", f"{export}; command -v dsh sextant-dsh"],
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert found.stdout.split() == [str(lane / "dsh"), str(lane / "sextant-dsh")]
