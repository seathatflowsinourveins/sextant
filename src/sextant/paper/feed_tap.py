"""Read-only instrumentation tap for the C lane's one Alpaca socket: it counts, it never trades.

Source: the reconciled C-lane capacity design (``tasks/entry-ages-screen/REPORT.md`` §5,
"Read-only instrumentation", read 2026-11-10) and Python's ``time.perf_counter_ns``
("Performance counter for benchmarking as nanoseconds", docs.python.org/3/library/time.html,
read 2026-11-10). The upstream shape is alpaca-py 0.44.0's synchronous handler dispatch
(``alpaca/data/live/websocket.py:324-372``, ``await handler(self._cast(msg))``): one handler
call per message on the stream's own thread, so a counter read at handler entry measures the
one socket the lane already reads.

The tap is a pure observer. It opens no socket, reads no key, submits nothing, and changes no
subscription. The stream thread only updates integers and short lists under a lock; one daemon
thread writes a JSON line for every second that saw a message to ``feed-tap.jsonl`` next to the
run's ``session.json``, then a final ``{"kind": "symbols", ...}`` line with per-symbol totals.
With no path it keeps the same counters in memory and writes nothing. A handler that is still
running keeps its second open, so a slow callback's sample is written rather than lost; a
message whose second was already written gets its own line, which the analyzer merges.

``entry_ns`` is ``time.time_ns`` at handler entry and ``perf_ns`` is ``time.perf_counter_ns``
there; the receipt lag is ``entry_ns - ts_event`` and the conversion lag the tick's own
``ts_init - ts_event``. The gate that reads this sidecar is ``feed_capacity.py``; it never
imports this module or the broker SDK.
"""

from __future__ import annotations

import contextlib
import json
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

__all__ = ["SIDECAR_NAME", "FeedTap", "FeedTapToken"]

SIDECAR_NAME = "feed-tap.jsonl"
_NS_PER_S = 1_000_000_000
_NS_PER_MS = 1_000_000
_FLUSH_S = 0.25
_JOIN_S = 5.0


@dataclass(frozen=True, slots=True)
class FeedTapToken:
    """One message's handler entry, held until its callback returns."""

    kind: str
    symbol: str
    second: int
    ts_event_ns: int | None
    entry_ns: int
    perf_ns: int


@dataclass(slots=True)
class _Flow:
    """One symbol's whole-run flow, written into the final line."""

    messages: int = 0
    trades: int = 0
    quotes: int = 0
    last_ts_event_ns: int = 0
    max_gap_ns: int = 0


@dataclass(slots=True)
class _Second:
    """One wall-clock second's counters; the only bucket shape that reaches the sidecar."""

    second: int
    trades: int = 0
    quotes: int = 0
    dropped_quotes: int = 0
    failures: int = 0
    inflight: int = 0
    service_sum_ns: int = 0
    service_max_ns: int = 0
    gap_max_ns: int = 0
    gap_samples: int = 0
    symbols: set[str] = field(default_factory=set)
    lag_entry: list[int] = field(default_factory=list)
    lag_init: list[int] = field(default_factory=list)
    service: list[int] = field(default_factory=list)
    hist_ms: dict[int, int] = field(default_factory=dict)

    @property
    def messages(self) -> int:
        return self.trades + self.quotes


def _percentiles(values: list[int], quantiles: tuple[float, ...]) -> list[int | None]:
    """Nearest-rank percentiles: the sample at ``ceil(q * n)``, never an interpolation."""
    if not values:
        return [None] * len(quantiles)
    ordered = sorted(values)
    limit = len(ordered)
    ranks = [min(max(1, math.ceil(q * limit)), limit) for q in quantiles]
    return [ordered[rank - 1] for rank in ranks]


def _nearest_rank(values: list[int], q: float) -> int | None:
    return _percentiles(values, (q,))[0]


def _lag_record(values: list[int], *, histogram: dict[int, int] | None = None) -> dict[str, Any]:
    p50, p95, p99, p999 = _percentiles(values, (0.5, 0.95, 0.99, 0.999))
    record: dict[str, Any] = {
        "count": len(values),
        "p50": p50,
        "p95": p95,
        "p99": p99,
        "p999": p999,
        "max": max(values) if values else None,
    }
    if histogram is not None:
        record["hist_ms"] = {str(ms): count for ms, count in sorted(histogram.items())}
    return record


