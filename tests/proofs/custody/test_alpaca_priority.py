"""Keep the native FIFO bounded while the account gateway owns wire priority.

NT d53849b python_adapters.md:167-174 and AX execution.rs command spawn_task.
"""

import asyncio
import threading
from types import SimpleNamespace as NS
from typing import Any, cast

from sextant.alpaca.execution import AlpacaExecutionClient

from .test_alpaca_client import client
from .test_alpaca_execution import order


def test_disconnect_cancels_and_awaits_in_flight_command_tasks():
    # execution.py _disconnect: cancel then gather owned command tasks (AX shutdown).
    async def run():
        node = client()
        node.gateway.pacer.bucket.tokens = 0
        queued = asyncio.Event()
        request = node.gateway.pacer.request

        def record_queue(*args, **kwargs):
            result = request(*args, **kwargs)
            queued.set()
            return result

        node.gateway.pacer.request = record_queue
        await AlpacaExecutionClient._submit_order(node, cast(Any, NS(order=order(), params={})))
        await asyncio.wait_for(queued.wait(), 1)
        (task,) = tuple(node._actions)
        await asyncio.wait_for(node._disconnect(), 1)
        assert task.done() and task.cancelled()
        assert not node._actions
        node.gateway.pacer.bucket.tokens = node.gateway.pacer.bucket.burst
        node.gateway.pacer.drain()
        await asyncio.sleep(0)
        assert not node.gateway.sdk.requests

    asyncio.run(run())


def test_disconnect_rejects_a_queued_entry_with_positive_not_sent_evidence():
    async def run():
        node = client()
        node.gateway.pacer.bucket.tokens = 0
        queued = asyncio.Event()
        request = node.gateway.pacer.request

        def record_queue(*args, **kwargs):
            result = request(*args, **kwargs)
            queued.set()
            return result

        node.gateway.pacer.request = record_queue
        entry = order()
        await AlpacaExecutionClient._submit_order(node, cast(Any, NS(order=entry, params={})))
        await asyncio.wait_for(queued.wait(), 1)
        await asyncio.wait_for(node._disconnect(), 1)
        node.generate_order_rejected.assert_called_once()
        rejected, reason = node.generate_order_rejected.call_args.args[:2]
        assert rejected is entry and "not sent" in reason
        node.gateway.pacer.bucket.tokens = node.gateway.pacer.bucket.burst
        node.gateway.pacer.drain()
        await asyncio.sleep(0)
        assert not node.gateway.sdk.requests and not node.gateway.pacer.wire_requests

    asyncio.run(run())


def test_disconnect_leaves_a_sent_entry_for_reconciliation():
    async def run():
        node = client()
        started, release = threading.Event(), threading.Event()
        post = node.gateway.sdk.post

        def slow_post(path, body):
            started.set()
            release.wait(1)
            return post(path, body)

        node.gateway.sdk.post = slow_post
        await AlpacaExecutionClient._submit_order(node, cast(Any, NS(order=order(), params={})))
        await asyncio.to_thread(started.wait, 1)
        disconnect = asyncio.create_task(node._disconnect())
        await asyncio.sleep(0.05)
        release.set()
        await asyncio.wait_for(disconnect, 2)
        node.generate_order_rejected.assert_not_called()

    asyncio.run(run())
