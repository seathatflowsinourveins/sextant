"""ADR-0024 mover-slot allocation.

The owner ruling records the 0.4 share as 2 of 5 and 8 of 20 mover slots, shared
with the potential pool. Custody counts first, qualified candidates fill in
first-moved order, and unused slots pass over. Session boundaries are supplied
receipts: this module never reads a clock, so 20:00 is the caller's new segment.
"""

from dataclasses import dataclass
from decimal import Decimal

SHARE = Decimal("0.4")


@dataclass(frozen=True)
class Candidate:
    """One arming candidate, qualified by the caller's own current evidence."""

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
    """The recorded 0.4 pool, shared by movers and the potential pool."""

    share: Decimal = SHARE

    def slots(self, candidates: int) -> int:
        if candidates <= 0:
            return 0
        return int(Decimal(candidates) * self.share)

    def allocate(
        self, candidates: tuple[Candidate, ...], *, custody_open: int | None
    ) -> Allocation:
        if custody_open is None:
            return Allocation((), 0, "custody_unknown")
        if custody_open < 0:
            return Allocation((), 0, "custody_invalid")
        slots = self.slots(len(candidates))
        remaining = max(0, slots - custody_open)
        eligible = sorted(
            (candidate for candidate in candidates if candidate.qualified),
            key=lambda candidate: candidate.first_moved_ns,
        )
        armed = tuple(candidate.symbol for candidate in eligible[:remaining])
        return Allocation(armed, slots, "filled" if armed else "pass")
