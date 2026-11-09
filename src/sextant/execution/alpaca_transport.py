"""Paper-only HTTP transport for the offline Alpaca bridge.

Shape and error handling: northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:
``nautilus_alpaca/{execution,http}.py``. Its REST caller is synchronous ``requests``, hands
every call through the account pacer, and turns a network failure into an unknown outcome
rather than a raise. The official Create an Order reference (read 2026-11-09) supplies the
``id`` in a 2xx reply. ``requests`` 2.34.2 at
6e83187b8feb273ed4c6cdab5efd8d54901dfab3 supplies ``Session.request``, ``timeout`` and
``RequestException``.

One transport call is one HTTP request: ``wire()`` runs exactly once immediately before it,
and the account pacer owns every retry. Redirects are not followed, so a 3xx is an unknown
outcome rather than a second request. A request path must be root-relative and may not carry
``@``, a leading ``//`` or a backslash, and the built URL is re-parsed to keep the paper host.
Only ``PAPER_HOST`` is reachable by construction, so no call here can reach the live venue.
HTTP and network answers become ``Outcome`` values, never exceptions, and no message carries
the key, the secret or the order body.
"""

from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

import requests

from sextant.execution.alpaca import Outcome, WireRequest
from sextant.execution.pacer import ActionKind

PAPER_HOST = "https://paper-api.alpaca.markets"
_PAPER_HOSTNAME = "paper-api.alpaca.markets"


def _paper_base_url(base_url: str) -> str:
    """Accept only the paper root; no other host is reachable by construction."""
    if not isinstance(base_url, str):
        raise ValueError("base_url must be a string")
    try:
        parts = urlsplit(base_url)
        # A malformed port raises here, before any request could exist.
        parts.port  # noqa: B018
    except ValueError:
        raise ValueError("base_url must be a valid https URL") from None
    if parts.scheme != "https":
        raise ValueError("the Alpaca transport is paper-only and requires https")
    if base_url != PAPER_HOST:
        raise ValueError("the Alpaca transport is paper-only; only PAPER_HOST is accepted")
    return base_url


def _request_url(path: str) -> str:
    """Return ``PAPER_HOST + path`` only for a path that cannot retarget the request."""
    if not path.startswith("/") or path.startswith("//") or "@" in path or "\\" in path:
        raise ValueError("a wire path must be root-relative and may not retarget the paper host")
    url = PAPER_HOST + path
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != _PAPER_HOSTNAME:
        raise ValueError("a wire path must keep the paper Alpaca host")
    return url


def _outcome(response: Any, *, query: bool) -> Outcome:
    status = response.status_code
    if status in (200, 201):
        try:
            payload = response.json()
        except ValueError:
            return Outcome("UNKNOWN")
        if query:
            # A confirmed query resets consecutive_429; its body may be a mapping or a list.
            if isinstance(payload, (Mapping, list)):
                return Outcome("ACK")
            return Outcome("UNKNOWN")
        venue_order_id = payload.get("id") if isinstance(payload, Mapping) else None
        if isinstance(venue_order_id, str) and venue_order_id:
            return Outcome("ACK", venue_order_id)
        return Outcome("UNKNOWN")
    if status == 404:
        return Outcome("NOT_FOUND")
    if status == 429:
        return Outcome("RATE_LIMIT")
    if 400 <= status < 500:
        return Outcome("REFUSED")
    return Outcome("UNKNOWN")


def build_transport(
    *,
    key: str,
    secret: str,
    session: Any = None,
    base_url: str = PAPER_HOST,
    # Pinned upstream: northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa,
    # src/nautilus_alpaca/http.py:146 sets the REST socket timeout as
    # ``timeout_secs: float = 10.0``; mirror that exact 10.0 s.
    timeout_s: float = 10.0,
) -> Callable[[WireRequest, Callable[[], None]], Outcome]:
    """Return a one-request paper transport; HTTP results all come back as an Outcome."""
    if not key or not secret:
        raise ValueError("a non-empty Alpaca paper key and secret are required")
    _paper_base_url(base_url)
    client = requests.Session() if session is None else session
    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Content-Type": "application/json",
    }

    def transport(request: WireRequest, wire: Callable[[], None]) -> Outcome:
        url = _request_url(request.path)
        wire()  # Exactly once, immediately before the only request; its failure aborts the send.
        try:
            response = client.request(
                request.method,
                url,
                headers=headers,
                json=dict(request.body),
                timeout=timeout_s,
                allow_redirects=False,
            )
        except requests.RequestException:
            return Outcome("UNKNOWN")
        return _outcome(response, query=request.kind == ActionKind.QUERY)

    return transport
