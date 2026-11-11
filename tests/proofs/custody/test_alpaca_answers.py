"""One command resolves exactly once, whichever authoritative answer comes first (E5 u10).

Review e5r3-99ac5bf P2: a read, a stream event or the venue's response settles the live
command it answers; a later answer for the same command emits nothing and is counted.
"""

import asyncio
import threading
from types import SimpleNamespace as NS
from typing import Any, cast

from nautilus_trader.model import ClientOrderId, OrderStatus

from .test_alpaca_client import client
from .test_alpaca_execution import order
from .test_alpaca_exits import HOOK, METHOD, _api, _cmd


def _held_then_422(venue, kind, *, applied):
    entered, release = threading.Event(), threading.Event()
    original = getattr(venue, METHOD[kind])

    def held(path, body):
        if applied:
            original(path, body)  # The venue holds the order while the reply is pending.
        else:
            venue.requests.append((METHOD[kind].upper(), path, dict(body or {})))
        entered.set()
        release.wait(2)
        raise _api(422)

    setattr(venue, METHOD[kind], held)
    return entered, release


async def _first_answer_then_422(kind, answer):
    node = client()
    if kind != "submit":
        await node._submit_order(NS(order=order(), params={}))
    node.generate_order_rejected.reset_mock()
    venue = node.gateway.sdk
    entered, release = _held_then_422(venue, kind, applied=kind == "submit")
    await HOOK[kind](node, cast(Any, _cmd(kind)))
    (task,) = [t for t in node._actions if not t.done()]
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        await answer(node)
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    finally:
        release.set()
    return node


def test_a_submit_the_venue_already_shows_is_not_rejected_by_a_late_422():
    async def run():
        async def read(node):
            report = await node._generate_order_status_report(
                NS(client_order_id=ClientOrderId("fixture-next"), venue_order_id=None)
            )
            assert report is not None

        node = await _first_answer_then_422("submit", read)
        node.generate_order_rejected.assert_not_called()
        assert node.late_answers == 1

    asyncio.run(run())


def test_a_cancel_the_stream_refused_is_not_rejected_again_by_a_late_422():
    async def run():
        async def stream(node):
            row = next(iter(node.gateway.sdk.rows.values()))
            await node._on_trade_update(
                {
                    "stream": "trade_updates",
                    "data": {
                        "event": "order_cancel_rejected",
                        "order": row,
                        "timestamp": row["updated_at"],
                    },
                }
            )
            node.generate_order_cancel_rejected.assert_called_once()

        node = await _first_answer_then_422("cancel", stream)
        node.generate_order_cancel_rejected.assert_called_once()
        assert node.late_answers == 1

    asyncio.run(run())


# PR 569 gate review: answers belong to one command attempt, never to (kind, order).
QUERY = NS(client_order_id=ClientOrderId("fixture-entry"), venue_order_id=None)


def _event(event, row):
    data = {"event": event, "order": row, "timestamp": row["updated_at"]}
    return {"stream": "trade_updates", "data": data}


async def _working(node):
    await node._submit_order(NS(order=order(), params={}))
    venue = node.gateway.sdk
    node.cache.order.return_value = order(status=OrderStatus.PENDING_CANCEL)
    venue.delete = lambda path, body: venue.requests.append(("DELETE", path, {}))  # 204
    return next(iter(venue.rows.values()))


async def _sent(node):
    await HOOK["cancel"](node, cast(Any, _cmd("cancel")))
    await asyncio.gather(*tuple(node._actions))  # the DELETE is on the wire


def test_a_retried_cancel_is_refused_on_its_own_answer():
    async def run():
        node = client()
        row = await _working(node)
        await _sent(node)
        await node._generate_order_status_report(QUERY)  # still working: attempt 1 refused
        await node._on_trade_update(_event("order_cancel_rejected", row))  # 1's, late
        await _sent(node)  # attempt 2
        await node._on_trade_update(_event("order_cancel_rejected", row))
        assert node.generate_order_cancel_rejected.call_count == 2 and not node._cancels

    asyncio.run(run())


def test_a_read_issued_before_a_delete_never_answers_it():
    async def run():
        node = client()
        row = await _working(node)
        entered, release, call = asyncio.Event(), asyncio.Event(), node._call

        async def late(kind, method, path, data=None, **kwargs):
            if method == "get" and not entered.is_set():
                entered.set()
                await release.wait()
            return await call(kind, method, path, data, **kwargs)

        node._call = late
        read = asyncio.create_task(node._generate_order_status_report(QUERY))
        await asyncio.wait_for(entered.wait(), 1)
        await _sent(node)  # its DELETE is newer than the read
        release.set()
        await read
        node.generate_order_cancel_rejected.assert_not_called()
        assert node._cancels == {row["id"]}

    asyncio.run(run())


def test_a_late_422_after_a_terminal_event_refuses_nothing():
    async def run():
        async def canceled(node):
            row = next(iter(node.gateway.sdk.rows.values()))
            await node._on_trade_update(_event("canceled", row | {"status": "canceled"}))

        node = await _first_answer_then_422("cancel", canceled)
        node.generate_order_cancel_rejected.assert_not_called()

    asyncio.run(run())
