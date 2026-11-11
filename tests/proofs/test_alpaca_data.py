"""Offline E4 witness through NautilusTrader's ALPACA sandbox shell."""

import asyncio
import threading
from datetime import UTC, datetime
from decimal import Decimal
from importlib import import_module
from typing import Any

import msgpack
import pytest
from alpaca.data.enums import DataFeed
from alpaca.data.models import BarSet, QuoteSet, TradeSet
from alpaca.data.requests import StockBarsRequest, StockQuotesRequest, StockTradesRequest
from nautilus_trader.adapters.sandbox import SandboxExecutionClientFactory
from nautilus_trader.common import DataResponse
from nautilus_trader.config import DataClientConfig
from nautilus_trader.live import InstrumentProvider, InstrumentProviderConfig, LiveNodeBuilder
from nautilus_trader.live.clients import DataClientFactory
from nautilus_trader.model import (
    AccountId,
    Bar,
    BarType,
    Currency,
    Equity,
    InstrumentId,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    TradeTick,
    Venue,
)
from nautilus_trader.trading import Strategy
from test_paper_config import account

from sextant.paper.native import node_config, sandbox_client_config

INSTRUMENT_ID = InstrumentId.from_str("AAPL.ALPACA")
BAR_TYPE = BarType.from_str("AAPL.ALPACA-1-MINUTE-LAST-EXTERNAL")
START = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)
END = datetime(2026, 11, 9, 15, 2, tzinfo=UTC)
STAMP = "2026-11-09T15:00:00Z"
QUOTE = {"S": "AAPL", "T": "q", "t": STAMP, "bp": 10.01, "ap": 10.03, "bs": 2, "as": 3}
INVALID_QUOTES = (
    {**QUOTE, "bp": 0},
    {**QUOTE, "bp": 10.05},
    {**QUOTE, "ap": QUOTE["bp"]},
)
TRADE = {"S": "AAPL", "T": "t", "t": STAMP, "p": 10.02, "s": 7, "x": "D", "i": 123}
BAR = {
    "S": "AAPL",
    "T": "b",
    "t": STAMP,
    "o": 10.01,
    "h": 10.04,
    "l": 10.00,
    "c": 10.02,
    "v": 19,
    "n": 2,
    "vw": 10.02,
}


class StandInSocket:
    """Emulate wire subscriptions under the SDK's own subscription methods."""

    def __init__(self, stream):
        self.stream = stream
        self.first_subscribe = True

    async def send(self, data):
        payload = msgpack.unpackb(data if isinstance(data, bytes) else b"".join(data))
        if payload["action"] == "unsubscribe":
            if payload.get("quotes") == ["AAPL"]:
                self.stream.unsubscribe_sent.set()
            return
        if self.first_subscribe:
            self.first_subscribe = False
            await asyncio.sleep(0.1)  # The initial send suspends after snapshotting symbols.
        rows_by_channel = (
            ("quotes", (*INVALID_QUOTES, QUOTE)),
            ("trades", (TRADE,)),
            ("bars", (BAR,)),
        )
        for channel, rows in rows_by_channel:
            if channel not in self.stream.delivered and "AAPL" in payload.get(channel, ()):
                for row in rows:
                    await self.stream._dispatch({**row, "t": _WireTimestamp()})
                self.stream.delivered.add(channel)

    async def close(self):
        self.stream.closed.set()


class _WireTimestamp:
    def to_datetime(self):
        return START


class StandInHistory:
    def __init__(self, fail: bool):
        self.fail = fail
        self.calls: list[
            tuple[StockQuotesRequest | StockTradesRequest | StockBarsRequest, int]
        ] = []

    def _reply(self, request, dataset, *rows):
        self.calls.append((request, threading.get_ident()))
        if self.fail:
            raise RuntimeError("fixture history unavailable")
        return dataset({"AAPL": list(rows)})

    def get_stock_quotes(self, request: StockQuotesRequest):
        return self._reply(request, QuoteSet, *INVALID_QUOTES, QUOTE)

    def get_stock_trades(self, request: StockTradesRequest):
        return self._reply(request, TradeSet, TRADE)

    def get_stock_bars(self, request: StockBarsRequest):
        return self._reply(request, BarSet, BAR)


