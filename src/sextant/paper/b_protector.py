"""B's owner-fill protector on alpaca-py's TradingClient and TradingStream (clean B PR-1).

The protector claims only positively reconciled owner fills, puts one native trailing stop on
the reconcilable whole shares, and never cancels, replaces or resizes an owner order. Outside
regular market hours it pages instead of submitting, because the native trailing stop does not
trigger there; PR-2 owns the 24/5 path.
"""

from __future__ import annotations

import calendar
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
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
CLAIM_LATENCY_NAME = "claim_max_latency_s"
PARAMETER_NAMES = frozenset({TRAIL_PERCENT_NAME, CLAIM_LATENCY_NAME})
PARAMETER_KEYS = frozenset({"name", "unit", "value", "source", "calibration_state", "last_change"})
MAX_TRAIL_FRACTION = Decimal("0.025")
FILL_EVENTS = frozenset({"fill", "partial_fill"})
RESERVATION_END_EVENTS = frozenset({"canceled", "expired", "done_for_day"})
TERMINAL_EVENTS = frozenset({"canceled", "expired", "rejected", "stopped", "done_for_day"})
OPEN_ORDER_LIMIT = 500
MAX_CLIENT_ORDER_ID = 128
NS_PER_SECOND = Decimal(1_000_000_000)


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
    """B's two reviewed starting parameters, both UNCALIBRATED."""

    native_trail_fraction: Decimal
    claim_max_latency_s: Decimal

    def __post_init__(self) -> None:
        fraction = _decimal(self.native_trail_fraction, TRAIL_PERCENT_NAME)
        latency = _decimal(self.claim_max_latency_s, CLAIM_LATENCY_NAME)
        object.__setattr__(self, "native_trail_fraction", fraction)
        object.__setattr__(self, "claim_max_latency_s", latency)
        if fraction <= 0 or fraction > MAX_TRAIL_FRACTION:
            raise ValueError("native_trail_fraction must be in (0, 0.025]")
        if latency <= 0:
            raise ValueError("claim_max_latency_s must be positive")


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
    return BParameters(values[TRAIL_PERCENT_NAME], values[CLAIM_LATENCY_NAME])


class TradingClientLike(Protocol):
    def get_account(self) -> TradeAccount: ...

    def get_all_positions(self) -> list[Position]: ...

    def get_orders(self, filter: GetOrdersRequest | None = None) -> list[Order]: ...

    def submit_order(self, order_data: OrderRequest) -> Any: ...

    def cancel_order_by_id(self, order_id: object) -> None: ...


def _event_name(event: object) -> str:
    return str(getattr(event, "value", event))


