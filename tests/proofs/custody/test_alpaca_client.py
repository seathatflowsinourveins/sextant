"""Native Alpaca hooks and venue witness; sources in the execution module."""

import asyncio
import importlib.util
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from nautilus_trader.model import ClientOrderId, Money, OrderSide, OrderType, Price, Quantity

from sextant.execution.pacer import AccountPacer

from .test_alpaca_execution import boundary, command, order


def client_module():
    assert importlib.util.find_spec("sextant.alpaca.execution") is not None, "client missing"
    return importlib.import_module("sextant.alpaca.execution")


def client():
    from nautilus_trader.common import Clock
    from nautilus_trader.config import ExecutionClientConfig
    from nautilus_trader.model import (
        AccountId,
        AccountType,
        Currency,
        Equity,
        InstrumentId,
        OmsType,
        Symbol,
        TraderId,
        Venue,
    )

    from .alpaca_venue import Venue as FakeVenue
    from .conftest import controls

    stock = Equity(
        InstrumentId.from_str("TEST.ALPACA"),
        Symbol("TEST"),
        Currency.from_str("USD"),
        4,
        Price.from_str("0.0001"),
        0,
        0,
    )
    config = ExecutionClientConfig()
    cache = Mock()
    cache.instrument.return_value = stock
    cache.positions_open.return_value = []
    cache.orders_open.return_value = []
    node = client_module().AlpacaExecutionClient(
        name="ALPACA",
        config=config,
        cache=cache,
        clock=Clock.new_test(),
        trader_id=TraderId("FIXTURE-001"),
        venue=Venue("ALPACA"),
        account_id=AccountId("ALPACA-fixture"),
        account_type=AccountType.MARGIN,
        oms_type=OmsType.NETTING,
    )
    node.house_prefix = "fixture-"
    node.gateway = boundary().AccountGateway(
        FakeVenue(), AccountPacer(controls(), lambda: 0), lambda: (0, 0)
    )
    node.create_task = lambda coroutine, name: asyncio.create_task(coroutine)
    # These unit helpers wait for receipts; the native hook itself only schedules.
    for name in ("submit_order", "modify_order", "cancel_order", "query_order", "query_account"):
        native_hook = getattr(node, "_" + name)

        async def wait_for_receipt(command, hook=native_hook):
            await hook(command)
            await asyncio.gather(*tuple(node._actions))

        setattr(node, "_" + name, wait_for_receipt)
    node._handle_report = Mock()
    for name in (
        "submitted",
        "denied",
        "rejected",
        "updated",
        "modify_rejected",
        "cancel_rejected",
        "canceled",
        "triggered",
    ):
        setattr(node, f"generate_order_{name}", Mock())
    node.cache.order.return_value = order()
    return node


@pytest.mark.parametrize(
    "event",
    [
        "accepted",
        "rejected",
        "pending_new",
        "stopped",
        "pending_cancel",
        "pending_replace",
        "calculated",
        "suspended",
        "order_replace_rejected",
        "order_cancel_rejected",
    ],
)
def test_trade_events_are_read_as_raw_strings(event):
    async def run():
        node = client()
        await node._submit_order(NS(order=order(), params={}))
        row = next(iter(node.gateway.sdk.rows.values()))
        await node._on_trade_update(
            {
                "stream": "trade_updates",
                "data": {
                    "event": event,
                    "order": row,
                    "timestamp": row["updated_at"],
                },
            }
        )
        if event == "order_replace_rejected":
            node.generate_order_modify_rejected.assert_called_once()
        elif event == "order_cancel_rejected":
            node.generate_order_cancel_rejected.assert_called_once()
        else:
            assert node._handle_report.called

    asyncio.run(run())


def test_fake_venue_models_session_trigger_and_wash_refusal():
    node = client()
    venue = node.gateway.sdk
    payload = boundary().submit_payload(
        order(order_type=OrderType.TRAILING_STOP_MARKET, side=OrderSide.SELL), {}, "fixture-"
    )
    venue.post("/orders", payload)
    venue.regular = False
    venue.quote("1")
    assert venue.quote("0.5")[0]["status"] == "new"
    venue.regular = True
    assert venue.quote("0.5")[0]["status"] == "stopped"
    with pytest.raises(ValueError, match="wash"):
        venue.post("/orders", boundary().submit_payload(order(), {}, "fixture-"))
    with pytest.raises(ValueError, match="LIMIT"):
        venue.post("/orders", payload | {"extended_hours": True})


