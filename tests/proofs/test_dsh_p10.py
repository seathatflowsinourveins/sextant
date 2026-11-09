"""P10's census picks: the goalloop gate and apcamargo/dsh-review.

CI-visible: the parity spec installs both picks at the piloted full SHA, and the review pick
keeps its distinct loader id. Host-only: the installed goalloop gate passes the four pilot
assertions (tests/proofs/goalloop_pilot.mjs), which need a composed dsh profile.

Source: samirliu/dsh-goalloop-agentteams@6b4b1fad8cd61f98e6eedbb4f12ed10b5dc93f17
  README.md Install (release pinning: install HEAD, a tag predates four P0/P1 fixes);
  bin/gate.mjs:1-80 (check|reset, exit 0 GO / 2 NO-GO / 3 BLOCKED);
  lib/index.js:139,166-260 (update_goal complete is denied; false-completes >= 2 latches
  BLOCKED), :1899-1925 (tools/pre-execute).
Source: apcamargo/dsh-review@4997159b99322f7551b33d72678e7a14c5282bbf README.md Install;
  config/dsh/review-cmd documents why the pick mounts through the sextant-review shim.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / ".github/gate/upstream/parity.json").read_text())
QUALITY = json.loads((ROOT / "config/dsh/quality/package.json").read_text())
PROFILE = json.loads((ROOT / ".github/gate/dsh-profile.json").read_text())
PLUGINS = SPEC["runtimes"]["dsh"]["quality"]["plugins"]

GOALLOOP = "github:samirliu/dsh-goalloop-agentteams#6b4b1fad8cd61f98e6eedbb4f12ed10b5dc93f17"
REVIEW = "github:apcamargo/dsh-review#4997159b99322f7551b33d72678e7a14c5282bbf"
SHIM = "config/dsh/review-cmd"


def _plugin_row(package: str) -> dict:
    rows = [row for row in PLUGINS if row["package"] == package]
    assert len(rows) == 1, f"parity.json quality.plugins: {package} rows = {len(rows)}"
    return rows[0]


def test_the_parity_spec_installs_the_piloted_goalloop_pin() -> None:
    assert _plugin_row("dsh-goalloop-agentteams")["spec"] == GOALLOOP
    assert QUALITY["devDependencies"]["dsh-goalloop-agentteams"] == GOALLOOP
    assert len(GOALLOOP.rsplit("#", 1)[1]) == 40


def test_the_parity_spec_delivers_the_review_shim_that_pins_apcamargo() -> None:
    row = _plugin_row("sextant-dsh-review-cmd")
    assert row["spec"] == SHIM
    shim = json.loads((ROOT / SHIM / "package.json").read_text())
    assert shim["dependencies"]["@apcamargo/dsh-review"] == REVIEW
    assert QUALITY["devDependencies"]["@apcamargo/dsh-review"] == REVIEW
    assert len(REVIEW.rsplit("#", 1)[1]) == 40


def test_the_review_shim_keeps_its_distinct_loader_id_in_the_gate_profile() -> None:
    assert "export const name = 'sextant-review';" in (ROOT / SHIM / "index.js").read_text()
    assert "id: sextant-review" in (ROOT / SHIM / "cordis.patch.yml").read_text()
    # The upstream plugin exports name "review", which @stardustlc/dsh-review owns in the
    # quality set: the shim is the only delivery path for the apcamargo pick.
    assert not [row for row in PLUGINS if row["package"] == "@apcamargo/dsh-review"]
    specs = [row["spec"] for row in PROFILE["bundles"]]
    assert specs.count(SHIM) == 1
    assert "@stardustlc/dsh-review@0.3.0" in specs


def test_the_installed_goalloop_gate_passes_the_four_pilot_assertions() -> None:
    home = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh-full")).expanduser()
    profile = os.environ.get("DSH_PILOT_PROFILE", "dsh-tui")
    package = home / "profiles" / profile / "node_modules" / "dsh-goalloop-agentteams"
    if not (package / "bin/gate.mjs").is_file():
        pytest.skip(f"{package}: the pinned goalloop bundle is not composed in this home")
    node = shutil.which("node")
    assert node, "node is not on PATH"
    run = subprocess.run(
        [node, str(ROOT / "tests/proofs/goalloop_pilot.mjs"), str(package)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    report = json.loads(run.stdout[run.stdout.index("{") :])
    assert report["ok"] is True
    assert sorted(report["assertions"]) == [
        "a-gate-reruns-the-check",
        "b-claim-denied-while-red",
        "c-two-false-completes-block",
        "d-reset-is-human-only",
    ]
