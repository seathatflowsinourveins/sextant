"""ADR-0021 J5 policy only; no controller or network connection.

Source: FerroxLabs/tvcontrol@v2.5.3 85200201f92967db9e4b63a9251d51fcdfe1f3a8,
src/tools/watchlist.js:6,11,20,27,48,62 and src/core/watchlist.js:462,504,578,911.
The memory witness models those bulk calls' captured-ID writes, not an installed controller.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
PIN = "85200201f92967db9e4b63a9251d51fcdfe1f3a8"
ROW = "TradingView research membership sync and Pine displays"
LESSON = ROOT / "docs/handbook/tradingview-watchlists.md"


def j5_policy() -> str:
    adr = (ROOT / "docs/adr/0021-tradingview-display.md").read_text()
    return adr.split("### Amendment, 2026-11-08: J5 watchlist display sync\n", 1)[1].split(
        "\n## ", 1
    )[0]


def test_j5_allowlist_matches_the_pinned_watchlist_tools() -> None:
    policy = j5_policy()
    line = next(line for line in policy.splitlines() if line.startswith("- **As-run allowlist:**"))
    assert line.split("`")[1::2] == [
        "watchlist_create",
        "watchlist_add_bulk",
        "watchlist_remove_bulk",
        "watchlist_list",
        "watchlist_get_by_id",
        "watchlist_get",
    ]
    assert f"FerroxLabs/tvcontrol v2.5.3 (`{PIN}`)" in policy
    for source_line in (6, 11, 20, 27, 48, 62):
        assert f"`src/tools/watchlist.js:{source_line}`" in policy
    for source_line in (462, 504, 578, 911):
        assert f"`src/core/watchlist.js:{source_line}`" in policy


def test_j5_keeps_display_only_target_and_readback_bounds() -> None:
    policy = j5_policy()
    for boundary in (
        "`NS Ranked` and `NS B-protected` watchlists from Sextant's lists",
        "Sextant's lists are the only input",
        "missing, stale or invalid input refuses a write",
        "no order, alert, broker or Pine",
        "never a machine signal from TradingView data",
        "Windows-native, one controller at a time on `127.0.0.1:29222`",
        "idempotent membership sync",
        "duplicate-name creation disabled",
        "active list, not an explicit target",
        "stop for reviewed selection outside J5",
        "Every write is read back by numeric ID with `watchlist_get_by_id`",
        "complete membership against Sextant's input",
        "Never write to a non-NS list",
        "J5 is not a required-check job",
        "controller apply after review",
    ):
        assert boundary in policy


def test_j5_manifest_registers_its_source_and_offline_proof() -> None:
    manifest = (ROOT / "docs/manifest.md").read_text()
    row = next(line for line in manifest.splitlines() if line.startswith(f"| {ROW} |"))
    assert f"FerroxLabs/tvcontrol@v2.5.3 `{PIN}`" in row
    assert "src/tools/watchlist.js:6,11,20,27,48,62" in row
    assert (
        "test_tradingview_desktop.py::test_j5_allowlist_matches_the_pinned_watchlist_tools" in row
    )
    assert "not a Desktop execution receipt" in row


def test_j5_pins_non_use_and_before_and_after_checks_in_policy_and_lesson() -> None:
    for text in (j5_policy(), LESSON.read_text()):
        for boundary in (
            '"i am not using it , it is opened for you"',
            "precondition of every J5 run",
            "watchlist_get -> watchlist_add_bulk -> watchlist_get",
            "watchlist_get -> watchlist_remove_bulk -> watchlist_get",
            "at most 100",
            "FIRST active-list ID or name mismatch",
            "report exactly what was written where",
            "Never write to a non-NS list",
        ):
            assert boundary in text
    lesson = LESSON.read_text()
    assert "not an atomic compare-and-write" in lesson
    assert "before the bulk call's own initial snapshot" in lesson
    assert "unknown" in lesson
    assert "4507021307" in lesson


def _replay_bulk_protocol(
    tool: str,
    *,
    before: tuple[int, str] = (17, "NS Ranked"),
    switch_to: tuple[int, str] | None = None,
    non_use: bool = True,
) -> tuple[list[str], list[tuple[int, str, str, tuple[str, ...]]], dict[int, set[str]], str]:
    """Interpret the handbook's triplet over memory, with upstream's captured-ID mutation.

    An ID switch is injected after the bulk call captures its ID, before its write. That
    call writes the captured ID (core :523/:609), never the newly active ID. Name drift is
    injected after the mutation. A second batch is queued to prove the first mismatch
    halts it; by-ID membership alone could pass. No upstream code runs here.
    """
    lesson = LESSON.read_text()
    line = next(line for line in lesson.splitlines() if f"-> {tool} ->" in line)
    steps = re.findall(r"watchlist_[a-z_]+", line) * 2
    target = (17, "NS Ranked")
    active = before
    symbols = ("NASDAQ:AAPL",)
    lists = {17: set() if tool == "watchlist_add_bulk" else set(symbols), 99: {"NYSE:IBM"}}
    calls: list[str] = []
    writes: list[tuple[int, str, str, tuple[str, ...]]] = []
    if not non_use:
        return calls, writes, lists, "non-use precondition"
    for step in steps:
        calls.append(step)
        if step == "watchlist_get":
            if active != target:
                return calls, writes, lists, "active-list ID or name mismatch"
        else:
            captured = active
            if switch_to is not None and switch_to[0] != captured[0]:
                active = switch_to
            writes.append((*captured, step, symbols))
            if step == "watchlist_add_bulk":
                lists[captured[0]].update(symbols)
            elif step == "watchlist_remove_bulk":
                lists[captured[0]].difference_update(symbols)
            else:
                raise AssertionError(f"Unbounded or unsupported write: {step}")
            if switch_to is not None and switch_to[0] == captured[0]:
                active = switch_to
            # Upstream also reports an ID change as an error. The caller must perform
            # its outer ID AND name read even on error, then stop before another batch.
    return calls, writes, lists, "accepted"


@pytest.mark.parametrize("tool", ["watchlist_add_bulk", "watchlist_remove_bulk"])
@pytest.mark.parametrize("observed", [(99, "Owner list"), (99, "NS Ranked"), (17, "Renamed")])
def test_j5_mid_run_switch_halts_with_only_the_captured_ns_list_written(tool, observed) -> None:
    calls, writes, lists, result = _replay_bulk_protocol(tool, switch_to=observed)
    assert calls == ["watchlist_get", tool, "watchlist_get"]
    assert result == "active-list ID or name mismatch"
    assert writes == [(17, "NS Ranked", tool, ("NASDAQ:AAPL",))]
    assert lists[99] == {"NYSE:IBM"}
    # The intended target already has its final membership. By-ID read-back would pass,
    # but the active-list post-check rejects the run and there is no next write/retry.
    assert lists[17] == ({"NASDAQ:AAPL"} if tool == "watchlist_add_bulk" else set())


@pytest.mark.parametrize("before", [(99, "Owner list"), (99, "NS Ranked"), (17, "Renamed")])
def test_j5_precheck_mismatch_writes_nothing(before) -> None:
    calls, writes, _, result = _replay_bulk_protocol("watchlist_add_bulk", before=before)
    assert calls == ["watchlist_get"]
    assert writes == []
    assert result == "active-list ID or name mismatch"


def test_j5_without_non_use_confirmation_never_starts() -> None:
    calls, writes, _, result = _replay_bulk_protocol("watchlist_add_bulk", non_use=False)
    assert calls == writes == []
    assert result == "non-use precondition"