class ProofProvider(InstrumentProvider):
    async def load_all_async(self, filters: dict | None = None):
        self.add(
            Equity(
                INSTRUMENT_ID,
                Symbol("AAPL"),
                Currency.from_str("USD"),
                2,
                Price.from_str("0.01"),
                0,
                0,
                lot_size=Quantity.from_int(1),
            )
        )


class Witness(Strategy):
    def __init__(self):
        super().__init__()
        self.historical = False
        self.events: list[tuple[QuoteTick | TradeTick | Bar, int]] = []
        self.completed: list[str] = []
        self.responses: list[DataResponse] = []
        self.finished = asyncio.Event()

    def on_start(self):
        if self.historical:
            self.request_quotes(
                INSTRUMENT_ID, START, END, limit=2, params={"witness": True}, callback=self.complete
            )
            self.request_trades(INSTRUMENT_ID, START, END, limit=2, callback=self.complete)
            self.request_bars(BAR_TYPE, START, END, limit=2, callback=self.complete)
        else:
            self.subscribe_quotes(INSTRUMENT_ID)
            self.subscribe_trades(INSTRUMENT_ID)
            self.subscribe_bars(BAR_TYPE)

    def complete(self, request_id: str):
        self.completed.append(request_id)
        if len(self.completed) == 3:
            self.finished.set()

    def receive(self, event):
        self.events.append((event, threading.get_ident()))
        if not self.historical and len(self.events) == 3:
            self.unsubscribe_quotes(INSTRUMENT_ID)
            self.finished.set()

    def on_quote(self, quote: QuoteTick):
        self.receive(quote)

    def on_trade(self, trade: TradeTick):
        self.receive(trade)

    def on_bar(self, bar: Bar):
        self.receive(bar)

    def on_data_response(self, response: DataResponse):
        self.responses.append(response)

    def on_historical_quotes(self, quotes):
        for quote in quotes:
            self.receive(quote)

    def on_historical_trades(self, trades):
        for trade in trades:
            self.receive(trade)

    def on_historical_bars(self, bars):
        for bar in bars:
            self.receive(bar)


async def run_shell(*, historical: bool = False, fail: bool = False):
    # Fail as a test assertion on the clean checkout. The actual native shell
    # and queue are built below once the adapter module is available.
    try:
        adapter = import_module("sextant.alpaca.data")
    except ModuleNotFoundError as error:
        if error.name not in {"sextant.alpaca", "sextant.alpaca.data"}:
            raise
        pytest.fail("AlpacaDataClient is missing from the sandbox shell", pytrace=False)

    feed = DataFeed.IEX if historical else DataFeed.SIP

    class StandInStream(adapter.AlpacaStockDataStream):
        def __init__(self):
            super().__init__("fixture", "fixture", feed=feed)
            self.thread_ids: set[int] = set()
            self.delivered: set[str] = set()
            self.unsubscribe_sent = threading.Event()
            self.closed = threading.Event()

        async def _start_ws(self):
            self.thread_ids.add(threading.get_ident())
            self._ws = StandInSocket(self)

        async def _consume(self):
            await asyncio.Future()

    stream = StandInStream()
    history = StandInHistory(fail)
    strategy = Witness()
    strategy.historical = historical

    clients = []

    class FixtureFactory(DataClientFactory):
        @staticmethod
        def create(*, name, config, cache, clock):
            client = adapter.AlpacaDataClient(
                name=name,
                config=config,
                cache=cache,
                clock=clock,
                instrument_provider=ProofProvider(InstrumentProviderConfig(load_all=True)),
                stream=stream,
                historical=history,
                feed=feed,
                venue=Venue.from_str("ALPACA"),
            )
            clients.append(client)
            return client

    settings = account()
    node = (
        LiveNodeBuilder.from_config("alpaca-data-proof", node_config(settings))
        .with_delay_post_stop_secs(0)
        .add_data_client("ALPACA", FixtureFactory(), DataClientConfig())
        .add_simulated_exec_client(
            settings.client_id,
            SandboxExecutionClientFactory(),
            sandbox_client_config(settings, "10000 USD"),
        )
        .build()
    )
    node.add_strategy(strategy)
    portfolio, handle = node.portfolio, node.handle()
    task = asyncio.create_task(node.run_async())
    try:
        await asyncio.wait_for(strategy.finished.wait(), timeout=5)
        assert portfolio.account(account_id=AccountId.from_str("SIM-A001")) is not None
        if not historical:
            assert await asyncio.to_thread(stream.unsubscribe_sent.wait, 5)
    finally:
        handle.stop()
        try:
            await asyncio.wait_for(task, timeout=10)
        finally:
            node.dispose()
    return strategy, stream, history, clients[0]


