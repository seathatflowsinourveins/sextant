"""Live Alpaca trades and quotes as native ticks for the paper runner: SIP streamed, BOATS polled.

Source: https://docs.alpaca.markets/docs/real-time-stock-pricing-data (read 2026-11-09);
alpaca-py==0.44.0 ``StockDataStream``. The conversion follows the pinned
northstar-trading adapter registered in the manifest's "Live Alpaca SIP tick feed"
row (``src/nautilus_alpaca/streams.py``).

Overnight (20:00-04:00 ET) the C lane needs BOATS, which alpaca-py 0.44's ``StockDataStream``
refuses, so ``feed="boats"`` polls REST ``get_stock_trades``/``get_stock_quotes`` with
``DataFeed.BOATS`` (Alpaca 24/5 trading and Market Data docs, read 2026-11-09) in the merged
``b_feed.py`` shape: one batched trades and one batched quotes request per poll over a
``2 * overlap_s`` window, each re-fetched print dropped. ``poll_interval_s`` defaults to the
registry's ``feed_poll_interval_s`` (``lanes/paper/b-parameters.json``, 1 s, UNCALIBRATED),
the shared REST polling cadence, not a B-scoped strategy parameter.

An optional read-only ``FeedTap`` counts handler entries and writes one JSON line
per wall-clock second; with no tap nothing here changes.

The feed only converts market data. It places no order, reads no key from the
environment or a file (the injected factories receive the pair), and adds no
reconnect or retry policy: the runner owns the feed's lifecycle. rc8's
``TradeTick`` has no conditions or tape field, so those vendor fields cannot ride the
tick; the pinned adapter likewise keeps only exchange and trade id in its stable
``TradeId``. The C-lane reads conditions separately. ``ts_event`` keeps the vendor
timestamp; ``ts_init`` comes from the local receipt clock.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from alpaca.data.enums import DataFeed
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.models.quotes import Quote
from alpaca.data.models.trades import Trade
from alpaca.data.requests import StockQuotesRequest, StockTradesRequest
from nautilus_trader.model import (
    AggressorSide,
    InstrumentId,
    Price,
    Quantity,
    QuoteTick,
    TradeId,
    TradeTick,
)

from sextant.paper.feed_tap import FeedTap

__all__ = ["AlpacaTickFeed"]

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SIP = "sip"
_BOATS = "boats"
_NS_PER_S = 1_000_000_000
_TRADE_ID_MAX = 36
# Alpaca's SIP quote schema reports bid_size/ask_size in round lots, not shares:
# https://docs.alpaca.markets/docs/real-time-stock-pricing-data (read 2026-11-09),
# "ask size in round lots" / "bid size in round lots". alpaca-py 0.44.0
# alpaca.data.models.quotes.Quote carries the raw bs/as fields.
_ROUND_LOT_SHARES = 100


class Instrument(Protocol):
    """The rc8 surface this feed reads; rc8 exports no shared instrument base."""

    @property
    def id(self) -> InstrumentId: ...

    @property
    def price_precision(self) -> int: ...


def _decimal(value: float | int | Decimal) -> Decimal:
    """Build a decimal from the vendor's float text, never from float arithmetic."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _timestamp_ns(value: datetime) -> int:
    """Return integer epoch nanoseconds; Python timestamps carry microseconds."""
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("vendor timestamp must be timezone-aware")
    delta = value.astimezone(UTC) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def _quantity(value: float, label: str, *, lot_size: int = 1) -> Quantity:
    decimal = _decimal(value)
    if not decimal.is_finite() or decimal != decimal.to_integral_value():
        raise ValueError(f"{label} must be a whole count")
    return Quantity.from_int(int(decimal) * lot_size)


def _price(value: float, precision: int) -> Price:
    return Price.from_decimal_dp(_decimal(value), precision)


