"""Alpaca paper ExecutionClient following NT d53849b's Python adapter template.

AP cc4cb3b7 trading/{client,stream}.py and common/rest.py; venue order,
replace, activities and websocket references read 2026-11-10. Replacement
proposal/confirmation follows NT crates/adapters/architect_ax/src/execution.rs.
House namespace, executing-exit guard and pacing: ADR-0007/0009, LEAD-2201.
Core owns trading state. This client retains venue identity evidence only.
"""

import asyncio
import os
import re
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from threading import Event
from typing import Any

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.models import Order
from alpaca.trading.stream import TradingStream
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.live.clients import ExecutionClient
from nautilus_trader.model import (
    AccountBalance,
    ClientOrderId,
    Money,
    OrderStatus,
    VenueOrderId,
)

from sextant.execution.pacer import AccountPacer, ActionKind
from sextant.risk.controls import Controls

from .reports import _decimal, fill_report, order_status_report
from .wire import AccountGateway, guard_mutation, house_id, submit_payload


class IncompleteCoverage(RuntimeError):
    """Retain good reports and original failed rows; never return a partial list."""

    def __init__(self, reports, failures):
        self.reports, self.failures = reports, failures
        named = "; ".join(str(error) for _, error in failures if "contract" in str(error))
        super().__init__(
            "Alpaca reconciliation coverage incomplete" + (f": {named}" if named else "")
        )


async def _deliver_update(reference, update):
    # Dereference only on the node loop; no client or traceback crosses to SDK thread.
    owner = reference()
    if owner is not None:
        try:
            await owner._on_trade_update(update)
        except IncompleteCoverage as exc:
            owner.failures.extend((row, error.with_traceback(None)) for row, error in exc.failures)


def _run_stream(stream, owner, ready, closing):
    async def run():
        task = asyncio.current_task()
        owner.call_soon_threadsafe(ready.set_result, (asyncio.get_running_loop(), task))
        try:
            if not closing.is_set():
                await stream._run_forever()
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await stream.close()
            finally:
                stream._trade_updates_handler = None

    asyncio.run(run())


# Alpaca order statuses that end an order (orders-at-alpaca, read 2026-11-10).
_TERMINAL = frozenset({"filled", "canceled", "expired", "rejected", "replaced"})


@dataclass(eq=False)
class _Command:
    """One house submit, modify or cancel, registered when its hook schedules it.

    ``sent`` is set only by ``_mark_sent``, the gateway's on-wire hook, before the request
    leaves; that is the one place on-wire evidence is recorded. Afterwards only an
    authoritative answer resolves it: the venue's response, a venue 4xx, or a later read.
    """

    kind: str
    native: Any
    venue_order_id: Any = None
    sent: bool = False
    withdrawn: bool = False  # Pacer admission refuses it from here on.
    settled: bool = False  # A refusal or a venue answer was applied once.
    submitted: bool = False
    row_id: str | None = None  # The venue order a DELETE targets.
    wire_id: str | None = None  # A PATCH's proposal key.
    root: str | None = None  # A submit's engine client order id.
    wire_seq: int = 0  # Its place in send order; 0 until it is on the wire.


# Every trade_updates event the client classifies: alpaca-py TradeEvent at the pin
# (enums.py:321-333) plus the documented status and refusal events (Alpaca streaming,
# read 2026-11-10). Anything else, "restated" included, is incomplete coverage.
_INGRESS = frozenset(
    {
        "new",
        "accepted",
        "rejected",
        "canceled",
        "expired",
        "done_for_day",
        "replaced",
        "pending_new",
        "stopped",
        "pending_cancel",
        "pending_replace",
        "calculated",
        "suspended",
        "accepted_for_bidding",
        "held",
        "pending_review",
        "fill",
        "partial_fill",
        "order_replace_rejected",
        "order_cancel_rejected",
    }
)
# Events after which no cancel of the order can still act (Alpaca order statuses).
_TERMINAL_EVENTS = frozenset({"fill", "canceled", "expired", "rejected", "replaced"})


