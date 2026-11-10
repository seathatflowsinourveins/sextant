"""Keep the newest complete display unit fresh for the current display segment.

This is a REST-only, display-only producer: it replays the current PRE, RTH or
POST session's completed one-minute SIP bars through the bar-fidelity host, then
projects the ranked J5 document with the bridge into a research directory that
``python -m sextant.tradingview --loop`` consumes.  It opens no stream, calls no
TradingView endpoint, and places no order.

Source: the merged ``host.py``, ``bridge.py``, ``producer.py`` and
``baseline.py`` (alpaca-py 0.44.0 REST bars, ADR-0003, northstar-lanes
registry). The producer supplies the operating clock and the slot-3 lease; it
adds no ranking, projection or clock rule of its own.
"""

from __future__ import annotations

import hashlib
import json
import os
from array import array
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo

from alpaca.common.enums import Sort
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.models import BarSet
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from exchange_calendars import get_calendar
from nautilus_trader.common import MessageBus
from nautilus_trader.model import TraderId

from sextant.data.alpaca_history import decimal_value
from sextant.execution.state import write_atomic
from sextant.ranking.baseline import BaselineTable, segment_start
from sextant.ranking.engine import ReferencePrices, Segment
from sextant.ranking.publisher import AssetState, RankingPublisher
from sextant.ranking.registry import ROWS, Registry, RegistryRow
from sextant.tradingview.bars import (
    MAX_BATCH,
    AlpacaBarSource,
    Bar,
    BarPoll,
    PacedStockBars,
    build_universe,
)
from sextant.tradingview.baseline import SCALE, FiveSessionBaseline, _session_start
from sextant.tradingview.bridge import DisplayBounds, project_display_unit
from sextant.tradingview.cadence import Cadence
from sextant.tradingview.host import BarFidelityHost, load_symbol_map
from sextant.tradingview.inputs import read_research_inputs
from sextant.tradingview.producer import Clocks

NS = 1_000_000_000
MINUTE_NS = 60 * NS
# OVERNIGHT (20:00-04:00 ET) is the next PR: bridge.py must accept it and #138
# supplies the boats baseline for this same publish path.
SUPPORTED = frozenset({"PRE", "RTH", "POST"})
ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CADENCE_REGISTRY = ROOT / "lanes/tradingview/j5-cadence.params.json"
DEFAULT_STATE_ROOT = Path.home() / "sextant-data" / "tradingview-prestage"
SIP_AUTHORITY = "slot-3 SIP market-data entitlement; REST-only display host"
MAPPING_SOURCE = "NASDAQ Trader nasdaqlisted.txt + otherlisted.txt read 2026-11-09"
REFERENCE_SOURCE = "alpaca_sip_split_1day official split-adjusted close"
ASSET_SOURCE = (
    "NASDAQ Trader directory operating-company superset; NOT PIT membership; "
    "halt status unknown (no status receipt)"
)
PROVENANCE = "alpaca_sip_raw_1min prior XNYS sessions; bar fidelity streaming one segment"
BOUNDS = frozenset({"gap_bound", "rvol_bound", "max_age_s"})


class PrestageError(ValueError):
    """A refused producer input or tick; the previous complete unit stays in place."""


class Source(Protocol):
    """The recorded or live bar history one producer tick may read."""

    def minute_bars(
        self, symbols: Sequence[str], *, start: datetime, end: datetime
    ) -> tuple[Bar, ...]: ...

    def daily_closes(self, symbols: Sequence[str], *, day: date) -> dict[str, Decimal]: ...


def load_registry(path: Path) -> Registry:
    """Read the operational K2 registry file into the validated registry."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema") != "k2-ranking.registry/1":
        raise PrestageError("not a K2 ranking registry")
    rows = []
    for item in raw.get("rows") or ():
        name, unit = item.get("name"), item.get("unit")
        kind = ROWS.get(name)
        if kind is None or kind[1] != unit:
            raise PrestageError(f"unknown registry row: {name}")
        raw_value = item["value"]
        if kind[0] is int:
            if type(raw_value) is not int:
                raise PrestageError(f"invalid registry value: {name}")
            value = raw_value
        else:
            if type(raw_value) not in (int, str):
                raise PrestageError(f"invalid registry value: {name}")
            value = Decimal(raw_value)
        rows.append(
            RegistryRow(
                name,
                unit,
                value,
                item["source"],
                item["calibration_state"],
                date.fromisoformat(item["last_change"]),
            )
        )
    return Registry(tuple(rows))


def load_maps(
    nasdaq_listed: Path, other_listed: Path, symbol_map: Path
) -> tuple[tuple[str, ...], dict[str, str]]:
    """Public directory texts plus the operator's exact TradingView map."""
    universe = build_universe(
        Path(nasdaq_listed).read_text(encoding="utf-8"),
        Path(other_listed).read_text(encoding="utf-8"),
    )
    raw = load_symbol_map(Path(symbol_map))
    missing = tuple(name for name in universe if not raw.get(name))
    if missing:
        raise PrestageError(
            f"The symbol map misses {len(missing)} of {len(universe)} directory symbols"
        )
    return universe, {name: str(raw[name]) for name in universe}


