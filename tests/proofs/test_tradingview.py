"""ADR-0021/26 witnesses against the real SDK's in-memory transport; no account."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib
import json
import socket
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from mcp import Client
from mcp.server import MCPServer

NOW = datetime(2026, 11, 6, 14, 30, tzinfo=UTC)


def api():
    try:
        return importlib.import_module("sextant.tradingview.inputs"), importlib.import_module(
            "sextant.tradingview.sync"
        )
    except ModuleNotFoundError:
        pytest.fail("The fixture-tested TradingView sync is not implemented")


def member(symbol: str, venue: str | None = "NASDAQ") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "tradingview_symbol": f"{venue}:{symbol}" if venue else None,
        "labels": ["early:1"],
    }


def unit(path: Path, *, movers=None, focus=None) -> Path:
    movers = [member("AAPL"), member("MSFT")] if movers is None else movers
    focus = [member("MSFT")] if focus is None else focus
    generation = {"as_of": "2026-11-06T14:29:00+00:00", "sha256": "a" * 64}
    common = {
        "session_date": "2026-11-06",
        "generated_at": "2026-11-06T14:29:30+00:00",
        "as_of": "2026-11-06T14:29:10+00:00",
        "as_of_snapshot": generation["as_of"],
        "snapshot_status": "observed",
        "status": "fresh",
        "generation": generation,
    }
    documents = {
        "top100.json": {"schema": "morning-pack.candidates/1", **common, "candidates": movers},
        "focus.json": {"schema": "top100.focus/1", **common, "candidates": focus},
        "display-lists.json": {
            "schema": "ns-display-lists/1",
            **common,
            "ns_movers": movers,
            "ns_focus": focus,
            "bounds": {"gap_bound": "0.05", "rvol_bound": "2", "max_age_s": 600},
            "counts": {"ns_movers": len(movers), "ns_focus": len(focus)},
            "excluded_unknown": 0,
            "armed": "UNVERIFIED",
            "sources": {"snapshot": {"path": "snapshot.json", **generation}, "armed_sets": []},
        },
    }
    path.mkdir(parents=True, exist_ok=True)
    for name, doc in documents.items():
        (path / name).write_text(json.dumps(doc))
    return path


def change(path: Path, name: str, **values: Any) -> None:
    doc = json.loads((path / name).read_text())
    doc.update(values)
    (path / name).write_text(json.dumps(doc))


class Peer:
    """Pinned upstream test_sync.py/test_readback_verify.py's SDK fixture peer."""

    def __init__(self):
        self.server = MCPServer("fixture official TradingView", log_level="CRITICAL")
        self.lists = {
            "1": {"id": "1", "name": "NS movers", "symbols": ["NASDAQ:MSFT", "NYSE:IBM"]},
            "2": {"id": "2", "name": "NS focus", "symbols": []},
            "3": {"id": "3", "name": "Owner favorites", "symbols": ["NYSE:IBM"]},
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.reject: set[str] = set()
        self.extras: set[str] = set()
        self.stubborn = False
        self.ambiguous = False
        self.malformed = False
        self.bad_create = False

        @self.server.tool(name="mcp-watchlist-list-watchlists")
        def list_watchlists() -> dict[str, Any]:
            self.calls.append(("list_watchlists", {}))
            return (
                {"partial": True, "watchlists": []}
                if self.malformed
                else {"watchlists": copy.deepcopy(list(self.lists.values()))}
            )

        @self.server.tool(name="mcp-watchlist-get-watchlist")
        def get_watchlist(watchlist_id: str) -> dict[str, Any]:
            self.calls.append(("get_watchlist", {"watchlist_id": watchlist_id}))
            return {"watchlist": copy.deepcopy(self.lists[watchlist_id])}

        @self.server.tool(name="mcp-watchlist-create-watchlist")
        def create_watchlist(name: str, symbols: list[str]) -> dict[str, Any]:
            self.calls.append(("create_watchlist", {"name": name, "symbols": symbols}))
            key = str(max((int(key) for key in self.lists), default=0) + 1)
            self.lists[key] = {
                "id": key,
                "name": name,
                "symbols": sorted(set(symbols) - self.reject),
            }
            row = copy.deepcopy(self.lists[key])
            if self.bad_create:
                row["name"] = "Unexpected list"
            return {"watchlist": row}

        @self.server.tool(name="mcp-watchlist-add-to-watchlist")
        def add_to_watchlist(watchlist_id: str, symbols: list[str]) -> dict[str, Any]:
            self.calls.append(
                ("add_to_watchlist", {"watchlist_id": watchlist_id, "symbols": symbols})
            )
            self.lists[watchlist_id]["symbols"].extend(sorted(set(symbols) - self.reject))
            self.lists[watchlist_id]["symbols"].extend(sorted(self.extras))
            return (
                {"unknown": "a write may have succeeded"} if self.ambiguous else {"success": True}
            )

        @self.server.tool(name="mcp-watchlist-remove-from-watchlist")
        def remove_from_watchlist(watchlist_id: str, symbols: list[str]) -> dict[str, Any]:
            self.calls.append(
                ("remove_from_watchlist", {"watchlist_id": watchlist_id, "symbols": symbols})
            )
            if not (self.stubborn and set(symbols) & self.extras):
                self.lists[watchlist_id]["symbols"] = [
                    value for value in self.lists[watchlist_id]["symbols"] if value not in symbols
                ]
            return {"success": True}


def run_sync(path: Path, peer: Peer, *, apply=True, clock=None):
    inputs, sync = api()
    data = inputs.read_research_inputs(path, now=NOW)

    async def run():
        error = None
        result = None
        async with Client(peer.server) as client:
            tools = sync.OfficialTools(client, interval=0, now=clock or (lambda: NOW))
            # SDK task groups wrap errors raised through __aexit__; test the
            # adapter's error after closing the real transport normally.
            try:
                result = await sync.sync_research(tools, data, apply=apply)
            except sync.SyncError as exc:
                error = exc
        if error:
            raise error
        assert result is not None
        return result

    return asyncio.run(run())


def test_membership_sync_preserves_survivor_order_and_owner_lists(tmp_path: Path):
    peer = Peer()
    result = run_sync(unit(tmp_path), peer)
    assert peer.lists["1"]["symbols"] == ["NASDAQ:MSFT", "NASDAQ:AAPL"]
    assert peer.lists["2"]["symbols"] == ["NASDAQ:MSFT"]
    assert peer.lists["3"]["symbols"] == ["NYSE:IBM"]
    assert result["applied"] is True
    assert result["readback"]["NS movers"]["stored"] == ["NASDAQ:AAPL", "NASDAQ:MSFT"]
    peer.calls.clear()
    again = run_sync(tmp_path, peer)
    assert again["operations"] == []
    assert [name for name, _ in peer.calls] == [
        "list_watchlists",
        "get_watchlist",
        "get_watchlist",
        "get_watchlist",
        "get_watchlist",
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "stale"),
        ("snapshot_status", "missing"),
        ("generated_at", "2026-11-06T14:31:00+00:00"),
        ("as_of_snapshot", "2026-11-06T14:00:00+00:00"),
        ("generated_at", "2026-11-06T14:29:30"),
        ("session_date", "2026-11-05"),
        ("generation", {"as_of": "2026-11-06T14:29:00+00:00", "sha256": "b" * 64}),
    ],
)
def test_invalid_or_mixed_unit_is_unavailable(tmp_path: Path, field, value):
    inputs, _ = api()
    unit(tmp_path)
    change(tmp_path, "focus.json", **{field: value})
    with pytest.raises(inputs.InputError):
        inputs.read_research_inputs(tmp_path, now=NOW)


