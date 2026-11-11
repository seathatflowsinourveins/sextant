"""Alpaca equity market data for the NautilusTrader rc8 Python adapter.

NautilusTrader d53849b: examples/live/_template/data.py, the Python adapter
guide and live/__init__.pyi. alpaca-py cc4cb3b: data/live/{stock,websocket}.py,
data/historical/stock.py and data/requests.py. Receipt and bar clocks follow
Sextant ADR-0013 and the existing alpaca_feed.py thread boundary.
Thread hand-off uses Python 3.13 asyncio's call_soon_threadsafe
(https://docs.python.org/3.13/library/asyncio-eventloop.html#asyncio.loop.call_soon_threadsafe,
read 2026-11-10).
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Protocol, cast
from zoneinfo import ZoneInfo

from alpaca.data.enums import DataFeed
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.live.stock import StockDataStream
from alpaca.data.models import Bar as StockBar
from alpaca.data.models import BarSet, Quote, QuoteSet, Trade, TradeSet
from alpaca.data.requests import StockBarsRequest, StockQuotesRequest, StockTradesRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from nautilus_trader.common import Clock, Logger
from nautilus_trader.config import DataClientConfig
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.live import (
    BarsResponse,
    ClientCache,
    InstrumentProvider,
    QuotesResponse,
    RequestBars,
    RequestQuotes,
    RequestTrades,
    SubscribeBars,
    SubscribeQuotes,
    SubscribeTrades,
    TradesResponse,
    UnsubscribeBars,
    UnsubscribeQuotes,
    UnsubscribeTrades,
)
from nautilus_trader.live.clients import MarketDataClient
from nautilus_trader.model import (
    AggressorSide,
    Bar,
    BarAggregation,
    BarType,
    Equity,
    InstrumentId,
    Price,
    PriceType,
    Quantity,
    QuoteTick,
    TradeId,
    TradeTick,
    Venue,
)

_NY = ZoneInfo("America/New_York")
_STREAM_STOP_TIMEOUT_S = 5.0  # E4 dsh build 48cb220, shutdown bound.
_TRADE_ID_MAX = 36  # NautilusTrader rc8 crates/model/src/identifiers/trade_id.rs:50.
_ROUND_LOT_SHARES = 100  # Alpaca's quote sizes and the incumbent SIP normalization.
type _Tick = QuoteTick | TradeTick | Bar
type _StreamOwner = tuple[asyncio.AbstractEventLoop, asyncio.Task[None]]
type _StockHandler = Callable[[Quote | Trade | StockBar], Awaitable[None]]


class _DataSettings(Protocol):
    """The E2 data config fields consumed here."""

    api_key_env: str
    api_secret_env: str
    feed: str


class AlpacaStockDataStream(StockDataStream):
    """Run alpaca-py's handler mutations on the loop that sends subscriptions.

    The pinned synchronous helpers use run_coroutine_threadsafe().result().
    Here the mutations and the SDK's initial/reconnect send share a lock so a
    change cannot land between the send snapshot and the SDK setting _running.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._subscription_lock = asyncio.Lock()

    async def _send_subscribe_msg(self) -> None:
        async with self._subscription_lock:
            await super()._send_subscribe_msg()

    async def register(
        self, channel: str, symbols: tuple[str, ...], handler: _StockHandler
    ) -> None:
        async with self._subscription_lock:
            self._handlers[channel].update(dict.fromkeys(symbols, handler))
            if self._running:
                await super()._send_subscribe_msg()

    async def unregister(self, channel: str, symbols: tuple[str, ...]) -> None:
        async with self._subscription_lock:
            if self._running:
                await self._send_unsubscribe_msg(channel, list(symbols))
            for symbol in symbols:
                del self._handlers[channel][symbol]


@dataclass(frozen=True)
class _Stock:
    id: InstrumentId
    symbol: str
    price_precision: int
    size_precision: int

    def price(self, value: object) -> Price:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
        return Price.from_decimal_dp(number, self.price_precision)

    def quantity(self, value: object, multiplier: int = 1) -> Quantity:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number != number.to_integral_value():
            raise ValueError("Alpaca market data size must be a nonnegative whole count")
        return Quantity.from_decimal_dp(number * multiplier, self.size_precision)


