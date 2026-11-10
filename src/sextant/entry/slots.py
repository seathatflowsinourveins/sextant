"""ADR-0024 mover-slot allocation.

Configured capacity supplies the ceiling-rounded 0.4 mover reservation.
Retained membership counts against its own pool; potential fills first,
then movers, and both pools share unused places. Qualified candidates retain
the caller's sourced ranking. Custody and session boundaries are supplied
receipts: this module never reads a clock, so 20:00 is the caller's new segment.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

SHARE = Decimal("0.4")


@dataclass(frozen=True)
class Candidate:
    """One caller-ranked candidate, qualified by the caller's current evidence."""

    symbol: str
    first_moved_ns: int | None = None
    qualified: bool = True


@dataclass(frozen=True)
class Allocation:
    """New arms and immutable total/mover membership for the next refresh."""

    armed: tuple[str, ...]
    slots: int
    reason: str
    chosen: frozenset[str]
    mover_armed: frozenset[str]

    def __bool__(self) -> bool:
        return bool(self.armed)


@dataclass(frozen=True)
class SlotPool:
    """The recorded shared pool with a 0.4 mover reservation."""

    share: Decimal = SHARE

    def slots(self, max_armed_symbols: int) -> int:
        if max_armed_symbols <= 0:
            return 0
        return int(
            (Decimal(max_armed_symbols) * self.share).to_integral_value(rounding=ROUND_CEILING)
        )

    def allocate(
        self,
        candidates: tuple[Candidate, ...],
        *,
        max_armed_symbols: int,
        potential: tuple[Candidate, ...],
        retained: frozenset[str] | None,
        mover_armed: frozenset[str] | None,
    ) -> Allocation:
        if retained is None or mover_armed is None:
            return Allocation((), 0, "custody_unknown", frozenset(), frozenset())
        if not isinstance(retained, frozenset) or not isinstance(mover_armed, frozenset):
            return Allocation((), 0, "custody_invalid", frozenset(), frozenset())
        slots = self.slots(max_armed_symbols)
        potential_quota = max_armed_symbols - slots
        retained_movers = retained & mover_armed
        chosen = set(retained)
        selected_movers = set(retained_movers)
        available = max(0, max_armed_symbols - len(chosen))
        armed: list[str] = []
        potential_candidates = [candidate for candidate in potential if candidate.qualified]
        eligible = [candidate for candidate in candidates if candidate.qualified]

        def choose(candidate: Candidate, *, mover: bool) -> None:
            nonlocal available
            chosen.add(candidate.symbol)
            armed.append(candidate.symbol)
            if mover:
                selected_movers.add(candidate.symbol)
            available -= 1

        potential_available = min(
            available, max(0, potential_quota - len(retained - retained_movers))
        )
        for candidate in potential_candidates:
            if candidate.symbol not in chosen and potential_available:
                choose(candidate, mover=False)
                potential_available -= 1

        mover_available = min(available, max(0, slots - len(retained_movers)))
        for candidate in eligible:
            if candidate.symbol not in chosen and mover_available:
                choose(candidate, mover=True)
                mover_available -= 1

        for candidate in potential_candidates:
            if available and candidate.symbol not in chosen:
                choose(candidate, mover=False)
        for candidate in eligible:
            if available and candidate.symbol not in chosen:
                choose(candidate, mover=True)

        return Allocation(
            tuple(armed),
            slots,
            "filled" if armed else "pass",
            frozenset(chosen),
            frozenset(selected_movers),
        )
