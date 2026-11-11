"""Alpaca paper ExecutionClient following NT d53849b's Python adapter template.

AP cc4cb3b7 trading/{client,stream}.py and common/rest.py; venue order,
replace, activities and websocket references read 2026-11-10. Replacement
proposal/confirmation follows NT crates/adapters/architect_ax/src/execution.rs.
House namespace, executing-exit guard and pacing: ADR-0007/0009, LEAD-2201.
Core owns trading state. This client retains venue identity evidence only.
"""

import asyncio
import re
from collections.abc import Callable
from decimal import Decimal
from threading import Event
from typing import Any

from alpaca.common.exceptions import APIError
from alpaca.trading.models import Order
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.live.clients import ExecutionClient
from nautilus_trader.model import (
    AccountBalance,
    ClientOrderId,
    Money,
    VenueOrderId,
)

from sextant.execution.pacer import ActionKind

from .constants import NOT_IMPLEMENTED
from .reports import _decimal, fill_report, order_status_report
from .wire import AccountGateway, submit_payload


class IncompleteCoverage(RuntimeError):
    """Retain good reports and original failed rows; never return a partial list."""

    def __init__(self, reports, failures):
        self.reports, self.failures = reports, failures
        named = "; ".join(str(error) for _, error in failures if "contract" in str(error))
        super().__init__(
            "Alpaca reconciliation coverage incomplete" + (f": {named}" if named else "")
        )


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
        self._stream = None
        self._stream_task = None
        self._stream_ready = None
        self._closing = Event()
        self._actions: set[asyncio.Task] = set()
        self._submissions: dict[str, dict[str, Any]] = {}
        # No invented commission: caller supplies an evidenced Money per execution.
        self.commission_for_fill: Callable[[dict], Money] | None = None

    def _queue_action(self, operation, name):
        # NT's Python client queue is FIFO; await no wire receipt in its hook.
        # The pinned AX adapter likewise spawns supervised command work.
        if self._closing.is_set():
            operation.close()
            raise RuntimeError("execution client is closing")
        try:
            task = self.create_task(operation, name)
        except BaseException:
            operation.close()
            raise
        self._actions.add(task)
        task.add_done_callback(self._actions.discard)

    async def _submit_order(self, command):
        self._queue_action(self._do_submit_order(command), "alpaca-submit")

    async def _query_order(self, command):
        self._queue_action(self._do_query_order(command), "alpaca-query-order")

    async def _query_account(self, command):
        self._queue_action(self._do_query_account(command), "alpaca-query-account")

    async def _connect(self) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _disconnect(self) -> None:
        """Disconnect from Alpaca: this shell opens no wire to close."""

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
        if wire_id != root:
            raise ValueError("replacement namespace requires parent evidence")
        known_predecessor = venue_id in self._roots and self._active.get(root) not in (
            None,
            venue_id,
        )
        if not row.get("replaced_by") and not known_predecessor:
            self._active[root] = venue_id
        self._roots[venue_id] = root
        suffix = re.search(r"-r([0-9]+)$", wire_id)
        self._sequence[root] = max(self._sequence.get(root, 0), int(suffix[1]) if suffix else 0)
        return ClientOrderId(root)

    def _parse_order(self, row, stable):
        # E3 validates each row independently; a typed list is never requested.
        return order_status_report(
            Order.model_validate(row),
            account_id=self.account_id,
            instrument=self._instrument(row),
            ts_init=self.clock.timestamp_ns(),
            client_order_id=stable,
        )

    async def _report(self, row):
        stable = await self._identity(row)
        if self._roots.get(row["id"]) == str(stable) and self._active.get(str(stable)) != row["id"]:
            return None  # Suppress stale predecessor state, not its execution reports.
        return self._parse_order(row, stable)

    async def _do_submit_order(self, command):
        native = command.order
        try:
            payload = submit_payload(native, command.params or {}, self.house_prefix)
        except ValueError as exc:
            self.generate_order_denied(native, str(exc))
            return
        self.generate_order_submitted(native)
        root = str(native.client_order_id)
        token = {"sent": False, "cancelled": False, "order": native}
        self._submissions[root] = token
        kind = ActionKind.REDUCE if native.side.name == "SELL" else ActionKind.SUBMIT
        try:
            row = await self._call(
                kind,
                "post",
                "/orders",
                payload,
                admission=lambda: not token["cancelled"],
                on_wire=lambda: token.__setitem__("sent", True),
            )
        except ValueError:
            if token["cancelled"]:
                return  # Positive local withdrawal already emitted Canceled.
            if not token["sent"]:
                self.generate_order_rejected(
                    native, "submission refused before wire", self.clock.timestamp_ns(), False
                )
                return
            raise  # A sent request with malformed evidence remains unresolved.
        except APIError as exc:
            if exc.status_code is not None and 400 <= exc.status_code < 500:
                self.generate_order_rejected(
                    native, "venue submit refused", self.clock.timestamp_ns(), False
                )
                return
            raise
        finally:
            if self._submissions.get(root) is token:
                self._submissions.pop(root)
        report = await self._report(row)
        if report is not None:
            self._handle_report(report)

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

    async def _process_update(self, update: dict[str, Any]):
        if update.get("stream") != "trade_updates":
            raise ValueError("raw trade_updates envelope required")
        data = update["data"]
        event, row = data["event"], data["order"]
        if row.get("side") == "sell" and event in ("fill", "partial_fill", "stopped"):
            self._executing.add(row["id"])
        native = self.cache.order(
            ClientOrderId(self._roots.get(row["id"]) or row["client_order_id"])
        )
        now = dt_to_unix_nanos(data.get("timestamp", row["updated_at"]))
        if event in ("order_replace_rejected", "order_cancel_rejected"):
            if event == "order_replace_rejected":
                self._proposals = {k: v for k, v in self._proposals.items() if v[1] != row["id"]}
            if native is not None:
                emit = (
                    self.generate_order_modify_rejected
                    if event == "order_replace_rejected"
                    else self.generate_order_cancel_rejected
                )
                emit(native, VenueOrderId(row["id"]), "venue mutation refused", now)
            return
        if event in ("trade_bust", "trade_correct"):
            self.coverage_complete = False
            raise IncompleteCoverage(
                [], [(update, ValueError("trade correction requires reconciliation"))]
            )
        if event in ("fill", "partial_fill"):
            stable = ClientOrderId(self._roots.get(row["id"]) or row["client_order_id"])
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
        if event not in {
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
        }:
            self.coverage_complete = False
            raise ValueError("unclassified trade update event")
        if event == "stopped" and native is not None:
            self.generate_order_triggered(native, VenueOrderId(row["id"]), now)
        report = await self._report(row)
        if report is not None:
            self._handle_report(report)
