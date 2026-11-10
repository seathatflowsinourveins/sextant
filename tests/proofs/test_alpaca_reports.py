"""Offline report proof from the pinned SDK schema and Nautilus adapter template.

Sources read 2026-11-10: alpaca-py@cc4cb3b7 alpaca/trading/{models,enums}.py
and NautilusTrader@d53849b python/tests/integration/test_python_adapter_template.py.
Synthetic replacement snapshots follow PatchVenue in test_b_owner_sell_patch.py
on lead/b-event-book-on-main and Alpaca's Replace Order by ID reference.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from alpaca.trading.models import Order
from nautilus_trader.model import (
    AccountId,
    ClientOrderId,
    InstrumentId,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    TrailingOffsetType,
    TriggerType,
    VenueOrderId,
)

from sextant.alpaca.reports import order_status_report

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
def test_report_refuses_venue_status_without_a_faithful_mapping(status):
    with pytest.raises(ValueError, match=status):
        order_status_report(
            snapshot(status=status),
            account_id=ACCOUNT,
            instrument_id=INSTRUMENT,
            ts_init=INITIALIZED_NS,
        )


def test_confirmed_trailing_successor_preserves_venue_id_and_basis_point_offset():
    successor = snapshot(
        id=str(UUID(int=2)),
        replaces=str(UUID(int=1)),
        type="trailing_stop",
        qty="9",
        limit_price=None,
        stop_price="0.1087",
        trail_percent="2.125",
        time_in_force="gtc",
    )
    report = order_status_report(
        successor, account_id=ACCOUNT, instrument_id=INSTRUMENT, ts_init=INITIALIZED_NS
    )

    assert report.venue_order_id == VenueOrderId(str(UUID(int=2)))
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