def _rows(payload: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """Raw ``{symbol: [row, ...]}`` pairs, skipping null rows as alpaca-py's TradeSet does."""
    return [(symbol, row) for symbol, rows in payload.items() for row in rows if row is not None]


class AlpacaTickFeed:
    """Convert SIP stream or BOATS REST trades and quotes into the C-lane's Nautilus ticks.

    The constructor validates credentials, the feed and the cadence but performs no network
    I/O and calls no factory. ``start()`` either subscribes every instrument's bare Alpaca
    symbol on a SIP stream and runs alpaca-py's blocking loop, or polls BOATS until ``stop()``.
    """

    def __init__(
        self,
        instruments: Mapping[str, Instrument],
        *,
        on_trade: Callable[[TradeTick], None],
        on_quote: Callable[[QuoteTick], None],
        api_key: str = "",
        secret_key: str = "",
        feed: str = _SIP,
        stream_factory: Callable[..., StockDataStream] = StockDataStream,
        poll_interval_s: float = 1.0,  # registry feed_poll_interval_s, UNCALIBRATED
        overlap_s: float = 5.0,
        data_client_factory: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.time,
        tap: FeedTap | None = None,
    ) -> None:
        if not api_key or not secret_key:
            raise ValueError("Alpaca key and secret are required")
        if feed not in (_SIP, _BOATS):
            raise ValueError(f"paper arming uses SIP, or BOATS overnight; {feed!r} is refused")
        if tap is not None and feed == _BOATS:
            raise ValueError("the read-only feed tap measures the SIP socket, not BOATS polls")
        if not 0 < poll_interval_s < 2 * overlap_s:
            raise ValueError("poll_interval_s must be positive and inside the 2 * overlap_s window")

        by_symbol: dict[str, Instrument] = {}
        for key, instrument in instruments.items():
            if key != str(instrument.id):
                raise ValueError(f"instrument key {key!r} does not match {instrument.id}")
            if str(instrument.id.venue) != "ALPACA":
                raise ValueError("Alpaca tick feed requires .ALPACA instruments")
            symbol = instrument.id.symbol.value
            if symbol in by_symbol:
                raise ValueError(f"duplicate instrument symbol {symbol}")
            by_symbol[symbol] = instrument

        self._instruments = by_symbol
        self._on_trade = on_trade
        self._on_quote = on_quote
        self._api_key = api_key
        self._secret_key = secret_key
        self._stream_factory = stream_factory
        self._stream: StockDataStream | None = None
        self._feed = feed
        self._poll_interval_s = poll_interval_s
        self._overlap_s = overlap_s
        self._data_client_factory = data_client_factory or StockHistoricalDataClient
        self._clock = clock
        self._client: Any = None
        self._stopped = threading.Event()
        self._seen: dict[tuple[object, ...], int] = {}
        self._horizon_ns = 0
        self._tap = tap
        self.failure: Exception | None = None

    def start(self) -> None:
        """Run the SIP stream's blocking loop, or poll BOATS until ``stop()``."""
        if self._stream is not None or self._client is not None:
            raise RuntimeError("Alpaca tick feed already started")
        if self._feed == _BOATS:
            self._poll_until_stopped()
            return

        if self._tap is not None:
            self._tap.start()
        try:
            stream = self._stream_factory(self._api_key, self._secret_key, feed=DataFeed.SIP)
            self._stream = stream
            symbols = tuple(sorted(self._instruments))
            stream.subscribe_trades(self._handle_trade, *symbols)
            stream.subscribe_quotes(self._handle_quote, *symbols)
            stream.run()
        except Exception as exc:
            self._observe_failure()
            if self.failure is None:
                self.failure = exc
            raise
        finally:
            # run() has returned, so no handler is mid-flight: finalize on this thread.
            if self._tap is not None:
                self._tap.stop()

    def stop(self) -> None:
        """Wake the BOATS poll loop, or delegate alpaca-py's cross-thread stream stop."""
        self._stopped.set()
        stream = self._stream
        if stream is None:
            return
        try:
            stream.stop()
        except AttributeError:
            # DataStream.stop() reads self._loop, which run() sets in _run_forever.
            return

    def _poll_until_stopped(self) -> None:
        client = self._data_client_factory(
            api_key=self._api_key, secret_key=self._secret_key, raw_data=True
        )
        self._client = client
        try:
            while not self._stopped.is_set():
                self._poll(client)
                self._stopped.wait(self._poll_interval_s)
        except Exception as exc:
            if self.failure is None:
                self.failure = exc
            raise

    def _poll(self, client: Any) -> None:
        """One batched trades and one batched quotes request; deliver each new print once."""
        now = self._clock()
        start = datetime.fromtimestamp(now - 2 * self._overlap_s, UTC)
        window: dict[str, Any] = {
            "symbol_or_symbols": sorted(self._instruments),
            "start": start,
            "end": datetime.fromtimestamp(now, UTC),
            "feed": DataFeed.BOATS,
        }
        trades = client.get_stock_trades(StockTradesRequest(**window))
        quotes = client.get_stock_quotes(StockQuotesRequest(**window))
        ts_init = int(_decimal(self._clock()) * _NS_PER_S)
        # The window start bounds the dedupe memory; its high-water mark stops a clock step
        # back from re-delivering a print whose key was already dropped.
        self._horizon_ns = max(self._horizon_ns, _timestamp_ns(start))
        self._seen = {key: ts for key, ts in self._seen.items() if ts >= self._horizon_ns}
        fresh: list[tuple[int, int, tuple[object, ...], TradeTick | QuoteTick]] = []
        for symbol, row in _rows(trades):
            trade = Trade(symbol, row)
            tick = self._trade_tick(trade, ts_init)
            if trade.id is not None:
                key = ("trade", symbol, trade.exchange, trade.id)
            else:
                key = ("trade", symbol, tick.ts_event, tick.price.raw, tick.size.raw)
            fresh.append((tick.ts_event, 0, key, tick))
        for symbol, row in _rows(quotes):
            quote_tick = self._quote_tick(Quote(symbol, row), ts_init)
            if quote_tick is not None:
                prices = (quote_tick.bid_price.raw, quote_tick.ask_price.raw)
                sizes = (quote_tick.bid_size.raw, quote_tick.ask_size.raw)
                key = ("quote", symbol, quote_tick.ts_event, *prices, *sizes)
                fresh.append((quote_tick.ts_event, 1, key, quote_tick))
        # Vendor-time order, as a stream delivers; at one vendor time the trade goes first, so
        # CSession.on_trade pairs it with the quote that prevailed before it.
        fresh.sort(key=lambda item: item[:2])
        for ts_event, _, key, tick in fresh:
            if ts_event < self._horizon_ns or key in self._seen:
                continue
            self._seen[key] = ts_event
            if isinstance(tick, TradeTick):
                self._on_trade(tick)
            else:
                self._on_quote(tick)

    async def _handle_trade(self, trade: Trade | dict[str, Any]) -> None:
        if self.failure is not None:
            return
        tap = self._tap
        token = None
        if tap is not None:
            ts_event = _timestamp_ns(trade.timestamp) if isinstance(trade, Trade) else None
            token = tap.trade_entry(getattr(trade, "symbol", ""), ts_event)
        try:
            if not isinstance(trade, Trade):
                raise TypeError("StockDataStream must run with raw_data=False")
            tick = self._trade_tick(trade, time.time_ns())
            self._on_trade(tick)
        except Exception as exc:
            await self._fail(exc)
        finally:
            if tap is not None and token is not None:
                tap.finish(token)

    async def _handle_quote(self, quote: Quote | dict[str, Any]) -> None:
        if self.failure is not None:
            return
        tap = self._tap
        token = None
        if tap is not None:
            ts_event = _timestamp_ns(quote.timestamp) if isinstance(quote, Quote) else None
            token = tap.quote_entry(getattr(quote, "symbol", ""), ts_event)
        try:
            if not isinstance(quote, Quote):
                raise TypeError("StockDataStream must run with raw_data=False")
            tick = self._quote_tick(quote, time.time_ns())
            if tick is not None:
                self._on_quote(tick)
        except Exception as exc:
            await self._fail(exc)
        finally:
            if tap is not None and token is not None:
                tap.finish(token)

    def _trade_tick(self, trade: Trade, ts_init: int) -> TradeTick:
        instrument = self._instrument_for(trade.symbol)
        ts_event = _timestamp_ns(trade.timestamp)
        return TradeTick(
            instrument.id,
            _price(trade.price, instrument.price_precision),
            _quantity(trade.size, "trade size"),
            AggressorSide.NO_AGGRESSOR,
            self._trade_id(trade, ts_event),
            ts_event,
            ts_init,
        )

    def _quote_tick(self, quote: Quote, ts_init: int) -> QuoteTick | None:
        instrument = self._instrument_for(quote.symbol)
        precision = instrument.price_precision
        bid_raw = _decimal(quote.bid_price)
        ask_raw = _decimal(quote.ask_price)
        if not bid_raw.is_finite() or not ask_raw.is_finite() or bid_raw <= 0 or ask_raw <= 0:
            return None

        bid = _price(quote.bid_price, precision)
        ask = _price(quote.ask_price, precision)
        bid_value = bid.as_decimal()
        ask_value = ask.as_decimal()
        if bid_value <= 0 or ask_value <= 0 or bid_value >= ask_value:
            return None

        ts_event = _timestamp_ns(quote.timestamp)
        return QuoteTick(
            instrument.id,
            bid,
            ask,
            _quantity(quote.bid_size, "bid size", lot_size=_ROUND_LOT_SHARES),
            _quantity(quote.ask_size, "ask size", lot_size=_ROUND_LOT_SHARES),
            ts_event,
            ts_init,
        )

    def _instrument_for(self, symbol: str) -> Instrument:
        instrument = self._instruments.get(symbol)
        if instrument is None:
            raise ValueError(f"unsubscribed symbol {symbol}")
        return instrument

    @staticmethod
    def _trade_id(trade: Trade, ts_ns: int) -> TradeId:
        parts: list[str] = []
        if trade.exchange is not None:
            parts.append(str(getattr(trade.exchange, "value", trade.exchange)))
        if trade.id is not None:
            parts.append(str(trade.id))
        value = "-".join(parts)
        if not value:
            value = f"{ts_ns}-{trade.price}-{trade.size}"
        return TradeId(value[:_TRADE_ID_MAX])

    def _observe_failure(self) -> None:
        if self._tap is not None:
            self._tap.observe_failure()

    async def _fail(self, exc: Exception) -> None:
        """Record the first failure and ask alpaca-py to stop from its own loop."""
        self._observe_failure()
        if self.failure is None:
            self.failure = exc
        stream = self._stream
        if stream is not None:
            # A stop failure must not escape into alpaca-py's consume loop.
            with contextlib.suppress(Exception):
                await stream.stop_ws()
