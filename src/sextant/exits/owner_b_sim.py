"""Sim-only B manager: existing X2-X5 trigger, native trail, terminal cancel, one LIMIT.

Not a live adapter or owner-fill claimer. The caller supplies an admitted position; real
external claiming is owed to Sandbox (#49). Custody/recovery intents: owner_b.py and its
ADR-0015 source. Native lifecycle as read at nautechsystems/nautilus_trader@v2.0.0rc7
55c0e82053142bce3a5cba4de4221d3929c2d3bc (Strategy cancel/modify, OrderFactory trailing stops,
BID_ASK OrderEmulator, native cache); trail pricing as read at the installed rc8 d53849b2. The RTH
native trail triggers on LAST_PRICE: Alpaca elects stop and trailing-stop orders on the
consolidated print (docs.alpaca.markets/docs/orders-at-alpaca, read 2026-11-06).
Alpaca has no reduce-only: this witness deliberately uses no reduce-only flag.
"""

from decimal import Decimal
from typing import Literal

from nautilus_trader.model import (
    ClientOrderId,
    OrderSide,
    OrderStatus,
    PositionSide,
    Quantity,
    TimeInForce,
    TrailingOffsetType,
    TriggerType,
)

from sextant.exits import policy
from sextant.exits.engine import NS, ExitEngine, ExitEngineConfig, Protection
from sextant.exits.owner_b import Adoption, BParams, OwnedExit, decide


class BManagerConfig(ExitEngineConfig):
    def __init__(self, *, b_params: BParams, owner_order_ids: tuple[str, ...], **kwargs):
        super().__init__(**kwargs)
        self.b_params = b_params
        self.owner_order_ids = owner_order_ids