def test_missing_display_and_empty_movers_never_become_a_cleanup(tmp_path: Path):
    inputs, _ = api()
    unit(tmp_path)
    (tmp_path / "display-lists.json").unlink()
    with pytest.raises(inputs.InputError):
        inputs.read_research_inputs(tmp_path, now=NOW)
    unit(tmp_path, movers=[])
    with pytest.raises(inputs.InputError):
        inputs.read_research_inputs(tmp_path, now=NOW)


def test_five_unmapped_omitted_six_refused_and_cross_list_venues_match(tmp_path: Path):
    inputs, _ = api()
    rows = [member("AAPL"), *[member(f"U{n}", None) for n in range(5)]]
    unit(tmp_path, movers=rows, focus=[])
    result = inputs.read_research_inputs(tmp_path, now=NOW)
    assert result.memberships["NS movers"] == frozenset({"NASDAQ:AAPL"})
    assert result.unmapped == frozenset({"U0", "U1", "U2", "U3", "U4"})
    unit(tmp_path, movers=[*rows, member("U5", None)], focus=[])
    with pytest.raises(inputs.InputError):
        inputs.read_research_inputs(tmp_path, now=NOW)
    unit(tmp_path, focus=[member("AAPL", "NYSE")])
    with pytest.raises(inputs.InputError):
        inputs.read_research_inputs(tmp_path, now=NOW)


def test_display_focus_may_include_producer_armed_names_outside_movers(tmp_path: Path):
    inputs, _ = api()
    result = inputs.read_research_inputs(unit(tmp_path, focus=[member("IBM", "NYSE")]), now=NOW)
    assert result.memberships["NS focus"] == frozenset({"NYSE:IBM"})


def test_rejections_are_reported_once_and_extras_get_one_correction(tmp_path: Path):
    peer = Peer()
    peer.reject = {"NASDAQ:AAPL"}
    peer.extras = {"NYSE:EXTRA"}
    result = run_sync(unit(tmp_path), peer)
    assert result["readback"]["NS movers"]["rejected"] == ["NASDAQ:AAPL"]
    assert result["readback"]["NS focus"]["corrective_removals"] == ["NYSE:EXTRA"]
    assert len([1 for name, _ in peer.calls if name == "add_to_watchlist"]) == 2
    assert peer.lists["2"]["symbols"] == ["NASDAQ:MSFT"]


@pytest.mark.parametrize(
    "failure",
    ["six_rejected", "stubborn", "ambiguous", "partial", "duplicate", "alias", "readonly"],
)
def test_refusal_stops_without_automatic_replay(tmp_path: Path, failure):
    _, sync = api()
    peer = Peer()
    path = unit(tmp_path)
    if failure == "six_rejected":
        rows = [member(f"U{n}") for n in range(6)]
        unit(path, movers=rows, focus=[])
        peer.reject = {f"NASDAQ:U{n}" for n in range(6)}
    elif failure == "stubborn":
        peer.extras, peer.stubborn = {"NYSE:EXTRA"}, True
    elif failure == "ambiguous":
        peer.ambiguous = True
    elif failure == "partial":
        peer.malformed = True
    elif failure == "duplicate":
        peer.lists["3"]["name"] = "NS movers"
    elif failure == "alias":
        peer.lists["3"]["id"] = "1"
    else:
        peer.lists["2"]["read_only"] = True
    with pytest.raises(sync.SyncError):
        run_sync(path, peer)
    if failure in {"partial", "duplicate", "alias", "readonly"}:
        assert all(name in {"list_watchlists", "get_watchlist"} for name, _ in peer.calls)
    if failure == "ambiguous":
        assert [name for name, _ in peer.calls].count("add_to_watchlist") == 1


def test_create_readback_and_dry_run_do_not_claim_same_success(tmp_path: Path):
    peer = Peer()
    del peer.lists["2"]
    result = run_sync(unit(tmp_path), peer, apply=False)
    assert result["applied"] is False and result["readback"] == {}
    assert all(name in {"list_watchlists", "get_watchlist"} for name, _ in peer.calls)
    result = run_sync(tmp_path, peer)
    assert result["readback"]["NS focus"]["stored"] == ["NASDAQ:MSFT"]


