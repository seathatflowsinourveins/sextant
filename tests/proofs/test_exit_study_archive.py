"""Rows 46 and 50: the finished exit studies live on a tagged research ref.

#41's study driver, its output driver and #98's exit-engine study are one-off
study code, so the budget rule (tests/repo/test_budgets.py) keeps them on
``research/exit-study-5fe0977`` at ``exit-study-2026-11-10``, cut from main
5fe09775. Main keeps the reusable pieces: the exit engine, the input pin and
catalog writer (``src/sextant/backtest/exit_inputs.py``) that the recorded-bar
replay needs, the cumulative trial ledger, the committed evidence and this proof
that the evidence notes name the ref and its paths and that no runtime module
names the retired studies.

The rerun proofs stay on the ref and run there. Here the committed evidence is
pinned byte-for-byte, so the published tables stay checkable on main.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from sextant.backtest import exit_inputs

ROOT = Path(__file__).parents[2]
BRANCH = "research/exit-study-5fe0977"
TAG = "exit-study-2026-11-10"
COMMIT = "1dfa15bc9ae5f60d778be827e09bf88dd670bce4"
RETIRED = (
    ROOT / "src" / "sextant" / "research" / "b_exit_replay.py",
    ROOT / "src" / "sextant" / "research" / "exit_study_41.py",
    ROOT / "src" / "sextant" / "research" / "exit_econ_98.py",
)
NOTES = (
    ROOT / "docs" / "research" / "2026-11-06-exit-study-41.md",
    ROOT / "docs" / "research" / "2026-11-06-exit-econ-98.md",
)
# Every tree that can reach a runtime module: the package, the lane configs, the scripts,
# the workflows and the justfile. tests/ and docs/ are excluded by design (they name the
# ref); a display preset's comment cites the upstream file as provenance, not as code.
SEARCHED = (
    ROOT / "src",
    ROOT / "lanes",
    ROOT / "scripts",
    ROOT / ".github" / "workflows",
)
JUSTFILE = ROOT / "justfile"
NAMES = ("b_exit_replay", "exit_study_41", "exit_econ_98")
STUDY = ROOT / "docs" / "research" / "2026-11-06-exit-study-41"
ECON = ROOT / "docs" / "research" / "2026-11-06-exit-econ-98"
UPSTREAM = "northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:scripts/research/"
STUDY_ROW = (
    UPSTREAM
    + "b_exit_replay.py sha256:143ab1dd4356e513c6b69d16928fdf594739f62ba170a87bfd6cd384eb99725a"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _runtime_files() -> list[Path]:
    files = [JUSTFILE] if JUSTFILE.is_file() else []
    for tree in SEARCHED:
        for path in sorted(tree.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".json", ".yaml", ".yml", ".toml", ".sh"}:
                files.append(path)
    return files


def _table(rows: list[dict]) -> dict[str, list[str]]:
    """The write-up's Appendix A cells, at its printed precision."""

    def q(value: str, places: str = "0.01") -> str:
        return f"{Decimal(value).quantize(Decimal(places)):f}"

    def pct(value: str) -> str:
        return q(str(Decimal(value) * 100))

    return {
        row["arm"]: [
            str(row["n"]),
            q(row["mean_bps_3"]),
            q(row["mean_bps_6"]),
            q(row["median_bps_3"]),
            q(row["median_bps_6"]),
            pct(row["win_rate_3"]),
            pct(row["win_rate_6"]),
            q(row["worst_mae_bps"]),
            q(row["mean_mae_bps"]),
            q(row["pnl_units_3"], "0.0001"),
            q(row["pnl_units_6"], "0.0001"),
            pct(row["share_before_flat"]),
        ]
        for row in rows
    }


def _published_table(path: Path) -> dict[str, list[str]]:
    lines = path.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("| Variant | n | Mean 3"))
    rows = {}
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        rows[cells[0]] = cells[1:]
    return rows


def test_the_finished_exit_studies_are_not_src_modules() -> None:
    for path in RETIRED:
        assert not path.exists(), path


def test_no_runtime_module_names_a_retired_study() -> None:
    for path in _runtime_files():
        text = path.read_text(errors="ignore")
        for name in NAMES:
            assert name not in text, (path, name)


def test_the_evidence_notes_name_the_tagged_research_branch() -> None:
    for note in NOTES:
        text = note.read_text()
        assert BRANCH in text, note
        assert TAG in text, note
        assert COMMIT in text, note


def test_the_evidence_notes_read_the_branch_paths() -> None:
    for note in NOTES:
        text = note.read_text()
        assert "research/b_exit_replay.py" in text, note
        assert "research/exit_study_41.py" in text, note
        assert "research/exit_econ_98.py" in text, note


