"""Official MCP membership/readback slice from northstar-trading@8256c16c.

Adapted from tradingview/{research,sync,contracts}.py. The SDK session API sends
each write once; Client.call_tool may re-send on HEADER_MISMATCH, so is excluded.
"""

from __future__ import annotations

import asyncio
import json
import re
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
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


class SyncError(RuntimeError):
    """Re-inventory after refusal: an earlier write may have succeeded.

    ``label``, ``stage`` and ``detail`` are fixed diagnostic literals (a type
    name, one of the flow positions: inputs, authorize, callback, token, client
    registration, session, tool list, tool call, apply, and fixed-vocabulary
    names-only detail). They never carry upstream text, values or credentials.
    """

    def __init__(self, message: str, *, label: str = "", stage: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.label = label
        self.stage = stage
        self.detail = detail


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
            raise SyncError(
                "Incomplete or failed MCP response; no automatic replay",
                stage="tool call",
            )
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
        offered: set[str] = set()
        for _ in range(100):
            async with self.lock:
                await self._pace()
                page = await self.client.list_tools(cursor=cursor, cache_mode="refresh")
            for tool in page.tools:
                if isinstance(tool.name, str) and _NAME.match(tool.name):
                    offered.add(tool.name)
                name = WIRE.get(tool.name, tool.name)
                if name in ALLOWED:
                    if name in self.schemas:
                        raise SyncError("Ambiguous official tool identity", stage="tool list")
                    self.schemas[name], self.wire[name] = tool.input_schema, tool.name
            cursor = page.next_cursor
            if cursor is None:
                break
            if cursor in seen:
                raise SyncError("Repeated tools/list cursor", stage="tool list")
            seen.add(cursor)
        else:
            raise SyncError("Incomplete tool discovery", stage="tool list")
        if set(self.schemas) != set(ALLOWED):
            required = set(WIRE)
            missing = sorted(required - set(self.wire.values()))[:8]
            extra = sorted(raw for raw in offered if WIRE.get(raw, raw) not in ALLOWED)[:8]
            detail = (
                f"tool list extra {', '.join(extra) or 'none'}; "
                f"missing {', '.join(missing) or 'none'}"
            )
            raise SyncError(
                "Required official watchlist tools unavailable",
                stage="tool list",
                detail=detail,
            )

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
            raise SyncError(
                "Non-display operation or incompatible official input schema",
                stage="tool call",
            )

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
                error = SyncError(
                    "MCP session refused or interrupted; no automatic replay",
                    stage="tool call",
                )
                _sanitized(error)
        if result.is_error:
            raise SyncError(
                "Official MCP call failed or was quota-limited; re-inventory before retry",
                stage="tool call",
            )
        value = result.structured_content
        if value is None:
            texts = [part.text for part in result.content if part.type == "text"]
            try:
                if len(texts) != 1:
                    raise ValueError
                value = json.loads(texts[0], parse_float=Decimal)
            except ValueError:
                raise SyncError("Unknown MCP result envelope", stage="tool call") from None
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
        raise SyncError("Invalid or conflicting owned-list ID", stage="tool call")
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
        raise SyncError("Owned watchlist is read-only or changed identity", stage="tool call")
    symbols = row.get("symbols")
    if not isinstance(symbols, list) or any(not isinstance(symbol, str) for symbol in symbols):
        raise SyncError("Unknown watchlist membership envelope", stage="tool call")
    return set(symbols)


async def _inventory(tools: OfficialTools) -> dict[str, tuple[str, set[str]]]:
    rows = await tools.call("list_watchlists", {})
    rows = rows.get("watchlists") if isinstance(rows, dict) else rows
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise SyncError("Unknown watchlist inventory envelope", stage="tool call")
    result = {}
    for name in NAMES:
        matches = [row for row in rows if row.get("name") == name]
        if len(matches) > 1:
            raise SyncError("Duplicate reserved watchlist name", stage="tool call")
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
            raise SyncError("Owned watchlist aliases another list", stage="tool call")
        result[name] = key, await _membership(tools, name, key)
    return result


async def sync_research(
    tools: OfficialTools, inputs: ResearchInputs, *, apply=False
) -> dict[str, Any]:
    """Preflight all operations, apply once, then verify the two named lists."""
    if (
        set(inputs.memberships) != set(NAMES)
        or not inputs.memberships["NS movers"]
        or len(inputs.unmapped) > 5
    ):
        raise SyncError(
            "Only a validated nonempty research membership pair can be synced",
            stage="inputs",
        )
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
            raise SyncError(
                "Ambiguous watchlist mutation; re-inventory before retry",
                stage="apply",
            )
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
                raise SyncError(
                    "Unknown create result; re-inventory before retry",
                    stage="apply",
                )
            if _id(row) in {item[0] for item in current.values()}:
                raise SyncError(
                    "Created list aliases an existing list; no further writes",
                    stage="apply",
                )
    if any(op["tool"] == "create_watchlist" for op in operations):
        current = await _inventory(tools)
    rejected_all = set()
    for name in NAMES:
        if name not in current:
            raise SyncError("Created watchlist missing from readback", stage="apply")
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
                raise SyncError("Ambiguous corrective removal; no replay", stage="apply")
            stored = await _membership(tools, name, key)
        result["readback"][name] = {
            "stored": sorted(stored),
            "rejected": sorted(rejected),
            "corrective_removals": sorted(extras),
        }
        rejected_all.update(rejected)
        if stored != desired - rejected:
            raise SyncError(
                "Readback mismatch after one corrective removal; no replay",
                stage="apply",
            )
    if len(rejected_all) > 5:
        raise SyncError(
            "Readback rejected more than five distinct names; verified subsets retained"
        )
    result["applied"] = True
    return result
