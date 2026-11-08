"""Fixture-only acceptance for the display contract at lane/research@d957d8e9."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from sextant.tradingview.display_lists import ArmedSet, build_display_lists
from sextant.tradingview.display_support import timestamp_ns

NOW = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
AS_OF = (NOW - timedelta(seconds=30)).isoformat()
DIGEST = "a" * 64


def row(symbol: str, rank: int, kind: Any = None, **inputs: Any) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "rank": rank,
        "exchange": "NASDAQ",
        "weights_version": "potential/2",
        "coverage": {"security_type": kind or {"type": "common_stock"}},
        "inputs": {"price": "10", "previous_close": "10", "rvol": "2", **inputs},
    }


def snapshot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "potential-snapshot/1",
        "weights_version": "potential/2",
        "as_of": AS_OF,
        "generated_at": AS_OF,
        "session_date": "2026-10-29",
        "session": "rth",
        "symbols": rows,
    }


def focus(*symbols: str) -> dict[str, Any]:
    return {
        "schema": "top100.focus/1",
        "as_of": NOW.isoformat(),
        "generated_at": NOW.isoformat(),
        "as_of_snapshot": AS_OF,
        "session_date": "2026-10-29",
        "snapshot_status": "observed",
        "status": "fresh",
        "candidates": [{"symbol": symbol, "tradingview_symbol": f"NASDAQ:{symbol}"} for symbol in symbols],
    }


def journal(armed: list[str], *, at: datetime = NOW, source: str = AS_OF) -> str:
    # Exact _record_refresh shape, scanner.py:470-483 at paper@d94292fb.
    return (
        json.dumps(
            {
                "version": 1,
                "kind": "premarket_gap_scanner_refresh",
                "ts_event": timestamp_ns(at),
                "strategy_id": "premarket_gap-001",
                "account_id": "ALPACA-001",
                "snapshot_reason": "fresh",
                "snapshot_as_of": source,
                "decisions": {},
                "armed": armed,
                "max_armed_symbols": 30,
                "scanner_premarket_entries": True,
            }
        )
        + "\n"
    )


def build(rows: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    return build_display_lists(
        snapshot(rows),
        kwargs.pop("focus_doc", focus("FOCUS")),
        snapshot_path="inputs/snapshot.json",
        snapshot_sha256=DIGEST,
        generated_at=NOW.isoformat(),
        **kwargs,
    )


def names(doc: dict[str, Any], key: str) -> list[str]:
    return [item["symbol"] for item in doc[key]]


@pytest.mark.parametrize("nested", [False, True], ids=["pinned-producer", "contract"])
def test_early_security_types_rank_order_and_labels(nested: bool) -> None:
    kinds = ["etf", "preferred", "warrant", "unit", "common_stock", "adr", "unknown"]
    rows = [row(f"SYM{i}", i, {"type": kind} if nested else kind) for i, kind in enumerate(kinds, 1)]
    doc = build(list(reversed(rows)))
    assert names(doc, "ns_movers") == ["SYM5", "SYM6"]
    assert doc["ns_movers"][0]["labels"] == ["early:5"]
    assert doc["ns_movers"][1]["labels"] == ["early:6"]
    assert doc["generation"] == {"as_of": AS_OF, "sha256": DIGEST}
    assert doc["schema"] == "ns-display-lists/1"
    assert doc["bounds"] == {"gap_bound": "0.05", "rvol_bound": "2", "max_age_s": 600}
    assert doc["sources"]["snapshot"] == {"path": "inputs/snapshot.json", "as_of": AS_OF, "sha256": DIGEST}


def test_extreme_190_percent_rank_below_2000_and_low_or_null_rvol() -> None:
    rows = [row(f"SYM{i:04}", i, rvol="1") for i in range(1, 2306)]
    rows.extend(
        [
            row("INO", 2306, price="29", rvol="2"),
            row("LOW", 2307, price="30", rvol="1.99"),
            row("NULL", 2308, price="30", rvol=None),
            row("ETF", 2309, "etf", price="99", rvol="20"),
        ]
    )
    doc = build(rows)
    assert names(doc, "ns_movers") == [*(f"SYM{i:04}" for i in range(1, 51)), "INO"]
    assert doc["ns_movers"][-1]["labels"] == ["extreme:≥20%"]
    assert doc["excluded_unknown"] == 1


@pytest.mark.parametrize("field", ["price", "previous_close", "rvol"])
def test_unknown_is_not_zero_even_with_large_session_return(field: str) -> None:
    rows = [row(f"EARLY{i}", i) for i in range(1, 51)]
    missing = row("UNKNOWN", 2001, **{"price": "30", field: None})
    missing["coverage"]["session_relative"] = {"session_return": "2"}
    doc = build([*rows, missing])
    assert "UNKNOWN" not in names(doc, "ns_movers")
    assert doc["excluded_unknown"] == 1


def test_move_max_sort_tie_break_and_registered_bounds_override() -> None:
    early = [row(f"EARLY{i}", i) for i in range(1, 51)]
    gap, session, tied, below = (
        row("GAP", 1001, price="11", rvol="3"),
        row("SESSION", 1002, price="10.01", rvol="3"),
        row("TIED", 1003, price="11", rvol="3"),
        row("BELOW", 1004, price="10.9", rvol="3"),
    )
    session["coverage"]["session_relative"] = {"session_return": "0.21"}
    doc = build([*early, tied, below, gap, session], gap_bound=Decimal(".1"), rvol_bound=Decimal(3))
    assert names(doc, "ns_movers")[-3:] == ["SESSION", "GAP", "TIED"]
    assert [r["labels"] for r in doc["ns_movers"][-3:]] == [
        ["extreme:≥20%"],
        ["extreme:≥10%"],
        ["extreme:≥10%"],
    ]
    assert doc["bounds"]["gap_bound"] == "0.1"


def test_deduplication_early_first_extreme_top50_and_total_cap() -> None:
    rows = [row(f"SYM{i:03}", i, price=str(Decimal(10) + Decimal(i))) for i in range(1, 151)]
    doc = build(rows)
    symbols = names(doc, "ns_movers")
    assert symbols == [*(f"SYM{i:03}" for i in range(1, 51)), *(f"SYM{i:03}" for i in range(150, 100, -1))]
    assert len(symbols) == len(set(symbols)) == 100
    overlap = build([row("BOTH", 1, price="10.5")])
    assert names(overlap, "ns_movers") == ["BOTH"]
    assert overlap["ns_movers"][0]["labels"] == ["early:1", "extreme:≥5%"]


def test_latest_refresh_not_historical_arms_or_other_evidence_and_all_arm_labels() -> None:
    first = ArmedSet(
        "lane-a",
        "a.jsonl",
        journal(["OLD.ALPACA"], at=NOW - timedelta(seconds=2))
        + journal(["AAA.ALPACA", "BRK.B.ALPACA"])
        + json.dumps({"kind": "premarket_gap_fill", "ts_event": timestamp_ns(NOW), "armed": ["NO.ALPACA"]})
        + "\n",
    )
    second = ArmedSet("trial-bcd", "trial.jsonl", journal(["AAA.ALPACA", "TRIAL.ALPACA"]))
    doc = build(
        [row("AAA", 1), row("BRK.B", 2), row("TRIAL", 3), row("FOCUS", 4)],
        focus_doc=focus("AAA", "FOCUS"),
        armed_sets=(first, second),
    )
    assert names(doc, "ns_focus") == ["AAA", "BRK.B", "TRIAL", "FOCUS"]
    assert doc["armed"] == "observed"
    assert doc["ns_focus"][0]["labels"] == [
        "arm:lane-a",
        "phase:rth",
        "sell_pressure:UNVERIFIED",
        "arm:trial-bcd",
    ]
    assert doc["sources"]["armed_sets"][1]["as_of"] == NOW.isoformat()


@pytest.mark.parametrize(
    "fault", ["missing", "stale", "future", "mixed", "malformed", "partial", "wrong-kind"]
)
def test_missing_or_stale_armed_set_is_explicit_unverified_and_focus_only(fault: str) -> None:
    text: str | None = journal(["OLD.ALPACA"])
    if fault == "missing":
        text = None
    elif fault == "stale":
        text = journal(["OLD.ALPACA"], at=NOW - timedelta(seconds=601))
    elif fault == "future":
        text = journal(["OLD.ALPACA"], at=NOW + timedelta(seconds=1))
    elif fault == "mixed":
        text = journal(["OLD.ALPACA"], source=(NOW - timedelta(seconds=31)).isoformat())
    elif fault == "malformed":
        text = "{\n"
    elif fault == "partial":
        text += "{"
    elif fault == "wrong-kind":
        text = '{"kind":"premarket_gap_fill"}\n'
    doc = build(
        [row("ARMED", 1), row("FOCUS", 2)],
        armed_sets=(
            ArmedSet("a", "a.jsonl", journal(["ARMED.ALPACA"])),
            ArmedSet("trial", "trial.jsonl", text),
        ),
    )
    assert doc["armed"] == "UNVERIFIED"
    assert names(doc, "ns_focus") == ["FOCUS"]
    assert doc["sources"]["armed_sets"][1]["status"] == "UNVERIFIED"


def test_no_arm_paths_is_not_silently_empty_and_pressure_unknown_is_labelled() -> None:
    doc = build([row("FOCUS", 1)])
    assert doc["armed"] == "UNVERIFIED"
    assert names(doc, "ns_focus") == ["FOCUS"]
    assert "sell_pressure:UNVERIFIED" in doc["ns_focus"][0]["labels"]
    empty = build([row("OTHER", 1)], focus_doc=focus())
    assert empty["ns_focus"] == []
    assert empty["armed"] == "UNVERIFIED"


def test_same_generation_and_pure_no_input_mutation() -> None:
    source, selected = snapshot([row("AAA", 1)]), focus("AAA")
    before = copy.deepcopy((source, selected))
    build_display_lists(
        source, selected, snapshot_path="s.json", snapshot_sha256=DIGEST, generated_at=NOW.isoformat()
    )
    assert (source, selected) == before
    selected["as_of_snapshot"] = NOW.isoformat()
    with pytest.raises(ValueError, match="generation"):
        build_display_lists(
            source, selected, snapshot_path="s.json", snapshot_sha256=DIGEST, generated_at=NOW.isoformat()
        )


@pytest.mark.parametrize("field", ["gap_bound", "rvol_bound", "max_age_s"])
def test_invalid_bounds_refused(field: str) -> None:
    with pytest.raises(ValueError, match=r"bound|age"):
        build([row("AAA", 1)], **{field: 0})


@pytest.mark.parametrize("at", [NOW - timedelta(seconds=600), NOW])
def test_journal_age_inclusive_boundary_and_empty_current_set_are_authoritative(at: datetime) -> None:
    doc = build([row("FOCUS", 1)], armed_sets=(ArmedSet("a", "a.jsonl", journal([], at=at)),))
    assert doc["armed"] == "observed"
    assert names(doc, "ns_focus") == ["FOCUS"]


def test_armed_current_refresh_can_remove_a_previous_name() -> None:
    doc = build(
        [row("OLD", 1), row("FOCUS", 2)],
        armed_sets=(ArmedSet("a", "a.jsonl", journal(["OLD.ALPACA"]) + journal([])),),
    )
    assert names(doc, "ns_focus") == ["FOCUS"]
    assert doc["armed"] == "observed"
