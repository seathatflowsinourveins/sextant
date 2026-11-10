"""Outside-RTH emulation of B's native trailing stop.

Alpaca's native trailing stop does not trigger outside regular market hours, so B rests the
native order and emulates its trigger from the feed: the trigger is NautilusTrader's own
BID_ASK trailing calculation, and a persistent run of eligible trades at or below it
releases one marketable LIMIT with ``extended_hours=True`` (``docs/design.md``:31 and
``docs/adr/0005-exit-engine.md`` X4; Alpaca orders page read 2026-11-09).

The node's feed is the caller's concern: this module is pure state over observations.
``ExitParams`` supplies the breach count and span and the chaser; no value is duplicated
here.
"""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum

from sextant.exits.policy import BreachRun, ExitParams, chase_limit
from sextant.paper.trailing import (
    Side,
    TrailingOffsetType,
    TriggerType,
    trailing_stop_calculate,
)

NS = Decimal(1_000_000_000)
# The quote_max_age_s row (LANES:15) records "seconds (RTH; 2 outside)".
OUTSIDE_QUOTE_MAX_AGE_S = Decimal(2)
SUB_DOLLAR_INCREMENT = Decimal("0.0001")


class OutsideRthError(RuntimeError):
    """The emulation cannot name a release price from the state it has."""


class OutsideRthState(StrEnum):
    WAITING = "waiting"
    ARMED = "armed"
    RELEASED = "released"


class OutsideRthTrail:
    """The emulated outside-RTH trigger and its one-shot breach release."""

    def __init__(
        self,
        *,
        trail_fraction: Decimal,
        params: ExitParams,
        price_increment: Decimal = Decimal("0.01"),
    ) -> None:
        if not Decimal(0) < trail_fraction < Decimal(1):
            raise ValueError("trail_fraction must be between 0 and 1")
        if params.breach_persist_count < 1:
            raise ValueError("breach_persist_count must be at least one")
        if price_increment <= 0:
            raise ValueError("price_increment must be positive")
        self._offset = trail_fraction * Decimal(10_000)
        self._params = params
        self._increment = price_increment
        self._trigger: Decimal | None = None
        self._breach = BreachRun()
        self._bid: Decimal | None = None
        self._last: Decimal | None = None
        self._quote_ts_ns: int | None = None
        self._breached = False
        self._pending = False
        self._released = False

    @property
    def trigger(self) -> Decimal | None:
        return self._trigger

    @property
    def has_trigger(self) -> bool:
        return self._trigger is not None

    @property
    def breached(self) -> bool:
        return self._breached

    @property
    def pending(self) -> bool:
        return self._pending

    @property
    def released(self) -> bool:
        return self._released

    @property
    def state(self) -> OutsideRthState:
        if self._released:
            return OutsideRthState.RELEASED
        return OutsideRthState.ARMED if self._trigger is not None else OutsideRthState.WAITING

    def adopt(self, trigger: Decimal | None, ts_ns: int) -> None:
        """Seed the trigger from the resting native trail's stop price and restart the run."""

        if self._released:
            raise OutsideRthError("cannot adopt a trigger while a release is outstanding")
        if trigger is not None and trigger <= 0:
            raise OutsideRthError("an adopted trigger must be positive")
        self._trigger = trigger
        self._breach = BreachRun()
        self._breached = False

    def observe_quote(
        self,
        *,
        bid: Decimal | None,
        ask: Decimal | None,
        last: Decimal | None,
        ts_ns: int,
    ) -> Decimal | None:
        """Move the trigger up when the calculator names a better one; never lower it."""

        if self._released:
            return None
        if bid is None or ask is None or bid <= 0 or ask <= 0 or bid > ask:
            return None
        self._bid = bid
        self._last = last
        self._quote_ts_ns = ts_ns
        if self._pending:
            # The handover reprices from the freshest quote; the trigger no longer moves.
            return None
        increment = SUB_DOLLAR_INCREMENT if bid < 1 else self._increment
        candidate, _ = trailing_stop_calculate(
            increment,
            side=Side.SELL,
            offset=self._offset,
            offset_type=TrailingOffsetType.BASIS_POINTS,
            trigger_type=TriggerType.BID_ASK,
            stored_trigger_px=self._trigger,
            bid=bid,
            ask=ask,
        )
        if candidate is not None and candidate < 1 and increment != SUB_DOLLAR_INCREMENT:
            candidate, _ = trailing_stop_calculate(
                SUB_DOLLAR_INCREMENT,
                side=Side.SELL,
                offset=self._offset,
                offset_type=TrailingOffsetType.BASIS_POINTS,
                trigger_type=TriggerType.BID_ASK,
                stored_trigger_px=self._trigger,
                bid=bid,
                ask=ask,
            )
        if candidate is None:
            return None
        self._trigger = candidate
        return candidate

    def observe_trade(self, price: Decimal, ts_ns: int) -> bool:
        """Count one eligible print against the trigger; true on the completed breach."""

        if self._released or self._pending or self._trigger is None or price <= 0:
            return False
        breached = self._breach.observe(price, self._trigger, ts_ns, self._params)
        if breached:
            self._breached = True
        return breached

    def release_price(self, ts_ns: int, *, fresh: bool | None = None) -> Decimal:
        """The one marketable LIMIT price: the fresh bid on Alpaca's increment ladder.

        ``fresh`` is the caller's priceability predicate (the same one that reports the
        shares armed). ``None`` keeps the older vendor-timestamp check used by the
        emulation's own proofs; ``True`` trusts the caller's successful poll and accepts a
        standing quote, including one stamped after the print that completed the breach.
        """

        if self._released:
            raise OutsideRthError("a release is already outstanding")
        if not self._breached:
            raise OutsideRthError("no persistent breach has completed")
        if self._quote_ts_ns is None or self._bid is None:
            raise OutsideRthError("a fresh quote is required to price the release")
        if fresh is False:
            raise OutsideRthError("a fresh quote is required to price the release")
        if fresh is None:
            age_ns = ts_ns - self._quote_ts_ns
            if age_ns < 0 or Decimal(age_ns) / NS > OUTSIDE_QUOTE_MAX_AGE_S:
                raise OutsideRthError("a fresh quote is required to price the release")
        price = chase_limit(self._bid, self._last, self._params)
        quantum = Decimal("0.01") if price >= 1 else SUB_DOLLAR_INCREMENT
        collared = price.quantize(quantum, rounding=ROUND_FLOOR)
        if collared <= 0:
            raise OutsideRthError("the release price must be positive")
        return collared

    def reset_run(self) -> None:
        """Forget a partial breach run without moving the ratcheted trigger."""

        if self._pending or self._released:
            return
        self._breach = BreachRun()
        self._breached = False

    def begin_release(self, ts_ns: int) -> None:
        """Mark the completed breach as waiting for its trail's terminal cancellation."""

        if self._released:
            raise OutsideRthError("a release is already outstanding")
        if self._pending:
            raise OutsideRthError("a release is already pending")
        if not self._breached:
            raise OutsideRthError("no persistent breach has completed")
        self._pending = True

    def mark_released(self, ts_ns: int) -> None:
        if not self._pending:
            raise OutsideRthError("no release is pending")
        self._pending = False
        self._released = True

    def rearm(self) -> None:
        """Forget the release and restart the breach run, keeping the ratcheted trigger."""

        self._pending = False
        self._released = False
        self._breached = False
        self._breach = BreachRun()
