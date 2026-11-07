"""Shared order gate; custody, reservations, pacing and kill policy belong to row 8.

The injected objects are the #51 contract. There is no fallback pacer/guard or
broker transport here. The native layer only prepares one command; the runtime runs its own
accounting hook and then that command, in upstream RestCaller.call's order. A submission
registers inside the hook, after native validation. A registration refused before the pacer
counts the wire is released in custody as never sent; once the command runs, its outcome
stays unknown and the account halts (#151).
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


class NativeRefusal(ValueError):
    """The native layer's refusal while preparing a command: nothing was registered or sent."""


class NotSent(ValueError):
    """A registered submission refused before the wire: custody releases it (#151)."""


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
        prepare: Callable[[PaperIntent], Callable[[], Any]],
    ):
        self.account, self.budget, self.services = account, budget, services
        self.now_ns, self.prepare = now_ns, prepare
        self.last_refusal: str | None = None
        self.last_error: str | None = None  # an admission or price-source error that halted
        self._registrars: dict[str, object] = {}  # client ID -> the lease token that registered it
        self._kill_prices: dict[str, Decimal] = {}  # queued kill EXIT -> the price it was built at
        self._kill_queued: dict[str, str] = {}  # instrument -> its newest queued kill EXIT
        self._kill_cids: set[str] = set()  # every kill EXIT this writer queued, until pruned
        self._denied_epochs: dict[str, int] = {}  # instrument -> epoch of a denied kill EXIT

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
        s.custody.refresh()  # load-on-acquire: never write from a map another writer outdated

    def close(self) -> None:
        self.services.writer.close()
        self._registrars.clear()
        self._kill_prices.clear()
        self._kill_queued.clear()
        self._kill_cids.clear()
        self._denied_epochs.clear()

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
        s, cid = self.services, intent.client_order_id
        try:
            if not self._admit(intent):
                return False
        except Exception as error:  # admission errors halt and never escape (#163 P1-2)
            self._halt_on(error, "admission error halts")
            return False
        registers = intent.action in {"ENTRY", "EXIT", "PROTECT"}
        registered_here = False
        lease_token = s.writer.token
        prepared: list[Callable[[], Any]] = []  # the native command, built before the token

        def gates() -> bool:
            # Total: an admission error halts and returns False, so row 8's pacer pops the item
            # instead of re-raising it at the head of every later drain (#163 #88 review P1-2).
            if s.writer.token != lease_token:
                allowed = self._refuse("queued command belongs to a previous writer lease")
            else:
                try:
                    # Every gate runs before the pacer spends a token: a refusal pops free
                    # instead of burning the budget that kill-to-flat needs (#163 P1-A).
                    allowed = self._admit(
                        intent, registered_here=registered_here
                    ) and self._kill_price_current(intent)
                except Exception as error:
                    allowed = self._halt_on(error, "admission error halts")
            if not allowed:
                self._forget_kill(intent)  # a refused command never comes back
            return allowed

        def admission() -> bool:
            # The pacer's check before its token, native validation included: the native layer
            # validates and builds one command (cache, identity, precision, OrderFactory) and
            # never receives the hook, so a deterministic refusal spends no token (#88 review).
            allowed = gates()
            if allowed:
                try:
                    prepared[:] = [self.prepare(intent)]
                except NativeRefusal as error:
                    allowed = self._native_refusal(intent, error)
                except Exception as error:
                    allowed = self._halt_on(error, "admission error halts")
                if not allowed:
                    self._forget_kill(intent)
            return allowed

        def register() -> None:
            nonlocal registered_here
            s.custody.register(
                cid,
                intent.instrument,
                "BUY" if intent.action == "ENTRY" else "SELL",
                intent.quantity,
                source=f"{self.account.lane}; ADR-0007; {self.budget.source}",
            )
            registered_here = True
            self._registrars[cid] = s.writer.token

        def send(before_wire):
            if not (gates() if prepared else admission()):
                return
            self._forget_kill(intent)  # past the drain head: it no longer waits in the queue
            command = prepared[0]  # prepared by the admission just above (#163 gate P0)
            try:
                # The runtime's own hook, then the command, in upstream RestCaller.call's order:
                # before_send runs once the pacer admits, right before the request leaves, and a
                # raise from it aborts the request (northstar-trading http.py). Register durably,
                # recheck with the own-ID exclusion, then count the wire.
                if registers:
                    register()
                    if not gates():
                        raise NotSent(self.last_refusal or "refused after registration")
                before_wire()  # row 8's pacer re-admits and raises only before it counts
            except Exception as error:
                if registered_here:
                    self._release(cid, error)  # the command never ran: never sent (#151)
                if not isinstance(error, ValueError):
                    s.guard.kill("unknown_execution_outcome", now=self.now_ns())
                    raise  # unexpected errors still halt
                if isinstance(error, NotSent):
                    self._refuse(str(error))
                else:
                    self._refuse(f"refused at the wire hook: {self.last_refusal or error}")
                return
            try:
                command()  # the native RiskEngine, then the ExecutionEngine's registered client
            except Exception:
                s.guard.kill("unknown_execution_outcome", now=self.now_ns())
                raise  # the wire is counted: the outcome stays unknown and the row in flight

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

    def _kill_price_current(self, intent: PaperIntent) -> bool:
        """A queued kill EXIT goes out only at the current exit price; checked before the token."""
        price = self._kill_prices.get(intent.client_order_id)
        if price is None:
            return True
        if self.services.exit_price(intent.instrument, self.now_ns()) != price:
            return self._refuse("kill exit price moved while queued; a fresh one is queued")
        return True

    def _forget_kill(self, intent: PaperIntent) -> None:
        cid = intent.client_order_id
        self._kill_prices.pop(cid, None)
        if self._kill_queued.get(intent.instrument) == cid:
            del self._kill_queued[intent.instrument]

    def _native_refusal(self, intent: PaperIntent, error: NativeRefusal) -> bool:
        """Refuse before the token; a refused kill EXIT waits for a new observation.

        The refusal is deterministic, so re-queuing it every tick would spend the budget other
        symbols need, as P1-A did. It is treated like an rc8 denial (#163 #88 review of 512660b).
        """
        self._refuse(f"native validation refused: {error}")
        epoch = getattr(self.services.custody.snapshot, "epoch", None)
        if epoch is not None and intent.client_order_id in self._kill_cids:
            self._denied_epochs[intent.instrument] = epoch
        return False

    def _release(self, cid: str, cause: object) -> None:
        reason = f"{type(cause).__name__}: {cause}"
        try:
            self.services.custody.release_unsent(cid, reason=reason)
        except Exception:
            self.services.guard.kill("unknown_execution_outcome", now=self.now_ns())
            raise
        self._registrars.pop(cid, None)

    def _halt_on(self, error: Exception, what: str) -> bool:
        """Record why, halt the account, and refuse; later successes keep `last_error` (P2)."""
        self.last_error = f"{what}: {type(error).__name__}: {error}"
        self._refuse(self.last_error)
        self.services.guard.kill("unknown_execution_outcome", now=self.now_ns())
        return False

    def _prune(self) -> None:
        """Drop bookkeeping for rows that can no longer be denied (#163 gh-aw review)."""
        rows = self.services.custody.registrations
        for cid in list(self._registrars):
            row = rows.get(cid)
            if row is None or row.get("lineage") or row.get("unsent"):
                del self._registrars[cid]
        self._kill_cids &= set(self._registrars) | set(self._kill_prices)

    def denied(self, client_order_id: str, reason: str) -> None:
        """An OrderDenied: rc7 refused on this node, before any venue, so custody releases it.

        Only this writer's own registration, while it still holds that lease: a late denial
        after the lease changed hands must not rewrite another writer's custody (#163 review).
        """
        s = self.services
        token = self._registrars.pop(client_order_id, None)
        row = s.custody.registrations.get(client_order_id)
        if row is None or row.get("unsent") or row.get("lineage"):
            return
        if token is None or not s.writer.held or s.writer.token != token:
            return
        self._refuse(f"denied before the venue: {reason}")
        epoch = getattr(s.custody.snapshot, "epoch", None)
        if epoch is not None and client_order_id in self._kill_cids:
            # Only a denied kill EXIT waits for a new observation; any other denial, such as
            # a strategy's PROTECT, must not silence that symbol's kill (#163 gate P1-D).
            self._denied_epochs[row["instrument"]] = epoch
        try:
            self.services.custody.release_unsent(client_order_id, reason=self.last_refusal)
        except Exception:
            self.services.guard.kill("unknown_execution_outcome", now=self.now_ns())
            raise

    def halt(self, reason: str) -> None:
        self.services.guard.kill(reason, now=self.now_ns())
        self.pulse()

    def pulse(self) -> None:
        """Drive row-8 kill intents and its pacer; never release/initialize the guard.

        Each intent is isolated: one that raises (its request has already halted where it
        must) cannot stop the rest of the account's intents or the final drain. The first
        failure is re-raised afterwards (#163 #88 review P2).
        """
        s, now = self.services, self.now_ns()
        if not s.writer.held:
            return
        self._prune()
        failures: list[Exception] = []
        try:
            for intent in s.guard.step(s.custody, now=now):
                try:
                    self._kill_intent(intent, now)
                except Exception as error:
                    failures.append(error)
        finally:
            try:
                s.pacer.drain()
            except Exception as error:
                failures.append(error)
        if failures:
            raise failures[0]

    def _kill_intent(self, intent: Any, now: int) -> None:
        s = self.services
        if intent.kind == "CANCEL_ENTRY":
            self.request(PaperIntent("CANCEL", intent.client_order_id, intent.instrument))
        elif intent.kind == "FLATTEN":
            epoch = getattr(s.custody.snapshot, "epoch", None)
            if epoch is not None and self._denied_epochs.get(intent.instrument) == epoch:
                self.last_refusal = "kill exit denied at this observation; waits for a new one"
                return
            try:
                price = s.exit_price(intent.instrument, now)
            except Exception as error:  # a failing price source must not stop the kill pulse
                self.last_error = f"exit price failed: {type(error).__name__}: {error}"
                self.last_refusal = "no executable exit price; guard stays halted"
                return
            if price is None:
                self.last_refusal = "no executable exit price; guard stays halted"
                return
            queued = self._kill_queued.get(intent.instrument)
            if queued is not None and self._kill_prices.get(queued) == price:
                return  # one kill EXIT per symbol waits in the queue at the current price
            cid = f"{self.account.house_prefix}{uuid4().hex}"
            try:  # validate before any bookkeeping: an invalid price must not grow it each pulse
                exit_ = PaperIntent("EXIT", cid, intent.instrument, intent.quantity, price)
            except ValueError as error:
                self.last_error = f"kill exit invalid: {error}"
                self.last_refusal = "no valid exit order; guard stays halted"
                return
            self._kill_prices[cid] = price
            self._kill_cids.add(cid)
            if self.request(exit_):
                if cid in self._kill_prices:  # still queued, not already drained
                    self._kill_queued[intent.instrument] = cid
            else:
                self._forget_kill(exit_)
