"""The finished exit-grid study lives on its tagged research branch; gate keeps the record.

The registered runner and its driver proof are one-off study code, so the budget rule
(tests/repo/test_budgets.py) keeps them on `research/exit-grid-141` at
`exit-grid-141-2026-11-09`. Gate keeps the registration, the report and the 27 outcome rows, and
this proof that the recorded run still reads. The opt-in per-cell rerun is on the branch.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
NOTE = ROOT / "docs" / "research" / "2026-11-06-exit-grid-141.md"
EVIDENCE = ROOT / "docs" / "research" / "2026-11-06-exit-grid-141"
SRC = ROOT / "src" / "sextant" / "research" / "exit_grid_141.py"
BRANCH = "research/exit-grid-141"
TAG = "exit-grid-141-2026-11-09"
REGISTRATION_SHA256 = "8302f7c34738260a56822205a617699f947d27409c8332c55be26398522285c6"
OUTCOME_SHA256 = "2190e30922d1e43c7865b992840967bfb981507be3f03dcb0f3b1f58513f82b7"
PR2_OUTCOME_SHA256 = "9688b74bb76acee81482b3e2144d1d51cd378d7b56d89a468275541f2d3905d5"


def test_the_finished_grid_study_is_not_a_src_module() -> None:
    assert not SRC.exists()
    for path in sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "tests").rglob("*.py")):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith(("from sextant.research import", "import sextant.research")):
                assert "exit_grid_141" not in stripped, path


def test_the_evidence_note_names_the_tagged_research_branch() -> None:
    note = NOTE.read_text()
    assert BRANCH in note
    assert TAG in note


def test_the_registered_run_still_reads_from_the_committed_evidence() -> None:
    assert hashlib.sha256((EVIDENCE / "registration.json").read_bytes()).hexdigest() == (
        REGISTRATION_SHA256
    )
    assert hashlib.sha256((EVIDENCE / "outcome.jsonl").read_bytes()).hexdigest() == OUTCOME_SHA256
    assert (
        hashlib.sha256((EVIDENCE / "run-a8282a4" / "outcome.jsonl").read_bytes()).hexdigest()
        == PR2_OUTCOME_SHA256
    )
    report = json.loads((EVIDENCE / "report.json").read_text())
    run = json.loads((EVIDENCE / "run-a8282a4" / "report.json").read_text())
    assert report["version"] == "exit-grid-141/1"
    assert report["issue"] == 141
    assert report["tier"] == "MODELED"
    assert report["registration_sha256"] == REGISTRATION_SHA256
    assert report["implementation"] == "4656648c6ed174403ffc5490eec7f2136772c6c2"
    assert report["selected"] is None
    assert report["inputs"] == {
        "b-owner-first-orders.json": (
            "5e95de9eaefd9e24cfbd96850ab499fdfa6505e83dcf205ca485584ad5d9e6d3"
        ),
        "fills-2026-10-26_29.jsonl": (
            "55eee2b64506c19e23d4c421c803be687daf06ebb39a2b84f621ea2a90618c0f"
        ),
        "minute-bars-2026-10-26_29.jsonl": (
            "105caeee0645455aa0e1de23a1720639347062061944ea3d49eedb6d99a86a69"
        ),
    }
    assert len(report["surface"]) == 27
    assert set(report["surface"]) == set(run["surface"])
    assert run["implementation"] == "a8282a4f11d69b2bd595d3035439f5edd64276be"
    assert run["registration_sha256"] == REGISTRATION_SHA256
    start = report["surface"]["b0.01-m1-g0.1"]
    assert start["3"]["mean_bps"] == "-49.71288104544344375585893207"
    assert start["3"]["median_bps"] == "-5.419673177952573070559892000"
    assert start["3"]["n"] == 1025
    rows = [json.loads(line) for line in (EVIDENCE / "outcome.jsonl").read_text().splitlines()]
    assert len(rows) == 27
    assert all(row["state"] == "COMPLETE" and row["result"]["selected"] is False for row in rows)
