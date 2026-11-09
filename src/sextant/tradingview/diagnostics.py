"""Safe class-and-stage labels for an owner-consent sync stop.

Adapted from northstar-trading@8256c16c ``tradingview/auth_safety.py:82-199``:
``_CLASS_LABELS`` keeps the exact type→literal map, ``_class_label`` and
``_leaf`` keep the bounded group walk. The stage order comes from the installed
MCP SDK's OAuth flow (``mcp/client/auth/oauth2.py:385`` authorize/callback,
``:453`` token exchange, ``:604`` the flow that starts it) and the session it
then enters. Only fixed literals leave this module; never an exception argument,
URL, token, or upstream message.
"""

from __future__ import annotations

import httpx2
from mcp.client.auth.exceptions import OAuthFlowError, OAuthRegistrationError, OAuthTokenError
from mcp.client.streamable_http import ResumptionError, StreamableHTTPError
from mcp.shared.exceptions import MCPError

from sextant.tradingview.sync import SyncError

MAX_GROUP_DEPTH = 32
MAX_GROUP_NODES = 256

_CLASS_LABELS: dict[type[BaseException], str] = {
    SyncError: "SyncError",
    OAuthTokenError: "OAuthTokenError",
    OAuthRegistrationError: "OAuthRegistrationError",
    OAuthFlowError: "OAuthFlowError",
    ResumptionError: "ResumptionError",
    StreamableHTTPError: "StreamableHTTPError",
    MCPError: "MCPError",
    httpx2.ConnectTimeout: "ConnectTimeout",
    httpx2.ReadTimeout: "ReadTimeout",
    httpx2.WriteTimeout: "WriteTimeout",
    httpx2.PoolTimeout: "PoolTimeout",
    httpx2.TimeoutException: "TimeoutException",
    httpx2.ConnectError: "ConnectError",
    httpx2.ReadError: "ReadError",
    httpx2.WriteError: "WriteError",
    httpx2.CloseError: "CloseError",
    httpx2.NetworkError: "NetworkError",
    httpx2.ProxyError: "ProxyError",
    httpx2.UnsupportedProtocol: "UnsupportedProtocol",
    httpx2.LocalProtocolError: "LocalProtocolError",
    httpx2.RemoteProtocolError: "RemoteProtocolError",
    httpx2.TransportError: "TransportError",
    httpx2.DecodingError: "DecodingError",
    httpx2.TooManyRedirects: "TooManyRedirects",
    httpx2.HTTPStatusError: "HTTPStatusError",
    httpx2.RequestError: "RequestError",
    TimeoutError: "TimeoutError",
    ConnectionError: "ConnectionError",
    OSError: "OSError",
    ValueError: "ValueError",
    RuntimeError: "RuntimeError",
}

# OAuthTokenError and OAuthRegistrationError subclass OAuthFlowError; order matters.
_STAGE_BY_CLASS: tuple[tuple[type[BaseException], str], ...] = (
    (OAuthRegistrationError, "client registration"),
    (OAuthTokenError, "token"),
    (OAuthFlowError, "callback"),
)


def class_label(error: BaseException) -> str:
    """The exact type's fixed label, or ExceptionGroup, never its text."""
    if type(error) is ExceptionGroup:
        return "ExceptionGroup"
    if type(error) is BaseExceptionGroup:
        return "BaseExceptionGroup"
    return _CLASS_LABELS.get(type(error), "UnrecognizedError")


def _leaf(error: BaseException) -> BaseException:
    """Bound the group walk by work AND depth, reading each group's children once."""
    seen: set[int] = set()
    for _ in range(min(MAX_GROUP_DEPTH, MAX_GROUP_NODES)):
        if not isinstance(error, BaseExceptionGroup) or id(error) in seen:
            break
        seen.add(id(error))
        children = error.exceptions
        if type(children) is not tuple or not children:
            break
        if not isinstance(children[0], BaseException):
            break
        error = children[0]
    return error


def stage(error: BaseException) -> str:
    """The flow position implied by the SDK's order: registration, callback, token, session."""
    leaf = _leaf(error)
    if isinstance(leaf, SyncError) and leaf.stage:
        # A local refusal already knows exactly where it is; keep its fixed literal.
        return leaf.stage
    for kind, name in _STAGE_BY_CLASS:
        if isinstance(leaf, kind):
            return name
    return "session"


def leaf_label(error: BaseException) -> str:
    """The fixed label of the group's first leaf; the class a stop is caused by."""
    return class_label(_leaf(error))
