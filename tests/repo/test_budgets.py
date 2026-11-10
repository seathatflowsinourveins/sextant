"""Size budgets, from the first ask: never bloat. Raising one takes a PR with a reason."""

from pathlib import Path

ROOT = Path(__file__).parents[2]


def _lines(path: Path) -> int:
    return len(path.read_text().splitlines())


def test_agent_files_stay_short() -> None:
    assert _lines(ROOT / "AGENTS.md") + _lines(ROOT / "CLAUDE.md") < 120


def test_justfile_stays_short() -> None:
    assert _lines(ROOT / "justfile") < 105


def test_at_most_thirty_one_page_adrs() -> None:
    adrs = list((ROOT / "docs" / "adr").glob("*.md"))
    assert len(adrs) <= 30
    assert all(_lines(adr) <= 80 for adr in adrs)


def test_at_most_thirty_research_notes() -> None:
    assert len(list((ROOT / "docs" / "research").glob("*.md"))) <= 30


def test_src_stays_under_budget() -> None:
    # Raised by the owner from 15,000 to 17,500 on 2026-11-06 (#58, 6701393837), to 17,650 and
    # 17,720 on 2026-11-07 (#58, 6709238862, 6709939678), then to 20,800 the same day (#58,
    # 6711818587): B's path to ready, live ranking (#66's fix, the registry loader, #133, #137,
    # #134) and the TradingView watchlist (#64). Then to 21,550 on 2026-11-09 (owner, in the
    # sextant-next lead's tab: "raise and resolute them at full speed now, it is long overdue"),
    # for rank-live (+589) and Owner Desk Phase 1 (+151), paired with X3's consolidation PRs and
    # the weekly consolidation report. Then to 24,000 on 2026-11-09 after #69's TradingView
    # host and #83's B replay merged back to back: each CI passed against a base without the
    # other, so the combined tree reached 23,020 against 21,550. The weekly report (#90,
    # 6750396545) shows only three safe dead lines and four duplicate blocks, so the raise
    # leaves 980 lines of headroom and the safe deletions stay a follow-up. Then to 26,500 the
    # same day under the owner's ruling ("those limit exit not for throtting but sota self
    # maintanced consolidation, please don't ask again but consolidate and raise if truly
    # needed"): the open PRs that fit alone plus the TradingView diagnostics fix need 26,059.
    # After each consolidation merge the cap ratchets back to the measured size plus a stated
    # headroom. Then to 28,000 the same day for the owner's 24/5 end to end ("we are using the
    # 24/5 so please e2e it now"): 26,498 measured, less the retirement in flight, plus the
    # 24/5 items is about 27,650 to 27,950. Growth is paired with consolidation: each PR
    # shows its native replacements, a weekly report from maintained tools proposes deletions,
    # and a later raise must cite that report. One-off study code stays on tagged research
    # branches. The owner: "it can be grow but with sota sustainable consolidation".
    # Then down to 27,000 on 2026-11-10 for ADR-0003's entry-ranking consumer: 25,825 measured
    # before it plus the consumer and its hosts stays under 26,000, so the cap ratchets down
    # from 28,000 while the consolidation follow-up keeps its headroom.
    assert sum(_lines(path) for path in (ROOT / "src").rglob("*.py")) < 27000


def test_design_stays_short() -> None:
    assert _lines(ROOT / "docs" / "design.md") <= 220


def test_lane_readmes_stay_short() -> None:
    assert all(_lines(path) <= 60 for path in (ROOT / "lanes").glob("*/README.md"))


def test_practices_stay_short() -> None:
    assert _lines(ROOT / "docs" / "handbook" / "practices.md") <= 80
