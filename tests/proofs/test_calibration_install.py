"""Run the installer only with fixture HOME/XDG and a fake user manager."""

import configparser
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy/calibration"


@pytest.mark.parametrize("override", [None, "/work/checkout&literal|path"])
def test_installer_uses_the_checkout_and_preserves_the_data_directory(tmp_path, override):
    repo = tmp_path / "checkout"
    deploy = repo / "deploy/calibration"
    deploy.mkdir(parents=True)
    for name in (
        "install.sh",
        "sextant-calibration-data.service",
        "sextant-calibration-data.timer",
    ):
        assert (DEPLOY / name).is_file(), f"missing installation artifact: {name}"
        shutil.copy2(DEPLOY / name, deploy / name)
    home = tmp_path / "home"
    config = tmp_path / "config"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls"
    fake = fake_bin / "systemctl"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n')
    fake.chmod(0o755)
    env = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(config),
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "CALLS": str(calls),
    }
    if override is not None:
        env["SEXTANT_REPO"] = override
    subprocess.run(["bash", str(deploy / "install.sh")], env=env, check=True, capture_output=True)
    service = configparser.ConfigParser(interpolation=None)
    service.read(config / "systemd/user/sextant-calibration-data.service")
    checkout = override or str(repo)
    assert service["Service"]["WorkingDirectory"] == checkout
    command = service["Service"]["ExecStart"]
    assert f"{checkout}/scripts/with-keys.sh" in command
    assert f"{checkout}/scripts/calibration-data.sh %h/sextant-data/calibration" in command
    assert "%h/sextant/" not in command
    assert service["Service"]["MemoryMax"] == "2G"
    assert service["Service"]["MemorySwapMax"] == "0"
    assert calls.read_text().splitlines() == [
        "--user daemon-reload",
        "--user enable --now sextant-calibration-data.timer",
        "--user list-timers sextant-calibration-data.timer --no-pager",
    ]
    installed_timer = config / "systemd/user/sextant-calibration-data.timer"
    assert installed_timer.read_bytes() == (DEPLOY / "sextant-calibration-data.timer").read_bytes()
    # Convergent reinstall replaces a stale unit instead of skipping it.
    (config / "systemd/user/sextant-calibration-data.service").write_text("stale")
    subprocess.run(["bash", str(deploy / "install.sh")], env=env, check=True, capture_output=True)
    assert "stale" not in (config / "systemd/user/sextant-calibration-data.service").read_text()
