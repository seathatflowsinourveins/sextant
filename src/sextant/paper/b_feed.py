"""B's outside-RTH market data, from alpaca-py's REST latest quote and trade endpoints.

The feed is polled, not streamed: the owner's C lane holds the slot-3 stream, and B only needs
the newest observation for the symbols it actually holds. Pre and post sessions use SIP; the
20:00-04:00 overnight session uses the BOATS feed (Algo Trader Plus), per the pinned Alpaca
24/5 trading and market-data pages read 2026-11-09. The adapter is a pure request/response
boundary, so proofs pass a fake client and never open a socket.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from alpaca.common.enums import Sort
from alpaca.data.enums import DataFeed
from alpaca.data.requests import (
    StockLatestQuoteRequest,
    StockLatestTradeRequest,
    StockQuotesRequest,
)

from sextant.paper.sessions import Session

NS_PER_SECOND = 1_000_000_000
FEEDS = frozenset({"sip", "boats"})


@dataclass(frozen=True, slots=True)
class QuoteObservation:
    """One latest quote, with the latest trade price when the same poll has one."""

    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal | None
    ts_ns: int


@dataclass(frozen=True, slots=True)
class TradeObservation:
    """One latest print."""

    symbol: str
    price: Decimal
    ts_ns: int


@dataclass(frozen=True, slots=True)
class FeedBatch:
    """One poll's fresh observations and the feed that produced them."""

    quotes: tuple[QuoteObservation, ...] = ()
    trades: tuple[TradeObservation, ...] = ()
    feed: str = "none"


class LatestDataClient(Protocol):
    """The two alpaca-py historical-data calls the poller needs; a fake implements this."""

    def get_stock_latest_quote(self, request: StockLatestQuoteRequest) -> Mapping[str, Any]: ...

    def get_stock_latest_trade(self, request: StockLatestTradeRequest) -> Mapping[str, Any]: ...


def feed_for(session: Session) -> str | None:
    """The data feed for a session; None when the native trail owns protection."""

    if session in (Session.PRE, Session.POST):
        return "sip"
    if session is Session.OVERNIGHT:
        return "boats"
    return None


def timestamp_ns(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp()) * NS_PER_SECOND + value.microsecond * 1_000


def _price(value: object) -> Decimal | None:
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not price.is_finite() or price <= 0:
        return None
    return price


class BMarketDataFeed:
    """Poll alpaca-py for the latest quote and trade of the held symbols only.

    Every successful poll returns the standing latest quote, even when its vendor timestamp has
    not changed: the quote is still the market's last bid, and its age is separate from whether
    the poller is alive. A latest print is returned only once, so repeating it cannot count twice
    toward the breach run. Switching feeds restarts the observation sequence so a stale BOATS
    quote is never mistaken for a fresh SIP one.
    """

    def __init__(self, client: LatestDataClient) -> None:
        self._client = client
        self._feed: str | None = None
        self._trade_ts: dict[str, int] = {}
        self._trade_price: dict[str, Decimal] = {}

    def poll(self, symbols: Sequence[str], feed: str) -> FeedBatch:
        if feed not in FEEDS:
            raise ValueError("B's market-data feed must be sip or boats")
        names = tuple(dict.fromkeys(symbol for symbol in symbols if symbol))
        if not names:
            return FeedBatch(feed=feed)
        if feed != self._feed:
            self._feed = feed
            self._trade_ts.clear()
            self._trade_price.clear()
        data_feed = DataFeed(feed)
        quotes = self._client.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=list(names), feed=data_feed)
        )
        trades = self._client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=list(names), feed=data_feed)
        )
        fresh_quotes: list[QuoteObservation] = []
        fresh_trades: list[TradeObservation] = []
        for symbol in names:
            self._observe_trade(symbol, trades.get(symbol), fresh_trades)
            self._observe_quote(symbol, quotes.get(symbol), fresh_quotes)
        return FeedBatch(tuple(fresh_quotes), tuple(fresh_trades), feed)

    def _observe_trade(self, symbol: str, raw: object, fresh: list[TradeObservation]) -> None:
        price = _price(getattr(raw, "price", None))
        at = getattr(raw, "timestamp", None)
        if price is None or not isinstance(at, datetime):
            return
        self._trade_price[symbol] = price
        ts_ns = timestamp_ns(at)
        if ts_ns <= self._trade_ts.get(symbol, -1):
            return
        self._trade_ts[symbol] = ts_ns
        fresh.append(TradeObservation(symbol, price, ts_ns))

    def _observe_quote(self, symbol: str, raw: object, fresh: list[QuoteObservation]) -> None:
        bid = _price(getattr(raw, "bid_price", None))
        ask = _price(getattr(raw, "ask_price", None))
        at = getattr(raw, "timestamp", None)
        if bid is None or ask is None or bid > ask or not isinstance(at, datetime):
            return
        fresh.append(
            QuoteObservation(symbol, bid, ask, self._trade_price.get(symbol), timestamp_ns(at))
        )


class HistoricalQuoteClient(Protocol):
    """The alpaca-py historical-quote call the tape rebuild needs; a fake implements this."""

    def get_stock_quotes(self, request: StockQuotesRequest) -> object: ...


def _row_value(row: object, name: str) -> object:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _datetime_at(ts_ns: int) -> datetime:
    seconds, nanos = divmod(ts_ns, NS_PER_SECOND)
    return datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=nanos // 1_000)


class BHistoricalTape:
    """Read the session's historical quotes between two instants, oldest first."""

    def __init__(self, client: HistoricalQuoteClient) -> None:
        self._client = client

    def quotes(
        self,
        symbol: str,
        start_ns: int,
        end_ns: int,
        feed: str,
    ) -> tuple[QuoteObservation, ...]:
        if feed not in FEEDS:
            raise ValueError("B's historical tape feed must be sip or boats")
        response = self._client.get_stock_quotes(
            StockQuotesRequest(
                symbol_or_symbols=symbol,
                start=_datetime_at(start_ns),
                end=_datetime_at(end_ns),
                feed=DataFeed(feed),
                sort=Sort.ASC,
            )
        )
        data = getattr(response, "data", response)
        rows = data.get(symbol, ()) if isinstance(data, Mapping) else ()
        observations: list[QuoteObservation] = []
        for row in rows:
            bid = _price(_row_value(row, "bid_price"))
            ask = _price(_row_value(row, "ask_price"))
            at = _row_value(row, "timestamp")
            if bid is None or ask is None or bid > ask or not isinstance(at, datetime):
                continue
            observations.append(QuoteObservation(symbol, bid, ask, None, timestamp_ns(at)))
        observations.sort(key=lambda item: item.ts_ns)
        return tuple(observations)
