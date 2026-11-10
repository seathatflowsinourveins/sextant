"""Witnesses for baseline coverage: which symbols a table actually holds.

Hand-built samples only: no vendor call, no network, no clock.
"""

from decimal import Decimal

from sextant.ranking.baseline import BaselineSample, BaselineTable
from sextant.ranking.baseline_coverage import (
    bare_symbol,
    coverage_receipt,
    partition_covered,
)

D = Decimal
KNOWN_AT = 1_794_255_177_466_676_010
PROVENANCE = (
    "alpaca-py sip raw 1-minute bars; v*vw, n; explicit complete coverage; "
    "linear within minute; first POST minute omitted"
)


def sample(
    symbol: str,
    segment: str,
    session: str,
    offset_s: int,
    dollar_volume: str,
    trade_count: str,
) -> BaselineSample:
    return BaselineSample(symbol, segment, session, offset_s, D(dollar_volume), D(trade_count))


def table() -> BaselineTable:
    return BaselineTable(
        (
            sample("AAPL", "PRE", "2026-11-05", 0, "10", "1"),
            sample("AAPL", "PRE", "2026-11-05", 60, "25", "3"),
            sample("AAPL", "PRE", "2026-11-06", 0, "12", "2"),
            sample("BRK.B", "PRE", "2026-11-06", 0, "7", "1"),
        ),
        PROVENANCE,
        KNOWN_AT,
        "sip",
    )


def test_a_table_reports_the_slices_it_holds() -> None:
    baseline = table()

    assert baseline.covers("AAPL", "PRE")
    assert baseline.covers("BRK.B", "PRE")
    assert not baseline.covers("MF", "PRE")
    assert not baseline.covers("AAPL", "RTH")
    assert baseline.sessions("AAPL", "PRE") == ("2026-11-05", "2026-11-06")
    assert baseline.sessions("MF", "PRE") == ()


def test_partition_keeps_the_caller_order_and_separates_missing_names() -> None:
    covered, missing = partition_covered(table(), ("MF.ALPACA", "AAPL.ALPACA", "TTD.ALPACA"), "PRE")

    assert covered == ("AAPL.ALPACA",)
    assert missing == ("MF.ALPACA", "TTD.ALPACA")


def test_only_the_alpaca_venue_suffix_is_stripped_from_a_ticker() -> None:
    assert bare_symbol("AAPL.ALPACA") == "AAPL"
    assert bare_symbol("BRK.B.ALPACA") == "BRK.B"
    assert bare_symbol("BRK.B") == "BRK.B"


def test_the_receipt_records_coverage_and_baseline_missing_per_symbol() -> None:
    receipt = coverage_receipt(table(), ("AAPL.ALPACA", "MF.ALPACA"), "PRE")

    assert receipt == {
        "AAPL.ALPACA": {
            "segment": "PRE",
            "state": "covered",
            "sessions": 2,
            "latest_session": "2026-11-06",
        },
        "MF.ALPACA": {
            "segment": "PRE",
            "state": "baseline_missing",
            "sessions": 0,
            "latest_session": None,
        },
    }
