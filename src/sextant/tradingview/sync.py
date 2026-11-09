"""Official MCP membership/readback slice from northstar-trading@8256c16c.

Adapted from tradingview/{research,sync,contracts}.py. The SDK session API sends
each write once; Client.call_tool may re-send on HEADER_MISMATCH, so is excluded.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Never

from jsonschema import Draft202012Validator
from mcp import Client

from sextant.tradingview.inputs import NAMES, ResearchInputs

ALLOWED = {
    "list_watchlists": set(),
    "get_watchlist": {"watchlist_id"},
    "create_watchlist": {"name", "symbols"},
    "add_to_watchlist": {"watchlist_id", "symbols"},
    "remove_from_watchlist": {"watchlist_id", "symbols"},
}
WIRE = {"mcp-watchlist-" + name.replace("_", "-"): name for name in ALLOWED}


class SyncError(RuntimeError):
    """Re-inventory after refusal: an earlier write may have succeeded."""


def _sanitized(error: BaseException) -> Never:
    """Upstream auth_safety.raise_sanitized; no retained raw exception graph."""
    try:
        raise error from None
    except BaseException:
        error.__context__ = None
        error.__cause__ = None
        raise


def _unwrap(value: Any) -> Any:
    if isinstance(value, dict):
        if (
            value.get("success") is False
            or value.get("error")
            or value.get("partial") is True
            or value.get("has_more") is True
            or value.get("next_cursor")
        ):
            raise SyncError("Incomplete or failed MCP response; no automatic replay")
        if set(value) == {"result"}:
            return _unwrap(value["result"])
        if set(value) == {"data", "success"} and value["success"] is True:
            return _unwrap(value["data"])
    return value


class OfficialTools:
    """Exact display allowlist, discovered schemas, serial pacing and safe errors."""

    def __init__(
        self,
        client: Client,
        interval: float = 0.75,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.client, self.interval, self.now = client, interval, now
        self.schemas: dict[str, Any] = {}
        self.wire: dict[str, str] = {}
        self.last_call = 0.0
        self.lock = asyncio.Lock()

    async def discover(self) -> None:
        self.schemas.clear()
        self.wire.clear()
        cursor, seen = None, set()
        for _ in range(100):
            async with self.lock:
                await self._pace()
                page = await self.client.list_tools(cursor=cursor, cache_mode="refresh")
            for tool in page.tools:
                name = WIRE.get(tool.name, tool.name)
                if name in ALLOWED:
                    if name in self.schemas:
                        raise SyncError("Ambiguous official tool identity")
                    self.schemas[name], self.wire[name] = tool.input_schema, tool.name
            cursor = page.next_cursor
            if cursor is None:
                break
            if cursor in seen:
                raise SyncError("Repeated tools/list cursor")
            seen.add(cursor)
        else:
            raise SyncError("Incomplete tool discovery")
        if set(self.schemas) != set(ALLOWED):
            raise SyncError("Required official watchlist tools unavailable")

    def fresh(self, inputs: ResearchInputs) -> None:
        if self.now() >= inputs.expires_at:
            raise SyncError("Research expired during sync; no further write")

    def validate(self, name: str, arguments: dict[str, Any]) -> None:
        if (
            name not in ALLOWED
            or arguments.keys() - ALLOWED[name]
            or name not in self.schemas
            or not Draft202012Validator(self.schemas[name]).is_valid(arguments)
        ):
            raise SyncError("Non-display operation or incompatible official input schema")

    async def _pace(self, inputs: ResearchInputs | None = None) -> None:
        # Caller holds the one lock for discovery pages and tool requests alike.
        delay = self.interval - (time.monotonic() - self.last_call)
        if delay > 0:
            await asyncio.sleep(delay)
        if inputs is not None:
            self.fresh(inputs)
        self.last_call = time.monotonic()

    async def call(self, name: str, arguments: dict[str, Any], *, inputs=None) -> Any:
        self.validate(name, arguments)
        async with self.lock:
            await self._pace(inputs)
            # No high-level tool-call negotiation/replay on an ambiguous mutation.
            try:
                result = await self.client.session.call_tool(
                    self.wire[name], arguments, read_timeout_seconds=60.0
                )
            except Exception:
                _sanitized(SyncError("MCP session refused or interrupted; no automatic replay"))
        if result.is_error:
            raise SyncError(
                "Official MCP call failed or was quota-limited; re-inventory before retry"
            )
        value = result.structured_content
        if value is None:
            texts = [part.text for part in result.content if part.type == "text"]
            try:
                if len(texts) != 1:
                    raise ValueError
                value = json.loads(texts[0], parse_float=Decimal)
            except ValueError:
                raise SyncError("Unknown MCP result envelope") from None
        return _unwrap(value)


def _id(row: dict[str, Any]) -> str:
    values = [row[key] for key in ("id", "watchlist_id") if key in row]
    if (
        not values
        or any(
            isinstance(value, bool)
            or not isinstance(value, (str, int))
            or not str(value).isascii()
            or not str(value).isdigit()
            for value in values
        )
        or len({str(value) for value in values}) != 1
    ):
        raise SyncError("Invalid or conflicting owned-list ID")
    return str(values[0])


async def _membership(tools: OfficialTools, name: str, key: str) -> set[str]:
    row = await tools.call("get_watchlist", {"watchlist_id": key})
    if isinstance(row, dict) and "watchlist" in row and set(row) <= {"watchlist", "note"}:
        row = _unwrap(row["watchlist"])
    if (
        not isinstance(row, dict)
        or row.get("name") != name
        or _id(row) != key
        or row.get("read_only") not in (None, False)
    ):
        raise SyncError("Owned watchlist is read-only or changed identity")
    symbols = row.get("symbols")
    if not isinstance(symbols, list) or any(not isinstance(symbol, str) for symbol in symbols):
        raise SyncError("Unknown watchlist membership envelope")
    return set(symbols)


async def _inventory(tools: OfficialTools) -> dict[str, tuple[str, set[str]]]:
    rows = await tools.call("list_watchlists", {})
    rows = rows.get("watchlists") if isinstance(rows, dict) else rows
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise SyncError("Unknown watchlist inventory envelope")
    result = {}
    for name in NAMES:
        matches = [row for row in rows if row.get("name") == name]
        if len(matches) > 1:
            raise SyncError("Duplicate reserved watchlist name")
        if not matches:
            continue
        key = _id(matches[0])
        references = sum(
            any(
                isinstance(row.get(field), (str, int))
                and not isinstance(row.get(field), bool)
                and str(row[field]) == key
                for field in ("id", "watchlist_id")
            )
            for row in rows
        )
        if references != 1:
            raise SyncError("Owned watchlist aliases another list")
        result[name] = key, await _membership(tools, name, key)
    return result


async def read_memberships(tools: OfficialTools) -> dict[str, frozenset[str]]:
    """Complete by-ID read-back; an absent reserved list is the known-empty fresh install.

    The display loop seeds ``Cadence`` with this pair so the first admission compares
    against observed membership, never a guessed empty or cleared list. Unknown,
    duplicate or aliased inventory raises before any run is claimed.
    """
    await tools.discover()
    inventory = await _inventory(tools)
    return {
        name: frozenset(inventory[name][1]) if name in inventory else frozenset() for name in NAMES
    }


async def sync_research(
    tools: OfficialTools, inputs: ResearchInputs, *, apply=False
) -> dict[str, Any]:
    """Preflight all operations, apply once, then verify the two named lists."""
    if (
        set(inputs.memberships) != set(NAMES)
        or not inputs.memberships["NS movers"]
        or len(inputs.unmapped) > 5
    ):
        raise SyncError("Only a validated nonempty research membership pair can be synced")
    tools.fresh(inputs)
    await tools.discover()
    current = await _inventory(tools)
    operations = []
    for name in NAMES:
        desired = inputs.memberships[name]
        if name not in current:
            operations.append(
                {
                    "tool": "create_watchlist",
                    "arguments": {"name": name, "symbols": sorted(desired)},
                }
            )
            continue
        key, stored = current[name]
        for tool, delta in (
            ("add_to_watchlist", desired - stored),
            ("remove_from_watchlist", stored - desired),
        ):
            if delta:
                operations.append(
                    {"tool": tool, "arguments": {"watchlist_id": key, "symbols": sorted(delta)}}
                )
    for operation in operations:
        tools.validate(operation["tool"], operation["arguments"])
    tools.fresh(inputs)
    result = {
        "applied": False,
        "operations": operations,
        "readback": {},
        "unmapped": sorted(inputs.unmapped),
    }
    if not apply:
        return result
    for operation in operations:
        response = await tools.call(operation["tool"], operation["arguments"], inputs=inputs)
        if operation["tool"] != "create_watchlist" and response != {"success": True}:
            raise SyncError("Ambiguous watchlist mutation; re-inventory before retry")
        if operation["tool"] == "create_watchlist":
            # Validate creation identity before any later mutation. Re-inventory
            # also detects duplicate names and aliases before final readback.
            row = response
            if isinstance(row, dict) and "watchlist" in row and set(row) <= {"watchlist", "note"}:
                row = _unwrap(row["watchlist"])
            if (
                not isinstance(row, dict)
                or row.get("name") != operation["arguments"]["name"]
                or row.get("read_only") not in (None, False)
                or not isinstance(row.get("symbols"), list)
                or any(not isinstance(symbol, str) for symbol in row["symbols"])
            ):
                raise SyncError("Unknown create result; re-inventory before retry")
            if _id(row) in {item[0] for item in current.values()}:
                raise SyncError("Created list aliases an existing list; no further writes")
    if any(op["tool"] == "create_watchlist" for op in operations):
        current = await _inventory(tools)
    rejected_all = set()
    for name in NAMES:
        if name not in current:
            raise SyncError("Created watchlist missing from readback")
        key = current[name][0]
        stored = await _membership(tools, name, key)
        desired = inputs.memberships[name]
        rejected, extras = desired - stored, stored - desired
        if extras:
            response = await tools.call(
                "remove_from_watchlist",
                {"watchlist_id": key, "symbols": sorted(extras)},
                inputs=inputs,
            )
            if response != {"success": True}:
                raise SyncError("Ambiguous corrective removal; no replay")
            stored = await _membership(tools, name, key)
        result["readback"][name] = {
            "stored": sorted(stored),
            "rejected": sorted(rejected),
            "corrective_removals": sorted(extras),
        }
        rejected_all.update(rejected)
        if stored != desired - rejected:
            raise SyncError("Readback mismatch after one corrective removal; no replay")
    if len(rejected_all) > 5:
        raise SyncError(
            "Readback rejected more than five distinct names; verified subsets retained"
        )
    result["applied"] = True
    return result
