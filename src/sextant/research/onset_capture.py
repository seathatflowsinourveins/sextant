"""Bounded #130 historical intake; no detector, stream, order or replacement ledger.

upstream checked: sextant@8ccf6934cdba20d7cd30c0e99129b24026ec462f:data/alpaca_history.py,
data/catalog.py, research/sharadar_client.py; northstar-trading@8256c16c31dc:data/alpaca_history.py;
alpaca-py@0.44.0 cc4cb3b7ba50ae250e621983c2779047fb16bb28:common/rest.py,
historical/stock.py; requests@6e83187b8feb273ed4c6cdab5efd8d54901dfab3:models.py.
The existing SDK pagination/capture and native catalog own data semantics. Request/byte/deadline
bounds are the owner's #130 acquisition contract, published before any request on the issue.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus, urlsplit

import pyarrow.parquet as pq
from alpaca.common.rest import RESTClient
from alpaca.trading.client import TradingClient
from requests import Response

from sextant.data.alpaca_history import (
    AlpacaHistory,
    Pacer,
    environment_credentials,
    land_raw,
    raw_path,
    read_raw,
)
from sextant.data.catalog import CatalogStore, decode_bars


class CaptureStopped(ValueError):
    """Closed, credential-free stop reason, suitable for a failed-attempt receipt."""


def _memory_ok() -> bool:
    values = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    available = int(values["MemAvailable"].split()[0]) * 1024
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    return available >= 20 * 1024**3 and peak < 2 * 1024**3


class CaptureBudget:
    def __init__(
        self,
        *,
        max_requests: int,
        max_bytes: int,
        deadline: datetime,
        requests_per_minute: Decimal,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        wait: Callable[[], None] | None = None,
        memory_ok: Callable[[], bool] = _memory_ok,
    ) -> None:
        if type(max_requests) is not int or not 0 < max_requests <= 160:
            raise ValueError("request cap exceeds the frozen pilot")
        if type(max_bytes) is not int or not 0 < max_bytes <= 128 * 1024**2:
            raise ValueError("capture cap exceeds the frozen pilot")
        if deadline.utcoffset() is None or not 0 < requests_per_minute <= 60:
            raise ValueError("explicit stop time and rate at most 60/min required")
        if deadline > datetime(2026, 11, 6, 19, 0, tzinfo=UTC):
            raise ValueError("deadline exceeds the frozen stop on #130")
        self.max_requests, self.max_bytes, self.deadline = max_requests, max_bytes, deadline
        self.rate = requests_per_minute
        self.requests = self.bytes = 0
        self.now, self.memory_ok = now, memory_ok
        self.wait = wait if wait is not None else Pacer(requests_per_minute).wait
        self.receipts: list[dict[str, Any]] = []

    def _check(self) -> None:
        if self.now() >= self.deadline:
            raise CaptureStopped("stop_time")
        if not self.memory_ok():
            raise CaptureStopped("memory_bound")

    def before_http(self, method: str, url: str) -> None:
        parts = urlsplit(url)
        allowed = {
            ("data.alpaca.markets", "/v2/stocks/bars"),
            ("paper-api.alpaca.markets", "/v2/calendar"),
        }
        if (
            method != "GET"
            or parts.scheme != "https"
            or parts.username
            or parts.password
            or parts.port not in (None, 443)
            or (parts.hostname, parts.path) not in allowed
        ):
            raise CaptureStopped("endpoint_refused")
        self._check()
        if self.requests >= self.max_requests:
            raise CaptureStopped("request_budget")
        self.wait()
        self._check()
        self.requests += 1
        self.receipts.append(
            dict(sequence=self.requests, endpoint=parts.path, requested_at=self.now().isoformat())
        )

    def capture(self, response: Response, secrets: Sequence[str]) -> None:
        """Requests' own chunked decoder/cache; bound bytes before SDK text/model decoding."""
        chunks = []
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                self._check()
                if self.bytes + len(chunk) > self.max_bytes:
                    raise CaptureStopped("byte_budget")
                self.bytes += len(chunk)
                chunks.append(chunk)
            body = b"".join(chunks)
            # The existing Sharadar transport's echo refusal; values never enter receipts.
            for secret in secrets:
                echoes = (
                    secret,
                    quote(secret, safe=""),
                    quote_plus(secret),
                    json.dumps(secret)[1:-1],
                )
                if any(value.encode() in body for value in echoes):
                    raise CaptureStopped("credential_echo")
            response._content = body
            response._content_consumed = True
            self.receipts[-1].update(
                received_at=self.now().isoformat(),
                http_status=response.status_code,
                bytes=len(body),
                response_sha256=hashlib.sha256(body).hexdigest(),
            )
            if response.status_code != 200:
                raise CaptureStopped(f"http_status_{response.status_code}")
        finally:
            response.close()


