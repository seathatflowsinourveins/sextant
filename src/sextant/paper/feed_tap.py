"""Read-only per-second measurement of the paper feed's handler traffic.

``FeedTap`` counts and times what already reaches ``AlpacaTickFeed``'s SIP
handlers and writes one JSON line per closed wall-clock second to a sidecar.
Handlers only bump ints; a daemon thread writes. A write error disables the
sidecar, never the feed. Reconnects are invisible here, so the sidecar reports
them as unmeasured rather than as zero.
"""

from __future__ import annotations

import contextlib
import json
import math
import threading
import time
from pathlib import Path
from typing import Any, NamedTuple

SIDECAR_NAME = "feed-tap.jsonl"
_NS_PER_S = 1_000_000_000
_NS_PER_MS = 1_000_000
_FLUSH_S = 0.25


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
        "trades": 0,
        "quotes": 0,
        "failures": 0,
        "inflight": 0,
        "service_sum": 0,
        "service_max": None,
        "symbols": set(),
        "lag": {},
        "max_lag": None,
    }


def _percentiles(hist: dict[int, int], max_lag: int | None) -> dict[str, int | None]:
    """Nearest-rank p99/p99.9 of a millisecond histogram, plus the exact ns max."""
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
    ) -> None:
        self._path, self._time_ns, self._perf_ns = path, time_ns, perf_ns
        self._flush_s = flush_s
        self._lock = threading.Lock()
        self._seconds: dict[int, dict[str, Any]] = {}
        self._flows: dict[str, list[Any]] = {}
        self._started = self._closed = False
        self._file: Any = None
        self._thread: threading.Thread | None = None
        self.write_errors = self.lost_finishes = 0

    def start(self) -> None:
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
        if self._closed:
            return
        self._closed = True
        if self._thread is not None:
            self._thread.join(5.0)
        self._write_all(force=True)
        with self._lock:
            symbols = self._symbols()
        self._write(symbols)
        if self._file is not None:
            with contextlib.suppress(Exception):
                self._file.close()

    def trade_entry(self, symbol: str, ts_event_ns: int | None) -> FeedTapToken:
        return self._enter("trade", symbol, ts_event_ns)

    def quote_entry(self, symbol: str, ts_event_ns: int | None) -> FeedTapToken:
        return self._enter("quote", symbol, ts_event_ns)

    def finish(self, token: FeedTapToken) -> None:
        service_ns = self._perf_ns() - token.perf_ns
        with self._lock:
            bucket = self._seconds.get(token.second)
            if bucket is None:
                self.lost_finishes += 1
                return
            bucket["inflight"] -= 1
            bucket["service_sum"] += service_ns
            longest_service = bucket["service_max"]
            bucket["service_max"] = (
                service_ns if longest_service is None else max(longest_service, service_ns)
            )
            if token.ts_event_ns is not None:
                lag = token.entry_ns - token.ts_event_ns
                if lag >= 0:
                    bucket["lag"][lag // _NS_PER_MS] = bucket["lag"].get(lag // _NS_PER_MS, 0) + 1
                    longest = bucket["max_lag"]
                    bucket["max_lag"] = lag if longest is None else max(longest, lag)

    def observe_failure(self) -> None:
        second = self._time_ns() // _NS_PER_S
        with self._lock:
            self._seconds.setdefault(second, _second(second))["failures"] += 1

    def take(self, now_ns: int, *, force: bool = False) -> list[dict[str, Any]]:
        now = now_ns // _NS_PER_S
        with self._lock:
            ready = [
                s for s, b in self._seconds.items() if not b["inflight"] and (force or s < now)
            ]
            buckets = [self._seconds.pop(s) for s in sorted(ready)]
        return [self._record(b, force and b["second"] >= now) for b in buckets]

    def _enter(self, kind: str, symbol: str, ts_event_ns: int | None) -> FeedTapToken:
        entry_ns, perf_ns = self._time_ns(), self._perf_ns()
        second = entry_ns // _NS_PER_S
        with self._lock:
            bucket = self._seconds.setdefault(second, _second(second))
            flow = self._flows.setdefault(symbol, [0, None, None])
            bucket[kind + "s"] += 1
            bucket["symbols"].add(symbol)
            flow[0] += 1
            if flow[0] == 1:
                flow[1] = ts_event_ns
            elif ts_event_ns is not None and flow[1] is not None and ts_event_ns > flow[1]:
                gap = ts_event_ns - flow[1]
                flow[2] = gap if flow[2] is None else max(flow[2], gap)
                flow[1] = ts_event_ns
            bucket["inflight"] += 1
        return FeedTapToken(kind, symbol, second, ts_event_ns, entry_ns, perf_ns)

    def _record(self, bucket: dict[str, Any], partial: bool) -> dict[str, Any]:
        return {
            "kind": "second",
            "second": bucket["second"],
            "partial": partial,
            "trades": bucket["trades"],
            "quotes": bucket["quotes"],
            "symbols_seen": len(bucket["symbols"]),
            "lag_ns": _percentiles(bucket["lag"], bucket["max_lag"]),
            "service_ns": {"sum": bucket["service_sum"], "max": bucket["service_max"]},
            "failures": bucket["failures"],
        }

    def _symbols(self) -> dict[str, Any]:
        return {
            "kind": "symbols",
            "symbols_seen": len(self._flows),
            "reconnects": None,
            "symbols": {
                name: {"last_ts_event_ns": flow[1], "max_gap_ns": flow[2]}
                for name, flow in sorted(self._flows.items())
            },
        }

    def _run(self) -> None:
        while not self._closed:
            time.sleep(self._flush_s)
            try:
                self._write_all()
            except Exception:
                self.write_errors += 1

    def _write_all(self, *, force: bool = False) -> None:
        for record in self.take(self._time_ns(), force=force):
            self._write(record)

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
