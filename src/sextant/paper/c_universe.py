"""Rank the tradeable 24/5 universe by ADR-0024's K2 level.

The scanner reads the Alpaca asset snapshot and SIP minute bars only. It never
orders and writes no credentials. ``--session`` changes eligibility, never the
score's official regular-session close.

Upstream checked: alpaca-py@0.44.0:trading/client.py:get_all_assets (raw_data),
alpacahq/alpaca-py@0.44.0 ``cc4cb3b7ba50ae250e621983c2779047fb16bb28``;
[Alpaca 24/5 trading](https://docs.alpaca.markets/us/docs/245-trading-for-trading-api.md),
read 2026-11-09; ADR-0024 K2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path
from time import time_ns
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from alpaca.common.enums import Sort
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.enums import AssetClass, AssetExchange, AssetStatus
from alpaca.trading.requests import GetAssetsRequest
from exchange_calendars import get_calendar

from sextant.data.alpaca_history import (
    decimal_value,
    environment_credentials,
    symbol_name,
    timestamp,
)

ET = ZoneInfo("America/New_York")
SESSIONS = ("overnight", "pre", "rth", "post")
LOOKBACK_SESSIONS = 21
PRIOR_SESSIONS = 20
# Minute bars are heavy and alpaca-py collects every page in memory. A small
# batch bounds peak memory; the total page count is set by the data, not this.
BARS_BATCH = 20


class Trading(Protocol):
    def get_all_assets(self, filter: GetAssetsRequest | None = None) -> Any: ...


class MarketData(Protocol):
    def get_stock_bars(self, request_params: StockBarsRequest) -> Any: ...


@dataclass(slots=True)
class AssetSkips:
    """Count unrecognized listing rows and warn once across a run's scans."""

    count: int = 0
    logged: bool = False

    def record(self, count: int) -> None:
        self.count += count
        if count and not self.logged:
            logging.getLogger(__name__).warning(
                "Skipped %s unrecognized asset rows; cumulative count is in the receipt", count
            )
            self.logged = True


@dataclass(frozen=True, slots=True)
class UniverseSymbol:
    symbol: str
    instrument_id: str
    overnight_tradable: bool


@dataclass(frozen=True, slots=True)
class DailyBar:
    day: date
    close: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class Ranked:
    symbol: str
    instrument_id: str
    score: Decimal
    move: Decimal
    dvol_ratio: Decimal
    overnight_tradable: bool


@dataclass(frozen=True, slots=True)
class Window:
    start: datetime
    end: datetime
    opens: Mapping[date, time]
    closes: Mapping[date, time]


@dataclass(slots=True)
class _Day:
    close: Decimal
    volume: Decimal
    at: datetime


def _field(row: Any, *names: str) -> Any:
    if isinstance(row, Mapping):
        for name in names:
            if name in row:
                return row[name]
        return None
    for name in names:
        value = getattr(row, name, None)
        if value is not None:
            return value
    return None


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _check_session(session: str) -> str:
    if session not in SESSIONS:
        raise ValueError(f"Unsupported session: {session}")
    return session


def _attribute(row: Any, name: str) -> bool:
    """Read the Assets API attribute list the way the live model carries it.

    alpaca-py v0.44.0 has no top-level ``overnight_tradable`` on ``Asset``; the
    response carries the flag inside ``attributes``.
    """
    values = _field(row, "attributes") or ()
    if isinstance(values, str):
        values = (values,)
    return any(str(item).lower() == name for item in values)


