"""The arms the frozen K3 section defines, plus explicit refusals.

Frozen: (a) ADR-0024's premarket gap rule exactly as recorded; (b) mean
instead of median over the same prior sessions; (c) ADR-0024 keep-alive;
(d) Page one-sided CUSUM.  (a) as recorded needs candidate calibrations the
sealed inputs cannot supply, so it is NOT_RUN and only its fixed-mode gap-only
sub-arm runs, under that name.  (d) has no reviewed parameter rows (all five
adapter rows are UNAVAILABLE), so its status is NOT_RUN; the river constructor
defaults are never market parameters.  The parent brief's OFI and EDGAR arms
are not in the frozen K3 section; they are recorded as NOT_IN_FROZEN_PROTOCOL,
not invented here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from .bars import Bar

GAP_THRESHOLD = Decimal("0.01")
GAP_SUB_ARM = "gap_fixed_open_sub_arm"


@dataclass(frozen=True, slots=True)
class Flag:
    symbol: str
    arm: str
    ts_ns: int
    price: Decimal
    reason: str
    gap: Decimal | None = None


class GapArm:
    """ADR-0024 fixed-range mode's gap test only: first open of 04:00-04:05 >= +1%.

    This is the gap-only sub-arm of arm (a), not arm (a): the recorded
    candidate calibrations (ADV20, the $5m candidate-ADV floor, unknown-ADV
    exclusions and the $1m prior-post turnover) are not applied, because the
    harness takes no receipt for them (``gap_rule_status``).  The arm is a
    single session-scoped instance.  A bar outside the fixed window never flags
    and never marks the symbol seen, so a later 07:30 or RTH observation cannot
    substitute for the opening print.
    """

    name = GAP_SUB_ARM

    def __init__(self, *, window_start_ns: int, window_end_ns: int) -> None:
        if window_end_ns <= window_start_ns:
            raise ValueError("gap window must be positive")
        self._window_start_ns = window_start_ns
        self._window_end_ns = window_end_ns
        self._seen: set[str] = set()

    def observe(self, bar: Bar, prior_close: Decimal | None) -> Flag | None:
        if not (self._window_start_ns <= bar.ts_ns < self._window_end_ns):
            return None
        symbol = bar.symbol
        if symbol in self._seen:
            return None
        self._seen.add(symbol)
        if prior_close is None or prior_close <= 0:
            return None
        gap = bar.open / prior_close - 1
        if gap < GAP_THRESHOLD:
            return None
        return Flag(symbol, self.name, bar.ts_ns, bar.open, "first_open_gap", gap)


def gap_rule_status() -> dict[str, object]:
    """Frozen arm (a) exactly as ADR-0024 records it: NOT_RUN, with what is missing.

    ADR-0024 (Premarket): the fixed range admits a first-open gap of at least
    1%; trigger mode seals the first complete aligned bullish five-minute block
    meeting explicit gap and ``sum(close x volume)`` thresholds; the
    calibration recommends ``max(50000, 0.001 x ADV20)`` and $1m prior-post
    turnover, retaining $5m candidate ADV and unknown-ADV exclusions; below-5%
    triggers remain an UNCALIBRATED candidate grid.  K3.8: arm (a) takes these
    values exactly as recorded, and any other value is a different arm.
    """
    return {
        "status": "NOT_RUN",
        "arm": "K3.5 (a): ADR-0024 premarket gap rule exactly as recorded",
        "reason": (
            "the recorded candidate calibrations need quantities the harness takes no "
            "receipt for, so the full rule cannot run as recorded; its fixed-mode gap test "
            f"runs alone as {GAP_SUB_ARM}, a different arm under K3.8"
        ),
        "missing": {
            "adv20": (
                "ADV20 per candidate (20 completed prior sessions of daily dollar volume): "
                "needed for the $5m candidate-ADV floor, the unknown-ADV exclusion and trigger "
                "mode's max(50000, 0.001 x ADV20) floor; no ADV20 receipt is an input"
            ),
            "prior_post_turnover": (
                "the prior session's post-market turnover from the prior XNYS close + 1 "
                "minute (flat-at-prior-close bars removed before close + 15 minutes), "
                "needed for the $1m prior-post filter; no post-market receipt is an input"
            ),
        },
        "fixed_mode": {
            "status": "NOT_RUN",
            "reason": f"candidate exclusions missing; the gap test alone runs as {GAP_SUB_ARM}",
        },
        "trigger_mode": {
            "status": "NOT_RUN",
            "reason": (
                "its sum(close x volume) floor max(50000, 0.001 x ADV20) needs ADV20, and "
                "below-5% gap triggers are an UNCALIBRATED candidate grid (ADR-0024) with no "
                "sealed registry row"
            ),
        },
    }


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


class RankedRow(Protocol):
    """The fields keep-alive reads from a ranked K2 row (``engine.MoverRow``)."""

    @property
    def symbol(self) -> str: ...

    @property
    def rank(self) -> int | None: ...

    @property
    def score(self) -> Decimal | None: ...

    @property
    def trades_accel(self) -> Decimal | None: ...


class KeepAlive:
    """ADR-0024 keep-alive on membership, applied to the K2 ranking state.

    ADR-0024 (Mover arming): keep-alive preserves eligible membership through
    incomplete session inputs; current entry qualification remains required,
    quotas win, and 20:00 resets.  On the K2 state an incomplete input is a
    member whose latest row is not computable (score or ``trades_accel``
    unknown, with the engine's unknown reasons), so the published generation
    does not rank it.  Such a row cannot decide qualification, so this class
    carries each symbol's last computable qualification itself (the round-2
    review's Fix line): an uncomputable member is retained only if its last
    computable row was entry-qualified (``engine.qualifies``).  A member with a
    computable row is judged afresh every generation: inside the top N and
    qualified now, or dropped.  Quotas win: fresh admits fill first, then the
    retained take the free slots in K2's own strict total order on their last
    computable rows (descending score, then descending ``trades_accel``, then
    symbol; ``engine.rank_movers``).  ``reset`` is the 20:00 ET boundary; the
    replay ends at 11:35, so it is not reached in this session.
    """

    def __init__(self, top_n: int = 100) -> None:
        if top_n <= 0:
            raise ValueError("top_n must be positive")
        self.top_n = top_n
        self._members: set[str] = set()
        self._last: dict[str, tuple[bool, tuple[Decimal, Decimal, str]]] = {}
        self.retained: frozenset[str] = frozenset()

    def update[R: RankedRow](
        self, ranked: Iterable[R], *, qualifies: Callable[[R], bool]
    ) -> set[str]:
        """Advance one published generation; ``ranked`` is its computable rows."""
        computable: set[str] = set()
        fresh: set[str] = set()
        for row in ranked:
            if row.rank is None or row.score is None or row.trades_accel is None:
                raise ValueError("keep-alive reads only ranked, computable rows")
            qualified = qualifies(row)
            computable.add(row.symbol)
            self._last[row.symbol] = (qualified, (-row.score, -row.trades_accel, row.symbol))
            if qualified and row.rank <= self.top_n:
                fresh.add(row.symbol)
        waiting: list[tuple[tuple[Decimal, Decimal, str], str]] = []
        for symbol in self._members - computable:
            last = self._last.get(symbol)
            if last is not None and last[0]:
                waiting.append((last[1], symbol))
        slots = max(0, self.top_n - len(fresh))
        self.retained = frozenset(symbol for _, symbol in sorted(waiting)[:slots])
        self._members = fresh | self.retained
        return set(self._members)

    def reset(self) -> None:
        """The 20:00 ET reset against the new close (ADR-0024)."""
        self._members.clear()
        self._last.clear()
        self.retained = frozenset()
