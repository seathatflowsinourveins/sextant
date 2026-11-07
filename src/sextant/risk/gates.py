"""ADR-0010 paper observation, adapted from pinned safeguards/__init__.py.

IDs below are the guard rows in safeguards/rows_ibkr.py at the manifest pin.
Other IDs enforce and log ERROR until their sourced registry row is carried.
"""

import logging
from decimal import Decimal
from typing import Any

from sextant.execution.state import decimal
from sextant.risk.controls import Controls

OBSERVE = frozenset(
    {
        "guard.daily_loss",
        "guard.drawdown",
        "guard.max_gross_exposure",
        "guard.leverage_exposure",
        "guard.account_unavailable",
        "guard.persistence",
        "guard.account_drift",
        "guard.state_recovery",
        "guard.automatic_halt",
        "guard.orphan_close",
        "guard.orphan_cancel",
    }
)
ENFORCE = frozenset({"guard.owner_kill"})


class Gates:
    def __init__(self, mode: str, controls: Controls, *, lane: str | None = None):
        if mode not in {"paper", "sim", "replay", "live"}:
            raise ValueError("unknown lane mode")
        self.mode, self.controls = mode, controls
        self.lane = lane
        self.edges: dict[tuple[str, str | None], tuple[int, Decimal | None]] = {}
        self.events: list[dict] = []

    def trigger(
        self,
        gate_id: str,
        *,
        now: int,
        value: Decimal | None = None,
        limit: Decimal | None = None,
        instrument: str | None = None,
        cleared=False,
        action_suppressed: str | None = None,
    ) -> bool:
        if gate_id not in OBSERVE | ENFORCE:
            logging.getLogger(__name__).error("unregistered safeguard: %s; enforcing", gate_id)
            return True
        if self.mode != "paper" or gate_id in ENFORCE:
            return True
        key = gate_id, instrument
        previous = self.edges.get(key)
        if cleared:
            if previous is None:
                return False
            self.edges.pop(key)
        else:
            for number in (value, limit):
                if number is not None:
                    decimal(abs(number), "observed monetary value")
            step = (
                self.controls["observation_leverage_step"]
                if "leverage" in gate_id
                else None
                if limit is None
                else abs(limit) * self.controls["observation_money_step_fraction"]
            )
            material = bool(
                previous
                and value is not None
                and previous[1] is not None
                and step is not None
                and step > 0
                and abs(value - previous[1]) >= step
            )
            if (
                previous
                and now >= previous[0]
                and not material
                and (now - previous[0] < self.controls.ns("observation_reminder_s"))
            ):
                return False
            self.edges[key] = now, value
        event: dict[str, Any] = dict(
            id=gate_id,
            ts_ns=now,
            lane=self.lane,
            strategy_id=None,
            instrument_id=instrument,
            value=None if value is None else str(value),
            limit=None if limit is None else str(limit),
            action_suppressed=action_suppressed,
        )
        if cleared:
            event["detail"] = {"cleared": True}
        self.events.append(event)
        if gate_id == "guard.daily_loss" and value is not None and limit is not None:
            logging.getLogger(__name__).warning(
                f"loss limit observed (paper, not enforced): daily_loss {value} >= {limit}"
                + (" cleared" if cleared else "")
            )
        maximum = self.controls["observation_max_edges"]
        if len(self.edges) > maximum:
            oldest = min(self.edges, key=lambda k: self.edges[k][0])
            self.edges.pop(oldest)
        del self.events[:-maximum]
        return False

    def to_state(self) -> list[dict]:
        return [
            dict(
                id=key[0],
                instrument=key[1],
                emitted=at,
                value=None if value is None else str(value),
            )
            for key, (at, value) in self.edges.items()
        ]

    def prune(self, held_or_deployed: set[str]):
        for key in list(self.edges):
            if key[1] is not None and key[1] not in held_or_deployed:
                self.edges.pop(key)

    def restore(self, rows: list[dict]):
        if not isinstance(rows, list) or len(rows) > self.controls["observation_max_edges"]:
            raise ValueError("invalid safeguard observation state")
        for row in rows:
            if row["id"] not in OBSERVE or type(row["emitted"]) is not int:
                raise ValueError("unknown persisted observation")
            value = None if row["value"] is None else Decimal(row["value"])
            if value is not None:
                decimal(abs(value), "persisted observation")
            self.edges[row["id"], row["instrument"]] = row["emitted"], value
