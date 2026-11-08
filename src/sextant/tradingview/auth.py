"""RAM-only SDK OAuth, adapted from northstar-trading@8256c16c auth.py.

MCP SDK v2.3.0 docs_src/oauth_clients/tutorial001.py supplies the memory store
and provider. Upstream's quiet loopback callback avoids pasted codes or URLs.
"""

from __future__ import annotations

import asyncio
import logging
import time
import webbrowser
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
from mcp import Client
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import AnyUrl

from sextant.tradingview.sync import SyncError, _sanitized

SERVER = "https://mcp.tradingview.com/mcp"
OWNER_STEP = (
    "TradingView owner browser consent required each session: run --authorize on the owner's "
    "machine with Essential+ (non-trial). Authorization stays in RAM; never paste credentials "
    "or callback URLs into a terminal or chat."
)


_logging_lock = Lock()
_logging_users = 0
_previous_logging = logging.NOTSET


@contextmanager
def sensitive_logging() -> Iterator[None]:
    """northstar-trading@8256c16c auth_safety: last user restores logging.

    No await occurs under the lock. Changing logging policy during OAuth is
    unsupported; overlapping users share the original application's policy.
    """
    global _logging_users, _previous_logging
    with _logging_lock:
        if _logging_users == 0:
            _previous_logging = logging.root.manager.disable
            logging.disable(max(_previous_logging, logging.CRITICAL))
        _logging_users += 1
    try:
        yield
    finally:
        with _logging_lock:
            _logging_users -= 1
            if _logging_users == 0:
                logging.disable(_previous_logging)


class InMemoryTokenStorage:
    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


class OwnerCallback:
    def __init__(self) -> None:
        self.result: AuthorizationCodeResult | None = None
        self.failed = False
        callback = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlsplit(self.path)
                if parsed.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                query = parse_qs(parsed.query)
                valid = (
                    all(len(query.get(key, [])) == 1 for key in ("code", "state"))
                    and len(query.get("iss", [])) <= 1
                    and "error" not in query
                )
                if valid:
                    callback.result = AuthorizationCodeResult(
                        code=query["code"][0],
                        state=query["state"][0],
                        iss=query.get("iss", [None])[0],
                    )
                else:
                    callback.failed = True
                self.send_response(200 if valid else 400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Return to the Sextant terminal. Do not copy this URL.")

            def log_message(self, format: str, *args: Any) -> None:
                # Default HTTP request logs contain the OAuth callback code/state.
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.server.timeout = 1
        self.uri = f"http://127.0.0.1:{self.server.server_port}/callback"

    async def redirect(self, authorization_url: str) -> None:
        if urlsplit(authorization_url).scheme != "https" or not webbrowser.open(authorization_url):
            raise SyncError(OWNER_STEP)

    async def wait(self) -> AuthorizationCodeResult:
        def receive():
            deadline = time.monotonic() + 300
            while self.result is None and not self.failed and time.monotonic() < deadline:
                self.server.handle_request()
            if self.result is None:
                raise SyncError(OWNER_STEP)
            return self.result

        return await asyncio.to_thread(receive)


async def identify_request(request: httpx2.Request) -> None:
    # Upstream measured missing SDK discovery headers rejected by CloudFront.
    request.headers.setdefault("User-Agent", "sextant-tradingview-sync/1 (display-only)")
    request.headers.setdefault("Accept", "application/json")


@asynccontextmanager
async def official_client(authorize: bool = False) -> AsyncIterator[Client]:
    """No grant reuse, file/keychain fallback, or transport without owner consent."""
    if not authorize:
        raise SyncError(OWNER_STEP)
    storage = InMemoryTokenStorage()
    callback = None
    with sensitive_logging():
        try:
            callback = OwnerCallback()
            oauth = OAuthClientProvider(
                server_url=SERVER,
                client_metadata=OAuthClientMetadata(
                    client_name="Sextant display-only sync", redirect_uris=[AnyUrl(callback.uri)]
                ),
                storage=storage,
                redirect_handler=callback.redirect,
                callback_handler=callback.wait,
            )
            async with httpx2.AsyncClient(
                auth=oauth,
                timeout=httpx2.Timeout(30.0, read=60.0),
                event_hooks={"request": [identify_request]},
            ) as http_client:
                transport = streamable_http_client(SERVER, http_client=http_client)
                body_error = None
                async with Client(transport, read_timeout_seconds=60.0) as client:
                    try:
                        yield client
                    except SyncError as error:
                        # SDK task groups wrap errors leaving Client; close normally
                        # before propagating a trusted local refusal to the caller.
                        body_error = error
            if body_error is not None:
                raise body_error
        except asyncio.CancelledError:
            _sanitized(asyncio.CancelledError())
        except SyncError:
            raise
        except Exception:
            _sanitized(
                SyncError("TradingView session stopped; re-inventory before retry. " + OWNER_STEP)
            )
        finally:
            storage.tokens = None
            storage.client_info = None
            if callback is not None:
                callback.server.server_close()
                callback.result = None