def _unresolved(exc, token) -> bool:
    """After send, only a venue 4xx refusal resolves a command locally.

    alpaca-py rest.py:197-210 raises APIError for 4xx/5xx and returns
    response.json() on 2xx (requests' JSONDecodeError, a ValueError); the session
    call raises requests' RequestException family (ConnectionError, Timeout,
    ChunkedEncodingError, ...). None of these, nor any other exception after the
    gateway's on-wire token, proves the venue did not act. Before it, nothing left.
    """
    if not token.sent:
        return False
    status = exc.status_code if isinstance(exc, APIError) else None
    return not (status is not None and 400 <= status < 500)


class AlpacaExecutionClient(ExecutionClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.house_prefix = getattr(self.config, "house_prefix", "")
        self.gateway: AccountGateway | None = None
        self.coverage_complete = False
        self._active: dict[str, str] = {}
        self._roots: dict[str, str] = {}
        self._proposals: dict[str, tuple[str, str]] = {}
        self._sequence: dict[str, int] = {}
        self.failures: list[tuple[object, Exception]] = []
        self._executing: set[str] = set()
        self._cancels: set[str] = set()  # Venue ids with a sent, unanswered DELETE.
        self._stream = None
        self._stream_task = None
        self._stream_ready = None
        self._closing = Event()
        self._actions: set[asyncio.Task] = set()
        self._submissions: dict[str, _Command] = {}
        self._commands: set[_Command] = set()
        self.late_answers = 0  # Venue answers to a command an earlier answer settled.
        self._active_n: dict[str, int] = {}  # Successor number of each root's active order.
        self._attempts: list[_Command] = []  # DELETEs on the wire with no venue answer yet
        self._cancel_answered: set[str] = set()  # venue ids with an answered cancel attempt
        self._wire_seq = 0
        # No invented commission: caller supplies an evidenced Money per execution.
        self.commission_for_fill: Callable[[dict], Money] | None = None

    def _queue_action(self, operation, name, token: _Command | None = None):
        # NT's Python client queue is FIFO; await no wire receipt in its hook.
        # The pinned AX adapter likewise spawns supervised command work.
        if self._closing.is_set():
            operation.close()
            if token is not None:  # Nothing left: refuse rather than leave it pending.
                self._refuse(token, f"{token.kind} not sent: execution client is closing")
            raise RuntimeError("execution client is closing")
        try:
            task = self.create_task(operation, name)
        except BaseException:
            operation.close()
            if token is not None:  # No task exists, so no done callback can refuse it.
                self._refuse(token, f"{token.kind} not sent: scheduling failed")
            raise
        self._actions.add(task)
        task.add_done_callback(self._actions.discard)
        if token is not None:
            self._commands.add(token)
            task.add_done_callback(lambda done: self._task_done(token, done))

    def _task_done(self, token: _Command, task) -> None:
        # Any cancellation (disconnect, node stop, a timeout wrapper, runner teardown),
        # even before the coroutine's first step, ends here; only unsent work is refused.
        self._commands.discard(token)
        if task.cancelled() and not token.sent:
            self._refuse(token, f"{token.kind} not sent before cancellation")

    def _mark_sent(self, token: _Command) -> None:
        """The send boundary: the one place on-wire evidence is recorded."""
        token.sent = True
        self._wire_seq += 1
        token.wire_seq = self._wire_seq
        if token.kind == "cancel" and token.row_id is not None:
            self._cancels.add(token.row_id)
            self._attempts.append(token)

    def _answer_cancels(self, row_id, *, before=None, oldest=False) -> list[_Command]:
        """One token per engine CancelOrder (command_id, execution/cancel.rs:43), as Bybit keys
        each request (websocket/dispatch.rs:125): a read answers only attempts sent before it."""
        live = [t for t in self._attempts if t.row_id == row_id]
        live = [t for t in live if before is None or t.wire_seq <= before][: 1 if oldest else None]
        for token in live:
            self._drop(token)
        return live

    def _drop(self, token: _Command) -> None:
        token.settled = True
        if token in self._attempts:
            self._attempts.remove(token)
            self._cancel_answered.add(str(token.row_id))
        if not any(t.row_id == token.row_id for t in self._attempts):
            self._cancels.discard(str(token.row_id))

    def _answered(self, kind: str, key: str | None) -> None:
        """An authoritative answer settles the live sent command it answers, once.

        Whichever comes first (the venue's response, a stream event or a read) settles
        the command; a later answer for it emits nothing (review e5r3-99ac5bf).
        """
        for token in self._commands:
            if (
                token.kind == kind
                and token.sent
                and key in (token.row_id, token.wire_id, token.root)
            ):
                token.settled = True

    def _refuse(self, token: _Command, reason: str) -> None:
        """Apply a definite refusal once: nothing left, or the venue said no (4xx).

        Refusing an unsent command withdraws it in the same act, so a request it left queued
        in the pacer is dropped at admission and never reaches the wire (review of PR 552)."""
        if not token.sent:
            token.withdrawn = True
        if token.settled:
            if token.sent:
                self.late_answers += 1  # An earlier authoritative answer already settled it.
            return
        token.settled = True
        if token.wire_id is not None:
            self._proposals.pop(token.wire_id, None)
        if token.row_id is not None:
            self._drop(token)
        native, now = token.native, self.clock.timestamp_ns()
        if native is None:
            return
        if token.kind == "submit":
            if token.submitted:
                self.generate_order_rejected(native, reason, now, False)
            else:
                self.generate_order_denied(native, reason)
        elif token.kind == "modify":
            self.generate_order_modify_rejected(native, token.venue_order_id, reason, now)
        else:
            self.generate_order_cancel_rejected(native, token.venue_order_id, reason, now)

    def _command(self, kind: str, command) -> _Command:
        native = command.order if kind == "submit" else self.cache.order(command.client_order_id)
        return _Command(kind, native, getattr(command, "venue_order_id", None))

    async def _submit_order(self, command):
        token = self._command("submit", command)
        self._queue_action(self._do_submit_order(command, token), "alpaca-submit", token)

    async def _cancel_order(self, command):
        token = self._command("cancel", command)
        self._queue_action(self._do_cancel_order(command, token), "alpaca-cancel", token)

    async def _query_order(self, command):
        self._queue_action(self._do_query_order(command), "alpaca-query-order")

    async def _query_account(self, command):
        self._queue_action(self._do_query_account(command), "alpaca-query-account")

    async def _connect(self):
        config: Any = self.config
        house_id(self.house_prefix, self.house_prefix)
        if config.pacing_rows is None:
            raise ValueError("execution pacing rows unavailable")
        controls = Controls.from_rows(config.pacing_rows)
        if not callable(self.commission_for_fill):
            raise ValueError("fill reports unavailable: commission evidence required")
        key, secret = os.environ[config.api_key_env], os.environ[config.api_secret_env]
        sdk = TradingClient(key, secret, paper=True, raw_data=True)
        self.gateway = AccountGateway(
            sdk, AccountPacer(controls, self.clock.timestamp_ns), self._position_counts
        )
        await self._do_query_account(None)
        self._stream = TradingStream(key, secret, paper=True, raw_data=True)
        loop = asyncio.get_running_loop()
        reference = weakref.ref(self)

        async def receive(update):
            # The SDK owns its own loop; every cache/output access stays on node loop.
            await asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(_deliver_update(reference, update), loop)
            )

        self._stream.subscribe_trade_updates(receive)
        self._closing.clear()
        self._stream_ready = loop.create_future()
        self._stream_task = self.create_task(
            asyncio.to_thread(_run_stream, self._stream, loop, self._stream_ready, self._closing),
            "trade-updates",
        )

    async def _disconnect(self):
        # Disconnect never cancels orders or closes positions.
        self.coverage_complete = False
        self._closing.set()
        for token in tuple(self._commands):
            if not token.sent:
                # Positive not-sent evidence: the admission check now refuses it.
                token.withdrawn = True
                self._refuse(token, f"{token.kind} not sent before disconnect")
        actions = tuple(self._actions)
        for action in actions:
            action.cancel()
        if actions:
            await asyncio.gather(*actions, return_exceptions=True)
        if self._stream_task is not None and self._stream_ready is not None:
            if not self._stream_task.done():
                loop, task = await asyncio.shield(self._stream_ready)
                if not loop.is_closed():
                    loop.call_soon_threadsafe(task.cancel)
            await asyncio.shield(self._stream_task)
            self._stream_task = self._stream_ready = None
        if self.gateway is not None:
            await self.gateway.close()

    def _position_counts(self):
        opened = len(self.cache.positions_open(venue=self.venue, account_id=self.account_id))
        exiting = len(
            {
                o.instrument_id
                for o in self.cache.orders_open(venue=self.venue, account_id=self.account_id)
                if o.is_sell
            }
        )
        return opened, exiting

    async def _call(self, kind, method, path, data=None, **kwargs):
        if self.gateway is None:
            raise RuntimeError("account gateway is disconnected")
        return await self.gateway.call(kind, method, path, data, **kwargs)

    def _instrument_id(self, row):
        from nautilus_trader.model import InstrumentId

        return InstrumentId.from_str(f"{row['symbol']}.{self.venue}")

    def _instrument(self, row):
        instrument = self.cache.instrument(self._instrument_id(row))
        if instrument is None:
            raise ValueError("report instrument is unavailable")
        return instrument

    async def _identity(self, row):
        wire_id, venue_id = row["client_order_id"], row["id"]
        if not wire_id.startswith(self.house_prefix) or not self.house_prefix:
            return ClientOrderId(wire_id)
        root = re.sub(r"-r[0-9]+$", "", wire_id)
        suffix = re.search(r"-r([0-9]+)$", wire_id)
        number = int(suffix[1]) if suffix else 0
        # House successors are numbered r1, r2, ...: an older number is never bound again.
        stale = number < self._active_n.get(root, -1)
        if wire_id != root:
            raise ValueError("replacement namespace requires parent evidence")
        known_predecessor = stale or (
            venue_id in self._roots and self._active.get(root) not in (None, venue_id)
        )
        if not row.get("replaced_by") and not known_predecessor:
            self._active[root], self._active_n[root] = venue_id, number
        self._roots[venue_id] = root
        self._sequence[root] = max(self._sequence.get(root, 0), number)
        return ClientOrderId(root)

    def _settle(self, row, issued: int):
        """Resolve an unanswered cancel against this order from an authoritative read.

        Alpaca order statuses: pending_cancel is still waiting; a working status
        proves the DELETE did not apply. After its retries the engine closes a
        PENDING_CANCEL order (manager.rs:1935-1939); never read a working order closed.
        """
        if row["status"] in ("pending_replace", "pending_cancel"):
            return
        cancel_lost = self._answer_cancels(row["id"], before=issued)
        if row["status"] == "replaced" or row.get("replaced_by"):
            return
        now, venue_id = self.clock.timestamp_ns(), VenueOrderId(row["id"])
        root = self._roots.get(row["id"])
        if cancel_lost and root is not None and row["status"] not in _TERMINAL:
            native = self.cache.order(ClientOrderId(root))
            if getattr(native, "status", None) == OrderStatus.PENDING_CANCEL:
                self.generate_order_cancel_rejected(
                    native, venue_id, "venue order still working after unanswered cancel", now
                )

    def _parse_order(self, row, stable):
        # E3 validates each row independently; a typed list is never requested.
        return order_status_report(
            Order.model_validate(row),
            account_id=self.account_id,
            instrument=self._instrument(row),
            ts_init=self.clock.timestamp_ns(),
            client_order_id=stable,
        )

    async def _report(self, row, stable=None):
        stable = stable or await self._identity(row)
        self._answered("submit", str(stable))  # The venue holds the order: the POST is answered.
        if self._roots.get(row["id"]) == str(stable) and self._active.get(str(stable)) != row["id"]:
            return None  # Suppress stale predecessor state, not its execution reports.
        return self._parse_order(row, stable)

    def _mutation_admitted(self, command, row):
        native = self.cache.order(command.client_order_id)
        return (
            row["id"] not in self._executing
            and self._active.get(str(command.client_order_id)) == row["id"]
            and not (
                native is not None
                and (
                    getattr(native, "is_triggered", False) is True
                    or (
                        getattr(native, "is_sell", False) is True
                        and native.filled_qty.as_decimal() > 0
                    )
                )
            )
        )

    async def _current(self, command):
        issued = self._wire_seq
        root = house_id(str(command.client_order_id), self.house_prefix)
        venue = self._active.get(root)
        path = f"/orders/{venue}" if venue else "/orders:by_client_order_id"
        row = await self._call(
            ActionKind.QUERY, "get", path, {} if venue else {"client_order_id": root}
        )
        if row.get("replaced_by"):
            row = await self._call(ActionKind.QUERY, "get", f"/orders/{row['replaced_by']}")
        if str(await self._identity(row)) != root:
            raise ValueError("venue order is outside requested house namespace")
        self._settle(row, issued)
        self._parse_order(row, command.client_order_id)
        guard_mutation(row, self.house_prefix)
        if not self._mutation_admitted(command, row):
            raise ValueError("executing exit cannot be mutated")
        return row

    async def _do_submit_order(self, command, token: _Command | None = None):
        native = command.order
        token = token or _Command("submit", native)
        try:
            payload = submit_payload(native, command.params or {}, self.house_prefix)
        except ValueError as exc:
            token.settled = True
            self.generate_order_denied(native, str(exc))
            return
        self.generate_order_submitted(native)
        token.submitted = True
        root = token.root = str(native.client_order_id)
        self._submissions[root] = token
        kind = ActionKind.REDUCE if native.side.name == "SELL" else ActionKind.SUBMIT
        try:
            row = await self._call(
                kind,
                "post",
                "/orders",
                payload,
                admission=lambda: not token.withdrawn,
                on_wire=lambda: self._mark_sent(token),
            )
        except Exception as exc:
            if _unresolved(exc, token):
                raise  # Sent: the venue's later status decides, never a local reject.
            sent = token.sent
            self._refuse(
                token, "venue submit refused" if sent else "submission refused before wire"
            )
            return
        finally:
            if self._submissions.get(root) is token:
                self._submissions.pop(root)
        token.settled = True  # The venue's response answers the submit.
        report = await self._report(row)
        if report is not None:
            self._handle_report(report)

    async def _do_cancel_order(self, command, token: _Command | None = None):
        token = token or self._command("cancel", command)
        native = token.native
        try:
            root = house_id(str(command.client_order_id), self.house_prefix)
            pending = self._submissions.get(root)
            if pending is not None and not pending.sent:
                if (
                    native is not None
                    and getattr(native, "is_sell", False) is True
                    and (
                        getattr(native, "is_triggered", False) is True
                        or native.filled_qty.as_decimal() > 0
                    )
                ):
                    raise ValueError("executing exit cannot be mutated")
                pending.withdrawn = pending.settled = token.settled = True
                if native is not None:
                    self.generate_order_canceled(native, None, self.clock.timestamp_ns())
                return
            row = await self._current(command)
            token.row_id = row["id"]
            await self._call(
                ActionKind.CANCEL,
                "delete",
                f"/orders/{row['id']}",
                admission=lambda: not token.withdrawn and self._mutation_admitted(command, row),
                on_wire=lambda: self._mark_sent(token),
            )
            # Alpaca's DELETE "Attempts to cancel an Open Order" (204): an attempt, not a
            # terminal cancel. The marker stays until a terminal confirmation or a refusal.
            token.settled = True
        except Exception as exc:
            if _unresolved(exc, token):
                raise  # Sent: the venue's later status decides, never a local reject.
            self._refuse(token, "cancellation refused")

    async def _cancel_all_orders(self, command):
        raise NotImplementedError("account-wide cancellation is forbidden")

    async def _do_query_account(self, command: Any):
        row = await self._call(ActionKind.QUERY, "get", "/account")
        # NT IBKR account.rs:397-419 and types/balance.rs:149-172: net value,
        # available funds, then clamp and derive locked after Money rounding.
        total = _decimal(row["equity"], "account equity")
        available = _decimal(row["buying_power"], "account buying power")
        _decimal(row["cash"], "account cash")
        if total >= 0:
            available = min(total, max(Decimal(0), available))
        currency = row["currency"]
        total_money = Money.from_str(f"{total} {currency}")
        free_money = Money.from_str(f"{available} {currency}")
        locked = total_money.as_decimal() - free_money.as_decimal()
        self.generate_account_state(
            [
                AccountBalance(
                    total_money,
                    Money.from_str(f"{locked} {currency}"),
                    free_money,
                )
            ],
            [],
            True,
            self.clock.timestamp_ns(),
            info={"buying_power": row["buying_power"], "cash": row["cash"]},
        )

    async def _generate_order_status_report(self, command: Any):
        issued = self._wire_seq
        venue = self._active.get(str(command.client_order_id)) or command.venue_order_id
        if venue is not None:
            row = await self._call(ActionKind.QUERY, "get", f"/orders/{venue}")
        else:
            row = await self._call(
                ActionKind.QUERY,
                "get",
                "/orders:by_client_order_id",
                {"client_order_id": str(command.client_order_id)},
            )
        visited = set()
        while row.get("replaced_by"):
            if row["id"] in visited:
                raise ValueError("replacement lineage cycle")
            visited.add(row["id"])
            row = await self._call(ActionKind.QUERY, "get", f"/orders/{row['replaced_by']}")
        report = await self._report(row)
        self._settle(row, issued)
        if (
            report is not None
            and command.client_order_id is not None
            and (report.client_order_id != command.client_order_id)
        ):
            raise IncompleteCoverage([], [(row, ValueError("query reached foreign successor"))])
        return report

    async def _do_query_order(self, command):
        report = await self._generate_order_status_report(command)
        if report is not None:
            self._handle_report(report)

    async def _on_trade_update(self, update: dict[str, Any]):
        try:
            await self._process_update(update)
        except Exception as exc:
            self.coverage_complete = False
            if isinstance(exc, IncompleteCoverage):
                raise
            raise IncompleteCoverage([], [(update, exc)]) from exc

    def _record(self, event: str, row: dict) -> bool:
        """Every safety fact the event names, keyed by its venue order id, synchronously on
        arrival and before any await (review e5r4-266edf5 P1). Returns True for a refusal an
        authoritative read already emitted."""
        if row.get("side") == "sell" and event in ("fill", "partial_fill", "stopped"):
            self._executing.add(row["id"])
        if event in _TERMINAL_EVENTS:
            self._answer_cancels(row["id"])  # Terminal: no attempt can still act.
        late = False
        if event == "order_cancel_rejected":
            seen = row["id"] in self._cancel_answered
            late = not self._answer_cancels(row["id"], oldest=True) and seen
        if event == "order_replace_rejected":
            for key, (_, parent) in self._proposals.items():
                if parent == row["id"]:
                    self._answered("modify", key)
            self._proposals = {k: v for k, v in self._proposals.items() if v[1] != row["id"]}
        self.late_answers += late
        return late

    async def _process_update(self, update: dict[str, Any]):
        if update.get("stream") != "trade_updates":
            raise ValueError("raw trade_updates envelope required")
        data = update["data"]
        event, row = data["event"], data["order"]
        if event in ("trade_bust", "trade_correct"):
            self.coverage_complete = False
            raise IncompleteCoverage(
                [], [(update, ValueError("trade correction requires reconciliation"))]
            )
        if event not in _INGRESS:
            self.coverage_complete = False
            raise ValueError("unclassified trade update event")
        late = self._record(event, row)
        # One identity resolution for every event: a successor binds before anything about
        # it is forwarded, and unconfirmed lineage fails here as incomplete coverage.
        stable = await self._identity(row)
        native = self.cache.order(stable)
        now = dt_to_unix_nanos(data.get("timestamp", row["updated_at"]))
        if event in ("order_replace_rejected", "order_cancel_rejected"):
            if native is not None and not late:
                emit = (
                    self.generate_order_modify_rejected
                    if event == "order_replace_rejected"
                    else self.generate_order_cancel_rejected
                )
                emit(native, VenueOrderId(row["id"]), "venue mutation refused", now)
            return
        if event in ("fill", "partial_fill"):
            if self.commission_for_fill is None:
                self.coverage_complete = False
                raise IncompleteCoverage(
                    [], [(update, ValueError("fill commission evidence unavailable"))]
                )
            report = fill_report(
                update,
                account_id=self.account_id,
                instrument=self._instrument(row),
                ts_init=self.clock.timestamp_ns(),
                commission=self.commission_for_fill(data),
                client_order_id=stable,
            )
            self._handle_report(report)
            return
        if event == "stopped" and native is not None:
            self.generate_order_triggered(native, VenueOrderId(row["id"]), now)
        report = await self._report(row, stable)
        if report is not None:
            self._handle_report(report)