class BManager(ExitEngine):
    def __init__(self, config: BManagerConfig) -> None:
        cap = config.params.chase_cap_fraction
        if cap is None or config.params.chase_min_interval_s is None:
            raise ValueError("B manager requires explicit chase parameters")
        super().__init__(config)
        self._chase_cap_fraction = cap
        self.b = config.b_params
        self.owner_order_ids = set(config.owner_order_ids)
        self.owned: dict[str, Literal["trail", "limit"]] = {}
        self.exiting = False
        self.recovering = False
        self.resume_pending = False
        self.limit_started_ns: int | None = None
        self.last_quantity: Decimal | None = None
        self.exit_reason = ""
        self.awaiting_trade = False  # the in-hours trail waits for a cached print
        self.pages: list[str] = []
        self.audits: list[dict] = []
        self.actions: list[dict] = []

    def on_resume(self) -> None:
        # Component::resume holds a native mutable borrow during this callback. Defer cache
        # access until the next normal event; STOPPED -> RESUME is rc7's supported transition.
        self.recovering, self.exiting, self.sell_id = True, False, None
        self.resume_pending = True

    def adopt_position(self, a: Adoption, *, total_quantity: Decimal) -> None:
        """A supplied-custody seam, never a claim or an invented reconciliation report."""
        if self.protection is not None:
            self._page("owner_add")
            return
        if a.quantity == 0 and a.reason != "owner_reserved_unprotected":
            self._page(a.reason)
            return
        if a.quantity == 0:
            self._alert(a.reason)
        self.last_quantity = total_quantity
        self.exit_reason = a.reason
        self.protection = Protection(a.entry, a.quantity, a.high, a.trigger, a.entry - a.trigger)
        self._record(
            self.clock.timestamp_ns(),
            "adoption",
            entry=a.entry,
            high=a.high,
            trigger=a.trigger,
        )
        self._drive()

    def _page(self, reason: str) -> None:
        self.paused = True
        self._alert(reason)

    def _alert(self, reason: str) -> None:
        if reason not in self.pages:
            self.pages.append(reason)
            self._record(self.clock.timestamp_ns(), "pause_and_page" if self.paused else "page")

    def _snapshot(self) -> tuple[Decimal, Decimal, tuple[OwnedExit, ...]]:
        position = Decimal(0)
        for p in self.cache.positions_open(instrument_id=self.instrument_id):
            position += p.quantity.as_decimal() * (1 if p.side == PositionSide.LONG else -1)
        reserved, owned = Decimal(0), []
        for order in self.cache.orders(instrument_id=self.instrument_id):
            if order.is_closed:
                continue
            cid = str(order.client_order_id)
            leaves = order.leaves_qty.as_decimal()
            if cid in self.owned:
                owned.append(
                    OwnedExit(
                        cid,
                        self.owned[cid],
                        leaves,
                        pending=order.is_inflight or order.status == OrderStatus.INITIALIZED,
                        pending_cancel=order.is_pending_cancel,
                    )
                )
            elif cid in self.owner_order_ids:
                if order.side == OrderSide.SELL:
                    reserved += leaves
            else:
                self._page("foreign_order")
        self.audits.append(
            {
                "ts": self.clock.timestamp_ns(),
                "position": str(position),
                "owner_reserved": str(reserved),
                "house_reserved": str(sum((o.leaves for o in owned), Decimal(0))),
                "house_exits": len(owned),
                "pending": [o.pending for o in owned],
                "pending_cancel": [o.pending_cancel for o in owned],
            }
        )
        return position, reserved, tuple(owned)

    def _drive(self) -> None:
        if not self.is_running() or self.protection is None or self.paused:
            return
        position, reserved, owned = self._snapshot()
        if self.paused:
            return
        if position < 0:
            self._page("quantity_mismatch")
            return
        if self.last_quantity is not None and position > self.last_quantity:
            self._page("owner_add")
            return
        self.last_quantity = position
        ts = self.clock.timestamp_ns()
        if self.limit_started_ns is not None and self.exiting:
            if ts - self.limit_started_ns >= int(self.b.limit_chase_window_s * NS):
                self.recovering, self.exiting = True, False
        mode = "recover" if self.recovering else "breach" if self.exiting else "protect"
        intent = decide(position, reserved, owned, mode=mode)
        self.audits[-1]["mode"] = mode
        self.audits[-1]["intent"] = intent.action
        if intent.action == "pause_and_page":
            self._page(intent.reason)
        elif intent.action == "page":
            self._alert(intent.reason)
        elif intent.action == "cancel":
            assert intent.order_id in self.owned
            self.actions.append({"action": "cancel", "order_id": intent.order_id, "ts": ts})
            self.cancel_order(ClientOrderId(intent.order_id))
        elif intent.action == "trail" or intent.action == "limit":
            if self.recovering and intent.action == "trail":
                self.recovering, self.exiting = False, False
                self.sell_id, self.limit_started_ns = None, None
                self.breach = policy.BreachRun()
            self._submit(intent.action, intent.quantity)

    def _submit(self, kind: Literal["trail", "limit"], quantity: Decimal) -> None:
        ts = self.clock.timestamp_ns()
        qty = Quantity.from_str(str(quantity))
        if kind == "limit":
            if self.bid is None:
                return
            order = self.order_factory.limit(
                instrument_id=self.instrument_id,
                order_side=OrderSide.SELL,
                quantity=qty,
                time_in_force=TimeInForce.DAY,
                price=self._price(policy.chase_limit(self.bid, self.last, self.p)),
            )
            self.sell_id, self.amended_ns = order.client_order_id, ts
            self.limit_started_ns = ts
        else:
            if self.rth:
                if self.cache.trade(self.instrument_id) is None:
                    # rc8's RiskEngine prices an untriggered LAST_PRICE trail from the cached
                    # trade and denies it without one (crates/risk/src/engine/mod.rs:2364-2417,
                    # :2137-2146). Wait for the first print, which re-drives, instead of pausing.
                    # Outside RTH the emulated trail goes to the OrderEmulator, which arms it on
                    # the first quote.
                    self._wait(ts)
                    return
                self.awaiting_trade = False
                order = self.order_factory.trailing_stop_market(
                    instrument_id=self.instrument_id,
                    order_side=OrderSide.SELL,
                    quantity=qty,
                    time_in_force=TimeInForce.DAY,
                    trailing_offset=self.b.native_trail_fraction * 10_000,
                    trailing_offset_type=TrailingOffsetType.BASIS_POINTS,
                    trigger_type=TriggerType.LAST_PRICE,
                )
            else:
                order = self.order_factory.trailing_stop_limit(
                    instrument_id=self.instrument_id,
                    order_side=OrderSide.SELL,
                    quantity=qty,
                    time_in_force=TimeInForce.DAY,
                    trailing_offset=self.b.native_trail_fraction * 10_000,
                    trailing_offset_type=TrailingOffsetType.BASIS_POINTS,
                    trigger_type=TriggerType.BID_ASK,
                    price=None,
                    limit_offset=self._chase_cap_fraction * 10_000,
                    emulation_trigger=TriggerType.BID_ASK,
                )
        cid = str(order.client_order_id)
        self.owned[cid] = kind
        trigger = getattr(order, "trigger_type", None)
        emulation = getattr(order, "emulation_trigger", None)
        self.actions.append(
            {"action": kind, "order_id": cid, "ts": ts, "trigger": getattr(trigger, "name", None),
             "emulation": getattr(emulation, "name", None)}
        )  # fmt: skip
        self.submit_order(order)
        self._snapshot()

    def _wait(self, ts: int) -> None:
        """The broker trail is unarmed: alert once without pausing, so X2-X5 keeps running."""
        if not self.awaiting_trade:
            self.awaiting_trade = True
            self._record(ts, "awaiting_trade")
            self._alert("awaiting_trade")

    def _step(self, ts: int, observed: Decimal | None) -> None:
        if not self.is_running():
            return
        if self.resume_pending:
            self._record(ts, "restart")
            self.resume_pending = False
        self._drive()  # An add/mismatch pauses before a new managed action.
        if self.recovering:
            return  # Recovery owns the exit until terminal cancellation and a fresh residual.
        super()._step(ts, observed)
        self._drive()

    def _sell(self, ts: int, p: Protection) -> None:
        assert p.trigger is not None
        self.exiting = True
        self._record(ts, "persisted_breach", trigger=p.trigger)
        self._drive()

    def _chase(self, ts: int) -> None:
        if self.recovering or self.paused:
            return
        if self.sell_id is not None:
            order = self.cache.order(self.sell_id)
            if order is not None and order.is_pending_cancel:
                return
        super()._chase(ts)

    def on_order_accepted(self, event) -> None:
        self._record(event.ts_event, "accepted", order_id=str(event.client_order_id))
        self._drive()

    def on_trade(self, trade) -> None:
        super().on_trade(trade)
        if self.awaiting_trade:
            self._drive()  # the first cached print arms the in-hours trail

    def on_order_canceled(self, event) -> None:
        self._record(event.ts_event, "canceled")
        self._drive()

    def on_order_expired(self, event) -> None:
        self._drive()

    def on_order_rejected(self, event) -> None:
        self._page("protection_rejected")

    def on_order_denied(self, event) -> None:
        cid, reason = str(event.client_order_id), str(event.reason)
        trail = self.rth and self.owned.get(cid) == "trail"  # only the in-hours trail waits
        if trail and reason.startswith("MARKET_PRICE_UNAVAILABLE"):
            self.owned.pop(cid)
            self._wait(event.ts_event)
            return
        self._page("protection_denied")  # anything else fails closed (#191 dsh leg P1)

    def on_order_released(self, event) -> None:
        cid = str(event.client_order_id)
        self.owned[cid] = "limit"
        self.sell_id = event.client_order_id
        self.exiting = True
        self.limit_started_ns = self.clock.timestamp_ns()

    # B adopts supplied custody and reads native positions in _snapshot (ADR-0007:17-18). The base
    # engine's own position tracking (R86, #129) is A/C's, so it never runs for B.
    def on_position_opened(self, event) -> None:
        return

    def on_position_changed(self, event) -> None:
        return

    def on_position_closed(self, event) -> None:
        return

    def on_order_filled(self, event) -> None:
        if event.order_side == OrderSide.SELL:
            self._record(
                event.ts_event,
                "sell_fill",
                qty=event.last_qty.as_decimal(),
                price=event.last_px.as_decimal(),
            )
        self._drive()