def test_expiry_before_write_and_non_display_tool_refused(tmp_path: Path):
    _, sync = api()
    peer = Peer()
    with pytest.raises(sync.SyncError):
        run_sync(unit(tmp_path), peer, clock=lambda: NOW + timedelta(minutes=30))
    assert peer.lists["1"]["symbols"] == ["NASDAQ:MSFT", "NYSE:IBM"]

    async def run():
        async with Client(peer.server) as client:
            tools = sync.OfficialTools(client, interval=0, now=lambda: NOW)
            await tools.discover()
            with pytest.raises(sync.SyncError):
                await tools.call("place_order", {})

    asyncio.run(run())


@pytest.mark.parametrize("namespaced", [False, True])
def test_official_discovery_ignores_every_non_membership_tool(
    monkeypatch: pytest.MonkeyPatch, namespaced: bool
):
    from mcp.server import Server
    from mcp.types import CallToolResult, ListToolsResult, Tool

    _, sync = api()
    documented = (
        "list_watchlists",
        "get_watchlist",
        "get_active_watchlist",
        "create_watchlist",
        "delete_watchlist",
        "add_to_watchlist",
        "remove_from_watchlist",
        "update_watchlist",
        "get_ohlcv",
        "get_economic_data",
        "get_economic_symbols",
        "search_symbols",
        "get_symbol_data",
        "run_screener",
        "get_symbol_data_batch",
        "get_screener_columns",
        "get_technicals_rating",
        "get_news",
        "get_news_story",
        "get_forecasts",
        "get_financials",
        "get_financial_history",
        "get_documents",
        "get_document_view",
        "get_earnings_calendar",
        "get_economic_calendar",
        "get_dividends_calendar",
        "create_alert",
        "update_alert",
        "delete_alert",
        "stop_alerts",
        "restart_alerts",
        "list_alerts",
        "get_alerts",
        "get_alerts_log",
    )
    membership = {
        "list_watchlists": {},
        "get_watchlist": {"watchlist_id": "1"},
        "create_watchlist": {"name": "NS movers", "symbols": []},
        "add_to_watchlist": {"watchlist_id": "1", "symbols": []},
        "remove_from_watchlist": {"watchlist_id": "1", "symbols": []},
    }
    wire = {
        name: "mcp-watchlist-" + name.replace("_", "-") if namespaced else name
        for name in membership
    }
    refused = (set(documented) - membership.keys()) | {
        "place_order",
        "mcp-watchlist-delete-watchlist",
        "mcp-watchlist-update-watchlist",
        "mcp-watchlist-get-active-watchlist",
    }
    requests = []

    def deny_connection(*args, **kwargs):
        pytest.fail("The official MCP inventory proof must not open a socket connection")

    monkeypatch.setattr(socket.socket, "connect", deny_connection)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_connection)
    monkeypatch.setattr(socket, "create_connection", deny_connection)

    async def list_tools(_ctx, _params):
        requests.append("tools/list")
        return ListToolsResult(
            tools=[
                Tool(
                    name=wire.get(name, name),
                    input_schema={"type": "object", "additionalProperties": True},
                )
                for name in (*documented, "place_order")
            ]
        )

    async def call_tool(_ctx, params):
        requests.append(params.name)
        assert params.name == wire["list_watchlists"] and params.arguments == {}
        return CallToolResult(content=[], structured_content={"watchlists": []})

    server = Server(
        "2026-11-09 official inventory", on_list_tools=list_tools, on_call_tool=call_tool
    )

    async def run():
        async with Client(server) as client:
            tools = sync.OfficialTools(client, interval=0)
            await tools.discover()
            assert tools.schemas.keys() == membership.keys()
            assert tools.wire == wire
            for name, arguments in membership.items():
                tools.validate(name, arguments)
            for name in sorted(refused):
                with pytest.raises(sync.SyncError, match="Non-display operation"):
                    tools.validate(name, {})
                with pytest.raises(sync.SyncError, match="Non-display operation"):
                    await tools.call(name, {})
            assert requests == ["tools/list"]
            assert await tools.call("list_watchlists", {}) == {"watchlists": []}

    assert len(documented) == len(set(documented)) == 35
    asyncio.run(run())
    assert requests == ["tools/list", wire["list_watchlists"]]


def test_three_discovery_pages_and_first_tool_share_the_limiter(monkeypatch: pytest.MonkeyPatch):
    from mcp.server import Server
    from mcp.types import CallToolResult, ListToolsResult, Tool

    _, sync = api()
    current = 10.0
    requests = []
    names = list(sync.WIRE)

    async def list_tools(_ctx, params):
        cursor = params.cursor if params else None
        page = {None: 0, "second": 1, "third": 2}[cursor]
        requests.append(("discovery", current))
        return ListToolsResult(
            tools=[
                Tool(name=name, input_schema={"type": "object"})
                for name in names[2 * page : 2 * page + 2]
            ],
            next_cursor=["second", "third", None][page],
        )

    async def call_tool(_ctx, params):
        assert params.name == "mcp-watchlist-list-watchlists" and params.arguments == {}
        requests.append(("tool", current))
        return CallToolResult(content=[], structured_content={"watchlists": []})

    async def sleep(seconds):
        nonlocal current
        current += seconds

    monkeypatch.setattr(sync, "time", SimpleNamespace(monotonic=lambda: current))
    monkeypatch.setattr(sync, "asyncio", SimpleNamespace(Lock=asyncio.Lock, sleep=sleep))
    server = Server("three-page fixture", on_list_tools=list_tools, on_call_tool=call_tool)

    async def run():
        async with Client(server) as client:
            tools = sync.OfficialTools(client)
            await tools.discover()
            return await tools.call("list_watchlists", {})

    assert asyncio.run(run()) == {"watchlists": []}
    assert requests == [
        ("discovery", 10.0),
        ("discovery", 10.75),
        ("discovery", 11.5),
        ("tool", 12.25),
    ]


def test_expiry_is_checked_after_pacing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs, sync = api()
    data = inputs.read_research_inputs(unit(tmp_path), now=NOW)
    peer = Peer()
    current = NOW

    async def sleep(_seconds):
        nonlocal current
        current = NOW + timedelta(minutes=30)

    async def run():
        async with Client(peer.server) as client:
            tools = sync.OfficialTools(client, now=lambda: current)
            await tools.discover()
            tools.last_call = sync.time.monotonic()
            monkeypatch.setattr(sync.asyncio, "sleep", sleep)
            with pytest.raises(sync.SyncError):
                await tools.call(
                    "add_to_watchlist",
                    {"watchlist_id": "1", "symbols": ["NASDAQ:AAPL"]},
                    inputs=data,
                )

    asyncio.run(run())
    assert peer.calls == []


