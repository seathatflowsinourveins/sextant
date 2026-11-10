"""Proofs for the live Alpaca tick feed; the stream and REST client are injected, so no network."""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
import time
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alpaca.data.enums import DataFeed
from alpaca.data.live import StockDataStream
from alpaca.data.models.quotes import Quote
from alpaca.data.models.trades import Trade
from alpaca.data.requests import StockQuotesRequest, StockTradesRequest
from nautilus_trader.model import (
    AggressorSide,
    Currency,
    Equity,
    InstrumentId,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    TradeId,
    TradeTick,
)

from sextant.paper.alpaca_feed import AlpacaTickFeed
from sextant.paper.feed_tap import FeedTap

_TRADE_TS = 1_794_234_600_123_456_000
_QUOTE_TS = 1_794_234_600_000_000_000
_FAR_PAST_TS = 1_577_977_200_000_000_000
_TEST_API_KEY = "test-key"
_TEST_API_CREDENTIAL = "test-credential"
_T0 = 1_794_234_600 * 1_000_000_000
_S = 1_000_000_000


class _Now:
    """A mutable wall clock the guard and the scripted exchange share."""

    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


_EQUITY = Equity(
    InstrumentId.from_str("AAPL.ALPACA"),
    Symbol("AAPL"),
    Currency.from_str("USD"),
    4,
    Price.from_str("0.0001"),
    0,
    0,
    lot_size=Quantity.from_int(1),
)


class _FakeStream(StockDataStream):
    """A stream stand-in that records calls; it never opens a socket."""

    def __init__(self) -> None:
        self.credentials: tuple[str, str] | None = None
        self.feed: DataFeed | None = None
        self.trade_handler: Callable[..., Any] | None = None
        self.quote_handler: Callable[..., Any] | None = None
        self.trade_symbols: tuple[str, ...] = ()
        self.quote_symbols: tuple[str, ...] = ()
        self.trade_subscriptions: list[tuple[Callable[..., Any], tuple[str, ...]]] = []
        self.quote_subscriptions: list[tuple[Callable[..., Any], tuple[str, ...]]] = []
        self.unsubscribed: list[tuple[str, tuple[str, ...]]] = []
        self.run_calls = 0
        self.stop_calls = 0
        self.stop_ws_calls = 0

    def subscribe_trades(self, handler: Callable[..., Any], *symbols: str) -> None:
        self.trade_handler = handler
        self.trade_symbols = symbols
        self.trade_subscriptions.append((handler, symbols))

    def subscribe_quotes(self, handler: Callable[..., Any], *symbols: str) -> None:
        self.quote_handler = handler
        self.quote_symbols = symbols
        self.quote_subscriptions.append((handler, symbols))

    def unsubscribe_trades(self, *symbols: str) -> None:
        self.unsubscribed.append(("trades", symbols))

    def unsubscribe_quotes(self, *symbols: str) -> None:
        self.unsubscribed.append(("quotes", symbols))

    def run(self) -> None:
        self.run_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

    async def stop_ws(self) -> None:
        self.stop_ws_calls += 1


class _ScriptedStream(_FakeStream):
    """A stream whose run() delivers a scripted exchange, still without a socket."""

    def __init__(self, script: Callable[[_ScriptedStream], None]) -> None:
        super().__init__()
        self.script = script

    def run(self) -> None:
        self.run_calls += 1
        self.script(self)


class _PreLoopStopStream(_FakeStream):
    """alpaca-py's stop() reads _loop before run() has set it."""

    def stop(self) -> None:
        self.stop_calls += 1
        raise AttributeError("'NoneType' object has no attribute 'is_running'")


def _factory_for(fake: _FakeStream) -> Callable[..., StockDataStream]:
    def factory(api_key: str, secret_key: str, *, feed: DataFeed) -> StockDataStream:
        fake.credentials = (api_key, secret_key)
        fake.feed = feed
        return fake

    return factory


