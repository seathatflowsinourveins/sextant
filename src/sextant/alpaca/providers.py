"""Alpaca instrument provider: assets by id, or every active US equity.

Follows nautilus_trader@d53849b216e20f2c122ca01b4dd0da377638b186
``examples/live/_template/providers.py`` and
``docs/developer_guide/python_adapters.md`` ("Instrument provider"): the provider
holds configuration and local state only, and all network work starts inside the
async load hooks. alpaca-py 0.44.0 ``TradingClient.get_asset`` and
``get_all_assets`` are blocking ``requests.Session`` calls, so each one runs
through ``asyncio.to_thread`` instead of stalling the node loop. The bulk load
asks the vendor for active US equities and skips rows it marks untradable
(``docs/concepts/instruments/equity.md``: the equity instrument is a Nautilus
instrument, not a venue filter).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import cast, override

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, AssetStatus
from alpaca.trading.models import Asset
from alpaca.trading.requests import GetAssetsRequest
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.live.providers import InstrumentProvider
from nautilus_trader.model import InstrumentId

from .parsing import parse_equity


class AlpacaInstrumentProvider(InstrumentProvider):
    """Load Alpaca equity assets into the engine's instrument cache.

    ``client_factory`` defers ``TradingClient`` construction to the first load:
    the adapter guide requires a factory (and therefore a provider built by one)
    to open no network resources, so credentials are resolved at load time.
    """

    def __init__(
        self,
        config: InstrumentProviderConfig | None = None,
        *,
        client_factory: Callable[[], TradingClient],
    ) -> None:
        super().__init__(config)
        self._client_factory = client_factory
        self._client: TradingClient | None = None

    def _trading_client(self) -> TradingClient:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    @override
    async def load_all_async(self, filters: dict | None = None) -> None:
        """Load every active US-equity asset that Alpaca marks tradable."""
        client = self._trading_client()
        request = GetAssetsRequest(
            status=AssetStatus.ACTIVE,
            asset_class=AssetClass.US_EQUITY,
        )
        assets = cast(
            "list[Asset]",
            await asyncio.to_thread(client.get_all_assets, request),
        )
        ts_init = time.time_ns()
        for asset in assets:
            if asset.tradable:
                self.add(parse_equity(asset, ts_init=ts_init))

    @override
    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        """Load the named instruments through one asset lookup each."""
        client = self._trading_client()
        ts_init = time.time_ns()
        for instrument_id in instrument_ids:
            asset = cast(
                "Asset",
                await asyncio.to_thread(client.get_asset, instrument_id.symbol.value),
            )
            self.add(parse_equity(asset, ts_init=ts_init))