def _timestamp_ns(value: datetime | None) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    seconds = calendar.timegm(value.utctimetuple())
    return seconds * 1_000_000_000 + value.microsecond * 1_000


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
        self.frozen: set[str] = set()
        self._cancelling: set[str] = set()
        self._last_position: dict[str, Decimal] = {}
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
        elif event in FILL_EVENTS:
            self._handle_owner_fill(update, symbol)
        else:
            self._fail_closed(
                symbol,
                "owner_event_fail_closed",
                f"owner order event {event}",
            )
            if event in RESERVATION_END_EVENTS:
                self.reconcile()

    def reconcile(self, *, strict_custody: bool = False) -> dict[str, Position]:
        """Match the broker's open orders and positions, then protect the whole shares.

        On a reconnect ``strict_custody`` refuses to trail a position the protector has not
        already reconciled: newly discovered custody must be claimed by an owner fill first.
        """

        try:
            positions, house, owner_sells, unrecognized = self._snapshot()
        except ProtectorRefusal as exc:
            self.page("open_orders_truncated", None, str(exc))
            return {}
        for symbol, position in positions.items():
            quantity = _decimal(position.qty, "position.qty")
            previous_position = self._last_position.get(symbol)
            if strict_custody and (previous_position is None or quantity > previous_position):
                self._fail_closed(
                    symbol,
                    "custody_unclaimed",
                    "reconnect found custody that no owner fill has claimed",
                )
                continue
            reserved = owner_sells.get(symbol, Decimal(0))
            self._reconcile_symbol(
                symbol,
                position,
                house.pop(symbol, []),
                reserved,
                symbol in unrecognized,
            )
            self._last_position[symbol] = quantity
        for symbol in set(self._last_position) - set(positions):
            self._last_position.pop(symbol, None)
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

    def _fail_closed(self, symbol: str, reason: str, detail: str) -> None:
        """Broker-first read, cancel only the house's excess, freeze the symbol, page."""

        try:
            positions, house, owner_sells, unrecognized = self._snapshot()
        except Exception as exc:
            self.frozen.add(symbol)
            if isinstance(exc, ProtectorRefusal):
                self.page("open_orders_truncated", symbol, str(exc))
            self.page(reason, symbol, f"{detail}; reconcile_failed={type(exc).__name__}")
            return
        if symbol in unrecognized:
            self._cancel_excess(house.get(symbol, []), 0, "unrecognized_open_order")
            self.frozen.add(symbol)
            self.page(
                "unrecognized_open_order",
                symbol,
                "an open order has no buy/sell side, so its reservation is unknown",
            )
            self.page(reason, symbol, detail)
            return
        position = positions.get(symbol)
        protective = 0
        if position is not None:
            quantity = _decimal(position.qty, "position.qty")
            if quantity > 0:
                available = quantity - owner_sells.get(symbol, Decimal(0))
                if available > 0:
                    protective = int(available.to_integral_value(rounding=ROUND_FLOOR))
        self._cancel_excess(house.get(symbol, []), protective, reason)
        self.frozen.add(symbol)
        self.page(reason, symbol, detail)

    def _cancel_excess(self, ours: list[Order], protective: int, reason: str) -> None:
        """Leave at most one house exit, no larger than the unreserved whole shares."""

        if len(ours) > 1:
            eligible = [order for order in ours if _leaves(order) <= protective]
            keeper = max(eligible, key=_leaves) if eligible else None
            for order in ours:
                if order is not keeper:
                    self._cancel(order, reason)
            return
        if ours and _leaves(ours[0]) > protective:
            self._cancel(ours[0], reason)

    @staticmethod
    def _clean(ours: list[Order], protective: int) -> bool:
        return len(ours) <= 1 and all(_leaves(order) <= protective for order in ours)

    def _fail_claim(self, update: TradeUpdate, symbol: str, reason: str, detail: str) -> None:
        """Fail closed, and after an owner sell partial fill arm the shares it frees."""

        self._fail_closed(symbol, reason, detail)
        if (
            _event_name(update.event) == "partial_fill"
            and _event_name(update.order.side).lower() == "sell"
        ):
            self.reconcile()

    def _handle_owner_fill(self, update: TradeUpdate, symbol: str) -> None:
        filled_ns = _timestamp_ns(update.timestamp)
        if filled_ns is None:
            self._fail_claim(update, symbol, "custody_unresolved", "owner fill has no timestamp")
            return
        now_ns = self._now_ns()
        if filled_ns > now_ns:
            self._fail_claim(
                update, symbol, "invalid_claim_clock", "owner fill clock is in the future"
            )
            return
        latency_ns = int(self._parameters.claim_max_latency_s * NS_PER_SECOND)
        if now_ns - filled_ns > latency_ns:
            self._fail_claim(
                update, symbol, "claim_too_late", "owner fill is older than claim_max_latency_s"
            )
            return
        if update.position_qty is None:
            self._fail_claim(update, symbol, "custody_unresolved", "owner fill has no position_qty")
            return
        expected = _decimal(str(update.position_qty), "position_qty")
        try:
            positions, _, _, _ = self._snapshot()
        except ProtectorRefusal as exc:
            self._fail_claim(update, symbol, "custody_unresolved", f"snapshot refused: {exc}")
            return
        position = positions.get(symbol)
        if position is None or _decimal(position.qty, "position.qty") != expected:
            self._fail_closed(
                symbol,
                "quantity_mismatch",
                "owner fill position_qty does not match the broker",
            )
            return
        positions = self.reconcile()
        position = positions.get(symbol)
        if position is None or _decimal(position.qty, "position.qty") != expected:
            self._fail_closed(
                symbol,
                "quantity_mismatch",
                "owner fill position_qty does not match the broker after reconcile",
            )

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
            for order in ours:
                self._cancel(order, "short_position")
            return
        if quantity == 0:
            for order in ours:
                self._cancel(order, "flat_with_house_exit")
            return
        if unrecognized_open_order:
            self.page(
                "unrecognized_open_order",
                symbol,
                "an open order has no buy/sell side, so its reservation is unknown",
            )
            for order in ours:
                self._cancel(order, "unrecognized_open_order")
            return
        available = quantity - owner_sell_reserved
        if available < 0:
            self.page(
                "quantity_mismatch",
                symbol,
                "owner sell orders reserve more than the position",
            )
            self._cancel_excess(ours, 0, "quantity_mismatch")
            self.frozen.add(symbol)
            return
        protective = int(available.to_integral_value(rounding=ROUND_FLOOR))
        if quantity != quantity.to_integral_value() or available != protective:
            self.page("fractional_custody_unverified", symbol)
        if symbol in self.frozen:
            if not self._clean(ours, protective):
                self._cancel_excess(ours, protective, "fail_closed_recheck")
                return
            self.frozen.discard(symbol)
        if protective == 0:
            self._cancel_excess(ours, protective, "owner_reserved_unprotected")
            self.frozen.add(symbol)
            self.page("owner_reserved_unprotected", symbol)
            return
        if len(ours) > 1:
            self._cancel_excess(ours, protective, "more_than_one_house_exit")
            self.frozen.add(symbol)
            self.page("more_than_one_house_exit", symbol)
            return
        in_rth = session_at(self._now_ns()) is Session.RTH
        if ours:
            held = _leaves(ours[0])
            if held == protective:
                if not in_rth:
                    self.page(
                        "unprotected_outside_rth_until_pr2",
                        symbol,
                        "the resting native trail does not trigger outside regular market hours",
                    )
                return
            if held > protective:
                self._cancel_excess(ours, protective, "quantity_mismatch")
                self.frozen.add(symbol)
                self.page("quantity_mismatch", symbol)
                if not in_rth:
                    self.page("unprotected_outside_rth_until_pr2", symbol)
                return
            if in_rth and self._cancel(ours[0], "arm_protective_quantity"):
                self._submit_trail(symbol, protective)
            elif not in_rth:
                self.page("unprotected_outside_rth_until_pr2", symbol)
            return
        if not in_rth:
            self.page("unprotected_outside_rth_until_pr2", symbol)
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
        self._connected = False
        self.subscribe_trade_updates(self._on_trade_update)

    async def _on_trade_update(self, update: TradeUpdate) -> None:
        try:
            self.protector.handle(update)
        except Exception as exc:
            self.protector.page("trade_update_failed", update.order.symbol, type(exc).__name__)

    async def _start_ws(self) -> None:
        await super()._start_ws()
        strict_custody = self._connected
        self._connected = True
        try:
            self.protector.reconcile(strict_custody=strict_custody)
        except Exception as exc:
            self.protector.page("reconcile_failed", None, type(exc).__name__)

    def run(self) -> None:
        self.protector.bind()
        super().run()