def _ignore_trade(tick: TradeTick) -> None:
    pass


def _ignore_quote(tick: QuoteTick) -> None:
    pass


def _make_feed(
    *,
    on_trade: Callable[[TradeTick], None] = _ignore_trade,
    on_quote: Callable[[QuoteTick], None] = _ignore_quote,
    stream: _FakeStream | None = None,
    tap: FeedTap | None = None,
    tap_symbols: tuple[str, ...] = (),
) -> tuple[AlpacaTickFeed, _FakeStream]:
    fake = stream if stream is not None else _FakeStream()
    extra: dict[str, Any] = {}
    if tap is not None:
        extra["tap"] = tap
    if tap_symbols:
        extra["tap_symbols"] = tap_symbols
    feed = AlpacaTickFeed(
        {"AAPL.ALPACA": _EQUITY},
        on_trade=on_trade,
        on_quote=on_quote,
        api_key=_TEST_API_KEY,
        secret_key=_TEST_API_CREDENTIAL,
        stream_factory=_factory_for(fake),
        **extra,
    )
    return feed, fake


def _trade(*, symbol: str = "AAPL", **overrides: Any) -> Trade:
    raw: dict[str, Any] = {
        "t": "2026-11-09T14:30:00.123456789Z",
        "p": 123.4567,
        "s": 100,
        "x": "NASDAQ",
        "i": 42,
        "c": ["@", "T"],
        "z": "C",
    }
    raw.update(overrides)
    return Trade(symbol, raw)


def _quote(*, symbol: str = "AAPL", **overrides: Any) -> Quote:
    raw: dict[str, Any] = {
        "t": "2026-11-09T14:30:00Z",
        "bp": 100.12,
        "bs": 3,
        "ap": 100.18,
        "as": 5,
    }
    raw.update(overrides)
    return Quote(symbol, raw)


def _deliver_trade(stream: _FakeStream, trade: Trade) -> None:
    assert stream.trade_handler is not None
    asyncio.run(stream.trade_handler(trade))


def _deliver_quote(stream: _FakeStream, quote: Quote) -> None:
    assert stream.quote_handler is not None
    asyncio.run(stream.quote_handler(quote))


def _handler_for(
    subscriptions: list[tuple[Callable[..., Any], tuple[str, ...]]], symbol: str
) -> Callable[..., Any]:
    for handler, symbols in reversed(subscriptions):
        if symbol in symbols:
            return handler
    raise AssertionError(f"no handler subscribed for {symbol}")


def _deliver_to(stream: _FakeStream, kind: str, symbol: str, message: Any) -> None:
    subscriptions = stream.trade_subscriptions if kind == "trade" else stream.quote_subscriptions
    asyncio.run(_handler_for(subscriptions, symbol)(message))


def test_trade_converts_to_exact_nautilus_tick() -> None:
    ticks: list[TradeTick] = []
    feed, stream = _make_feed(on_trade=ticks.append)
    feed.start()

    _deliver_trade(stream, _trade())

    assert len(ticks) == 1
    tick = ticks[0]
    assert tick.instrument_id == _EQUITY.id
    assert tick.price == Price.from_decimal_dp(Decimal("123.4567"), 4)
    assert tick.price.precision == 4
    assert tick.size == Quantity.from_int(100)
    assert tick.aggressor_side == AggressorSide.NO_AGGRESSOR
    assert tick.trade_id == TradeId("NASDAQ-42")
    assert tick.ts_event == _TRADE_TS
    assert feed.failure is None


def test_quote_converts_both_prices_at_the_same_precision() -> None:
    quotes: list[QuoteTick] = []
    feed, stream = _make_feed(on_quote=quotes.append)
    feed.start()

    _deliver_quote(stream, _quote())

    assert len(quotes) == 1
    tick = quotes[0]
    assert tick.instrument_id == _EQUITY.id
    assert tick.bid_price == Price.from_decimal_dp(Decimal("100.12"), 4)
    assert tick.ask_price == Price.from_decimal_dp(Decimal("100.18"), 4)
    assert tick.bid_price.precision == 4
    assert tick.ask_price.precision == 4
    assert tick.bid_size == Quantity.from_int(300)
    assert tick.ask_size == Quantity.from_int(500)
    assert tick.ts_event == _QUOTE_TS
    assert feed.failure is None