def assert_ticks(events: list[tuple[Any, int]], owner: int):
    assert len(events) == 3
    by_type = {type(event): event for event, thread in events if thread == owner}
    assert set(by_type) == {QuoteTick, TradeTick, Bar}
    quote, trade, bar = by_type[QuoteTick], by_type[TradeTick], by_type[Bar]
    assert quote.instrument_id == trade.instrument_id == INSTRUMENT_ID
    assert quote.bid_price.as_decimal() == Decimal("10.01")
    assert quote.ask_price.as_decimal() == Decimal("10.03")
    assert quote.bid_size.as_decimal() == Decimal("200")
    assert quote.ask_size.as_decimal() == Decimal("300")
    assert trade.price.as_decimal() == Decimal("10.02")
    assert trade.size.as_decimal() == Decimal("7")
    assert str(trade.trade_id) == "D-123"
    assert bar.bar_type == BAR_TYPE
    assert bar.close.as_decimal() == Decimal("10.02")
    assert bar.volume.as_decimal() == Decimal("19")
    assert quote.ts_event == trade.ts_event == 1_794_236_400_000_000_000
    assert bar.ts_event == 1_794_236_460_000_000_000
    assert all(event.ts_init >= event.ts_event for event in by_type.values())


def test_stock_stream_delivers_typed_data_to_strategy_on_sandbox_loop():
    owner = threading.get_ident()
    strategy, stream, history, client = asyncio.run(run_shell())
    assert_ticks(strategy.events, owner)
    assert stream.thread_ids and owner not in stream.thread_ids
    assert stream.closed.is_set()
    assert not history.calls
    assert client.dropped_quote_count == 3


def test_stock_history_delivers_correlated_typed_data_off_the_node_loop():
    owner = threading.get_ident()
    strategy, stream, history, client = asyncio.run(run_shell(historical=True))
    assert_ticks(strategy.events, owner)
    assert len(set(strategy.completed)) == 3
    assert client.dropped_quote_count == 3
    assert {response.correlation_id for response in strategy.responses} == set(strategy.completed)
    assert all(
        response.completed and response.failure_reason is None for response in strategy.responses
    )
    assert all(response.start == 1_794_236_400_000_000_000 for response in strategy.responses)
    assert all(response.end == 1_794_236_520_000_000_000 for response in strategy.responses)
    assert any(
        response.params and response.params.get("witness") for response in strategy.responses
    )
    assert not stream.thread_ids
    requests = {type(request): request for request, thread in history.calls if thread != owner}
    assert set(requests) == {StockQuotesRequest, StockTradesRequest, StockBarsRequest}
    bars_request = requests[StockBarsRequest]
    assert isinstance(bars_request, StockBarsRequest)
    assert bars_request.timeframe.value == "1Min"
    assert bars_request.start == datetime(2026, 11, 9, 14, 59)
    assert bars_request.end == datetime(2026, 11, 9, 15, 1)
    assert all(request.feed == DataFeed.IEX and request.limit == 2 for request in requests.values())


