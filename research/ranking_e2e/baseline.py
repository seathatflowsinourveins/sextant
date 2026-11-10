"""Prior-session cumulative dollar-volume curves without numpy or look-ahead.

K2's baseline is the median, at the same elapsed offset, of each prior
session's own cumulative dollar-volume curve.  Arm (b) swaps only the
statistic to the mean of the identical session set.  Missing minutes are
carried forward within a recorded session (a symbol that did not trade there
is a zero), but a prior session that never recorded the symbol is unknown and
does not enter the sample; no future session enters the curve.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import median

from .bars import Bar

NS = 1_000_000_000
ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class CurveValue:
    dollar_volume: Decimal
    sessions: int


class CurveBaseline:
    """Duck-types ``sextant.ranking.baseline.BaselineTable.cumulative``."""

    feed: str
    known_at: int
    provenance: str
    latest_session: date | None
    minute_s: int

    def __init__(
        self,
        curves: Mapping[str, Sequence[Sequence[Decimal | int]]],
        *,
        feed: str,
        known_at: int,
        provenance: str,
        latest_session: date | None = None,
        minute_s: int = 60,
    ) -> None:
        if feed not in {"sip", "boats"}:
            raise ValueError("baseline feed must be sip or boats")
        if minute_s <= 0:
            raise ValueError("positive minute size required")
        frozen: dict[str, tuple[tuple[Decimal, ...], ...]] = {}
        for symbol, sessions in curves.items():
            if not sessions:
                continue
            length = len(sessions[0])
            if length == 0 or any(len(curve) != length for curve in sessions):
                raise ValueError("all baseline curves for a symbol must share a length")
            frozen[symbol] = tuple(tuple(Decimal(value) for value in curve) for curve in sessions)
        self._curves = frozen
        self.feed = feed
        self.known_at = known_at
        self.provenance = provenance
        self.latest_session = latest_session
        self.minute_s = minute_s

    def _values(self, symbol: str, offset_s: Decimal) -> list[Decimal] | None:
        curves = self._curves.get(symbol)
        if not curves:
            return None
        x = offset_s / Decimal(self.minute_s)
        if x < 0 or x > len(curves[0]) - 1:
            return None
        lower = int(x)
        if x == lower:
            return [curve[lower] for curve in curves]
        fraction = x - lower
        return [
            curve[lower] + fraction * (curve[lower + 1] - curve[lower])
            for curve in curves
            if lower + 1 < len(curve)
        ]

    def _aggregate(self, values: Sequence[Decimal]) -> CurveValue:  # pragma: no cover - abstract
        raise NotImplementedError

    def cumulative(self, symbol: str, segment: str, offset_s: int | Decimal) -> CurveValue | None:
        del segment  # one baseline object is built per segment
        values = self._values(symbol, Decimal(offset_s))
        if not values:
            return None
        return self._aggregate(values)


class MedianCurveBaseline(CurveBaseline):
    def _aggregate(self, values: Sequence[Decimal]) -> CurveValue:
        return CurveValue(Decimal(median(values)), len(values))


class MeanCurveBaseline(CurveBaseline):
    def _aggregate(self, values: Sequence[Decimal]) -> CurveValue:
        return CurveValue(sum(values, ZERO) / len(values), len(values))


def cumulative_curves(
    day_bars: Mapping[str, Sequence[Bar]],
    symbols: Sequence[str],
    start_ns: int,
    minutes: int,
) -> dict[str, tuple[Decimal, ...]]:
    """One cumulative curve per symbol: ``curve[m]`` is through minute ``m``.

    Bars are minute starts in ``[start_ns, start_ns + minutes*60s)``.  A minute
    with no bar repeats the previous cumulative value.  The bar at offset ``m``
    contributes to ``curve[m+1]``.
    """
    out: dict[str, tuple[Decimal, ...]] = {}
    for symbol in symbols:
        rows = day_bars.get(symbol, ())
        curve = [ZERO] * (minutes + 1)
        dv = ZERO
        pointer = 0
        for minute in range(minutes):
            boundary = start_ns + minute * 60 * NS
            while pointer < len(rows) and rows[pointer].ts_ns < boundary + 60 * NS:
                bar = rows[pointer]
                if bar.ts_ns >= boundary:
                    dv += bar.close * bar.volume
                pointer += 1
            curve[minute + 1] = dv
        out[symbol] = tuple(curve)
    return out