def test_init_time_comes_from_the_local_clock_not_event_time() -> None:
    trades: list[TradeTick] = []
    quotes: list[QuoteTick] = []
    feed, stream = _make_feed(on_trade=trades.append, on_quote=quotes.append)
    feed.start()

    before = time.time_ns()
    _deliver_trade(stream, _trade(t="2020-01-02T15:00:00Z"))
    _deliver_quote(stream, _quote(t="2020-01-02T15:00:00Z"))
    after = time.time_ns()

    assert len(trades) == 1
    assert len(quotes) == 1
    assert trades[0].ts_event == _FAR_PAST_TS
    assert quotes[0].ts_event == _FAR_PAST_TS
    assert before <= trades[0].ts_init <= after
    assert before <= quotes[0].ts_init <= after


def test_zero_lot_quote_converts_to_zero_shares() -> None:
    quotes: list[QuoteTick] = []
    feed, stream = _make_feed(on_quote=quotes.append)
    feed.start()

    _deliver_quote(stream, _quote(bs=0, **{"as": 0}))  # pyright: ignore[reportArgumentType]

    assert len(quotes) == 1
    assert quotes[0].bid_size == Quantity.from_int(0)
    assert quotes[0].ask_size == Quantity.from_int(0)
    assert feed.failure is None


@pytest.mark.parametrize(
    ("bid", "ask"),
    [
        (100.0, 100.0),
        (100.01, 100.0),
        (0.0, 100.0),
        (100.0, 0.0),
        (-1.0, 100.0),
        (100.0, -1.0),
    ],
)
def test_locked_crossed_or_non_positive_quote_is_skipped(bid: float, ask: float) -> None:
    quotes: list[QuoteTick] = []
    feed, stream = _make_feed(on_quote=quotes.append)
    feed.start()

    _deliver_quote(stream, _quote(bp=bid, ap=ask))

    assert quotes == []
    assert feed.failure is None
    assert stream.stop_ws_calls == 0


def test_iex_feed_is_refused() -> None:
    fake = _FakeStream()
    with pytest.raises(ValueError, match="SIP"):
        AlpacaTickFeed(
            {"AAPL.ALPACA": _EQUITY},
            on_trade=_ignore_trade,
            on_quote=_ignore_quote,
            api_key=_TEST_API_KEY,
            secret_key=_TEST_API_CREDENTIAL,
            feed="iex",
            stream_factory=_factory_for(fake),
        )
    assert fake.credentials is None


@pytest.mark.parametrize(
    ("api_key", "secret_key"),
    [("", _TEST_API_CREDENTIAL), (_TEST_API_KEY, "")],
)
def test_empty_credentials_are_refused(api_key: str, secret_key: str) -> None:
    fake = _FakeStream()
    with pytest.raises(ValueError, match="key and secret"):
        AlpacaTickFeed(
            {"AAPL.ALPACA": _EQUITY},
            on_trade=_ignore_trade,
            on_quote=_ignore_quote,
            api_key=api_key,
            secret_key=secret_key,
            stream_factory=_factory_for(fake),
        )
    assert fake.credentials is None


def test_callback_exception_sets_failure_and_requests_stop() -> None:
    def explode(tick: TradeTick) -> None:
        raise RuntimeError("callback failed")

    feed, stream = _make_feed(on_trade=explode)
    feed.start()

    _deliver_trade(stream, _trade())

    assert isinstance(feed.failure, RuntimeError)
    assert str(feed.failure) == "callback failed"
    assert stream.stop_ws_calls == 1


