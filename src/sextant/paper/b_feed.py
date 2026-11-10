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
from alpaca.data.models.quotes import Quote
from alpaca.data.requests import (
    StockLatestQuoteRequest,
    StockLatestTradeRequest,
    StockQuotesRequest,
)
from requests.adapters import HTTPAdapter

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
    """One alpaca-py REST GET (common/rest.py:212); a fake implements this."""

    def get(self, path: str, data: dict[str, Any], /) -> object: ...


class TapeShapeError(ValueError):
    """A historical response that is not the requested symbol's quotes, or one over its bound."""


class BoundedAdapter(HTTPAdapter):
    """requests' transport adapter with one connect and read timeout on every send."""

    def __init__(self, timeout_s: float) -> None:
        super().__init__()
        self._timeout_s = timeout_s

    def send(
        self,
        request: Any,
        stream: bool = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> Any:
        return super().send(request, stream, self._timeout_s, verify, cert, proxies)


def bound_transport(client: object, timeout_s: Decimal) -> None:
    """Give an alpaca-py REST client a transport timeout and no internal retries.

    alpaca-py v0.44.0 keeps its requests session in ``_session`` (common/rest.py:69) and
    retries a 429 or 504 ``_retry`` times with a sleep (rest.py:72,127-134,201); its
    constructor ignores ``retry_attempts=0``, so the start read sets ``_retry`` to zero.
    """

    session = getattr(client, "_session", None)
    if session is None or not hasattr(client, "_retry"):
        raise TypeError("the historical client exposes no requests session to bound")
    client._retry = 0  # type: ignore[attr-defined]
    adapter = BoundedAdapter(float(timeout_s))
    session.mount("https://", adapter)
    session.mount("http://", adapter)


def _datetime_at(ts_ns: int) -> datetime:
    seconds, nanos = divmod(ts_ns, NS_PER_SECOND)
    return datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=nanos // 1_000)


class BHistoricalTape:
    """Read one page of one symbol's quotes between two instants: one page, one HTTP request.

    The request is the one alpaca-py's ``get_stock_quotes`` sends (``/stocks/quotes`` with
    ``StockQuotesRequest.to_request_fields()``, data/historical/stock.py:98-118), sent once
    through ``RESTClient.get`` so that one pacer admission is one request (N1). The caller
    follows the continuation token as the SDK's page loop does (common/rest.py:381,388,398:
    ``page_token`` in, ``next_page_token`` out), one request per page (R1). Pages come newest
    first (``sort``, alpaca-py 0.44.0 data/requests.py:40; common/enums.py:36-38), so a read
    that stops early holds the most recent rows (R4). Completeness is judged on the raw JSON
    before ``QuoteSet`` drops null rows (N3): a response without the symbol's ``quotes``, a
    null or malformed row, a non-text token or a page over ``max_quotes`` raises
    ``TapeShapeError``. A symbol absent from ``quotes`` is an empty page.
    """

    def __init__(self, client: HistoricalQuoteClient, max_quotes: int) -> None:
        if max_quotes < 1:
            raise ValueError("the tape's quote bound must be positive")
        self._client = client
        self._max_quotes = max_quotes

    def quote_page(
        self,
        symbol: str,
        start_ns: int,
        end_ns: int,
        feed: str,
        page_token: str | None = None,
    ) -> tuple[tuple[QuoteObservation, ...], str | None]:
        if feed not in FEEDS:
            raise ValueError("B's historical tape feed must be sip or boats")
        request = StockQuotesRequest(
            symbol_or_symbols=symbol,
            start=_datetime_at(start_ns),
            end=_datetime_at(end_ns),
            feed=DataFeed(feed),
            sort=Sort.DESC,
            limit=self._max_quotes,
        )
        fields = request.to_request_fields()
        if page_token is not None:
            fields["page_token"] = page_token
        response = self._client.get("/stocks/quotes", fields)
        data = response.get("quotes") if isinstance(response, Mapping) else None
        if (
            not isinstance(response, Mapping)
            or not isinstance(data, Mapping)
            or set(data) - {symbol}
        ):
            raise TapeShapeError(f"the {feed} response is not {symbol}'s quotes")
        rows = data.get(symbol, [])
        if not isinstance(rows, Sequence) or len(rows) > self._max_quotes:
            raise TapeShapeError(f"the {feed} page is malformed or over its quote bound")
        token = response.get("next_page_token")
        if token is not None and (not isinstance(token, str) or not token):
            raise TapeShapeError(f"the {feed} page has a malformed continuation token")
        observations: list[QuoteObservation] = []
        for raw in rows:
            if not isinstance(raw, Mapping) or not {"t", "bp", "ap"} <= set(raw):
                raise TapeShapeError(f"a {feed} row has no bid, ask and timestamp")
            row = Quote(symbol, dict(raw))
            # A non-positive side is a one-sided quote; skip it as the live poller does.
            bid, ask = _price(row.bid_price), _price(row.ask_price)
            if bid is not None and ask is not None and bid <= ask:
                observations.append(
                    QuoteObservation(symbol, bid, ask, None, timestamp_ns(row.timestamp))
                )
        return tuple(observations), token
