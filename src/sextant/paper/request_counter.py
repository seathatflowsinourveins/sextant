"""C's process-local request counts on one fixed-interval log line.

Pinned alpaca-py 0.44.0 discards HTTP response headers (``alpaca/common/rest.py``
``_request`` ends in ``response.json()``), so Alpaca's documented
``X-RateLimit-Remaining`` is not available to C.  The fallback counts what C
itself did: the account pacer's ``wire_requests`` and the calls to
``get_stock_bars``.  The line is a pure observer: a counter or print failure is
swallowed with one ``c-requests unavailable`` line and never reaches trading.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from typing import Any

REQUEST_LOG_INTERVAL_S = 60.0


def _default_out(line: str) -> None:
    print(line, flush=True)


class CountingMarketData:
    """Passes ``get_stock_bars`` through unchanged and counts the call first."""

    def __init__(self, data: Any, count: Callable[[], None]) -> None:
        self._data = data
        self._count = count

    def get_stock_bars(self, request_params: Any) -> Any:
        with contextlib.suppress(Exception):
            self._count()
        return self._data.get_stock_bars(request_params)


class RequestLog:
    """Prints ``c-requests wire=<n> data=<n>`` every ``interval_s``, fail-silent."""

    def __init__(
        self,
        requests: Callable[[], int],
        now: Callable[[], float],
        *,
        out: Callable[[str], None] = _default_out,
        interval_s: float = REQUEST_LOG_INTERVAL_S,
    ) -> None:
        self._requests = requests
        self._now = now
        self._out = out
        self.interval_s = interval_s
        self.data_requests = 0
        self._next_at: float | None = None
        self._failed = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def count_data_request(self) -> None:
        self.data_requests += 1

    def maybe_log(self) -> None:
        if self._failed:
            return
        try:
            now = self._now()
            if self._next_at is None:
                self._next_at = now + self.interval_s
            if now < self._next_at:
                return
            while self._next_at <= now:
                self._next_at += self.interval_s
            self._emit(f"c-requests wire={self._requests()} data={self.data_requests}")
        except Exception:
            self._failed = True
            self._emit("c-requests unavailable")

    def start(self) -> None:
        if self._thread is not None:
            return
        try:
            self._next_at = self._now() + self.interval_s
            thread = threading.Thread(target=self._run, name="c-request-log", daemon=True)
            thread.start()
            self._thread = thread
        except Exception:
            self._failed = True
            self._emit("c-requests unavailable")

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            self.maybe_log()

    def _emit(self, line: str) -> None:
        try:
            self._out(line)
        except Exception:
            self._failed = True
