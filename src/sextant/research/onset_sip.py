"""#130 Part 1: the admitted Stocks in Play screen over the frozen SIP minute catalog.

The screen is the published local-filter screen from
`onest.sextant.research.detectors.stocks_in_play` (Zarattini--Barbon--Aziz,
DOI 10.2139/ssrn.4729284). This module only builds the coordinator-owned inputs:
the 09:30--09:35 ET opening window, the 14 prior opening windows, ATR(14) and the
14-day average volume. Missing inputs censor a symbol-day; nothing is imputed.

The composite bar is a native Nautilus BarType envelope over the five source
one-minute SIP bars. It is not a tick aggregation and not a venue feed claim.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from nautilus_trader.model import Bar, BarType, InstrumentId, Price, Quantity

from sextant.data.alpaca_history import symbol_name, timestamp
from sextant.research.detectors.stocks_in_play import (
    DailyFacts,
    OpeningWindow,
    StocksInPlaySpec,
    opening_window,
    screen,
)
from sextant.research.onset_common import read_bars, read_jsonl, read_sessions

NY = ZoneInfo("America/New_York")
NS = 1_000_000_000
OPEN = time(9, 30)
WINDOW_END = time(9, 35)
RTH_CLOSE = time(16, 0)
PRE = time(4, 0)
POST = time(20, 0)
LOOKBACK = 14


@dataclass(frozen=True)
class SymbolDay:
    symbol: str
    day: date
    role: str
    event_id: str
    control_id: str


def _clock(row: dict[str, Any]) -> datetime:
    return timestamp(row["t"]).astimezone(NY)


def _rth(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if OPEN <= _clock(row).time() < RTH_CLOSE]


def _opening(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in _rth(rows) if OPEN <= _clock(row).time() < WINDOW_END]


def _decimal(row: dict[str, Any], key: str) -> Decimal:
    return Decimal(str(row[key]))


def _instrument(symbol: str) -> InstrumentId:
    return InstrumentId.from_str(f"{symbol_name(symbol)}.NASDAQ")


def _composite(symbol: str, spec: StocksInPlaySpec) -> BarType:
    return spec.composite_type(_instrument(symbol))


def _native_window(
    symbol: str, day: date, rows: Sequence[dict[str, Any]], spec: StocksInPlaySpec
) -> OpeningWindow | None:
    five = _opening(rows)
    if not five:
        return None
    opened = datetime.combine(day, OPEN, NY)
    closed = opened + timedelta(minutes=spec.integer("opening_window"))
    opened_ns = int(opened.timestamp()) * NS
    closed_ns = int(closed.timestamp()) * NS
    # The opening window is the 5-minute composite over every SIP trade bar
    # printed in 09:30--09:35; a minute with no print is no trade, not a filled
    # price. A window with no print at all is censored above.
    composite = _composite(symbol, spec)
    bar = Bar(
        composite,
        Price.from_str(str(_decimal(five[0], "o"))),
        Price.from_str(str(max(_decimal(row, "h") for row in five))),
        Price.from_str(str(min(_decimal(row, "l") for row in five))),
        Price.from_str(str(_decimal(five[-1], "c"))),
        Quantity.from_str(str(sum(int(_decimal(row, "v")) for row in five))),
        closed_ns,
        closed_ns,
    )
    return opening_window(
        (bar,),
        session_open_ns=opened_ns,
        as_of_ns=closed_ns,
        coverage_complete=True,
        composite_type=composite,
        spec=spec,
    )


def _daily(rows: Sequence[dict[str, Any]]) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    """Return (high, low, close, volume) for one completed session, or None.

    Session means the 04:00--20:00 ET SIP window, the extended-session proxy
    used for ATR and ADV; not RTH only.
    """
    rows = [row for row in rows if PRE <= _clock(row).time() < POST]
    if not rows:
        return None
    high = max(_decimal(row, "h") for row in rows)
    low = min(_decimal(row, "l") for row in rows)
    close = _decimal(rows[-1], "c")
    volume = sum((_decimal(row, "v") for row in rows), Decimal(0))
    return high, low, close, volume


def _facts(
    symbol: str,
    prior_days: Sequence[date],
    bars_by_day: dict[date, list[dict[str, Any]]],
    spec: StocksInPlaySpec,
) -> DailyFacts | None:
    if len(prior_days) != LOOKBACK:
        return None
    daily = [_daily(bars_by_day[day]) for day in prior_days]
    if any(item is None for item in daily):
        return None
    highs = [item[0] for item in daily]  # type: ignore[index]
    lows = [item[1] for item in daily]  # type: ignore[index]
    closes = [item[2] for item in daily]  # type: ignore[index]
    volumes = [item[3] for item in daily]  # type: ignore[index]
    ranges = []
    for i in range(LOOKBACK):
        if i == 0:
            ranges.append(highs[0] - lows[0])
        else:
            ranges.append(
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
            )
    atr = sum(ranges, Decimal(0)) / LOOKBACK
    adv = sum(volumes, Decimal(0)) / LOOKBACK
    known = datetime.combine(prior_days[-1] + timedelta(days=1), time.min, NY)
    return DailyFacts(
        _instrument(symbol),
        tuple(prior_days),
        adv,
        atr,
        int(known.timestamp()) * NS,
    )


def evaluate(
    freeze: Path,
    raw_root: Path,
    calendar: Path,
    thresholds: Path,
    spec: StocksInPlaySpec,
    fallback: Path | None = None,
) -> dict[str, Any]:
    events = [
        row for row in read_jsonl(freeze / "events.jsonl") if row["cohort"] == "selected_gainer"
    ]
    controls = read_jsonl(freeze / "controls.jsonl")
    sessions = read_sessions(calendar)
    index = {day: i for i, day in enumerate(sessions)}
    anchors = {row["event_id"]: row for row in read_jsonl(thresholds)}

    primary = {(row["event_id"]): row for row in controls if row["role"] == "primary"}
    replacements = {}
    if fallback is not None and fallback.exists():
        replacements = {
            row["event_id"]: row for row in json.loads(fallback.read_text())["replacements"]
        }
    targets: dict[tuple[str, date], SymbolDay] = {}
    replaced = 0
    for event in events:
        key = (event["symbol"], date.fromisoformat(event["day"]))
        targets[key] = SymbolDay(
            event["symbol"],
            date.fromisoformat(event["day"]),
            "event",
            event["event_id"],
            "",
        )
        replacement = replacements.get(event["event_id"])
        control = replacement if replacement is not None else primary.get(event["event_id"])
        if replacement is not None:
            replaced += 1
        if control is not None:
            ckey = (control["ticker"], date.fromisoformat(control["day"]))
            targets.setdefault(
                ckey,
                SymbolDay(
                    control["ticker"],
                    date.fromisoformat(control["day"]),
                    "control",
                    event["event_id"],
                    control["control_id"],
                ),
            )

    results: list[dict[str, Any]] = []
    censored: Counter[str] = Counter()
    censored_role: Counter[str] = Counter()
    censored_detail: Counter[tuple[str, str]] = Counter()
    evaluated_role: Counter[str] = Counter()
    for (symbol, day), target in targets.items():
        i = index.get(day)
        if i is None or i < LOOKBACK:
            censored["calendar"] += 1
            censored_role[target.role] += 1
            censored_detail[(target.role, "calendar")] += 1
            continue
        prior_days = sessions[i - LOOKBACK : i]
        days = [*prior_days, day]
        bars = {d: read_bars(raw_root, symbol, d, ordered=True) for d in days}
        current = _native_window(symbol, day, bars[day], spec)
        if current is None:
            censored["opening_window"] += 1
            censored_role[target.role] += 1
            censored_detail[(target.role, "opening_window")] += 1
            continue
        prior = []
        for prior_day in prior_days:
            window = _native_window(symbol, prior_day, bars[prior_day], spec)
            if window is None:
                prior = []
                break
            prior.append(window)
        if len(prior) != LOOKBACK:
            censored["prior_opening_window"] += 1
            censored_role[target.role] += 1
            censored_detail[(target.role, "prior_opening_window")] += 1
            continue
        facts = _facts(symbol, prior_days, bars, spec)
        if facts is None:
            censored["daily_facts"] += 1
            censored_role[target.role] += 1
            censored_detail[(target.role, "daily_facts")] += 1
            continue
        as_of = int(datetime.combine(day, WINDOW_END, NY).timestamp()) * NS
        verdict = screen(
            current,
            tuple(prior),
            expected_sessions=tuple(prior_days),
            facts=facts,
            as_of_ns=as_of,
            spec=spec,
        )
        evaluated_role[target.role] += 1
        results.append(
            dict(
                symbol=symbol,
                day=day.isoformat(),
                role=target.role,
                event_id=target.event_id,
                control_id=target.control_id,
                rvol=str(verdict.rvol) if verdict.rvol is not None else None,
                passes=verdict.passes_local_filters,
                reason=verdict.reason,
                opening_volume=str(current.volume),
                atr=str(facts.atr),
                adv=str(facts.adv),
            )
        )

    # Rank the screen's passers by RVOL on the same 09:35 clock.
    passers = sorted(
        (row for row in results if row["passes"] is True and row["rvol"] is not None),
        key=lambda row: (-Decimal(row["rvol"]), row["symbol"], row["day"]),
    )
    rank = {f"{row['symbol']}|{row['day']}": i + 1 for i, row in enumerate(passers)}
    top_keys = {
        "top30": {f"{row['symbol']}|{row['day']}" for row in passers[:30]},
        "top100": {f"{row['symbol']}|{row['day']}" for row in passers[:100]},
    }

    def delta(row: dict[str, Any], field: str) -> float | None:
        anchor = row.get(field)
        if not anchor or row.get("passes") is not True:
            return None
        flagged = datetime.combine(date.fromisoformat(row["day"]), WINDOW_END, NY)
        return (flagged - datetime.fromisoformat(anchor)).total_seconds() / 60.0

    event_rows = {}
    for row in results:
        if row["role"] != "event":
            continue
        anchor = anchors.get(row["event_id"], {})
        event_rows[row["event_id"]] = dict(
            row,
            rank=rank.get(f"{row['symbol']}|{row['day']}"),
            first_5pct=anchor.get("first_5pct"),
            first_5pct_session=anchor.get("first_5pct_session"),
            first_10pct=anchor.get("first_10pct"),
            first_10pct_session=anchor.get("first_10pct_session"),
        )
        event_rows[row["event_id"]]["flag_minutes_5"] = delta(
            event_rows[row["event_id"]], "first_5pct"
        )
        event_rows[row["event_id"]]["flag_minutes_10"] = delta(
            event_rows[row["event_id"]], "first_10pct"
        )

    time_to_flag: dict[str, Any] = {}
    for field, label in (("flag_minutes_5", "five"), ("flag_minutes_10", "ten")):
        by_session: dict[str, list[float]] = defaultdict(list)
        session_field = "first_5pct_session" if label == "five" else "first_10pct_session"
        for row in event_rows.values():
            value = row.get(field)
            if value is not None:
                by_session[row.get(session_field)].append(value)
        time_to_flag[label] = {
            session: {
                "n": len(values),
                "median": median(values),
                "min": min(values),
                "max": max(values),
            }
            for session, values in by_session.items()
        }

    recall: dict[str, Any] = {}
    for field, label in (("first_5pct", "five"), ("first_10pct", "ten")):
        per_session: dict[str, dict[str, int]] = defaultdict(
            lambda: {"events": 0, "top30": 0, "top100": 0}
        )
        for row in event_rows.values():
            anchor = row.get(field)
            if not anchor:
                continue
            session = row.get(f"{field}_session")
            key = f"{row['symbol']}|{row['day']}"
            per_session[session]["events"] += 1
            per_session[session]["top30"] += int(key in top_keys["top30"])
            per_session[session]["top100"] += int(key in top_keys["top100"])
        recall[label] = {
            session: {
                "events": counts["events"],
                "top30": counts["top30"],
                "top100": counts["top100"],
                "recall30": counts["top30"] / counts["events"] if counts["events"] else None,
                "recall100": counts["top100"] / counts["events"] if counts["events"] else None,
            }
            for session, counts in per_session.items()
        }

    control_days = {row["day"] for row in results if row["role"] == "control"}
    control_flags = [row for row in results if row["role"] == "control" and row["passes"] is True]
    false_per_day = len(control_flags) / len(control_days) if control_days else None

    return dict(
        spec="stocks-in-play",
        params_hash=spec.params_hash,
        targets=len(targets),
        evaluated=len(results),
        censored=dict(censored),
        censored_role=dict(censored_role),
        censored_by_role_reason={
            f"{role}:{reason}": count for (role, reason), count in sorted(censored_detail.items())
        },
        censored_total=sum(censored.values()),
        evaluated_role=dict(evaluated_role),
        reasons=dict(Counter(row["reason"] for row in results)),
        fallback_used=replaced,
        fallback_file=str(fallback) if fallback is not None else None,
        passers=len(passers),
        top30=len(top_keys["top30"]),
        top100=len(top_keys["top100"]),
        recall=recall,
        control_days=len(control_days),
        control_flags=len(control_flags),
        control_top30=sum(
            1
            for row in results
            if row["role"] == "control" and f"{row['symbol']}|{row['day']}" in top_keys["top30"]
        ),
        control_top100=sum(
            1
            for row in results
            if row["role"] == "control" and f"{row['symbol']}|{row['day']}" in top_keys["top100"]
        ),
        time_to_flag=time_to_flag,
        false_flags_per_day=str(false_per_day) if false_per_day is not None else None,
        rows=sorted(results, key=lambda row: (row["day"], row["symbol"])),
        event_rows=sorted(event_rows.values(), key=lambda row: (row["day"], row["symbol"])),
    )
