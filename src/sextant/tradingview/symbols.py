"""Build the display producer's exact TradingView symbol map with the official search.

Source: the earlier campaign took each exact TradingView symbol from the official MCP
``search_symbols`` and never a fuzzy first hit (northstar-trading@8256c16c
``docs/tradingview/README.md:16,24,30``: "Use the returned **exact** ``symbol``, after
checking instrument type and listing exchange"; "The sync never chooses the first fuzzy
hit"). The official MCP documentation (https://www.tradingview.com/mcp/docs, read
2026-11-11) lists ``search_symbols`` as Read-only: it resolves a ticker into "routable
EXCHANGE:TICKER symbols via fuzzy search" and "Returns symbol, description, type,
exchange, logoid"; "Read-only tools never modify the account". No TradingView page read
2026-11-11 states a prefix for each US listing venue, so no prefix is derived from the
directory's exchange code.

This session admits exactly one operation, ``search_symbols``; the display sync's
allowlist (``sync.ALLOWED``) is unchanged. A name is mapped only when exactly one returned
row is a ``stock`` whose qualified symbol's ticker equals the directory ticker. No match,
or more than one, records ``null`` and is counted; a failed or quota-limited call stops the
run and records nothing for that name. Progress is saved as it goes, so a rerun only
searches names that are not yet in the map.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from sextant.execution.state import write_atomic
from sextant.tradingview.auth import official_client
from sextant.tradingview.bars import build_universe
from sextant.tradingview.host import load_symbol_map
from sextant.tradingview.inputs import QUALIFIED
from sextant.tradingview.sync import (
    SEARCH_UNAVAILABLE,
    UNKNOWN_RESULT_ENVELOPE,
    OfficialTools,
    SyncError,
    _shape,
)

# "type_filter ... stock, etf, bond, forex, index, futures, or crypto" (MCP docs, search).
STOCK = "stock"
ROUTING = frozenset({"SMART", "IB", "IBKR", "ALPACA"})
US = "country/US"
# Blue Ocean ATS is an overnight venue, not a listing exchange: the 20:00-04:00 session
# "uses the BOATS feed" (src/sextant/paper/b_feed.py:4-6, Alpaca 24/5 trading page read
# 2026-11-09); docs/research/2026-11-06-legs-convergence.md:35 lists "Blue Ocean ATS" among
# overnight venues.
OVERNIGHT_VENUE = "BOATS"
SAVE_EVERY = 50


class SymbolSearch(OfficialTools):
    """The official tools fence with one read-only operation and no namespaced alias."""

    allowed: ClassVar[dict[str, set[str]]] = {"search_symbols": {"query", "type_filter"}}
    # The live wire name, read from the official tools list 2026-11-11 (lead, LEAD-0201).
    aliases: ClassVar[dict[str, str]] = {"mcp-tv-search-symbols": "search_symbols"}
    unavailable: ClassVar[str] = SEARCH_UNAVAILABLE


def exact_match(ticker: str, page: Any) -> tuple[str | None, list[str], bool]:
    """The one US stock listing of ``ticker`` (lead ruling LEAD-0201, 2026-11-11).

    Rows whose ticker equals ``ticker`` exactly, whose type is ``stock`` and whose
    ``currency_logoid`` is ``country/US`` are kept; the BOATS overnight venue is dropped.
    Exactly one survivor is mapped. Returns the mapping (or None), the survivors, and
    whether dropping BOATS decided the name. A short page leaves the name unmapped.
    """
    if (
        not isinstance(page, dict)
        or set(page) != {"count", "symbols"}
        or type(page["count"]) is not int
        or not isinstance(page["symbols"], list)
    ):
        raise SyncError(UNKNOWN_RESULT_ENVELOPE, stage="tool call", detail=_shape(page))
    rows = page["symbols"]
    us = sorted(
        {
            (row["symbol"], row.get("exchange"))
            for row in rows
            if isinstance(row, dict)
            and row.get("type") == STOCK
            and row.get("currency_logoid") == US
            and isinstance(row.get("symbol"), str)
            and QUALIFIED.fullmatch(row["symbol"])
            and row["symbol"].split(":", 1)[1] == ticker
            and row["symbol"].split(":", 1)[0] not in ROUTING
        }
    )
    listed = sorted(
        {
            symbol
            for symbol, exchange in us
            if OVERNIGHT_VENUE not in (exchange, symbol.split(":")[0])
        }
    )
    if page["count"] != len(rows) or len(listed) != 1:
        return None, listed, False
    return listed[0], listed, len({symbol for symbol, _ in us}) > 1


async def resolve(
    tools: OfficialTools,
    universe: Sequence[str],
    mapping: dict[str, str | None],
    *,
    save: Callable[[dict[str, str | None], dict[str, list[str]], int], None],
    retry_unresolved: bool = False,
) -> dict[str, list[str]]:
    """Search every name not yet mapped; ``mapping`` is updated in place."""
    await tools.discover()
    ambiguous: dict[str, list[str]] = {}
    decided = 0
    pending = [
        name
        for name in universe
        if name not in mapping or (retry_unresolved and mapping[name] is None)
    ]
    try:
        for count, name in enumerate(pending, 1):
            result = await tools.call("search_symbols", {"query": name, "type_filter": STOCK})
            mapping[name], candidates, by_boats = exact_match(name, result)
            decided += by_boats
            if len(candidates) > 1:
                ambiguous[name] = candidates
            if count % SAVE_EVERY == 0:
                save(mapping, ambiguous, decided)
    finally:
        save(mapping, ambiguous, decided)
    return ambiguous


async def build(
    nasdaq_listed: Path,
    other_listed: Path,
    symbol_map: Path,
    tools: OfficialTools,
    *,
    retry_unresolved: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Resolve the producer's directory universe into ``symbol_map`` plus a receipt."""
    universe = build_universe(
        Path(nasdaq_listed).read_text(encoding="utf-8"),
        Path(other_listed).read_text(encoding="utf-8"),
    )
    symbol_map = Path(symbol_map)
    mapping: dict[str, str | None] = {}
    if symbol_map.exists():
        mapping = {k: v for k, v in load_symbol_map(symbol_map).items() if k in universe}
    receipt_path = symbol_map.with_name(symbol_map.stem + ".receipt.json")
    receipt: dict[str, Any] = {}

    def save(current: dict[str, str | None], ambiguous: dict[str, list[str]], boats: int) -> None:
        kept = {name: current[name] for name in universe if name in current}
        if kept:
            write_atomic(symbol_map, kept)
        receipt.clear()
        receipt.update(
            {
                "schema": "sextant.tv-symbol-map-receipt/1",
                "written_at": now().isoformat(),
                "source": (
                    "official MCP search_symbols; exact ticker, type stock, country/US, "
                    "BOATS dropped, exactly one listing (LEAD-0201)"
                ),
                "universe": len(universe),
                "searched_or_cached": len(kept),
                "mapped": sum(value is not None for value in kept.values()),
                "unresolved": sorted(name for name, value in kept.items() if value is None),
                "ambiguous_this_run": ambiguous,
                "boats_decided_this_run": boats,
            }
        )
        write_atomic(receipt_path, receipt)

    await resolve(tools, universe, mapping, save=save, retry_unresolved=retry_unresolved)
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sextant.tradingview.symbols",
        description="Resolve the display universe with the official read-only symbol search.",
    )
    parser.add_argument("--nasdaq-listed", type=Path, required=True)
    parser.add_argument("--other-listed", type=Path, required=True)
    parser.add_argument("--symbol-map", type=Path, required=True)
    parser.add_argument("--authorize", action="store_true", help="Owner browser consent, RAM-only")
    parser.add_argument("--retry-unresolved", action="store_true")
    args = parser.parse_args(argv)

    async def session() -> dict[str, Any] | SyncError:
        async with official_client(args.authorize) as client:
            try:
                tools = SymbolSearch(client)
                return await build(
                    args.nasdaq_listed,
                    args.other_listed,
                    args.symbol_map,
                    tools,
                    retry_unresolved=args.retry_unresolved,
                )
            except SyncError as error:
                return error

    try:
        outcome = asyncio.run(session())
    except SyncError as error:
        print(f"Symbol map stopped; progress kept. Safe diagnostic: {error.stop_tail()}.")
        return 2
    except Exception:
        print("Symbol map stopped; progress kept.")
        return 2
    if isinstance(outcome, SyncError):
        print(f"Symbol map stopped; progress kept. Safe diagnostic: {outcome.stop_tail()}.")
        return 2
    summary = {key: outcome[key] for key in ("universe", "searched_or_cached", "mapped")}
    print(json.dumps({**summary, "unresolved": len(outcome["unresolved"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