def test_all_operation_schemas_are_preflighted_before_first_write(tmp_path: Path):
    _, sync = api()
    peer = Peer()
    peer.server.remove_tool("mcp-watchlist-remove-from-watchlist")

    @peer.server.tool(name="mcp-watchlist-remove-from-watchlist")
    def incompatible_remove(watchlist_id: str, symbols: list[str], extra_required: str) -> dict:
        pytest.fail("An incompatible mutation must never reach the peer")

    with pytest.raises(sync.SyncError):
        run_sync(unit(tmp_path), peer)
    assert peer.lists["1"]["symbols"] == ["NASDAQ:MSFT", "NYSE:IBM"]
    assert all(name in {"list_watchlists", "get_watchlist"} for name, _ in peer.calls)


def test_presets_have_immutable_ids_and_detect_modified_source(tmp_path: Path):
    try:
        presets = importlib.import_module("sextant.tradingview.presets")
    except ModuleNotFoundError:
        pytest.fail("The dated Pine preset package is not implemented")
    root = Path(__file__).parents[2] / "lanes/tradingview/presets"
    result = presets.preset_receipt(root)
    assert {row["script_id"] for row in result} == {
        "NS 2026-11-06 · ema_cross",
        "NS 2026-11-06 · hurst_vpin",
        "NS 2026-11-06 · quote_imbalance",
        "NS 2026-11-06 · exit_levels",
    }
    manifest = json.loads((root / "manifest.json").read_text())
    for item in manifest:
        path = root / item["file"]
        text = path.read_text()
        # Formula bytes are the pinned upstream artifact, with only its title changed.
        normalized = text.replace(item["script_id"], item["upstream_title"], 1)
        assert hashlib.sha256(normalized.encode()).hexdigest() == item["upstream_sha256"]
        (tmp_path / item["file"]).write_text(text)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "exit_levels.pine").write_text("tampered")
    with pytest.raises(ValueError):
        presets.preset_receipt(tmp_path)


@pytest.mark.parametrize("corruption", ["upstream_sha256", "upstream_title", "packaged_formula"])
def test_preset_receipt_refuses_mismatched_upstream_provenance(tmp_path: Path, corruption: str):
    presets = importlib.import_module("sextant.tradingview.presets")
    root = Path(__file__).parents[2] / "lanes/tradingview/presets"
    manifest = json.loads((root / "manifest.json").read_text())
    for item in manifest:
        (tmp_path / item["file"]).write_bytes((root / item["file"]).read_bytes())
    if corruption == "packaged_formula":
        path = tmp_path / manifest[0]["file"]
        source = path.read_bytes() + b"\n// unreviewed change\n"
        path.write_bytes(source)
        manifest[0]["sha256"] = hashlib.sha256(source).hexdigest()
    else:
        manifest[0][corruption] = "0" * 64 if corruption == "upstream_sha256" else "Wrong title"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        presets.preset_receipt(tmp_path)


def test_preset_roster_keeps_managed_tickets_plain_limit():
    """The roster is the owner-manual ticket contract, never a machine order path."""
    root = Path(__file__).parents[2]
    docs = (root / "docs/tradingview.md").read_text()
    rows = [line for line in docs.splitlines() if line.startswith("| `NS ")]
    assert len(rows) == 3, f"the documented roster is not the three named presets: {rows}"
    by_name = {
        row.split("|")[1].strip().strip("`"): [cell.strip() for cell in row.split("|")[2:-1]]
        for row in rows
    }
    assert set(by_name) == {
        "NS ALPACA DAY LIMIT MANAGED",
        "NS ALPACA DAY LIMIT BRACKET",
        "NS IBKR DAY LIMIT BRACKET",
    }
    managed = by_name["NS ALPACA DAY LIMIT MANAGED"]
    assert managed[:2] == ["LIMIT", "0 relative ticks (at the touch, not a fixed price)"]
    assert managed[2:] == ["DAY", "none", "ON", "managed-paper entries"]
    for name in ("NS ALPACA DAY LIMIT BRACKET", "NS IBKR DAY LIMIT BRACKET"):
        bracket = by_name[name]
        assert bracket[0] == "LIMIT"
        assert bracket[2] == "DAY"
        assert bracket[3] == "TP/SL"
        assert bracket[5] == "owner-managed positions only"
    assert "TV presets can place brackets without confirmation" in docs
    assert "managed-paper entries stay plain LIMIT, never a bracket" in docs
    assert "at the touch, not a fixed price" in docs
    assert "20:00\u201304:00 ET" in docs
    assert "20:00 ET if unfilled" in docs
    assert "extended_hours" in docs and "false/omitted" in docs
    presets = root / "lanes/tradingview/presets"
    for pine in sorted(presets.glob("*.pine")):
        source = pine.read_text()
        for forbidden in ("strategy(", "alert(", "alertcondition("):
            assert forbidden not in source, f"{pine.name} carries an order path: {forbidden}"
    for path in sorted((root / "lanes/tradingview").rglob("*")):
        if path.is_file() and path.suffix != ".pine":
            text = path.read_text(errors="ignore").lower()
            assert '"webhook"' not in text and "autotrade" not in text
            assert "hooks.slack" not in text and "hooks.discord" not in text


def test_preset_import_card_matches_the_reviewed_manifest_hashes():
    """The owner import card must match the pinned preset manifest exactly."""
    root = Path(__file__).parents[2]
    docs = (root / "docs/tradingview.md").read_text()
    assert "## Owner import card" in docs
    card = docs.split("## Owner import card", 1)[1].split("\n## ", 1)[0]
    presets = root / "lanes/tradingview/presets"
    manifest = json.loads((presets / "manifest.json").read_text())
    assert len(manifest) == 4
    for item in manifest:
        assert f"`{item['file']}`" in card
        assert f"`{item['script_id']}`" in card
        assert item["sha256"] in card
    for phrase in (
        "NEW",
        "paste",
        "add it to the owner's chart",
        "No install automation",
        "lanes/tradingview/presets/manifest.json",
    ):
        assert phrase in card, f"import card is missing {phrase!r}"


