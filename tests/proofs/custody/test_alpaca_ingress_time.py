"""T2 in time (E5 r5, review e5r4-266edf5): safety facts before the first await.

Every safety fact an event carries is recorded synchronously on arrival, keyed by the venue
order id the raw event names, before the first await: executing (a SELL's fill, partial fill
or stop), terminal (no cancel can still act), refused (the venue answered the mutation).
Lineage work afterwards only adds the stable binding. Every value read before an await is
re-validated after it. One proof per await; the list is EXIT-TABLE-r5.md.
"""

import asyncio
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from nautilus_trader.model import ClientOrderId, Money, OrderSide, OrderStatus, Quantity

from .test_alpaca_client import client, client_module
from .test_alpaca_execution import order
from .test_alpaca_exits import _cmd

EXECUTING = ["partial_fill", "stopped"]


def _event(event, row):
    row = deepcopy(row) | {"status": "partially_filled" if event == "partial_fill" else event}
    data = {"event": event, "order": row, "timestamp": row["updated_at"]}
    if event in ("fill", "partial_fill"):
        row.update(filled_qty="1", filled_avg_price="0.1234")
        data |= {"execution_id": f"fixture-{event}", "price": "0.1234", "qty": "1"}
    return {"stream": "trade_updates", "data": data}


async def _sell(node):
    native = order(side=OrderSide.SELL, is_sell=True, filled_qty=Quantity.from_str("0"))
    node.cache.order.return_value = native
    node.commission_for_fill = lambda data: Money.from_str("0 USD")
    await node._submit_order(NS(order=native, params={}))
    return next(iter(node.gateway.sdk.rows.values()))


def _hold(node, path):
    """Pause the first GET of path; return (entered, release)."""
    entered, release, call = asyncio.Event(), asyncio.Event(), node._call

    async def held(kind, method, where, data=None, **kwargs):
        if method == "get" and where == path and not entered.is_set():
            entered.set()
            await release.wait()
        return await call(kind, method, where, data, **kwargs)

    node._call = held
    return entered, release


async def _successor(node, *, sell=True):
    """A confirmed, bound successor of a house order; returns its row."""
    if sell:
        await _sell(node)
    else:
        await node._submit_order(NS(order=order(), params={}))
    await node._modify_order(_cmd("modify"))
    row = node.gateway.sdk.confirm()
    await node._on_trade_update(_event("new", row) | {})
    return row


def test_an_executing_successor_is_fenced_before_its_parent_read():
    async def run():
        node = client()
        row = await _successor(node)
        entered, release = _hold(node, f"/orders/{row['replaces']}")
        task = asyncio.create_task(node._on_trade_update(_event("partial_fill", row)))
        await asyncio.wait_for(entered.wait(), 1)
        assert row["id"] in node._executing  # before the await, not after it
        release.set()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_a_newer_binding_made_during_an_older_parent_read_stands():
    async def run():
        node = client()
        await node._submit_order(NS(order=order(), params={}))
        venue, chain = node.gateway.sdk, []
        parent = next(iter(venue.rows.values()))
        for number in (1, 2, 3):
            venue.patch(f"/orders/{parent['id']}", {"client_order_id": f"fixture-entry-r{number}"})
            parent = venue.confirm()
            chain.append(deepcopy(parent))
        for memory in (node._active, node._roots, node._active_n):  # a cold restart
            memory.clear()
        entered, release = _hold(node, f"/orders/{chain[0]['replaces']}")
        older = asyncio.create_task(node._report(chain[0]))
        await asyncio.wait_for(entered.wait(), 1)
        await node._report(chain[2])
        release.set()
        await older
        assert node._active["fixture-entry"] == chain[2]["id"]

    asyncio.run(run())


def test_a_held_successor_fill_is_released_exactly_once_on_confirmation():
    async def run():
        node = client()
        await node._submit_order(NS(order=order(), params={}))
        node.commission_for_fill = lambda data: Money.from_str("0 USD")
        await node._modify_order(_cmd("modify"))
        fill = _event("partial_fill", node.gateway.sdk.pending[1])
        with pytest.raises(client_module().IncompleteCoverage):
            await node._on_trade_update(fill)  # lineage not yet confirmed: held
        confirmed = node.gateway.sdk.confirm()
        await node._on_trade_update(_event("new", confirmed))  # confirmation releases it

        def fills():
            calls = node._handle_report.call_args_list
            return [str(c.args[0].client_order_id) for c in calls if hasattr(c.args[0], "trade_id")]

        assert fills() == ["fixture-entry"]
        await node._on_trade_update(fill)  # a replay is not forwarded again
        assert fills() == ["fixture-entry"]

    asyncio.run(run())


def test_a_replace_refusal_a_read_emitted_is_not_emitted_again():
    async def run():
        node = client()
        await node._submit_order(NS(order=order(), params={}))
        row = next(iter(node.gateway.sdk.rows.values()))
        node.cache.order.return_value = order(status=OrderStatus.PENDING_UPDATE)
        node.gateway.sdk.patch = lambda path, body: node.gateway.sdk.requests.append(("PATCH",))
        await node._modify_order(_cmd("modify"))
        await node._generate_order_status_report(
            NS(client_order_id=ClientOrderId("fixture-entry"), venue_order_id=None)
        )  # the read finds the order unchanged and refuses the modify
        await node._on_trade_update(_event("order_replace_rejected", row | {"status": "new"}))
        node.generate_order_modify_rejected.assert_called_once()

    asyncio.run(run())
