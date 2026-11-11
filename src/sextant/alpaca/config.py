"""Alpaca adapter client configuration without stored credentials.

The subclass pattern, the "declare adapter fields as keyword arguments and accept
``**kwargs`` for common fields" rule and the serialization warning follow
nautilus_trader@d53849b216e20f2c122ca01b4dd0da377638b186
``docs/developer_guide/python_adapters.md`` ("Config classes"). A config carries
the name of an environment variable, never its value, following the repo key
store's per-account entries (``scripts/keys.sh:26-31``). Both names are required:
the adapter has no key name default, so a node states the account it runs as.
Feed values are the vendor's own alpaca-py 0.44.0 enum
(``alpaca/data/enums.py:56``, ``DataFeed``). The execution account id is also
required and its issuer must be ``ALPACA``, so one writer per account is named
explicitly (AGENTS.md custody rule); ``AccountId.value`` splits as
``<issuer>-<number>``.
"""

from __future__ import annotations

import os
from typing import Any

from alpaca.data.enums import DataFeed
from nautilus_trader.config import DataClientConfig, ExecutionClientConfig
from nautilus_trader.model import AccountId

from .constants import DEFAULT_FEED

_DATA_COMMON_FIELDS = frozenset({"handle_revised_bars", "instrument_provider", "routing"})
_EXECUTION_COMMON_FIELDS = frozenset({"instrument_provider", "routing"})
_ACCOUNT_ISSUER = "ALPACA"


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
        api_key_env: str,
        api_secret_env: str,
        feed: str = DEFAULT_FEED,
        **kwargs: Any,
    ) -> None:
        _refuse_unknown(kwargs, _DATA_COMMON_FIELDS, type(self).__name__)
        self.api_key_env = str(api_key_env)
        self.api_secret_env = str(api_secret_env)
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
        api_key_env: str,
        api_secret_env: str,
        account_id: str,
        **kwargs: Any,
    ) -> None:
        _refuse_unknown(kwargs, _EXECUTION_COMMON_FIELDS, type(self).__name__)
        self.api_key_env = str(api_key_env)
        self.api_secret_env = str(api_secret_env)
        account = AccountId.from_str(account_id)
        issuer = account.value.split("-", 1)[0]
        if issuer != _ACCOUNT_ISSUER:
            raise ValueError(f"account_id issuer must be {_ACCOUNT_ISSUER}, was {issuer!r}")
        self.account_id = account.value
