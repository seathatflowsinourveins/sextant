"""The finished Sharadar coverage study lives on its tagged research branch; gate keeps the record.

The runner and its 21-case offline driver proof are one-off study code, so the budget rule
(tests/repo/test_budgets.py) keeps them on `research/sharadar-coverage` at
`sharadar-coverage-2026-11-09`. Gate keeps the reusable direct transport, the receipt and this
proof that the recorded result still reads. No test here makes a network call or needs a key.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
NOTE = ROOT / "docs" / "research" / "2026-11-06-sharadar-coverage.md"
RECEIPT = ROOT / "docs" / "research" / "2026-11-06-sharadar-coverage-receipt.json"
SRC = ROOT / "src" / "sextant" / "research" / "sharadar_coverage.py"
BRANCH = "research/sharadar-coverage"
TAG = "sharadar-coverage-2026-11-09"


def test_the_finished_coverage_study_is_not_a_src_module() -> None:
    assert not SRC.exists()
    for path in sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "tests").rglob("*.py")):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith(("from sextant.research import", "import sextant.research")):
                assert "sharadar_coverage" not in stripped, path


def test_the_evidence_note_names_the_tagged_research_branch() -> None:
    note = NOTE.read_text()
    assert BRANCH in note
    assert TAG in note


def test_the_measured_receipt_still_reads() -> None:
    receipt = json.loads(RECEIPT.read_text())
    assert receipt["scope"] == "literal_symbol_daily_coverage_only"
    assert receipt["pit_verified"] is False
    assert receipt["historical_known_at"] is None
    assert receipt["asof"] == "2026-11-06T16:58:52+00:00"
    assert receipt["capture_mode"] == "authenticated"
    assert receipt["capture_sha256"] == (
        "cd158d7932f58190b2ffddf2f380d0c2bbd235b5aad3789e079b08afc1ea7de3"
    )
    assert receipt["implementation_sha"] == "4e06da7a32a616794d27d8a042fdcd98501ebe34"
    assert receipt["implementation_source_sha256"] == (
        "bda1cc0d7685d14dfe6aad250233090339aa914e0567a6327a5a194101bf6fd3"
    )
    probe = receipt["access_probe"]
    assert probe["http_status"] == 200
    assert probe["entitlement_verified"] is False
    assert probe["raw_sha256"] == (
        "b0aea7d2b6c89a653a6c07f9749a01cb5c3eb3cd8b709f04cf5ad76aed7aa6b6"
    )
    assert receipt["client"]["adapter_commit"] == ("8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa")
    assert receipt["client"]["commit"] == "6e83187b8feb273ed4c6cdab5efd8d54901dfab3"
    assert receipt["float_history"]["status"] == "UNVERIFIED"
    assert receipt["float_history"]["shares_outstanding_is_float"] is False
    assert receipt["independent_verification"] == {
        "offline_rebuild_idempotent": True,
        "raw_response_hashes": 1887,
        "report_artifact_hashes": 1438,
        "session_event_hashes": 1436,
    }
    assert receipt["report_sha256"] == (
        "deee6053219eae9692db678418aa25b452ed72d1a13767000654b40acba31ba7"
    )
    assert receipt["literal_price_absent_events"] == 226
    assert receipt["literal_price_absent_with_master_candidates"] == 224
    gainer = receipt["seed_coverage"]["selected_gainer"]
    assert (gainer["events"], gainer["price_observed"], gainer["absent"]) == (957, 814, 143)
    loser = receipt["seed_coverage"]["selected_loser"]
    assert (loser["events"], loser["price_observed"], loser["absent"]) == (215, 132, 83)