def test_failed_stock_history_completes_requests_without_publishing_data():
    strategy, stream, history, _client = asyncio.run(run_shell(historical=True, fail=True))
    assert len(set(strategy.completed)) == 3
    assert not strategy.events and not stream.thread_ids
    assert len(history.calls) == 3
    assert len(strategy.responses) == 3
    assert all(
        "fixture history unavailable" in (r.failure_reason or "") for r in strategy.responses
    )


@pytest.mark.parametrize("bound", [False, True])
def test_disconnect_bounds_readiness_and_join(monkeypatch, bound):
    from sextant.alpaca import data

    monkeypatch.setattr(data, "_STREAM_STOP_TIMEOUT_S", 0.01, raising=False)

    async def blocked():
        await asyncio.Future()

    async def check():
        client = offline_client()
        loop = asyncio.get_running_loop()
        vendor = asyncio.create_task(blocked())
        worker = asyncio.create_task(blocked())
        client._stream_task = worker
        client._stream_ready = loop.create_future()
        if bound:
            client._stream_ready.set_result((loop, vendor))
        stop = asyncio.create_task(client._disconnect())
        try:
            done, _ = await asyncio.wait([stop], timeout=0.1)
            assert done, f"disconnect stalled with stream loop bound={bound}"
            with pytest.raises(TimeoutError):
                stop.result()
            assert vendor.cancelled() is bound
            assert not worker.done()
        finally:
            for task in (stop, worker, vendor):
                task.cancel()
            await asyncio.gather(stop, worker, vendor, return_exceptions=True)

    asyncio.run(check())


def offline_client(**kwargs):
    from typing import cast

    from sextant.alpaca.data import AlpacaDataClient

    return AlpacaDataClient(
        name="ALPACA",
        config=DataClientConfig(),
        cache=cast(Any, None),
        clock=cast(Any, None),
        venue=INSTRUMENT_ID.venue,
        feed=DataFeed.SIP,
        **kwargs,
    )


def test_disconnect_reraises_first_handler_conversion_failure(monkeypatch):
    from unittest.mock import AsyncMock

    from alpaca.data.models import Quote

    from sextant.alpaca import data

    class Stream(data.AlpacaStockDataStream):
        async def _run_forever(self):
            await asyncio.Future()

        async def register(self, channel, symbols, handler):
            await handler(Quote(symbols[0], {**QUOTE, "bs": 1.5}))
            await handler(Quote("UNREGISTERED", QUOTE))

    async def check():
        client = offline_client(stream=Stream("fixture", "fixture"))
        monkeypatch.setattr(client, "create_task", lambda coro, _name: asyncio.create_task(coro))
        monkeypatch.setattr(
            client,
            "_stock",
            AsyncMock(
                return_value=data._Stock(INSTRUMENT_ID, INSTRUMENT_ID.symbol.value, 2, 0),
            ),
        )
        await client._subscribe_channel("quotes", [INSTRUMENT_ID])
        with pytest.raises(ValueError, match="nonnegative whole count"):
            await client._disconnect()

    asyncio.run(check())


def test_trade_id_is_bounded_without_claiming_aggressor():
    from alpaca.data.models import Trade
    from nautilus_trader.model import AggressorSide

    from sextant.alpaca import data

    stock = data._Stock(INSTRUMENT_ID, INSTRUMENT_ID.symbol.value, 2, 0)
    row = Trade(stock.symbol, {**TRADE, "i": int("7" * 40)})
    tick = data._trade_tick(row, stock)
    assert str(tick.trade_id) == "D-" + "7" * 34
    assert tick.aggressor_side == AggressorSide.NO_AGGRESSOR