def select_universe(
    assets: Iterable[Any], session: str, *, asset_skips: AssetSkips | None = None
) -> list[UniverseSymbol]:
    """Keep active, tradeable NMS symbols; the US_EQUITY class already excludes OTC."""
    _check_session(session)
    chosen: dict[str, UniverseSymbol] = {}
    skipped = 0
    for asset in assets:
        try:
            AssetExchange(_enum_value(_field(asset, "exchange")))
            AssetStatus(_enum_value(_field(asset, "status")))
            AssetClass(_enum_value(_field(asset, "asset_class", "class")))
            if not isinstance(_field(asset, "tradable"), bool):
                raise ValueError("unknown tradability")
            symbol = symbol_name(_field(asset, "symbol"))
            instrument_id = _field(asset, "id")
            if not isinstance(instrument_id, (str, UUID)) or not str(instrument_id):
                raise ValueError("missing asset identity")
            attributes = _field(asset, "attributes")
            if attributes is not None and (
                not isinstance(attributes, list)
                or any(not isinstance(value, str) for value in attributes)
            ):
                raise ValueError("unknown attributes")
            for flag in ("overnight_tradable", "overnight_halted"):
                value = _field(asset, flag)
                if value is not None and not isinstance(value, bool):
                    raise ValueError("unknown overnight eligibility")
        except (TypeError, ValueError):
            skipped += 1
            continue
        if _enum_value(_field(asset, "status")) != AssetStatus.ACTIVE.value:
            continue
        if _enum_value(_field(asset, "asset_class", "class")) != AssetClass.US_EQUITY.value:
            continue
        if _field(asset, "tradable") is not True:
            continue
        overnight_tradable = _field(asset, "overnight_tradable") is True or _attribute(
            asset, "overnight_tradable"
        )
        if session == "overnight":
            if not overnight_tradable:
                continue
            if _field(asset, "overnight_halted") is True or _attribute(asset, "overnight_halted"):
                continue
        chosen[symbol] = UniverseSymbol(symbol, str(instrument_id), overnight_tradable)
    (asset_skips if asset_skips is not None else AssetSkips()).record(skipped)
    return sorted(chosen.values(), key=lambda row: row.symbol)


@cache
def _calendar(today: date):
    return get_calendar("XNYS", start=today - timedelta(days=60), end=today, side="left")


def _window(now: datetime) -> Window | None:
    if now.tzinfo is None:
        raise ValueError("Scanner clock must carry a timezone")
    local = now.astimezone(ET)
    today = local.date()
    calendar = _calendar(today)
    sessions = list(calendar.sessions_in_range(today - timedelta(days=60), today))
    if not sessions:
        return None
    if sessions[-1].date() == today and local < calendar.session_open(sessions[-1]).to_pydatetime():
        sessions.pop()
    sessions = sessions[-LOOKBACK_SESSIONS:]
    if not sessions:
        return None
    start = calendar.session_open(sessions[0]).to_pydatetime()
    end = min(local, calendar.session_close(sessions[-1]).to_pydatetime())
    opens = {
        session.date(): calendar.session_open(session).tz_convert(ET).time() for session in sessions
    }
    closes = {
        session.date(): calendar.session_close(session).tz_convert(ET).time()
        for session in sessions
    }
    return Window(start, end, opens, closes)


def fetch_bars(data: MarketData, symbols: Sequence[str], window: Window) -> dict[str, list[Any]]:
    result: dict[str, list[Any]] = {}
    for offset in range(0, len(symbols), BARS_BATCH):
        batch = list(symbols[offset : offset + BARS_BATCH])
        request = StockBarsRequest(
            symbol_or_symbols=batch,
            timeframe=TimeFrame(1, TimeFrameUnit("Min")),
            start=window.start,
            end=window.end,
            feed=DataFeed.SIP,
            adjustment=Adjustment.SPLIT,
            sort=Sort.ASC,
        )
        response = data.get_stock_bars(request)
        body = getattr(response, "data", response)
        for symbol in batch:
            bars = body.get(symbol) if isinstance(body, Mapping) else None
            result[symbol] = list(bars or ())
    return result


def _day_bars(bars: Iterable[Any], window: Window) -> list[DailyBar] | None:
    """One official regular-session close and volume per New York trade date."""
    days: dict[date, _Day] = {}
    for bar in bars:
        try:
            at = timestamp(bar.timestamp).astimezone(ET)
        except (AttributeError, TypeError, ValueError):
            return None
        day = at.date()
        if day not in window.opens:
            continue
        if not window.opens[day] <= at.time() < window.closes[day]:
            continue
        try:
            close = decimal_value(bar.close)
            volume = decimal_value(bar.volume)
        except (AttributeError, InvalidOperation, TypeError, ValueError):
            return None
        if not close.is_finite() or not volume.is_finite() or close <= 0 or volume < 0:
            return None
        current = days.get(day)
        if current is None:
            days[day] = _Day(close, volume, at)
        elif at == current.at:
            return None
        else:
            current.volume += volume
            if at > current.at:
                current.close = close
                current.at = at
    if not days:
        return None
    return [DailyBar(day, value.close, value.volume) for day, value in sorted(days.items())]


