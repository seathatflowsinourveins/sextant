"""Proofs for the live Alpaca SIP tick feed; the stream is injected, so no network."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from alpaca.data.enums import DataFeed
from alpaca.data.live import StockDataStream
from alpaca.data.models.quotes import Quote
from alpaca.data.models.trades import Trade
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

_TRADE_TS = 1_794_234_600_123_456_000
_QUOTE_TS = 1_794_234_600_000_000_000
_FAR_PAST_TS = 1_577_977_200_000_000_000
_TEST_API_KEY = "test-key"
_TEST_API_CREDENTIAL = "test-credential"
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
        self.run_calls = 0
        self.stop_calls = 0
        self.stop_ws_calls = 0

    def subscribe_trades(self, handler: Callable[..., Any], *symbols: str) -> None:
        self.trade_handler = handler
        self.trade_symbols = symbols

    def subscribe_quotes(self, handler: Callable[..., Any], *symbols: str) -> None:
        self.quote_handler = handler
        self.quote_symbols = symbols

    def run(self) -> None:
        self.run_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

    async def stop_ws(self) -> None:
        self.stop_ws_calls += 1


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
) -> tuple[AlpacaTickFeed, _FakeStream]:
    fake = stream if stream is not None else _FakeStream()
    feed = AlpacaTickFeed(
        {"AAPL.ALPACA": _EQUITY},
        on_trade=on_trade,
        on_quote=on_quote,
        api_key=_TEST_API_KEY,
        secret_key=_TEST_API_CREDENTIAL,
        stream_factory=_factory_for(fake),
    )
    return feed, fake


def _trade(**overrides: Any) -> Trade:
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
    return Trade("AAPL", raw)


def _quote(**overrides: Any) -> Quote:
    raw: dict[str, Any] = {
        "t": "2026-11-09T14:30:00Z",
        "bp": 100.12,
        "bs": 3,
        "ap": 100.18,
        "as": 5,
    }
    raw.update(overrides)
    return Quote("AAPL", raw)


def _deliver_trade(stream: _FakeStream, trade: Trade) -> None:
    assert stream.trade_handler is not None
    asyncio.run(stream.trade_handler(trade))


def _deliver_quote(stream: _FakeStream, quote: Quote) -> None:
    assert stream.quote_handler is not None
    asyncio.run(stream.quote_handler(quote))


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

    _deliver_quote(stream, _quote(bs=0, **{"as": 0}))

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