def test_missing_fill_commission_is_unavailable_not_zero():
    async def run():
        node = client()
        await node._submit_order(NS(order=order(), params={}))
        row = next(iter(node.gateway.sdk.rows.values()))
        update = {
            "stream": "trade_updates",
            "data": {
                "event": "fill",
                "order": row,
                "execution_id": "fixture-fill",
                "price": "0.1234",
                "qty": "9",
                "timestamp": row["updated_at"],
            },
        }
        with pytest.raises(client_module().IncompleteCoverage, match="incomplete") as failure:
            await node._on_trade_update(update)
        assert failure.value.failures[0][0] is update
        assert "commission" in str(failure.value.failures[0][1])
        assert not node.coverage_complete

    asyncio.run(run())


def test_stream_fill_with_explicit_evidence_uses_execution_not_order_totals():
    async def run():
        from nautilus_trader.model import Money

        node = client()
        await node._submit_order(NS(order=order(), params={}))
        row = next(iter(node.gateway.sdk.rows.values()))
        node.commission_for_fill = lambda data: Money.from_str("0.01 USD")
        node._handle_report.reset_mock()
        update = {
            "stream": "trade_updates",
            "data": {
                "event": "partial_fill",
                "order": row,
                "execution_id": "fixture-fill",
                "price": "0.1234",
                "qty": "1",
                "timestamp": row["updated_at"],
            },
        }
        await node._on_trade_update(update)
        report = node._handle_report.call_args.args[0]
        assert report.last_qty == Quantity.from_str("1")
        assert report.commission == Money.from_str("0.01 USD")
        assert report.client_order_id == ClientOrderId("fixture-entry")

    asyncio.run(run())


def test_bad_stream_row_preserves_payload_and_revokes_coverage():
    async def run():
        node = client()
        await node._submit_order(NS(order=order(), params={}))
        row = dict(next(iter(node.gateway.sdk.rows.values())), status="future_state")
        node.coverage_complete = True
        update = {
            "stream": "trade_updates",
            "data": {"event": "new", "order": row, "timestamp": row["updated_at"]},
        }
        with pytest.raises(client_module().IncompleteCoverage) as failure:
            await node._on_trade_update(update)
        assert failure.value.failures[0][0] is update
        assert not node.coverage_complete

    asyncio.run(run())


def test_gateway_configuration_is_serialized_and_missing_rows_stop_before_sdk(monkeypatch):
    from sextant.alpaca.config import AlpacaExecutionClientConfig

    config = AlpacaExecutionClientConfig(
        api_key_env="FIXTURE_KEY",
        api_secret_env="FIXTURE_SECRET",  # noqa: S106 - environment name, not a key.
        account_id="ALPACA-fixture",
        house_prefix="fixture-",
        pacing_rows=None,
    )
    assert config.dict()["house_prefix"] == "fixture-"
    sdk = Mock()
    monkeypatch.setattr(client_module(), "TradingClient", sdk)
    node = client()
    node.config = config
    node.house_prefix = "fixture-"
    with pytest.raises(ValueError, match="pacing"):
        asyncio.run(node._connect())
    sdk.assert_not_called()


def test_stream_callback_does_not_hold_client_on_sdk_thread(monkeypatch):
    import gc
    import weakref
    from unittest.mock import AsyncMock

    from .conftest import controls

    class Stream:
        def subscribe_trade_updates(self, handler):
            self.handler = handler

        def run(self):
            raise AssertionError("offline proof must not start SDK transport")

    stream = Stream()
    monkeypatch.setenv("FIXTURE_KEY", "dummy-key")
    monkeypatch.setenv("FIXTURE_SECRET", "dummy-secret")
    node = client()
    fixture_controls = controls()
    monkeypatch.setattr(client_module().Controls, "from_rows", lambda rows: fixture_controls)
    monkeypatch.setattr(client_module(), "TradingClient", Mock())
    monkeypatch.setattr(client_module(), "TradingStream", lambda *a, **k: stream)
    node.config = NS(pacing_rows=[], api_key_env="FIXTURE_KEY", api_secret_env="FIXTURE_SECRET")  # noqa: S106 - fixture environment name
    node._do_query_account = AsyncMock()
    node.commission_for_fill = lambda data: Money.from_str("0.01 USD")  # Fixture evidence only.
    node.create_task = lambda coroutine, name: coroutine.close()
    asyncio.run(node._connect())
    reference = weakref.ref(node)
    del node
    gc.collect()
    assert reference() is None, "SDK callback must only retain a weak client reference"


def test_account_report_rejects_float_money_before_emission():
    async def run():
        node = client()
        node.generate_account_state = Mock()
        node.gateway.sdk.get = Mock(
            return_value={
                "equity": 100.1,
                "cash": "100.00",
                "buying_power": "100.00",
                "currency": "USD",
            }
        )
        with pytest.raises(ValueError, match="decimal"):
            await node._query_account(None)
        node.generate_account_state.assert_not_called()

    asyncio.run(run())


