"""Proofs for the read-only feed tap and its smallest sidecar writer.

The tap observes C's SIP handlers: per-second trade/quote counts and distinct
symbols, the wall-clock receipt lag ``time.time_ns() - ts_event`` (count, p99,
p99.9, exact max), handler service time (sum and max), feed failures, and per
symbol's longest inter-arrival gap. The handler path takes no lock and writes no
file; the sidecar carries anonymous counts and the worst gap, never ticker names.
These proofs use scripted clocks and a fake stream: no socket, no broker, no key.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alpaca.data.enums import DataFeed
from alpaca.data.live import StockDataStream
from alpaca.data.models.quotes import Quote
from alpaca.data.models.trades import Trade
from nautilus_trader.model import (
    Currency,
    Equity,
    InstrumentId,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    TradeTick,
)

import sextant.paper.alpaca_feed as feed_module
import sextant.paper.feed_tap as tap_module
from sextant.paper.alpaca_feed import AlpacaTickFeed
from sextant.paper.feed_tap import FeedTap, FeedTapToken

_S = 1_000_000_000
_MS = 1_000_000
_T0 = 1_794_234_600 * _S

# Module constants rather than inline literals: ruff's S105 flags the latter.
_TEST_KEY = "test-key"
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


class _Clock:
    """A scripted integer clock; an unscripted read fails the test instead of guessing."""

    def __init__(self, *readings: int) -> None:
        self._readings = list(readings)
        self.calls = 0

    def __call__(self) -> int:
        self.calls += 1
        if not self._readings:
            raise AssertionError("clock read past the script")
        return self._readings.pop(0)


class _Now:
    """A mutable shared wall clock: the writer thread and the test read the same second."""

    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


class _CountingClock:
    """The feed's own clock, counting calls so the proof can compare them across runs."""

    def __init__(self, start_ns: int) -> None:
        self.start_ns = start_ns
        self.calls = 0

    def __call__(self) -> int:
        value = self.start_ns + self.calls
        self.calls += 1
        return value


def _tap(
    *,
    path: Path | None = None,
    time_ns: Callable[[], int] | None = None,
    perf_ns: Callable[[], int] | None = None,
    flush_s: float = 0.25,
    pending: int = 120,
) -> FeedTap:
    return FeedTap(
        path=path,
        time_ns=time_ns if time_ns is not None else _Clock(),
        perf_ns=perf_ns if perf_ns is not None else _Clock(),
        flush_s=flush_s,
        pending=pending,
    )


def _message(tap: FeedTap, kind: str, symbol: str, ts_event_ns: int | None) -> FeedTapToken | None:
    entry = tap.trade_entry if kind == "trade" else tap.quote_entry
    token = entry(symbol, ts_event_ns)
    tap.finish(token)
    return token


def _ignored(tick: Any) -> None:
    pass


# -- the observer: counters, receipt lag, service, failures, gaps -----------------------------


def test_a_second_records_counts_lag_percentiles_service_and_failures() -> None:
    tap = _tap(
        time_ns=_Clock(
            _T0 + 5 * _MS,
            _T0 + 15 * _MS,
            _T0 + 30 * _MS,
            _T0 + 41 * _MS,
        ),
        perf_ns=_Clock(1_000, 2_000, 1_000, 4_000, 1_000, 3_000, 1_000, 5_000),
    )
    # Receipt lags: 5, 15, 30 and 41 ms at handler entry.
    _message(tap, "trade", "AAPL", _T0)
    _message(tap, "trade", "AAPL", _T0)
    _message(tap, "trade", "MSFT", _T0)
    _message(tap, "quote", "AAPL", _T0)

    records = tap.take(_T0 + _S)

    assert len(records) == 1
    record = records[0]
    assert record["kind"] == "second"
    assert record["second"] == _T0 // _S
    assert record["partial"] is False
    assert record["trades"] == 3
    assert record["quotes"] == 1
    assert record["symbols_seen"] == 2
    assert record["lag_ns"] == {
        "count": 4,
        "p99": 41 * _MS,
        "p999": 41 * _MS,
        "max": 41 * _MS,
    }
    assert record["service_ns"] == {"sum": 10_000, "max": 4_000}
    assert record["failures"] == 0
    # The per-second line never carries a symbol name; the final line carries per-symbol totals.
    assert "AAPL" not in repr(record)


