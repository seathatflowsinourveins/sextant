"""One account service for the native S strategy fleet, reused by recorded replay.

Composition of the owning custody/pacer/guard objects; native cache/portfolio
observations follow custody_witness.py. No second reservation book or guard.
"""

from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader.model import ClientOrderId, OrderSide, Price, Quantity, TimeInForce
from nautilus_trader.trading import Strategy

from sextant.execution.custody import (
    AccountScope,
    AccountSnapshot,
    Custody,
    OrderFact,
    PositionAuthority,
    WriterLease,
)
from sextant.execution.pacer import AccountPacer, ActionKind
from sextant.risk.guard import Guard
from sextant.sandbox.profile import controls, values


class AccountStack:
    def __init__(
        self,
        *,
        binding: Any,
        profile: dict,
        root: Path,
        instruments: list,
        case: str,
        data_client: str,
        execution_client: str,
    ):
        self.binding, self.profile, self.root = binding, profile, root
        self.instruments = {str(instrument.id): instrument for instrument in instruments}
        self.case, self.data_client, self.execution_client = case, data_client, execution_client
        self.now = self.epoch = 0
        self.started = False
        self.strategies: dict[str, Any] = {}
        self.counts: Counter[str] = Counter()
        self.errors: list[str] = []
        self.routes: list[dict] = []
        self.fills: list[dict] = []
        self.minimum_net = Decimal(0)
        self.owner_id: str | None = None
        self.kill_started = False
        self.cache: Any = None
        self.portfolio: Any = None
        self.scope = AccountScope("SIM", binding.account_id)
        c = controls(profile)
        self.writer = WriterLease(self.scope, root / "locks", binding.client_id)
        self.custody = Custody(self.scope, root / "custody.json", create=True)
        if case == "unknown":
            root.mkdir(parents=True, exist_ok=True)
            (root / "guard.json").write_text("{unreadable fixture state")
        self.guard = Guard(self.scope, root / "guard.json", root / "kill", c, mode="replay")
        self.pacer = AccountPacer(c, lambda: self.now)

    def open(self, strategy):
        self.cache, self.portfolio = strategy.cache, strategy.portfolio
        if self.started:
            return
        self.writer.acquire()
        self.writer.bind_pacer(self.pacer)
        self.started = True
        self.refresh(strategy.clock.timestamp_ns())
        if self.case != "unknown":
            self.guard.initialize(self.custody.flat_receipt())

    def refresh(self, now: int):
        self.now = now
        if self.cache is None:
            return
        facts, house = [], {iid: Decimal(0) for iid in self.instruments}
        for order in self.cache.orders():
            cid, iid = str(order.client_order_id), str(order.instrument_id)
            if iid not in self.instruments:
                raise ValueError("native order outside frozen instrument set")
            vid = None if order.venue_order_id is None else str(order.venue_order_id)
            managed = cid in self.custody.registrations
            if managed:
                if vid is not None:
                    self.custody.link(cid, vid)
                sign = 1 if order.side == OrderSide.BUY else -1
                house[iid] += sign * order.filled_qty.as_decimal()
            facts.append(
                OrderFact(
                    cid,
                    iid,
                    order.side.name,
                    order.quantity.as_decimal(),
                    order.filled_qty.as_decimal(),
                    order.status.name,
                    vid,
                    cid == self.owner_id,
                )
            )
        present = {fact.client_order_id for fact in facts}
        for cid, row in self.custody.registrations.items():
            if cid in present:
                continue
            intent = row.get("native_intent", {})
            # A durable, positively unsent native intent is distinct from a
            # missing post-send report. Same reservation book, no invented fill.
            status = (
                intent.get("status", "UNKNOWN")
                if intent.get("wire_started") is False
                else "UNKNOWN"
            )
            facts.append(
                OrderFact(
                    cid,
                    row["instrument"],
                    row["side"],
                    Decimal(row["quantity"]),
                    Decimal(0),
                    status,
                    None,
                )
            )
        positions = {
            iid: self.portfolio.net_position(instrument.id)
            for iid, instrument in self.instruments.items()
        }
        self.minimum_net = min(self.minimum_net, *positions.values())
        authority = {
            iid: PositionAuthority(
                max(Decimal(0), quantity), "MODELED registered house fills; no external-owner claim"
            )
            for iid, quantity in house.items()
        }
        self.epoch += 1
        self.custody.observe(
            AccountSnapshot(
                self.scope,
                self.epoch,
                positions,
                authority,
                tuple(facts),
                True,
                now,
                "MODELED native cache/portfolio; explicit S-to-R account translation",
            ),
            now=now,
        )
        self.counts["custody_observations"] += 1

    def position_counts(self):
        snap = self.custody.snapshot
        return (
            sum(q > 0 for q in snap.positions.values()) if snap else 0,
            len({o.instrument for o in snap.orders if o.side == "SELL" and not o.terminal})
            if snap
            else 0,
        )

    def residual(self, iid: str, *, exclude: str) -> Decimal:
        """Pre-wire request retains ONLY its own reservation, capped by current net."""
        book, snap = self.custody, self.custody.snapshot
        if snap is None or not book.submission_ready(iid, exclude_client_id=exclude):
            return Decimal(0)
        reserved = sum(
            (
                o.leaves
                for o in snap.orders
                if o.instrument == iid and o.side == "SELL" and o.client_order_id != exclude
            ),
            Decimal(0),
        )
        return max(Decimal(0), snap.positions.get(iid, Decimal(0)) - reserved)

    def _intent_status(self, cid: str, *, status: str, started: bool):
        self.custody.registrations[cid]["native_intent"] = dict(status=status, wire_started=started)
        self.custody._save()

    def cycle(self, now: int):
        self.refresh(now)
        tape = values(self.profile, "tape")
        if (
            self.case == "kill_owner"
            and not self.kill_started
            and now
            >= (
                self.strategies[next(iter(self.strategies))].start_ns
                + tape["kill_s"] * 1_000_000_000
            )
        ):
            self.guard.kill("fixture_owner_kill", now=now)
            self.kill_started = True
        self.counts["guard_checks"] += 1
        for intent in self.guard.step(self.custody, now=now):
            strategy = self.strategies.get(intent.instrument)
            if strategy is None:
                raise ValueError("guard intent lacks frozen instrument owner")
            if intent.kind == "CANCEL_ENTRY":
                assert intent.client_order_id is not None
                strategy.cancel_order(
                    ClientOrderId(intent.client_order_id), client_id=strategy.route
                )
            elif intent.kind == "FLATTEN" and strategy.quote is not None:
                strategy.reduce(intent.quantity, strategy.quote.bid_price, reason="guard_flatten")
        self.pacer.drain()

    def submit(self, strategy, order, *, position_id=None, client_id=None, params=None):
        if client_id != strategy.route:
            raise ValueError("every S command requires its explicit execution client")
        now, iid, cid = (
            strategy.clock.timestamp_ns(),
            str(order.instrument_id),
            str(order.client_order_id),
        )
        self.refresh(now)
        if not cid.startswith(self.binding.order_namespace + "."):
            raise ValueError("order outside frozen arm namespace")
        if not self.custody.submission_ready(iid):
            raise ValueError("custody submission unresolved")
        side = order.side.name
        if side == "BUY" and not self.guard.entry_allowed():
            raise ValueError("guard denies entry")
        if side == "SELL" and order.quantity.as_decimal() > self.custody.available_exit(iid):
            raise ValueError("native close exceeds unreserved net")
        if side == "BUY" and self.pacer.controls["reserve_per_open_position"] is None:
            raise ValueError("protection reserve authority unavailable")
        self.custody.register(
            cid, iid, side, order.quantity.as_decimal(), source="MODELED native S stack intent"
        )
        self._intent_status(cid, status="INITIALIZED", started=False)
        token = self.writer.token
        sending = False

        def allowed():
            if not sending:
                self.refresh(strategy.clock.timestamp_ns())
            admitted = bool(
                self.writer.held
                and self.writer.token == token
                and self.custody.registrations[cid]["native_intent"]["status"]
                == ("SUBMITTED" if sending else "INITIALIZED")
                and self.custody.submission_ready(iid, exclude_client_id=cid)
                and (side != "BUY" or (self.guard.entry_allowed() and strategy.entry_admitted()))
                and (
                    side != "SELL" or order.quantity.as_decimal() <= self.residual(iid, exclude=cid)
                )
            )
            if (
                not admitted
                and self.custody.registrations[cid]["native_intent"]["wire_started"] is False
            ):
                self._intent_status(cid, status="DENIED", started=False)
            return admitted

        def send(mark):
            nonlocal sending
            if not allowed():
                raise ValueError("native send admission changed")
            target = position_id
            if side == "SELL":
                positions = strategy.cache.positions_open(
                    instrument_id=order.instrument_id, strategy_id=strategy.strategy_id
                )
                if len(positions) != 1:
                    raise ValueError("positive native house position required for reduction")
                target = positions[0].id
            self._intent_status(cid, status="SUBMITTED", started=True)
            # Same synchronous native callback, with no event-loop yield: retain
            # this preflight snapshot while the paced hook rechecks admission.
            sending = True
            try:
                mark()
                self.routes.append(dict(action="SUBMIT", client=str(client_id), cid=cid, side=side))
                Strategy.submit_order(
                    strategy, order, position_id=target, client_id=client_id, params=params
                )
            finally:
                sending = False

        self.pacer.request(
            ActionKind.SUBMIT if side == "BUY" else ActionKind.REDUCE,
            send,
            admission=allowed,
            position_counts=self.position_counts,
        )

    def action(self, strategy, cid, *, kind, client_id, price=None):
        if client_id != strategy.route:
            raise ValueError("every S command requires its explicit execution client")
        token = self.writer.token
        key = str(cid)
        intent = self.custody.registrations.get(key, {}).get("native_intent", {})
        if kind == ActionKind.CANCEL and intent.get("wire_started") is False:
            self._intent_status(key, status="DENIED", started=False)
            return

        def allowed():
            self.refresh(strategy.clock.timestamp_ns())
            return bool(
                self.writer.held
                and self.writer.token == token
                and (
                    self.custody.may_cancel(key)
                    if kind == ActionKind.CANCEL
                    else self.custody.may_replace(key)
                )
            )

        def send(mark):
            mark()
            self.routes.append(dict(action=kind.name, client=str(client_id), cid=key))
            if kind == ActionKind.CANCEL:
                Strategy.cancel_order(strategy, cid, client_id=client_id)
            else:
                Strategy.modify_order(strategy, cid, price=price, client_id=client_id)

        self.pacer.request(kind, send, admission=allowed)

    def seed_owner(self, strategy):
        """The owning custody proof's resting owner-labelled fixture, never a real claim."""
        if self.case != "kill_owner" or self.owner_id is not None:
            return
        self.owner_id = f"fixture-owner-{self.binding.client_id}"
        order = strategy.order_factory.limit(
            strategy.instrument_id,
            OrderSide.BUY,
            Quantity.from_int(1),
            Price.from_str(values(self.profile, "tape")["owner_limit"]),
            time_in_force=TimeInForce.GTC,
            client_order_id=ClientOrderId(self.owner_id),
        )

        def send(mark):
            mark()
            self.routes.append(
                dict(
                    action="OWNER_FIXTURE",
                    client=str(strategy.route),
                    cid=self.owner_id,
                    side="BUY",
                )
            )
            Strategy.submit_order(strategy, order, client_id=strategy.route)

        self.pacer.request(
            ActionKind.SUBMIT,
            send,
            admission=lambda: self.writer.held,
            position_counts=self.position_counts,
        )