def test_start_subscribes_symbols_and_runs_the_stream() -> None:
    feed, stream = _make_feed()
    assert stream.credentials is None

    feed.start()

    assert stream.credentials == (_TEST_API_KEY, _TEST_API_CREDENTIAL)
    assert stream.feed is DataFeed.SIP
    assert stream.trade_symbols == ("AAPL",)
    assert stream.quote_symbols == ("AAPL",)
    assert stream.trade_handler is not None
    assert stream.quote_handler is not None
    assert stream.run_calls == 1
    assert feed.failure is None


def test_stop_delegates_to_the_stream() -> None:
    feed, stream = _make_feed()
    feed.start()

    feed.stop()

    assert stream.stop_calls == 1


def test_stop_before_start_is_a_noop() -> None:
    feed, stream = _make_feed()

    feed.stop()

    assert stream.stop_calls == 0
    assert feed.failure is None


def test_stop_ignores_the_pre_loop_attribute_error() -> None:
    feed, stream = _make_feed(stream=_PreLoopStopStream())
    feed.start()

    feed.stop()

    assert stream.stop_calls == 1
    assert feed.failure is None


def test_mapping_key_must_match_the_instrument_id() -> None:
    fake = _FakeStream()
    with pytest.raises(ValueError, match="does not match"):
        AlpacaTickFeed(
            {"MSFT.ALPACA": _EQUITY},
            on_trade=_ignore_trade,
            on_quote=_ignore_quote,
            api_key=_TEST_API_KEY,
            secret_key=_TEST_API_CREDENTIAL,
            stream_factory=_factory_for(fake),
        )
    assert fake.credentials is None


# -- BOATS overnight: REST polling through an injected fake data client ----------------------

_NOW_S = 1_794_272_400.25  # 2026-11-10T01:00:00.25Z, 20:00:00.25 ET
_NOW_NS = 1_794_272_400_250_000_000
_AT_57 = 1_794_272_397_000_000_000  # 00:59:57Z
_AT_58 = 1_794_272_398_000_000_000
_AT_59 = 1_794_272_399_000_000_000
_MSFT = Equity(
    InstrumentId.from_str("MSFT.ALPACA"),
    Symbol("MSFT"),
    Currency.from_str("USD"),
    2,
    Price.from_str("0.01"),
    0,
    0,
    lot_size=Quantity.from_int(1),
)
_Rows = dict[str, list[dict[str, Any]]]


def _noop() -> None:
    pass


class _FakeDataClient:
    """StockHistoricalDataClient(raw_data=True) stand-in: records requests, opens no socket.

    Poll n answers ``polls[n]`` as raw rows ``{symbol: [row, ...]}``, the shape alpaca-py
    0.44's ``_get_marketdata`` returns; later polls answer empty. After ``stop_after`` polls it
    calls ``stop``.
    """

    def __init__(self, *polls: tuple[_Rows, _Rows], stop_after: int = 0) -> None:
        self.polls = polls
        self.stop_after = stop_after
        self.stop: Callable[[], None] = _noop
        self.credentials: tuple[str, str] | None = None
        self.raw_data: bool | None = None
        self.trade_requests: list[StockTradesRequest] = []
        self.quote_requests: list[StockQuotesRequest] = []
        self.polled = threading.Event()

    def get_stock_trades(self, request: StockTradesRequest) -> _Rows:
        self.trade_requests.append(request)
        return self._answer(len(self.trade_requests), 0)

    def get_stock_quotes(self, request: StockQuotesRequest) -> _Rows:
        self.quote_requests.append(request)
        return self._answer(len(self.quote_requests), 1)

    def _answer(self, count: int, side: int) -> _Rows:
        self.polled.set()
        done = min(len(self.trade_requests), len(self.quote_requests))
        if self.stop_after and done >= self.stop_after:
            self.stop()
        return self.polls[count - 1][side] if count <= len(self.polls) else {}