class BoundedHistory(AlpacaHistory):
    """Keep source fetch/asof/raw envelopes; every page is charged and 429 never retries."""

    def __init__(self, budget: CaptureBudget) -> None:
        self.budget = budget
        self._secrets = environment_credentials()
        super().__init__(calls_per_minute=budget.rate)
        self._session.trust_env = False

    def _one_request(self, method: str, url: str, opts: dict, retry: int) -> dict:
        self.budget.before_http(method, url)
        try:
            # The shared source Pacer already waited, then rechecked the absolute stop time.
            return RESTClient._one_request(self, method, url, {**opts, "timeout": (10, 20)}, 0)
        except CaptureStopped:
            raise
        except Exception:
            raise CaptureStopped("historical_request_failed") from None

    def _capture(self, response: Response, **kwargs: Any) -> None:
        self.budget.capture(response, self._secrets)
        super()._capture(response, **kwargs)


class BoundedCalendar(TradingClient):
    """Only the pinned calendar GET is admitted; this client has no permitted order endpoint."""

    def __init__(self, budget: CaptureBudget) -> None:
        self.budget = budget
        self._secrets = environment_credentials()
        super().__init__(*self._secrets, paper=True)
        self._session.trust_env = False
        self._session.hooks["response"].append(self._capture)

    def _one_request(self, method: str, url: str, opts: dict, retry: int) -> dict:
        self.budget.before_http(method, url)
        try:
            return super()._one_request(method, url, {**opts, "timeout": (10, 20)}, 0)
        except CaptureStopped:
            raise
        except Exception:
            raise CaptureStopped("calendar_request_failed") from None

    def _capture(self, response: Response, **kwargs: Any) -> None:
        self.budget.capture(response, self._secrets)

    def close(self) -> None:
        self._session.close()


def ingest_partition(
    raw_root: Path,
    catalog_root: Path,
    symbol: str,
    day: date,
    bar: str,
    pages: Sequence[str],
) -> dict[str, Any]:
    """Use row 11's raw envelope, lossless decoder and native ParquetDataCatalog writer."""
    raw = raw_path(raw_root, bar, symbol, day)
    if raw.exists() and pq.read_table(raw)["response_json"].to_pylist() != list(pages):
        raise CaptureStopped("raw_partition_conflict")
    land_raw(raw, pages, symbol=symbol, day=day, bar=bar)
    bars = decode_bars(read_raw(raw), symbol, bar)
    CatalogStore(catalog_root, cache_intervals=True).write(symbol, bars, raw_partition=raw)
    first = (
        datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=bars[0].ts_init // 1000)
        if bars
        else None
    )
    return dict(
        symbol=symbol,
        day=day.isoformat(),
        bar=bar,
        bars=len(bars),
        raw_path=str(raw),
        raw_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
        known_at_first=None if first is None else first.isoformat(),
        survivor_only=True,
        pit_verified=False,
    )


def require_reservation(
    ledger: Path,
    attempt: str,
    params: dict[str, Any],
    code_sha: str,
) -> dict[str, Any]:
    """Require exact RUNNING code/input identity from #102 before credentials or HTTP."""
    if not ledger.is_file():
        raise CaptureStopped("reservation_unavailable")
    matches = []
    for row in pq.read_table(ledger).to_pylist():
        config = json.loads(row["config"])
        if config.get("arm_run_id") == attempt:
            matches.append((row, config))
    if len(matches) != 1:
        raise CaptureStopped("reservation_not_unique")
    row, config = matches[0]
    if (
        row["state"] != "RUNNING"
        or config.get("tier") != "MODELED"
        or config.get("implementation_sha") != code_sha
        or config.get("sandbox_config") != params
        or json.loads(row["params"]) != params
    ):
        raise CaptureStopped("reservation_identity_or_state")
    return dict(
        trial_id=row["trial_id"],
        n_trials=row["n_trials"],
        canonical_parquet_sha256=hashlib.sha256(ledger.read_bytes()).hexdigest(),
        canonical_snapshot_file=str(ledger),
    )


def _git(repository: Path, *args: str) -> bytes:
    # The credentialed Python command needs the paper key; local git does not.
    clean = {
        k: v
        for k, v in os.environ.items()
        if not any(s in k.upper() for s in ("KEY", "SECRET", "TOKEN", "PASSWORD"))
    }
    return subprocess.check_output(
        ["git", *args], cwd=repository, env=clean, stderr=subprocess.DEVNULL
    )


def canonical_snapshot(repository: Path, receipt_commit: str) -> tuple[str, bytes]:
    """Read the fetched ledger tip, so an old RUNNING receipt cannot reopen a closed trial."""
    if not re.fullmatch(r"[0-9a-f]{40}", receipt_commit):
        raise CaptureStopped("reservation_commit_required")
    tip = _git(repository, "rev-parse", "refs/remotes/origin/ledger").decode().strip()
    _git(repository, "merge-base", "--is-ancestor", receipt_commit, tip)
    return tip, _git(repository, "show", f"{tip}:reports/research/sim-runner/trials.parquet")
