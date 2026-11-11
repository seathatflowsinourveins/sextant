"""Stage 1 start 1 (FAILED-START-1.md): a failed startup reconciliation names its cause.

The engine's composer runs the three report generators under try_join and returns the first
error (nautilus d53849b2 crates/common/src/clients/execution.rs:543-561). The node logs only the
outer context, "Failed to get mass status from ALPACA" (crates/live/src/python/node.rs:676), so
the client records, per stage, its request and row counts and the first failure's class, HTTP
status and reason text, and the node writes them to the receipt and the unit output. No value
(symbol, price, quantity, order id, account id, key) is recorded.
"""

import asyncio
import json
from types import SimpleNamespace as NS

import pytest

from .test_alpaca_client import client, client_module
from .test_alpaca_execution import order
from .test_alpaca_exits import _api
from .test_b_order_node import AccountVenue, expected, start  # noqa: F401 - autouse fixture

SCOPE = NS(open_only=False, instrument_id=None, start=None, end=None)
STRAY = {"id": "x::1", "order_id": "00000000-0000-0000-0000-000000000999", "cum_qty": "1"}


def _values(node):
    """Every value the fixture venue holds that the trace must never carry."""
    rows = [*node.gateway.sdk.rows.values(), *node.gateway.sdk.activities]
    return {str(v) for row in rows for k, v in row.items() if k in ("id", "symbol", "order_id")}


def test_an_unexplained_fill_names_its_stage_counts_and_reason():
    async def run():
        node = client()
        await node._submit_order(NS(order=order(), params={}))
        node.gateway.sdk.activities = [dict(STRAY, symbol="TEST", price="0.1234", qty="1")]
        with pytest.raises(client_module().IncompleteCoverage):
            await node._generate_fill_reports(SCOPE)
        fills = node.report_trace["fills"]
        assert fills["error"] == "IncompleteCoverage" and fills["first"] == "ValueError"
        assert fills["reason"] == "historical fill that no order report explains"
        assert fills["failures"] == 1 and fills["status"] is None
        assert fills["requests"]["/account/activities/FILL"] == {"requests": 1, "rows": 1}
        assert fills["requests"]["/orders"] == {"requests": 1, "rows": 1}
        text = json.dumps(node.report_trace)
        assert not any(value in text for value in _values(node)) and "0.1234" not in text

    asyncio.run(run())


@pytest.mark.parametrize("status", [429, 500])
def test_an_http_failure_names_its_status_and_no_body(status):
    async def run():
        node = client()

        def refused(path, params):
            raise _api(status)

        node.gateway.sdk.get = refused
        with pytest.raises(client_module().APIError):
            await node._generate_position_status_reports(SCOPE)
        positions = node.report_trace["positions"]
        assert (positions["error"], positions["status"]) == ("APIError", status)
        assert positions["reason"] is None  # A venue body is never copied.
        assert positions["requests"]["/positions"] == {"requests": 1, "rows": 0}

    asyncio.run(run())


def test_a_failed_start_writes_the_cause_to_the_receipt_and_one_error_line(tmp_path, capfd):
    venue = AccountVenue()
    venue.activities = [dict(STRAY, symbol="ZA")]
    body, code, _ = start(tmp_path, venue)
    assert (code, body["phase"]) == (2, "failed")
    cause = body["reconciliation"]
    assert cause["fills"]["reason"] == "historical fill that no order report explains"
    assert cause["fills"]["requests"]["/account/activities/FILL"]["rows"] == 1
    err = capfd.readouterr().err
    (line,) = [x for x in err.splitlines() if "startup reconciliation failed" in x]
    assert line.startswith("order node ERROR") and "stage=fills" in line
    assert "IncompleteCoverage" in line and STRAY["order_id"] not in line + json.dumps(body)
