"""Bounded immutable tick history, shared only by the pure M2 transitions."""

from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal
from typing import Self

from nautilus_trader.model import TradeTick

NS = 1_000_000_000

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class Bucket:
    second: int
    ticks: tuple[TradeTick, ...]
    dollar_volume: Decimal


@dataclass(frozen=True, slots=True)
class TradeWindow:
    buckets: tuple[Bucket, ...] = ()
    anchor: TradeTick | None = None

    def append(self, tick: TradeTick, keep_s: int) -> Self:
        buckets = self.buckets
        second = tick.ts_event // NS
        anchor = self.anchor
        if buckets and tick.ts_event < buckets[-1].ticks[-1].ts_event:
            raise ValueError("out-of-order event; canonicalize equal-time inputs through M1 first")
        value = tick.price.as_decimal() * tick.size.as_decimal()
        if buckets and buckets[-1].second == second:
            last = buckets[-1]
            buckets = (
                *buckets[:-1],
                Bucket(second, (*last.ticks, tick), last.dollar_volume + value),
            )
        else:
            buckets = (*buckets, Bucket(second, (tick,), value))
        i = 0
        while i < len(buckets) - 1 and buckets[i].second < second - keep_s:
            anchor = buckets[i].ticks[-1]
            i += 1
        return type(self)(buckets[i:], anchor)

    def price_at(self, ts: int) -> TradeTick | None:
        i = bisect_right(self.buckets, ts // NS, key=lambda b: b.second) - 1
        while i >= 0:
            ticks = self.buckets[i].ticks
            j = bisect_right(ticks, ts, key=lambda t: t.ts_event) - 1
            if j >= 0:
                return ticks[j]
            i -= 1
        return self.anchor if self.anchor and self.anchor.ts_event <= ts else None

    def before(self, ts: int) -> TradeTick | None:
        return self.price_at(ts - 1)

    def last(self, n: int) -> tuple[TradeTick, ...]:
        result: tuple[TradeTick, ...] = ()
        for bucket in reversed(self.buckets):
            result = bucket.ticks[-n:] + result
            if len(result) >= n:
                break
        return result[-n:]

    def first_moved(self, start: int, price: Decimal, move: Decimal) -> TradeTick | None:
        for bucket in self.buckets:
            if (bucket.second + 1) * NS <= start:
                continue
            for tick in bucket.ticks:
                if tick.ts_event > start and tick.price.as_decimal() >= price * (1 + move):
                    return tick
        return None

    def totals(self, start: int, end: int) -> tuple[Decimal, int]:
        """Half-open at start: (start, end], matching all rolling windows."""
        dv, count = ZERO, 0
        for bucket in self.buckets:
            if bucket.second * NS > end or (bucket.second + 1) * NS <= start:
                continue
            if bucket.ticks[0].ts_event > start and bucket.ticks[-1].ts_event <= end:
                dv += bucket.dollar_volume
                count += len(bucket.ticks)
            else:
                for tick in bucket.ticks:
                    if start < tick.ts_event <= end:
                        dv += tick.price.as_decimal() * tick.size.as_decimal()
                        count += 1
        return dv, count
