"""The disposable OpenViking index follows main: one current revision, on a timer, loopback only.

A stand-in `ov` records each call, so no test reaches the running server at 127.0.0.1:21933.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
OV_DIR = ROOT / "deploy" / "openviking"
UNITS = ("openviking.service", "openviking-index.service", "openviking-index.timer")
SOURCE = "viking://resources/sextant"
# Answers `ls` from $OV_LS (after the CLI's own "cmd:" echo line), fails `add-resource` with
# $OV_ADD_RC, and records whether the corpus it was handed holds the committed docs.
FAKE_OV = """#!/usr/bin/env bash
echo "ov $*" >> "$OV_LOG"
case "$1" in
  ls) echo "cmd: ov $*"; cat "$OV_LS" ;;
  stat) exit "${OV_STAT_RC:-0}" ;;
  add-resource)
    [ -f "$2/guide.md" ] && [ ! -e "$2/untracked.md" ] && echo corpus-ok >> "$OV_LOG"
    exit "${OV_ADD_RC:-0}" ;;
esac
"""
FAKE_SYSTEMCTL = """#!/usr/bin/env bash
echo "systemctl $*" >> "$OV_LOG"
"""


def _git(repo: Path, *args: str) -> str:
    command = [
        "git",
        "-C",
        str(repo),
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        *args,
    ]
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()


def _checkout(tmp: Path) -> tuple[Path, str]:
    repo = tmp / "checkout"
    (repo / "docs").mkdir(parents=True)
    shutil.copytree(OV_DIR, repo / "deploy" / "openviking")
    (repo / "docs" / "guide.md").write_text("# Guide\n")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "docs")
    (repo / "docs" / "untracked.md").write_text("not committed\n")
    head = _git(repo, "rev-parse", "HEAD")
    # git-maintenance(1) "prefetch" keeps main here; lifecycle.sh registers this repo for it.
    _git(repo, "update-ref", "refs/prefetch/remotes/origin/main", head)
    return repo, head


def _run(tmp: Path, script: Path, *args: str, **env: str) -> tuple[int, list[str]]:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("ov", FAKE_OV), ("systemctl", FAKE_SYSTEMCTL)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    log = tmp / "calls.log"
    log.touch()
    listing = tmp / "listing.txt"
    if not listing.exists():
        listing.write_text("")
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    full_env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(home),
        "OV_LOG": str(log),
        "OV_LS": str(listing),
        **env,
    }
    done = subprocess.run(
        ["bash", str(script), *args], env=full_env, capture_output=True, text=True, timeout=60
    )
    return done.returncode, log.read_text().splitlines()


def _index(repo: Path) -> Path:
    return repo / "deploy" / "openviking" / "index.sh"


def test_the_index_names_the_revision_it_archived(tmp_path: Path) -> None:
    repo, head = _checkout(tmp_path)
    code, calls = _run(tmp_path, _index(repo))
    assert code == 0
    adds = [call for call in calls if call.startswith("ov add-resource ")]
    assert len(adds) == 1
    assert f"--to {SOURCE}/{head} " in adds[0]
    for flag in ("--processing-mode vectors_only", "--watch-interval 0", "--wait"):
        assert flag in adds[0]
    assert "corpus-ok" in calls  # The tracked docs only, from that commit.
    assert (
        tmp_path / "home/.local/share/sextant-openviking/indexed-revision"
    ).read_text().strip() == head
    # The CLI uploads a zip of the directory, so the copy is gone once the import returns.
    assert list((tmp_path / "home/.local/share/sextant-openviking/corpus").iterdir()) == []


def test_the_retire_step_removes_only_other_revisions(tmp_path: Path) -> None:
    repo, head = _checkout(tmp_path)
    old = "f" * 40
    (tmp_path / "listing.txt").write_text(
        "\n".join(
            (
                f"{SOURCE}/{head}",
                f"{SOURCE}/{old}",
                f"{SOURCE}/{'e' * 39}",
                f"{SOURCE}/{'E' * 40}",
                f"{SOURCE}/notes",
                f"{SOURCE}/{old}/adr",
                f"{SOURCE}-other/{'d' * 40}",
                f"viking://resources/{'c' * 40}",
            )
        )
        + "\n"
    )
    code, calls = _run(tmp_path, _index(repo))
    assert code == 0
    removed = [call for call in calls if call.startswith("ov rm ")]
    assert removed == [f"ov rm --recursive {SOURCE}/{old}"]
    assert calls.index(removed[0]) > max(
        i for i, call in enumerate(calls) if call.startswith("ov stat ")
    )


def test_a_failed_import_retires_nothing(tmp_path: Path) -> None:
    repo, _ = _checkout(tmp_path)
    (tmp_path / "listing.txt").write_text(f"{SOURCE}/{'f' * 40}\n")
    code, calls = _run(tmp_path, _index(repo), OV_ADD_RC="1")
    assert code != 0
    assert not [call for call in calls if call.startswith(("ov rm ", "ov ls "))]
    assert not (tmp_path / "home/.local/share/sextant-openviking/indexed-revision").exists()


def test_a_current_revision_is_not_imported_again(tmp_path: Path) -> None:
    repo, head = _checkout(tmp_path)
    assert _run(tmp_path, _index(repo))[0] == 0
    (tmp_path / "calls.log").write_text("")
    (tmp_path / "listing.txt").write_text(f"{SOURCE}/{head}\n{SOURCE}/{'a' * 40}\n")
    code, calls = _run(tmp_path, _index(repo))
    assert code == 0
    assert not [call for call in calls if call.startswith("ov add-resource ")]
    assert [call for call in calls if call.startswith("ov rm ")] == [
        f"ov rm --recursive {SOURCE}/{'a' * 40}"
    ]
    # A revision that is recorded but missing from the server is imported again.
    (tmp_path / "calls.log").write_text("")
    code, calls = _run(tmp_path, _index(repo), OV_STAT_RC="1")
    assert any(call.startswith("ov add-resource ") for call in calls)


def test_an_explicit_revision_is_resolved_to_its_full_commit(tmp_path: Path) -> None:
    repo, head = _checkout(tmp_path)
    (repo / "docs" / "guide.md").write_text("# Guide, revised\n")
    _git(repo, "commit", "-q", "-am", "revise")
    code, calls = _run(tmp_path, _index(repo), "HEAD~1")
    assert code == 0
    assert any(f"--to {SOURCE}/{head} " in call for call in calls)


def test_before_the_first_prefetch_the_index_follows_origin_main(tmp_path: Path) -> None:
    repo, head = _checkout(tmp_path)
    _git(repo, "update-ref", "-d", "refs/prefetch/remotes/origin/main")
    _git(repo, "update-ref", "refs/remotes/origin/main", head)
    (repo / "docs" / "guide.md").write_text("# Guide, on a branch\n")
    _git(repo, "commit", "-q", "-am", "branch work")
    code, calls = _run(tmp_path, _index(repo))
    assert code == 0
    assert any(f"--to {SOURCE}/{head} " in call for call in calls)


def test_the_installer_renders_every_unit_from_this_checkout_and_starts_the_timer(
    tmp_path: Path,
) -> None:
    repo, _ = _checkout(tmp_path)
    code, calls = _run(tmp_path, repo / "deploy" / "openviking" / "install-units.sh")
    assert code == 0
    installed = tmp_path / "home/.config/systemd/user"
    for unit in UNITS:
        text = (installed / f"sextant-{unit}").read_text()
        assert "%h/sextant/deploy" not in text
    server = (installed / "sextant-openviking.service").read_text()
    assert f"--config {repo}/deploy/openviking/ov.conf" in server
    index = (installed / "sextant-openviking-index.service").read_text()
    assert f"{repo}/deploy/openviking/index.sh" in index
    assert "systemctl --user daemon-reload" in calls
    enable = [call for call in calls if call.startswith("systemctl --user enable --now ")]
    assert (
        enable
        and "sextant-openviking-index.timer" in enable[0]
        and "sextant-openviking.service" in enable[0]
    )
    # Never a restart: the running server keeps its clients until the lead's switch-over.
    assert not [call for call in calls if re.search(r"\b(restart|stop|kill)\b", call)]
    setup = (ROOT / "deploy/wsl/setup.sh").read_text()
    assert "bash deploy/openviking/install-units.sh" in setup
    assert setup.index("install-units.sh") < setup.index("just index")


def test_the_timer_has_a_schedule_and_runs_the_index_once_at_a_time() -> None:
    timer = (OV_DIR / "openviking-index.timer").read_text()
    assert re.search(r"^OnCalendar=\S", timer, re.M)
    assert "Persistent=true" in timer and "WantedBy=timers.target" in timer
    service = (OV_DIR / "openviking-index.service").read_text()
    assert "Type=oneshot" in service
    assert "ExecStart=/usr/bin/bash %h/sextant/deploy/openviking/index.sh" in service
    assert "flock" in (OV_DIR / "index.sh").read_text()


def test_every_unit_binds_or_addresses_loopback_only() -> None:
    config = json.loads((OV_DIR / "ov.conf").read_text())
    assert config["server"]["host"] == "127.0.0.1"
    assert json.loads((OV_DIR / "ovcli.conf").read_text())["url"].startswith("http://127.0.0.1:")
    for name in (*UNITS, "index.sh", "install-units.sh"):
        text = (OV_DIR / name).read_text()
        for address in re.findall(r"\b(?:https?|wss?)://([^/\s:\"']+)", text):
            assert address == "127.0.0.1", (name, address)
        assert not re.search(r"\b0\.0\.0\.0\b", text), name
    assert "OPENVIKING_CLI_CONFIG_FILE" in (OV_DIR / "index.sh").read_text()


def test_the_index_and_timer_name_no_model() -> None:
    pins = json.loads((OV_DIR / "pins.json").read_text())["embedding"]
    model = Path(pins["file"]).stem
    for name in (
        "index.sh",
        "openviking-index.service",
        "openviking-index.timer",
        "install-units.sh",
    ):
        text = (OV_DIR / name).read_text()
        assert model not in text and "dimension" not in text, name
