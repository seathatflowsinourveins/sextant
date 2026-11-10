"""The finished B replay study lives on its tagged research branch; main keeps the record.

PR-3's historical replay (``b_e2e.py`` and ``b_e2e_cohort.py``) and PR-4's tuning adapter
(``b_tuning.py``) are one-off study code, so the budget rule (tests/repo/test_budgets.py)
keeps them on ``research/b-replay-5830f0e`` at ``b-replay-2026-11-10``, cut from main
5830f0e. Main keeps the reusable validation mechanism, the cumulative trial ledger and this
proof that the two evidence notes name the ref, name the branch paths, and that no runtime
module imports the retired runners.
"""

from __future__ import annotations

import importlib
from pathlib import Path

ROOT = Path(__file__).parents[2]
BRANCH = "research/b-replay-5830f0e"
TAG = "b-replay-2026-11-10"
RETIRED = (
    ROOT / "src" / "sextant" / "backtest" / "b_e2e.py",
    ROOT / "src" / "sextant" / "backtest" / "b_e2e_cohort.py",
    ROOT / "src" / "sextant" / "research" / "b_tuning.py",
)
NOTES = (
    ROOT / "docs" / "research" / "2026-11-06-ranking.md",
    ROOT / "docs" / "research" / "2026-11-06-owner-b-manager.md",
)
# Every tree that can reach a runtime module: the package, the lane configs, the scripts,
# the workflows and the justfile. tests/ and docs/ are excluded by design (they name the ref).
SEARCHED = (
    ROOT / "src",
    ROOT / "lanes",
    ROOT / "scripts",
    ROOT / ".github" / "workflows",
)
JUSTFILE = ROOT / "justfile"
NAMES = ("b_e2e", "b_tuning")


def _files() -> list[Path]:
    files = [JUSTFILE] if JUSTFILE.is_file() else []
    for tree in SEARCHED:
        for path in sorted(tree.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".json", ".yaml", ".yml", ".toml", ".sh"}:
                files.append(path)
    return files


def test_the_b_replay_study_is_not_a_src_module() -> None:
    for path in RETIRED:
        assert not path.exists(), path


def test_no_runtime_module_names_the_retired_runners() -> None:
    for path in _files():
        text = path.read_text(errors="ignore")
        for name in NAMES:
            assert name not in text, (path, name)


def test_the_evidence_notes_name_the_tagged_research_branch() -> None:
    for note in NOTES:
        text = note.read_text()
        assert BRANCH in text, note
        assert TAG in text, note


def test_the_evidence_notes_read_the_branch_paths() -> None:
    ranking = NOTES[0].read_text()
    owner_b = NOTES[1].read_text()
    assert "research/b_e2e.py" in ranking
    assert "research/b_e2e_cohort.py" in ranking
    assert "research/b_e2e.py" in owner_b
    assert "research/b_tuning.py" in owner_b


def test_the_reusable_tuning_mechanism_stays_registered() -> None:
    tuning = importlib.import_module("sextant.validation.tuning")
    assert tuning.SCHEMA == "b-tuning.study/1"
    assert (tuning.MIN_PARAMETERS, tuning.MAX_PARAMETERS) == (5, 8)
    assert (tuning.MIN_TRIALS, tuning.MAX_TRIALS) == (100, 300)
    assert (tuning.MIN_HOLDOUT_DAYS, tuning.MAX_HOLDOUT_DAYS) == (365, 730)
    assert tuning.TRAIL_CAP == "0.025"
