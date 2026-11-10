"""Alpaca adapter client configuration without stored credentials.

The subclass pattern, the "declare adapter fields as keyword arguments and accept
``**kwargs`` for common fields" rule and the serialization warning follow
nautilus_trader@d53849b216e20f2c122ca01b4dd0da377638b186
``docs/developer_guide/python_adapters.md`` ("Config classes"). A config carries
the name of each environment variable, never its value, following the repo key
store's per-account entries (``scripts/keys.sh:26-31``). Feed values are the
vendor's own alpaca-py 0.44.0 enum
(``alpaca/data/enums.py:56``, ``DataFeed``).
"""

from __future__ import annotations

import os
from typing import Any

from alpaca.data.enums import DataFeed
from nautilus_trader.config import DataClientConfig, ExecutionClientConfig

from .constants import DEFAULT_ACCOUNT_ID, DEFAULT_API_KEY_ENV, DEFAULT_API_SECRET_ENV, DEFAULT_FEED

_DATA_COMMON_FIELDS = frozenset({"handle_revised_bars", "instrument_provider", "routing"})
_EXECUTION_COMMON_FIELDS = frozenset({"instrument_provider", "routing"})


def resolve_credential(env_name: str) -> str:
    """Return the value of ``env_name``, or name it when the process lacks it."""
    try:
        return os.environ[env_name]
    except KeyError:
        raise ValueError(f"set the {env_name} environment variable") from None


def _refuse_unknown(
    kwargs: dict[str, Any],
    allowed: frozenset[str],
    owner: str,
) -> None:
    unknown = sorted(set(kwargs) - allowed)
    if unknown:
        raise TypeError(f"{owner}() got unexpected keyword arguments {unknown}")


class AlpacaDataClientConfig(DataClientConfig):
    """Configuration for the Alpaca market-data client.

    ``api_key_env`` and ``api_secret_env`` name process environment variables;
    no key or secret value is stored in the config or its serialized form.
    """

    def __init__(
        self,
        *,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        api_secret_env: str = DEFAULT_API_SECRET_ENV,
        paper: bool = True,
        feed: str = DEFAULT_FEED,
        **kwargs: Any,
    ) -> None:
        _refuse_unknown(kwargs, _DATA_COMMON_FIELDS, type(self).__name__)
        self.api_key_env = str(api_key_env)
        self.api_secret_env = str(api_secret_env)
        self.paper = bool(paper)
        try:
            self.feed = DataFeed(feed).value
        except ValueError:
            feeds = [member.value for member in DataFeed]
            raise ValueError(f"feed must be one of {feeds}, was {feed!r}") from None


class AlpacaExecutionClientConfig(ExecutionClientConfig):
    """Configuration for the Alpaca execution client.

    ``account_id`` is the engine account identity, so one writer per account can
    be named explicitly (AGENTS.md custody rule). Credentials are named, never
    held, exactly as in :class:`AlpacaDataClientConfig`.
    """

    def __init__(
        self,
        *,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        api_secret_env: str = DEFAULT_API_SECRET_ENV,
        paper: bool = True,
        account_id: str = DEFAULT_ACCOUNT_ID,
        **kwargs: Any,
    ) -> None:
        _refuse_unknown(kwargs, _EXECUTION_COMMON_FIELDS, type(self).__name__)
        self.api_key_env = str(api_key_env)
        self.api_secret_env = str(api_secret_env)
        self.paper = bool(paper)
        self.account_id = str(account_id)
