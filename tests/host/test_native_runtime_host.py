"""Native installations in the clean distro; kept separate from the offline proof module."""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("command", "version"),
    (("agy", "1.4.6"),),
)
def test_installed_native_version(command: str, version: str) -> None:
    result = subprocess.run([command, "--version"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert version in result.stdout


def test_fresh_router_bind_and_available_memory() -> None:
    prefix = Path.home() / ".local/share/sextant-lane-runtimes"
    version = subprocess.run(
        [str(prefix / "router/node_modules/.bin/omniroute"), "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert version.returncode == 0 and version.stdout.strip() == "3.8.53"
    listen = subprocess.run(
        ["ss", "-Hltn", "sport = :22128"], capture_output=True, text=True, check=False
    )
    assert "127.0.0.1:22128" in listen.stdout
    assert "0.0.0.0:22128" not in listen.stdout and "[::]:22128" not in listen.stdout
    memory = Path("/proc/meminfo").read_text().splitlines()
    available = next(
        int(line.split()[1]) * 1024 for line in memory if line.startswith("MemAvailable:")
    )
    assert available >= 20_000_000_000


def test_router_is_durable_with_upstream_notify_watchdog_and_no_secret_file() -> None:
    unit = (Path.home() / ".config/systemd/user/omniroute.service").read_text()
    for line in ("Type=notify", "NotifyAccess=all", "WatchdogSec=180", "Restart=on-failure"):
        assert line in unit
    assert "router-start.sh" in unit
    assert "EnvironmentFile=" not in unit
    assert "WorkingDirectory=/home/sextant/sextant" in unit
    active = subprocess.run(
        ["systemctl", "--user", "is-active", "omniroute.service"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert active.returncode == 0 and active.stdout.strip() == "active"
