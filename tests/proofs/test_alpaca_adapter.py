"""Proofs for the Alpaca adapter's instrument provider, configs and factories.

upstream checked: nautilus_trader@d53849b216e20f2c122ca01b4dd0da377638b186:
examples/live/_template/{constants,providers,factories,data,execution}.py,
docs/developer_guide/python_adapters.md, docs/concepts/instruments/equity.md;
alpaca-py@cc4cb3b7ba50ae250e621983c2779047fb16bb28:
alpaca/trading/{client,models,requests}.py, alpaca/data/enums.py.
The sub-dollar fallback tick follows src/sextant/paper/c_live_main.py:273-295.

No network: every Alpaca trading client is faked, environment values are dummies,
and no proof reads or records a real credential.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from typing import Any, cast

import alpaca
import pytest
from alpaca.data.enums import DataFeed
from alpaca.trading import client as alpaca_client_module
from alpaca.trading.enums import AssetClass, AssetStatus
from alpaca.trading.models import Asset
from alpaca.trading.requests import GetAssetsRequest
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.model import (
    AccountId,
    AccountType,
    Currency,
    InstrumentId,
    OmsType,
    Price,
    Symbol,
    TraderId,
    Venue,
)

import sextant.alpaca
from sextant.alpaca import constants, factories, providers
from sextant.alpaca.config import AlpacaDataClientConfig, AlpacaExecutionClientConfig
from sextant.alpaca.data import AlpacaDataClient
from sextant.alpaca.execution import AlpacaExecutionClient
from sextant.alpaca.parsing import parse_equity


def _asset(
    symbol: str = "AAPL",
    *,
    increment: float | None = 0.01,
    tradable: bool = True,
) -> Asset:
    return cast(
        Asset,
        SimpleNamespace(symbol=symbol, price_increment=increment, tradable=tradable),
    )


class FakeTradingClient:
    """A recorded stand-in for ``alpaca.trading.client.TradingClient``."""

    def __init__(self, assets: dict[str, Asset]) -> None:
        self.assets = assets
        self.calls: list[str] = []
        self.bulk_requests: list[GetAssetsRequest] = []

    def get_asset(self, symbol: str) -> Asset:
        self.calls.append(f"get_asset:{symbol}")
        return self.assets[symbol]

    def get_all_assets(self, request: GetAssetsRequest) -> list[Asset]:
        self.calls.append("get_all_assets")
        self.bulk_requests.append(request)
        return list(self.assets.values())


def _provider(
    fake: Any,
    config: InstrumentProviderConfig,
) -> providers.AlpacaInstrumentProvider:
    return providers.AlpacaInstrumentProvider(
        config,
        client_factory=cast("Any", lambda: fake),
    )


def test_the_adapter_package_does_not_shadow_alpaca_py() -> None:
    assert sextant.alpaca is not alpaca
    assert sys.modules["alpaca"] is alpaca
    assert factories.TradingClient is alpaca_client_module.TradingClient


def test_the_venue_and_the_unsupported_message_are_the_alpaca_ones() -> None:
    assert constants.VENUE == Venue.from_str("ALPACA")
    assert "Alpaca" in constants.NOT_IMPLEMENTED


def test_the_data_config_holds_environment_names_not_secret_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "dummy-key-value")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "dummy-secret-value")
    config = AlpacaDataClientConfig()
    assert (config.api_key_env, config.api_secret_env) == (
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
    )
    assert config.paper is True
    assert config.feed == "sip"
    body = config.dict()
    assert body["api_key_env"] == "ALPACA_API_KEY"
    assert "dummy-key-value" not in str(body)
    assert "dummy-secret-value" not in str(body)


def test_the_data_config_accepts_the_vendor_feeds_and_refuses_an_unknown_one() -> None:
    for feed in DataFeed:
        assert AlpacaDataClientConfig(feed=feed.value).feed == feed.value
    with pytest.raises(ValueError, match="feed"):
        AlpacaDataClientConfig(feed="tape")


def test_the_data_config_passes_common_fields_to_the_native_base() -> None:
    provider = InstrumentProviderConfig(load_ids=["AAPL.ALPACA"])
    config = AlpacaDataClientConfig(instrument_provider=provider, feed="iex")
    assert config.instrument_provider.load_ids == ["AAPL.ALPACA"]
    assert config.feed == "iex"
    assert config.dict()["feed"] == "iex"


def test_the_execution_config_holds_the_account_identity_and_environment_names() -> None:
    config = AlpacaExecutionClientConfig(account_id="ALPACA-002", paper=False)
    assert config.account_id == "ALPACA-002"
    assert config.paper is False
    body = config.dict()
    assert body["account_id"] == "ALPACA-002"
    assert body["api_key_env"] == "ALPACA_API_KEY"


def test_an_asset_becomes_an_alpaca_equity_with_the_vendor_tick() -> None:
    equity = parse_equity(_asset("AAPL", increment=0.01), ts_init=11)
    assert equity.id == InstrumentId.from_str("AAPL.ALPACA")
    assert equity.raw_symbol == Symbol("AAPL")
    assert equity.price_precision == 2
    assert equity.price_increment == Price.from_str("0.01")
    assert equity.ts_event == 11
    assert equity.ts_init == 11
    assert equity.quote_currency == Currency.from_str("USD")


def test_a_sub_penny_asset_keeps_its_vendor_increment() -> None:
    equity = parse_equity(_asset("PENNY", increment=0.0001), ts_init=11)
    assert equity.price_precision == 4
    assert equity.price_increment == Price.from_str("0.0001")


def test_a_missing_asset_tick_falls_back_to_the_n4_sub_dollar_tick() -> None:
    equity = parse_equity(_asset("PENNY", increment=None), ts_init=11)
    assert equity.price_precision == 4
    assert equity.price_increment == Price.from_str("0.0001")


def test_a_non_positive_asset_tick_falls_back_to_the_n4_sub_dollar_tick() -> None:
    equity = parse_equity(_asset("AAPL", increment=0.0), ts_init=11)
    assert equity.price_precision == 4
    assert equity.price_increment == Price.from_str("0.0001")


def test_the_provider_loads_the_requested_ids_through_the_asset_lookup() -> None:
    fake = FakeTradingClient({"AAPL": _asset("AAPL")})
    provider = _provider(fake, InstrumentProviderConfig(load_ids=["AAPL.ALPACA"]))
    asyncio.run(provider.initialize())
    assert fake.calls == ["get_asset:AAPL"]
    assert provider.find(InstrumentId.from_str("AAPL.ALPACA")) is not None
    assert [str(instrument.id) for instrument in provider.list_all()] == ["AAPL.ALPACA"]


def test_the_provider_defers_the_trading_client_until_the_first_load() -> None:
    fake = FakeTradingClient({"AAPL": _asset("AAPL")})
    created: list[Any] = []
    provider = providers.AlpacaInstrumentProvider(
        InstrumentProviderConfig(load_ids=["AAPL.ALPACA"]),
        client_factory=cast("Any", lambda: created.append(fake) or fake),
    )
    assert created == []
    asyncio.run(provider.initialize())
    assert created == [fake]
    asyncio.run(provider.initialize())
    assert created == [fake]


def test_the_provider_loads_all_active_us_equities_and_skips_untradable_assets() -> None:
    fake = FakeTradingClient(
        {"AAPL": _asset("AAPL"), "DEAD": _asset("DEAD", tradable=False)},
    )
    provider = _provider(fake, InstrumentProviderConfig(load_all=True))
    asyncio.run(provider.initialize())
    assert fake.calls == ["get_all_assets"]
    request = fake.bulk_requests[0]
    assert request.status is AssetStatus.ACTIVE
    assert request.asset_class is AssetClass.US_EQUITY
    assert [str(instrument.id) for instrument in provider.list_all()] == ["AAPL.ALPACA"]


def test_the_data_factory_builds_a_lazy_alpaca_client_with_our_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[dict[str, Any]] = []

    class RecordingTradingClient:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)

        def get_asset(self, symbol: str) -> Asset:
            return _asset(symbol)

    monkeypatch.setattr(factories, "TradingClient", RecordingTradingClient)
    monkeypatch.setenv("SEXTANT_TEST_API_KEY", "dummy-key")
    monkeypatch.setenv("SEXTANT_TEST_SECRET", "dummy-secret")
    config = AlpacaDataClientConfig(
        api_key_env="SEXTANT_TEST_API_KEY",
        api_secret_env="SEXTANT_TEST_SECRET",  # noqa: S106 - a variable name, not a secret
        instrument_provider=InstrumentProviderConfig(load_ids=["AAPL.ALPACA"]),
    )
    client = factories.AlpacaDataClientFactory.create(
        name="ALPACA",
        config=config,
        cache=cast("Any", None),
        clock=cast("Any", None),
    )
    assert isinstance(client, AlpacaDataClient)
    assert client.venue == constants.VENUE
    provider = client.instrument_provider
    assert isinstance(provider, providers.AlpacaInstrumentProvider)
    assert created == []
    asyncio.run(provider.initialize())
    assert created == [
        {"api_key": "dummy-key", "secret_key": "dummy-secret", "paper": True},
    ]
    assert [str(instrument.id) for instrument in provider.list_all()] == ["AAPL.ALPACA"]


def test_the_data_factory_names_the_missing_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEXTANT_TEST_MISSING_API_KEY", raising=False)
    config = AlpacaDataClientConfig(
        api_key_env="SEXTANT_TEST_MISSING_API_KEY",
        api_secret_env="SEXTANT_TEST_MISSING_SECRET",  # noqa: S106 - a variable name, not a secret
        instrument_provider=InstrumentProviderConfig(load_ids=["AAPL.ALPACA"]),
    )
    client = factories.AlpacaDataClientFactory.create(
        name="ALPACA",
        config=config,
        cache=cast("Any", None),
        clock=cast("Any", None),
    )
    provider = client.instrument_provider
    assert provider is not None
    with pytest.raises(ValueError, match="SEXTANT_TEST_MISSING_API_KEY"):
        asyncio.run(provider.initialize())


def test_the_execution_factory_builds_a_margin_netting_alpaca_client() -> None:
    config = AlpacaExecutionClientConfig(
        account_id="ALPACA-002",
        paper=False,
    )
    client = factories.AlpacaExecutionClientFactory.create(
        name="ALPACA",
        config=config,
        cache=cast("Any", None),
        clock=cast("Any", None),
        trader_id=TraderId("ALPACA-001"),
    )
    assert isinstance(client, AlpacaExecutionClient)
    assert client.venue == constants.VENUE
    assert client.account_id == AccountId.from_str("ALPACA-002")
    assert client.account_type == AccountType.MARGIN
    assert client.oms_type == OmsType.NETTING
    assert client.instrument_provider is None
    assert client.config is config


def test_the_execution_client_connect_refuses_until_execution_lands() -> None:
    client = factories.AlpacaExecutionClientFactory.create(
        name="ALPACA",
        config=AlpacaExecutionClientConfig(),
        cache=cast("Any", None),
        clock=cast("Any", None),
        trader_id=TraderId("ALPACA-001"),
    )
    with pytest.raises(NotImplementedError, match="Alpaca"):
        asyncio.run(client._connect())


def test_the_data_client_connect_initializes_the_provider_and_publishes_instruments() -> None:
    fake = FakeTradingClient({"AAPL": _asset("AAPL")})
    provider_config = InstrumentProviderConfig(load_ids=["AAPL.ALPACA"])
    provider = _provider(fake, provider_config)
    seen: list[Any] = []

    class RecordingClient(AlpacaDataClient):
        def _handle_instrument(self, instrument: object) -> None:
            seen.append(instrument)

    client = RecordingClient(
        name="ALPACA",
        config=AlpacaDataClientConfig(instrument_provider=provider_config),
        cache=cast("Any", None),
        clock=cast("Any", None),
        venue=constants.VENUE,
        instrument_provider=provider,
    )
    asyncio.run(client._connect())
    assert [str(instrument.id) for instrument in seen] == ["AAPL.ALPACA"]


def test_the_data_client_refuses_to_connect_without_an_instrument_provider() -> None:
    client = AlpacaDataClient(
        name="ALPACA",
        config=AlpacaDataClientConfig(),
        cache=cast("Any", None),
        clock=cast("Any", None),
        venue=constants.VENUE,
    )
    with pytest.raises(RuntimeError, match="instrument provider"):
        asyncio.run(client._connect())


def test_the_data_client_still_refuses_every_unbuilt_subscription() -> None:
    fake = FakeTradingClient({"AAPL": _asset("AAPL")})
    provider = _provider(fake, InstrumentProviderConfig(load_ids=["AAPL.ALPACA"]))
    client = AlpacaDataClient(
        name="ALPACA",
        config=AlpacaDataClientConfig(
            instrument_provider=InstrumentProviderConfig(load_ids=["AAPL.ALPACA"]),
        ),
        cache=cast("Any", None),
        clock=cast("Any", None),
        venue=constants.VENUE,
        instrument_provider=provider,
    )
    with pytest.raises(NotImplementedError):
        asyncio.run(client._subscribe_bars(None))  # type: ignore[arg-type]


def test_an_unknown_adapter_field_is_refused() -> None:
    with pytest.raises(TypeError):
        AlpacaDataClientConfig(feed="sip", self_invented_field=1)  # type: ignore[call-arg]