def test_oauth_requires_explicit_owner_flag_before_any_transport():
    try:
        auth = importlib.import_module("sextant.tradingview.auth")
    except ModuleNotFoundError:
        pytest.fail("RAM-only owner-consented SDK OAuth is not implemented")
    _, sync = api()

    async def run():
        with pytest.raises(sync.SyncError, match="owner"):
            async with auth.official_client():
                pytest.fail("No session is allowed without owner browser consent")

    asyncio.run(run())


def test_cli_invalid_input_never_opens_oauth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    try:
        cli = importlib.import_module("sextant.tradingview.__main__")
    except ModuleNotFoundError:
        pytest.fail("The bounded TradingView CLI is not implemented")

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid input must stop before OAuth")

    monkeypatch.setattr(cli, "official_client", forbidden)
    assert cli.main(["--research-dir", str(tmp_path)]) == 2


@pytest.mark.parametrize("manifest", [None, "RAW RECEIPT ERROR", "[]"])
def test_cli_preset_failures_report_only_offline_receipt_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, manifest
):
    cli = importlib.import_module("sextant.tradingview.__main__")
    if manifest is not None:
        (tmp_path / "manifest.json").write_text(manifest)

    def forbidden(*args, **kwargs):
        pytest.fail("Offline receipts must never open OAuth or read research")

    monkeypatch.setattr(cli, "official_client", forbidden)
    monkeypatch.setattr(cli, "read_research_inputs", forbidden)
    assert cli.main(["--presets", str(tmp_path)]) == 2
    output = capsys.readouterr()
    assert "receipt" in output.out.lower()
    assert "no session opened" in output.out.lower()
    assert "earlier writes" not in output.out.lower()
    assert "RAW RECEIPT ERROR" not in output.out
    assert output.err == ""


def test_cli_preset_success_is_a_local_receipt_without_installation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    cli = importlib.import_module("sextant.tradingview.__main__")

    def forbidden(*args, **kwargs):
        pytest.fail("Offline receipts must never open OAuth or read research")

    monkeypatch.setattr(cli, "official_client", forbidden)
    monkeypatch.setattr(cli, "read_research_inputs", forbidden)
    root = Path(__file__).parents[2] / "lanes/tradingview/presets"
    assert cli.main(["--presets", str(root)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["installed"] is False
    assert len(result["artifacts"]) == 4


def test_nanosecond_clock_disagreement_refuses_the_generation(tmp_path: Path):
    inputs, _ = api()
    unit(tmp_path)
    change(tmp_path, "focus.json", generated_at="2026-11-06T14:29:30.000000001+00:00")
    with pytest.raises(inputs.InputError):
        inputs.read_research_inputs(tmp_path, now=NOW)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1970-01-01T00:00:00Z", 0),
        ("1969-12-31T23:59:59.999999999Z", -1),
        ("1970-01-01T00:00:00.000000001+0000", 1),
        ("1970-01-01T05:30:00+05:30", 0),
        ("1970-01-01T00:00:00+00:59", -3_540_000_000_000),
        ("1970-01-01 00:00:00-0059", 3_540_000_000_000),
        ("1970-01-01T00:00:00+2359", -86_340_000_000_000),
        ("1970-01-01T00:00:00-23:59", 86_340_000_000_000),
        ("2026-11-06T14:29:30.123456789Z", 1_793_975_370_123_456_789),
        ("2026-11-06T09:29:30.123456789-05:00", 1_793_975_370_123_456_789),
        (datetime(1970, 1, 1, 0, 0, 0, 1, tzinfo=UTC), 1_000),
        (datetime(1969, 12, 31, 23, 59, 59, 999999, tzinfo=UTC), -1_000),
        (datetime(1970, 1, 1, tzinfo=timezone(timedelta(microseconds=1))), -1_000_000_000),
        (pd.Timestamp("1970-01-01T00:00:00.000000123Z"), 0),
        ("0001-01-01T00:00:00Z", -62_135_596_800_000_000_000),
        ("9999-12-31T23:59:59.999999Z", 253_402_300_799_999_999_000),
    ],
)
def test_native_clock_has_zero_difference_from_reviewed_witnesses(value, expected):
    # Literal outputs captured before replacing the bridge; a 1 ns rounding,
    # offset, or public-parser range change must fail these consumer witnesses.
    inputs, _ = api()
    assert inputs._ns(value) == expected
    assert inputs.timestamp(value) == datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
        microseconds=expected // 1000
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        0,
        "2026-11-06T14:30:00",
        "2026-11-06T14:30:00.1234567890Z",
        "1970-01-01T00:00:00.123456789+00:60",
        "1970-01-01 00:00:00.123456789-00:60",
        "1970-01-01T00:00:00+0060",
        "1970-01-01T00:00:00-0060",
        "1970-01-01T00:00:00+24:00",
        "1970-01-01T00:00:00-24:00",
        "1970-01-01T00:00:00+2400",
        "1970-01-01T00:00:00-2400",
        NOW.replace(tzinfo=None),
    ],
)
def test_native_clock_keeps_explicit_timezone_and_wire_precision_requirements(value):
    inputs, _ = api()
    with pytest.raises(inputs.InputError):
        inputs._ns(value)


@pytest.mark.parametrize("year", [1, 9999])
def test_unsupported_calendar_bounds_refuse_research_as_input_error(tmp_path: Path, year: int):
    inputs, _ = api()
    unit(tmp_path)
    now = datetime(year, 6, 15, 14, 30, tzinfo=UTC)
    for name in ("top100.json", "focus.json", "display-lists.json"):
        change(
            tmp_path,
            name,
            as_of_snapshot=now.isoformat(),
            as_of=now.isoformat(),
            generated_at=now.isoformat(),
        )
    with pytest.raises(inputs.InputError, match="No supported XNYS trading date for this input"):
        inputs.read_research_inputs(tmp_path, now=now)


