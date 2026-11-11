"""Not-sent refusals versus sent-but-unresolved outcomes (E5 fix round).

alpaca-py cc4cb3b7 common/rest.py:197-210 (no raise on 2xx; response.json()),
requests' JSONDecodeError is a ValueError; NT d53849b reconciliation resolves a
sent command from the venue's later status, never from a local guess.
"""

import asyncio
from types import SimpleNamespace as NS

from .test_alpaca_client import client
from .test_alpaca_execution import order


def test_entry_refused_by_reserve_ends_rejected_before_wire():
    async def run():
        node = client()
        # Fixture rows: burst 18; nine positions each with a working sell need 19.
        node.gateway.position_counts = lambda: (9, 9)
        await node._submit_order(NS(order=order(), params={}))
        node.generate_order_rejected.assert_called_once()
        assert "refused before wire" in node.generate_order_rejected.call_args.args[1]
        assert not any(r[0] == "POST" for r in node.gateway.sdk.requests)
        assert not node._submissions

    asyncio.run(run())
