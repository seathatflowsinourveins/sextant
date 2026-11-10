#!/usr/bin/env python3
"""Offline exit-rule study, NOT a NautilusTrader backtest or live validation.

Only local JSON/JSONL inputs; prices, quantities, indicators and returns use Decimal.
See docs/research/2026-10-29-b-exit-replay.md for the decision and assumptions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from bisect import bisect_right
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from itertools import product
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

from northstar_trading.scanner.day_files import day_file_path, day_files, read_day_json

D = Decimal
ZERO = D(0)
ONE = D(1)
BPS = D(10_000)
MINUTE = timedelta(minutes=1)
ET = ZoneInfo("America/New_York")
VERSION = "b-exit-replay/3"


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def session(at: datetime) -> str:
    return at.astimezone(ET).date().isoformat()


def boundary(day: str, hour: int, minute: int) -> datetime:
    return datetime.combine(date.fromisoformat(day), time(hour, minute), ET).astimezone(UTC)


def in_rth(at: datetime) -> bool:
    return time(9, 30) <= at.astimezone(ET).time().replace(tzinfo=None) < time(16)


def read_jsonl(path: Path) -> list[dict]:
    with path.open() as stream:
        return [json.loads(line, parse_float=D) for line in stream if line.strip()]


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    at: datetime
    o: Decimal
    h: Decimal
    l: Decimal  # noqa: E741 - input OHLC field name
    c: Decimal
    v: Decimal
    vw: Decimal

    @property
    def end(self) -> datetime:
        return self.at + MINUTE


@dataclass(slots=True)
class WilderAtr:
    """Growing arithmetic seed, then Wilder smoothing, initialized at period TRs."""

    period: int
    count: int = 0
    value: Decimal = ZERO
    previous: Decimal | None = None

    def update(self, high: Decimal, low: Decimal, close: Decimal) -> Decimal | None:
        tr = high - low
        if self.previous is not None:
            tr = max(tr, abs(high - self.previous), abs(low - self.previous))
        self.count += 1
        self.value += (tr - self.value) / min(self.count, self.period)
        self.previous = close
        return self.value if self.count >= self.period else None


@dataclass(slots=True)
class Entry:
    key: str
    symbol: str
    at: datetime
    price: Decimal
    qty: Decimal
    account: str
    source: str
    remaining: Decimal
    matched_qty: Decimal = ZERO
    matched_value: Decimal = ZERO
    actual_at: datetime | None = None

    @property
    def day(self) -> str:
        return session(self.at)

    @property
    def actual_price(self) -> Decimal | None:
        return self.matched_value / self.qty if self.remaining == 0 else None


@dataclass(frozen=True, slots=True)
class Variant:
    minutes: int
    period: int
    k: Decimal
    momentum: bool = False
    vwap: bool = False
    overlay: bool = False

    @property
    def name(self) -> str:
        extras = ("M" if self.momentum else "") + ("V" if self.vwap else "")
        return f"C{self.minutes}-n{self.period}-k{self.k}-{extras or 'R'}-{'ON' if self.overlay else 'OFF'}"

    @property
    def pair_name(self) -> str:
        return Variant(self.minutes, self.period, self.k, self.momentum, self.vwap, False).name


def variants() -> list[Variant]:
    return [
        Variant(minutes, period, D(k), momentum, vwap, overlay)
        for minutes, period, k, momentum, vwap, overlay in product(
            (1, 5), (14, 22), ("2", "2.5", "3"), (False, True), (False, True), (False, True)
        )
    ]


def load_bars(path: Path) -> dict[str, list[Bar]]:
    result: dict[str, list[Bar]] = defaultdict(list)
    seen = set()
    for row in read_jsonl(path):
        bar = Bar(row["symbol"], timestamp(row["t"]), *(D(row[k]) for k in ("o", "h", "l", "c", "v", "vw")))
        key = (bar.symbol, bar.at)
        if key in seen:
            raise ValueError(f"duplicate bar: {key}")
        seen.add(key)
        if not ZERO < bar.l <= min(bar.o, bar.c) <= max(bar.o, bar.c) <= bar.h or bar.v < 0:
            raise ValueError(f"invalid OHLC/volume: {key}")
        result[bar.symbol].append(bar)
    return {symbol: sorted(rows, key=lambda b: b.at) for symbol, rows in result.items()}


def owner_fill(path: Path) -> dict:
    orders = json.loads(path.read_text(), parse_float=D)["owner_orders"]
    mu = next(row["broker"] for row in orders if row["broker"]["symbol"] == "MU")
    return dict(
        activity_id="owner-MU-20261029",
        order_id=mu["id"],
        client_order_id=mu["client_order_id"],
        symbol="MU",
        side="buy",
        qty=mu["filled_qty"],
        price=mu["filled_avg_price"],
        transaction_time=mu["filled_at"],
        account_slot="b",
    )


def opening_entries(rows: list[dict], symbols: set[str]) -> tuple[list[Entry], dict]:
    """FIFO long ledger; explicit shorts create cover debt, never long entries.

    Unknown-prefix buys and pre-window long disposals taint their account/symbol
    until a later explicit sell_short establishes a known short-side boundary.
    """
    entries: list[Entry] = []
    lots: dict[tuple[str, str], deque[Entry]] = defaultdict(deque)
    short: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    unknown: set[tuple[str, str]] = set()
    counts: Counter = Counter()
    for row in sorted(rows, key=lambda r: (timestamp(r["transaction_time"]), r["activity_id"])):
        key = (row["account_slot"], row["symbol"])
        qty = D(row["qty"])
        at = timestamp(row["transaction_time"])
        tag = row.get("client_order_id")
        if row["side"] == "sell_short":
            short[key] += qty
            unknown.discard(key)
            counts["explicit_short_fills"] += 1
            continue
        if row["side"] == "sell":
            while qty > 0 and lots[key]:
                lot = lots[key][0]
                used = min(qty, lot.remaining)
                lot.matched_qty += used
                lot.matched_value += used * D(row["price"])
                lot.remaining -= used
                lot.actual_at = at
                qty -= used
                if lot.remaining == 0:
                    lots[key].popleft()
            if qty > 0:
                unknown.add(key)
                counts["unmatched_sell_fills_preexisting_or_unknown"] += 1
            continue
        if row["side"] != "buy":
            raise ValueError(f"unsupported fill side: {row['side']}")
        covered = min(qty, short[key])
        short[key] -= covered
        qty -= covered
        if covered:
            counts["short_cover_buy_fills"] += 1
        if not qty:
            continue
        if not tag or tag.startswith(("coord-", "ns-")):
            counts["unclassified_or_protection_buy_fills"] += 1
            unknown.add(key)
            continue
        if key in unknown:
            counts["unknown_inventory_buy_fills_excluded"] += 1
            continue
        source = "strategy" if tag.startswith("O-") else "owner"
        entry = Entry(
            row["activity_id"], row["symbol"], at, D(row["price"]), qty, row["account_slot"], source, qty
        )
        lots[key].append(entry)
        counts["known_long_opening_fills_all_hours"] += 1
        if row["symbol"] not in symbols:
            counts["opening_fills_outside_symbol_universe"] += 1
        elif not in_rth(at):
            counts["opening_fills_outside_rth"] += 1
        else:
            entries.append(entry)
    counts["entries"] = len(entries)
    counts["strategy_entries"] = sum(e.source == "strategy" for e in entries)
    counts["owner_entries"] = sum(e.source == "owner" for e in entries)
    counts["unresolved_inventory_pairs"] = len(unknown)
    return entries, dict(counts)


def five_minute(bars: list[Bar]) -> list[Bar]:
    groups: dict[datetime, list[Bar]] = defaultdict(list)
    for bar in bars:
        groups[bar.at.replace(minute=bar.at.minute // 5 * 5)].append(bar)
    result = []
    for at, group in sorted(groups.items()):
        if [b.at for b in group] != [at + i * MINUTE for i in range(5)]:
            continue
        volume = sum((b.v for b in group), ZERO)
        vwap = sum((b.vw * b.v for b in group), ZERO) / volume if volume else group[-1].c
        result.append(
            Bar(
                group[0].symbol,
                at,
                group[0].o,
                max(b.h for b in group),
                min(b.l for b in group),
                group[-1].c,
                volume,
                vwap,
            )
        )
    return result


def atr_series(bars: list[Bar], period: int, minutes: int) -> dict[datetime, tuple[Decimal, Bar]]:
    atr = WilderAtr(period)
    result = {}
    for bar in bars:
        value = atr.update(bar.h, bar.l, bar.c)
        if value is not None:
            result[bar.at + minutes * MINUTE] = (value, bar)
    return result


def market_states(all_bars: dict[str, list[Bar]]) -> dict[datetime, bool]:
    """Known-at-close OR across SPY/QQQ; 20-period return state, no future bars."""
    events: dict[datetime, dict[str, bool]] = defaultdict(dict)
    for symbol in ("SPY", "QQQ"):
        bars = five_minute(all_bars[symbol])
        for i, bar in enumerate(bars):
            low_break = i > 0 and bar.c < bars[i - 1].l
            negative_return = i >= 20 and bar.c < bars[i - 20].c
            events[bar.at + 5 * MINUTE][symbol] = low_break or negative_return
    state = {"SPY": False, "QQQ": False}
    result = {}
    for at, updates in sorted(events.items()):
        state.update(updates)
        result[at] = any(state.values())
    return result


@dataclass(slots=True)
class PathData:
    bars: list[Bar]
    atr: dict[tuple[int, int], dict[datetime, tuple[Decimal, Bar]]]
    vwap: dict[datetime, Decimal]
    market: dict[datetime, bool]
    market_times: list[datetime] = field(init=False)
    opens: dict[datetime, Bar] = field(init=False)
    times: list[datetime] = field(init=False)
    atr_times: dict[tuple[int, int], list[datetime]] = field(init=False)

    def __post_init__(self) -> None:
        self.market_times = sorted(self.market)
        self.opens = {b.at: b for b in self.bars}
        self.times = [b.at for b in self.bars]
        self.atr_times = {key: sorted(values) for key, values in self.atr.items()}

    def risk_off(self, at: datetime) -> bool:
        i = bisect_right(self.market_times, at) - 1
        return self.market[self.market_times[i]] if i >= 0 else False


def prepare(bars: dict[str, list[Bar]]) -> dict[str, PathData]:
    market = market_states(bars)
    result = {}
    for symbol, rows in bars.items():
        five = five_minute(rows)
        atr = {(m, n): atr_series(rows if m == 1 else five, n, m) for m, n in product((1, 5), (14, 22))}
        pv = volume = ZERO
        day = ""
        vwaps = {}
        for b in rows:
            if session(b.at) != day:
                pv = volume = ZERO
                day = session(b.at)
            # Session VWAP = RTH only; extended bars warm ATR, not the RTH VWAP.
            if in_rth(b.at):
                pv += b.v * b.vw
                volume += b.v
                if volume:
                    vwaps[b.end] = pv / volume
        result[symbol] = PathData(rows, atr, vwaps, market)
    return result


@dataclass(frozen=True, slots=True)
class Exit:
    at: datetime | None
    price: Decimal | None
    reason: str
    mae_bps: Decimal
    tightened: bool = False
    trail_distance: Decimal | None = None


def replay(entry: Entry, data: PathData, variant: Variant | None, *, trail_floor: Decimal = ZERO) -> Exit:
    flat = boundary(entry.day, 15, 55)
    if entry.at >= flat:
        return Exit(None, None, "entry_after_flat", ZERO)
    start = entry.at.replace(second=0, microsecond=0)
    if start < entry.at:
        start += MINUTE
    hh = entry.price
    lowest = entry.price
    stop: Decimal | None = None
    active_atr: Decimal | None = None
    tightened = False
    above = 0
    armed = False
    previous: Bar | None = None
    lower_high = False
    previous_end: datetime | None = None
    atrs = data.atr[(variant.minutes, variant.period)] if variant else {}
    # ATR can warm on all completed bars, but HH and signals exclude the entry's partial bar.
    if variant:
        times = data.atr_times[(variant.minutes, variant.period)]
        i = bisect_right(times, start) - 1
        if i >= 0:
            active_atr = atrs[times[i]][0]
            stop = hh - max(variant.k * active_atr, trail_floor)
    left = bisect_right(data.times, start - timedelta(microseconds=1))
    right = bisect_right(data.times, flat - timedelta(microseconds=1))
    for bar in data.bars[left:right]:
        lowest = min(lowest, bar.l)
        hh = max(hh, bar.h)
        end = bar.end
        if (previous_end is None and bar.at != start) or (
            previous_end is not None and bar.at != previous_end
        ):
            # Cannot claim a known first exit across a missing held minute.
            return Exit(None, None, "missing_held_minute", (lowest / entry.price - ONE) * BPS, tightened)
        previous_end = end
        if variant is None:
            continue
        if end in atrs:
            active_atr = atrs[end][0]
        if variant.overlay and data.risk_off(end):
            tightened = True
        chandelier_close = variant.minutes == 1 or end in atrs
        if active_atr is not None and chandelier_close:
            k = variant.k - (D("0.5") if tightened else ZERO)
            candidate = hh - max(k * active_atr, trail_floor)
            stop = candidate if stop is None else max(stop, candidate)
        reason = ""
        if chandelier_close and stop is not None and bar.c <= stop:
            reason = "chandelier"
        contiguous = previous is not None and previous.end == bar.at
        if variant.momentum and previous is not None and contiguous:
            # A completed lower-high bar, THEN a later close below its low.
            if lower_high and bar.c < previous.l:
                reason = reason or "momentum"
            lower_high = bar.h < previous.h
        elif not contiguous:
            lower_high = False
        vwap = data.vwap.get(end)
        if vwap is not None and bar.c > vwap:
            above = above + 1 if contiguous else 1
            armed = armed or above >= 5
        else:
            if variant.vwap and armed and vwap is not None and bar.c < vwap:
                reason = reason or "vwap"
            above = 0
        previous = bar
        if reason:
            next_bar = data.opens.get(end)
            if next_bar is None or end > flat:
                return Exit(
                    None, None, "signal_without_next_open", (lowest / entry.price - ONE) * BPS, tightened
                )
            lowest = min(lowest, next_bar.o)
            distance = hh - stop if reason == "chandelier" and stop is not None else None
            return Exit(end, next_bar.o, reason, (lowest / entry.price - ONE) * BPS, tightened, distance)
    if previous_end != flat and flat in data.opens:
        return Exit(None, None, "missing_held_minute", (lowest / entry.price - ONE) * BPS, tightened)
    flat_bar = data.opens.get(flat)
    if flat_bar is not None:
        lowest = min(lowest, flat_bar.o)
        return Exit(flat, flat_bar.o, "flat", (lowest / entry.price - ONE) * BPS, tightened)
    return Exit(None, None, "right_censored", (lowest / entry.price - ONE) * BPS, tightened)


def actual_exit(entry: Entry, data: PathData) -> Exit:
    if entry.actual_price is None or entry.actual_at is None:
        return Exit(None, None, "unmatched_actual", ZERO)
    # Only fully held minute lows; entry/exit partial minutes are unknowable.
    lows = [b.l for b in data.bars if b.at >= entry.at and b.end <= entry.actual_at]
    lowest = min([entry.price, entry.actual_price, *lows])
    return Exit(entry.actual_at, entry.actual_price, "actual", (lowest / entry.price - ONE) * BPS)


def net_return(entry: Entry, exit_price: Decimal, cost_bps: Decimal) -> Decimal:
    # One unit entry mid notional; costs on both traded notionals, not just subtract 2c.
    ratio = exit_price / entry.price
    return ratio * (ONE - cost_bps / BPS) - (ONE + cost_bps / BPS)


def metrics(entries: list[Entry], exits: dict[str, Exit], cost: Decimal) -> dict:
    resolved = [
        (e, exits[e.key]) for e in entries if exits[e.key].price is not None and exits[e.key].at is not None
    ]
    returns = [net_return(e, x.price, cost) for e, x in resolved if x.price is not None]
    bps = [r * BPS for r in returns]
    wins = [r for r in bps if r > 0]
    losses = [r for r in bps if r <= 0]
    total = sum(returns, ZERO)
    count = len(returns)
    mean = total * BPS / count if count else None
    return dict(
        entries=len(entries),
        trades=count,
        censored=len(entries) - count,
        mean_bps=mean,
        median_bps=median(bps) if bps else None,
        expectancy_bps=mean,
        win_rate=D(len(wins)) / count if count else None,
        mean_win_bps=sum(wins, ZERO) / len(wins) if wins else ZERO,
        mean_loss_bps=sum(losses, ZERO) / len(losses) if losses else ZERO,
        max_adverse_excursion_bps=min((x.mae_bps for _, x in resolved), default=None),
        mean_mae_bps=sum((x.mae_bps for _, x in resolved), ZERO) / count if count else None,
        total_pnl_unit_notional=total,
        share_exited_before_flat=D(
            sum(x.at is not None and x.at < boundary(e.day, 15, 55) for e, x in resolved)
        )
        / count
        if count
        else None,
        tightened_trades=sum(x.tightened for _, x in resolved),
        reasons=dict(Counter(x.reason for _, x in resolved)),
    )


def summarize(entries: list[Entry], exits: dict[str, Exit]) -> dict:
    return {str(cost): metrics(entries, exits, cost) for cost in (D(3), D(6))}


def select(
    entries: list[Entry], grid: list[Variant], results: dict[str, dict[str, Exit]], summaries: dict[str, dict]
) -> dict:
    """Predeclared: positive 6bps/side, positive every leave-one-day-out mean.

    Overlay must not underperform its otherwise identical OFF pair at either cost.
    All decisions use identical full-flat-covered 10/26-28 entries, never survivors.
    """
    eligible = []
    reasons = Counter()
    days = sorted({e.day for e in entries})
    for v in grid:
        scores = summaries[v.name]["primary"]["combined"]
        stress = scores["6"]["mean_bps"]
        if stress is None or stress <= 0:
            reasons["nonpositive_stressed_expectancy"] += 1
            continue
        if scores["3"]["trades"] != len(entries):
            reasons["incomplete_primary_cohort"] += 1
            continue
        loo = {}
        for day in days:
            subset = [e for e in entries if e.day != day]
            loo[day] = metrics(subset, results[v.name], D(6))["mean_bps"]
        if len(days) < 3 or any(value is None or value <= 0 for value in loo.values()):
            reasons["single_day_dependence"] += 1
            continue
        if v.overlay:
            off = summaries[v.pair_name]["primary"]["combined"]
            if any(scores[c]["mean_bps"] < off[c]["mean_bps"] for c in ("3", "6")):
                reasons["overlay_worse_than_off"] += 1
                continue
        eligible.append((scores["3"]["mean_bps"], v.name, loo))
    eligible.sort(key=lambda x: (-x[0], x[1]))
    ranking = sorted(
        grid,
        key=lambda v: (
            -(summaries[v.name]["primary"]["combined"]["3"]["mean_bps"] or D("-Infinity")),
            v.name,
        ),
    )
    return dict(
        eligible_count=len(eligible),
        rejected=dict(reasons),
        recommended=eligible[0][1] if eligible else None,
        leave_one_day_out_stress_bps=eligible[0][2] if eligible else {},
        top_five=[v.name for v in ranking[:5]],
        eligible_top_five=[row[1] for row in eligible[:5]],
        rule="maximize primary combined mean; stress>0; all leave-one-day-out stress means>0; overlay>=OFF",
    )


HALF_SPREAD_BPS = D(1)  # Assumption: no historical quotes are present.


def patch_price(price: Decimal) -> Decimal:
    return price * (ONE - HALF_SPREAD_BPS / BPS)


def patch_exit(entry: Entry, data: PathData, variant: Variant | None) -> Exit:
    mark = replay(entry, data, variant)
    if mark.price is not None and mark.reason != "flat":
        return replace(mark, price=patch_price(mark.price))
    return mark


def resting_exit(entry: Entry, data: PathData, variant: Variant) -> Exit:
    """Stop known before the triggering minute; no same-bar high/low ordering guess.

    A crossed new stop cannot be PATCHed above market, so request an active exit
    at the next open instead. The old resting stop remains valid until then.
    """
    flat = boundary(entry.day, 15, 55)
    if entry.at >= flat:
        return Exit(None, None, "entry_after_flat", ZERO)
    start = entry.at.replace(second=0, microsecond=0)
    if start < entry.at:
        start += MINUTE
    times = data.atr_times[(variant.minutes, variant.period)]
    atrs = data.atr[(variant.minutes, variant.period)]
    i = bisect_right(times, entry.at) - 1
    active_atr = atrs[times[i]][0] if i >= 0 else None
    stop = entry.price - variant.k * active_atr if active_atr is not None else None
    hh = lowest = entry.price
    previous_end = start
    left = bisect_right(data.times, start - timedelta(microseconds=1))
    right = bisect_right(data.times, flat - timedelta(microseconds=1))
    for bar in data.bars[left:right]:
        if bar.at != previous_end:
            return Exit(None, None, "missing_held_minute", (lowest / entry.price - ONE) * BPS)
        # The existing stop was known before this bar; never use its future HH.
        if stop is not None and bar.l <= stop:
            price = min(stop, bar.o)
            # The trigger-minute low may occur after execution; it is not held MAE.
            lowest = min(lowest, price)
            return Exit(bar.at, price, "resting_stop", (lowest / entry.price - ONE) * BPS)
        lowest = min(lowest, bar.l)
        hh = max(hh, bar.h)
        previous_end = bar.end
        if bar.end in atrs:
            active_atr = atrs[bar.end][0]
            candidate = hh - variant.k * active_atr
            stop = candidate if stop is None else max(stop, candidate)
            if bar.c <= stop:
                next_bar = data.opens.get(bar.end)
                if next_bar is None:
                    return Exit(None, None, "signal_without_next_open", (lowest / entry.price - ONE) * BPS)
                price = patch_price(next_bar.o)
                lowest = min(lowest, price)
                return Exit(bar.end, price, "crossed_stop_patch", (lowest / entry.price - ONE) * BPS)
    flat_bar = data.opens.get(flat)
    if flat_bar is not None and previous_end == flat:
        lowest = min(lowest, flat_bar.o)
        return Exit(flat, flat_bar.o, "flat", (lowest / entry.price - ONE) * BPS)
    reason = "missing_held_minute" if flat_bar is not None else "right_censored"
    return Exit(None, None, reason, (lowest / entry.price - ONE) * BPS)


def execution_study(
    entries: list[Entry], primary: list[Entry], data: dict[str, PathData], frozen: Variant
) -> dict:
    marks = {
        "active_patch": {e.key: patch_exit(e, data[e.symbol], frozen) for e in entries},
        "resting_stop": {e.key: resting_exit(e, data[e.symbol], frozen) for e in entries},
    }
    # Same minute-resolution prices; an extra subsecond delay is not observable.
    marks["cancel_market"] = marks["active_patch"]
    periods = {
        "primary": primary,
        "all_observed": entries,
        **{day: [e for e in entries if e.day == day] for day in sorted({e.day for e in entries})},
    }
    return {
        "frozen": frozen.name,
        "assumed_half_spread_bps": HALF_SPREAD_BPS,
        "cancel_market_price_difference_bps": ZERO,
        "summaries": {
            name: {p: summarize(subset, exits) for p, subset in periods.items()}
            for name, exits in marks.items()
        },
        "mu": {
            name: [dict(entry=e.key, **asdict(exits[e.key])) for e in entries if e.source == "owner"]
            for name, exits in marks.items()
        },
    }


def proxy_ranks(bars: dict[str, list[Bar]]) -> tuple[dict[datetime, list[str]], dict]:
    """Bar-only PROXY, not the unarchived live focus-list rank.

    RVOL uses contiguous RTH volume through the decision against the same elapsed
    minutes of earlier file sessions. Signed opening gap uses the immediately prior
    file session's last RTH close. All inputs end no later than the rank timestamp.
    """
    days = sorted({session(b.at) for rows in bars.values() for b in rows})
    opens = {symbol: {b.at: b for b in rows} for symbol, rows in bars.items()}
    prefixes = {}
    for symbol, by_time in opens.items():
        for day in days:
            volume = ZERO
            contiguous = True
            values = {}
            for minute in range(390):
                b = by_time.get(boundary(day, 9, 30) + minute * MINUTE)
                contiguous = contiguous and b is not None
                if b is not None:
                    volume += b.v
                if contiguous:
                    values[minute + 1] = volume
            prefixes[(symbol, day)] = values
    ranks = {}
    counts = Counter()
    for day_index, day in enumerate(days):
        if day_index == 0:
            counts[f"{day}/no_prior_session"] += 1
            continue
        prior_day = days[day_index - 1]
        for elapsed in range(5, 386, 5):
            at = boundary(day, 9, 30) + elapsed * MINUTE
            scored = []
            for symbol, by_time in opens.items():
                opening = by_time.get(boundary(day, 9, 30))
                prior_close = by_time.get(boundary(prior_day, 15, 59))
                last = by_time.get(at - MINUTE)
                lookback = by_time.get(at - 31 * MINUTE)
                current = prefixes[(symbol, day)].get(elapsed)
                history = [
                    prefixes[(symbol, d)][elapsed]
                    for d in days[:day_index]
                    if elapsed in prefixes[(symbol, d)]
                ]
                if (
                    opening is None
                    or prior_close is None
                    or last is None
                    or lookback is None
                    or current is None
                    or not history
                    or sum(history, ZERO) <= 0
                ):
                    continue
                rvol = current * len(history) / sum(history, ZERO)
                gap = opening.o / prior_close.c - ONE
                ret30 = last.c / lookback.c - ONE
                scored.append((rvol * gap, ret30, symbol))
            scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
            if scored:
                ranks[at] = [row[2] for row in scored]
                counts[f"{day}/rank_boundaries"] += 1
                counts[f"{day}/ranked_name_observations"] += len(scored)
    return ranks, dict(counts)


@dataclass(frozen=True, slots=True)
class Rotation:
    slots: int
    rank_gap: int = 0
    cap: int = 0
    hold: bool = False

    @property
    def name(self) -> str:
        if self.hold:
            return f"PROXY-N{self.slots}-hold-flat"
        if not self.cap:
            return f"PROXY-N{self.slots}-exits-refill"
        return f"PROXY-N{self.slots}-X{self.rank_gap}-R{self.cap}"


def lagged_return(data: PathData, at: datetime, minutes: int) -> Decimal | None:
    last = data.opens.get(at - MINUTE)
    before = data.opens.get(at - (minutes + 1) * MINUTE)
    return last.c / before.c - ONE if last is not None and before is not None else None


def rotation_day(
    day: str,
    config: Rotation,
    ranks: dict[datetime, list[str]],
    data: dict[str, PathData],
    frozen: Variant,
    cache: dict,
) -> dict:
    """Price decisions independent of costs; N self-financing equal-capital slots.

    Empty slots may refill immediately with another name; a sold name is ineligible
    for 15 minutes and may re-enter just once, only while top-N. An eligible sold
    same-name top-N gets refill priority after its cooldown. Cash compounds within
    each slot separately for the two cost assumptions.
    """
    flat = boundary(day, 15, 55)
    available = min(flat, max(b.end for d in data.values() for b in d.bars if session(b.at) == day))
    slots: list[tuple[Entry, Exit] | None] = [None] * config.slots
    capital = {c: [ONE / config.slots] * config.slots for c in (D(3), D(6))}
    buys = Counter()
    last_exit: dict[str, datetime] = {}
    last_slot_action = [boundary(day, 9, 15)] * config.slots
    rotations = 0
    trades = []
    invalid = set()

    def close(slot: int, mark: Exit) -> None:
        position = slots[slot]
        assert position is not None
        assert mark.price is not None
        assert mark.at is not None
        e = position[0]
        for cost, values in capital.items():
            # Entry costs paid from available cash, no borrowing or fixed-notional reset.
            values[slot] *= (mark.price / e.price) * (ONE - cost / BPS) / (ONE + cost / BPS)
        last_exit[e.symbol] = mark.at + MINUTE if mark.reason == "resting_stop" else mark.at
        slots[slot] = None
        trades.append(
            dict(
                symbol=e.symbol,
                entry_at=e.at,
                exit_at=mark.at,
                entry_price=e.price,
                exit_price=mark.price,
                reason=mark.reason,
            )
        )

    def open_slot(slot: int, symbol: str, at: datetime) -> None:
        current = data[symbol].opens.get(at)
        if current is None:
            return
        e = Entry(f"PROXY-{day}-{symbol}-{at.isoformat()}", symbol, at, current.o, ONE, "proxy", "proxy", ONE)
        key = (symbol, at, config.hold)
        if key not in cache:
            cache[key] = (
                replay(e, data[symbol], None) if config.hold else resting_exit(e, data[symbol], frozen)
            )
        mark = cache[key]
        slots[slot] = (e, mark)
        buys[symbol] += 1
        last_slot_action[slot] = at

    def record_missing(e: Entry, until: datetime) -> None:
        times = data[e.symbol].times
        left = bisect_right(times, e.at - timedelta(microseconds=1))
        right = bisect_right(times, until - timedelta(microseconds=1))
        if right - left != (until - e.at) // MINUTE:
            invalid.add(e.key)

    for elapsed in range(5, 386, 5):
        at = boundary(day, 9, 30) + elapsed * MINUTE
        if at > available:
            break
        for slot, position in enumerate(slots):
            if position is None:
                continue
            mark = position[1]
            # A non-gap resting fill's within-minute time is unknown; use only after its bar completes.
            known_at = mark.at + MINUTE if mark.at is not None and mark.reason == "resting_stop" else mark.at
            if known_at is not None and known_at <= at:
                close(slot, mark)
            elif mark.price is None:
                record_missing(position[0], at)
        if at == flat:
            break
        ranked = ranks.get(at, [])
        if not ranked:
            continue
        held: set[str] = {p[0].symbol for p in slots if p is not None}
        rank = {symbol: i + 1 for i, symbol in enumerate(ranked)}

        def eligible(symbol: str, held=held, at=at, rank=rank) -> bool:
            if symbol in held or at not in data[symbol].opens:
                return False
            if buys[symbol] == 0:
                return True
            return (
                buys[symbol] == 1
                and rank[symbol] <= config.slots
                and symbol in last_exit
                and at - last_exit[symbol] >= 15 * MINUTE
            )

        candidates = [symbol for symbol in ranked if eligible(symbol)]
        if config.cap and rotations < config.cap and all(p is not None for p in slots) and candidates:
            candidate = candidates[0]
            stalled = []
            for slot, position in enumerate(slots):
                assert position is not None
                e = position[0]
                ret15 = lagged_return(data[e.symbol], at, 15)
                if (
                    e.symbol in rank
                    and ret15 is not None
                    and ret15 <= 0
                    and at - last_slot_action[slot] >= 15 * MINUTE
                    and rank[e.symbol] - rank[candidate] >= config.rank_gap
                    and at in data[e.symbol].opens
                ):
                    stalled.append((rank[e.symbol], -ret15, slot))
            if stalled:
                _, _, slot = max(stalled)
                position = slots[slot]
                assert position is not None
                e = position[0]
                price = patch_price(data[e.symbol].opens[at].o)
                close(slot, Exit(at, price, "opportunity_rotation", ZERO))
                open_slot(slot, candidate, at)
                held.add(candidate)
                rotations += 1
        for slot, position in enumerate(slots):
            if position is not None:
                continue
            # Re-entry priority applies only after cooldown and only if still top-N.
            choices = [symbol for symbol in ranked if eligible(symbol)]
            reentries = [symbol for symbol in choices if buys[symbol] == 1]
            choices = reentries or choices
            if choices:
                open_slot(slot, choices[0], at)
                held.add(choices[0])

    open_positions = 0
    for slot, position in enumerate(slots):
        if position is None:
            continue
        e, mark = position
        if mark.price is None:
            record_missing(e, available)
        if mark.price is not None and mark.at is not None and mark.at <= available:
            close(slot, mark)
            continue
        # No invented flat: partial session is marked to last known close with exit-cost reserve.
        observed = [b for b in data[e.symbol].bars if e.at <= b.at and b.end <= available]
        flat_bar = data[e.symbol].opens.get(flat) if available == flat else None
        price = flat_bar.o if flat_bar is not None else observed[-1].c if observed else e.price
        for cost, values in capital.items():
            values[slot] *= (price / e.price) * (ONE - cost / BPS) / (ONE + cost / BPS)
        open_positions += 1
    return dict(
        day=day,
        status=(
            "no_prior_proxy_rank"
            if not buys
            else "invalid_missing_minutes"
            if invalid
            else "full"
            if available == flat and not open_positions
            else "partial_mtm"
        ),
        entries=sum(buys.values()),
        closed_trades=len(trades),
        open_positions=open_positions,
        rotations=rotations,
        reentries=sum(max(n - 1, 0) for n in buys.values()),
        invalid_missing_minute_paths=len(invalid),
        available_through=available,
        return_bps={str(c): (sum(values, ZERO) - ONE) * BPS for c, values in capital.items()},
        trades=trades,
    )


def rotation_study(bars: dict[str, list[Bar]], data: dict[str, PathData], frozen: Variant) -> dict:
    ranks, audit = proxy_ranks(bars)
    days = sorted({session(b.at) for rows in bars.values() for b in rows})
    configurations = [Rotation(n, gap, cap) for n, gap, cap in product((4, 8), (5, 10), (2, 4))]
    configurations += [Rotation(n, hold=hold) for n, hold in product((4, 8), (False, True))]
    cache = {}
    results = {
        c.name: {day: rotation_day(day, c, ranks, data, frozen, cache) for day in days}
        for c in configurations
    }
    primary_days = [day for day in days if day < "2026-10-29" and any(session(at) == day for at in ranks)]
    aggregates = {}
    eligible = []
    for c in configurations:
        rows = results[c.name]
        means = {
            str(cost): sum((rows[d]["return_bps"][str(cost)] for d in primary_days), ZERO) / len(primary_days)
            if primary_days
            else None
            for cost in (D(3), D(6))
        }
        baseline = results[Rotation(c.slots).name]
        deltas = {
            d: {
                str(cost): rows[d]["return_bps"][str(cost)] - baseline[d]["return_bps"][str(cost)]
                for cost in (D(3), D(6))
            }
            for d in primary_days
        }
        complete = all(
            rows[d]["status"] == baseline[d]["status"] == "full"
            and not rows[d]["open_positions"]
            and not baseline[d]["open_positions"]
            and not rows[d]["invalid_missing_minute_paths"]
            and not baseline[d]["invalid_missing_minute_paths"]
            for d in primary_days
        )
        passes = bool(
            c.cap
            and len(primary_days) >= 2
            and complete
            and all(value >= 0 for row in deltas.values() for value in row.values())
            and any(value > 0 for row in deltas.values() for value in row.values())
        )
        aggregates[c.name] = dict(
            primary_days=primary_days,
            mean_daily_return_bps=means,
            deltas_vs_no_rotation_bps=deltas,
            complete=complete,
            eligible=passes,
        )
        if passes:
            eligible.append((means["3"], c.name))
    eligible.sort(reverse=True)
    return dict(
        label="BAR-ONLY PROXY RANK; NOT LIVE FOCUS-LIST HISTORY",
        variant_count=8,
        baseline_count=4,
        frozen=frozen.name,
        exit_execution="resting_stop",
        rank_audit=audit,
        primary_days=primary_days,
        aggregates=aggregates,
        daily=results,
        recommendation=eligible[0][1] if eligible else "OFF",
        rule="ON only with complete full sessions and nonnegative daily deltas at both costs; strict gain",
    )


@dataclass(frozen=True, slots=True)
class SpreadSnapshot:
    at: datetime
    quotes: dict[str, tuple[Decimal, datetime | None]]
    path: str
    sha256: str


def load_spreads(root: Path, symbols: set[str]) -> list[SpreadSnapshot]:
    """Read each immutable archive file once; retain only study symbols and provenance."""
    snapshots = []
    for path in day_files(root, recursive=True):
        if path.parent.parent != root:
            continue
        path = day_file_path(path)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            path = day_file_path(path)
            raw = path.read_bytes()
        document = read_day_json(path, raw=raw)
        quotes = {}
        for row in document["symbols"]:
            if row["symbol"] not in symbols:
                continue
            quote = row.get("coverage", {}).get("tradeability", {})
            spread = quote.get("spread_bps")
            if spread is None:
                continue
            spread = D(spread)
            if not spread.is_finite() or spread < ZERO:
                continue
            at = timestamp(quote["quote_at"]) if quote.get("quote_at") else None
            quotes[row["symbol"]] = (spread, at)
        snapshots.append(
            SpreadSnapshot(
                timestamp(document["generated_at"]), quotes, str(path), hashlib.sha256(raw).hexdigest()
            )
        )
    return sorted(snapshots, key=lambda s: (s.at, s.path))


def elapsed_seconds(delta: timedelta) -> Decimal:
    return D(delta.days * 86400 + delta.seconds) + D(delta.microseconds) / 1_000_000


def spread_matches(
    entries: list[Entry], snapshots: list[SpreadSnapshot], data: dict[str, PathData], frozen: Variant
) -> dict[str, dict]:
    """Latest generated snapshot, not latest nonmissing symbol; no future quote or ATR."""
    times = [s.at for s in snapshots]
    matches = {}
    atr_key = (frozen.minutes, frozen.period)
    for e in entries:
        match: dict = dict(key=e.key, symbol=e.symbol, day=e.day, source=e.source, status="no_prior_snapshot")
        matches[e.key] = match
        i = bisect_right(times, e.at) - 1
        if i < 0:
            continue
        snapshot = snapshots[i]
        match.update(
            snapshot=snapshot.path,
            generated_at=snapshot.at,
            snapshot_age_seconds=elapsed_seconds(e.at - snapshot.at),
        )
        if e.symbol not in snapshot.quotes:
            match["status"] = "symbol_spread_missing"
            continue
        spread, quote_at = snapshot.quotes[e.symbol]
        match.update(
            spread_bps=spread,
            quote_at=quote_at,
            quote_age_seconds=elapsed_seconds(e.at - quote_at) if quote_at else None,
        )
        if quote_at is not None and quote_at > snapshot.at:
            match["status"] = "future_quote"
            continue
        known = data[e.symbol].atr_times[atr_key]
        j = bisect_right(known, e.at) - 1
        if j < 0:
            match["status"] = "atr_uninitialized"
            continue
        distance = frozen.k * data[e.symbol].atr[atr_key][known[j]][0]
        if distance <= ZERO:
            match["status"] = "nonpositive_planned_distance"
            continue
        match.update(
            status="usable",
            planned_distance=distance,
            atr_known_at=known[j],
            planned_distance_bps=distance / e.price * BPS,
            spread_distance=e.price * spread / BPS,
            fresh_10m=(
                e.at - snapshot.at <= 10 * MINUTE and quote_at is not None and e.at - quote_at <= 10 * MINUTE
            ),
        )
    return matches


def spread_policy(cohort: list[Entry], retained: list[Entry], exits: dict[str, Exit]) -> dict:
    """Refused opportunities stay cash; unresolved retained paths never become cash."""
    scores = summarize(retained, exits)
    for stats in scores.values():
        stats.update(
            opportunities=len(cohort),
            refused=len(cohort) - len(retained),
            policy_mean_bps=(
                stats["total_pnl_unit_notional"] * BPS / len(cohort)
                if cohort and stats["censored"] == 0
                else None
            ),
        )
    return scores


def spread_study(
    entries: list[Entry], primary: list[Entry], data: dict[str, PathData], frozen: Variant, root: Path
) -> dict:
    snapshots = load_spreads(root, {e.symbol for e in entries})
    matches = spread_matches(entries, snapshots, data, frozen)
    covered = [e for e in primary if matches[e.key]["status"] == "usable"]
    days = sorted({e.day for e in primary})
    base = {e.key: replay(e, data[e.symbol], frozen) for e in covered}
    coverage = {}
    for day in sorted({e.day for e in entries}):
        all_day = [e for e in entries if e.day == day]
        paired = [e for e in primary if e.day == day]
        usable = [matches[e.key] for e in paired if matches[e.key]["status"] == "usable"]
        ages = [m["snapshot_age_seconds"] for m in usable]
        quote_ages = [m["quote_age_seconds"] for m in usable if m["quote_age_seconds"] is not None]
        coverage[day] = dict(
            entries=len(all_day),
            primary=len(paired),
            usable_primary=len(usable),
            all_statuses=dict(Counter(matches[e.key]["status"] for e in all_day)),
            primary_statuses=dict(Counter(matches[e.key]["status"] for e in paired)),
            fresh_10m_primary=sum(m["fresh_10m"] for m in usable),
            snapshot_age_median_seconds=median(ages) if ages else None,
            snapshot_age_max_seconds=max(ages) if ages else None,
            quote_age_median_seconds=median(quote_ages) if quote_ages else None,
            quote_age_max_seconds=max(quote_ages) if quote_ages else None,
            snapshot_older_10m=sum(age > 600 for age in ages),
            quote_older_10m=sum(age > 600 for age in quote_ages),
        )

    def evaluate(retained: list[Entry], exits: dict[str, Exit]) -> dict:
        scores = spread_policy(covered, retained, exits)
        daily = {
            day: spread_policy(
                [e for e in covered if e.day == day], [e for e in retained if e.day == day], exits
            )
            for day in days
        }
        observed_days = sorted({e.day for e in covered})
        loo = {
            day: spread_policy(
                [e for e in covered if e.day != day], [e for e in retained if e.day != day], exits
            )["6"]["policy_mean_bps"]
            for day in observed_days
        }
        eligible = (
            len(observed_days) >= 3
            and scores["6"]["policy_mean_bps"] is not None
            and scores["6"]["policy_mean_bps"] > ZERO
            and all(value is not None and value > ZERO for value in loo.values())
        )
        fresh = [e for e in covered if matches[e.key]["fresh_10m"]]
        fresh_keys = {e.key for e in fresh}
        return dict(
            primary=scores,
            daily=daily,
            leave_one_day_out_stress_bps=loo,
            fresh_10m=spread_policy(fresh, [e for e in retained if e.key in fresh_keys], exits),
            eligible=eligible,
        )

    floors = {}
    for f in (D("0.1"), D("0.25"), D("0.5"), None):
        retained = [
            e
            for e in covered
            if f is None or matches[e.key]["spread_distance"] <= f * matches[e.key]["planned_distance"]
        ]
        floors[str(f) if f is not None else "off"] = evaluate(retained, base)
    trails = {"off": evaluate(covered, base)}
    for m in (D(2), D(3), D(5)):
        adjusted = {
            e.key: replay(e, data[e.symbol], frozen, trail_floor=m * matches[e.key]["spread_distance"])
            for e in covered
        }
        result = evaluate(covered, adjusted)
        result["baseline_trail_exits"] = sum(mark.reason == "chandelier" for mark in base.values())
        result["too_tight_exits"] = sum(
            base[e.key].trail_distance is not None
            and base[e.key].trail_distance < m * matches[e.key]["spread_distance"]
            for e in covered
        )
        result["initial_too_tight_entries"] = sum(
            matches[e.key]["planned_distance"] < m * matches[e.key]["spread_distance"] for e in covered
        )
        result["changed_exits"] = sum(
            (base[e.key].at, base[e.key].price) != (adjusted[e.key].at, adjusted[e.key].price)
            for e in covered
        )
        result["tightness_by_day"] = {
            day: sum(
                base[e.key].trail_distance is not None
                and base[e.key].trail_distance < m * matches[e.key]["spread_distance"]
                for e in covered
                if e.day == day
            )
            for day in days
        }
        trails[str(m)] = result
    return dict(
        frozen=frozen.name,
        execution="Part-1 close-confirmed next-open; entry spread held fixed",
        entry_floor_count=4,
        trail_floor_count=3,
        coverage=coverage,
        entry_floors=floors,
        trail_floors=trails,
        matches=matches,
        snapshots=[dict(path=s.path, generated_at=s.at, sha256=s.sha256) for s in snapshots],
        rule="Positive stressed cash-denominator mean and every leave-day-out; >=3 covered full days",
        recommendation={"f": "INSUFFICIENT_EVIDENCE", "m": "INSUFFICIENT_EVIDENCE"}
        if len({e.day for e in covered}) < 3
        else {
            "f": max(
                (f for f, r in floors.items() if r["eligible"]),
                key=lambda f: floors[f]["primary"]["3"]["policy_mean_bps"],
                default="off",
            ),
            "m": max(
                (m for m, r in trails.items() if r["eligible"]),
                key=lambda m: trails[m]["primary"]["3"]["policy_mean_bps"],
                default="off",
            ),
        },
    )


def run(bars_path: Path, fills_path: Path, owner_path: Path, snapshots: Path | None = None) -> dict:
    bars = load_bars(bars_path)
    fills = read_jsonl(fills_path)
    mu = owner_fill(owner_path)
    if not any(r["order_id"] == mu["order_id"] and r["side"] == "buy" for r in fills):
        fills.append(mu)
    entries, audit = opening_entries(fills, set(bars))
    data = prepare(bars)
    grid = variants()
    results = {v.name: {e.key: replay(e, data[e.symbol], v) for e in entries} for v in grid}
    results["hold_flat"] = {e.key: replay(e, data[e.symbol], None) for e in entries}
    results["actual_fifo"] = {e.key: actual_exit(e, data[e.symbol]) for e in entries}
    # A full-horizon opportunity is defined by bar coverage alone, not variant outcome.
    primary = [e for e in entries if e.day < "2026-10-29" and results["hold_flat"][e.key].price is not None]
    primary_keys = {e.key for e in primary}
    audit["primary_full_horizon_entries"] = len(primary)
    audit["prior_day_entries_excluded_missing_horizon_or_after_flat"] = sum(
        e.day < "2026-10-29" and e.key not in primary_keys for e in entries
    )
    audit["entries_by_day"] = dict(Counter(e.day for e in entries))
    audit["entries_by_source_day"] = dict(Counter(f"{e.day}/{e.source}" for e in entries))
    audit["primary_entries_by_day"] = dict(Counter(e.day for e in primary))
    audit["prior_day_exclusion_reasons"] = dict(
        Counter(
            results["hold_flat"][e.key].reason
            for e in entries
            if e.day < "2026-10-29" and e.key not in primary_keys
        )
    )
    summaries = {}
    for name, exits in results.items():
        periods = {
            "all_observed": entries,
            "primary": primary,
            **{day: [e for e in entries if e.day == day] for day in sorted({e.day for e in entries})},
            **{
                f"primary_{day}": [e for e in primary if e.day == day]
                for day in sorted({e.day for e in primary})
            },
        }
        summaries[name] = {
            period: {
                source: summarize([e for e in subset if source == "combined" or e.source == source], exits)
                for source in ("combined", "strategy", "owner")
            }
            for period, subset in periods.items()
        }
    decision = select(primary, grid, results, summaries)
    frozen = Variant(5, 22, D(3))  # Part-2 sensitivity, never re-optimized by another input sample.
    execution = execution_study(entries, primary, data, frozen)
    rotation = rotation_study(bars, data, frozen)
    spread = spread_study(entries, primary, data, frozen, snapshots) if snapshots is not None else None
    actual_keys = {e.key for e in primary if results["actual_fifo"][e.key].price is not None}
    actual_paired = [e for e in primary if e.key in actual_keys]
    mu_entries = [e for e in entries if e.symbol == "MU" and e.source == "owner"]
    mu_results = {}
    for name, exits in results.items():
        mu_results[name] = []
        for e in mu_entries:
            mark = exits[e.key]
            mu_results[name].append(
                dict(
                    entry=e.key,
                    entry_time=e.at,
                    entry_price=e.price,
                    **asdict(mark),
                    net_bps={
                        str(c): net_return(e, mark.price, c) * BPS if mark.price is not None else None
                        for c in (D(3), D(6))
                    },
                )
            )
    ledger = [
        dict(
            key=e.key,
            symbol=e.symbol,
            day=e.day,
            source=e.source,
            account=e.account,
            at=e.at,
            price=e.price,
            qty=e.qty,
            primary=e.key in primary_keys,
            actual_price=e.actual_price,
            actual_at=e.actual_at,
        )
        for e in entries
    ]
    return dict(
        version=VERSION,
        variant_count=len(grid),
        baseline_count=2,
        inputs={
            str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (bars_path, fills_path, owner_path)
        },
        bar_count=sum(map(len, bars.values())),
        symbols=sorted(bars),
        bar_open_first=min(b.at for rows in bars.values() for b in rows),
        bar_open_last=max(b.at for rows in bars.values() for b in rows),
        available_through=max(b.end for rows in bars.values() for b in rows),
        fill_count=len(fills),
        audit=audit,
        decision=decision,
        summaries=summaries,
        actual_paired={name: summarize(actual_paired, exits) for name, exits in results.items()},
        mu=mu_results,
        entries=ledger,
        execution=execution,
        rotation=rotation,
        spread=spread,
    )


def json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--fills", type=Path, required=True)
    parser.add_argument("--owner", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshots", type=Path, help="Optional point-in-time scanner snapshot archive")
    args = parser.parse_args()
    report = run(args.bars, args.fills, args.owner, args.snapshots)
    args.output.write_text(json.dumps(report, default=json_default, indent=2) + "\n")
    print(
        json.dumps(
            {"output": str(args.output), "audit": report["audit"], "decision": report["decision"]},
            default=json_default,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
