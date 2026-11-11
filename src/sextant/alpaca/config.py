"""Alpaca client configuration without stored credentials.

The subclass and ``**kwargs`` pattern follows nautilus_trader@d53849b
``docs/developer_guide/python_adapters.md``; a config carries an environment
variable's name, never its value (``scripts/keys.sh:26-31``). Key names and the
execution account id are required: no adapter default, and the account issuer
must be ALPACA (AGENTS.md custody rule). Feeds are alpaca-py 0.44.0 ``DataFeed``
values (``alpaca/data/enums.py:56``).
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
