"""LEAD-0937 Part A: account guard proofs, offline with no symbol resolver."""

import asyncio
import fcntl
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from mcp.server import Server

from sextant.tradingview import account
from sextant.tradingview.account import (
    Account,
    AccountError,
    MeteredClient,
    MeteredDispatcher,
    main,
)

NOW = datetime(2026, 11, 11, 15, tzinfo=UTC)


def policy(value: int | None = 10, **changes):
    path = account.DEFAULT_PARAMETERS
    data = json.loads(path.read_text())
    data["rows"][0].update(value=value, **changes)
    path.write_text(json.dumps(data))
    return path


async def success():
    return {"ok": True}


@pytest.mark.parametrize("error", [AccountError("quota"), TimeoutError(), asyncio.CancelledError()])
def test_dispatched_failure_latches_across_restarts_days_and_clock_jumps(error):
    policy()
    calls = []

    async def fail():
        calls.append("sent")
        raise error

    with pytest.raises(type(error)):
        asyncio.run(Account(now=lambda: NOW).request(fail))
    for days in (1, 7, 365):
        later = Account(now=lambda days=days: NOW + timedelta(days=days))
        with pytest.raises(AccountError, match="latched"):
            asyncio.run(later.request(fail))
    assert calls == ["sent"]


def test_two_clients_share_cap_and_alternate_registry_cannot_reset_it(tmp_path):
    path = policy(2)
    assert asyncio.run(Account().request(success)) == {"ok": True}
    assert asyncio.run(Account().request(success)) == {"ok": True}
    with pytest.raises(AccountError, match="budget exhausted"):
        asyncio.run(Account().request(success))
    assert Account().snapshot()["calls"] == 2
    other = tmp_path / "other.params.json"
    other.write_bytes(path.read_bytes())
    with pytest.raises(AccountError, match="canonical"):
        Account(parameters=other)


@pytest.mark.parametrize("bad", [None, "truncated"])
def test_missing_or_corrupt_state_refuses_without_reset(tmp_path, bad):
    path = tmp_path / "state.json"
    if bad is None:
        path.unlink()
    else:
        path.write_text(bad)
    with pytest.raises(AccountError, match="state"):
        asyncio.run(Account().request(success))
    assert (path.read_text() if path.exists() else None) == bad


