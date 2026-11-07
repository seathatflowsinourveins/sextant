"""IBKR's paper-only config boundary, using the pinned native adapter without a connection."""

import json
import tomllib
from decimal import Decimal
from importlib import import_module, reload
from pathlib import Path
from typing import Any

import nautilus_trader.adapters.interactive_brokers as native_ib
import nautilus_trader.live as native_live
import pytest
import yaml
from nautilus_trader.adapters.interactive_brokers import (
    InteractiveBrokersDataClientConfig,
    InteractiveBrokersExecutionClientConfig,
    MarketDataType,
    SymbologyMethod,
)
from nautilus_trader.model import InstrumentId

from sextant.paper.config import PaperAccount
from sextant.paper.sessions import Session

ROOT = Path(__file__).parents[2]
DATA_POLICY = (
    "use_regular_trading_hours",
    "ignore_quote_tick_size_updates",
    "batch_quotes",
    "market_data_type",
)


def _build(
    *, account_id: str = "DU0000000", port: int = 4002, lane: str = "ibkr-paper", **changes: Any
) -> Any:
    # Explicit fixtures are not registry authority or account credentials.
    settings = {
        "account": PaperAccount(
            lane, account_id, "IB-TEST", "IBTEST", (Session.RTH,), ib_port=port
        ),
        "host": "192.0.2.1",
        "data_client_id": 91001,
        "exec_client_id": 91002,
        "load_ids": frozenset(
            {InstrumentId.from_str("AAPL.NASDAQ"), InstrumentId.from_str("IBM.NYSE")}
        ),
        "connection_timeout": 30,
        "request_timeout": 60,
        "use_regular_trading_hours": False,
        "ignore_quote_tick_size_updates": False,
        "batch_quotes": True,
        "market_data_type": MarketDataType.REALTIME,
    }
    settings.update(changes)
    return import_module("sextant.paper.ibkr").build_client_configs(**settings)


