"""Shared order gate; custody, reservations, pacing and kill policy belong to row 8.

The injected objects are the #51 contract. There is no fallback pacer/guard or
broker transport here. ``send`` owns actual-send accounting through its hook.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sextant.paper.config import PaperAccount, PaperBudget
from sextant.paper.sessions import Session, session_at

PRIORITY = {
    "ENTRY": "SUBMIT",
    "EXIT": "REDUCE",
    "PROTECT": "REDUCE",
    "MODIFY": "MODIFY",
    "CANCEL": "CANCEL",
}
ORDER_TYPES = frozenset({"LIMIT", "STOP_MARKET", "STOP_LIMIT", "TRAILING_STOP_MARKET"})


@dataclass(frozen=True)
class PaperIntent:
    action: str
    client_order_id: str
    instrument: str
    quantity: Decimal | None = None
    price: Decimal | None = None
    order_type: str = "LIMIT"
    trigger_price: Decimal | None = None
    trailing_offset: Decimal | None = None
    time_in_force: str = "DAY"

    def __post_init__(self):
        if (
            self.action not in PRIORITY
            or self.order_type not in ORDER_TYPES
            or not self.client_order_id
            or not self.instrument
            or self.time_in_force not in {"DAY", "GTC"}
        ):
            raise ValueError("known action, type, identity and DAY/GTC required")
        for number in (self.quantity, self.price, self.trigger_price, self.trailing_offset):
            if number is not None and (
                type(number) is not Decimal or not number.is_finite() or number <= 0
            ):
                raise ValueError("finite positive Decimal money and quantity required")
        if self.action in {"ENTRY", "EXIT", "PROTECT"}:
            if self.quantity is None:
                raise ValueError("submission quantity required")
            if self.order_type in {"LIMIT", "STOP_LIMIT"} and self.price is None:
                raise ValueError("limit price required")
            if self.order_type in {"STOP_MARKET", "STOP_LIMIT"} and self.trigger_price is None:
                raise ValueError("stop trigger required")
            if self.order_type == "TRAILING_STOP_MARKET" and self.trailing_offset is None:
                raise ValueError("native trailing offset required")
        if self.action == "ENTRY" and self.order_type != "LIMIT":
            raise ValueError("entries use plain LIMIT")
        if self.action == "MODIFY" and (self.price is None or self.quantity is not None):
            raise ValueError(
                "shared modifications are price-only; size changes need account policy"
            )


@dataclass
class PaperServices:
    """Bindings to row 8; Any preserves its types without vendoring unlanded modules.

    ``kinds`` is ActionKind.__members__. ``submit_allowed`` must be the row-8
    pending/residual admission seam, not a prefix or a second reservation book.
    SELLs also require custody's ``submission_ready`` and ``available_exit``
    with its own-registration exclusion; a permissive callback grants nothing.
    ``eligible`` supplies dated broker/instrument/session and maintenance facts.
    """

    writer: Any
    custody: Any
    pacer: Any
    guard: Any
    kinds: Mapping[str, Any]
    submit_allowed: Callable[[str, str, Decimal, str | None], bool]
    eligible: Callable[[PaperIntent, int], bool]
    exit_price: Callable[[str, int], Decimal | None]


class PaperRuntime:
    def __init__(
        self,
        account: PaperAccount,
        budget: PaperBudget,
        services: PaperServices,
        *,
        now_ns: Callable[[], int],
        send: Callable[[PaperIntent, Callable[[], None]], Any],
    ):
        self.account, self.budget, self.services = account, budget, services
        self.now_ns, self.send = now_ns, send
        self.last_refusal: str | None = None

    def open(self) -> None:
        s = self.services
        if any(obj.scope.key != self.account.scope_key for obj in (s.writer, s.custody, s.guard)):
            raise ValueError("writer/custody/guard account mismatch")
        controls = s.pacer.controls
        if (
            controls["request_budget"] != self.budget.requests
            or controls["window_s"] != self.budget.window_s
            or controls["broker_limit"] > self.budget.broker_cap
        ):
            raise ValueError("row-8 pacer does not match the paper limit sheet")
        if s.guard.gates.mode != "paper":
            raise ValueError("paper safeguards derive paper-observe mode")
        if set(s.kinds) != {"CANCEL", "REDUCE", "MODIFY", "QUERY", "SUBMIT"}:
            raise ValueError("row-8 action kinds required")
        s.writer.acquire()

    def close(self) -> None:
        self.services.writer.close()

    def _refuse(self, reason: str) -> bool:
        self.last_refusal = reason
        return False

    def _admit(self, intent: PaperIntent, *, registered_here: bool = False) -> bool:
        s, now = self.services, self.now_ns()
        book, snapshot = s.custody, s.custody.snapshot
        if not s.writer.held or s.writer.token is None:
            return self._refuse("writer lease is not held")
        if (
            not book.loaded
            or snapshot is None
            or not snapshot.complete
            or snapshot.known_at > now
            or intent.instrument in book.frozen
        ):
            return self._refuse("unknown or frozen custody")
        if not intent.client_order_id.startswith(self.account.house_prefix):
            return self._refuse("client ID is outside this house namespace")
        if intent.action in {"CANCEL", "MODIFY"}:
            row = book.registrations.get(intent.client_order_id)
            allowed = book.may_cancel if intent.action == "CANCEL" else book.may_replace
            if (
                row is None
                or row["instrument"] != intent.instrument
                or not allowed(intent.client_order_id)
            ):
                return self._refuse("no current house lineage for this action")
            if intent.action == "CANCEL":
                return True
            entry = row["side"] == "BUY"
        else:
            row = book.registrations.get(intent.client_order_id)
            if row is not None and not registered_here:
                return self._refuse(
                    "submission client ID already registered; reconcile its outcome"
                )
            entry = intent.action == "ENTRY"
            side = "BUY" if entry else "SELL"
            assert intent.quantity is not None
            if registered_here and (
                row is None
                or row["instrument"] != intent.instrument
                or row["side"] != side
                or Decimal(row["quantity"]) != intent.quantity
            ):
                return self._refuse("this paced request lost its registered house identity")
            own_id = intent.client_order_id if registered_here else None
            if not s.submit_allowed(intent.instrument, side, intent.quantity, own_id):
                return self._refuse("row-8 pending/residual submission admission refused")
            if not entry:
                ready = getattr(book, "submission_ready", None)
                if not callable(ready) or not ready(intent.instrument, exclude_client_id=own_id):
                    return self._refuse("row-8 authoritative submission readiness unavailable")
                if (
                    book.available_exit(intent.instrument, exclude_client_id=own_id)
                    < intent.quantity
                ):
                    return self._refuse("quantity exceeds the reconciled unreserved residual")
        phase = session_at(now)
        if entry and (not s.guard.entry_allowed() or phase not in self.account.sessions):
            return self._refuse("entry halted or outside configured entry sessions")
        if phase is not Session.RTH and intent.order_type != "LIMIT":
            return self._refuse("outside RTH requires LIMIT")
        if not s.eligible(intent, now):
            return self._refuse("broker/instrument eligibility is unavailable or closed")
        self.last_refusal = None
        return True

    def request(self, intent: PaperIntent) -> bool:
        """True means queued, never ACK/fill. Recheck before and inside paced send."""
        if not self._admit(intent):
            return False
        s = self.services
        registered_here = False
        lease_token = s.writer.token

        def admission():
            if s.writer.token != lease_token:
                return self._refuse("queued command belongs to a previous writer lease")
            return self._admit(intent, registered_here=registered_here)

        def send(before_wire):
            nonlocal registered_here
            if not admission():
                return
            if intent.action in {"ENTRY", "EXIT", "PROTECT"}:
                s.custody.register(
                    intent.client_order_id,
                    intent.instrument,
                    "BUY" if intent.action == "ENTRY" else "SELL",
                    intent.quantity,
                    source=f"{self.account.lane}; ADR-0007; {self.budget.source}",
                )
                registered_here = True
            wire_started = False

            def account_wire():
                nonlocal wire_started
                wire_started = True
                before_wire()

            try:
                if not admission():
                    return
                try:
                    self.send(intent, account_wire)
                except ValueError as error:
                    if wire_started:
                        raise
                    self._refuse(f"native validation refused: {error}")
            except Exception:
                s.guard.kill("unknown_execution_outcome", now=self.now_ns())
                raise

        snapshot = s.custody.snapshot
        open_positions = sum(q > 0 for q in snapshot.positions.values())
        exiting = {
            o.instrument
            for o in snapshot.orders
            if o.side == "SELL" and not o.terminal and o.client_order_id in s.custody.registrations
        }
        s.pacer.request(
            s.kinds[PRIORITY[intent.action]],
            send,
            admission=admission,
            open_positions=open_positions,
            exiting_positions=len(exiting),
        )
        return True

    def halt(self, reason: str) -> None:
        self.services.guard.kill(reason, now=self.now_ns())
        self.pulse()

    def pulse(self) -> None:
        """Drive row-8 kill intents and its pacer; never release/initialize the guard."""
        s, now = self.services, self.now_ns()
        if not s.writer.held:
            return
        for intent in s.guard.step(s.custody, now=now):
            if intent.kind == "CANCEL_ENTRY":
                self.request(PaperIntent("CANCEL", intent.client_order_id, intent.instrument))
            elif intent.kind == "FLATTEN":
                price = s.exit_price(intent.instrument, now)
                if price is None:
                    self.last_refusal = "no executable exit price; guard stays halted"
                    continue
                cid = f"{self.account.house_prefix}{uuid4().hex}"
                self.request(PaperIntent("EXIT", cid, intent.instrument, intent.quantity, price))
        s.pacer.drain()
