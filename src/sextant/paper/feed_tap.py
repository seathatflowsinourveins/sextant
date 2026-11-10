"""Read-only per-second measurement of the paper feed's handler traffic.

``FeedTap`` counts and times what already reaches ``AlpacaTickFeed``'s SIP
handlers and writes one JSON line per closed wall-clock second to a sidecar.
Handlers take no lock and write no file: they bump ints and hand a closed
bucket to a bounded queue that one daemon thread drains. The gap map is keyed
only by the subscribed instruments, so it cannot grow with time or traffic.
A sidecar that cannot open or write never stops the feed; it is counted and
disabled. Reconnects are invisible here, so the sidecar reports them as
unmeasured rather than as zero.
"""

from __future__ import annotations

import contextlib
import json
import math
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, NamedTuple

SIDECAR_NAME = "feed-tap.jsonl"
_NS_PER_S = 1_000_000_000
_NS_PER_MS = 1_000_000
_FLUSH_S = 0.25
_PENDING = 120
_LIVE = 8
_QUIESCE_S = 5.0


class FeedTapToken(NamedTuple):
    kind: str
    symbol: str
    second: int
    ts_event_ns: int | None
    entry_ns: int
    perf_ns: int


def _second(second: int) -> dict[str, Any]:
    return {
        "second": second,
        "partial": False,
        "trades": 0,
        "quotes": 0,
        "symbols": set(),
        "failures": 0,
        "service_sum": 0,
        "service_max": None,
        "lag": {},
        "max_lag": None,
    }


def _percentiles(hist: dict[int, int], max_lag: int | None) -> dict[str, int | None]:
    """Nearest-rank p99/p99.9, each the floor bin's lower edge, plus the exact max."""
    total = sum(hist.values())
    if not total:
        return {"count": 0, "p99": None, "p999": None, "max": None}
    keys = sorted(hist)

    def at(quantile: float) -> int:
        rank, seen = max(1, math.ceil(quantile * total)), 0
        for key in keys:
            seen += hist[key]
            if seen >= rank:
                return key * _NS_PER_MS
        return keys[-1] * _NS_PER_MS

    return {"count": total, "p99": at(0.99), "p999": at(0.999), "max": max_lag}


