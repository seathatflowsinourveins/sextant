"""Convert Alpaca snapshots to Nautilus reconciliation reports.

Sources read 2026-11-10: alpaca-py@cc4cb3b7 alpaca/trading/{models,enums}.py,
https://docs.alpaca.markets/us/docs/orders-at-alpaca,
https://docs.alpaca.markets/us/docs/websocket-streaming,
and https://docs.alpaca.markets/us/docs/position-average-entry-price-calculation.
NautilusTrader@d53849b docs/developer_guide/{python_adapters,adapters}.md,
crates/adapters/{architect_ax,coinbase}/src/http/parse.rs,
crates/adapters/okx/src/websocket/parse.rs,
crates/execution/src/reconciliation/orders.rs, crates/model/src/orders/trailing_stop_market.rs
and python/nautilus_trader/model/__init__.pyi.
"""

import logging
from decimal import Decimal

from alpaca.trading import enums as alpaca
from alpaca.trading.models import Order, Position, TradeUpdate
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    AccountId,
    AvgPxReconciliation,
    ClientOrderId,
    FillReport,
    InstrumentId,
    LiquiditySide,
    Money,
    OrderSide,
    OrderStatus,
    OrderStatusReport,
    OrderType,
    PositionSide,
    PositionStatusReport,
    Price,
    Quantity,
    TimeInForce,
    TradeId,
    TrailingOffsetType,
    TriggerType,
    VenueOrderId,
)

_LOG = logging.getLogger(__name__)

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
_POSITION_SIDE = {
    alpaca.PositionSide.LONG: PositionSide.LONG,
    alpaca.PositionSide.SHORT: PositionSide.SHORT,
}
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
    client_order_id: ClientOrderId | None = None,
) -> OrderStatusReport | None:
    """Map a simple equity snapshot, skipping statuses outside the engine lifecycle.

    The caller supplies the stable engine ID after resolving replacement lineage.
    A PATCH response alone can be a proposal (Alpaca's Replace Order by ID reference).
    """
    status = _STATUS.get(order.status)
    if status is None:
        _LOG.warning(
            "Skipping unmapped Alpaca order status %s for venue order %s on %s",
            order.status.value,
            order.id,
            instrument_id,
        )
        return None
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
        client_order_id=client_order_id or ClientOrderId(order.client_order_id),
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


def position_status_report(
    position: Position,
    *,
    account_id: AccountId,
    instrument_id: InstrumentId,
    ts_init: int,
) -> PositionStatusReport:
    """Map an open equity position at snapshot observation time."""
    if position.asset_class != alpaca.AssetClass.US_EQUITY:
        raise ValueError("Alpaca position report requires a US equity")
    side = _POSITION_SIDE[position.side]
    quantity = Decimal(position.qty)
    if (
        not quantity.is_finite()
        or quantity.is_zero()
        or (side == PositionSide.LONG and quantity < 0)
    ):
        raise ValueError("Alpaca open position report has inconsistent share quantity")
    avg_entry_price = Decimal(position.avg_entry_price)
    if not avg_entry_price.is_finite() or avg_entry_price < 0:
        raise ValueError("Alpaca position report has invalid average entry price")

    # Alpaca's cost basis can change overnight without a fill.
    return PositionStatusReport(
        account_id=account_id,
        instrument_id=instrument_id,
        position_side=side,
        quantity=Quantity.from_decimal(quantity.copy_abs()),
        ts_last=ts_init,
        ts_init=ts_init,
        avg_px_open=avg_entry_price or None,
        avg_px_open_reconciliation=AvgPxReconciliation.OPENING_ONLY,
    )


def fill_report(
    update: TradeUpdate,
    *,
    account_id: AccountId,
    instrument_id: InstrumentId,
    ts_init: int,
    commission: Money,
    client_order_id: ClientOrderId | None = None,
) -> FillReport | None:
    """Map one stream execution. The caller supplies commission evidence."""
    if update.event not in (alpaca.TradeEvent.FILL, alpaca.TradeEvent.PARTIAL_FILL):
        return None
    order = update.order
    if order.asset_class != alpaca.AssetClass.US_EQUITY or order.side is None:
        raise ValueError("Alpaca fill report requires a US equity and side")
    if update.execution_id is None or update.price is None or update.qty is None:
        raise ValueError("Alpaca fill report requires execution ID, fill price and fill quantity")

    # The SDK models these wire numbers as floats. Convert their decimal text at the boundary.
    price = Decimal(str(update.price))
    quantity = Decimal(str(update.qty))
    if not price.is_finite() or not quantity.is_finite() or price <= 0 or quantity <= 0:
        raise ValueError("Alpaca fill report requires positive finite fill price and quantity")

    return FillReport(
        account_id=account_id,
        instrument_id=instrument_id,
        venue_order_id=VenueOrderId(str(order.id)),
        trade_id=TradeId(str(update.execution_id)),
        order_side=_SIDE[order.side],
        last_qty=Quantity.from_decimal(quantity),
        last_px=Price.from_decimal(price),
        commission=commission,
        liquidity_side=LiquiditySide.NO_LIQUIDITY_SIDE,
        ts_event=dt_to_unix_nanos(update.timestamp),
        ts_init=ts_init,
        client_order_id=client_order_id or ClientOrderId(order.client_order_id),
    )