class _FailingDataClient(_FakeDataClient):
    def get_stock_trades(self, request: StockTradesRequest) -> _Rows:
        raise ConnectionError("data API unreachable")


def _boats_feed(
    client: _FakeDataClient,
    *,
    on_trade: Callable[[TradeTick], None] = _ignore_trade,
    on_quote: Callable[[QuoteTick], None] = _ignore_quote,
    feed: str = "boats",
    poll_interval_s: float = 0.001,
    instruments: dict[str, Equity] | None = None,
    clock: Callable[[], float] = lambda: _NOW_S,
) -> AlpacaTickFeed:
    def factory(*, api_key: str, secret_key: str, raw_data: bool) -> _FakeDataClient:
        client.credentials = (api_key, secret_key)
        client.raw_data = raw_data
        return client

    tick_feed = AlpacaTickFeed(
        instruments or {"AAPL.ALPACA": _EQUITY},
        on_trade=on_trade,
        on_quote=on_quote,
        api_key=_TEST_API_KEY,
        secret_key=_TEST_API_CREDENTIAL,
        feed=feed,
        poll_interval_s=poll_interval_s,
        data_client_factory=factory,
        clock=clock,
    )
    client.stop = tick_feed.stop
    return tick_feed


def _row_trade(t: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"t": t, "p": 123.4567, "s": 100, "x": "NASDAQ", "i": 42}
    return row | {"c": ["@"], "z": "C"} | overrides


def _row_quote(t: str, **overrides: Any) -> dict[str, Any]:
    return {"t": t, "bp": 100.12, "bs": 3, "ap": 100.18, "as": 5} | overrides


@pytest.mark.parametrize("name", ["iex", "overnight", "delayed_sip"])
def test_feeds_other_than_sip_and_boats_are_refused(name: str) -> None:
    client = _FakeDataClient()
    with pytest.raises(ValueError, match="SIP"):
        _boats_feed(client, feed=name)
    assert client.credentials is None


def test_one_boats_poll_sends_one_batched_trades_and_one_batched_quotes_request() -> None:
    client = _FakeDataClient(stop_after=1)
    feed = _boats_feed(client, instruments={"MSFT.ALPACA": _MSFT, "AAPL.ALPACA": _EQUITY})

    feed.start()

    assert client.credentials == (_TEST_API_KEY, _TEST_API_CREDENTIAL)
    assert client.raw_data is True
    assert len(client.trade_requests) == 1
    assert len(client.quote_requests) == 1
    for request in (client.trade_requests[0], client.quote_requests[0]):
        assert request.symbol_or_symbols == ["AAPL", "MSFT"]
        assert request.feed is DataFeed.BOATS
        assert request.start == datetime(2026, 11, 10, 0, 59, 50, 250_000)
        assert request.end == datetime(2026, 11, 10, 1, 0, 0, 250_000)
    assert feed.failure is None


def test_boats_polls_deliver_each_print_once() -> None:
    trades: list[TradeTick] = []
    quotes: list[QuoteTick] = []
    numbered = _row_trade("2026-11-10T00:59:57.5Z")
    unnumbered = _row_trade("2026-11-10T00:59:58Z", i=None)
    second_unnumbered = _row_trade("2026-11-10T00:59:58Z", i=None, p=123.5)
    new = _row_trade("2026-11-10T00:59:59Z", i=43)
    quote = _row_quote("2026-11-10T00:59:57Z")
    new_quote = _row_quote("2026-11-10T00:59:59Z", ap=100.19)
    client = _FakeDataClient(
        ({"AAPL": [numbered, unnumbered]}, {"AAPL": [quote]}),
        ({"AAPL": [numbered, unnumbered, second_unnumbered, new]}, {"AAPL": [quote, new_quote]}),
        stop_after=2,
    )
    feed = _boats_feed(client, on_trade=trades.append, on_quote=quotes.append)

    feed.start()

    assert len(client.trade_requests) == 2
    assert [(tick.ts_event, str(tick.price)) for tick in trades] == [
        (1_794_272_397_500_000_000, "123.4567"),
        (_AT_58, "123.4567"),
        (_AT_58, "123.5000"),
        (_AT_59, "123.4567"),
    ]
    assert [(tick.ts_event, str(tick.ask_price)) for tick in quotes] == [
        (_AT_57, "100.1800"),
        (_AT_59, "100.1900"),
    ]


