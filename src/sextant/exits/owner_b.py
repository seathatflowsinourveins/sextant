"""B's custody/adoption and cancel-first intents, never orders or a reconciliation substitute.

Policy: ADR-0005 X2, ADR-0007 and ADR-0025; option B/recovery is the approved
`none exists:` mechanism in northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa,
docs/adr/0015-owner-entry-paper-exit-manager.md:94-124. Decimal intent shape follows that
pin's strategies/exit_manager/rules.py. A caller supplies authoritative custody facts;
these predicates do NOT verify Nautilus live-node claiming (#49, owed to Sandbox).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sextant.exits.policy import Row

ZERO = Decimal(0)
ADR = "docs/adr/0007-custody-and-order-writing.md"
REGISTRY = (
    Row("native_trail_fraction", "fraction; capped at 0.025", None, "ADR-0025 B scope"),
    Row("limit_chase_window_s", "seconds", None, "ADR-0025 option B bounded chase"),
    Row("claim_max_latency_s", "seconds", None, f"{ADR} C1-C2"),
)


def _nonnegative(*values: Decimal) -> None:
    if any(not isinstance(v, Decimal) or not v.is_finite() or v < 0 for v in values):
        raise ValueError("finite nonnegative Decimal values required")


@dataclass(frozen=True)
class BParams:
    """Required UNCALIBRATED values. Witness fixture numbers grant no trading authority."""

    native_trail_fraction: Decimal
    limit_chase_window_s: Decimal
    claim_max_latency_s: Decimal

    def __post_init__(self) -> None:
        _nonnegative(
            self.native_trail_fraction, self.limit_chase_window_s, self.claim_max_latency_s
        )
        if not ZERO < self.native_trail_fraction <= Decimal("0.025"):
            raise ValueError("B's native trail must be positive and at most 0.025 (ADR-0025)")


@dataclass(frozen=True)
class Adoption:
    entry: Decimal
    high: Decimal
    trigger: Decimal
    quantity: Decimal
    reason: str


def adopt(
    *,
    entry: Decimal,
    mark: Decimal,
    quantity: Decimal,
    owner_reserved: Decimal,
    buffer: Decimal,
    filled_ns: int,
    now_ns: int,
    reconciled: bool,
    claim_max_latency_s: Decimal | None,
) -> Adoption:
    """Admission on supplied facts, with original entry basis and H at the adoption mark."""
    _nonnegative(entry, mark, quantity, owner_reserved, buffer)
    if entry == 0 or mark == 0 or buffer == 0 or buffer >= entry:
        raise ValueError("positive entry, mark and buffer below entry required")
    reason = "adopted-below-trigger" if mark <= entry - buffer else "adopted"
    available = max(ZERO, quantity - owner_reserved)
    if not reconciled:
        reason, available = "custody_unresolved", ZERO
    elif claim_max_latency_s is None:
        reason, available = "claim_latency_unavailable", ZERO
    else:
        _nonnegative(claim_max_latency_s)
        if filled_ns < 0 or now_ns < filled_ns:
            reason, available = "invalid_claim_clock", ZERO
        elif now_ns - filled_ns > int(claim_max_latency_s * 1_000_000_000):
            reason, available = "claim_too_late", ZERO
        elif owner_reserved > quantity:
            reason, available = "quantity_mismatch", ZERO
        elif any(v != v.to_integral_value() for v in (quantity, owner_reserved)):
            reason, available = "fractional_custody_unverified", ZERO
        elif available == 0:
            reason = "owner_reserved_unprotected"
    return Adoption(entry, mark, entry - buffer, available, reason)


@dataclass(frozen=True)
class OwnedExit:
    """Only positively identified house lineage belongs here, including in-flight submits."""

    order_id: str
    kind: Literal["trail", "limit"]
    leaves: Decimal
    pending: bool = False
    pending_cancel: bool = False


@dataclass(frozen=True)
class Intent:
    action: Literal["wait", "page", "pause_and_page", "cancel", "trail", "limit"]
    quantity: Decimal = ZERO
    order_id: str | None = None
    reason: str = ""


def decide(
    position: Decimal,
    owner_reserved: Decimal,
    owned: tuple[OwnedExit, ...],
    *,
    mode: Literal["protect", "breach", "recover"],
    owner_add: bool = False,
) -> Intent:
    """One fresh, same-account snapshot after every terminal event; ACK never means flat.

    A cancellation or uncertain submission retains its entire possible-fill exposure. Recovery
    cancels a resting LIMIT, waits terminal, rereads the residual, then arms just that quantity.
    No intent can name an owner order: targets come only from the supplied house lineage.
    """
    _nonnegative(position, owner_reserved, *(order.leaves for order in owned))
    if mode not in {"protect", "breach", "recover"}:
        raise ValueError("unknown B mode")
    if owner_add:
        return Intent("pause_and_page", reason="owner_add")
    if owner_reserved > position or len(owned) > 1:
        return Intent("pause_and_page", reason="quantity_mismatch")
    quantity = position - owner_reserved
    if any(v != v.to_integral_value() for v in (position, owner_reserved)):
        return Intent("pause_and_page", reason="fractional_custody_unverified")
    if owned:
        order = owned[0]
        if order.pending or order.pending_cancel:
            return Intent("wait", reason="possible_fill_exposure")
        handover = mode == "breach" and order.kind == "trail"
        recovery = mode == "recover" and order.kind == "limit"
        if handover or recovery or order.leaves != quantity:
            return Intent("cancel", order_id=order.order_id, reason="terminal_before_handover")
        return Intent("wait", reason="already_reserved")
    if quantity == 0:
        return Intent("page" if position else "wait", reason="owner_reserved_unprotected")
    return Intent("limit" if mode == "breach" else "trail", quantity)