def test_five_readback_rejections_are_tolerated_across_the_pair(tmp_path: Path):
    peer = Peer()
    rows = [member("AAPL"), *[member(f"U{n}") for n in range(5)]]
    peer.reject = {f"NASDAQ:U{n}" for n in range(5)}
    result = run_sync(unit(tmp_path, movers=rows, focus=[member("U0")]), peer)
    assert result["applied"] is True
    assert result["readback"]["NS movers"]["rejected"] == [
        "NASDAQ:U0",
        "NASDAQ:U1",
        "NASDAQ:U2",
        "NASDAQ:U3",
        "NASDAQ:U4",
    ]
    assert result["readback"]["NS focus"]["rejected"] == ["NASDAQ:U0"]


def test_sunday_overnight_unit_uses_monday_xnys_date(tmp_path: Path):
    inputs, _ = api()
    unit(tmp_path)
    clocks = {
        "as_of_snapshot": "2026-11-09T01:29:00+00:00",
        "as_of": "2026-11-09T01:29:10+00:00",
        "generated_at": "2026-11-09T01:29:30+00:00",
    }
    generation = {"as_of": clocks["as_of_snapshot"], "sha256": "a" * 64}
    context = {
        "session": "overnight",
        "session_date": "2026-11-09",
        "intraday_feed": "boats",
        "daily_history_feed": "sip",
        "daily_history_scope": "prior completed XNYS sessions; not BOATS intraday evidence",
    }
    for name in ("top100.json", "focus.json", "display-lists.json"):
        change(
            tmp_path,
            name,
            **clocks,
            session_date="2026-11-09",
            generation=generation,
            ranking_context=context,
            research_inputs={},
        )
    change(tmp_path, "display-lists.json", sources={"snapshot": generation, "armed_sets": []})
    data = inputs.read_research_inputs(tmp_path, now=datetime(2026, 11, 9, 1, 30, tzinfo=UTC))
    assert data.memberships["NS movers"] == frozenset({"NASDAQ:AAPL", "NASDAQ:MSFT"})


@pytest.fixture
def offline_owner_session(monkeypatch: pytest.MonkeyPatch):
    """Replace only callback/HTTP transport; keep the SDK Client task groups real."""
    from sextant.tradingview import auth

    class Callback:
        uri = "http://127.0.0.1:1/callback"
        result = None
        server = SimpleNamespace(server_close=lambda: None)

        async def redirect(self, _url):
            pytest.fail("No browser is authorized in this fixture")

        async def wait(self):
            pytest.fail("No OAuth callback is authorized in this fixture")

    monkeypatch.setattr(auth, "OwnerCallback", Callback)

    def connect(server):
        monkeypatch.setattr(auth, "streamable_http_client", lambda *args, **kwargs: server)
        return auth.official_client(authorize=True)

    return connect


@pytest.mark.parametrize(
    "failure,message",
    [("stubborn", "Readback mismatch"), ("ambiguous", "Ambiguous watchlist mutation")],
)
def test_owner_session_preserves_trusted_sync_errors(
    tmp_path: Path, offline_owner_session, failure, message
):
    inputs, sync = api()
    data = inputs.read_research_inputs(unit(tmp_path), now=NOW)
    peer = Peer()
    if failure == "stubborn":
        peer.extras, peer.stubborn = {"NYSE:EXTRA"}, True
    else:
        peer.ambiguous = True
    original = None

    async def run():
        nonlocal original
        with pytest.raises(sync.SyncError, match=message) as error:
            async with offline_owner_session(peer.server) as client:
                try:
                    await sync.sync_research(
                        sync.OfficialTools(client, interval=0, now=lambda: NOW), data, apply=True
                    )
                except sync.SyncError as exc:
                    original = exc
                    raise
        assert error.value is original

    asyncio.run(run())


@pytest.mark.parametrize("initial", [0, 55])
@pytest.mark.parametrize("first_exit", [0, 1])
@pytest.mark.parametrize("cancel_first", [False, True])
def test_overlapping_owner_sessions_restore_logging_only_after_last_exit(
    offline_owner_session, initial, first_exit, cancel_first, caplog
):
    import logging

    entered = [asyncio.Event(), asyncio.Event()]
    leave = [asyncio.Event(), asyncio.Event()]

    async def session(index):
        async with offline_owner_session(Peer().server):
            entered[index].set()
            await leave[index].wait()

    async def run():
        tasks = []
        try:
            for index in range(2):
                tasks.append(asyncio.create_task(session(index)))
                await entered[index].wait()
            assert logging.root.manager.disable == max(initial, logging.CRITICAL)
            if cancel_first:
                tasks[first_exit].cancel()
                with pytest.raises(asyncio.CancelledError):
                    await tasks[first_exit]
            else:
                leave[first_exit].set()
                await tasks[first_exit]
            assert logging.root.manager.disable == max(initial, logging.CRITICAL)
            logging.critical("overlapping session diagnostic must stay private")
            leave[1 - first_exit].set()
            await tasks[1 - first_exit]
            assert logging.root.manager.disable == initial
        finally:
            for event in leave:
                event.set()
            await asyncio.gather(*tasks, return_exceptions=True)

    previous = logging.root.manager.disable
    try:
        logging.disable(initial)
        asyncio.run(run())
        assert "overlapping session diagnostic" not in caplog.text
    finally:
        logging.disable(previous)