def test_a_lag_that_is_not_positive_is_ignored() -> None:
    tap = _tap(time_ns=_Clock(_T0), perf_ns=_Clock(0, 0))
    _message(tap, "trade", "AAPL", _T0 + 5 * _MS)

    record = tap.take(_T0 + _S)[0]

    assert record["lag_ns"] == {"count": 0, "p99": None, "p999": None, "max": None}
    assert record["trades"] == 1


def test_percentiles_never_invent_a_value() -> None:
    tap = _tap(time_ns=_Clock(_T0 + 10 * _MS), perf_ns=_Clock(0, 0))
    _message(tap, "trade", "AAPL", _T0)

    assert tap.take(_T0 + _S)[0]["lag_ns"] == {
        "count": 1,
        "p99": 10 * _MS,
        "p999": 10 * _MS,
        "max": 10 * _MS,
    }


def test_a_message_late_for_a_flushed_second_gets_its_own_line() -> None:
    tap = _tap(time_ns=_Clock(_T0, _T0 + _S, _T0 + 2 * _MS), perf_ns=_Clock(0, 0, 0, 0, 0, 0))
    _message(tap, "trade", "AAPL", _T0)
    _message(tap, "trade", "MSFT", _T0 + _S)

    first = tap.take(_T0 + 2 * _S)
    assert [record["second"] for record in first] == [_T0 // _S, _T0 // _S + 1]

    _message(tap, "trade", "AAPL", _T0 + 2 * _MS)
    second = tap.take(_T0 + 3 * _S)

    assert [record["second"] for record in second] == [_T0 // _S]
    assert second[0]["trades"] == 1


def test_a_callback_still_running_never_loses_its_sample() -> None:
    tap = _tap(time_ns=_Clock(_T0), perf_ns=_Clock(0, 2_000))
    token = tap.trade_entry("AAPL", _T0)

    assert tap.take(_T0 + 2 * _S) == []

    tap.finish(token)

    records = tap.take(_T0 + 3 * _S)
    assert len(records) == 1
    assert records[0]["trades"] == 1
    assert records[0]["service_ns"]["max"] == 2_000


def test_a_feed_failure_counts_each_event_and_gets_its_own_line() -> None:
    tap = _tap(time_ns=_Clock(_T0, _T0))
    tap.observe_failure()
    tap.observe_failure()

    record = tap.take(_T0 + _S)[0]

    assert record["failures"] == 2
    assert record["trades"] == 0
    assert record["lag_ns"]["count"] == 0


def test_no_second_is_recorded_without_a_message_or_a_failure() -> None:
    assert _tap().take(_T0 + 10 * _S) == []


def test_a_forced_take_marks_the_open_second_partial() -> None:
    now = _Now(_T0)
    tap = _tap(time_ns=now, perf_ns=_Clock(0, 0))
    _message(tap, "trade", "AAPL", _T0)

    records = tap.take(now(), force=True)

    assert records[0]["partial"] is True


def test_the_percentile_is_the_bin_lower_edge_not_its_exclusive_edge() -> None:
    tap = _tap(time_ns=_Clock(_T0 + 999_999_999), perf_ns=_Clock(0, 0))
    _message(tap, "trade", "AAPL", _T0)

    lag = tap.take(_T0 + _S)[0]["lag_ns"]

    # A 0.999999999 s lag sits in the 999 ms bin; its lower edge satisfies < 1 s.
    assert lag["p99"] == 999 * _MS
    assert lag["p999"] == 999 * _MS
    assert lag["max"] == 999_999_999


def test_the_handler_path_takes_no_shared_lock() -> None:
    source = inspect.getsource(tap_module)

    assert "Lock(" not in source
    assert "_lock" not in vars(FeedTap())


def test_a_sidecar_that_cannot_open_never_stops_the_feed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")
    tap = FeedTap(blocker / "feed-tap.jsonl", time_ns=_Now(_T0), perf_ns=_Clock())
    _feed_clock(monkeypatch, _CountingClock(_T0))
    feed, fake = _wire_feed(tap=tap)

    feed.start()

    assert fake.run_calls == 1
    assert fake.trade_symbols == ("AAPL",)
    assert tap.init_errors == 1
    feed.stop()
    assert not (blocker / "feed-tap.jsonl").exists()


def test_retention_is_bounded_and_overflow_is_counted() -> None:
    now = _Now(_T0)
    tap = _tap(time_ns=now, perf_ns=_Clock(*([0] * 20)), pending=2)
    tap.start()
    for step in range(5):
        now.value = _T0 + step * _S
        _message(tap, "trade", "AAPL", now.value)

    tap.stop()

    assert tap.pending <= 2
    assert tap.dropped_buckets == 3


def test_a_stuck_writer_never_blocks_the_handler_and_its_drops_are_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = _Now(_T0)
    release = threading.Event()
    tap = FeedTap(
        tmp_path / "feed-tap.jsonl",
        time_ns=now,
        perf_ns=_Clock(*([0] * 40)),
        flush_s=0.01,
        pending=2,
    )
    tap.start()
    monkeypatch.setattr(tap, "_write", lambda record: release.wait(5))

    started = time.monotonic()
    for step in range(6):
        now.value = _T0 + step * _S
        _message(tap, "trade", "AAPL", now.value)
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert tap.dropped_buckets >= 1

    release.set()
    tap.stop()


def test_stop_waits_for_the_handler_before_it_writes_the_sidecar(tmp_path: Path) -> None:
    now = _Now(_T0)
    path = tmp_path / "feed-tap.jsonl"
    tap = FeedTap(path, time_ns=now, perf_ns=_Clock(0, 5_000_000), flush_s=0.01)
    tap.start()
    token = tap.trade_entry("AAPL", _T0)

    stopper = threading.Thread(target=tap.stop)
    stopper.start()
    time.sleep(0.05)
    assert stopper.is_alive()

    tap.finish(token)
    stopper.join(5.0)

    assert not stopper.is_alive()
    assert _lines(path)[0]["service_ns"] == {"sum": 5_000_000, "max": 5_000_000}


# -- the sidecar: each closed second, then the per-symbol freshness line ---------------------


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_the_sidecar_writes_each_closed_second_then_the_symbols_line(tmp_path: Path) -> None:
    now = _Now(_T0)
    path = tmp_path / "feed-tap.jsonl"
    tap = FeedTap(path, time_ns=now, perf_ns=_Clock(0, 1, 2, 3, 4, 5), flush_s=0.01)
    tap.start()
    _message(tap, "trade", "AAPL", _T0)
    _message(tap, "trade", "AAPL", _T0 + 100 * _MS)
    now.value = _T0 + _S
    _message(tap, "trade", "MSFT", _T0 + _S)
    now.value = _T0 + 5 * _S

    tap.stop()

    lines = _lines(path)
    seconds = [line for line in lines if line["kind"] == "second"]
    assert [line["second"] for line in seconds] == [_T0 // _S, _T0 // _S + 1]
    assert [line["trades"] for line in seconds] == [2, 1]
    final = lines[-1]
    assert final["kind"] == "symbols"
    assert final["symbols_seen"] == 2
    assert final["symbols_with_gap"] == 1
    assert final["max_gap_ns"] == 100 * _MS
    assert final["dropped_buckets"] == 0
    assert final["write_errors"] == 0
    assert final["reconnects"] is None
    text = path.read_text()
    assert "AAPL" not in text and "MSFT" not in text


def test_stop_is_idempotent_and_closes_the_sidecar(tmp_path: Path) -> None:
    now = _Now(_T0)
    path = tmp_path / "feed-tap.jsonl"
    tap = FeedTap(path, time_ns=now, perf_ns=_Clock(0, 0), flush_s=0.01)
    tap.start()
    _message(tap, "trade", "AAPL", _T0)

    tap.stop()
    tap.stop()

    assert [line["kind"] for line in _lines(path)] == ["second", "symbols"]


def test_starting_twice_is_refused(tmp_path: Path) -> None:
    tap = FeedTap(tmp_path / "feed-tap.jsonl", time_ns=_Now(_T0), perf_ns=_Clock())
    tap.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            tap.start()
    finally:
        tap.stop()


@pytest.mark.skipif(not Path("/dev/full").exists(), reason="needs /dev/full")
def test_a_sidecar_write_error_never_escapes_into_the_feed() -> None:
    now = _Now(_T0)
    tap = FeedTap(Path("/dev/full"), time_ns=now, perf_ns=_Clock(0, 0), flush_s=0.01)
    tap.start()
    _message(tap, "trade", "AAPL", _T0)
    now.value = _T0 + 2 * _S

    tap.stop()

    assert tap.write_errors >= 1


# -- the feed wiring: default OFF, identical clocks, one socket, no order path ----------------


class _FakeStream(StockDataStream):
    """A stream stand-in that records calls; it never opens a socket."""

    def __init__(self) -> None:
        self.trade_handler: Callable[..., Any] | None = None
        self.quote_handler: Callable[..., Any] | None = None
        self.trade_symbols: tuple[str, ...] = ()
        self.quote_symbols: tuple[str, ...] = ()
        self.during_run: Callable[[], None] | None = None
        self.run_calls = 0
        self.stop_calls = 0

    def subscribe_trades(self, handler: Callable[..., Any], *symbols: str) -> None:
        self.trade_handler = handler
        self.trade_symbols = symbols

    def subscribe_quotes(self, handler: Callable[..., Any], *symbols: str) -> None:
        self.quote_handler = handler
        self.quote_symbols = symbols

    def run(self) -> None:
        self.run_calls += 1
        if self.during_run is not None:
            self.during_run()

    def stop(self) -> None:
        self.stop_calls += 1

    async def stop_ws(self) -> None:
        pass


class _ExplodingStream(_FakeStream):
    def run(self) -> None:
        raise ConnectionError("socket closed")


def _factory_for(fake: _FakeStream) -> Callable[..., StockDataStream]:
    def factory(api_key: str, secret_key: str, *, feed: DataFeed) -> StockDataStream:
        return fake

    return factory


def _wire_feed(
    *,
    tap: FeedTap | None = None,
    stream: _FakeStream | None = None,
    during_run: Callable[[], None] | None = None,
    on_trade: Callable[[TradeTick], None] = _ignored,
    on_quote: Callable[[QuoteTick], None] = _ignored,
) -> tuple[AlpacaTickFeed, _FakeStream]:
    fake = stream if stream is not None else _FakeStream()
    fake.during_run = during_run
    feed = AlpacaTickFeed(
        {"AAPL.ALPACA": _EQUITY},
        on_trade=on_trade,
        on_quote=on_quote,
        api_key=_TEST_KEY,
        secret_key=_TEST_API_CREDENTIAL,
        stream_factory=_factory_for(fake),
        tap=tap,
    )
    return feed, fake


def _trade() -> Trade:
    return Trade(
        "AAPL",
        {"t": "2026-11-09T14:30:00Z", "p": 123.4567, "s": 100, "x": "NASDAQ", "i": 42},
    )


def _quote() -> Quote:
    return Quote(
        "AAPL", {"t": "2026-11-09T14:30:00Z", "bp": 100.12, "bs": 3, "ap": 100.18, "as": 5}
    )


def _deliver(fake: _FakeStream, message: Any, *, quote: bool = False) -> None:
    handler = fake.quote_handler if quote else fake.trade_handler
    assert handler is not None
    asyncio.run(handler(message))


def _view(tick: Any) -> tuple[Any, ...]:
    return (
        str(tick.instrument_id),
        str(tick.ts_event),
        str(tick.ts_init),
        str(getattr(tick, "price", None)),
        str(getattr(tick, "bid_price", None)),
        str(getattr(tick, "ask_price", None)),
        str(getattr(tick, "trade_id", None)),
    )


def _feed_clock(monkeypatch: pytest.MonkeyPatch, clock: Callable[[], int]) -> None:
    monkeypatch.setattr(feed_module, "time", SimpleNamespace(time_ns=clock, time=time.time))


def test_the_token_carries_only_what_finish_reads() -> None:
    assert FeedTapToken._fields == ("second", "ts_event_ns", "entry_ns", "perf_ns")


def test_a_naive_trade_timestamp_inside_the_tap_takes_the_failure_path() -> None:
    tap = _tap(time_ns=_Now(_T0), perf_ns=_Clock())
    feed, _ = _wire_feed(tap=tap)
    naive = Trade("AAPL", {"t": "2026-11-09T14:30:00", "p": 1.0, "s": 100, "x": "NASDAQ", "i": 7})

    asyncio.run(feed._handle_trade(naive))

    assert isinstance(feed.failure, ValueError)
    assert tap.failures == 1


def test_a_naive_quote_timestamp_inside_the_tap_takes_the_failure_path() -> None:
    tap = _tap(time_ns=_Now(_T0), perf_ns=_Clock())
    feed, _ = _wire_feed(tap=tap)
    naive = Quote(
        "AAPL", {"t": "2026-11-09T14:30:00", "bp": 100.12, "bs": 3, "ap": 100.18, "as": 5}
    )

    asyncio.run(feed._handle_quote(naive))

    assert isinstance(feed.failure, ValueError)
    assert tap.failures == 1


def test_a_feed_without_the_tap_delivers_identically_and_reads_the_clock_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trades_seen: list[Any] = []
    quotes_seen: list[Any] = []

    def run(tap: FeedTap | None) -> tuple[list[Any], list[Any], int]:
        clock = _CountingClock(_T0)
        _feed_clock(monkeypatch, clock)
        trades_seen.clear()
        quotes_seen.clear()
        feed, fake = _wire_feed(tap=tap, on_trade=trades_seen.append, on_quote=quotes_seen.append)

        def deliver() -> None:
            _deliver(fake, _trade())
            _deliver(fake, _quote(), quote=True)

        fake.during_run = deliver
        feed.start()
        feed.stop()
        return (
            [_view(tick) for tick in trades_seen],
            [_view(tick) for tick in quotes_seen],
            clock.calls,
        )

    plain = run(None)
    assert list(tmp_path.iterdir()) == []
    tapped = run(FeedTap(tmp_path / "feed-tap.jsonl"))

    assert tapped == plain
    assert plain[2] == 2


def test_the_sidecar_carries_the_handlers_the_feed_delivered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _feed_clock(monkeypatch, _CountingClock(_T0))
    path = tmp_path / "feed-tap.jsonl"
    tap = FeedTap(path, time_ns=_Now(_T0), perf_ns=_Clock(0, 0, 0, 0))
    feed, fake = _wire_feed(tap=tap)

    def deliver() -> None:
        _deliver(fake, _trade())
        _deliver(fake, _quote(), quote=True)

    fake.during_run = deliver
    feed.start()
    feed.stop()

    lines = _lines(path)
    assert lines[-1]["kind"] == "symbols"
    assert lines[-1]["symbols_seen"] == 1
    assert lines[-1]["max_gap_ns"] is None
    assert lines[0]["trades"] == 1
    assert lines[0]["quotes"] == 1
    assert lines[0]["symbols_seen"] == 1


def test_the_tap_never_changes_the_subscription_or_the_stream_count() -> None:
    tap = FeedTap()
    feed, fake = _wire_feed(tap=tap)

    feed.start()

    assert fake.trade_symbols == ("AAPL",)
    assert fake.quote_symbols == ("AAPL",)
    assert fake.run_calls == 1


def test_a_boats_feed_refuses_the_tap() -> None:
    with pytest.raises(ValueError, match="tap"):
        AlpacaTickFeed(
            {"AAPL.ALPACA": _EQUITY},
            on_trade=_ignored,
            on_quote=_ignored,
            api_key=_TEST_KEY,
            secret_key=_TEST_API_CREDENTIAL,
            feed="boats",
            tap=FeedTap(),
        )


def test_a_failing_callback_still_records_its_service_and_the_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _feed_clock(monkeypatch, _CountingClock(_T0))
    path = tmp_path / "feed-tap.jsonl"
    tap = FeedTap(path, time_ns=_Now(_T0), perf_ns=_Clock(0, 2_000))

    def explode(tick: TradeTick) -> None:
        raise RuntimeError("callback failed")

    feed, fake = _wire_feed(tap=tap, on_trade=explode)

    def deliver() -> None:
        _deliver(fake, _trade())

    fake.during_run = deliver
    feed.start()

    record = _lines(path)[0]
    assert record["trades"] == 1
    assert record["service_ns"]["max"] > 0
    assert record["failures"] == 1
    assert isinstance(feed.failure, RuntimeError)
    feed.stop()


def test_the_receipt_lag_is_read_at_handler_entry_not_from_ts_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _feed_clock(monkeypatch, _CountingClock(_T0 + 9 * _MS))
    path = tmp_path / "feed-tap.jsonl"
    tap = FeedTap(path, time_ns=_Now(_T0 + 7 * _MS), perf_ns=_Clock(0, 0))
    feed, fake = _wire_feed(tap=tap)

    def deliver() -> None:
        _deliver(fake, _trade())

    fake.during_run = deliver
    feed.start()

    record = _lines(path)[0]

    # The tap read its wall clock at 7 ms; the tick carried ts_init at 9 ms.
    assert record["lag_ns"]["p99"] == 7 * _MS
    assert record["lag_ns"]["max"] == 7 * _MS
    feed.stop()


def test_a_stream_start_error_is_counted_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _feed_clock(monkeypatch, _CountingClock(_T0))
    path = tmp_path / "feed-tap.jsonl"
    tap = FeedTap(path, time_ns=_Now(_T0), perf_ns=_Clock())
    feed, _ = _wire_feed(tap=tap, stream=_ExplodingStream())

    with pytest.raises(ConnectionError, match="socket closed"):
        feed.start()

    assert tap.failures == 1
    assert next(line for line in _lines(path) if line["kind"] == "second")["failures"] == 1
    assert isinstance(feed.failure, ConnectionError)
    feed.stop()
