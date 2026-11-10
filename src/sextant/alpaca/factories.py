"""Build Alpaca clients and the instrument provider from node configuration.

Follows nautilus_trader@d53849b216e20f2c122ca01b4dd0da377638b186
``examples/live/_template/factories.py`` and
``docs/developer_guide/python_adapters.md``: each factory's static ``create``
returns a fresh client synchronously and opens no network resource. The data
factory builds the instrument provider with a deferred ``TradingClient``
factory, matching the template's data/execution wiring split. The execution
factory owns the account identity and, following the template, passes no
instrument provider: the venue's instruments reach the engine through the data
client. ``AccountType.MARGIN`` and ``OmsType.NETTING`` are the template's
execution settings, and margin is the Alpaca lane in ADR-0008 B1. Credentials
arrive only as environment-variable names from the adapter config; the
``TradingClient`` is built inside the provider's first load.
"""

from __future__ import annotations

from functools import partial
from typing import cast

from alpaca.trading.client import TradingClient
from nautilus_trader.live.clients import DataClientFactory, ExecutionClientFactory
from nautilus_trader.model import AccountId, AccountType, OmsType

from .config import AlpacaDataClientConfig, AlpacaExecutionClientConfig, resolve_credential
from .constants import VENUE
from .data import AlpacaDataClient
from .execution import AlpacaExecutionClient
from .providers import AlpacaInstrumentProvider


def trading_client(
    config: AlpacaDataClientConfig | AlpacaExecutionClientConfig,
) -> TradingClient:
    """Build a ``TradingClient`` from the config's environment-variable names."""
    return TradingClient(
        api_key=resolve_credential(config.api_key_env),
        secret_key=resolve_credential(config.api_secret_env),
        paper=config.paper,
    )


class AlpacaDataClientFactory(DataClientFactory):
    """Construct the Alpaca market-data client and its instrument provider."""

    @staticmethod
    def create(*, name, config, cache, clock) -> AlpacaDataClient:
        """Construct a fresh data client; no network is opened here."""
        config = cast("AlpacaDataClientConfig", config)
        provider = AlpacaInstrumentProvider(
            config.instrument_provider,
            client_factory=partial(trading_client, config),
        )
        return AlpacaDataClient(
            name=name,
            config=config,
            cache=cache,
            clock=clock,
            venue=VENUE,
            instrument_provider=provider,
        )


class AlpacaExecutionClientFactory(ExecutionClientFactory):
    """Construct the Alpaca execution client from configuration."""

    @staticmethod
    def create(*, name, config, cache, clock, trader_id) -> AlpacaExecutionClient:
        """Construct a fresh execution client; no network is opened here."""
        config = cast("AlpacaExecutionClientConfig", config)
        return AlpacaExecutionClient(
            name=name,
            config=config,
            cache=cache,
            clock=clock,
            trader_id=trader_id,
            venue=VENUE,
            account_id=AccountId.from_str(config.account_id),
            account_type=AccountType.MARGIN,
            oms_type=OmsType.NETTING,
        )
