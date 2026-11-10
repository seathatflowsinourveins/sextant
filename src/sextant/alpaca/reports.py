"""Convert Alpaca snapshots to Nautilus reconciliation reports.

Sources read 2026-11-10: alpaca-py@cc4cb3b7 alpaca/trading/{models,enums}.py
and https://docs.alpaca.markets/us/docs/orders-at-alpaca.
NautilusTrader@d53849b docs/developer_guide/{python_adapters,adapters}.md,
crates/adapters/coinbase/src/http/parse.rs, crates/adapters/okx/src/websocket/parse.rs,
crates/execution/src/reconciliation/orders.rs, crates/model/src/orders/trailing_stop_market.rs
and python/nautilus_trader/model/__init__.pyi.
"""

from decimal import Decimal

from alpaca.trading import enums as alpaca
from alpaca.trading.models import Order
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    AccountId,
    ClientOrderId,
    InstrumentId,
    OrderSide,
    OrderStatus,
    OrderStatusReport,
    OrderType,
    Price,
    Quantity,
    TimeInForce,
    TrailingOffsetType,
    TriggerType,
    VenueOrderId,
)

_STATUS = {
    alpaca.OrderStatus.NEW: OrderStatus.ACCEPTED,
    alpaca.OrderStatus.ACCEPTED: OrderStatus.ACCEPTED,
    alpaca.OrderStatus.PARTIALLY_FILLED: OrderStatus.PARTIALLY_FILLED,
    alpaca.OrderStatus.FILLED: OrderStatus.FILLED,
    alpaca.OrderStatus.CANCELED: OrderStatus.CANCELED,
    alpaca.OrderStatus.EXPIRED: OrderStatus.EXPIRED,
    alpaca.OrderStatus.REJECTED: OrderStatus.REJECTED,
    alpaca.OrderStatus.PENDING_CANCEL: OrderStatus.PENDING_CANCEL,
    alpaca.OrderStatus.PENDING_REPLACE: OrderStatus.PENDING_UPDATE,
}
_SIDE = {alpaca.OrderSide.BUY: OrderSide.BUY, alpaca.OrderSide.SELL: OrderSide.SELL}
_TYPE = {
    alpaca.OrderType.MARKET: OrderType.MARKET,
    alpaca.OrderType.LIMIT: OrderType.LIMIT,
    alpaca.OrderType.STOP: OrderType.STOP_MARKET,
    alpaca.OrderType.STOP_LIMIT: OrderType.STOP_LIMIT,
    alpaca.OrderType.TRAILING_STOP: OrderType.TRAILING_STOP_MARKET,
}
_TIF = {
    alpaca.TimeInForce.DAY: TimeInForce.DAY,
    alpaca.TimeInForce.GTC: TimeInForce.GTC,
    alpaca.TimeInForce.OPG: TimeInForce.AT_THE_OPEN,
    alpaca.TimeInForce.CLS: TimeInForce.AT_THE_CLOSE,
    alpaca.TimeInForce.IOC: TimeInForce.IOC,
    alpaca.TimeInForce.FOK: TimeInForce.FOK,
}


def order_status_report(
    order: Order,
    *,
    account_id: AccountId,
    instrument_id: InstrumentId,
    ts_init: int,
) -> OrderStatusReport:
    """Map a simple equity snapshot using the venue's client and order IDs.

    The caller resolves replacement lineage before submitting reports to the engine.
    A PATCH response alone can be a proposal (Alpaca's Replace Order by ID reference).
    """
    status = _STATUS.get(order.status)
    if status is None:
        raise ValueError(f"Alpaca order status has no report mapping: {order.status.value}")
    if (
        order.asset_class != alpaca.AssetClass.US_EQUITY
        or order.order_class != alpaca.OrderClass.SIMPLE
    ):
        raise ValueError("Alpaca order report requires a simple equity order")
    if order.qty is None or order.filled_qty is None:
        raise ValueError("Alpaca order report requires ordered and filled share quantity")
    kind = order.type or order.order_type
    if kind is None or order.side is None:
        raise ValueError("Alpaca order report requires order type and side")

    quantity = Decimal(str(order.qty))
    filled_qty = Decimal(str(order.filled_qty))
    if quantity <= 0 or not 0 <= filled_qty <= quantity:
        raise ValueError("Alpaca order report has inconsistent share quantities")

    trigger_type = (
        TriggerType.DEFAULT
        if kind
        in (alpaca.OrderType.STOP, alpaca.OrderType.STOP_LIMIT, alpaca.OrderType.TRAILING_STOP)
        else None
    )
    trailing_offset = None
    trailing_offset_type = None
    if kind == alpaca.OrderType.TRAILING_STOP:
        if (order.trail_price is None) == (order.trail_percent is None):
            raise ValueError("Alpaca trailing stop requires exactly one offset")
        if order.trail_price is not None:
            trailing_offset = Decimal(order.trail_price)
            trailing_offset_type = TrailingOffsetType.PRICE
        elif order.trail_percent is not None:
            trailing_offset = Decimal(order.trail_percent) * 100
            trailing_offset_type = TrailingOffsetType.BASIS_POINTS

    # The SDK supplies submission and update times, with no separate acceptance timestamp.
    return OrderStatusReport(
        account_id=account_id,
        instrument_id=instrument_id,
        venue_order_id=VenueOrderId(str(order.id)),
        order_side=_SIDE[order.side],
        order_type=_TYPE[kind],
        time_in_force=_TIF[order.time_in_force],
        order_status=status,
        quantity=Quantity.from_decimal(quantity),
        filled_qty=Quantity.from_decimal(filled_qty),
        ts_accepted=dt_to_unix_nanos(order.submitted_at),
        ts_last=dt_to_unix_nanos(order.updated_at),
        ts_init=ts_init,
        client_order_id=ClientOrderId(order.client_order_id),
        expire_time=dt_to_unix_nanos(order.expires_at) if order.expires_at is not None else None,
        price=Price.from_decimal(Decimal(str(order.limit_price)))
        if order.limit_price is not None
        else None,
        trigger_price=Price.from_decimal(Decimal(str(order.stop_price)))
        if order.stop_price is not None
        else None,
        trigger_type=trigger_type,
        trailing_offset=trailing_offset,
        trailing_offset_type=trailing_offset_type,
        avg_px=Decimal(str(order.filled_avg_price))
        if filled_qty and order.filled_avg_price is not None
        else None,
    )