def test_boats_trade_converts_to_an_exact_native_tick() -> None:
    trades: list[TradeTick] = []
    client = _FakeDataClient(
        ({"AAPL": [_row_trade("2026-11-10T00:59:58.123456789Z")]}, {}), stop_after=1
    )

    _boats_feed(client, on_trade=trades.append).start()

    assert len(trades) == 1
    tick = trades[0]
    assert tick.instrument_id == _EQUITY.id
    assert tick.price == Price.from_decimal_dp(Decimal("123.4567"), 4)
    assert tick.price.precision == 4
    assert tick.size == Quantity.from_int(100)
    assert tick.ts_event == 1_794_272_398_123_456_000
    assert tick.ts_init == _NOW_NS


def test_boats_quote_converts_round_lots_to_shares() -> None:
    quotes: list[QuoteTick] = []
    client = _FakeDataClient(({}, {"AAPL": [_row_quote("2026-11-10T00:59:57Z")]}), stop_after=1)

    _boats_feed(client, on_quote=quotes.append).start()

    assert len(quotes) == 1
    tick = quotes[0]
    assert tick.instrument_id == _EQUITY.id
    assert tick.bid_price == Price.from_decimal_dp(Decimal("100.12"), 4)
    assert tick.ask_price == Price.from_decimal_dp(Decimal("100.18"), 4)
    assert tick.bid_price.precision == 4
    assert tick.bid_size == Quantity.from_int(300)
    assert tick.ask_size == Quantity.from_int(500)
    assert tick.ts_event == _AT_57
    assert tick.ts_init == _NOW_NS


def test_boats_poll_delivers_trades_and_quotes_in_vendor_time_order() -> None:
    events: list[tuple[str, int]] = []
    quotes = [
        _row_quote("2026-11-10T00:59:59Z", bp=100.14),
        _row_quote("2026-11-10T00:59:57Z"),
        _row_quote("2026-11-10T00:59:58Z", bp=100.13),
    ]
    client = _FakeDataClient(
        ({"AAPL": [_row_trade("2026-11-10T00:59:58Z")]}, {"AAPL": quotes}), stop_after=1
    )

    _boats_feed(
        client,
        on_trade=lambda tick: events.append(("trade", tick.ts_event)),
        on_quote=lambda tick: events.append(("quote", tick.ts_event)),
    ).start()

    # At one vendor time the trade goes first, so it meets the quote that prevailed before it.
    assert events == [("quote", _AT_57), ("trade", _AT_58), ("quote", _AT_58), ("quote", _AT_59)]


def test_a_clock_step_back_never_redelivers_a_pruned_print() -> None:
    trades: list[TradeTick] = []
    readings = iter([0.0, 0.0, 20.0, 20.0, 0.0, 0.0])  # two reads a poll: 20 s on, then back
    rows: _Rows = {"AAPL": [_row_trade("2026-11-10T00:59:51Z")]}
    client = _FakeDataClient((rows, {}), ({}, {}), (rows, {}), stop_after=3)
    feed = _boats_feed(client, on_trade=trades.append, clock=lambda: _NOW_S + next(readings))

    feed.start()

    assert len(client.trade_requests) == 3
    assert [tick.ts_event for tick in trades] == [1_794_272_391_000_000_000]


def test_stop_interrupts_a_running_boats_poll_during_its_sleep() -> None:
    client = _FakeDataClient()
    feed = _boats_feed(client, poll_interval_s=1.0)
    runner = threading.Thread(target=feed.start, daemon=True)
    runner.start()
    assert client.polled.wait(1.0)

    feed.stop()
    runner.join(timeout=0.5)

    assert not runner.is_alive()
    assert feed.failure is None