def test_owner_session_failure_never_emits_upstream_diagnostics(
    monkeypatch: pytest.MonkeyPatch, capsys
):
    import logging
    from types import SimpleNamespace

    from sextant.tradingview import auth
    from sextant.tradingview.sync import SyncError

    class Callback:
        uri = "http://127.0.0.1:1/callback"
        result = None
        server = SimpleNamespace(server_close=lambda: None)

        async def redirect(self, _url):
            pytest.fail("A browser is not needed in this failure fixture")

        async def wait(self):
            pytest.fail("A callback is not needed in this failure fixture")

    def refuse_transport(*args, **kwargs):
        logging.critical("fixture diagnostic must stay private")
        raise RuntimeError("fixture diagnostic must stay private")

    previous = logging.root.manager.disable
    monkeypatch.setattr(auth, "OwnerCallback", Callback)
    monkeypatch.setattr(auth, "streamable_http_client", refuse_transport)

    async def run():
        with pytest.raises(SyncError) as error:
            async with auth.official_client(authorize=True):
                pytest.fail("Fixture transport always refuses")
        assert error.value.__context__ is None
        assert error.value.__cause__ is None

    asyncio.run(run())
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert logging.root.manager.disable == previous


def test_owner_session_names_the_safe_class_and_stage_of_an_oauth_failure(
    monkeypatch: pytest.MonkeyPatch, capsys
):
    import asyncio
    from types import SimpleNamespace

    from mcp.client.auth.exceptions import OAuthTokenError

    from sextant.tradingview import auth
    from sextant.tradingview.sync import SyncError

    class Callback:
        uri = "http://127.0.0.1:1/callback"
        result = None
        server = SimpleNamespace(server_close=lambda: None)

        async def redirect(self, _url):
            pytest.fail("A browser is not needed in this failure fixture")

        async def wait(self):
            pytest.fail("A callback is not needed in this failure fixture")

    def refuse_transport(*args, **kwargs):
        raise OAuthTokenError(
            "Token exchange failed (400): access_token=SECRET https://example.invalid/?state=x"
        )

    monkeypatch.setattr(auth, "OwnerCallback", Callback)
    monkeypatch.setattr(auth, "streamable_http_client", refuse_transport)

    async def run():
        with pytest.raises(SyncError) as error:
            async with auth.official_client(authorize=True):
                pytest.fail("Fixture transport always refuses")
        assert error.value.label == "OAuthTokenError"
        assert error.value.stage == "token"
        assert error.value.detail == "HTTP 400 at token endpoint"
        assert "SECRET" not in str(error.value) and "example.invalid" not in str(error.value)
        assert error.value.__context__ is None
        assert error.value.__cause__ is None

    asyncio.run(run())
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_owner_callback_names_authorize_and_callback_refusals(monkeypatch: pytest.MonkeyPatch):
    import asyncio

    from sextant.tradingview import auth
    from sextant.tradingview.sync import SyncError

    monkeypatch.setattr(auth.webbrowser, "open", lambda _url: False)
    callback = auth.OwnerCallback()
    try:
        with pytest.raises(SyncError) as error:
            asyncio.run(callback.redirect("https://www.tradingview.com/mcp/oauth/authorize?ok=1"))
        assert error.value.stage == "authorize"
    finally:
        callback.server.server_close()

    callback = auth.OwnerCallback()
    try:
        callback.failed = True
        with pytest.raises(SyncError) as error:
            asyncio.run(callback.wait())
        assert error.value.stage == "callback"
    finally:
        callback.server.server_close()


def test_cli_stop_names_only_the_safe_class_and_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
):
    cli = importlib.import_module("sextant.tradingview.__main__")
    from sextant.tradingview.sync import SyncError

    def refuse(*args, **kwargs):
        raise SyncError(
            "TradingView session stopped; re-inventory before retry.",
            label="OAuthFlowError",
            stage="callback",
        )

    monkeypatch.setattr(cli, "read_research_inputs", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "official_client", refuse)
    assert cli.main(["--research-dir", str(tmp_path), "--authorize"]) == 2
    output = capsys.readouterr()
    assert "Safe diagnostic: OAuthFlowError at callback." in output.out
    assert "SECRET" not in output.out and "https://" not in output.out and output.err == ""
    assert "earlier writes" in output.out


def test_tool_discovery_names_the_tool_list_stage():
    import asyncio
    from types import SimpleNamespace

    from sextant.tradingview import sync

    class Silent:
        async def list_tools(self, *, cursor=None, cache_mode=None):
            return SimpleNamespace(
                tools=[SimpleNamespace(name="mcp-watchlist-list-watchlists", input_schema={})],
                next_cursor=None,
            )

    tools = sync.OfficialTools(Silent(), interval=0)  # type: ignore[arg-type]
    with pytest.raises(sync.SyncError) as error:
        asyncio.run(tools.discover())
    assert error.value.stage == "tool list"


def test_diagnostics_keeps_a_trusted_sync_stage_through_a_group():
    from sextant.tradingview import diagnostics, sync

    error = ExceptionGroup("sdk", [sync.SyncError("stop", stage="callback")])
    assert diagnostics.stage(error) == "callback"
    assert diagnostics.leaf_label(error) == "SyncError"


def test_diagnostics_names_http_status_and_endpoint_class():
    import httpx2

    from sextant.tradingview import diagnostics

    def status_error(status, path):
        request = httpx2.Request("POST", f"https://mcp.tradingview.com{path}")
        return httpx2.HTTPStatusError(
            "refused", request=request, response=httpx2.Response(status, request=request)
        )

    assert diagnostics.detail(status_error(400, "/mcp/oauth/token")) == "HTTP 400 at token endpoint"
    assert diagnostics.detail(status_error(401, "/mcp")) == "HTTP 401 at session endpoint"
    assert diagnostics.detail(ExceptionGroup("sdk", [status_error(503, "/mcp")])) == (
        "HTTP 503 at session endpoint"
    )


def test_diagnostics_names_only_the_oauth_error_vocabulary():
    from mcp.client.auth.exceptions import OAuthTokenError

    from sextant.tradingview import diagnostics

    known = OAuthTokenError(
        'Token exchange failed (400): {"error": "invalid_grant", "error_description": "SECRET"}'
    )
    assert diagnostics.detail(known) == "HTTP 400 at token endpoint; OAuth error invalid_grant"
    assert "SECRET" not in diagnostics.detail(known)
    unknown = OAuthTokenError('Token exchange failed (401): {"error": "made_up_code"}')
    assert "made_up_code" not in diagnostics.detail(unknown)
    assert "OAuth error" not in diagnostics.detail(unknown)


