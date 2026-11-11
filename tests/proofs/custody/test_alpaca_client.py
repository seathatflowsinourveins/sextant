"""Native Alpaca hooks and venue witness; sources in the execution module."""

import asyncio
import importlib.util
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from nautilus_trader.model import ClientOrderId, Money, OrderSide, OrderType, Price, Quantity

from sextant.execution.pacer import AccountPacer

from .test_alpaca_execution import boundary, order


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
