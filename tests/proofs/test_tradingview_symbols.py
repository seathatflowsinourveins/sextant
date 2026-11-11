"""The symbol map from the official read-only search, against the real SDK's in-memory peer.

No account, OAuth, network or TradingView endpoint: the peer advertises the documented
``search_symbols`` beside a watchlist write and a synthetic ``place_order``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.server import MCPServer

from sextant.tradingview import sync
from sextant.tradingview.prestage import load_maps
from sextant.tradingview.symbols import SymbolSearch, build, exact_match

FIXTURES = Path(__file__).resolve().parents[2] / "tests/fixtures/nasdaqtrader"
NASDAQ, OTHER = FIXTURES / "nasdaqlisted.txt", FIXTURES / "otherlisted.txt"


def row(symbol: str, kind: str = "stock", country: str = "US", exchange: str = "") -> dict:
    """One row in the live shape read 2026-11-11: exactly these six keys."""
    return {
        "currency_logoid": f"country/{country}",
        "description": "fixture",
        "exchange": exchange or symbol.split(":", 1)[0],
        "logoid": "fixture",
        "symbol": symbol,
        "type": kind,
    }


RESULTS = {
    # The live AAPL rows (first five): one US listing, the BOATS overnight venue, foreign rows.
    "AAPL": [
        row("NASDAQ:AAPL"),
        row("BOATS:AAPL"),
        row("TSX:AAPL", "dr", "CA"),
        row("BMV:AAPL", country="MX"),
        row("BCBA:AAPL", "dr", "AR", "BYMA"),
    ],
    # The fuzzy first hit is another ticker; two US listings of the exact ticker stay ambiguous.
    "IBM": [row("NYSE:IBMX"), row("NYSE:IBM"), row("CBOE:IBM"), row("NYSE:IBM", "etf")],
    # Only a non-stock, a foreign stock or a routing venue matches exactly.
    "A": [row("NYSE:A", "fund"), row("LSE:A", country="GB"), row("ALPACA:A")],
}


class Peer:
    def __init__(self, results: dict[str, Any] | None = None, fail: str | None = None):
        self.server = MCPServer("fixture official TradingView", log_level="CRITICAL")
        self.calls: list[dict[str, Any]] = []
        results = RESULTS if results is None else results

        @self.server.tool(name="mcp-tv-search-symbols")
        def search_symbols(query: str, type_filter: str = "all") -> dict[str, Any]:
            self.calls.append({"query": query, "type_filter": type_filter})
            if query == fail:
                raise ValueError("quota exceeded")
            rows = results.get(query, [])
            return {"success": True, "data": {"count": len(rows), "symbols": rows}}

        @self.server.tool(name="mcp-watchlist-add-to-watchlist")
        def add_to_watchlist(watchlist_id: str, symbols: list[str]) -> dict[str, Any]:
            raise AssertionError("a search session never writes")

        @self.server.tool()
        def place_order(symbol: str) -> dict[str, Any]:
            raise AssertionError("no order tool")


def run_build(peer: Peer, path: Path, **kwargs: Any) -> dict[str, Any] | sync.SyncError:
    async def run():
        async with Client(peer.server) as client:
            try:
                return await build(NASDAQ, OTHER, path, SymbolSearch(client, interval=0), **kwargs)
            except sync.SyncError as error:
                return error

    return asyncio.run(run())


def test_the_map_takes_the_one_us_listing_after_dropping_boats(tmp_path: Path) -> None:
    peer = Peer()
    receipt = run_build(peer, tmp_path / "symbol_map.json")
    assert isinstance(receipt, dict)
    assert [call["query"] for call in peer.calls] == ["A", "AAPL", "IBM"]
    assert all(call["type_filter"] == "stock" for call in peer.calls)
    written = json.loads((tmp_path / "symbol_map.json").read_text())
    assert written == {"A": None, "AAPL": "NASDAQ:AAPL", "IBM": None}
    assert receipt["mapped"] == 1 and receipt["unresolved"] == ["A", "IBM"]
    assert receipt["ambiguous_this_run"] == {"IBM": ["CBOE:IBM", "NYSE:IBM"]}
    assert receipt["boats_decided_this_run"] == 1
    saved = json.loads((tmp_path / "symbol_map.receipt.json").read_text())
    assert saved == receipt


def test_a_short_page_leaves_the_name_unmapped() -> None:
    rows = [row("NASDAQ:AAPL")]
    assert exact_match("AAPL", {"count": 2, "symbols": rows})[0] is None
    assert exact_match("AAPL", {"count": 1, "symbols": rows})[0] == "NASDAQ:AAPL"


def test_the_producer_omits_and_counts_what_the_map_could_not_resolve(tmp_path: Path) -> None:
    path = tmp_path / "symbol_map.json"
    run_build(Peer(), path)
    universe, mapping, provenance = load_maps(NASDAQ, OTHER, path)
    assert universe == ("AAPL",) and mapping == {"AAPL": "NASDAQ:AAPL"}
    assert "1 of 3 directory symbols mapped, 2 unmapped omitted" in provenance
    assert "File Creation Time 1110202621:31 / 1110202621:31" in provenance


def test_a_rerun_searches_only_new_names_unless_retrying(tmp_path: Path) -> None:
    path = tmp_path / "symbol_map.json"
    run_build(Peer(), path)
    again = Peer()
    run_build(again, path)
    assert again.calls == []
    retry = Peer({**RESULTS, "A": [row("NYSE:A")]})
    receipt = run_build(retry, path, retry_unresolved=True)
    assert [call["query"] for call in retry.calls] == ["A", "IBM"]
    assert isinstance(receipt, dict) and receipt["mapped"] == 2


def test_a_failed_search_stops_and_keeps_earlier_progress(tmp_path: Path) -> None:
    path = tmp_path / "symbol_map.json"
    error = run_build(Peer(fail="IBM"), path)
    assert isinstance(error, sync.SyncError) and str(error) == sync.CALL_FAILED
    # A failed lookup is a coverage gap, never a null result.
    assert json.loads(path.read_text()) == {"A": None, "AAPL": "NASDAQ:AAPL"}


def test_an_unknown_envelope_stops_without_a_guess() -> None:
    with pytest.raises(sync.SyncError, match="Unknown MCP result envelope"):
        exact_match("IBM", {"symbols": []})


def test_the_search_session_admits_one_read_only_tool_and_the_sync_is_unchanged() -> None:
    assert sync.ALLOWED.keys() == {
        "list_watchlists",
        "get_watchlist",
        "create_watchlist",
        "add_to_watchlist",
        "remove_from_watchlist",
    }
    assert SymbolSearch.allowed == {"search_symbols": {"query", "type_filter"}}

    async def run():
        async with Client(Peer().server) as client:
            tools = SymbolSearch(client, interval=0)
            await tools.discover()
            assert set(tools.schemas) == {"search_symbols"}
            for name, arguments in (
                ("add_to_watchlist", {"watchlist_id": "1", "symbols": []}),
                ("place_order", {"symbol": "IBM"}),
                ("search_symbols", {"query": "IBM", "exchange": "NYSE"}),
            ):
                with pytest.raises(sync.SyncError, match="Non-display operation"):
                    await tools.call(name, arguments)
            display = sync.OfficialTools(client, interval=0)
            with pytest.raises(sync.SyncError, match="watchlist tools unavailable"):
                await display.discover()

    asyncio.run(run())


def test_a_missing_search_tool_stops_with_its_own_text() -> None:
    async def run():
        server = MCPServer("fixture official TradingView", log_level="CRITICAL")

        @server.tool(name="mcp-watchlist-list-watchlists")
        def list_watchlists() -> dict[str, Any]:
            return {"watchlists": []}

        async with Client(server) as client:
            with pytest.raises(sync.SyncError) as stop:
                await SymbolSearch(client, interval=0).discover()
            assert str(stop.value) == sync.SEARCH_UNAVAILABLE
            assert stop.value.stop_tail().endswith(
                f"{sync.SEARCH_UNAVAILABLE} (tool list extra mcp-watchlist-list-watchlists; "
                "missing mcp-tv-search-symbols)"
            )

    asyncio.run(run())
