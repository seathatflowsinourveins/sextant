"""The arms the frozen K3 section defines, plus explicit refusals.

Frozen: (a) ADR-0024's first-open gap >= 1%; (b) mean instead of median over
the same prior sessions; (c) ADR-0024 keep-alive; (d) Page one-sided CUSUM.
(d) has no reviewed parameter rows (all five adapter rows are UNAVAILABLE), so
its status is NOT_RUN; the river constructor defaults are never market
parameters.  The parent brief's OFI and EDGAR arms are not in the frozen K3
section; they are recorded as NOT_IN_FROZEN_PROTOCOL, not invented here.
"""

from __future__ import annotations

from collections.abc import Mapping, Set
from dataclasses import dataclass
from decimal import Decimal

GAP_THRESHOLD = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Flag:
    symbol: str
    arm: str
    ts_ns: int
    price: Decimal
    reason: str
    gap: Decimal | None = None


class GapArm:
    """ADR-0024 fixed-range mode: first open of the 04:00-04:05 window >= +1%."""

    name = "gap"

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def observe(self, bar: object, prior_close: Decimal | None) -> Flag | None:
        symbol = bar.symbol
        if symbol in self._seen:
            return None
        self._seen.add(symbol)
        if prior_close is None or prior_close <= 0:
            return None
        gap = bar.open / prior_close - 1
        if gap < GAP_THRESHOLD:
            return None
        return Flag(symbol, self.name, bar.close_ns, bar.open, "first_open_gap", gap)


class PageCusum:
    """Page (1954) one-sided CUSUM: ``S_t = max(0, S_{t-1} + x_t - k)``."""

    def __init__(self, *, k: Decimal, h: Decimal) -> None:
        if k <= 0 or h <= 0:
            raise ValueError("Page CUSUM k and h must be positive")
        self.k, self.h = k, h
        self.s = Decimal(0)
        self.triggered = False

    def update(self, x: Decimal) -> bool:
        """Feed the dimensionless ratio; True only on the first breach."""
        if self.triggered:
            self.s = max(Decimal(0), self.s + x - self.k)
            return False
        self.s = max(Decimal(0), self.s + x - self.k)
        if self.s > self.h:
            self.triggered = True
            return True
        return False


@dataclass(frozen=True, slots=True)
class PageArmStatus:
    status: str
    reason: str
    parameters: Mapping[str, str]


def page_arm_status() -> PageArmStatus:
    return PageArmStatus(
        "NOT_RUN",
        "the frozen K3 section records all five PageHinkleyArm rows as UNAVAILABLE; "
        "river constructor defaults and fixture values are refused",
        {
            "min_instances": "UNAVAILABLE",
            "delta": "UNAVAILABLE",
            "threshold": "UNAVAILABLE",
            "alpha": "UNAVAILABLE",
            "mode": "UNAVAILABLE",
        },
    )


class KeepAlive:
    """ADR-0024 keep-alive on membership: retain a member through an
    incomplete generation (no computable row), drop it when a computable
    row's rank falls outside the top N, and admit any name currently in
    the top N.  Membership is the K2 top-N state; the four entry gates
    are entry qualification and are not applied to membership.
    """

    def __init__(self, top_n: int = 100) -> None:
        if top_n <= 0:
            raise ValueError("top_n must be positive")
        self.top_n = top_n
        self._members: set[str] = set()

    def update(self, *, rank: Mapping[str, int], qualified: Set[str]) -> set[str]:
        # `qualified` is accepted for call-site compatibility with the
        # entry path, but ADR-0024 applies it at entry, not membership.
        computable = set(rank)
        fresh = {symbol for symbol, place in rank.items() if place <= self.top_n}
        retained = {symbol for symbol in self._members if symbol not in computable}
        self._members = fresh | retained
        return set(self._members)
