"""Scoped kill/flatten carry from risk/guard.py and selected risk/actor.py methods.

Only positive custody snapshots drive intents. The runtime alone may construct
orders. A state read failure is retained as UNKNOWN, never initialized as ACTIVE.
"""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from sextant.execution.custody import AccountScope, Custody, FlatReceipt
from sextant.execution.state import decimal, touch_durable, write_atomic
from sextant.risk.controls import Controls
from sextant.risk.gates import Gates


class GuardState(StrEnum):
    UNKNOWN = "UNKNOWN"
    ACTIVE = "ACTIVE"
    HALTED = "HALTED"
    REDUCING = "REDUCING"


@dataclass(frozen=True)
class GuardIntent:
    kind: str
    instrument: str
    client_order_id: str | None = None
    quantity: Decimal | None = None


class Guard:
    def __init__(
        self, scope: AccountScope, path: Path, marker: Path, controls: Controls, *, mode: str
    ):
        self.scope, self.path, self.marker, self.controls = scope, path, marker, controls
        self.gates = Gates(mode, controls, lane=scope.key)
        self.loaded, self.state = False, GuardState.UNKNOWN
        self.reasons: set[str] = {"state_not_loaded"}
        self.flattened = False
        self.halted_at = self.last_cancel = self.last_flatten = self.last_epoch = 0
        self.errors: list[str] = []
        self.day_start_equity: str | None = None
        self.economic_hwm: str | None = None
        self.oer: dict = {}
        self.trading_day: str | None = None
        if path.exists():
            try:
                data = json.loads(path.read_text())
                if data["scope"] != scope.key or data["params_hash"] != controls.params_hash:
                    raise ValueError("guard account/parameters mismatch")
                self.state = GuardState(data["state"])
                if not isinstance(data["reasons"], list) or not all(
                    isinstance(reason, str) and reason for reason in data["reasons"]
                ):
                    raise ValueError("guard reasons invalid")
                self.reasons = set(data["reasons"])
                self.flattened = data["flattened"]
                if type(self.flattened) is not bool or (
                    self.state is GuardState.ACTIVE and (self.reasons or self.flattened)
                ):
                    raise ValueError("guard state inconsistent")
                for name in ("halted_at", "last_cancel", "last_flatten", "last_epoch"):
                    if type(data[name]) is not int or data[name] < 0:
                        raise ValueError("guard timestamp invalid")
                    setattr(self, name, data[name])
                self.gates.restore(data["observations"])
                self.day_start_equity, self.economic_hwm = (
                    data["day_start_equity"],
                    data["economic_hwm"],
                )
                for value in (self.day_start_equity, self.economic_hwm):
                    if value is not None:
                        if type(value) is not str:
                            raise ValueError("anchor must be a Decimal string")
                        decimal(Decimal(value), "persisted equity anchor")
                self.oer = data["oer"]
                if not isinstance(self.oer, dict) or (
                    self.oer
                    and (
                        not isinstance(self.oer.get("day"), str)
                        or any(
                            type(self.oer.get(key)) is not int or self.oer[key] < 0
                            for key in ("actions", "fills", "requests")
                        )
                    )
                ):
                    raise ValueError("unknown persisted operational counters")
                self.trading_day = data["trading_day"]
                self.loaded = True
            except (ValueError, KeyError, TypeError, OSError) as error:
                self.errors.append(str(error))
                self.state, self.reasons = GuardState.UNKNOWN, {"state_not_loaded"}
        if marker.exists():
            self.reasons.add("owner_kill")
            self.state, self.flattened = GuardState.HALTED, False

    def _save(self) -> bool:
        if not self.loaded:
            return False
        try:
            write_atomic(
                self.path,
                dict(
                    scope=self.scope.key,
                    params_hash=self.controls.params_hash,
                    state=str(self.state),
                    reasons=sorted(self.reasons),
                    flattened=self.flattened,
                    halted_at=self.halted_at,
                    last_cancel=self.last_cancel,
                    last_flatten=self.last_flatten,
                    last_epoch=self.last_epoch,
                    observations=self.gates.to_state(),
                    day_start_equity=self.day_start_equity,
                    economic_hwm=self.economic_hwm,
                    oer=self.oer,
                    trading_day=self.trading_day,
                ),
            )
            return True
        except OSError as error:
            self.errors.append(str(error))
            return False

    def initialize(self, receipt: FlatReceipt | None):
        if (
            self.path.exists()
            or self.marker.exists()
            or receipt is None
            or receipt.scope != self.scope
        ):
            raise ValueError(
                "fresh guard initialization requires positive flat custody and no old state"
            )
        self.loaded, self.state, self.reasons = True, GuardState.ACTIVE, set()
        self.last_epoch = receipt.epoch
        if not self._save():
            self.state, self.reasons = GuardState.UNKNOWN, {"state_not_loaded"}
            raise ValueError("guard initialization could not persist")

    def entry_allowed(self) -> bool:
        return (
            self.loaded
            and self.state is GuardState.ACTIVE
            and not self.reasons
            and not self.marker.exists()
        )

    def record_evidence(
        self, *, trading_day: str, day_start_equity: Decimal, economic_hwm: Decimal, oer: dict
    ):
        date.fromisoformat(trading_day)
        decimal(day_start_equity, "day-start equity")
        decimal(economic_hwm, "economic high-water mark")
        if oer.get("day") != trading_day or any(
            type(oer.get(key)) is not int or oer[key] < 0
            for key in ("actions", "fills", "requests")
        ):
            raise ValueError("OER evidence has invalid day/counters")
        if self.trading_day == trading_day and any(
            oer[key] < self.oer.get(key, 0) for key in ("actions", "fills", "requests")
        ):
            raise ValueError("same-day wire history cannot reset")
        if self.trading_day != trading_day or self.day_start_equity is None:
            self.day_start_equity = str(day_start_equity)
        previous = Decimal(self.economic_hwm) if self.economic_hwm is not None else economic_hwm
        self.economic_hwm = str(max(previous, economic_hwm))
        self.trading_day, self.oer = trading_day, dict(oer)
        if not self._save():
            raise ValueError("financial evidence cannot be persisted")

    def kill(self, reason: str, *, now: int):
        # Persist the owner's marker before every fallible callback/state save.
        try:
            touch_durable(self.marker)
        except OSError as error:
            self.errors.append(str(error))
        self.reasons.add(reason)
        if self.state in {GuardState.ACTIVE, GuardState.UNKNOWN}:
            self.halted_at = now
            self.last_cancel = max(0, now - self.controls.ns("cancel_retry_s"))
        self.state, self.flattened = GuardState.HALTED, False
        self._save()

    def step(self, custody: Custody, *, now: int) -> list[GuardIntent]:
        if self.marker.exists() and self.state is GuardState.ACTIVE:
            self.kill("owner_kill", now=now)
        snap = custody.snapshot
        if (
            custody.scope != self.scope
            or not custody.loaded
            or snap is None
            or not snap.complete
            or snap.known_at > now
            or custody.frozen
        ):
            self.reasons.add("unknown_execution_state")
            self.state = GuardState.HALTED
            self._save()
            return []
        self.last_epoch = max(self.last_epoch, snap.epoch)
        if self.state is GuardState.ACTIVE:
            return []
        receipt = custody.flat_receipt()
        if receipt is not None:
            self.state, self.flattened = GuardState.HALTED, True
            self._save()
            return []
        entries = [
            order
            for order in snap.orders
            if order.side == "BUY"
            and not order.terminal
            and custody.may_cancel(order.client_order_id)
        ]
        actions = []
        cancel_due = now == self.halted_at or now - self.last_cancel >= self.controls.ns(
            "cancel_retry_s"
        )
        if entries and cancel_due:
            self.last_cancel = now
            actions.extend(
                GuardIntent("CANCEL_ENTRY", o.instrument, o.client_order_id) for o in entries
            )
        if (
            entries
            and not self.flattened
            and self.state is GuardState.HALTED
            and (now - self.halted_at < self.controls.ns("cancel_timeout_s"))
        ):
            self._save()
            return actions
        due = (
            self.state is not GuardState.REDUCING
            or self.flattened
            or now - self.last_flatten >= self.controls.ns("flatten_tick_s")
        )
        self.state, self.flattened = GuardState.REDUCING, False
        if due:
            self.last_flatten = now
            for iid in snap.positions:
                quantity = custody.available_exit(iid)
                if quantity > 0:
                    actions.append(GuardIntent("FLATTEN", iid, quantity=quantity))
                elif snap.positions[iid] > 0 and custody.owner_reserved(iid) >= snap.positions[iid]:
                    actions.append(GuardIntent("OWNER_RESERVED_UNPROTECTED", iid))
        self._save()
        return actions

    def release(self, reason: str, receipt: FlatReceipt | None, *, now: int) -> bool:
        if (
            not self.loaded
            or self.state is not GuardState.HALTED
            or not self.flattened
            or receipt is None
            or receipt.scope != self.scope
            or receipt.epoch < self.last_epoch
            or receipt.known_at > now
            or reason not in self.reasons
        ):
            return False
        self.reasons.remove(reason)
        if self.reasons:
            self._save()
            return False
        self.state, self.flattened = GuardState.ACTIVE, False
        if not self._save():
            self.state, self.reasons = GuardState.HALTED, {reason}
            return False
        self.marker.unlink(missing_ok=True)
        return True
