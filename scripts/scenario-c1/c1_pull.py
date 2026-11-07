"""C1 acquisition: SIP 1-minute bars, trades and quotes into ONE ParquetDataCatalog.

Every request goes through `sextant.data.alpaca_history.AlpacaHistory` (raw response texts,
upstream pagination), slot ALPACA_PAPER_3 only, capped at 150 requests/minute. Bars keep the
house raw envelope and provenance (`CatalogStore.write`); trades and quotes land beside it and
are written with the engine's typed catalog API at the same wall clock (`ts_init = ts_event`).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator, Sequence
from datetime import date, datetime, time as daytime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import pyarrow as pa
import pyarrow.parquet as pq
from alpaca.common.enums import Sort
from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockQuotesRequest, StockTradesRequest
from alpaca.data.historical.corporate_actions import CorporateActionsClient
from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import CorporateActionsRequest, NewsRequest
from nautilus_trader.model import (
    AggressorSide,
    InstrumentId,
    Price,
    Quantity,
    QuoteTick,
    TradeId,
    TradeTick,
)
from nautilus_trader.persistence import ParquetDataCatalog

from sextant.data.alpaca_history import (
    NY,
    AlpacaHistory,
    day_start,
    land_raw,
    nanos,
    raw_path,
    read_raw,
    timestamp,
)
from sextant.data.catalog import CatalogStore, decode_bars, equity

ROOT = Path.home() / "sextant-data" / "c1-scenario"
CATALOG = ROOT / "catalog"
RAW = ROOT / "raw"

CALENDAR = xcals.get_calendar("XNYS")
CALLS_PER_MINUTE = Decimal("150")


def sessions(start: date, end: date) -> list[date]:
    return [stamp.date() for stamp in CALENDAR.sessions_in_range(start.isoformat(), end.isoformat())]


# 14 completed sessions before each case day, the case day, and its continuation.
PARA_DAYS = sessions(date(2026, 10, 13), date(2026, 11, 4))
SPCX_DAYS = sessions(date(2026, 10, 1), date(2026, 10, 22))
BARS_PLAN: dict[str, list[date]] = {"PARA": PARA_DAYS, "SPCX": SPCX_DAYS}
TICK_DAYS: list[tuple[str, date]] = [
    ("PARA", date(2026, 10, 27)),
    ("PARA", date(2026, 11, 3)),
    ("PARA", date(2026, 11, 4)),
    ("SPCX", date(2026, 10, 21)),
    ("SPCX", date(2026, 10, 22)),
]


def window(day: date) -> tuple[datetime, datetime]:
    """04:00-20:00 America/New_York, the extended session, inclusive bounds."""
    return (
        datetime.combine(day, daytime(4, 0), tzinfo=NY),
        datetime.combine(day, daytime(20, 0), tzinfo=NY),
    )


def bar_window(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    start, end = None, None
    for row in rows:
        moment = timestamp(row["t"]).astimezone(NY)
        if not daytime(4, 0) <= moment.time() <= daytime(20, 0):
            raise ValueError(f"bar outside 04:00-20:00: {row['t']}")
        start = start or moment
        end = moment
    return list(rows)


def land_ticks(path: Path, pages: Sequence[str], *, kind: str, symbol: str, day: date) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return False
    metadata = {
        "source": "alpaca_sip",
        "feed": "sip",
        "adjustment": "raw",
        "kind": kind,
        "symbol": symbol,
        "date": day.isoformat(),
        "asof": day.isoformat(),
    }
    table = pa.table({"page": list(range(len(pages))), "response_json": list(pages)})
    table = table.replace_schema_metadata(
        {key.encode(): value.encode() for key, value in metadata.items()}
    )
    pq.write_table(table, path)
    return True


def page_rows(path: Path, key: str) -> Iterator[dict[str, Any]]:
    table = pq.read_table(path, columns=["response_json"])
    for text in table["response_json"].to_pylist():
        payload = json.loads(text)
        for row in (payload[key] or {}).get(path.stem, []):
            yield row


def tick_pages(
    client: AlpacaHistory, symbol: str, day: date, kind: str
) -> tuple[str, ...]:
    start, end = window(day)
    if kind == "trades":
        request: Any = StockTradesRequest(
            symbol_or_symbols=symbol,
            start=start,
            end=end,
            feed=DataFeed.SIP,
            sort=Sort.ASC,
            asof=day.isoformat(),
        )
        client.pages = []
        client.get_stock_trades(request)
    else:
        request = StockQuotesRequest(
            symbol_or_symbols=symbol,
            start=start,
            end=end,
            feed=DataFeed.SIP,
            sort=Sort.ASC,
            asof=day.isoformat(),
        )
        client.pages = []
        client.get_stock_quotes(request)
    return tuple(client.pages)


def ticks_from_rows(
    rows: Sequence[dict[str, Any]], symbol: str, kind: str
) -> tuple[list[TradeTick] | list[QuoteTick], int]:
    instrument_id = InstrumentId.from_str(f"{symbol}.ALPACA")
    out: list[Any] = []
    skipped = 0
    for row in rows:
        moment = nanos(timestamp(row["t"]))
        if kind == "trades":
            price, size = Decimal(str(row["p"])), int(row["s"])
            if price <= 0 or size <= 0:
                skipped += 1
                continue
            out.append(
                TradeTick(
                    instrument_id=instrument_id,
                    price=Price.from_str(f"{price:.9f}"),
                    size=Quantity.from_int(size),
                    aggressor_side=AggressorSide.NO_AGGRESSOR,
                    trade_id=TradeId(str(row.get("c", "")) or f"t-{moment}"),
                    ts_event=moment,
                    ts_init=moment,
                )
            )
        else:
            bid, ask = Decimal(str(row["bp"])), Decimal(str(row["ap"]))
            bid_size, ask_size = int(row["bs"]), int(row["as"])
            if bid <= 0 or ask <= 0 or bid_size < 0 or ask_size < 0:
                skipped += 1
                continue
            out.append(
                QuoteTick(
                    instrument_id=instrument_id,
                    bid_price=Price.from_str(f"{bid:.9f}"),
                    ask_price=Price.from_str(f"{ask:.9f}"),
                    bid_size=Quantity.from_int(bid_size),
                    ask_size=Quantity.from_int(ask_size),
                    ts_event=moment,
                    ts_init=moment,
                )
            )
    return out, skipped


def catalog() -> ParquetDataCatalog:
    return ParquetDataCatalog(str(CATALOG.resolve()))


def ensure_instrument(store: ParquetDataCatalog, symbol: str) -> None:
    if not store.instruments(instrument_ids=[f"{symbol}.ALPACA"]):
        store.write_instruments([equity(symbol)])


def flush(store: ParquetDataCatalog, buffer: list[Any]) -> int:
    if not buffer:
        return 0
    if isinstance(buffer[0], TradeTick):
        store.write_trade_ticks(buffer)
    elif isinstance(buffer[0], QuoteTick):
        store.write_quote_ticks(buffer)
    else:
        raise TypeError(f"unsupported tick type {type(buffer[0])}")
    count = len(buffer)
    buffer.clear()
    return count


def cmd_plan(_: argparse.Namespace) -> int:
    print(json.dumps(
        {
            "bars": {symbol: [day.isoformat() for day in days] for symbol, days in BARS_PLAN.items()},
            "bar_requests": sum(len(days) for days in BARS_PLAN.values()),
            "tick_days": [[symbol, day.isoformat()] for symbol, day in TICK_DAYS],
        },
        indent=2,
    ))
    return 0


def cmd_bars(args: argparse.Namespace) -> int:
    store, client = CatalogStore(CATALOG), AlpacaHistory(CALLS_PER_MINUTE)
    try:
        for symbol, days in BARS_PLAN.items():
            for day in days:
                path = raw_path(RAW, "1min", symbol, day)
                pages = client.fetch(symbol, day, "1min")
                land_raw(path, pages, symbol=symbol, day=day, bar="1min")
                rows = bar_window(read_raw(path))
                bars = decode_bars(rows, symbol, "1min")
                status = store.write(symbol, bars, raw_partition=path)
                start, end = window(day)
                print(
                    json.dumps(
                        {
                            "symbol": symbol,
                            "day": day.isoformat(),
                            "pages": len(pages),
                            "bars": len(bars),
                            "status": status,
                            "start": start.isoformat(),
                            "end": end.isoformat(),
                        }
                    ),
                    flush=True,
                )
    finally:
        client.close()
    return 0


def cmd_ticks(args: argparse.Namespace) -> int:
    kind = args.kind
    store, client = catalog(), AlpacaHistory(CALLS_PER_MINUTE)
    total_pages = total_rows = total_skipped = 0
    try:
        for symbol, day in TICK_DAYS:
            if args.only and f"{symbol}:{day.isoformat()}" != args.only:
                continue
            ensure_instrument(store, symbol)
            path = RAW / "alpaca_sip" / kind / symbol / f"{day.isoformat()}.parquet"
            if path.exists():
                table = pq.read_table(path, columns=["response_json"])
                pages = tuple(table["response_json"].to_pylist())
                print(json.dumps({"reused": str(path), "pages": len(pages)}), flush=True)
            else:
                pages = tick_pages(client, symbol, day, kind)
                land_ticks(path, pages, kind=kind, symbol=symbol, day=day)
            buffer: list[Any] = []
            day_rows = day_skipped = 0
            for page in pages:
                rows = (json.loads(page)[kind] or {}).get(symbol, [])
                ticks, skipped = ticks_from_rows(rows, symbol, kind)
                buffer.extend(ticks)
                day_rows += len(ticks)
                day_skipped += skipped
                if len(buffer) >= 250_000:
                    flush(store, buffer)
            flush(store, buffer)
            total_pages += len(pages)
            total_rows += day_rows
            total_skipped += day_skipped
            print(
                json.dumps(
                    {
                        "kind": kind,
                        "symbol": symbol,
                        "day": day.isoformat(),
                        "pages": len(pages),
                        "ticks": day_rows,
                        "skipped": day_skipped,
                    }
                ),
                flush=True,
            )
    finally:
        client.close()
    print(
        json.dumps({"kind": kind, "pages": total_pages, "ticks": total_rows, "skipped": total_skipped})
    )
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    client = AlpacaHistory(CALLS_PER_MINUTE)
    day = date.fromisoformat(args.day)
    start = datetime.combine(day, daytime(9, 30), tzinfo=NY)
    end = start + timedelta(minutes=1)
    try:
        request = StockQuotesRequest(
            symbol_or_symbols=args.symbol,
            start=start,
            end=end,
            feed=DataFeed.SIP,
            sort=Sort.ASC,
            asof=day.isoformat(),
        )
        client.pages = []
        client.get_stock_quotes(request)
        pages = tuple(client.pages)
    finally:
        client.close()
    rows = sum(len((json.loads(page)["quotes"] or {}).get(args.symbol, [])) for page in pages)
    first = last = None
    for page in pages:
        payload = json.loads(page)["quotes"].get(args.symbol, [])
        if payload:
            first = first or payload[0]["t"]
            last = payload[-1]["t"]
    span = (
        (timestamp(last) - timestamp(first)).total_seconds() if first and last else 0.0
    )
    print(
        json.dumps(
            {
                "symbol": args.symbol,
                "day": day.isoformat(),
                "pages": len(pages),
                "rows": rows,
                "first": first,
                "last": last,
                "span_s": span,
                "rows_per_s": (rows / span) if span else None,
            }
        )
    )
    return 0


def cmd_actions(args: argparse.Namespace) -> int:
    key, secret = __import__("os").environ["APCA_API_KEY_ID"], __import__("os").environ[
        "APCA_API_SECRET_KEY"
    ]
    client = CorporateActionsClient(api_key=key, secret_key=secret)
    request = CorporateActionsRequest(
        symbols=[args.symbol],
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        types=["reverse_split", "forward_split"],
    )
    payload = client.get_corporate_actions(request)
    raw = payload if isinstance(payload, dict) else payload.model_dump(mode="json")
    path = ROOT / "corporate-actions" / f"{args.symbol}-{args.start}-{args.end}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2, sort_keys=True, default=str))
    print(json.dumps({"path": str(path), "payload": raw}, default=str))
    return 0


def cmd_news(args: argparse.Namespace) -> int:
    key, secret = __import__("os").environ["APCA_API_KEY_ID"], __import__("os").environ[
        "APCA_API_SECRET_KEY"
    ]
    client = NewsClient(api_key=key, secret_key=secret)
    start = datetime.fromisoformat(args.start).replace(tzinfo=NY)
    end = datetime.fromisoformat(args.end).replace(tzinfo=NY)
    token = None
    items: list[dict[str, Any]] = []
    pages = 0
    while pages < 5:
        request = NewsRequest(
            symbols=args.symbol,
            start=start,
            end=end,
            limit=50,
            page_token=token,
            exclude_contentless=True,
        )
        page = client.get_news(request)
        payload = page.model_dump(mode="json") if hasattr(page, "model_dump") else dict(page)
        batch = payload.get("news") or []
        items.extend(batch)
        pages += 1
        token = payload.get("next_page_token")
        print(json.dumps({"page": pages, "items": len(batch), "next": bool(token)}), flush=True)
        if not token:
            break
    path = ROOT / "news" / f"{args.symbol}-{args.start}-{args.end}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": items}, indent=2, sort_keys=True, default=str))
    print(json.dumps({"path": str(path), "items": len(items), "pages": pages}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan").set_defaults(func=cmd_plan)
    sub.add_parser("bars").set_defaults(func=cmd_bars)
    ticks = sub.add_parser("ticks")
    ticks.add_argument("kind", choices=["trades", "quotes"])
    ticks.add_argument("--only", default=None)
    ticks.set_defaults(func=cmd_ticks)
    probe = sub.add_parser("probe")
    probe.add_argument("symbol")
    probe.add_argument("day")
    probe.set_defaults(func=cmd_probe)
    actions = sub.add_parser("actions")
    actions.add_argument("symbol")
    actions.add_argument("start")
    actions.add_argument("end")
    actions.set_defaults(func=cmd_actions)
    news = sub.add_parser("news")
    news.add_argument("symbol")
    news.add_argument("start")
    news.add_argument("end")
    news.set_defaults(func=cmd_news)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
