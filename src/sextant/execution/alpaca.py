"""Offline single-order Alpaca bridge slice, with no HTTP or stream client.

State shape/transitions: northstar-trading@8256c16c31dc:nautilus_alpaca/
{execution,order_reducer,parsing}.py. Decimal string fields: official Create Order
and Replace Order by ID references, read 2026-11-06 (manifest). Each transport
call is one request; every retry must return through the account pacer.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from nautilus_trader.model import TradeId

from sextant.execution.custody import TERMINAL, Custody, CustodyError, OrderFact, WriterLease
from sextant.execution.pacer import AccountPacer, ActionKind
from sextant.execution.state import decimal


@dataclass(frozen=True)
class OrderCommand:
    client_order_id: str
    instrument: str
    side: str
    quantity: Decimal
    order_type: str
    time_in_force: str
    limit_price: Decimal | None = None
    trail_price: Decimal | None = None

    def payload(self, session: str) -> dict:
        if session not in {"RTH", "EXTENDED", "CLOSED"}:
            raise CustodyError("unknown broker session")
        decimal(self.quantity, "order quantity", zero=False)
        if self.quantity != self.quantity.to_integral_value():
            raise CustodyError("fractional order shape is outside this bridge slice")
        if (
            not self.client_order_id
            or len(self.client_order_id) > 128
            or not self.instrument.endswith(".ALPACA")
            or self.side not in {"BUY", "SELL"}
            or self.time_in_force not in {"DAY", "GTC"}
        ):
            raise CustodyError("unsupported order identity, side or time in force")
        payload: dict[str, Any] = dict(
            client_order_id=self.client_order_id,
            symbol=self.instrument.rsplit(".", 1)[0],
            side=self.side.lower(),
            qty=str(self.quantity),
            type=self.order_type.lower(),
            time_in_force=self.time_in_force.lower(),
            order_class="simple",
        )
        if self.order_type == "LIMIT" and self.trail_price is None:
            decimal(self.limit_price, "limit price", zero=False)
            assert self.limit_price is not None
            step = Decimal("0.0001") if self.limit_price < 1 else Decimal("0.01")
            if self.limit_price % step:
                raise CustodyError("price precision exceeds Alpaca ladder")
            precision = 4 if self.limit_price < 1 else 2
            payload.update(
                limit_price=f"{self.limit_price:.{precision}f}", extended_hours=session != "RTH"
            )
        elif (
            self.order_type == "TRAILING_STOP"
            and self.side == "SELL"
            and self.limit_price is None
            and session == "RTH"
        ):
            decimal(self.trail_price, "trail price", zero=False)
            payload["trail_price"] = str(self.trail_price)
        else:
            raise CustodyError("unsupported order shape/session; native trailing sells require RTH")
        return payload


@dataclass(frozen=True)
class WireRequest:
    method: str
    path: str
    body: Mapping
    client_order_id: str | None
    kind: ActionKind
    generation: int
    epoch: int
    lease_token: str
    params_hash: str

    def __post_init__(self):
        object.__setattr__(self, "body", MappingProxyType(dict(self.body)))


@dataclass(frozen=True)
class Outcome:
    kind: str
    venue_order_id: str | None = None


@dataclass(frozen=True)
class FillFact:
    venue_order_id: str
    quantity: Decimal
    cumulative_quantity: Decimal
    price: Decimal

    def __post_init__(self):
        for name in ("quantity", "cumulative_quantity", "price"):
            decimal(getattr(self, name), name, zero=False)
        if not self.venue_order_id:
            raise ValueError("executing order UUID required")

    @property
    def trade_id(self) -> str:
        # common.py::make_trade_id/format_decimal at the same adapter pin.
        quantity = format(self.cumulative_quantity.normalize(), "f")
        prefix = min(20, 36 - 1 - len(quantity))
        if prefix < 12:
            raise ValueError("cumulative quantity exceeds native TradeId capacity")
        return TradeId(f"{self.venue_order_id.replace('-', '')[:prefix]}-{quantity}").value


class AlpacaBridge:
    def __init__(
        self,
        custody: Custody,
        lease: WriterLease,
        pacer: AccountPacer,
        transport: Callable[[WireRequest, Callable], Outcome],
        *,
        session: Callable[[], str],
        admission: Callable[[WireRequest], bool],
    ):
        if custody.scope != lease.scope or custody.scope.broker != "ALPACA":
            raise CustodyError("bridge account scope mismatch")
        lease.bind_pacer(pacer)
        self.writer_token = lease.token
        self.custody, self.lease, self.pacer = custody, lease, pacer
        self.transport, self.session, self.admission = transport, session, admission
        self.records = {
            cid: row["bridge"] for cid, row in custody.registrations.items() if "bridge" in row
        }

    def _save(self, cid: str):
        self.custody.registrations[cid]["bridge"] = self.records[cid]
        self.custody._save()

    def _bump(self, cid: str):
        self.records[cid]["epoch"] += 1
        self._save(cid)

    def _owned(self, cid: str) -> dict:
        if (
            not self.lease.held
            or self.lease.token != self.writer_token
            or not self.custody.loaded
            or cid not in self.records
        ):
            raise CustodyError("positive house ownership and account writer required")
        return self.records[cid]

    def _remaining(self, instrument: str, *, exclude: str | None = None) -> Decimal:
        present = {
            o.client_order_id
            for o in (() if self.custody.snapshot is None else self.custody.snapshot.orders)
        }
        held = sum(
            (
                Decimal(r["quantity"]) - self._filled(r)
                for cid, r in self.records.items()
                if cid != exclude
                and cid not in present
                and r["instrument"] == instrument
                and r["side"] == "SELL"
                and r["status"] not in TERMINAL
            ),
            Decimal(0),
        )
        return max(
            Decimal(0),
            self.custody.available_exit(instrument, exclude_client_id=exclude) - held,
        )

    def _position_counts(self) -> tuple[int, int]:
        snapshot = self.custody.snapshot
        opened = sum(
            quantity > 0 for quantity in (() if snapshot is None else snapshot.positions.values())
        )
        exiting = {
            order.instrument
            for order in (() if snapshot is None else snapshot.orders)
            if order.side == "SELL" and not order.terminal
        }
        exiting.update(
            r["instrument"]
            for r in self.records.values()
            if r["side"] == "SELL" and r["status"] not in TERMINAL
        )
        return opened, len(exiting)

    def _reserve_known(self) -> bool:
        return self.pacer.controls["reserve_per_open_position"] is not None and (
            not self._position_counts()[1]
            or self.pacer.controls["reserve_per_exiting_position"] is not None
        )

    @staticmethod
    def _filled(record: dict) -> Decimal:
        return sum((Decimal(q) for q in record["cum_by_vid"].values()), Decimal(0))

    def _command(self, cid: str) -> OrderCommand:
        r = self.records[cid]
        return OrderCommand(
            cid,
            r["instrument"],
            r["side"],
            Decimal(r["quantity"]),
            r["order_type"],
            r["time_in_force"],
            None if r["limit_price"] is None else Decimal(r["limit_price"]),
            None if r["trail_price"] is None else Decimal(r["trail_price"]),
        )

    def submit(self, command: OrderCommand):
        if (
            not self.lease.held
            or self.lease.token != self.writer_token
            or not self.custody.loaded
            or self.custody.snapshot is None
        ):
            raise CustodyError("account writer and complete preflight required")
        if not self.custody.submission_ready(command.instrument):
            raise CustodyError("custody preflight unresolved")
        command.payload(self.session())
        if command.side == "BUY" and not self._reserve_known():
            raise CustodyError("protection reserve authority unavailable")
        if command.side == "SELL" and command.quantity > self._remaining(command.instrument):
            raise CustodyError("exit quantity exceeds unreserved broker net")
        cid = command.client_order_id
        if cid in self.records:
            raise CustodyError("submit identity already has an outcome; reconcile before retry")
        self.custody.register(
            cid,
            command.instrument,
            command.side,
            command.quantity,
            source="native house order intent",
        )
        self.records[cid] = dict(
            instrument=command.instrument,
            side=command.side,
            quantity=str(command.quantity),
            order_type=command.order_type,
            time_in_force=command.time_in_force,
            limit_price=None if command.limit_price is None else str(command.limit_price),
            trail_price=None if command.trail_price is None else str(command.trail_price),
            status="SUBMITTING",
            venue=None,
            epoch=1,
            cancel_requested=False,
            cancel_generation=0,
            cancel_sends={},
            cancel_attempts={},
            replace_seq=0,
            replace_attempts={},
            replace_pending=False,
            pending_venue=None,
            cum_by_vid={},
            fill_ids=[],
            history={},
            sends=0,
            stream_epoch=0,
        )
        self._save(cid)
        kind = ActionKind.REDUCE if command.side == "SELL" else ActionKind.SUBMIT
        self._queue(
            WireRequest(
                "POST",
                "/v2/orders",
                command.payload(self.session()),
                cid,
                kind,
                0,
                1,
                self.lease.token or "",
                self.pacer.controls.params_hash,
            )
        )

    def _queue(self, request: WireRequest):
        def allowed():
            if not self.lease.held or self.lease.token != request.lease_token:
                return False
            cid = request.client_order_id
            if cid is None:
                return True
            if not self.custody.loaded:
                return False
            r = self.records[cid]
            if request.method == "DELETE":
                return bool(
                    r["cancel_requested"]
                    and request.generation == r["cancel_generation"]
                    and request.path.endswith(str(r["venue"]))
                )
            if request.method == "PATCH" and (
                r["cancel_requested"]
                or request.generation != r["replace_seq"]
                or r["status"] == "UNKNOWN"
            ):
                return False
            if request.method == "POST":
                if not self.custody.submission_ready(r["instrument"], exclude_client_id=cid):
                    self._unsent(cid)
                    return False
                if r["side"] == "BUY" and not self._reserve_known():
                    self._unsent(cid)
                    return False
                try:
                    self._command(cid).payload(self.session())
                except (ValueError, CustodyError):
                    self._unsent(cid)
                    return False
                if r["cancel_requested"] or not self.admission(request):
                    self._unsent(cid)
                    return False
                if r["side"] == "BUY" and self.session() == "CLOSED":
                    self._unsent(cid)
                    return False
                if r["side"] == "SELL" and Decimal(r["quantity"]) > self._remaining(
                    r["instrument"], exclude=cid
                ):
                    self._unsent(cid)
                    return False
            return self.admission(request)

        def send(mark):
            cid = request.client_order_id
            outbound = request
            if cid is not None and request.method == "POST":
                outbound = WireRequest(
                    request.method,
                    request.path,
                    self._command(cid).payload(self.session()),
                    cid,
                    request.kind,
                    request.generation,
                    request.epoch,
                    request.lease_token,
                    request.params_hash,
                )
            if cid is not None and request.method == "DELETE":
                r = self.records[cid]
                count = r["cancel_sends"].get(r["venue"], 0)
                if count >= self.pacer.controls["max_cancel_retries"] + 1:
                    r["status"] = "UNKNOWN"
                    self._bump(cid)
                    return
            used = False

            def before_wire():
                nonlocal used
                if not allowed():
                    raise CustodyError("admission changed immediately before wire")
                if cid is not None:
                    r = self.records[cid]
                    r["sends"] += 1
                    if request.method == "DELETE":
                        r["cancel_sends"][r["venue"]] = r["cancel_sends"].get(r["venue"], 0) + 1
                        r["cancel_attempts"].setdefault(r["venue"], []).append(
                            dict(
                                generation=request.generation,
                                attempt=r["cancel_sends"][r["venue"]],
                                outcome="IN_FLIGHT",
                            )
                        )
                    self._bump(cid)
                mark()
                used = True

            try:
                outcome = self.transport(outbound, before_wire)
            except Exception:
                if cid is not None and used:
                    self.records[cid]["status"] = "UNKNOWN"
                    self._bump(cid)
                raise
            if not used:
                raise CustodyError("transport returned without its actual-send hook")
            self.apply(outbound, outcome)

        cid = request.client_order_id

        def refuse(reason: str) -> None:
            if cid is not None:
                self._unsent(cid, reason)

        self.pacer.request(
            request.kind,
            send,
            admission=allowed,
            position_counts=self._position_counts,
            refuse=refuse,
        )

    def _unsent(self, cid: str, reason: str = "refused before the wire"):
        r = self.records[cid]
        if r["sends"] == 0:
            r["status"] = "REJECTED"
            self._bump(cid)
            row = self.custody.registrations.get(cid)
            if row is not None and not row.get("unsent"):
                self.custody.release_unsent(cid, reason=reason)

    def cancel(self, cid: str):
        r = self._owned(cid)
        if r["status"] in TERMINAL:
            return
        r["cancel_requested"], r["cancel_generation"] = True, r["cancel_generation"] + 1
        self._bump(cid)
        if r["venue"] is None:
            self._unsent(cid)
            return
        self._queue(
            WireRequest(
                "DELETE",
                f"/v2/orders/{r['venue']}",
                {},
                cid,
                ActionKind.CANCEL,
                r["cancel_generation"],
                r["epoch"],
                self.lease.token or "",
                self.pacer.controls.params_hash,
            )
        )

    def replace_limit(self, cid: str, price: Decimal):
        r = self._owned(cid)
        if r["cancel_requested"]:
            raise CustodyError("cancel intent blocks repricing")
        if (
            r["status"] not in {"NEW", "PARTIALLY_FILLED"}
            or r["replace_pending"]
            or r["order_type"] != "LIMIT"
            or r["venue"] is None
        ):
            raise CustodyError("unsettled or unsupported price replacement")
        decimal(price, "replacement price", zero=False)
        check = self._command(cid)
        OrderCommand(
            cid, check.instrument, check.side, check.quantity, "LIMIT", check.time_in_force, price
        ).payload(self.session())
        sequence = r["replace_seq"] + 1
        replacement_id = f"{cid}__R{sequence}"
        if len(replacement_id) > 128:
            raise CustodyError("replacement client identity exceeds Alpaca schema")
        r["replace_seq"], r["replace_pending"] = sequence, True
        r["replace_attempts"][str(r["replace_seq"])] = dict(outcome="QUEUED", venue=None)
        self._bump(cid)
        self._queue(
            WireRequest(
                "PATCH",
                f"/v2/orders/{r['venue']}",
                {"client_order_id": replacement_id, "limit_price": str(price)},
                cid,
                ActionKind.MODIFY,
                r["replace_seq"],
                r["epoch"],
                self.lease.token or "",
                self.pacer.controls.params_hash,
            )
        )

    def query(self, resource: str):
        if resource not in {"account", "positions", "orders"}:
            raise ValueError("unsupported query scope")
        self._queue(
            WireRequest(
                "GET",
                f"/v2/{resource}",
                {},
                None,
                ActionKind.QUERY,
                0,
                0,
                self.lease.token or "",
                self.pacer.controls.params_hash,
            )
        )

    def apply(self, request: WireRequest, outcome: Outcome) -> bool:
        if (
            not self.lease.held
            or self.lease.token != self.writer_token
            or request.lease_token != self.writer_token
        ):
            return False
        if outcome.kind == "RATE_LIMIT":
            self.pacer.on_rate_limited()
        elif outcome.kind in {"ACK", "REFUSED", "NOT_FOUND"}:
            self.pacer.on_success()
        cid = request.client_order_id
        if cid is None:
            return True
        r = self.records[cid]
        if request.method == "DELETE":
            vid = request.path.rsplit("/", 1)[-1]
            for attempt in r["cancel_attempts"].get(vid, []):
                if attempt["generation"] == request.generation:
                    attempt["outcome"] = outcome.kind
            self._bump(cid)
        if request.method == "PATCH":
            attempt = r["replace_attempts"].get(str(request.generation))
            if attempt is not None:
                attempt.update(outcome=outcome.kind, venue=outcome.venue_order_id)
                self._bump(cid)
        if request.method == "DELETE" and request.generation != r["cancel_generation"]:
            return False
        if request.method == "PATCH" and request.generation != r["replace_seq"]:
            return False
        if outcome.kind in {"NOT_FOUND", "DEFERRED"}:
            return False
        if request.method == "POST" and r["stream_epoch"] > request.epoch:
            if outcome.venue_order_id not in {None, r["venue"]}:
                r["status"] = "UNKNOWN"
                self._bump(cid)
                return False
            return True  # The stream's accepted quantity/fills outrank a late action answer.
        if request.method == "DELETE" and r["status"] in TERMINAL:
            return True
        if request.method == "PATCH" and not request.path.endswith(str(r["venue"])):
            return True  # A positive successor already advanced this replacement generation.
        if outcome.kind == "RATE_LIMIT":
            r["status"] = "UNKNOWN" if request.method != "POST" else "REJECTED"
        elif outcome.kind == "UNKNOWN":
            r["status"] = "UNKNOWN"
        elif outcome.kind == "REFUSED":
            if request.method == "POST":
                r["status"] = "REJECTED"
        elif outcome.kind == "ACK":
            if request.method == "POST" and outcome.venue_order_id:
                r["venue"], r["status"] = outcome.venue_order_id, "NEW"
                self.custody.link(cid, outcome.venue_order_id)
            elif request.method == "DELETE":
                r["status"] = "PENDING_CANCEL"
            elif request.method == "PATCH":
                r["pending_venue"], r["status"] = outcome.venue_order_id, "PENDING_REPLACE"
        else:
            raise ValueError("unclassified wire outcome")
        self._bump(cid)
        if request.method == "POST" and r["cancel_requested"] and r["venue"]:
            self.cancel(cid)
        return True

    def epoch(self, cid: str) -> int:
        return self.records[cid]["epoch"]

    def cancel_attempts(self, cid: str, venue_id: str) -> tuple[Mapping, ...]:
        return tuple(
            MappingProxyType(dict(a))
            for a in self.records[cid]["cancel_attempts"].get(venue_id, ())
        )

    def observe(
        self,
        fact: OrderFact,
        *,
        fetched_epoch: int | None = None,
        fills: tuple[FillFact, ...] = (),
        replaces: str | None = None,
    ) -> bool:
        if fact.client_order_id not in self.records:
            suffix = re.search(r"__R(\d+)$", fact.client_order_id)
            if suffix:
                root, sequence = fact.client_order_id[: suffix.start()], int(suffix[1])
                if root in self.records and sequence == self.records[root]["replace_seq"]:
                    fact = replace(fact, client_order_id=root)
        r = self._owned(fact.client_order_id)
        if fetched_epoch is not None and fetched_epoch != r["epoch"]:
            return False
        if (
            fact.owner_order
            or fact.instrument != r["instrument"]
            or fact.side != r["side"]
            or fact.quantity != Decimal(r["quantity"])
        ):
            raise CustodyError("order report identity/quantity mismatch")
        vid = fact.venue_order_id
        if vid is None:
            return False
        if vid in r["history"]:
            if fact.filled > Decimal(r["history"][vid]["filled"]):
                r["status"] = "UNKNOWN"  # Late old-generation fill requires full reconciliation.
                self._bump(fact.client_order_id)
            return False
        if r["venue"] not in {None, vid}:
            if (
                replaces != r["venue"]
                or not r["replace_pending"]
                or r["pending_venue"] not in {None, vid}
            ):
                r["status"] = "UNKNOWN"
                self._bump(fact.client_order_id)
                return False
            old = r["venue"]
            r["history"][old] = dict(status="REPLACED", filled=r["cum_by_vid"].get(old, "0"))
            self.custody.link(fact.client_order_id, vid, predecessor=old)
        previous = Decimal(r["cum_by_vid"].get(vid, "0"))
        fresh = sorted(
            (f for f in fills if f.trade_id not in r["fill_ids"]),
            key=lambda f: f.cumulative_quantity,
        )
        cumulative = previous
        for fill in fresh:
            if fill.venue_order_id != vid or fill.cumulative_quantity != cumulative + fill.quantity:
                r["status"] = "UNKNOWN"
                self._bump(fact.client_order_id)
                return False
            cumulative += fill.quantity
        if fact.filled < previous:
            return False
        if fact.filled != cumulative:
            r["status"] = "UNKNOWN"
            self._bump(fact.client_order_id)
            return False
        if r["venue"] is None:
            self.custody.link(fact.client_order_id, vid)
        r["venue"], r["status"] = vid, fact.status
        r["cum_by_vid"][vid] = str(cumulative)
        r["fill_ids"].extend(f.trade_id for f in fresh)
        if fact.terminal:
            r["cancel_requested"], r["replace_pending"] = False, False
        elif replaces:
            r["replace_pending"] = False
        if fetched_epoch is None:
            r["stream_epoch"] = r["epoch"] + 1
        self._bump(fact.client_order_id)
        for _ in fresh:
            self.pacer.record_fill()
        if r["cancel_requested"] and r["venue"]:
            self.cancel(fact.client_order_id)
        return True

    def facts(self) -> tuple[OrderFact, ...]:
        result = []
        for cid, r in self.records.items():
            for vid, prior in r["history"].items():
                result.append(
                    OrderFact(
                        cid,
                        r["instrument"],
                        r["side"],
                        Decimal(r["quantity"]),
                        Decimal(prior["filled"]),
                        prior["status"],
                        vid,
                    )
                )
            result.append(
                OrderFact(
                    cid,
                    r["instrument"],
                    r["side"],
                    Decimal(r["quantity"]),
                    Decimal(r["cum_by_vid"].get(r["venue"], "0")),
                    r["status"],
                    r["venue"],
                )
            )
        return tuple(result)