class AlpacaDataClient(MarketDataClient):
    """One SDK stream and historical client for one explicit IEX or SIP feed.

    The E2 factory supplies the provider and names-only config. SDK clients
    can also be supplied at construction for a socket-free sandbox.
    """

    def __init__(
        self,
        *,
        name: str,
        config: DataClientConfig,
        cache: ClientCache,
        clock: Clock,
        instrument_provider: InstrumentProvider | None = None,
        venue: Venue,
        stream: AlpacaStockDataStream | None = None,
        historical: StockHistoricalDataClient | None = None,
        feed: DataFeed | None = None,
    ) -> None:
        self._settings = cast(_DataSettings, config)
        selected = DataFeed(self._settings.feed) if feed is None else feed
        if selected not in (DataFeed.IEX, DataFeed.SIP):
            raise ValueError("alpaca-py StockDataStream supports IEX and SIP")
        super().__init__(
            name=name,
            config=config,
            cache=cache,
            clock=clock,
            venue=venue,
            instrument_provider=instrument_provider,
        )
        self._stream = stream
        self._historical = historical
        self._feed = selected
        self._log = Logger(type(self).__name__)
        self._active: dict[str, dict[str, InstrumentId | BarType]] = {
            "quotes": {},
            "trades": {},
            "bars": {},
        }
        self._stream_ready: asyncio.Future[_StreamOwner] | None = None
        self._stream_task: asyncio.Task[object] | None = None
        self._closing = False
        self._handler_failure: Exception | None = None
        self._dropped_quote_count = 0

    @property
    def dropped_quote_count(self) -> int:
        """Rejected spreads from streaming and history, counted on the node loop."""
        return self._dropped_quote_count

    async def _connect(self) -> None:
        if self.instrument_provider is None:
            raise RuntimeError("The Alpaca data client requires an instrument provider")
        await self.instrument_provider.initialize()
        for instrument in self.instrument_provider.list_all():
            self._handle_instrument(instrument)

    def _credentials(self) -> tuple[str, str]:
        try:
            return os.environ[self._settings.api_key_env], os.environ[self._settings.api_secret_env]
        except KeyError as error:
            raise ValueError(f"Missing Alpaca credential environment variable {error}") from None

    def _history_client(self) -> StockHistoricalDataClient:
        if self._historical is None:
            self._historical = StockHistoricalDataClient(*self._credentials())
        return self._historical

    async def _disconnect(self) -> None:
        self._closing = True
        # The ready future supplies the actual loop before stop is attempted.
        async with asyncio.timeout(_STREAM_STOP_TIMEOUT_S):
            if self._stream_task is not None and self._stream_ready is not None:
                if not self._stream_task.done():
                    loop, task = await asyncio.shield(self._stream_ready)
                    try:
                        loop.call_soon_threadsafe(task.cancel)
                    except RuntimeError:
                        if not loop.is_closed():
                            raise
                await asyncio.shield(self._stream_task)

    def _run_stream(
        self,
        stream: AlpacaStockDataStream,
        owner: asyncio.AbstractEventLoop,
        ready: asyncio.Future[_StreamOwner],
    ) -> None:
        async def run() -> None:
            task = asyncio.current_task()
            assert task is not None
            owner.call_soon_threadsafe(ready.set_result, (asyncio.get_running_loop(), task))
            try:
                # SDK run() wraps this coroutine in asyncio.run(). Retain
                # that boundary while making startup and shutdown cancellable.
                if not self._closing:
                    await stream._run_forever()
            except asyncio.CancelledError:
                pass
            finally:
                try:
                    await stream.close()
                finally:
                    if self._handler_failure is not None:
                        raise self._handler_failure

        asyncio.run(run())

    async def _stream_worker(
        self,
        stream: AlpacaStockDataStream,
        owner: asyncio.AbstractEventLoop,
        ready: asyncio.Future[_StreamOwner],
    ) -> None:
        await asyncio.to_thread(self._run_stream, stream, owner, ready)
        if not self._closing:
            raise RuntimeError("Alpaca stock data stream exited")

    async def _change_subscription(
        self, stream: AlpacaStockDataStream, change: Callable[..., Awaitable[None]], *args: object
    ) -> None:
        if self._stream_task is None:
            owner = asyncio.get_running_loop()
            self._stream_ready = owner.create_future()
            self._stream_task = self.create_task(
                self._stream_worker(stream, owner, self._stream_ready), "alpaca-stock-stream"
            )
        assert self._stream_ready is not None
        loop, _ = await asyncio.shield(self._stream_ready)
        if self._stream_task.done():
            raise RuntimeError("Alpaca stock data stream is unavailable")

        async def apply() -> None:
            await change(*args)

        operation = apply()
        try:
            completion = asyncio.run_coroutine_threadsafe(operation, loop)
        except RuntimeError:
            operation.close()
            raise
        result = asyncio.wrap_future(completion)
        try:
            await asyncio.wait((result, self._stream_task), return_when=asyncio.FIRST_COMPLETED)
            if not result.done():
                raise RuntimeError("Alpaca stock data stream exited during subscription change")
            await result
        finally:
            if not result.done():
                result.cancel()

    async def _stock(self, instrument_id: InstrumentId) -> _Stock:
        provider = self.instrument_provider
        if provider is None or instrument_id.venue != self.venue:
            raise ValueError(f"Alpaca equity unavailable: {instrument_id}")
        instrument = provider.find(instrument_id)
        if instrument is None:
            await provider.load_async(instrument_id)
            instrument = provider.find(instrument_id)
            if isinstance(instrument, Equity):
                self._handle_instrument(instrument)
        if not isinstance(instrument, Equity):
            raise ValueError(f"Alpaca equity unavailable: {instrument_id}")
        symbol = str(instrument.raw_symbol)
        if "*" in symbol:
            raise ValueError("Alpaca data subscriptions and requests require named symbols")
        return _Stock(instrument.id, symbol, instrument.price_precision, instrument.size_precision)

    async def _subscribe_quotes(self, command: SubscribeQuotes) -> None:
        await self._subscribe_channel("quotes", command.instrument_ids)

    async def _subscribe_trades(self, command: SubscribeTrades) -> None:
        await self._subscribe_channel("trades", command.instrument_ids)

    async def _subscribe_bars(self, command: SubscribeBars) -> None:
        for bar_type in command.bar_types:
            _bar_timeframe(bar_type, streaming=True)
        await self._subscribe_channel("bars", command.bar_types)

    async def _subscribe_channel(
        self, channel: str, keys: list[InstrumentId] | list[BarType]
    ) -> None:
        owner = asyncio.get_running_loop()
        active = self._active[channel]
        stocks: dict[str, tuple[_Stock, InstrumentId | BarType]] = {}
        for key in keys:
            try:
                stock = await self._stock(key.instrument_id if isinstance(key, BarType) else key)
                if stock.symbol in active:
                    if active[stock.symbol] != key:
                        raise ValueError("Alpaca symbol already has a different subscription")
                    continue
                stocks[stock.symbol] = (stock, key)
            except (ValueError, TypeError) as error:
                self._log.error(f"Alpaca {channel} subscription skipped for {key}: {error}")
        if not stocks:
            return

        if self._stream is None:
            self._stream = AlpacaStockDataStream(*self._credentials(), feed=self._feed)
        stream = self._stream

        async def receive(row: Quote | Trade | StockBar) -> None:
            if self._handler_failure is not None:
                return
            receipt = time.time_ns()
            try:
                stock, key = stocks[row.symbol]
                if channel == "quotes" and isinstance(row, Quote):
                    tick = _quote_tick(row, stock, receipt)
                elif channel == "trades" and isinstance(row, Trade):
                    tick = _trade_tick(row, stock, receipt)
                elif isinstance(key, BarType) and isinstance(row, StockBar):
                    tick = _bar(row, stock, key, receipt)
                else:
                    raise TypeError("Unexpected Alpaca market data model")
            except Exception as error:
                self._handler_failure = error
                await stream.stop_ws()
                return
            owner.call_soon_threadsafe(self._publish, channel, stock.symbol, key, tick)

        # alpaca-py installs these handlers before its wire send and retains
        # them for reconnect. Accept the earliest queued tick from each handler.
        active.update({symbol: key for symbol, (_, key) in stocks.items()})
        await self._change_subscription(stream, stream.register, channel, tuple(stocks), receive)

    def _publish(
        self, channel: str, symbol: str, key: InstrumentId | BarType, tick: _Tick | None
    ) -> None:
        if tick is None:
            self._dropped_quote_count += 1
        elif not self._closing and self._active[channel].get(symbol) == key:
            self._handle_data(tick)

    async def _unsubscribe_quotes(self, command: UnsubscribeQuotes) -> None:
        await self._unsubscribe_channel("quotes", command.instrument_ids)

    async def _unsubscribe_trades(self, command: UnsubscribeTrades) -> None:
        await self._unsubscribe_channel("trades", command.instrument_ids)

    async def _unsubscribe_bars(self, command: UnsubscribeBars) -> None:
        await self._unsubscribe_channel("bars", command.bar_types)

    async def _unsubscribe_channel(
        self, channel: str, keys: list[InstrumentId] | list[BarType]
    ) -> None:
        active = self._active[channel]
        symbols = [symbol for symbol, key in active.items() if key in keys]
        if symbols:
            stream = self._stream
            assert stream is not None
            await self._change_subscription(stream, stream.unregister, channel, tuple(symbols))
            for symbol in symbols:
                del active[symbol]

    async def _request_quotes(self, request: RequestQuotes) -> None:
        stocks = [await self._stock(instrument_id) for instrument_id in request.instrument_ids]
        params = StockQuotesRequest(
            symbol_or_symbols=[stock.symbol for stock in stocks],
            start=request.start,
            end=request.end,
            limit=request.limit,
            feed=self._feed,
        )
        result = await asyncio.to_thread(self._history_client().get_stock_quotes, params)
        if not isinstance(result, QuoteSet):
            raise TypeError("Alpaca quote history must return an SDK QuoteSet")
        ticks: list[QuoteTick] = []
        for stock in stocks:
            for row in result.data.get(stock.symbol, ()):
                tick = _quote_tick(row, stock)
                if tick is None:
                    self._dropped_quote_count += 1
                else:
                    ticks.append(tick)
        self._handle_response(
            QuotesResponse(
                self.client_id,
                request.instrument_ids,
                sorted(ticks, key=lambda tick: tick.ts_event),
                request.request_id,
                self.clock.timestamp_ns(),
                request.start_ns,
                request.end_ns,
                request.params,
            )
        )

    async def _request_trades(self, request: RequestTrades) -> None:
        stocks = [await self._stock(instrument_id) for instrument_id in request.instrument_ids]
        params = StockTradesRequest(
            symbol_or_symbols=[stock.symbol for stock in stocks],
            start=request.start,
            end=request.end,
            limit=request.limit,
            feed=self._feed,
        )
        result = await asyncio.to_thread(self._history_client().get_stock_trades, params)
        if not isinstance(result, TradeSet):
            raise TypeError("Alpaca trade history must return an SDK TradeSet")
        ticks = [
            _trade_tick(row, stock) for stock in stocks for row in result.data.get(stock.symbol, ())
        ]
        self._handle_response(
            TradesResponse(
                self.client_id,
                request.instrument_ids,
                sorted(ticks, key=lambda tick: tick.ts_event),
                request.request_id,
                self.clock.timestamp_ns(),
                request.start_ns,
                request.end_ns,
                request.params,
            )
        )

    async def _request_bars(self, request: RequestBars) -> None:
        # rc8 validates a single historical bar type before dispatch.
        bar_type = request.bar_type
        timeframe = _bar_timeframe(bar_type)
        stock = await self._stock(bar_type.instrument_id)
        start, end = request.start, request.end or self.clock.utc_now()
        # Alpaca filters opening timestamps. The engine window names the
        # closing timestamps we emit under ADR-0013.
        if timeframe.unit == TimeFrameUnit.Day:
            start = start.astimezone(_NY) - timedelta(days=1) if start is not None else None
            end = end.astimezone(_NY) - timedelta(days=1) if end is not None else None
        else:
            start = start - bar_type.spec.timedelta if start is not None else None
            end = end - bar_type.spec.timedelta if end is not None else None
        params = StockBarsRequest(
            symbol_or_symbols=stock.symbol,
            start=start,
            end=end,
            timeframe=timeframe,
            limit=request.limit,
            feed=self._feed,
        )
        result = await asyncio.to_thread(self._history_client().get_stock_bars, params)
        if not isinstance(result, BarSet):
            raise TypeError("Alpaca bar history must return an SDK BarSet")
        bars = [_bar(row, stock, bar_type) for row in result.data.get(stock.symbol, ())]
        self._handle_response(
            BarsResponse(
                self.client_id,
                bar_type,
                bars,
                request.request_id,
                self.clock.timestamp_ns(),
                request.start_ns,
                request.end_ns,
                request.params,
            )
        )