def _level(bars: Sequence[DailyBar]) -> tuple[Decimal, Decimal, Decimal] | None:
    recent = list(bars[-LOOKBACK_SESSIONS:])
    if len(recent) < 2:
        return None
    latest = recent[-1]
    prior = recent[:-1][-PRIOR_SESSIONS:]
    if not prior:
        return None
    prior_close = prior[-1].close
    if prior_close <= 0:
        return None
    mean_volume = sum((row.volume for row in prior), Decimal(0)) / Decimal(len(prior))
    if mean_volume <= 0:
        return None
    move = latest.close / prior_close - 1
    dvol_ratio = latest.volume / mean_volume
    score = move * dvol_ratio
    if not all(value.is_finite() for value in (move, dvol_ratio, score)):
        return None
    return score, move, dvol_ratio


def rank_universe(
    trading: Trading,
    data: MarketData,
    session: str,
    *,
    now: datetime | None = None,
    asset_skips: AssetSkips | None = None,
) -> list[Ranked]:
    _check_session(session)
    request = GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY)
    universe = select_universe(trading.get_all_assets(request), session, asset_skips=asset_skips)
    rows: list[Ranked] = []
    if not universe:
        return rows
    window = _window(now or datetime.now(tz=ET))
    if window is None:
        return rows
    bars_by_symbol = fetch_bars(data, [row.symbol for row in universe], window)
    for symbol in universe:
        bars = _day_bars(bars_by_symbol.get(symbol.symbol, ()), window)
        if bars is None:
            continue
        level = _level(bars)
        if level is None:
            continue
        score, move, dvol_ratio = level
        rows.append(
            Ranked(
                symbol.symbol,
                symbol.instrument_id,
                score,
                move,
                dvol_ratio,
                symbol.overnight_tradable,
            )
        )
    rows.sort(key=lambda row: (-row.score, row.symbol))
    return rows


def _decimal_string(value: Decimal) -> str:
    return format(value, "f")


def row_payload(row: Ranked) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "instrument_id": row.instrument_id,
        "score": _decimal_string(row.score),
        "move": _decimal_string(row.move),
        "dvol_ratio": _decimal_string(row.dvol_ratio),
        "overnight_tradable": row.overnight_tradable,
    }


def canonical_rows(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def build_payload(session: str, generated_ns: int, rows: Sequence[Ranked]) -> dict[str, Any]:
    body = [row_payload(row) for row in rows]
    return {
        "session": session,
        "generated_ns": generated_ns,
        "rows": body,
        "sha256": hashlib.sha256(canonical_rows(body)).hexdigest(),
    }


def scan(
    trading: Trading,
    data: MarketData,
    session: str,
    *,
    limit: int | None = None,
    now: datetime | None = None,
    generated_ns: int | None = None,
) -> dict[str, Any]:
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    asset_skips = AssetSkips()
    rows = rank_universe(trading, data, session, now=now, asset_skips=asset_skips)
    if limit is not None:
        rows = rows[:limit]
    return {
        **build_payload(session, time_ns() if generated_ns is None else generated_ns, rows),
        "asset_rows_skipped": asset_skips.count,
    }


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("limit must be an integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError("limit must be positive")
    return number


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rank paper lane C's 24/5 universe.")
    parser.add_argument("--out", type=Path, required=True, help="JSON artifact path")
    parser.add_argument("--session", choices=SESSIONS, default="rth")
    parser.add_argument("--limit", type=_positive_int, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    key, secret = environment_credentials()
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient

    trading = TradingClient(key, secret, paper=True, raw_data=True)
    data = StockHistoricalDataClient(key, secret)
    payload = scan(trading, data, args.session, limit=args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
