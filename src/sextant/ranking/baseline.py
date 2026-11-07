"""Pure time-matched historical dollar-volume and trade-count curves.

Minute bars approximate within-minute flow by linear interpolation, explicitly;
they do not contain seconds. No full-session total is used as a time-matched
median. Window queries take a window within EACH historical session, then its
median (a difference of medians is generally not the median of differences).
"""

import hashlib
import json
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from statistics import median
from types import MappingProxyType

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class BaselineSample:
    symbol: str
    segment: str
    session: str
    offset_s: int
    dollar_volume: Decimal
    trade_count: Decimal

    def __post_init__(self) -> None:
        if self.offset_s < 0:
            raise ValueError("negative baseline offset")
        for value in (self.dollar_volume, self.trade_count):
            if not isinstance(value, Decimal):
                raise TypeError("baseline values must be Decimal")
            if not value.is_finite() or value < 0:
                raise ValueError("invalid baseline value")


@dataclass(frozen=True, slots=True)
class BaselineValue:
    dollar_volume: Decimal
    trade_count: Decimal
    sessions: int
    known_at: int
    provenance: str


@dataclass(frozen=True, slots=True)
class BaselineTable:
    samples: tuple[BaselineSample, ...]
    provenance: str
    known_at: int
    feed: str
    latest_session: date | None = field(init=False)
    _identity: str = field(init=False, repr=False)
    _index: Mapping[tuple[str, str], tuple[tuple[BaselineSample, ...], ...]] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not self.provenance or self.feed not in {"sip", "boats"}:
            raise ValueError("baseline source and feed required")
        ordered = tuple(
            sorted(self.samples, key=lambda s: (s.symbol, s.segment, s.session, s.offset_s))
        )
        previous: BaselineSample | None = None
        for sample in ordered:
            if previous and (sample.symbol, sample.segment, sample.session) == (
                previous.symbol,
                previous.segment,
                previous.session,
            ):
                if sample.offset_s == previous.offset_s:
                    raise ValueError("duplicate baseline offset")
                if (
                    sample.dollar_volume < previous.dollar_volume
                    or sample.trade_count < previous.trade_count
                ):
                    raise ValueError("cumulative baseline decreases")
            previous = sample
        object.__setattr__(self, "samples", ordered)
        object.__setattr__(
            self,
            "latest_session",
            max(
                (date.fromisoformat(sample.session) for sample in ordered),
                default=None,
            ),
        )
        payload = json.dumps(
            {
                "samples": [asdict(s) for s in ordered],
                "provenance": self.provenance,
                "known_at": self.known_at,
                "feed": self.feed,
            },
            default=str,
            sort_keys=True,
            separators=(",", ":"),
        )
        object.__setattr__(self, "_identity", hashlib.sha256(payload.encode()).hexdigest())
        grouped: dict[tuple[str, str], dict[str, list[BaselineSample]]] = defaultdict(dict)
        for sample in ordered:
            grouped[sample.symbol, sample.segment].setdefault(sample.session, []).append(sample)
        object.__setattr__(
            self,
            "_index",
            MappingProxyType(
                {
                    key: tuple(tuple(curve) for curve in sessions.values())
                    for key, sessions in grouped.items()
                }
            ),
        )

    def _curves(self, symbol: str, segment: str) -> Iterable[tuple[BaselineSample, ...]]:
        return self._index.get((symbol, segment), ())

    @property
    def identity(self) -> str:
        return self._identity

    @staticmethod
    def _at(curve: tuple[BaselineSample, ...], offset: Decimal) -> tuple[Decimal, Decimal] | None:
        if offset < curve[0].offset_s or offset > curve[-1].offset_s:
            return None  # missing coverage is not a zero, or an extrapolation
        i = bisect_left(curve, offset, key=lambda sample: sample.offset_s)
        upper = curve[i]
        if upper.offset_s == offset:
            return upper.dollar_volume, upper.trade_count
        lower = curve[i - 1]
        fraction = (offset - lower.offset_s) / (upper.offset_s - lower.offset_s)
        return (
            lower.dollar_volume + fraction * (upper.dollar_volume - lower.dollar_volume),
            lower.trade_count + fraction * (upper.trade_count - lower.trade_count),
        )

    def cumulative(
        self, symbol: str, segment: str, offset_s: int | Decimal
    ) -> BaselineValue | None:
        values = [
            value
            for curve in self._curves(symbol, segment)
            if (value := self._at(curve, Decimal(offset_s)))
        ]
        return self._median(values)

    def window(
        self, symbol: str, segment: str, offset_s: int | Decimal, window_s: int
    ) -> BaselineValue | None:
        end = Decimal(offset_s)
        start = end - window_s
        values = []
        for curve in self._curves(symbol, segment):
            a, b = self._at(curve, start), self._at(curve, end)
            if a is not None and b is not None:
                values.append((b[0] - a[0], b[1] - a[1]))
        return self._median(values)

    def _median(self, values: list[tuple[Decimal, Decimal]]) -> BaselineValue | None:
        if not values:
            return None
        return BaselineValue(
            Decimal(median(value[0] for value in values)),
            Decimal(median(value[1] for value in values)),
            len(values),
            self.known_at,
            self.provenance,
        )
