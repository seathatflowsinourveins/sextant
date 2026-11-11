"""Not-sent refusals versus sent-but-unresolved outcomes (E5 fix round).

alpaca-py cc4cb3b7 common/rest.py:197-210 (no raise on 2xx; response.json()),
requests' JSONDecodeError is a ValueError; NT d53849b reconciliation resolves a
sent command from the venue's later status, never from a local guess.
"""

import asyncio
from types import SimpleNamespace as NS

import pytest

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


class _OddFailure(Exception):
    """Any exception family the SDK or a transport could let through after send."""


def _requests_failure(kind):
    import requests

    return {
        "connection": lambda: requests.ConnectionError("fixture reset after send"),
        "timeout": lambda: requests.Timeout("fixture read timeout after send"),
        "chunked": lambda: requests.exceptions.ChunkedEncodingError("fixture broken body"),
        "other": lambda: _OddFailure("fixture failure of no known family"),
    }[kind]()


ANY_FAILURE = ["connection", "timeout", "chunked", "other"]


def _lose(venue, method, error):
    def lost(path, body):
        venue.requests.append((method.upper(), path, dict(body or {})))  # Sent, not applied.
        raise error

    setattr(venue, method, lost)


@pytest.mark.parametrize("kind", ANY_FAILURE)
def test_sent_post_lost_to_any_failure_stays_unresolved(kind):
    async def run():
        node = client()
        error = _requests_failure(kind)
        _lose(node.gateway.sdk, "post", error)
        with pytest.raises(type(error)):
            await node._submit_order(NS(order=order(), params={}))
        node.generate_order_rejected.assert_not_called()
        assert [r[0] for r in node.gateway.sdk.requests] == ["POST"]

    asyncio.run(run())