def test_stop_before_start_is_a_noop_for_boats() -> None:
    client = _FakeDataClient()
    feed = _boats_feed(client)

    feed.stop()
    feed.stop()

    assert client.credentials is None
    assert client.trade_requests == []
    assert client.quote_requests == []
    assert feed.failure is None


def test_a_failed_boats_request_is_recorded_and_raised() -> None:
    feed = _boats_feed(_FailingDataClient())

    with pytest.raises(ConnectionError, match="unreachable"):
        feed.start()

    assert isinstance(feed.failure, ConnectionError)


@pytest.mark.parametrize("poll_interval_s", [0.0, -1.0, 10.0])
def test_boats_cadence_must_be_positive_and_inside_the_window(poll_interval_s: float) -> None:
    with pytest.raises(ValueError, match="poll_interval_s"):
        _boats_feed(_FakeDataClient(), poll_interval_s=poll_interval_s)


def test_the_default_cadence_is_the_registry_feed_poll_interval() -> None:
    registry = Path(__file__).parents[2] / "lanes/paper/b-parameters.json"
    row = next(r for r in json.loads(registry.read_text()) if r["name"] == "feed_poll_interval_s")
    default = inspect.signature(AlpacaTickFeed).parameters["poll_interval_s"].default

    assert Decimal(str(default)) == Decimal(row["value"])


def test_a_breach_drops_only_measurement_subscriptions_and_pages_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = _Now(_T0)
    tap = FeedTap(tmp_path / "feed-tap.jsonl", time_ns=now, perf_ns=lambda: 0, flush_s=0.01)
    trades: list[TradeTick] = []

    def script(stream: _FakeStream) -> None:
        now.value = _T0 + 2 * _S
        _deliver_to(stream, "trade", "AAPL", _trade())
        now.value = _T0 + 3 * _S
        _deliver_to(stream, "trade", "AAPL", _trade())
        deadline = time.monotonic() + 2.0
        while not stream.unsubscribed and time.monotonic() < deadline:
            time.sleep(0.01)

    stream = _ScriptedStream(script)
    feed, _ = _make_feed(
        on_trade=trades.append,
        tap=tap,
        tap_symbols=("EXTRA",),
        stream=stream,
    )

    feed.start()

    page = capsys.readouterr().err
    assert page.count("feed tap guard") == 1
    assert "drop requested" in page
    assert ("trades", ("EXTRA",)) in stream.unsubscribed
    assert ("quotes", ("EXTRA",)) in stream.unsubscribed
    assert all("AAPL" not in symbols for _, symbols in stream.unsubscribed)
    assert ("AAPL",) in [symbols for _, symbols in stream.trade_subscriptions]
    assert ("EXTRA",) in [symbols for _, symbols in stream.trade_subscriptions]
    assert len(trades) == 2
    assert feed.failure is None


def test_measurement_symbols_stay_subscribed_inside_the_bound(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = _Now(_T0)
    tap = FeedTap(tmp_path / "feed-tap.jsonl", time_ns=now, perf_ns=lambda: 0, flush_s=0.01)

    def script(stream: _FakeStream) -> None:
        _deliver_to(stream, "trade", "AAPL", _trade())
        now.value = _T0 + _S
        _deliver_to(stream, "trade", "AAPL", _trade())
        time.sleep(0.6)

    stream = _ScriptedStream(script)
    feed, _ = _make_feed(
        tap=tap,
        tap_symbols=("EXTRA",),
        stream=stream,
    )

    feed.start()

    assert "feed tap guard" not in capsys.readouterr().err
    assert stream.unsubscribed == []
    assert ("EXTRA",) in [symbols for _, symbols in stream.trade_subscriptions]
    assert feed.failure is None