def test_the_committed_exit_study_rows_stay_the_published_table() -> None:
    assert _sha256(STUDY / "trials.jsonl") == (
        "a059ffd331e7be07ef451f7dfc6bf265dc2c8158037c284b7cd8cfecb44018ac"
    )
    assert _sha256(STUDY / "appendix-a.md") == (
        "e0049922637d38e4018c2bbb3548075ed4e4903a1ed393aa142bf30683f71a82"
    )
    rows = _jsonl(STUDY / "trials.jsonl")
    assert len(rows) == 98
    assert sum(row["kind"] == "variant" for row in rows) == 96
    assert sorted(row["arm"] for row in rows if row["kind"] == "baseline") == [
        "actual_fifo",
        "hold_flat",
    ]
    assert [row["arm"] for row in rows if row["selected"]] == ["C5-n22-k3-R-OFF"]
    for row in rows:
        assert row["tier"] == "MODELED"
        assert row["n"] == 1025
        assert row["version"] == "b-exit-replay/3"
        assert row["study"] == STUDY_ROW
        assert row["inputs"] == exit_inputs.INPUTS
    hold = next(row for row in rows if row["arm"] == "hold_flat")
    for row in rows:
        if row["kind"] == "variant":
            assert Decimal(row["mean_bps_3"]) < Decimal(hold["mean_bps_3"])
            assert Decimal(row["mean_bps_6"]) < Decimal(hold["mean_bps_6"])
    assert _table(rows) == _published_table(STUDY / "appendix-a.md")


def test_the_committed_exit_econ_evidence_stays_bound_to_its_inputs() -> None:
    assert _sha256(ECON / "trials.jsonl") == (
        "019e162c9433a27064a4eebe79e0bd6354c5ae6b22bdb37ebbbf21c468753cfd"
    )
    assert _sha256(ECON / "report.json") == (
        "8fec944f59047b924f73fe5e26597e46804fe73b1471bc59f2d08f72c92c477f"
    )
    rows = _jsonl(ECON / "trials.jsonl")
    assert sorted(row["arm"] for row in rows) == [
        "C5-n22-k3-R-OFF-study",
        "C5-n22-k3-R-OFF-tape",
        "exit-engine-starts-rw-dropped",
        "exit-engine-starts-rw-strict",
        "hold_flat",
    ]
    for row in rows:
        assert row["tier"] == "MODELED"
        assert row["n"] == 1025
        assert row["inputs"] == exit_inputs.INPUTS
        assert row["study"] == STUDY_ROW
    report = json.loads((ECON / "report.json").read_text())
    assert (report["issue"], report["tier"]) == (98, "MODELED")
    assert report["implementation"] == "92008be903825e7f6bf3ecf75be3d3235de65b29"
    for arm in report["arms"].values():
        assert arm["n"] == 1025
    hold_3 = Decimal(report["arms"]["hold_flat/3"]["mean_bps"])
    hold_6 = Decimal(report["arms"]["hold_flat/6"]["mean_bps"])
    assert hold_3 == Decimal("76.44154155886256837408115509")
    assert hold_6 == Decimal("70.41680167442957970696879719")
    for key, labels in report["attribution"].items():
        gap = sum(Decimal(part["gap_contribution_bps"]) for part in labels.values())
        hold = report["arms"]["hold_flat/" + key.rsplit("/", 1)[1]]
        arm = Decimal(report["arms"][key]["mean_bps"])
        assert abs(gap - (arm - Decimal(hold["mean_bps"]))) < Decimal("1e-6")
    later = json.loads((ECON / "run-a8282a4" / "report.json").read_text())
    assert later["implementation"] == "a8282a4f11d69b2bd595d3035439f5edd64276be"
    assert Decimal(later["arms"]["exit-engine-starts-rw-dropped/3"]["mean_bps"]) == Decimal(
        "-46.24690588211056476522507862"
    )
    assert Decimal(later["arms"]["hold_flat/3"]["mean_bps"]) == hold_3


def test_the_later_run_keeps_its_own_trials_on_committed_record() -> None:
    """Lead ruling (a), 2026-11-07: PR 2's run sits beside the history with its own trial rows."""
    run = ECON / "run-a8282a4"
    assert _sha256(run / "report.json") == (
        "aaba28d2a5d6ea7baa54255aabd5f613108033bd224572efc34345088b19ee71"
    )
    assert _sha256(run / "trials.jsonl") == (
        "5abfba46363c74c57c5af47e73108b614efdae82f8fbc32c195d721aca6559de"
    )
    history = json.loads((ECON / "report.json").read_text())
    later = json.loads((run / "report.json").read_text())
    assert later["implementation"] == "a8282a4f11d69b2bd595d3035439f5edd64276be"
    assert later["inputs"] == history["inputs"]
    assert set(later["arms"]) == set(history["arms"])
    rows = _jsonl(run / "trials.jsonl")
    assert sorted(row["arm"] for row in rows) == sorted(
        {key.rsplit("/", 1)[0] for key in later["arms"]}
    )
    for row in rows:
        assert row["implementation"] == later["implementation"]
        assert row["tier"] == "MODELED"
        assert row["n"] == 1025
        assert row["inputs"] == later["inputs"]
        for cost in ("3", "6"):
            assert Decimal(row[f"mean_bps_{cost}"]) == Decimal(
                later["arms"][f"{row['arm']}/{cost}"]["mean_bps"]
            )