def _bar_timeframe(bar_type: BarType, *, streaming: bool = False) -> TimeFrame:
    spec = bar_type.spec
    if (
        bar_type.is_standard()
        and bar_type.is_externally_aggregated()
        and spec.price_type == PriceType.LAST
        and spec.step == 1
    ):
        if spec.aggregation == BarAggregation.MINUTE:
            return cast(TimeFrame, TimeFrame.Minute)
        if not streaming and spec.aggregation == BarAggregation.DAY:
            return cast(TimeFrame, TimeFrame.Day)
    raise NotImplementedError(
        f"Unsupported Alpaca {'streaming' if streaming else 'historical'} bar: {bar_type}"
    )


def _quote_tick(row: Quote, stock: _Stock, receipt: int | None = None) -> QuoteTick | None:
    bid_raw, ask_raw = Decimal(str(row.bid_price)), Decimal(str(row.ask_price))
    if not bid_raw.is_finite() or not ask_raw.is_finite() or not 0 < bid_raw < ask_raw:
        return None
    bid, ask = stock.price(bid_raw), stock.price(ask_raw)
    if not 0 < bid.as_decimal() < ask.as_decimal():
        return None
    event = dt_to_unix_nanos(row.timestamp)
    return QuoteTick(
        stock.id,
        bid,
        ask,
        stock.quantity(row.bid_size, _ROUND_LOT_SHARES),
        stock.quantity(row.ask_size, _ROUND_LOT_SHARES),
        event,
        event if receipt is None else receipt,
    )


def _trade_tick(row: Trade, stock: _Stock, receipt: int | None = None) -> TradeTick:
    if row.id is None:
        raise ValueError("Alpaca trade is missing its vendor ID")
    exchange = getattr(row.exchange, "value", row.exchange)
    trade_id = f"{exchange}-{row.id}" if exchange else str(row.id)
    event = dt_to_unix_nanos(row.timestamp)
    return TradeTick(
        stock.id,
        stock.price(row.price),
        stock.quantity(row.size),
        AggressorSide.NO_AGGRESSOR,
        TradeId(trade_id[:_TRADE_ID_MAX]),
        event,
        event if receipt is None else receipt,
    )


def _bar(row: StockBar, stock: _Stock, bar_type: BarType, receipt: int | None = None) -> Bar:
    if bar_type.spec.aggregation == BarAggregation.DAY:
        local = row.timestamp.astimezone(_NY)
        close = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    else:
        close = row.timestamp + bar_type.spec.timedelta
    event = dt_to_unix_nanos(close)
    return Bar(
        bar_type,
        stock.price(row.open),
        stock.price(row.high),
        stock.price(row.low),
        stock.price(row.close),
        stock.quantity(row.volume),
        event,
        event if receipt is None else receipt,
    )
