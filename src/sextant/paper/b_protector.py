"""B's owner-fill protector on alpaca-py's TradingClient and TradingStream (clean B PR-1).

The protector covers every unreserved whole long share with exactly one native trailing stop
of the full net quantity, re-arms it on every change, and never cancels, replaces or resizes
an owner order. Outside regular market hours the native trail rests but does not trigger, so
the protector adopts or emulates its trigger from quotes through NautilusTrader's own
calculator and, after a persistent run of eligible trades, cancels the trail and releases one
marketable extended-hours LIMIT (``docs/design.md`` X4; Alpaca orders page read 2026-11-09).
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
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    OrderRequest,
    TrailingStopOrderRequest,
)
from alpaca.trading.stream import TradingStream

from sextant.exits.policy import ExitParams
from sextant.paper.config import PaperAccount
from sextant.paper.outside_rth import OutsideRthError, OutsideRthTrail
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
class _PendingRelease:
    """One broken trail waiting for its terminal cancellation before the LIMIT goes out."""

    trail_order_id: str


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


def _is_limit(order: Order) -> bool:
    kind = getattr(order, "type", None)
    if kind is None:
        kind = getattr(order, "order_type", None)
    return _event_name(kind) == "limit"


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
        exit_params: ExitParams | None = None,
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
        self._last_position: dict[str, Decimal] = {}
        self._last_reserved: dict[str, Decimal] = {}
        self._exit_params = exit_params if exit_params is not None else ExitParams.starts()
        self._outside: dict[str, OutsideRthTrail] = {}
        self._pending_release: dict[str, _PendingRelease] = {}
        self._pending_rearm: dict[str, str] = {}
        self._released_symbols: set[str] = set()
        self._house: dict[str, list[Order]] = {}
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

    def emulated_trigger(self, symbol: str) -> Decimal | None:
        """The trigger the outside-RTH node is currently watching, if any."""

        state = self._outside.get(symbol)
        return None if state is None else state.trigger

    def on_quote(
        self,
        symbol: str,
        *,
        bid: Decimal | None,
        ask: Decimal | None,
        last: Decimal | None,
        ts_ns: int | None = None,
    ) -> Decimal | None:
        """Feed one outside-RTH quote to the emulated trailing trigger.

        The node's data adapter calls this; in the regular session the native trail owns the
        trigger, so the observation is ignored there.
        """

        at = self._now_ns() if ts_ns is None else ts_ns
        if session_at(at) not in (Session.PRE, Session.POST, Session.OVERNIGHT):
            return None
        return self._outside_state(symbol).observe_quote(bid=bid, ask=ask, last=last, ts_ns=at)

    def on_trade(self, symbol: str, price: Decimal, ts_ns: int | None = None) -> bool:
        """Feed one outside-RTH trade; true when it completes a persistent breach."""

        at = self._now_ns() if ts_ns is None else ts_ns
        if session_at(at) not in (Session.PRE, Session.POST, Session.OVERNIGHT):
            return False
        state = self._outside.get(symbol)
        if state is None or not state.observe_trade(price, at):
            return False
        self._begin_outside_release(symbol, at)
        return True

    def _outside_state(self, symbol: str) -> OutsideRthTrail:
        state = self._outside.get(symbol)
        if state is None:
            state = OutsideRthTrail(
                trail_fraction=self._parameters.native_trail_fraction,
                params=self._exit_params,
            )
            self._outside[symbol] = state
        return state

    def _adopt_outside(self, symbol: str, order: Order) -> None:
        """Take the resting native trail's stop price as the emulated trigger once."""

        state = self._outside_state(symbol)
        if state.has_trigger:
            return
        stop_price = getattr(order, "stop_price", None)
        if stop_price is None:
            self.page(
                "outside_rth_trigger_missing",
                symbol,
                "the resting native trail has no stop price to emulate",
            )
            return
        state.adopt(_decimal(str(stop_price), "order.stop_price"), self._now_ns())

    def _begin_outside_release(self, symbol: str, ts_ns: int) -> None:
        """Cancel the trail and release one LIMIT after its terminal cancellation."""

        state = self._outside.get(symbol)
        if state is None or state.released or state.pending or symbol in self._released_symbols:
            return
        trails = [order for order in self._house.get(symbol, []) if not _is_limit(order)]
        if len(trails) != 1:
            self.page(
                "outside_rth_no_trail_at_breach",
                symbol,
                "the breach has no single resting native trail to cancel",
            )
            return
        try:
            state.release_price(ts_ns)
        except OutsideRthError as exc:
            self.page("outside_rth_release_unpriced", symbol, str(exc))
            return
        available = self._last_position.get(symbol, Decimal(0)) - self._last_reserved.get(
            symbol, Decimal(0)
        )
        whole = int(available.to_integral_value(rounding=ROUND_FLOOR)) if available > 0 else 0
        if whole <= 0:
            self.page("outside_rth_release_unquantified", symbol, "no unreserved whole share")
            return
        if not self._cancel(trails[0], "outside_rth_breach"):
            return
        self._pending_release[symbol] = _PendingRelease(trail_order_id=str(trails[0].id))
        state.begin_release(ts_ns)

    def _complete_outside_release(self, symbol: str, ts_ns: int) -> None:
        """Reprice and re-quantify from a fresh snapshot, then submit the one LIMIT."""

        state = self._outside.get(symbol)
        if state is None:
            self._released_symbols.discard(symbol)
            return
        if session_at(ts_ns) is Session.CLOSED:
            state.rearm()
            self._released_symbols.discard(symbol)
            self.page("market_closed", symbol, "B writes only in an open session")
            return
        positions = self.reconcile()
        if symbol not in positions:
            state.rearm()
            self._released_symbols.discard(symbol)
            return
        try:
            price = state.release_price(ts_ns)
        except OutsideRthError as exc:
            state.rearm()
            self._released_symbols.discard(symbol)
            self.page("outside_rth_release_unpriced", symbol, str(exc))
            return
        available = self._last_position.get(symbol, Decimal(0)) - self._last_reserved.get(
            symbol, Decimal(0)
        )
        whole = int(available.to_integral_value(rounding=ROUND_FLOOR)) if available > 0 else 0
        if whole <= 0:
            state.rearm()
            self._released_symbols.discard(symbol)
            self.page("outside_rth_release_unquantified", symbol, "no unreserved whole share")
            return
        self._submit_outside_limit(symbol, whole, price)

    def _submit_outside_limit(self, symbol: str, whole: int, price: Decimal) -> None:
        self._sequence += 1
        client_order_id = (
            f"{self._account.house_prefix}outside-{_safe_symbol(symbol)}-"
            f"{self._now_ns()}-{self._sequence}"
        )
        request = LimitOrderRequest(
            symbol=symbol,
            qty=whole,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            limit_price=str(price),
            extended_hours=True,
            client_order_id=client_order_id[:MAX_CLIENT_ORDER_ID],
        )
        try:
            submitted = self._client.submit_order(request)
        except Exception as exc:
            state = self._outside.get(symbol)
            if state is not None:
                state.rearm()
            self._released_symbols.discard(symbol)
            self.page("outside_limit_submit_failed", symbol, type(exc).__name__)
            return
        if isinstance(submitted, Order):
            self._remember(submitted)
        state = self._outside.get(symbol)
        if state is not None:
            state.mark_released(self._now_ns())

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
        self._house = {symbol: list(ours) for symbol, ours in house.items()}
        self._last_position = {
            symbol: _decimal(position.qty, "position.qty") for symbol, position in positions.items()
        }
        self._last_reserved = {symbol: owner_sells.get(symbol, Decimal(0)) for symbol in positions}
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
        held = set(positions)
        self._outside = {s: state for s, state in self._outside.items() if s in held}
        self._pending_release = {
            s: pending for s, pending in self._pending_release.items() if s in held
        }
        self._pending_rearm = {
            s: order_id for s, order_id in self._pending_rearm.items() if s in held
        }
        self._released_symbols &= held
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
            pending = self._pending_release.get(symbol)
            if pending is not None and pending.trail_order_id == order_id:
                self._pending_release.pop(symbol, None)
                if event == "canceled":
                    self._released_symbols.add(symbol)
                    self._complete_outside_release(symbol, self._now_ns())
                else:
                    state = self._outside.get(symbol)
                    if state is not None:
                        state.rearm()
                    self.page(
                        "outside_rth_release_failed",
                        symbol,
                        f"the resting trail ended {event} before the release",
                    )
            elif self._pending_rearm.get(symbol) == order_id:
                self._pending_rearm.pop(symbol, None)
            elif not known:
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
        session = session_at(self._now_ns())
        in_rth = session is Session.RTH
        # An oversized GTC trail is cancelled before the RTH guard, so it can never
        # ride into the next open; only the replacement submit waits for RTH.
        rest = self._cancel_excess(ours, protective, "rearm_full_protective_quantity")
        if symbol in self._pending_release:
            # The breach already decided the release; wait for the trail's terminal
            # cancellation instead of arming a second exit beside it.
            return
        if symbol in self._pending_rearm:
            # A resize waits for the old exit's terminal event before it replaces it.
            return
        if session is Session.CLOSED:
            self.page("market_closed", symbol, "B writes only in an open session")
            return
        if len(rest) == 1 and _leaves(rest[0]) == protective:
            if _is_limit(rest[0]):
                self._released_symbols.discard(symbol)
            elif not in_rth:
                self._adopt_outside(symbol, rest[0])
            return
        if not in_rth:
            for order in rest:
                if self._cancel(order, "outside_rth_resize"):
                    self._pending_rearm[symbol] = str(order.id)
            if ours:
                return
            if symbol in self._released_symbols:
                return
            self._submit_trail(symbol, protective)
            return
        for order in rest:
            if self._cancel(order, "rearm_full_protective_quantity"):
                self._pending_rearm[symbol] = str(order.id)
        # The terminal canceled event of the house's own trail drives reconcile(),
        # which submits the single replacement; never submit over a live exit.
        if ours:
            return
        if symbol in self._released_symbols:
            # The release handover is about to submit its LIMIT from a fresh
            # snapshot; never arm a second full-position exit beside it.
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
            submitted = self._client.submit_order(request)
        except Exception as exc:
            self.page("trail_submit_failed", symbol, type(exc).__name__)
            return
        if isinstance(submitted, Order):
            self._remember(submitted)

    def _remember(self, order: Order) -> None:
        """Keep an order the broker just accepted so the next breach can find it."""

        if not order.symbol:
            return
        ours = self._house.setdefault(order.symbol, [])
        if all(str(existing.id) != str(order.id) for existing in ours):
            ours.append(order)

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
        if _is_limit(order):
            # A cancelled release no longer blocks re-arming protection, and the
            # emulator must accept quotes again for whatever exit replaces it.
            self._released_symbols.discard(order.symbol)
            state = self._outside.get(order.symbol)
            if state is not None:
                state.rearm()
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
