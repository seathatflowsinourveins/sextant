"""Published local Stocks in Play screen, NOT top-20 selection or an ORB trade.

upstream checked: Zarattini--Barbon--Aziz, DOI 10.2139/ssrn.4729284,
author PDF SHA-256 9423012e9f0199e3f6925c500725815c236d7ddbdd7500d50d10bac2be745e91,
pp. 9, 14--15, 19, sections 2.1, 3, 4 and 5. Published default: RTH 09:30--09:35 ET.
Reviewed row overrides identify adaptations, never newly calibrated market parameters.
Native bars: NautilusTrader@55c0e82053142bce3a5cba4de4221d3929c2d3bc,
docs/concepts/data/index.md:218-296 and python/tests/unit/backtest/test_bar_aggregation.py.
The coordinator owns calendar, dated universe, raw/action-qualified inputs,
prior-session identity, native daily ATR and the full candidate cross-section.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import MappingProxyType
from zoneinfo import ZoneInfo

from nautilus_trader.model import Bar, BarType, InstrumentId

from .common import Parameter, decimal, digest

SOURCE = (
    "doi:10.2139/ssrn.4729284; "
    "pdf-sha256:9423012e9f0199e3f6925c500725815c236d7ddbdd7500d50d10bac2be745e91"
)
PARAMETERS = tuple(
    Parameter(name, unit, value, f"{SOURCE}; {section}", "PUBLISHED", date(2026, 11, 6))
    for name, unit, value, section in (
        ("opening_window", "minutes", 5, "sections 2.1/3"),
        ("lookback", "completed exchange sessions", 14, "sections 2.1/3"),
        ("open_above", "USD", Decimal(5), "section 4"),
        ("adv_at_least", "shares per day", Decimal(1_000_000), "section 4"),
        ("atr_above", "USD", Decimal("0.50"), "section 4"),
        ("rvol_at_least", "ratio", Decimal(1), "section 4"),
        ("top_n", "stocks (external cross-section)", 20, "section 4"),
    )
)
DENOMINATOR = "mean_prior_opening_windows"
PARAMETERS += (
    Parameter(
        "denominator",
        "interpretation",
        DENOMINATOR,
        f"{SOURCE}; section 5 p.19 previous-days average; section 3 p.14 notation interpreted",
        "UNCALIBRATED",
        date(2026, 11, 6),
    ),
)
UNITS = {row.name: row.unit for row in PARAMETERS}
NS = 1_000_000_000


@dataclass(frozen=True)
class StocksInPlaySpec:
    """Immutable active mapping; sourced overrides identify adaptations, not admission."""

    rows: tuple[Parameter, ...]
    mapping: Mapping[str, Parameter] = field(init=False, repr=False)
    params_hash: str = field(init=False)

    def __post_init__(self) -> None:
        rows = tuple(self.rows)
        mapping = {row.name: row for row in rows}
        if len(rows) != len(UNITS) or set(mapping) != set(UNITS):
            raise ValueError("exact Stocks in Play parameter rows required")
        for name, row in mapping.items():
            if row.unit != UNITS[name] or row.value is None:
                raise ValueError("available parameter and matching unit required")
            if name in {"opening_window", "lookback", "top_n"}:
                if type(row.value) is not int or row.value <= 0:
                    raise ValueError("positive integer window, lookback and top_n required")
            elif name == "denominator":
                if row.value != DENOMINATOR:
                    raise ValueError("unsupported RVOL denominator interpretation")
            elif not isinstance(row.value, Decimal) or decimal(row.value) < 0:
                raise ValueError("nonnegative Decimal threshold required")
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "mapping", MappingProxyType(mapping))
        object.__setattr__(self, "params_hash", digest({k: r.identity for k, r in mapping.items()}))

    def integer(self, name: str) -> int:
        value = self.mapping[name].value
        assert type(value) is int  # Validated once; never coerce an unavailable/float value.
        return value

    def threshold(self, name: str) -> Decimal:
        value = self.mapping[name].value
        assert isinstance(value, Decimal)
        return value

    def composite_type(self, instrument_id: InstrumentId) -> BarType:
        # rc7 docs/concepts/data/index.md:218-296; source cadence is 1m, not a threshold.
        return BarType.from_str(
            f"{instrument_id}-{self.integer('opening_window')}-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL"
        )


@dataclass(frozen=True)
class OpeningWindow:
    """Factory output; direct construction is an explicit fixture/receipt seam only.

    Missing evidence remains missing through screen; known_at is row-11 availability,
    not a claim about an external venue's initialization or actual network receipt.
    """

    instrument_id: InstrumentId
    session: date
    open: Decimal
    close: Decimal
    volume: Decimal
    known_at_ns: int
    coverage_complete: bool | None = None
    params_hash: str | None = None
    composite_type: BarType | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId) or type(self.session) is not date:
            raise ValueError("native instrument and explicit session date required")
        if decimal(self.open) <= 0 or decimal(self.close) <= 0 or decimal(self.volume) < 0:
            raise ValueError("invalid opening window")
        if type(self.known_at_ns) is not int or self.known_at_ns < 0:
            raise ValueError("nonnegative opening availability required")
        if self.composite_type is not None:
            opened = datetime.combine(self.session, time(9, 30), ZoneInfo("America/New_York"))
            closed = opened + timedelta(minutes=self.composite_type.spec.step)
            if self.known_at_ns < int(closed.timestamp()) * NS:
                raise ValueError("opening window cannot be known before configured completion")


def opening_window(
    bars: tuple[Bar, ...],
    *,
    session_open_ns: int,
    as_of_ns: int,
    coverage_complete: bool | None,
    composite_type: BarType,
    spec: StocksInPlaySpec | None = None,
) -> OpeningWindow | None:
    """Consume one native composite output, close-stamped per row 11.

    The coordinator subscribes to the explicit composite_type. Native delivery uses
    its standard internal type (rc7 python/tests/unit/backtest/test_bar_aggregation.py).
    No local bar aggregation, extrapolation or zero fill. Independent complete-source
    coverage is required, retained and rechecked by screen; native output alone is
    not completion evidence. ts_init is row-11 known-at; it may lag the close.
    """
    active = spec if spec is not None else StocksInPlaySpec(PARAMETERS)
    if any(type(t) is not int or t < 0 for t in (session_open_ns, as_of_ns)):
        raise ValueError("nonnegative nanosecond clocks required")
    opened = datetime.fromtimestamp(session_open_ns // NS, ZoneInfo("America/New_York"))
    if (opened.hour, opened.minute, opened.second) != (9, 30, 0) or session_open_ns % NS:
        raise ValueError("published screen requires the 09:30 ET RTH open")
    if coverage_complete is not True or len(bars) != 1:
        return None
    first = bars[0]
    expected = active.composite_type(first.bar_type.instrument_id)
    if composite_type != expected or first.bar_type not in (expected, expected.standard()):
        raise ValueError("configured native composite MINUTE LAST bar required")
    interval = active.integer("opening_window") * 60 * NS
    if first.ts_event != session_open_ns + interval:
        return None
    if first.ts_init < first.ts_event:
        raise ValueError("row-11 bar availability precedes completion")
    if first.ts_init > as_of_ns:
        return None
    return OpeningWindow(
        first.bar_type.instrument_id,
        opened.date(),
        first.open.as_decimal(),
        first.close.as_decimal(),
        first.volume.as_decimal(),
        first.ts_init,
        coverage_complete=True,
        params_hash=active.params_hash,
        composite_type=composite_type,
    )


@dataclass(frozen=True)
class DailyFacts:
    """Caller supplies ADV and native ATR for the SAME configured prior sessions.

    Do not rebuild AverageTrueRange here. Native smoothing/initialization and any
    extra warm-up history must be resolved under #129 and bound at admission;
    citing Wilder does not by itself resolve the paper's precise implementation.
    Unknown or uninitialized ATR remains None, not zero.
    """

    instrument_id: InstrumentId
    sessions: tuple[date, ...]
    adv: Decimal | None
    atr: Decimal | None
    known_at_ns: int

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise ValueError("native instrument required")
        if type(self.known_at_ns) is not int or self.known_at_ns < 0:
            raise ValueError("nonnegative daily-facts availability required")
        if any(type(session) is not date for session in self.sessions):
            raise ValueError("explicit daily-facts session dates required")
        if self.sessions:
            closed = datetime.combine(
                max(self.sessions) + timedelta(days=1), time.min, ZoneInfo("America/New_York")
            )
            if self.known_at_ns < int(closed.timestamp()) * NS:
                raise ValueError("daily facts precede completed prior sessions (row 11)")
        for value in (self.adv, self.atr):
            if value is not None and decimal(value) < 0:
                raise ValueError("nonnegative daily facts required")


@dataclass(frozen=True)
class Screen:
    rvol: Decimal | None
    passes_local_filters: bool | None
    reason: str
    params_hash: str
    # No top-20 membership, breakout direction, entry, stop, risk or leverage.


def screen(
    current: OpeningWindow | None,
    prior: tuple[OpeningWindow, ...],
    *,
    expected_sessions: tuple[date, ...],
    facts: DailyFacts | None,
    as_of_ns: int,
    spec: StocksInPlaySpec | None = None,
) -> Screen:
    active = spec if spec is not None else StocksInPlaySpec(PARAMETERS)

    def result(rvol: Decimal | None, passes: bool | None, reason: str) -> Screen:
        return Screen(rvol, passes, reason, active.params_hash)

    if current is None:
        return result(None, None, "opening_window_unavailable")
    if type(as_of_ns) is not int or as_of_ns < current.known_at_ns:
        return result(None, None, "not_yet_available")
    if (
        len(expected_sessions) != active.integer("lookback")
        or tuple(sorted(set(expected_sessions))) != expected_sessions
        or expected_sessions[-1] >= current.session
        or tuple(w.session for w in prior) != expected_sessions
    ):
        return result(None, None, "prior_sessions_unavailable")
    for window in (current, *prior):
        if window.coverage_complete is not True:
            return result(None, None, "opening_coverage_unavailable")
        if window.composite_type is None:
            return result(None, None, "opening_source_unavailable")
        if window.params_hash != active.params_hash:
            raise ValueError("opening window parameter identity mismatch")
        if window.instrument_id != current.instrument_id:
            raise ValueError("mixed instruments")
        if window.composite_type != active.composite_type(window.instrument_id):
            raise ValueError("opening window composite source mismatch")
        if window.known_at_ns > as_of_ns:
            return result(None, None, "not_yet_available")
        if decimal(window.volume) < 0 or decimal(window.open) <= 0 or decimal(window.close) <= 0:
            raise ValueError("invalid opening window")
    # The validated denominator row selects the mean (§5 p.19); §3 p.14 has ambiguous indices.
    baseline = sum((w.volume for w in prior), Decimal(0)) / active.integer("lookback")
    if baseline == 0:
        return result(None, None, "zero_opening_volume_baseline")
    rvol = current.volume / baseline
    if facts is None or facts.adv is None or facts.atr is None:
        return result(rvol, None, "daily_facts_unavailable")
    if facts.instrument_id != current.instrument_id or facts.sessions != expected_sessions:
        return result(rvol, None, "daily_facts_identity_mismatch")
    if facts.known_at_ns > as_of_ns:
        return result(rvol, None, "daily_facts_not_yet_available")
    if decimal(facts.adv) < 0 or decimal(facts.atr) < 0:
        raise ValueError("invalid daily facts")
    passed = (
        current.open > active.threshold("open_above")
        and facts.adv >= active.threshold("adv_at_least")
        and facts.atr > active.threshold("atr_above")
        and rvol >= active.threshold("rvol_at_least")
    )
    return result(rvol, passed, "local_filters_only_top20_external")
