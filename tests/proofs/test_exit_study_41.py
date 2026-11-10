"""Design row 7's proof: the 96-variant exit study reruns from the catalog and reproduces its table.

CI checks the committed trial rows against the published table. The full rerun needs the exact
inputs (private release exit-study-41-inputs-2026-10-29), which CI's tokenless runner cannot read,
so it runs wherever they are present and skips, saying why, where they are not.
"""

import hashlib
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.exit_study_41 import (  # noqa: E402
    DEFAULT_INPUTS,
    INPUTS,
    STUDY_SHA256,
    published_table,
    rerun,
    table,
)

EVIDENCE = ROOT / "docs" / "research" / "2026-11-06-exit-study-41"
INPUT_DIR = Path(os.environ.get("SEXTANT_EXIT_STUDY_41", DEFAULT_INPUTS))


def _committed() -> list[dict]:
    return [json.loads(line) for line in (EVIDENCE / "trials.jsonl").read_text().splitlines()]


def test_the_study_is_the_pinned_file_verbatim() -> None:
    source = (ROOT / "research" / "b_exit_replay.py").read_bytes()
    assert hashlib.sha256(source).hexdigest() == STUDY_SHA256


def test_committed_trials_reproduce_the_published_table_to_the_cent() -> None:
    want = published_table(EVIDENCE / "appendix-a.md")
    got = table(_committed())
    assert len(want) == 98
    assert got == want


def test_every_arm_and_both_baselines_are_ledger_rows_bound_to_their_inputs() -> None:
    rows = _committed()
    assert [r["kind"] for r in rows].count("variant") == 96
    assert {r["arm"] for r in rows if r["kind"] == "baseline"} == {"hold_flat", "actual_fifo"}
    assert {r["tier"] for r in rows} == {"MODELED"}
    assert all(r["inputs"] == INPUTS and STUDY_SHA256 in r["study"] for r in rows)
    assert [r["arm"] for r in rows if r["selected"]] == ["C5-n22-k3-R-OFF"]


def test_hold_to_1555_beat_every_active_variant_in_the_rerun() -> None:
    rows = _committed()
    hold = next(r for r in rows if r["arm"] == "hold_flat")
    for cost in ("mean_bps_3", "mean_bps_6"):
        assert all(Decimal(r[cost]) < Decimal(hold[cost]) for r in rows if r["kind"] == "variant")


@pytest.mark.skipif(
    not all((INPUT_DIR / name).exists() for name in INPUTS),
    reason=f"exact inputs not on this host ({INPUT_DIR}); release exit-study-41-inputs-2026-10-29",
)
def test_rerun_from_the_catalog_regenerates_the_committed_trials(tmp_path: Path) -> None:
    _report, rows = rerun(INPUT_DIR, tmp_path)
    committed = _committed()
    assert [r["arm"] for r in rows] == [r["arm"] for r in committed]
    for fresh, kept in zip(rows, committed, strict=True):
        for key, value in kept.items():
            if key.startswith(("mean", "median", "win", "worst", "pnl", "share")):
                # The catalog's 4-decimal Price can add trailing zeros; values must be equal.
                assert Decimal(fresh[key]) == Decimal(value), (kept["arm"], key)
            else:
                assert fresh[key] == value, (kept["arm"], key)
    assert table(rows) == published_table(EVIDENCE / "appendix-a.md")