def cadence_floor(
    now: datetime,
    *,
    registry: Path = DEFAULT_CADENCE_REGISTRY,
    state_root: Path = DEFAULT_STATE_ROOT,
    weekly_usage_pct: Decimal = Decimal(0),
) -> int | None:
    """The J5 display floor from the shipped registry; never a timer or a literal."""
    cadence = Cadence(Path(state_root) / "cadence-unused", Path(registry), page=lambda _: None)
    return cadence.floor(now, weekly_usage_pct)


def prior_sessions(day: date, count: int = 5) -> tuple[date, ...]:
    """The most recent XNYS sessions strictly before ``day``, oldest first."""
    calendar = get_calendar("XNYS")
    sessions = calendar.sessions_in_range(day - timedelta(days=60), day - timedelta(days=1))
    if len(sessions) < count:
        raise PrestageError(f"fewer than {count} prior XNYS sessions")
    return tuple(item.date() for item in sessions[-count:])


def baseline_sessions(day: date, segment: Segment, count: int = 5) -> tuple[date, ...]:
    """Prior sessions whose start did not move and whose span covers this prefix."""
    candidates = prior_sessions(day, count + 10)
    expected_span = segment.end_ns - segment.start_ns
    chosen: list[date] = []
    for candidate in reversed(candidates):
        anchored = _session_start(candidate, segment)
        found, _, _ = segment_start(anchored + NS)
        if (
            found is None
            or found.name != segment.name
            or found.start_ns != anchored
            or found.end_ns - anchored < expected_span
        ):
            continue
        chosen.append(candidate)
        if len(chosen) == count:
            break
    if len(chosen) < count:
        raise PrestageError(f"fewer than {count} usable prior {segment.name} sessions")
    return tuple(sorted(chosen))


