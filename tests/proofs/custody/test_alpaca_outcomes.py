"""Not-sent refusals versus sent-but-unresolved outcomes (E5 fix round).

alpaca-py cc4cb3b7 common/rest.py:197-210 (no raise on 2xx; response.json()),
requests' JSONDecodeError is a ValueError; NT d53849b reconciliation resolves a
sent command from the venue's later status, never from a local guess.
"""

import asyncio
from types import SimpleNamespace as NS

import pytest
from nautilus_trader.model import ClientOrderId

from .test_alpaca_client import client
from .test_alpaca_execution import command, order


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


def _server_error():
    import requests
    from alpaca.common.exceptions import APIError

    response = requests.Response()
    response.status_code = 500
    return APIError(
        '{"code": 50010000, "message": "fixture"}', requests.HTTPError(response=response)
    )


def _malformed_body():
    import requests

    # rest.py:209-210 calls response.json() on a nonempty 2xx body.
    return requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0)


def _transport_error():
    import requests

    return requests.ConnectionError("fixture connection reset after send")


SENT_FAILURES = [
    pytest.param(_malformed_body, id="malformed-2xx"),
    pytest.param(_server_error, id="5xx"),
    pytest.param(_transport_error, id="transport"),
]


def _applied_then(venue, method, error):
    original = getattr(venue, method)

    def call(path, body):
        original(path, body)  # The venue applied it; only the reply is lost.
        raise error

    setattr(venue, method, call)


@pytest.mark.parametrize("failure", SENT_FAILURES)
def test_sent_cancel_with_lost_reply_stays_unresolved_never_rejected(failure):
    async def run():
        node = client()
        await node._submit_order(NS(order=order(), params={}))
        venue = node.gateway.sdk
        error = failure()
        _applied_then(venue, "delete", error)
        with pytest.raises(type(error)):
            await node._cancel_order(
                command(client_order_id=ClientOrderId("fixture-entry"), venue_order_id=None)
            )
        assert [r[0] for r in venue.requests].count("DELETE") == 1
        node.generate_order_cancel_rejected.assert_not_called()
        node.generate_order_canceled.assert_not_called()

    asyncio.run(run())


@pytest.mark.parametrize("applied", [False, True])
def test_read_returns_a_working_order_to_its_venue_state_after_a_lost_delete(applied):
    async def run():
        from nautilus_trader.model import OrderStatus

        node = client()
        await node._submit_order(NS(order=order(), params={}))
        venue = node.gateway.sdk
        delete = venue.delete

        def answer_5xx(path, body):
            if applied:
                delete(path, body)
            else:
                venue.requests.append(("DELETE", path, dict(body or {})))
            raise _server_error()

        venue.delete = answer_5xx
        with pytest.raises(type(_server_error())):
            await node._cancel_order(
                command(client_order_id=ClientOrderId("fixture-entry"), venue_order_id=None)
            )
        node.cache.order.return_value = order(status=OrderStatus.PENDING_CANCEL)
        await node._generate_order_status_report(
            NS(client_order_id=ClientOrderId("fixture-entry"), venue_order_id=None)
        )
        assert node.generate_order_cancel_rejected.called is not applied
        assert not node._cancels

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
def test_sent_delete_lost_to_any_failure_is_restored_by_the_next_read(kind):
    # Review e5fix-2a7d367 P1: a transport-lost DELETE left the order locally CANCELED.
    async def run():
        from nautilus_trader.model import OrderStatus

        node = client()
        await node._submit_order(NS(order=order(), params={}))
        venue = node.gateway.sdk
        error = _requests_failure(kind)
        _lose(venue, "delete", error)
        with pytest.raises(type(error)):
            await node._cancel_order(
                command(client_order_id=ClientOrderId("fixture-entry"), venue_order_id=None)
            )
        node.generate_order_cancel_rejected.assert_not_called()
        node.cache.order.return_value = order(status=OrderStatus.PENDING_CANCEL)
        await node._generate_order_status_report(
            NS(client_order_id=ClientOrderId("fixture-entry"), venue_order_id=None)
        )
        assert next(iter(venue.rows.values()))["status"] == "new"
        node.generate_order_cancel_rejected.assert_called_once()

    asyncio.run(run())


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


async def _gateway_gone(node):
    await node._submit_order(NS(order=order(), params={}))
    node.generate_order_rejected.reset_mock()
    node.gateway = None  # _call raises RuntimeError before any request.


@pytest.mark.parametrize("hook", ["cancel", "submit"])
def test_a_failure_before_the_wire_is_a_local_refusal_whatever_its_type(hook):
    # Positive not-sent evidence: the gateway's on-wire token never fired.
    async def run():
        node = client()
        await _gateway_gone(node)
        if hook == "cancel":
            await node._cancel_order(
                command(client_order_id=ClientOrderId("fixture-entry"), venue_order_id=None)
            )
            node.generate_order_cancel_rejected.assert_called_once()
        else:
            await node._submit_order(
                NS(order=order(client_order_id=ClientOrderId("fixture-next")), params={})
            )
            node.generate_order_rejected.assert_called_once()

    asyncio.run(run())
