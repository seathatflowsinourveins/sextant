"""B's owner-fill protector on alpaca-py's TradingClient and TradingStream (clean B PR-1).

The protector covers every unreserved whole long share with exactly one native trailing stop
of the full net quantity, re-arms it on every change, and never cancels, replaces or resizes
an owner order. Outside regular market hours it pages instead of writing, because the native
trailing stop does not trigger there; PR-2 owns the 24/5 path.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.models import Order, Position, TradeAccount, TradeUpdate
from alpaca.trading.requests import GetOrdersRequest, OrderRequest, TrailingStopOrderRequest
from alpaca.trading.stream import TradingStream

from sextant.paper.config import PaperAccount
from sextant.paper.sessions import Session, session_at

B_LANE = "alpaca-paper-b"
TRAIL_PERCENT_NAME = "native_trail_fraction"
PARAMETER_NAMES = frozenset({TRAIL_PERCENT_NAME})
PARAMETER_KEYS = frozenset({"name", "unit", "value", "source", "calibration_state", "last_change"})
MAX_TRAIL_FRACTION = Decimal("0.025")
FILL_EVENTS = frozenset({"fill", "partial_fill"})
TERMINAL_EVENTS = frozenset({"canceled", "expired", "rejected", "stopped", "done_for_day"})
OPEN_ORDER_LIMIT = 500
MAX_CLIENT_ORDER_ID = 128


class ProtectorRefusal(RuntimeError):
    """The protector will not act on this account or order."""


@dataclass(frozen=True)
class Page:
    """One operator alert; the runner decides where it goes."""

    reason: str
    symbol: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class BParameters:
    """B's one reviewed starting parameter, UNCALIBRATED."""

    native_trail_fraction: Decimal

    def __post_init__(self) -> None:
        fraction = _decimal(self.native_trail_fraction, TRAIL_PERCENT_NAME)
        object.__setattr__(self, "native_trail_fraction", fraction)
        if fraction <= 0 or fraction > MAX_TRAIL_FRACTION:
            raise ValueError("native_trail_fraction must be in (0, 0.025]")


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int) and not isinstance(value, bool):
        result = Decimal(value)
    elif isinstance(value, str):
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"{field} must be a decimal string") from exc
    else:
        raise ValueError(f"{field} must be a Decimal, int or string")
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def load_b_parameters(path: Path) -> BParameters:
    """Read B's registry rows, refusing anything not reviewed and UNCALIBRATED."""

    try:
        rows = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path.name}") from exc
    if not isinstance(rows, list):
        raise ValueError("B parameter registry must be a list")
    values: dict[str, Decimal] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != PARAMETER_KEYS:
            raise ValueError("B parameter row has the wrong keys")
        name = row["name"]
        if not isinstance(name, str) or name not in PARAMETER_NAMES or name in values:
            raise ValueError("B parameter row has an unknown or duplicate name")
        if row["calibration_state"] != "UNCALIBRATED":
            raise ValueError("B parameters start UNCALIBRATED")
        for key in ("unit", "value", "source", "last_change"):
            if not isinstance(row[key], str) or not row[key].strip():
                raise ValueError(f"B parameter row needs a nonempty {key}")
        try:
            date.fromisoformat(row["last_change"])
        except ValueError as exc:
            raise ValueError("B parameter last_change must be an ISO date") from exc
        values[name] = _decimal(row["value"], name)
    if set(values) != PARAMETER_NAMES:
        raise ValueError("B parameter registry is incomplete")
    return BParameters(values[TRAIL_PERCENT_NAME])


class TradingClientLike(Protocol):
    def get_account(self) -> TradeAccount: ...

    def get_all_positions(self) -> list[Position]: ...

    def get_orders(self, filter: GetOrdersRequest | None = None) -> list[Order]: ...

    def submit_order(self, order_data: OrderRequest) -> Any: ...

    def cancel_order_by_id(self, order_id: object) -> None: ...


def _event_name(event: object) -> str:
    return str(getattr(event, "value", event))


def _leaves(order: Order) -> Decimal:
    quantity = _decimal(order.qty or "0", "order.qty")
    filled = _decimal(order.filled_qty or "0", "order.filled_qty")
    return quantity - filled