def build_segment_baseline(
    source: Source,
    *,
    segment: Segment,
    symbols: Sequence[str],
    sessions: Sequence[date],
    known_at: int,
    provenance: str = PROVENANCE,
) -> FiveSessionBaseline:
    """Stream one session at a time into the same curves/digest as build_baseline."""
    if segment.name not in SUPPORTED:
        raise PrestageError(f"no baseline for a {segment.name} segment")
    names = tuple(sorted(set(symbols)))
    if not names or len(names) != len(tuple(symbols)):
        raise PrestageError("A baseline needs distinct symbols")
    ordered = tuple(sorted(set(sessions)))
    if len(ordered) < 5 or len(ordered) != len(tuple(sessions)):
        raise PrestageError("A baseline needs five distinct prior sessions")
    span = segment.end_ns - segment.start_ns
    if span <= 0 or span % MINUTE_NS:
        raise PrestageError("A baseline segment spans whole minutes")
    points = span // MINUTE_NS + 1
    index = {name: position for position, name in enumerate(names)}
    dv_curves: list[array] = []
    count_curves: list[array] = []
    digest = hashlib.sha256()
    for day in ordered:
        session_start = _session_start(day, segment)
        start = datetime.fromtimestamp(session_start / NS, ET)
        bars = source.minute_bars(names, start=start, end=start + timedelta(seconds=span // NS))
        dv = array("q", [0]) * (len(names) * points)
        counts = array("i", [0]) * (len(names) * points)
        deltas: dict[int, list[int]] = {}
        trade_deltas: dict[int, list[int]] = {}
        for item in bars:
            row = index.get(item.symbol)
            if row is None:
                raise PrestageError(f"Bar outside the baseline universe: {item.symbol}")
            offset = (item.start_ns - session_start) // MINUTE_NS
            if offset < 0 or offset >= points - 1:
                continue
            delta = deltas.setdefault(row, [0] * points)
            count_delta = trade_deltas.setdefault(row, [0] * points)
            delta[offset] += int(item.close * item.volume * SCALE)
            count_delta[offset] += item.trades
        for row, delta in deltas.items():
            running = 0
            running_trades = 0
            base = row * points
            count_delta = trade_deltas[row]
            for point in range(1, points):
                running += delta[point - 1]
                running_trades += count_delta[point - 1]
                dv[base + point] = running
                counts[base + point] = running_trades
        dv_curves.append(dv)
        count_curves.append(counts)
        digest.update(day.isoformat().encode())
        digest.update(dv.tobytes())
        digest.update(counts.tobytes())
    if len(dv_curves) != 5:
        raise PrestageError("A baseline needs five sessions")
    return FiveSessionBaseline(
        segment=segment.name,
        end_s=span // NS,
        sessions=ordered,
        symbols=names,
        known_at=known_at,
        provenance=provenance,
        dv=tuple(dv_curves),
        counts=tuple(count_curves),
        data_digest=digest.hexdigest(),
    )


def collect_references(
    source: Source, *, day: date, symbols: Sequence[str]
) -> tuple[tuple[str, ...], dict[str, Decimal]]:
    """The official prior-session close, or a refusal; no symbol is invented."""
    closes = source.daily_closes(symbols, day=day)
    names = tuple(name for name in symbols if name in closes)
    if not names:
        raise PrestageError("no prior official close for the universe")
    return names, {name: closes[name] for name in names}


def _at(day: date, hour: int, minute: int = 0) -> int:
    return int(datetime.combine(day, clock_time(hour, minute), tzinfo=ET).timestamp()) * NS


def _ns(at: datetime) -> int:
    return int(at.timestamp()) * NS


class AlpacaDailyBars:
    """Daily official closes through the same paced transport as the minute bars."""

    def __init__(
        self, client: PacedStockBars, *, batch: int = MAX_BATCH, feed: DataFeed = DataFeed.SIP
    ) -> None:
        if type(batch) is not int or not 1 <= batch <= MAX_BATCH:
            raise ValueError(f"A daily close batch is 1..{MAX_BATCH}")
        self._client, self._batch, self._feed = client, batch, feed

    def daily_closes(self, symbols: Sequence[str], *, day: date) -> dict[str, Decimal]:
        if not isinstance(day, date):
            raise ValueError("A daily close request needs a date")
        names = tuple(sorted(set(symbols)))
        if not names:
            return {}
        start = datetime.combine(day, clock_time(0, 0), tzinfo=ET)
        end = start + timedelta(days=1)
        closes: dict[str, Decimal] = {}
        for chunk in _chunks(names, self._batch):
            request = StockBarsRequest(
                symbol_or_symbols=list(chunk),
                timeframe=cast(TimeFrame, TimeFrame.Day),
                start=start,
                end=end,
                feed=self._feed,
                adjustment=Adjustment.SPLIT,
                sort=Sort.ASC,
            )
            bars = cast(BarSet, self._client.get_stock_bars(request))
            for symbol, rows in bars.data.items():
                for row in rows:
                    stamp = row.timestamp
                    local = (
                        stamp.astimezone(ET)
                        if stamp.tzinfo is not None
                        else stamp.replace(tzinfo=UTC).astimezone(ET)
                    )
                    if local.date() != day:
                        continue
                    closes[str(symbol).upper()] = decimal_value(row.close)
        return closes


class AlpacaSource:
    """The live REST source one producer tick reads."""

    def __init__(self, bars: AlpacaBarSource, daily: AlpacaDailyBars) -> None:
        self._bars, self._daily = bars, daily

    def minute_bars(
        self, symbols: Sequence[str], *, start: datetime, end: datetime
    ) -> tuple[Bar, ...]:
        return self._bars.minute_bars(symbols, start=start, end=end)

    def daily_closes(self, symbols: Sequence[str], *, day: date) -> dict[str, Decimal]:
        return self._daily.daily_closes(symbols, day=day)


def _chunks(names: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for index in range(0, len(names), size):
        yield names[index : index + size]


def publish_tick(
    *,
    lease: Any,
    source: Source,
    segment: Segment,
    baseline: FiveSessionBaseline,
    symbols: Sequence[str],
    prior_closes: Mapping[str, Decimal],
    prior_close_ns: int,
    symbol_map: Mapping[str, str],
    registry: Registry,
    epoch: str,
    universe_source: str,
    now_ns: int,
    unit_dir: Path,
    j5_path: Path,
    bounds: DisplayBounds,
    max_age: int = 1_200,
    feed: str = "sip",
) -> dict[str, Any]:
    """Replay the current segment once and publish one complete unit."""
    if segment.name not in SUPPORTED:
        raise PrestageError(f"the producer does not write {segment.name} units")
    if not segment.start_ns <= now_ns < segment.end_ns:
        raise PrestageError("the publish clock is outside the supplied segment")
    start = datetime.fromtimestamp(segment.start_ns / NS, ET)
    completed_end_ns = now_ns - now_ns % MINUTE_NS
    if completed_end_ns <= segment.start_ns:
        raise PrestageError("no completed minute bars for this segment")
    end = datetime.fromtimestamp(completed_end_ns / NS, ET)
    bars = source.minute_bars(symbols, start=start, end=end)
    by_minute: dict[int, list[Bar]] = {}
    for item in bars:
        if (
            item.start_ns < segment.start_ns
            or item.close_ns > segment.end_ns
            or item.close_ns > completed_end_ns
        ):
            continue
        by_minute.setdefault(item.close_ns, []).append(item)
    clocks = sorted(by_minute)
    if not clocks:
        raise PrestageError("no completed minute bars for this segment")
    latest_close_ns = clocks[-1]

    publisher = RankingPublisher(
        bus=MessageBus(TraderId.from_str(f"TV-PRODUCER-{segment.name}-001")),
        epoch=epoch,
        feed=feed,
        segment=segment,
        registry=registry,
        universe=tuple(symbols),
        universe_source=universe_source,
        baseline=cast(BaselineTable, baseline),
    )
    for name in symbols:
        publisher.set_symbol(
            name,
            references=ReferencePrices(prior_closes[name], prior_close_ns, REFERENCE_SOURCE),
            asset=AssetState(prior_close_ns, segment.end_ns, None, "common", ASSET_SOURCE),
        )
    host = BarFidelityHost(
        publisher,
        lease=lease,
        sip_authority=SIP_AUTHORITY,
        symbol_map=dict(symbol_map),
    )

    ingested = 0
    for close_ns in clocks:
        ingested += host.ingest(
            BarPoll(bars=tuple(by_minute[close_ns]), requested=tuple(symbols)),
            market_ns=close_ns,
            received_ns=close_ns,
        )

    publish_clock_ns = max(latest_close_ns, min(now_ns, segment.end_ns - NS))
    max_age_ns = registry.seconds("input_max_age_s")
    for name, state in list(publisher.states.items()):
        if state.latest is None:
            continue
        event_ns = state.latest.observations.get("ts_event")
        price_ns = state.latest.observations.get("last_price_ts")
        if (
            type(event_ns) is not int
            or publish_clock_ns - event_ns > max_age_ns
            or (type(price_ns) is int and publish_clock_ns - price_ns > max_age_ns)
        ):
            publisher.states[name] = replace(state, latest=None)

    if not host.heartbeat(at=latest_close_ns, received_ns=publish_clock_ns):
        raise PrestageError("the bar-fidelity heartbeat was refused")
    j5 = host.publish(
        Path(j5_path),
        now=publish_clock_ns,
        mapping_clocks=Clocks(latest_close_ns, publish_clock_ns, MAPPING_SOURCE),
    )
    if j5.get("status") != "fresh":
        raise PrestageError(f"the J5 unit is not fresh: {j5.get('reason')}")
    projected = project_display_unit(j5, bounds=bounds)
    unit_dir = Path(unit_dir)
    if unit_dir.exists() and not unit_dir.is_symlink():
        raise PrestageError("the display unit is not a generation pointer; move it aside once")
    generations = unit_dir.parent / f"{unit_dir.name}.generations"
    generation = generations / j5["generation_sha256"]
    for filename, document in projected.documents().items():
        write_atomic(generation / filename, document)
    validated = read_research_inputs(
        generation,
        now=datetime.fromtimestamp(publish_clock_ns / NS, UTC),
        max_age=max_age,
    )
    pointer = unit_dir.parent / f".{unit_dir.name}.pointer"
    pointer.unlink(missing_ok=True)
    os.symlink(f"{generations.name}/{generation.name}", pointer, target_is_directory=True)
    os.replace(pointer, unit_dir)
    return {
        "schema": "sextant.tv-prestage-receipt/1",
        "segment": segment.name,
        "session_date": segment.session_date.isoformat(),
        "now_ns": now_ns,
        "publish_clock_ns": publish_clock_ns,
        "bars": sum(len(by_minute[clock]) for clock in clocks),
        "ingested": ingested,
        "expires_at_ns": _ns(validated.expires_at),
        "unit_dir": str(unit_dir),
        "generation_sha256": j5["generation_sha256"],
    }
