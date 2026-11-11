"""Witnesses for paper lane C's 24/5 ranked universe (ADR-0024 K2).

All clients are fakes: no broker call, no credential and no network.
"""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from alpaca.common.enums import Sort
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.models import Bar
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrameUnit
from alpaca.trading.enums import AssetClass, AssetStatus
from alpaca.trading.requests import GetAssetsRequest

from sextant.paper.c_universe import (
    canonical_rows,
    parse_args,
    rank_universe,
    scan,
    select_universe,
)

ET_PARTS = (2026, 11, 9, 14, 47)
NOW = datetime(*ET_PARTS, tzinfo=ZoneInfo("America/New_York"))
GENERATED_NS = 1_763_000_000_000_000_000
D = Decimal


class FakeTrading:
    def __init__(self, assets: list[dict[str, Any]]) -> None:
        self.assets = assets
        self.request: GetAssetsRequest | None = None

    def get_all_assets(self, filter: GetAssetsRequest | None = None) -> list[dict[str, Any]]:
        self.request = filter
        return self.assets


class FakeData:
    def __init__(self, bars: dict[str, list[Any]]) -> None:
        self.bars = bars
        self.requests: list[StockBarsRequest] = []

    def get_stock_bars(self, request_params: StockBarsRequest) -> Any:
        self.requests.append(request_params)
        symbols = request_params.symbol_or_symbols
        if isinstance(symbols, str):
            symbols = [symbols]
        return SimpleNamespace(data={symbol: list(self.bars.get(symbol, [])) for symbol in symbols})


def asset(
    symbol: str,
    *,
    tradable: bool = True,
    overnight_tradable: bool = True,
    overnight_halted: bool = False,
    status: str = "active",
    asset_class: str = "us_equity",
) -> dict[str, Any]:
    return {
        "id": f"instrument-{symbol}",
        "exchange": "NASDAQ",
        "symbol": symbol,
        "status": status,
        "class": asset_class,
        "tradable": tradable,
        "overnight_tradable": overnight_tradable,
        "overnight_halted": overnight_halted,
    }


def bar(symbol: str, when: datetime, close: str, volume: str) -> Bar:
    return Bar(
        symbol,
        {
            "t": when.isoformat(),
            "o": close,
            "h": close,
            "l": close,
            "c": close,
            "v": volume,
            "n": 1,
            "vw": close,
        },
    )


def at(day: int, hour: int = 10, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=NOW.tzinfo)


def two_session_bars(
    symbol: str, prior_close: str, close: str, prior_volume: str, volume: str
) -> list[Bar]:
    return [
        bar(symbol, at(6), prior_close, prior_volume),
        bar(symbol, at(9), close, volume),
    ]


def scan_fixture(
    assets: list[dict[str, Any]], bars: dict[str, list[Any]], *, limit: int | None = None
) -> dict[str, Any]:
    return scan(
        FakeTrading(assets),
        FakeData(bars),
        "rth",
        limit=limit,
        now=NOW,
        generated_ns=GENERATED_NS,
    )


def test_universe_keeps_only_active_tradable_us_equity() -> None:
    assets = [
        asset("KEEP"),
        asset("INACTIVE", status="inactive"),
        asset("NOTRADE", tradable=False),
        asset("OPTION", asset_class="us_option"),
    ]
    assert [row.symbol for row in select_universe(assets, "rth")] == ["KEEP"]


def test_overnight_requires_overnight_tradable_and_not_halted() -> None:
    assets = [
        asset("BOTH"),
        asset("FALSE", overnight_tradable=False),
        asset("HALTED", overnight_halted=True),
    ]
    no_attribute = asset("MISSING")
    del no_attribute["overnight_tradable"]
    assets.append(no_attribute)

    assert [row.symbol for row in select_universe(assets, "overnight")] == ["BOTH"]
    assert [row.symbol for row in select_universe(assets, "rth")] == [
        "BOTH",
        "FALSE",
        "HALTED",
        "MISSING",
    ]