def test_concurrent_writer_and_regressing_day_cannot_reset_usage(tmp_path):
    asyncio.run(Account().request(success))
    before = (tmp_path / "state.json").read_bytes()
    with (tmp_path / "state.json.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(AccountError, match="writer"):
            Account().preflight()
    with pytest.raises(AccountError, match="clock"):
        Account(now=lambda: NOW - timedelta(days=1)).preflight()
    assert (tmp_path / "state.json").read_bytes() == before


@pytest.mark.parametrize(
    "changes",
    [
        {"value": None},
        {"value": True},
        {"value": 2.5},
        {"value": 0},
        {"source": ""},
        {"calibration_state": "MEASURED"},
        {"calibration_state": "FIXED"},
        {"unit": "seconds"},
    ],
)
def test_invalid_or_unavailable_budget_refuses_before_dispatch(changes):
    policy(**changes)
    with pytest.raises(AccountError):
        asyncio.run(Account().request(success))
    assert Account().snapshot()["calls"] == 0


@pytest.mark.parametrize("spacing", [None, 0.75, 1.5])
def test_spacing_requires_authority_slower_than_both_failed_incident_runs(spacing):
    data = json.loads(account.DEFAULT_PARAMETERS.read_text())
    data["rows"][2]["value"] = spacing
    account.DEFAULT_PARAMETERS.write_text(json.dumps(data))
    with pytest.raises(AccountError):
        asyncio.run(Account().request(success))
    assert Account().snapshot()["calls"] == 0


def test_named_lead_clear_is_audited_and_preserves_usage_and_spacing():
    policy()

    async def fail():
        raise AccountError("quota")

    with pytest.raises(AccountError):
        asyncio.run(Account(now=lambda: NOW).request(fail))
    before = Account().snapshot()
    item = Account(now=lambda: NOW)
    item.clear(lead="fixture lead", authority="offline reviewed clear")
    state = item.snapshot()
    assert state["calls"] == before["calls"] == 1
    assert state["last_call"] == before["last_call"]
    assert state["audit"][-1] == {
        "action": "clear",
        "lead": "fixture lead",
        "authority": "offline reviewed clear",
        "at": NOW.isoformat(),
    }
    assert asyncio.run(Account().request(success)) == {"ok": True}


def test_explicit_init_stays_latched_and_refuses_existing_state(tmp_path):
    (tmp_path / "state.json").unlink()
    args = ["--lead", "fixture lead", "--authority", "offline init"]
    assert main(["init", *args]) == 0
    with pytest.raises(AccountError, match="latched"):
        Account().preflight()
    assert main(["init", *args]) == 2
    assert main(["clear", "--lead", "", "--authority", "offline clear"]) == 2
    assert main(["clear", *args]) == 0
    Account().preflight()
    assert [r["action"] for r in Account().snapshot()["audit"]] == ["init", "clear"]


def test_sdk_setup_and_notification_consume_cap_before_tool_discovery():
    policy(2)

    async def exercise():
        async with MeteredClient(Server("offline"), mode="legacy") as client:
            assert Account().snapshot()["calls"] == 2
            with pytest.raises(AccountError, match="budget exhausted"):
                await client.list_tools(cache_mode="refresh")

    asyncio.run(exercise())
    assert Account().snapshot()["calls"] == 2


def test_latched_sdk_client_never_opens_transport(tmp_path):
    state = Account().snapshot()
    state["quota_stop"] = True
    (tmp_path / "state.json").write_text(json.dumps(state))
    entered = []

    @asynccontextmanager
    async def lifespan(server):
        entered.append(True)
        yield {}

    async def exercise():
        with pytest.raises(AccountError, match="latched"):
            async with MeteredClient(Server("offline", lifespan=lifespan), mode="legacy"):
                pytest.fail("latched client opened")

    asyncio.run(exercise())
    assert entered == []


@pytest.mark.parametrize(("method", "status"), [("POST", 405), ("GET", 429), ("DELETE", 403)])
def test_optional_endpoint_exception_does_not_accept_other_refusals(method, status):
    import httpx2

    gate = account.HTTPGate()
    request = httpx2.Request(method, "https://offline.invalid/mcp")

    async def exercise():
        await gate.request(request)
        with pytest.raises(AccountError, match="stop latched"):
            await gate.response(httpx2.Response(status, request=request))

    asyncio.run(exercise())
    assert Account().snapshot()["calls"] == 1
    with pytest.raises(AccountError, match="latched"):
        Account().preflight()


@pytest.mark.parametrize("field", ["inputSchema", "outputSchema"])
def test_tool_schema_error_property_is_metadata_not_a_quota_answer(field):
    result = {
        "tools": [
            {
                "name": "offline",
                "inputSchema": {"type": "object"},
                field: {"type": "object", "properties": {"error": {"type": "string"}}},
            }
        ]
    }

    class Upstream:
        async def send_raw_request(self, *args):
            return result

    assert (
        asyncio.run(MeteredDispatcher(Upstream(), Account()).send_raw_request("tools/list", {}))
        == result
    )
    assert Account().snapshot()["quota_stop"] is False
    Account().preflight()


@pytest.fixture
def attended_registry(tmp_path, monkeypatch):
    """Use shipped authority unchanged; isolate only the durable state location."""
    shipped = Path(__file__).resolve().parents[2] / "lanes/tradingview/account.params.json"
    data = json.loads(shipped.read_text())
    for row in data["rows"]:
        if row["name"] == "account_state_path":
            row["value"] = str(tmp_path / "state.json")
    path = tmp_path / "attended.params.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(account, "DEFAULT_PARAMETERS", path)
    return data


def test_attended_registry_stops_before_request_183(attended_registry):
    async def exercise():
        item = Account()
        for _ in range(182):
            await item.request(success)
        with pytest.raises(AccountError, match="budget exhausted"):
            await item.request(success)
        assert item.snapshot()["calls"] == 182

    asyncio.run(exercise())


def test_attended_registry_spaces_requests_six_seconds_across_clients(attended_registry):
    asyncio.run(Account().request(success))
    first = datetime.fromisoformat(Account().snapshot()["last_call"])
    asyncio.run(Account().request(success))
    second = datetime.fromisoformat(Account().snapshot()["last_call"])
    assert second - first == timedelta(seconds=6)


def test_attended_registry_uses_sourced_sdk_timeout(attended_registry):
    assert Account().timeout() == 30


def test_attended_registry_records_uncalibrated_authority(attended_registry):
    for row in attended_registry["rows"]:
        if row["name"] == "account_state_path":
            continue
        assert row["calibration_state"] == "UNCALIBRATED"
        assert row["last_change"] == "2026-11-11"
        for source in (
            "LEAD-1614",
            "7e92258392599bd6b3e6295c58327de88199150c503c8cf113561450ccbddec0",
            "https://www.tradingview.com/mcp/docs",
            "read 2026-11-11",
            "REQUEST-NEED.md",
            "f4d025e77dfc5fb9aa7385a17bda3dc59ea8b0447e1f5e094c121dfb4a5d1409",
        ):
            assert source in row["source"]