class FeedTap:
    """Count one Alpaca stream's messages per second and write the sidecar; never an order.

    ``path`` is the sidecar next to the run's ``session.json``; ``None`` keeps everything in
    memory. ``time_ns`` and ``perf_ns`` are injectable for proofs only.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        time_ns: Callable[[], int] = time.time_ns,
        perf_ns: Callable[[], int] = time.perf_counter_ns,
        flush_s: float = _FLUSH_S,
    ) -> None:
        if not 0 < flush_s <= 1:
            raise ValueError("flush_s must be positive and at most one second")
        self._path = path
        self._time_ns = time_ns
        self._perf_ns = perf_ns
        self._flush_s = flush_s
        self._lock = threading.Lock()
        self._live: dict[int, _Second] = {}
        self._flows: dict[str, _Flow] = {}
        self._closed = threading.Event()
        self._thread: threading.Thread | None = None
        self._file: TextIO | None = None
        self._started = False
        self.write_errors = 0
        self.lost_finishes = 0

    def start(self) -> None:
        """Open the sidecar and its writer thread; no path means counters only."""
        if self._started:
            raise RuntimeError("feed tap already started")
        self._started = True
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("w", encoding="utf-8")
        self._thread = threading.Thread(target=self._run, name="feed-tap", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Write the remaining seconds and the per-symbol line, then close; idempotent."""
        if self._closed.is_set():
            return
        self._closed.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=_JOIN_S)
        try:
            for record in self.take(self._time_ns(), force=True):
                self._write(record)
            self._write(self._symbols_record())
        finally:
            if self._file is not None:
                with contextlib.suppress(Exception):
                    self._file.close()
                self._file = None

    def trade_entry(self, symbol: str, ts_event_ns: int | None) -> FeedTapToken:
        """Count a trade at handler entry; the caller holds the token until its callback ends."""
        return self._enter("trade", symbol, ts_event_ns)

    def quote_entry(self, symbol: str, ts_event_ns: int | None) -> FeedTapToken:
        """Count a quote at handler entry; a ``None`` tick at finish means it was dropped."""
        return self._enter("quote", symbol, ts_event_ns)

    def finish(self, token: FeedTapToken, *, ts_init: int | None = None) -> None:
        """Record service time, the conversion lag and a dropped quote, in the token's second."""
        service_ns = self._perf_ns() - token.perf_ns
        init_lag = (
            ts_init - token.ts_event_ns
            if ts_init is not None and token.ts_event_ns is not None
            else None
        )
        with self._lock:
            bucket = self._live.get(token.second)
            if bucket is None:
                self.lost_finishes += 1
                return
            bucket.inflight -= 1
            bucket.service.append(service_ns)
            bucket.service_sum_ns += service_ns
            bucket.service_max_ns = max(bucket.service_max_ns, service_ns)
            if init_lag is not None:
                bucket.lag_init.append(init_lag)
            if token.kind == "quote" and ts_init is None:
                bucket.dropped_quotes += 1

    def observe_failure(self) -> None:
        """Count one feed failure or start error in the second it happened."""
        with self._lock:
            self._bucket(self._time_ns() // _NS_PER_S).failures += 1

    def take(self, now_ns: int, *, force: bool = False) -> list[dict[str, Any]]:
        """Return the records of seconds that closed; ``force`` also closes the current second."""
        now_s = now_ns // _NS_PER_S
        with self._lock:
            ready = sorted(
                second
                for second, bucket in self._live.items()
                if force or (second < now_s and bucket.inflight == 0)
            )
            buckets = [self._live.pop(second) for second in ready]
        return [
            self._record(bucket, partial=force and bucket.second >= now_s) for bucket in buckets
        ]

    def _enter(self, kind: str, symbol: str, ts_event_ns: int | None) -> FeedTapToken:
        entry_ns = self._time_ns()
        perf_ns = self._perf_ns()
        second = entry_ns // _NS_PER_S
        with self._lock:
            bucket = self._bucket(second)
            bucket.inflight += 1
            if kind == "trade":
                bucket.trades += 1
            else:
                bucket.quotes += 1
            bucket.symbols.add(symbol)
            self._count_flow(symbol, kind)
            if ts_event_ns is not None:
                entry_lag = entry_ns - ts_event_ns
                bucket.lag_entry.append(entry_lag)
                bucket.hist_ms[entry_lag // _NS_PER_MS] = (
                    bucket.hist_ms.get(entry_lag // _NS_PER_MS, 0) + 1
                )
                self._advance_flow(symbol, ts_event_ns, bucket)
        return FeedTapToken(kind, symbol, second, ts_event_ns, entry_ns, perf_ns)

    def _bucket(self, second: int) -> _Second:
        bucket = self._live.get(second)
        if bucket is None:
            bucket = self._live[second] = _Second(second=second)
        return bucket

    def _count_flow(self, symbol: str, kind: str) -> None:
        flow = self._flows.get(symbol)
        if flow is None:
            flow = self._flows[symbol] = _Flow()
        if kind == "trade":
            flow.trades += 1
        else:
            flow.quotes += 1

    def _advance_flow(self, symbol: str, ts_event_ns: int, bucket: _Second) -> None:
        flow = self._flows[symbol]
        flow.messages += 1
        if flow.messages == 1:
            flow.last_ts_event_ns = ts_event_ns
            return
        gap = ts_event_ns - flow.last_ts_event_ns
        if gap > 0:
            bucket.gap_samples += 1
            bucket.gap_max_ns = max(bucket.gap_max_ns, gap)
            flow.max_gap_ns = max(flow.max_gap_ns, gap)
        if ts_event_ns > flow.last_ts_event_ns:
            flow.last_ts_event_ns = ts_event_ns

    def _record(self, bucket: _Second, *, partial: bool) -> dict[str, Any]:
        return {
            "kind": "second",
            "second": bucket.second,
            "partial": partial,
            "trades": bucket.trades,
            "quotes": bucket.quotes,
            "messages": bucket.messages,
            "symbols_seen": len(bucket.symbols),
            "rate_mps": float(bucket.messages),
            "lag_entry_ns": _lag_record(bucket.lag_entry, histogram=bucket.hist_ms),
            "lag_init_ns": _lag_record(bucket.lag_init),
            "service_ns": {
                "count": len(bucket.service),
                "sum": bucket.service_sum_ns,
                "p99": _nearest_rank(bucket.service, 0.99),
                "max": bucket.service_max_ns,
            },
            "utilization": bucket.service_sum_ns / _NS_PER_S,
            "gap_max_ns": bucket.gap_max_ns,
            "gap_samples": bucket.gap_samples,
            "failures": bucket.failures,
            "dropped_quotes": bucket.dropped_quotes,
        }

    def _symbols_record(self) -> dict[str, Any]:
        with self._lock:
            flows = dict(self._flows)
        symbols = {
            symbol: {
                "trades": flow.trades,
                "quotes": flow.quotes,
                "messages": flow.messages,
                "last_ts_event_ns": flow.last_ts_event_ns or None,
                "max_gap_ns": flow.max_gap_ns,
            }
            for symbol, flow in sorted(flows.items())
        }
        return {
            "kind": "symbols",
            "symbols_seen": len(symbols),
            "gap_max_ns": max((flow.max_gap_ns for flow in flows.values()), default=0),
            "incomplete_finishes": self.lost_finishes,
            "symbols": symbols,
        }

    def _run(self) -> None:
        while not self._closed.wait(self._flush_s):
            try:
                for record in self.take(self._time_ns()):
                    self._write(record)
            except Exception:
                self.write_errors += 1
                return

    def _write(self, record: dict[str, Any]) -> None:
        """Append one line; a full or vanished disk disables the sidecar, never the feed."""
        handle = self._file
        if handle is None:
            return
        try:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
            handle.flush()
        except Exception:
            self.write_errors += 1
            self._file = None
            with contextlib.suppress(Exception):
                handle.close()
