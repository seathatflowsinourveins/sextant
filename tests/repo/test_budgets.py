"""Size budgets, from the first ask: never bloat. Raising one takes a PR with a reason."""

from pathlib import Path

ROOT = Path(__file__).parents[2]


def _lines(path: Path) -> int:
    return len(path.read_text().splitlines())


def test_agent_files_stay_short() -> None:
    assert _lines(ROOT / "AGENTS.md") + _lines(ROOT / "CLAUDE.md") < 120


def test_justfile_stays_short() -> None:
    assert _lines(ROOT / "justfile") < 100


def test_at_most_thirty_one_page_adrs() -> None:
    adrs = list((ROOT / "docs" / "adr").glob("*.md"))
    assert len(adrs) <= 30
    assert all(_lines(adr) <= 80 for adr in adrs)


def test_at_most_thirty_research_notes() -> None:
    assert len(list((ROOT / "docs" / "research").glob("*.md"))) <= 30


def test_src_stays_under_budget() -> None:
    # Raised from 15,000 by the owner on 2026-11-06 (#58, 6701393837), for the focus path to
    # B's ready: #163, #93, #68, the ledger (#96, #110) and B's Alpaca client (#139). Every PR
    # still shows its native replacements; the other queued PRs wait for native trims or a later
    # reasoned raise.
    assert sum(_lines(path) for path in (ROOT / "src").rglob("*.py")) < 17500


def test_design_stays_short() -> None:
    assert _lines(ROOT / "docs" / "design.md") <= 220


def test_lane_readmes_stay_short() -> None:
    assert all(_lines(path) <= 60 for path in (ROOT / "lanes").glob("*/README.md"))


def test_practices_stay_short() -> None:
    assert _lines(ROOT / "docs" / "handbook" / "practices.md") <= 80
