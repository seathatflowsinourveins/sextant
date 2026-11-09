"""Live Alpaca SIP trades and quotes as native ticks for the paper runner.

Source: https://docs.alpaca.markets/docs/real-time-stock-pricing-data (read 2026-11-09);
alpaca-py==0.44.0 ``StockDataStream``. The conversion follows the pinned
northstar-trading adapter registered in the manifest's "Live Alpaca SIP tick feed"
row (``src/nautilus_alpaca/streams.py``).

The feed only converts market data. It places no order, reads no key from the
environment or a file (the injected stream factory receives the pair), and adds no
reconnect or retry policy: the runner owns the stream's lifecycle. rc8's
``TradeTick`` has no conditions or tape field, so those vendor fields cannot ride the
tick; the pinned adapter likewise keeps only exchange and trade id in its stable
``TradeId``. The C-lane reads conditions separately. ``ts_event`` keeps the vendor
timestamp; ``ts_init`` comes from the local receipt clock.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from alpaca.data.enums import DataFeed
from alpaca.data.live import StockDataStream
from alpaca.data.models.quotes import Quote
from alpaca.data.models.trades import Trade
from nautilus_trader.model import (
    AggressorSide,
    InstrumentId,
    Price,
    Quantity,
    QuoteTick,
    TradeId,
    TradeTick,
)

__all__ = ["AlpacaTickFeed"]

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SIP = "sip"
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


class AlpacaTickFeed:
    """Convert one SIP trade or quote stream into the C-lane's Nautilus ticks.

    The constructor validates credentials and the feed but performs no network I/O
    and calls no stream factory. ``start()`` builds the stream, subscribes every
    instrument's bare Alpaca symbol, and runs alpaca-py's blocking loop.
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
    ) -> None:
        if not api_key or not secret_key:
            raise ValueError("Alpaca key and secret are required")
        if feed != _SIP:
            raise ValueError("paper arming uses the SIP feed only; iex is refused")

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
        self.failure: Exception | None = None

    def start(self) -> None:
        """Subscribe all instruments and run the stream's blocking loop."""
        if self._stream is not None:
            raise RuntimeError("Alpaca tick feed already started")

        stream = self._stream_factory(self._api_key, self._secret_key, feed=DataFeed.SIP)
        self._stream = stream
        symbols = tuple(sorted(self._instruments))
        stream.subscribe_trades(self._handle_trade, *symbols)
        stream.subscribe_quotes(self._handle_quote, *symbols)
        try:
            stream.run()
        except Exception as exc:
            if self.failure is None:
                self.failure = exc
            raise

    def stop(self) -> None:
        """Delegate alpaca-py's cross-thread stop; the runner owns retries."""
        stream = self._stream
        if stream is None:
            return
        try:
            stream.stop()
        except AttributeError:
            # DataStream.stop() reads self._loop, which run() sets in _run_forever.
            return

    async def _handle_trade(self, trade: Trade | dict[str, Any]) -> None:
        if self.failure is not None:
            return
        try:
            if not isinstance(trade, Trade):
                raise TypeError("StockDataStream must run with raw_data=False")
            self._on_trade(self._trade_tick(trade))
        except Exception as exc:
            await self._fail(exc)

    async def _handle_quote(self, quote: Quote | dict[str, Any]) -> None:
        if self.failure is not None:
            return
        try:
            if not isinstance(quote, Quote):
                raise TypeError("StockDataStream must run with raw_data=False")
            tick = self._quote_tick(quote)
            if tick is not None:
                self._on_quote(tick)
        except Exception as exc:
            await self._fail(exc)

    def _trade_tick(self, trade: Trade) -> TradeTick:
        instrument = self._instrument_for(trade.symbol)
        ts_event = _timestamp_ns(trade.timestamp)
        return TradeTick(
            instrument.id,
            _price(trade.price, instrument.price_precision),
            _quantity(trade.size, "trade size"),
            AggressorSide.NO_AGGRESSOR,
            self._trade_id(trade, ts_event),
            ts_event,
            time.time_ns(),
        )

    def _quote_tick(self, quote: Quote) -> QuoteTick | None:
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
            time.time_ns(),
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

    async def _fail(self, exc: Exception) -> None:
        """Record the first failure and ask alpaca-py to stop from its own loop."""
        if self.failure is None:
            self.failure = exc
        stream = self._stream
        if stream is not None:
            # A stop failure must not escape into alpaca-py's consume loop.
            with contextlib.suppress(Exception):
                await stream.stop_ws()
