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


def stock(symbol: str, kind: str = "stock") -> dict[str, Any]:
    return {"symbol": symbol, "description": "fixture", "type": kind, "exchange": "x"}


RESULTS = {
    # The fuzzy first hit is a different ticker; the exact stock row is chosen.
    "IBM": [stock("NYSE:IBMX"), stock("NYSE:IBM"), stock("NYSE:IBM", "etf")],
    # Two exact stock listings: ambiguous, never the first.
    "AAPL": [stock("NASDAQ:AAPL"), stock("BMV:AAPL"), stock("SMART:AAPL")],
    # Only a non-stock or a routing venue matches exactly.
    "A": [stock("NYSE:A", "fund"), stock("ALPACA:A")],
}


class Peer:
    def __init__(self, results: dict[str, Any] | None = None, fail: str | None = None):
        self.server = MCPServer("fixture official TradingView", log_level="CRITICAL")
        self.calls: list[dict[str, Any]] = []
        results = RESULTS if results is None else results

        @self.server.tool()
        def search_symbols(query: str, type_filter: str = "all") -> dict[str, Any]:
            self.calls.append({"query": query, "type_filter": type_filter})
            if query == fail:
                raise ValueError("quota exceeded")
            return {"symbols": results.get(query, [])}

        @self.server.tool()
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


def test_the_map_takes_only_one_exact_stock_listing(tmp_path: Path) -> None:
    peer = Peer()
    receipt = run_build(peer, tmp_path / "symbol_map.json")
    assert isinstance(receipt, dict)
    assert [call["query"] for call in peer.calls] == ["A", "AAPL", "IBM"]
    assert all(call["type_filter"] == "stock" for call in peer.calls)
    written = json.loads((tmp_path / "symbol_map.json").read_text())
    assert written == {"A": None, "AAPL": None, "IBM": "NYSE:IBM"}
    assert receipt["mapped"] == 1 and receipt["unresolved"] == ["A", "AAPL"]
    assert receipt["ambiguous_this_run"] == {"AAPL": ["BMV:AAPL", "NASDAQ:AAPL"]}
    saved = json.loads((tmp_path / "symbol_map.receipt.json").read_text())
    assert saved == receipt


def test_the_producer_omits_and_counts_what_the_map_could_not_resolve(tmp_path: Path) -> None:
    path = tmp_path / "symbol_map.json"
    run_build(Peer(), path)
    universe, mapping, provenance = load_maps(NASDAQ, OTHER, path)
    assert universe == ("IBM",) and mapping == {"IBM": "NYSE:IBM"}
    assert "1 of 3 directory symbols mapped, 2 unmapped omitted" in provenance
    assert "File Creation Time 1110202621:31 / 1110202621:31" in provenance


def test_a_rerun_searches_only_new_names_unless_retrying(tmp_path: Path) -> None:
    path = tmp_path / "symbol_map.json"
    run_build(Peer(), path)
    again = Peer()
    run_build(again, path)
    assert again.calls == []
    retry = Peer({**RESULTS, "A": [stock("NYSE:A")]})
    receipt = run_build(retry, path, retry_unresolved=True)
    assert [call["query"] for call in retry.calls] == ["A", "AAPL"]
    assert isinstance(receipt, dict) and receipt["mapped"] == 2


def test_a_failed_search_stops_and_keeps_earlier_progress(tmp_path: Path) -> None:
    path = tmp_path / "symbol_map.json"
    error = run_build(Peer(fail="IBM"), path)
    assert isinstance(error, sync.SyncError) and str(error) == sync.CALL_FAILED
    # A failed lookup is a coverage gap, never a null result.
    assert json.loads(path.read_text()) == {"A": None, "AAPL": None}


def test_an_unknown_envelope_stops_without_a_guess() -> None:
    with pytest.raises(sync.SyncError, match="Unknown MCP result envelope"):
        exact_match("IBM", {"rows": []})


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