def test_trade_stream_shutdown_cancels_pending_connect_and_joins(monkeypatch):
    from threading import Event
    from unittest.mock import AsyncMock

    from alpaca.trading.stream import TradingStream

    from .conftest import controls

    async def run():
        node = client()
        fixture_controls = controls()
        stream = TradingStream("fixture-key", "fixture-secret", paper=True, raw_data=True)
        started, closed = Event(), Event()
        owner = []

        async def connecting():
            stream._loop = asyncio.get_running_loop()
            owner.append((stream._loop, asyncio.current_task()))
            started.set()
            await asyncio.Event().wait()  # Model a connect/auth await that does not finish.

        async def close():
            closed.set()

        monkeypatch.setattr(stream, "_run_forever", connecting)
        monkeypatch.setattr(stream, "close", close)
        monkeypatch.setenv("FIXTURE_KEY", "dummy-key")
        monkeypatch.setenv("FIXTURE_SECRET", "dummy-secret")
        monkeypatch.setattr(client_module().Controls, "from_rows", lambda rows: fixture_controls)
        monkeypatch.setattr(client_module(), "TradingClient", Mock())
        monkeypatch.setattr(client_module(), "TradingStream", lambda *a, **k: stream)
        node.config = NS(pacing_rows=[], api_key_env="FIXTURE_KEY", api_secret_env="FIXTURE_SECRET")  # noqa: S106 - fixture environment name  # noqa: S106 - fixture env name
        node._do_query_account = AsyncMock()
        node.commission_for_fill = lambda data: Money.from_str("0.01 USD")  # Fixture evidence only.
        node.create_task = lambda coro, name: asyncio.create_task(coro)
        await node._connect()
        assert await asyncio.to_thread(started.wait, 1)
        try:
            await asyncio.wait_for(node._disconnect(), 0.2)
            assert closed.is_set()
            assert node._stream_task is None or node._stream_task.done()
        finally:
            loop, task = owner[0]
            if not loop.is_closed():
                loop.call_soon_threadsafe(task.cancel)

    asyncio.run(run())


def test_partly_filled_entry_can_cancel_its_unfilled_remainder():
    async def run():
        node = client()
        await node._submit_order(NS(order=order(), params={}))
        row = next(iter(node.gateway.sdk.rows.values()))
        row.update(status="partially_filled", filled_qty="1", filled_avg_price="0.1234")
        update = {
            "stream": "trade_updates",
            "data": {
                "event": "partial_fill",
                "order": row,
                "execution_id": "fixture-fill",
                "price": "0.1234",
                "qty": "1",
                "timestamp": row["updated_at"],
            },
        }
        with pytest.raises(client_module().IncompleteCoverage):
            await node._on_trade_update(update)
        await node._cancel_order(
            command(client_order_id=ClientOrderId("fixture-entry"), venue_order_id=None)
        )
        assert node.gateway.sdk.requests[-1][0] == "DELETE"

    asyncio.run(run())


def test_missing_commission_evidence_keeps_writer_unavailable_before_sdk(monkeypatch):
    from .conftest import controls

    node = client()
    fixture_controls = controls()
    node.config = NS(pacing_rows=[], api_key_env="FIXTURE_KEY", api_secret_env="FIXTURE_SECRET")  # noqa: S106 - fixture environment name
    monkeypatch.setattr(client_module().Controls, "from_rows", lambda rows: fixture_controls)
    sdk = Mock()
    monkeypatch.setattr(client_module(), "TradingClient", sdk)
    monkeypatch.delenv("FIXTURE_KEY", raising=False)
    monkeypatch.delenv("FIXTURE_SECRET", raising=False)
    with pytest.raises(ValueError, match="commission"):
        asyncio.run(node._connect())
    sdk.assert_not_called()


def test_connect_uses_registered_account_budget_without_a_second_code_pin(monkeypatch):
    from unittest.mock import AsyncMock

    from .conftest import controls

    node = client()
    fixture_controls = controls(request_budget=150)
    node.config = NS(pacing_rows=[], api_key_env="FIXTURE_KEY", api_secret_env="FIXTURE_SECRET")  # noqa: S106 - fixture environment name
    node.commission_for_fill = lambda data: Money.from_str("0.01 USD")  # Fixture evidence only.
    node._do_query_account = AsyncMock()
    node.create_task = lambda coroutine, name: coroutine.close()
    monkeypatch.setenv("FIXTURE_KEY", "dummy-key")
    monkeypatch.setenv("FIXTURE_SECRET", "dummy-secret")
    monkeypatch.setattr(client_module().Controls, "from_rows", lambda rows: fixture_controls)
    sdk = Mock()
    monkeypatch.setattr(client_module(), "TradingClient", sdk)
    monkeypatch.setattr(client_module(), "TradingStream", Mock())
    asyncio.run(node._connect())
    assert node.gateway.pacer.controls is fixture_controls
    assert node.gateway.pacer.bucket.limit == fixture_controls["request_budget"]
    sdk.assert_called_once()
