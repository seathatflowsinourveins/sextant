"""Alpaca instrument provider: assets by id, or every US equity.

Follows nautilus_trader@d53849b ``examples/live/_template/providers.py`` and
``docs/developer_guide/python_adapters.md``: configuration and local state only;
network work starts in the async load hooks, each blocking SDK call through
``asyncio.to_thread``. The provider's client uses ``raw_data=True``: typed
``get_all_assets`` validates the whole list at once
(``alpaca/trading/client.py:394-397``), so one unlisted vendor value would fail
every instrument. Each raw row is read and validated on its own; a row that
cannot be parsed is skipped, counted and the count logged.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any, cast, override

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass
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
        """Load every US-equity asset, tradable or not, from Alpaca."""
        client = self._trading_client()
        request = GetAssetsRequest(asset_class=AssetClass.US_EQUITY)
        rows = cast(
            "list[Any]",
            await asyncio.to_thread(client.get_all_assets, request),
        )
        ts_init = time.time_ns()
        skipped = 0
        for row in rows:
            try:
                self.add(parse_equity(row, ts_init=ts_init))
            except (AttributeError, KeyError, TypeError, ValueError):
                skipped += 1
        if skipped:
            self._log.warning(
                f"Skipped {skipped} of {len(rows)} Alpaca asset row(s) that "
                "could not be parsed (missing or invalid symbol/fields)",
            )

    @override
    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict | None = None,
    ) -> None:
        """Load the named instruments through one asset lookup each."""
        client = self._trading_client()
        ts_init = time.time_ns()
        skipped = 0
        for instrument_id in instrument_ids:
            try:
                row = await asyncio.to_thread(
                    client.get_asset,
                    instrument_id.symbol.value,
                )
                self.add(parse_equity(row, ts_init=ts_init))
            except (AttributeError, KeyError, TypeError, ValueError):
                skipped += 1
        if skipped:
            self._log.warning(
                f"Skipped {skipped} of {len(instrument_ids)} Alpaca asset "
                "lookup(s) that could not be parsed",
            )

    @override
    async def load_async(
        self,
        instrument_id: InstrumentId,
        filters: dict | None = None,
    ) -> None:
        """Load one instrument through the ID-list loader, or fail closed.

        The signature follows nautilus_trader@d53849b
        ``python/nautilus_trader/live/providers.py:110``. A single-instrument
        request never guesses: an id the venue does not list raises instead of
        leaving the data client to fail later on a different message.
        """
        if self.find(instrument_id) is not None:
            return
        await self.load_ids_async([instrument_id], filters)
        if self.find(instrument_id) is None:
            raise ValueError(f"Alpaca does not list an equity for {instrument_id}")
