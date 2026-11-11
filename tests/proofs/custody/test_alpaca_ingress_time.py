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

from nautilus_trader.model import ClientOrderId, OrderStatus

from .test_alpaca_client import client
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


# One RED witness per r5 fix (each fails on the r4 client).


def test_a_cancel_refusal_a_read_emitted_is_not_emitted_again():
    async def run():
        node = client()
        await node._submit_order(NS(order=order(), params={}))
        venue = node.gateway.sdk
        row = next(iter(venue.rows.values()))
        node.cache.order.return_value = order(status=OrderStatus.PENDING_CANCEL)
        venue.delete = lambda path, body: venue.requests.append(("DELETE", path, {}))
        await node._cancel_order(_cmd("cancel"))  # an attempt; the order keeps working
        await node._generate_order_status_report(
            NS(client_order_id=ClientOrderId("fixture-entry"), venue_order_id=None)
        )  # the read finds it working and refuses the cancel
        await node._on_trade_update(_event("order_cancel_rejected", row))
        node.generate_order_cancel_rejected.assert_called_once()

    asyncio.run(run())
