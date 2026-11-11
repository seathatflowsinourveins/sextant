"""One command resolves exactly once, whichever authoritative answer comes first (E5 u10).

Review e5r3-99ac5bf P2: a read, a stream event or the venue's response settles the live
command it answers; a later answer for the same command emits nothing and is counted.
"""

import asyncio
import threading
from types import SimpleNamespace as NS
from typing import Any, cast

from nautilus_trader.model import ClientOrderId

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