def _safe_symbol(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", symbol)[:40]


class Protector:
    """B's one-account protector; the client is called, never constructed here."""

    def __init__(
        self,
        client: TradingClientLike,
        account: PaperAccount,
        parameters: BParameters,
        *,
        now_ns: Callable[[], int] = time.time_ns,
        on_page: Callable[[Page], None] | None = None,
    ) -> None:
        if account.lane != B_LANE:
            raise ProtectorRefusal("B's protector runs only on the slot-2 B paper lane")
        self._client = client
        self._account = account
        self._parameters = parameters
        self._now_ns = now_ns
        self._on_page = on_page
        self.pages: list[Page] = []
        self._cancelling: set[str] = set()
        self._sequence = 0

    def page(self, reason: str, symbol: str | None = None, detail: str = "") -> None:
        page = Page(reason=reason, symbol=symbol, detail=detail)
        self.pages.append(page)
        if self._on_page is not None:
            self._on_page(page)

    def bind(self) -> None:
        """Confirm the broker account number before the stream starts."""

        fetched = self._client.get_account()
        if fetched.account_number != self._account.account_id:
            self.page("account_number_mismatch")
            raise ProtectorRefusal(
                "the broker account number does not match the configured B paper account"
            )

    def handle(self, update: TradeUpdate) -> None:
        symbol = update.order.symbol
        if not symbol:
            return
        event = _event_name(update.event)
        if self._is_ours(update.order):
            self._handle_house(update, symbol, event)
            return
        # Any owner order event may change a reservation or the position: reconcile and
        # re-arm. Non-fill events never freeze the symbol.
        self.reconcile()

    def reconcile(self) -> dict[str, Position]:
        """Match the broker's open orders and positions, then protect the whole net shares.

        Every unreserved whole long share is covered by exactly one house trail of the full
        net quantity; a change in that quantity re-arms it during regular market hours.
        """

        try:
            positions, house, owner_sells, unrecognized = self._snapshot()
        except ProtectorRefusal as exc:
            self.page("open_orders_truncated", None, str(exc))
            return {}
        for symbol, position in positions.items():
            self._reconcile_symbol(
                symbol,
                position,
                house.pop(symbol, []),
                owner_sells.get(symbol, Decimal(0)),
                symbol in unrecognized,
            )
        for symbol, ours in house.items():
            if symbol not in positions:
                for order in ours:
                    self._cancel(order, "flat_with_house_exit")
        return positions

    def _snapshot(
        self,
    ) -> tuple[
        dict[str, Position],
        dict[str, list[Order]],
        dict[str, Decimal],
        set[str],
    ]:
        """Read positions and open orders, without changing anything at the broker."""

        positions = {
            position.symbol: position
            for position in self._client.get_all_positions()
            if position.symbol
        }
        orders = self._client.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=OPEN_ORDER_LIMIT)
        )
        if len(orders) >= OPEN_ORDER_LIMIT:
            raise ProtectorRefusal("open order snapshot hit the page limit and may be truncated")
        house: dict[str, list[Order]] = {}
        owner_sells: dict[str, Decimal] = {}
        unrecognized: set[str] = set()
        for order in orders:
            if not order.symbol:
                continue
            if self._is_ours(order):
                house.setdefault(order.symbol, []).append(order)
                continue
            side = _event_name(order.side).lower()
            if side == "sell":
                leaves = owner_sells.get(order.symbol, Decimal(0)) + _leaves(order)
                owner_sells[order.symbol] = leaves
            elif side != "buy":
                unrecognized.add(order.symbol)
        return positions, house, owner_sells, unrecognized

    def _cancel_all(self, ours: list[Order], reason: str) -> None:
        for order in ours:
            self._cancel(order, reason)

    def _cancel_excess(self, ours: list[Order], protective: int, reason: str) -> list[Order]:
        """Cancel house exits beyond one trail no larger than the protective quantity."""

        if len(ours) > 1:
            eligible = [order for order in ours if _leaves(order) <= protective]
            keeper = max(eligible, key=_leaves) if eligible else None
            for order in ours:
                if order is not keeper:
                    self._cancel(order, reason)
            return [keeper] if keeper is not None else []
        if ours and _leaves(ours[0]) > protective:
            self._cancel(ours[0], reason)
            return []
        return list(ours)

    def _handle_house(self, update: TradeUpdate, symbol: str, event: str) -> None:
        if event in FILL_EVENTS:
            self.reconcile()
            return
        order_id = str(update.order.id)
        if event == "replaced":
            self.page("house_exit_lost", symbol, "a house exit was replaced elsewhere")
            self.reconcile()
            return
        if event in TERMINAL_EVENTS:
            known = order_id in self._cancelling
            self._cancelling.discard(order_id)
            if not known:
                self.page("house_exit_lost", symbol, f"a house exit ended {event}")
            self.reconcile()

    def _reconcile_symbol(
        self,
        symbol: str,
        position: Position,
        ours: list[Order],
        owner_sell_reserved: Decimal,
        unrecognized_open_order: bool,
    ) -> None:
        quantity = _decimal(position.qty, "position.qty")
        if quantity < 0:
            self.page("short_position_unprotected", symbol)
            self._cancel_all(ours, "short_position")
            return
        if quantity == 0:
            self._cancel_all(ours, "flat_with_house_exit")
            return
        if unrecognized_open_order:
            self.page(
                "unrecognized_open_order",
                symbol,
                "an open order has no buy/sell side; only owner sells are netted out",
            )
        available = quantity - owner_sell_reserved
        protective = 0
        if available > 0:
            protective = int(available.to_integral_value(rounding=ROUND_FLOOR))
        if quantity != quantity.to_integral_value() or available != protective:
            self.page("fractional_custody_unverified", symbol)
        if protective == 0:
            self._cancel_all(ours, "owner_reserved_unprotected")
            self.page("owner_reserved_unprotected", symbol)
            return
        in_rth = session_at(self._now_ns()) is Session.RTH
        # An oversized GTC trail is cancelled before the RTH guard, so it can never
        # ride into the next open; only the replacement submit waits for RTH.
        rest = self._cancel_excess(ours, protective, "rearm_full_protective_quantity")
        if len(rest) == 1 and _leaves(rest[0]) == protective:
            if not in_rth:
                self.page(
                    "unprotected_outside_rth_until_pr2",
                    symbol,
                    "the resting native trail does not trigger outside regular market hours",
                )
            return
        if not in_rth:
            self.page("unprotected_outside_rth_until_pr2", symbol)
            return
        for order in rest:
            self._cancel(order, "rearm_full_protective_quantity")
        # The terminal canceled event of the house's own trail drives reconcile(),
        # which submits the single replacement; never submit over a live exit.
        if ours:
            return
        self._submit_trail(symbol, protective)

    def _submit_trail(self, symbol: str, whole: int) -> None:
        self._sequence += 1
        client_order_id = (
            f"{self._account.house_prefix}trail-{_safe_symbol(symbol)}-"
            f"{self._now_ns()}-{self._sequence}"
        )
        request = TrailingStopOrderRequest(
            symbol=symbol,
            qty=whole,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            trail_percent=float(self._parameters.native_trail_fraction * 100),
            client_order_id=client_order_id[:MAX_CLIENT_ORDER_ID],
        )
        try:
            self._client.submit_order(request)
        except Exception as exc:
            self.page("trail_submit_failed", symbol, type(exc).__name__)

    def _cancel(self, order: Order, reason: str) -> bool:
        if not self._is_ours(order):
            raise ProtectorRefusal("refusing to cancel an order the house does not own")
        order_id = str(order.id)
        self._cancelling.add(order_id)
        try:
            self._client.cancel_order_by_id(order.id)
        except Exception as exc:
            self._cancelling.discard(order_id)
            self.page("cancel_failed", order.symbol, f"{reason}: {type(exc).__name__}")
            return False
        return True

    def _is_ours(self, order: Order) -> bool:
        return bool(order.client_order_id) and order.client_order_id.startswith(
            self._account.house_prefix
        )


