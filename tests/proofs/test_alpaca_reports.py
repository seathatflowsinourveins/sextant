"""Offline report proof from the pinned SDK schema and Nautilus adapter template.

Sources read 2026-11-10: alpaca-py@cc4cb3b7 alpaca/trading/{models,enums}.py
and NautilusTrader@d53849b python/tests/integration/test_python_adapter_template.py.
Synthetic SDK snapshots follow the Alpaca streaming and position examples
and the lead's venue fake on lead/b-event-book-on-main.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from alpaca.trading.models import Order, Position, TradeUpdate
from nautilus_trader.model import (
    AccountId,
    AvgPxReconciliation,
    ClientOrderId,
    InstrumentId,
    LiquiditySide,
    Money,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    TimeInForce,
    TradeId,
    TrailingOffsetType,
    TriggerType,
    VenueOrderId,
)

from sextant.alpaca.reports import fill_report, order_status_report, position_status_report

ACCOUNT = AccountId("ALPACA-TEST")
INSTRUMENT = InstrumentId.from_str("TEST.ALPACA")
INITIALIZED_NS = 3_000_000_000


def snapshot(**fields: object) -> Order:
    return Order.model_validate(
        {
            "id": str(UUID(int=1)),
            "client_order_id": "synthetic-order",
            "created_at": "1970-01-01T00:00:00Z",
            "submitted_at": "1970-01-01T00:00:01Z",
            "updated_at": "1970-01-01T00:00:02.000001Z",
            "asset_class": "us_equity",
            "symbol": "TEST",
            "side": "sell",
            "type": "limit",
            "time_in_force": "day",
            "qty": "9.123456789",
            "filled_qty": "0",
            "limit_price": "0.1234",
            "status": "new",
            "extended_hours": False,
        }
        | fields
    )


def test_partial_limit_snapshot_preserves_decimal_fields_and_timestamps():
    order = snapshot(
        status="partially_filled", filled_qty="1.000000009", filled_avg_price="0.12345"
    )
    report = order_status_report(
        order, account_id=ACCOUNT, instrument_id=INSTRUMENT, ts_init=INITIALIZED_NS
    )

    assert report is not None
    assert (report.account_id, report.instrument_id) == (ACCOUNT, INSTRUMENT)
    assert report.client_order_id == ClientOrderId("synthetic-order")
    assert report.venue_order_id == VenueOrderId(str(UUID(int=1)))
    assert (report.order_side, report.order_type) == (OrderSide.SELL, OrderType.LIMIT)
    assert (report.time_in_force, report.order_status) == (
        TimeInForce.DAY,
        OrderStatus.PARTIALLY_FILLED,
    )
    assert report.quantity.as_decimal() == Decimal("9.123456789")
    assert report.filled_qty.as_decimal() == Decimal("1.000000009")
    assert report.price is not None and report.price.as_decimal() == Decimal("0.1234")
    assert report.avg_px == Decimal("0.12345")
    assert (report.ts_accepted, report.ts_last, report.ts_init) == (
        1_000_000_000,
        2_000_001_000,
        INITIALIZED_NS,
    )


@pytest.mark.parametrize(
    ("status", "filled_qty", "expected"),
    [
        pytest.param("new", "0", OrderStatus.ACCEPTED, id="new"),
        pytest.param("accepted", "0", OrderStatus.ACCEPTED, id="accepted"),
        pytest.param("filled", "9.123456789", OrderStatus.FILLED, id="filled"),
        pytest.param("canceled", "0", OrderStatus.CANCELED, id="canceled"),
        pytest.param("expired", "0", OrderStatus.EXPIRED, id="expired"),
        pytest.param("rejected", "0", OrderStatus.REJECTED, id="rejected"),
        pytest.param("pending_cancel", "0", OrderStatus.PENDING_CANCEL, id="pending_cancel"),
        pytest.param("pending_replace", "0", OrderStatus.PENDING_UPDATE, id="pending_replace"),
    ],
)
def test_report_preserves_supported_venue_status(status, filled_qty, expected):
    report = order_status_report(
        snapshot(status=status, filled_qty=filled_qty),
        account_id=ACCOUNT,
        instrument_id=INSTRUMENT,
        ts_init=INITIALIZED_NS,
    )
    assert report is not None
    assert report.order_status == expected


@pytest.mark.parametrize(
    "status",
    [
        "done_for_day",
        "replaced",
        "pending_review",
        "pending_new",
        "accepted_for_bidding",
        "stopped",
        "suspended",
        "calculated",
        "held",
    ],
)
def test_report_logs_and_skips_venue_status_without_a_faithful_mapping(status, caplog):
    report = order_status_report(
        snapshot(status=status),
        account_id=ACCOUNT,
        instrument_id=INSTRUMENT,
        ts_init=INITIALIZED_NS,
    )
    assert report is None
    assert any(
        record.levelname == "WARNING" and status in record.message for record in caplog.records
    )


def test_confirmed_trailing_successor_preserves_venue_id_and_basis_point_offset():
    successor = snapshot(
        id=str(UUID(int=2)),
        client_order_id="synthetic-successor",
        replaces=str(UUID(int=1)),
        type="trailing_stop",
        qty="9",
        limit_price=None,
        stop_price="0.1087",
        trail_percent="2.125",
        time_in_force="gtc",
    )
    stable_id = ClientOrderId("synthetic-order")
    report = order_status_report(
        successor,
        account_id=ACCOUNT,
        instrument_id=INSTRUMENT,
        ts_init=INITIALIZED_NS,
        client_order_id=stable_id,
    )

    assert report is not None
    assert report.venue_order_id == VenueOrderId(str(UUID(int=2)))
    assert report.client_order_id == stable_id
    assert report.order_type == OrderType.TRAILING_STOP_MARKET
    assert report.time_in_force == TimeInForce.GTC
    assert report.trigger_type == TriggerType.DEFAULT
    assert report.trigger_price is not None and report.trigger_price.as_decimal() == Decimal(
        "0.1087"
    )
    assert report.trailing_offset == Decimal("212.5")
    assert report.trailing_offset_type == TrailingOffsetType.BASIS_POINTS


def test_notional_snapshot_without_share_quantity_is_refused():
    with pytest.raises(ValueError, match="share quantity"):
        order_status_report(
            snapshot(qty=None, notional="9.00"),
            account_id=ACCOUNT,
            instrument_id=INSTRUMENT,
            ts_init=INITIALIZED_NS,
        )


@pytest.mark.parametrize(
    ("side", "qty", "expected"),
    [
        pytest.param("long", "5.000000009", PositionSide.LONG, id="long"),
        pytest.param("short", "-5.000000009", PositionSide.SHORT, id="short"),
    ],
)
def test_position_uses_total_shares_and_opening_only_cost_basis(side, qty, expected):
    position = Position.model_validate(
        {
            "asset_id": str(UUID(int=3)),
            "symbol": "TEST",
            "exchange": "NASDAQ",
            "asset_class": "us_equity",
            "avg_entry_price": "1.23456789",
            "qty": qty,
            "qty_available": "2",
            "cost_basis": "6.17283946",
            "side": side,
        }
    )

    report = position_status_report(
        position, account_id=ACCOUNT, instrument_id=INSTRUMENT, ts_init=INITIALIZED_NS
    )

    assert (report.account_id, report.instrument_id) == (ACCOUNT, INSTRUMENT)
    assert report.position_side == expected
    assert report.quantity.as_decimal() == Decimal("5.000000009")
    assert report.avg_px_open == Decimal("1.23456789")
    assert report.avg_px_open_reconciliation == AvgPxReconciliation.OPENING_ONLY
    assert report.venue_position_id is None
    assert (report.ts_last, report.ts_init) == (INITIALIZED_NS, INITIALIZED_NS)


def trade_update(**fields: object) -> TradeUpdate:
    return TradeUpdate.model_validate(
        {
            "event": "partial_fill",
            "execution_id": str(UUID(int=4)),
            "order": snapshot(
                status="partially_filled", filled_qty="4.5", filled_avg_price="0.125"
            ).model_dump(mode="json"),
            "timestamp": "1970-01-01T00:00:02.000002Z",
            "position_qty": "3",
            "qty": "1.123456789",
            "price": "0.12456789",
        }
        | fields
    )


@pytest.mark.parametrize("event", ["fill", "partial_fill"])
def test_fill_uses_execution_fields_even_when_order_status_cannot_map(event):
    order = snapshot(status="done_for_day", filled_qty="4.5", filled_avg_price="0.125")
    update = trade_update(event=event, order=order.model_dump(mode="json"))
    commission = Money.from_str("0.01 USD")
    stable_id = ClientOrderId("synthetic-stable")

    report = fill_report(
        update,
        account_id=ACCOUNT,
        instrument_id=INSTRUMENT,
        ts_init=INITIALIZED_NS,
        commission=commission,
        client_order_id=stable_id,
    )

    assert report is not None
    assert (report.account_id, report.instrument_id) == (ACCOUNT, INSTRUMENT)
    assert report.client_order_id == stable_id
    assert report.venue_order_id == VenueOrderId(str(UUID(int=1)))
    assert report.trade_id == TradeId(str(UUID(int=4)))
    assert report.order_side == OrderSide.SELL
    assert report.last_qty.as_decimal() == Decimal("1.123456789")
    assert report.last_px.as_decimal() == Decimal("0.12456789")
    assert report.commission == commission
    assert report.liquidity_side == LiquiditySide.NO_LIQUIDITY_SIDE
    assert (report.ts_event, report.ts_init) == (2_000_002_000, INITIALIZED_NS)


@pytest.mark.parametrize("field", ["price", "qty", "execution_id"])
def test_incomplete_fill_raises_instead_of_using_order_totals(field):
    with pytest.raises(ValueError, match="fill"):
        fill_report(
            trade_update(**{field: None}),
            account_id=ACCOUNT,
            instrument_id=INSTRUMENT,
            ts_init=INITIALIZED_NS,
            commission=Money.from_str("0.01 USD"),
        )


def test_non_fill_update_has_no_fill_report():
    assert (
        fill_report(
            trade_update(event="canceled"),
            account_id=ACCOUNT,
            instrument_id=INSTRUMENT,
            ts_init=INITIALIZED_NS,
            commission=Money.from_str("0.01 USD"),
        )
        is None
    )
