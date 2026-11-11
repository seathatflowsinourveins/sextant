"""The owner's lasting TradingView sign-in in the repo's encrypted systemd-creds store.

D-23 (docs/adr/0021 amendment) authorises one stored sign-in for the display-only
sync: one JSON line of the official SDK's tokens and client registration, written
and read only through ``scripts/keys.sh`` and ``systemd-creds --with-key=host``.
No plain file, environment variable, argv value or log line carries it.

The pinned SDK's ``TokenStorage`` protocol is the seam (mcp 2.3.0,
``mcp/client/auth/oauth2.py``). ``StoredTokenStorage`` is used only when
``--keep-login`` passes a ``StoredLogin``; the in-memory store stays the default.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Never

from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

NAME = "TRADINGVIEW_MCP_OAUTH"
SEALED = "NS_SEALED_TRANSFER_COMPLETE"
ROOT = Path(__file__).resolve().parents[3]
KEYS = ROOT / "scripts" / "keys.sh"
SYSTEMD = ROOT / "scripts" / "key-systemd.sh"


class StoredLoginError(RuntimeError):
    """The store refused the sign-in; the message is a fixed literal, never its value."""


class StoredLoginCorrupt(StoredLoginError):
    """The stored value cannot be decrypted or parsed; only --forget-login clears it."""


@dataclass(frozen=True)
class StoredDocument:
    tokens: OAuthToken
    client_info: OAuthClientInformationFull | None
    obtained_at: float


def _run(
    command: list[str], home: Path | None, **kwargs: Any
) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ)
    if home is not None:
        env["HOME"] = str(home)
    return subprocess.run(command, capture_output=True, check=False, env=env, **kwargs)


def _sanitized(error: BaseException) -> Never:
    """Upstream auth_safety.raise_sanitized; no retained raw exception graph."""
    try:
        raise error from None
    except BaseException:
        error.__context__ = None
        error.__cause__ = None
        raise


class StoredLogin:
    """One encrypted JSON line under ``$HOME/.config/sextant/credentials``."""

    def __init__(self, home: Path | None = None) -> None:
        self._home = home

    def _state(self) -> str:
        for script in (KEYS, SYSTEMD):
            if not script.is_file():
                raise StoredLoginError("the repo's key store script is missing")
        result = _run(
            [
                "bash",
                "-c",
                'source "$1"; ns_systemd_init; ns_systemd_state "$2"',
                "keys",
                str(SYSTEMD),
                NAME,
            ],
            self._home,
        )
        state = result.stdout.decode(errors="replace").strip()
        if result.returncode == 44 or state == "missing":
            return "missing"
        if result.returncode != 0 or state != "set":
            raise StoredLoginError("the sign-in store is unavailable")
        return "set"

    def present(self) -> bool:
        return self._state() == "set"

    def load(self) -> StoredDocument | None:
        if self._state() == "missing":
            return None
        result = _run(
            [
                "bash",
                "-c",
                'source "$1"; ns_systemd_init; ns_systemd_read "$2"',
                "keys",
                str(SYSTEMD),
                NAME,
            ],
            self._home,
        )
        if result.returncode != 0:
            raise StoredLoginCorrupt("the stored sign-in could not be read")
        try:
            payload = json.loads(result.stdout)
            tokens = OAuthToken.model_validate(payload["tokens"])
            client_info = (
                OAuthClientInformationFull.model_validate(payload["client_info"])
                if payload.get("client_info")
                else None
            )
            obtained_at = float(payload["obtained_at"])
        except (ValueError, KeyError, TypeError):
            _sanitized(StoredLoginCorrupt("the stored sign-in is unreadable"))
        return StoredDocument(tokens=tokens, client_info=client_info, obtained_at=obtained_at)

    def save(
        self,
        tokens: OAuthToken,
        client_info: OAuthClientInformationFull | None,
        obtained_at: float | None = None,
    ) -> None:
        payload = json.dumps(
            {
                "tokens": tokens.model_dump(mode="json"),
                "client_info": client_info.model_dump(mode="json")
                if client_info is not None
                else None,
                "obtained_at": time.time() if obtained_at is None else obtained_at,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        if not payload.isprintable():
            raise StoredLoginError("the sign-in does not fit the store's one printable line")
        result = _run(
            ["bash", str(KEYS), "set", NAME, "--sealed-stdin"],
            self._home,
            input=f"{payload}\n{SEALED}\n".encode(),
        )
        if result.returncode != 0:
            raise StoredLoginError("the store refused the sign-in")

    def forget(self) -> bool:
        if self._state() == "missing":
            return False
        result = _run(["bash", str(KEYS), "rm", NAME], self._home)
        if result.returncode != 0:
            raise StoredLoginError("the store refused to remove the sign-in")
        return True


class StoredTokenStorage:
    """The SDK's TokenStorage protocol over one ``StoredLogin``; writes merge the document."""

    def __init__(self, login: StoredLogin) -> None:
        self._login = login
        self._tokens: OAuthToken | None = None
        self._client_info: OAuthClientInformationFull | None = None
        self._obtained_at = 0.0
        self._loaded = False
        self._lock = asyncio.Lock()

    def _load(self) -> None:
        if self._loaded:
            return
        document = self._login.load()
        if document is not None:
            self._tokens = document.tokens
            self._client_info = document.client_info
            self._obtained_at = document.obtained_at
        self._loaded = True

    def _persist(self) -> None:
        if self._tokens is not None:
            self._login.save(self._tokens, self._client_info, self._obtained_at)

    def prime_expiry(self, context: Any) -> None:
        """Set the SDK's expiry field so an old stored token refreshes, not re-consents."""
        self._load()
        if self._tokens is not None and self._tokens.expires_in:
            context.token_expiry_time = self._obtained_at + int(self._tokens.expires_in)

    async def get_tokens(self) -> OAuthToken | None:
        self._load()
        return self._tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        self._load()
        return self._client_info

    async def set_tokens(self, tokens: OAuthToken) -> None:
        async with self._lock:
            self._load()
            self._tokens = tokens
            self._obtained_at = time.time()
            # The registration is written with the first token so a fresh consent
            # keeps the client id the next refresh needs.
            self._persist()

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        async with self._lock:
            self._load()
            self._client_info = client_info
            if self._tokens is not None:
                self._persist()