@pytest.mark.parametrize("port", [4002, 7497])
def test_native_configs_preserve_identity_and_preload_without_starting_clients(
    monkeypatch: pytest.MonkeyPatch, port: int
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("offline config construction must not create a client, node or Gateway")

    for name in (
        "InteractiveBrokersDataClientFactory",
        "InteractiveBrokersExecutionClientFactory",
        "DockerizedIBGateway",
        "HistoricalInteractiveBrokersClient",
    ):
        monkeypatch.setattr(native_ib, name, forbidden)
    monkeypatch.setattr(native_live, "LiveNode", forbidden)
    reload(import_module("sextant.paper.ibkr"))

    configs = _build(port=port)

    assert isinstance(configs.data, InteractiveBrokersDataClientConfig)
    assert isinstance(configs.execution, InteractiveBrokersExecutionClientConfig)
    assert configs.data.host == configs.execution.host == "192.0.2.1"
    assert configs.data.port == configs.execution.port == port
    assert configs.data.client_id == 91001
    assert configs.execution.client_id == 91002
    assert configs.execution.account_id == "DU0000000"
    assert configs.data.use_regular_trading_hours is False
    assert configs.data.batch_quotes is True
    assert configs.data.ignore_quote_tick_size_updates is False
    assert configs.data.market_data_type == MarketDataType.REALTIME
    assert configs.data.connection_timeout == configs.execution.connection_timeout == 30
    assert configs.data.request_timeout == configs.execution.request_timeout == 60
    for provider in (configs.data.instrument_provider, configs.execution.instrument_provider):
        assert provider.symbology_method == SymbologyMethod.SIMPLIFIED
        assert provider.load_ids == {
            InstrumentId.from_str("AAPL.NASDAQ"),
            InstrumentId.from_str("IBM.NYSE"),
        }


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"lane": "alpaca-live"}, "known paper lane"),
        ({"lane": "alpaca-paper-a"}, "shared IBKR paper account"),
        ({"account_id": "U0000000"}, "D-prefixed"),
        ({"account_id": ""}, "account"),
        ({"account_id": "IB-DU0000000"}, "D-prefixed"),
        ({"account_id": "DU0000000-U1234567"}, "D-prefixed"),
        ({"account_id": "D-U1234567"}, "D-prefixed"),
        ({"account_id": "DUMMY-F7654321"}, "D-prefixed"),
        ({"account_id": "DU0000000 "}, "D-prefixed"),
        ({"account_id": "DU0000000\n"}, "D-prefixed"),
        ({"account_id": " DU0000000"}, "D-prefixed"),
        ({"account_id": "DUMMY"}, "D-prefixed"),
        ({"account_id": "D"}, "D-prefixed"),
        ({"account_id": "DU"}, "D-prefixed"),
        ({"port": 4001}, "paper port"),
        ({"port": 7496}, "paper port"),
        ({"port": 5000}, "paper port"),
        ({"data_client_id": 91002}, "distinct"),
        ({"exec_client_id": 1000}, "multiple of 1000"),
        ({"load_ids": frozenset({InstrumentId.from_str("ESZ6.XCME")})}, "US equities"),
        (
            {"load_ids": frozenset({InstrumentId.from_str("AAPL261218C00200000.NASDAQ")})},
            "US equities",
        ),
        ({"load_ids": frozenset({InstrumentId.from_str("AAPL=STK.SMART")})}, "US equities"),
        *[
            ({"load_ids": frozenset({InstrumentId.from_str(value)})}, "US equities")
            for value in (
                "AAPL261218C00200000=OPT.AMEX",
                "SPY=OPT.ARCA",
                "ESZ6=FUT.NYSE",
                "AAPL=CFD.NASDAQ",
                "NDX=IND.NASDAQ",
                "^NDX.NASDAQ",
                "AAPL=STK.NASDAQ",
                "(1)AAPL___((2))MSFT.NASDAQ",
                "(1)SPY___((1))^SPX.ARCA",
                "(1)QQQ___((1))^NDX.NASDAQ",
            )
        ],
    ],
)
def test_nonpaper_or_unsupported_configuration_is_refused(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _build(**changes)


def test_account_is_exact_and_never_taken_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IB_ACCOUNT_ID", "DU9999999")
    monkeypatch.setenv("TWS_ACCOUNT", "DU9999999")
    assert _build(account_id="DU0000000").execution.account_id == "DU0000000"
    with pytest.raises(ValueError, match="account"):
        _build(account_id="")


def test_native_configs_derive_identity_and_port_from_the_shared_account() -> None:
    account = PaperAccount(
        "ibkr-paper", "DU2222222", "IB-TEST", "IBTEST", (Session.RTH,), ib_port=7497
    )
    configs = _build(account=account)
    assert configs.execution.account_id == "DU2222222"
    assert configs.data.port == configs.execution.port == 7497


@pytest.mark.parametrize(
    "name,value",
    [
        ("use_regular_trading_hours", True),
        ("ignore_quote_tick_size_updates", True),
        ("batch_quotes", False),
        ("market_data_type", MarketDataType.DELAYED),
    ],
)
def test_data_policy_is_explicitly_forwarded(name: str, value: Any) -> None:
    assert getattr(_build(**{name: value}).data, name) == value


def test_preload_iterable_is_materialized_without_losing_instruments() -> None:
    ids = (InstrumentId.from_str(value) for value in ("AAPL.NASDAQ", "IBM.NYSE"))
    assert _build(load_ids=ids).data.instrument_provider.load_ids == {
        InstrumentId.from_str("AAPL.NASDAQ"),
        InstrumentId.from_str("IBM.NYSE"),
    }


def test_toml_registry_preserves_inventory_and_supplies_native_data_policy() -> None:
    registry = tomllib.loads((ROOT / "lanes/paper/ibkr.toml").read_text())
    assert registry["state"] == "OFF" and registry["lane"] == "ibkr-paper"
    gateway = registry["gateway"]
    assert gateway["image"] == (
        "ghcr.io/gnzsnz/ib-gateway:10.50.1f@sha256:"
        "1e2236804ac949b789197c225a048c0c891c9958f948c87166226e5b647ff581"
    )
    assert gateway["ibc_version"] == "3.24.2"
    assert gateway["state"] == "NOT_STARTED"
    assert gateway["server_protocol_state"] == "UNVERIFIED"
    controller = registry["controller_qualification"]
    assert controller["source"]
    assert {key: value for key, value in controller.items() if key != "source"} == {
        "repository": "code-hustler-ft3d/ibg-controller",
        "version": "v0.16.3",
        "commit": "9c3a1f9037a9dfd3c644a7c6a4142a9e9e0d3b1a",
        "state": "NOT_RUN",
    }
    candidate = registry["candidate"]
    assert (candidate["id"], candidate["disposition"], candidate["implementation"]) == (
        "C06",
        "CANDIDATE",
        "OFF",
    )
    assert candidate["long_liquid_tier_first"] is True
    assert candidate["shorts"] == candidate["reentry"] == "OFF"
    assert candidate["source"]
    parameters = registry["parameters"]
    decimal_rows = {
        "risk_per_trade",
        "leverage",
        "protective_stop_fraction",
        "emulated_stop_strict_upper_bound",
        "peak_actions_per_second",
        "long_only_peak_actions_per_second",
        "connection_timeout",
        "request_timeout",
    }
    assert set(parameters) == decimal_rows | set(DATA_POLICY)
    for name, row in parameters.items():
        assert row["state"] == "UNCALIBRATED" and row["source"]
        if name in decimal_rows:
            assert isinstance(row["start"], str) and Decimal(row["start"]).is_finite()
    shared = registry["shared_parameters"]
    assert set(shared) == {
        "request_budget_per_second",
        "request_budget_after_paced_rotation",
        "order_action_ceiling_per_minute",
        "market_data_lines",
        "oer_daily_ceiling",
        "working_orders_per_side_per_contract",
        "reserve_per_open_position",
        "reserve_per_exiting_position",
    }
    assert not (set(shared) & set(parameters))
    for name, reference in shared.items():
        filename, key = reference.split(":", 1)
        if filename.endswith(".yaml"):
            value = yaml.safe_load((ROOT / filename).read_text())
            for component in key.split("."):
                value = value[component]
            assert value > 0
        else:
            row = next(
                row for row in json.loads((ROOT / filename).read_text()) if row["name"] == key
            )
            assert name.startswith("reserve_per_") and row["value"] is None
            assert row["calibration"] == row["scope"] == "UNAVAILABLE" and row["source"]
    policy = {name: parameters[name]["start"] for name in DATA_POLICY}
    policy["market_data_type"] = getattr(MarketDataType, policy["market_data_type"])
    data = _build(**policy).data
    assert data.use_regular_trading_hours is False
    assert data.ignore_quote_tick_size_updates is False
    assert data.batch_quotes is True
    assert data.market_data_type == MarketDataType.REALTIME
