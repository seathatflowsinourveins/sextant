"""ADR-0024 mover-slot allocation.

The recorded 0.4 mover share rounds up: 2 of 5 and 8 of 20 slots. Custody
counts first, and qualified candidates retain the caller's sourced ranking
order. Session boundaries are supplied receipts: this module never reads a
clock, so 20:00 is the caller's new segment.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

SHARE = Decimal("0.4")


@dataclass(frozen=True)
class Candidate:
    """One caller-ranked candidate, qualified by the caller's current evidence."""

    symbol: str
    first_moved_ns: int
    qualified: bool = True


@dataclass(frozen=True)
class Allocation:
    armed: tuple[str, ...]
    slots: int
    reason: str

    def __bool__(self) -> bool:
        return bool(self.armed)


@dataclass(frozen=True)
class SlotPool:
    """The recorded 0.4 mover reservation."""

    share: Decimal = SHARE

    def slots(self, candidates: int) -> int:
        if candidates <= 0:
            return 0
        return int((Decimal(candidates) * self.share).to_integral_value(rounding=ROUND_CEILING))

    def allocate(
        self, candidates: tuple[Candidate, ...], *, custody_open: int | None
    ) -> Allocation:
        if custody_open is None:
            return Allocation((), 0, "custody_unknown")
        if custody_open < 0:
            return Allocation((), 0, "custody_invalid")
        slots = self.slots(len(candidates))
        remaining = max(0, slots - custody_open)
        eligible = [candidate for candidate in candidates if candidate.qualified]
        armed = tuple(candidate.symbol for candidate in eligible[:remaining])
        return Allocation(armed, slots, "filled" if armed else "pass")