def test_diagnostics_names_pydantic_field_names_only():
    from pydantic import BaseModel, ValidationError

    from sextant.tradingview import diagnostics

    class Token(BaseModel):
        access_token: str
        token_type: str

    with pytest.raises(ValidationError) as error:
        Token.model_validate({"detail": "SECRET"})
    result = diagnostics.detail(error.value)
    assert result == "fields access_token, token_type"
    assert "SECRET" not in result


def test_tool_discovery_reports_the_name_diff():
    import asyncio
    from types import SimpleNamespace

    from sextant.tradingview import sync

    class Drifting:
        async def list_tools(self, *, cursor=None, cache_mode=None):
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(name="mcp-watchlist-list-watchlists", input_schema={}),
                    SimpleNamespace(name="mcp-watchlist-delete-watchlist", input_schema={}),
                ],
                next_cursor=None,
            )

    tools = sync.OfficialTools(Drifting(), interval=0)  # type: ignore[arg-type]
    with pytest.raises(sync.SyncError) as error:
        asyncio.run(tools.discover())
    assert error.value.stage == "tool list"
    assert "mcp-watchlist-delete-watchlist" in error.value.detail
    for name in (
        "mcp-watchlist-get-watchlist",
        "mcp-watchlist-create-watchlist",
        "mcp-watchlist-add-to-watchlist",
        "mcp-watchlist-remove-from-watchlist",
    ):
        assert name in error.value.detail


def test_cli_stop_prints_a_fixed_vocabulary_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
):
    cli = importlib.import_module("sextant.tradingview.__main__")
    from sextant.tradingview.sync import SyncError

    def refuse(*args, **kwargs):
        raise SyncError(
            "TradingView session stopped; re-inventory before retry.",
            label="OAuthTokenError",
            stage="token",
            detail="HTTP 400 at token endpoint; OAuth error invalid_grant",
        )

    monkeypatch.setattr(cli, "read_research_inputs", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "official_client", refuse)
    assert cli.main(["--research-dir", str(tmp_path), "--authorize"]) == 2
    output = capsys.readouterr()
    assert (
        "Safe diagnostic: OAuthTokenError at token "
        "(HTTP 400 at token endpoint; OAuth error invalid_grant)." in output.out
    )
    assert "SECRET" not in output.out and "https://" not in output.out


def test_cli_prints_each_fixed_sync_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    _, sync = api()
    cli = importlib.import_module("sextant.tradingview.__main__")
    monkeypatch.setattr(cli, "read_research_inputs", lambda *args, **kwargs: object())
    for message in sync.SAFE_STOP_MESSAGES:

        def refuse(*args, _message=message, **kwargs):
            raise sync.SyncError(_message, stage="tool list")

        monkeypatch.setattr(cli, "official_client", refuse)
        assert cli.main(["--research-dir", str(tmp_path), "--authorize"]) == 2
        output = capsys.readouterr()
        assert f"Safe diagnostic: SyncError at tool list: {message}" in output.out
        assert output.err == ""


def test_cli_withholds_a_message_outside_the_fixed_sync_literals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    cli = importlib.import_module("sextant.tradingview.__main__")
    from sextant.tradingview.sync import SyncError

    def refuse(*args, **kwargs):
        raise SyncError(
            "TradingView session stopped; SECRET-7f3a",
            label="OAuthFlowError",
            stage="callback",
        )

    monkeypatch.setattr(cli, "read_research_inputs", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "official_client", refuse)
    assert cli.main(["--research-dir", str(tmp_path), "--authorize"]) == 2
    output = capsys.readouterr()
    assert "Safe diagnostic: OAuthFlowError at callback." in output.out
    assert "TradingView session stopped" not in output.out
    assert "SECRET-7f3a" not in output.out
    assert output.err == ""


def test_same_owner_session_can_sync_another_cycle(tmp_path: Path):
    inputs, sync = api()
    data = inputs.read_research_inputs(unit(tmp_path), now=NOW)
    peer = Peer()

    async def run():
        async with Client(peer.server) as client:
            tools = sync.OfficialTools(client, interval=0, now=lambda: NOW)
            await sync.sync_research(tools, data, apply=True)
            return await sync.sync_research(tools, data, apply=True)

    result = asyncio.run(run())
    assert result["applied"] is True and result["operations"] == []


def test_oversize_parent_is_not_an_authoritative_top100(tmp_path: Path):
    inputs, _ = api()
    unit(tmp_path)
    change(tmp_path, "top100.json", candidates=[member(f"S{n}") for n in range(101)])
    with pytest.raises(inputs.InputError):
        inputs.read_research_inputs(tmp_path, now=NOW)


def test_ambiguous_create_identity_stops_before_creating_another_list(tmp_path: Path):
    _, sync = api()
    peer = Peer()
    del peer.lists["1"]
    del peer.lists["2"]
    peer.bad_create = True
    with pytest.raises(sync.SyncError):
        run_sync(unit(tmp_path), peer)
    assert [name for name, _ in peer.calls].count("create_watchlist") == 1


@pytest.mark.parametrize("response", ["header_mismatch", "input_required"])
def test_sdk_does_not_negotiate_and_resend_mutations(monkeypatch: pytest.MonkeyPatch, response):
    from mcp.shared.exceptions import MCPError
    from mcp_types import HEADER_MISMATCH, InputRequiredResult

    _, sync = api()
    peer = Peer()
    attempts = []

    async def run():
        async with Client(peer.server) as client:
            tools = sync.OfficialTools(client, interval=0, now=lambda: NOW)
            await tools.discover()

            async def rejected(*args, **kwargs):
                attempts.append(args)
                if response == "header_mismatch":
                    raise MCPError(code=HEADER_MISMATCH, message="fixture schema mismatch")
                return InputRequiredResult(input_requests={}, request_state="fixture")

            monkeypatch.setattr(client.session, "send_request", rejected)
            with pytest.raises(sync.SyncError):
                await tools.call("create_watchlist", {"name": "NS focus", "symbols": []})

    asyncio.run(run())
    assert len(attempts) == 1
    assert peer.calls == []