class FeedTap:
    """The read-only observer; with no ``path`` it only keeps counts in memory."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        time_ns=time.time_ns,
        perf_ns=time.perf_counter_ns,
        flush_s: float = _FLUSH_S,
        pending: int = _PENDING,
    ) -> None:
        self._path, self._time_ns, self._perf_ns = path, time_ns, perf_ns
        self._flush_s, self._max_pending = flush_s, pending
        self._seconds: dict[int, dict[str, Any]] = {}
        self._flows: dict[str, list[int | None]] = {}
        self._pending: deque[dict[str, Any]] = deque()
        self._started = self._closed = False
        self._file: Any = None
        self._thread: threading.Thread | None = None
        self._inflight = 0
        self.failures = self.write_errors = self.init_errors = 0
        self.lost_finishes = self.dropped_buckets = 0

    def start(self) -> None:
        if self._started:
            raise RuntimeError("feed tap already started")
        self._started = True
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self._path.open("w", encoding="utf-8")
            self._thread = threading.Thread(target=self._run, name="feed-tap", daemon=True)
            self._thread.start()
        except Exception:
            # The feed's own run must not depend on the sidecar opening.
            self.init_errors += 1
            handle, self._file = self._file, None
            if handle is not None:
                with contextlib.suppress(Exception):
                    handle.close()

    def stop(self) -> None:
        if not self._started or self._closed:
            return
        deadline = time.monotonic() + _QUIESCE_S
        while self._inflight and time.monotonic() < deadline:
            time.sleep(0.001)
        now = self._time_ns() // _NS_PER_S
        for second in sorted(self._seconds):
            self._detach(second, partial=second >= now)
        self._closed = True
        if self._thread is not None:
            self._thread.join(_QUIESCE_S)

    @property
    def pending(self) -> int:
        return len(self._pending)

    def trade_entry(self, symbol: str, ts_event_ns: int | None) -> FeedTapToken | None:
        return self._enter("trade", symbol, ts_event_ns)

    def quote_entry(self, symbol: str, ts_event_ns: int | None) -> FeedTapToken | None:
        return self._enter("quote", symbol, ts_event_ns)

    def finish(self, token: FeedTapToken | None) -> None:
        if token is None:
            return
        service_ns = self._perf_ns() - token.perf_ns
        self._inflight -= 1
        bucket = self._seconds.get(token.second)
        if bucket is None:
            self.lost_finishes += 1
            return
        bucket["service_sum"] += service_ns
        longest = bucket["service_max"]
        bucket["service_max"] = service_ns if longest is None else max(longest, service_ns)
        if token.ts_event_ns is not None:
            lag = token.entry_ns - token.ts_event_ns
            if lag >= 0:
                bin_ms = lag // _NS_PER_MS
                bucket["lag"][bin_ms] = bucket["lag"].get(bin_ms, 0) + 1
                longest_lag = bucket["max_lag"]
                bucket["max_lag"] = lag if longest_lag is None else max(longest_lag, lag)

    def observe_failure(self) -> None:
        self.failures += 1
        if self._closed:
            return
        second = self._time_ns() // _NS_PER_S
        self._seconds.setdefault(second, _second(second))["failures"] += 1

    def take(self, now_ns: int, *, force: bool = False) -> list[dict[str, Any]]:
        """Detach ready seconds and return their records; only for a quiet tap."""
        if self._inflight == 0:
            now = now_ns // _NS_PER_S
            for second in sorted(self._seconds):
                if force or second < now:
                    self._detach(second, partial=force and second >= now)
        return self._drain()

    def _enter(self, kind: str, symbol: str, ts_event_ns: int | None) -> FeedTapToken | None:
        if self._closed:
            return None
        entry_ns, perf_ns = self._time_ns(), self._perf_ns()
        second = entry_ns // _NS_PER_S
        for old in sorted(s for s in self._seconds if s < second):
            self._detach(old, partial=False)
        if len(self._seconds) >= _LIVE:
            self._detach(min(self._seconds), partial=False)
        bucket = self._seconds.setdefault(second, _second(second))
        bucket[kind + "s"] += 1
        bucket["symbols"].add(symbol)
        flow = self._flows.get(symbol)
        if flow is None:
            self._flows[symbol] = [ts_event_ns, None]
        elif ts_event_ns is not None:
            last = flow[0]
            if last is None:
                flow[0] = ts_event_ns
            elif ts_event_ns > last:
                gap = ts_event_ns - last
                flow[1] = gap if flow[1] is None else max(flow[1], gap)
                flow[0] = ts_event_ns
        self._inflight += 1
        return FeedTapToken(kind, symbol, second, ts_event_ns, entry_ns, perf_ns)

    def _detach(self, second: int, *, partial: bool) -> None:
        bucket = self._seconds.pop(second)
        bucket["partial"] = partial
        if len(self._pending) >= self._max_pending:
            self.dropped_buckets += 1
        else:
            self._pending.append(bucket)

    def _drain(self) -> list[dict[str, Any]]:
        return [self._record(self._pending.popleft()) for _ in range(len(self._pending))]

    def _record(self, bucket: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "second",
            "second": bucket["second"],
            "partial": bucket["partial"],
            "trades": bucket["trades"],
            "quotes": bucket["quotes"],
            "symbols_seen": len(bucket["symbols"]),
            "lag_ns": _percentiles(bucket["lag"], bucket["max_lag"]),
            "service_ns": {"sum": bucket["service_sum"], "max": bucket["service_max"]},
            "failures": bucket["failures"],
        }

    def _symbols(self) -> dict[str, Any]:
        gaps = [flow[1] for flow in self._flows.values() if flow[1] is not None]
        return {
            "kind": "symbols",
            "symbols_seen": len(self._flows),
            "symbols_with_gap": len(gaps),
            "max_gap_ns": max(gaps) if gaps else None,
            "reconnects": None,
            "dropped_buckets": self.dropped_buckets,
            "write_errors": self.write_errors,
            "init_errors": self.init_errors,
        }

    def _run(self) -> None:
        while not self._closed or self._pending:
            for record in self._drain():
                self._write(record)
            if not self._closed:
                time.sleep(self._flush_s)
        self._write(self._symbols())
        handle = self._file
        self._file = None
        if handle is not None:
            with contextlib.suppress(Exception):
                handle.close()

    def _write(self, record: dict[str, Any]) -> None:
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