def test_score_is_move_times_dvol_ratio() -> None:
    rows = rank_universe(
        FakeTrading([asset("AAA")]),
        FakeData({"AAA": two_session_bars("AAA", "10", "11", "1000", "1500")}),
        "rth",
        now=NOW,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.move == D("0.1")
    assert row.dvol_ratio == D("1.5")
    assert row.score == D("0.15")
    payload = scan(
        FakeTrading([asset("AAA")]),
        FakeData({"AAA": two_session_bars("AAA", "10", "11", "1000", "1500")}),
        "rth",
        now=NOW,
        generated_ns=GENERATED_NS,
    )
    assert payload["rows"][0]["move"] == "0.1"
    assert payload["rows"][0]["dvol_ratio"] == "1.5"
    assert payload["rows"][0]["score"] == "0.15"


def test_rows_sort_by_score_then_symbol() -> None:
    bars = {
        "AAA": two_session_bars("AAA", "10", "11", "1000", "1500"),
        "BBB": two_session_bars("BBB", "10", "11", "1000", "2000"),
        "CCC": two_session_bars("CCC", "10", "11", "1000", "2000"),
    }
    payload = scan_fixture([asset("CCC"), asset("AAA"), asset("BBB")], bars)
    assert [row["symbol"] for row in payload["rows"]] == ["BBB", "CCC", "AAA"]
    assert payload["rows"][0]["score"] == "0.2"
    assert payload["rows"][1]["score"] == "0.2"

    limited = scan_fixture([asset("CCC"), asset("AAA"), asset("BBB")], bars, limit=2)
    assert [row["symbol"] for row in limited["rows"]] == ["BBB", "CCC"]


def test_symbols_without_two_sessions_or_missing_bars_are_skipped() -> None:
    assets = [
        asset("EMPTY"),
        asset("ONE"),
        asset("NULLCLOSE"),
        asset("MISSINGATTR"),
        asset("ZEROVOL"),
        asset("OK"),
    ]
    bars: dict[str, list[Any]] = {
        "EMPTY": [],
        "ONE": [bar("ONE", at(6), "10", "1000")],
        "NULLCLOSE": [SimpleNamespace(timestamp=at(6), close=None, volume=1)],
        "MISSINGATTR": [SimpleNamespace(close="10", volume="1000")],
        "ZEROVOL": two_session_bars("ZEROVOL", "10", "11", "0", "1000"),
        "OK": two_session_bars("OK", "10", "11", "1000", "1500"),
    }
    payload = scan_fixture(assets, bars)
    assert [row["symbol"] for row in payload["rows"]] == ["OK"]


def test_bars_and_assets_requests_use_the_pinned_shape() -> None:
    trading = FakeTrading([asset("AAA")])
    data = FakeData({"AAA": two_session_bars("AAA", "10", "11", "1000", "1500")})
    rank_universe(trading, data, "rth", now=NOW)

    assert trading.request is not None
    assert trading.request.status == AssetStatus.ACTIVE
    assert trading.request.asset_class == AssetClass.US_EQUITY

    assert len(data.requests) == 1
    request = data.requests[0]
    assert request.feed == DataFeed.SIP
    assert (request.timeframe.amount, request.timeframe.unit) == (1, TimeFrameUnit("Min"))
    assert request.adjustment == Adjustment.SPLIT
    assert request.sort == Sort.ASC
    # alpaca-py normalizes aware inputs to naive UTC in the request model.
    assert request.start is not None and request.start.tzinfo is None
    assert request.end is not None and request.end.tzinfo is None


def test_json_and_sha_are_deterministic_and_key_free() -> None:
    assets = [asset("AAA"), asset("BBB")]
    bars = {
        "AAA": two_session_bars("AAA", "10", "11", "1000", "1500"),
        "BBB": two_session_bars("BBB", "20", "19", "2000", "1000"),
    }
    first = scan_fixture(assets, bars)
    reversed_bars = {symbol: list(reversed(rows)) for symbol, rows in reversed(list(bars.items()))}
    second = scan_fixture(list(reversed(assets)), reversed_bars)

    assert first == second
    digest = hashlib.sha256(canonical_rows(first["rows"])).hexdigest()
    assert first["sha256"] == digest
    text = json.dumps(first)
    assert "APCA" not in text
    assert "secret" not in text.lower()


def test_unknown_session_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported session"):
        select_universe([], "closed")
    with pytest.raises(SystemExit):
        parse_args(["--out", "rows.json", "--session", "closed"])


def test_session_defaults_and_limit_validation() -> None:
    assert parse_args(["--out", "rows.json"]).session == "rth"
    with pytest.raises(SystemExit):
        parse_args(["--out", "rows.json", "--limit", "0"])
    with pytest.raises(ValueError, match="limit must be positive"):
        scan_fixture([asset("AAA")], {}, limit=0)


def test_overnight_eligibility_reads_the_assets_api_attributes() -> None:
    # alpaca-py v0.44.0 has no top-level overnight_tradable on Asset; the live
    # GET /v2/assets response carries it in attributes. This is the real shape.
    asset = SimpleNamespace(
        exchange="NASDAQ",
        symbol="AAPL",
        status=AssetStatus.ACTIVE,
        asset_class=AssetClass.US_EQUITY,
        tradable=True,
        id="b0b6dd9d-8b9b-48a9-ba46-3ee76b1a03cc",
        attributes=["fractional_eh_enabled", "has_options", "overnight_tradable"],
    )
    chosen = select_universe([asset], "overnight")
    assert [row.symbol for row in chosen] == ["AAPL"]
    assert chosen[0].overnight_tradable is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("exchange", "TXSE"),
        ("status", "future-status"),
        ("class", "future-class"),
        ("tradable", "true"),
        ("symbol", ""),
        ("id", None),
        ("id", 123),
        ("attributes", 1),
        ("attributes", [1]),
        ("overnight_tradable", "true"),
        ("overnight_halted", "true"),
    ],
)
def test_unknown_asset_rows_are_skipped_counted_and_logged(field, value, caplog) -> None:
    unknown = {**asset("UNKNOWN"), field: value}
    payload = scan_fixture(
        [unknown, unknown, asset("KEEP")],
        {"KEEP": two_session_bars("KEEP", "10", "11", "1000", "1500")},
    )
    assert [row["symbol"] for row in payload["rows"]] == ["KEEP"]
    assert payload["asset_rows_skipped"] == 2
    messages = [r for r in caplog.records if "asset rows" in r.message]
    assert len(messages) == 1
    assert "UNKNOWN" not in messages[0].message
