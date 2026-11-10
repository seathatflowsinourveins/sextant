"""Proofs for the tap abort's independence, latch and SDK replay safety.

The witnesses are the executed review proofs for P1-1 through P1-4: a sidecar
that cannot open, a blocked sink, a later extra-only record, a failed
unsubscribe send and a C segment transition.  No socket or running event loop
is reached except the pinned SDK's own in-memory frame builder.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

import msgpack
import pytest
import test_alpaca_feed as feed_proofs  # pyright: ignore[reportMissingImports]
import test_c_live_main as runner_proofs  # pyright: ignore[reportMissingImports]
from alpaca.data.enums import DataFeed
from alpaca.data.live.stock import StockDataStream

import sextant.paper.c_live_main as runner_module
from sextant.paper.alpaca_feed import AlpacaTickFeed
from sextant.paper.feed_tap import FeedTap

SECOND = 1_000_000_000
START = feed_proofs._T0
live_env = runner_proofs.live_env


def wait_until(predicate: Any, seconds: float = 0.8) -> bool:
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.005)
    return bool(predicate())


def test_sidecar_open_failure_does_not_disable_abort(tmp_path: Path) -> None:
    now = feed_proofs._Now(START)
    tap = FeedTap(tmp_path, time_ns=now, perf_ns=lambda: 0, flush_s=0.01)
    own_ticks: list[Any] = []

    def script(stream: Any) -> None:
        now.value = START + 2 * SECOND
        feed_proofs._deliver_to(stream, "trade", "AAPL", feed_proofs._trade())
        now.value += SECOND
        feed_proofs._deliver_to(stream, "trade", "AAPL", feed_proofs._trade())
        wait_until(lambda: stream.unsubscribed)

    stream = feed_proofs._ScriptedStream(script)
    feed, _ = feed_proofs._make_feed(
        tap=tap, tap_symbols=("EXTRA",), stream=stream, on_trade=own_ticks.append
    )
    feed.start()
    records = tap.take(now.value + SECOND)
    worst_lag = max(record["lag_ns"]["p999"] or 0 for record in records)
    print(
        f"open failure: init_errors={tap.init_errors}, own_ticks={len(own_ticks)}, "
        f"own_p999_ns={worst_lag}, unsubscribed={stream.unsubscribed}"
    )
    assert worst_lag >= SECOND
    assert ("trades", ("EXTRA",)) in stream.unsubscribed


def test_blocked_sidecar_sink_does_not_hide_later_own_feed_delay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = feed_proofs._Now(START)
    blocked, release = threading.Event(), threading.Event()
    tap = FeedTap(tmp_path / "slow.jsonl", time_ns=now, perf_ns=lambda: 0, flush_s=0.01)
    write = tap._write

    def slow_write(record: dict[str, Any]) -> None:
        blocked.set()
        release.wait(4)
        write(record)

    monkeypatch.setattr(tap, "_write", slow_write)
    own_ticks: list[Any] = []
    observed: dict[str, Any] = {}

    def script(stream: Any) -> None:
        feed_proofs._deliver_to(
            stream, "trade", "AAPL", feed_proofs._trade(t="2026-11-09T14:30:00Z")
        )
        now.value += SECOND
        feed_proofs._deliver_to(
            stream, "trade", "AAPL", feed_proofs._trade(t="2026-11-09T14:30:01Z")
        )
        assert blocked.wait(1)
        now.value = START + 5 * SECOND
        feed_proofs._deliver_to(stream, "trade", "AAPL", feed_proofs._trade())
        now.value += SECOND
        feed_proofs._deliver_to(stream, "trade", "AAPL", feed_proofs._trade())
        wait_until(lambda: stream.unsubscribed)
        observed["unsubscribed"] = list(stream.unsubscribed)
        record = tap.last_record
        observed["guard_lag"] = None if record is None else record["lag_ns"]["p999"]
        observed["queued"] = tap.pending
        release.set()

    stream = feed_proofs._ScriptedStream(script)
    feed, _ = feed_proofs._make_feed(
        tap=tap, tap_symbols=("EXTRA",), stream=stream, on_trade=own_ticks.append
    )
    try:
        feed.start()
    finally:
        release.set()
        tap.stop()
    records = [json.loads(line) for line in (tmp_path / "slow.jsonl").read_text().splitlines()]
    worst_lag = max(record.get("lag_ns", {}).get("p999") or 0 for record in records)
    print(f"blocked sink: own_ticks={len(own_ticks)}, own_p999_ns={worst_lag}, observed={observed}")
    assert worst_lag >= SECOND
    assert ("trades", ("EXTRA",)) in observed["unsubscribed"]


def test_a_breached_second_is_not_overwritten_by_a_later_extra_only_second() -> None:
    now = feed_proofs._Now(START)
    tap = FeedTap(time_ns=now, perf_ns=lambda: 0)
    records: list[Any] = []

    def script(stream: Any) -> None:
        now.value = START + 2 * SECOND
        feed_proofs._deliver_to(stream, "trade", "AAPL", feed_proofs._trade())
        now.value += SECOND
        feed_proofs._deliver_to(stream, "trade", "EXTRA", feed_proofs._trade(symbol="EXTRA"))
        now.value += SECOND
        records.extend(tap.take(now.value))
        wait_until(lambda: stream.unsubscribed)

    stream = feed_proofs._ScriptedStream(script)
    feed, _ = feed_proofs._make_feed(tap=tap, tap_symbols=("EXTRA",), stream=stream)
    feed.start()
    last = tap.last_record
    print(
        f"batch: p999s={[record['lag_ns']['p999'] for record in records]}, "
        f"last_p999={None if last is None else last['lag_ns']['p999']}, "
        f"unsubscribed={stream.unsubscribed}"
    )
    assert records[0]["lag_ns"]["p999"] >= SECOND
    assert ("trades", ("EXTRA",)) in stream.unsubscribed


class Wire:
    def __init__(self, fail_unsubscribe: bool = False) -> None:
        self.fail_unsubscribe = fail_unsubscribe
        self.frames: list[dict[str, Any]] = []
        self.parts: list[int] = []

    async def send(self, payload: Any) -> None:
        chunks = [payload] if isinstance(payload, bytes) else list(payload)
        self.parts.extend(map(len, chunks))
        message = msgpack.unpackb(b"".join(chunks))
        self.frames.append(message)
        if message["action"] == "unsubscribe" and self.fail_unsubscribe:
            raise ConnectionResetError("fake reconnect during unsubscribe")


class ReplaySDKStream(StockDataStream):
    def __init__(self, scenario: Any, wire: Wire) -> None:
        super().__init__(
            feed_proofs._TEST_API_KEY, feed_proofs._TEST_API_CREDENTIAL, feed=DataFeed.SIP
        )
        self.scenario = scenario
        self.wire = wire

    def run(self) -> None:
        async def run_scenario() -> None:
            self._loop = asyncio.get_running_loop()
            self._ws = self.wire
            self._running = True
            try:
                await asyncio.wait_for(self.scenario(self), timeout=5)
            finally:
                self._running = False

        asyncio.run(run_scenario())


@pytest.mark.parametrize("fail_unsubscribe", [False, True])
def test_sdk_abort_survives_resubscribe_replay(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fail_unsubscribe: bool
) -> None:
    now = feed_proofs._Now(START)
    wire = Wire(fail_unsubscribe)
    tap = FeedTap(tmp_path / "sdk.jsonl", time_ns=now, perf_ns=lambda: 0, flush_s=0.01)
    own_ticks: list[Any] = []

    async def scenario(stream: ReplaySDKStream) -> None:
        now.value = START + 2 * SECOND
        await stream._handlers["trades"]["AAPL"](feed_proofs._trade())
        now.value += SECOND
        await stream._handlers["trades"]["AAPL"](feed_proofs._trade())
        deadline = time.monotonic() + 2
        while sum(frame["action"] == "unsubscribe" for frame in wire.frames) < 2:
            assert time.monotonic() < deadline
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        wire.fail_unsubscribe = False
        await stream._send_subscribe_msg()
        await stream._handlers["trades"]["AAPL"](feed_proofs._trade())

    stream = ReplaySDKStream(scenario, wire)
    factories: list[Any] = []

    def factory(*args: Any, **kwargs: Any) -> ReplaySDKStream:
        factories.append(stream)
        return stream

    feed = AlpacaTickFeed(
        {"AAPL.ALPACA": feed_proofs._EQUITY},
        on_trade=own_ticks.append,
        on_quote=lambda tick: None,
        api_key=feed_proofs._TEST_API_KEY,
        secret_key=feed_proofs._TEST_API_CREDENTIAL,
        stream_factory=factory,
        tap=tap,
        tap_symbols=("EXTRA",),
    )
    feed.start()
    page = capsys.readouterr().err
    replay = [frame for frame in wire.frames if frame["action"] == "subscribe"][-1]
    print(
        f"SDK abort: send_failed={fail_unsubscribe}, replay={replay}, "
        f"pages={page.count('feed tap guard')}, own_ticks={len(own_ticks)}, "
        f"stream_factories={len(factories)}, stopped={feed._guard_stopped}"
    )
    assert len(factories) == 1
    assert page.count("feed tap guard") == 1
    assert len(own_ticks) == 3
    assert feed.failure is None
    assert replay["trades"] == ["AAPL"]
    assert replay["quotes"] == ["AAPL"]


class ActualRunnerFeed:
    def __init__(self, instruments: Any, *, clock: Any, replay: Any, **kwargs: Any) -> None:
        self.clock = clock
        self.instruments = instruments
        self.tap = kwargs.get("tap")
        self.tap_symbols = kwargs.get("tap_symbols", ())
        self.on_trade = kwargs["on_trade"]
        self.on_quote = kwargs["on_quote"]
        self.stream = feed_proofs._ScriptedStream(lambda stream: replay(self))
        self.delegate = AlpacaTickFeed(
            instruments, **kwargs, stream_factory=lambda *args, **kwargs: self.stream
        )

    @property
    def failure(self) -> Any:
        return self.delegate.failure

    def start(self) -> None:
        self.delegate.start()

    def stop(self) -> None:
        self.delegate.stop()


def test_c_runner_preserves_a_successful_abort_across_segment_resubscribe(
    live_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    universe = live_env / "universe.json"
    universe.write_text(json.dumps({"rows": [{"symbol": "OMH"}, {"symbol": "EXTRA"}]}))
    wall = feed_proofs._Now(START)

    def tap_factory(path: Path) -> FeedTap:
        return FeedTap(path, time_ns=wall, perf_ns=lambda: 0, flush_s=0.01)

    monkeypatch.setattr(runner_module, "FeedTap", tap_factory)
    monkeypatch.setattr(runner_proofs, "FakeFeed", ActualRunnerFeed)
    feeds: list[Any] = []
    client = runner_proofs.FakeTradingClient()

    def breach_ticks(feed: ActualRunnerFeed) -> None:
        wall.value += 2 * SECOND
        feed_proofs._deliver_to(feed.stream, "quote", "OMH", feed_proofs._quote(symbol="OMH"))
        wall.value += SECOND
        feed_proofs._deliver_to(feed.stream, "quote", "OMH", feed_proofs._quote(symbol="OMH"))
        assert wait_until(lambda: len(feed.stream.unsubscribed) == 2)

    def cross_boundary(feed: ActualRunnerFeed) -> None:
        breach_ticks(feed)
        feed.clock.value = runner_proofs.RTH_AFTER_OPEN

    def second_segment_ticks(feed: ActualRunnerFeed) -> None:
        wall.value += 2 * SECOND
        feed_proofs._deliver_to(feed.stream, "quote", "OMH", feed_proofs._quote(symbol="OMH"))

    assert (
        runner_proofs.invoke(
            live_env,
            client,
            runner_proofs.Clock(runner_proofs.PRE_OPEN_CLOCK),
            runner_proofs.Monotonic(),
            baseline_dir=runner_proofs.write_baseline_dir(live_env),
            feed_tap=True,
            feed_tap_universe=universe,
            replays=[cross_boundary, second_segment_ticks],
            feed_log=feeds,
        )
        == 0
    )
    page = capsys.readouterr().err
    subscribed = [
        [symbols for handler, symbols in feed.stream.trade_subscriptions] for feed in feeds
    ]
    print(
        f"C segment replay: streams={len(feeds)}, same_tap={feeds[0].tap is feeds[1].tap}, "
        f"trade_subscriptions={subscribed}, pages={page.count('feed tap guard')}, "
        f"orders={len(client.submitted)}, cancels={len(client.cancelled)}"
    )
    assert len(feeds) == 2
    assert ("EXTRA",) not in subscribed[1]
    assert page.count("feed tap guard") == 1