class ProtectorStream(TradingStream):
    """The SDK's trade-update stream with a reconcile hook on every (re)connect."""

    def __init__(
        self,
        client: TradingClientLike,
        account: PaperAccount,
        parameters: BParameters,
        *,
        api_key: str,
        secret_key: str,
        paper: bool = True,
        url_override: str | None = None,
        now_ns: Callable[[], int] = time.time_ns,
        on_page: Callable[[Page], None] | None = None,
    ) -> None:
        if url_override is None:
            super().__init__(api_key=api_key, secret_key=secret_key, paper=paper)
        else:
            super().__init__(
                api_key=api_key,
                secret_key=secret_key,
                paper=paper,
                url_override=url_override,
            )
        self.protector = Protector(client, account, parameters, now_ns=now_ns, on_page=on_page)
        self.subscribe_trade_updates(self._on_trade_update)

    async def _on_trade_update(self, update: TradeUpdate) -> None:
        try:
            self.protector.handle(update)
        except Exception as exc:
            self.protector.page("trade_update_failed", update.order.symbol, type(exc).__name__)

    async def _start_ws(self) -> None:
        await super()._start_ws()
        try:
            self.protector.reconcile()
        except Exception as exc:
            self.protector.page("reconcile_failed", None, type(exc).__name__)

    def run(self) -> None:
        self.protector.bind()
        super().run()
