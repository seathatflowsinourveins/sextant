"""Sharadar direct REST, adapted from northstar-trading@8256c16c's data/sharadar.py.

Official API: https://sharadar.com/llms.txt, docs/{auth,getting-started,bulk},
read 2026-11-06. No official direct-service Python SDK was found there.
Use the documented x-api-key header with pinned requests, never a Nasdaq alias.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus, urlsplit
from zipfile import ZipFile, is_zipfile

import requests

from sextant.research import candidate_history as seed

BASE = "https://api.sharadar.com/v1.0"
KEY_ENV = "SHARADAR_API_KEY"  # House store name, not an official SDK environment variable.
PIN = "6e83187b8feb273ed4c6cdab5efd8d54901dfab3"
SOURCE = {
    "service": "sharadar",
    "api_version": "v1.0",
    "api_base": BASE,
    "transport": "psf/requests",
    "version": "2.34.2",
    "commit": PIN,
    "adapter_commit": "8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa",
}
ROUTES = {
    "TICKERS": "tickers",
    "ACTIONS": "actions",
    "SEP": "stocks",
    "SFP": "funds",
    "SF1": "fundamentals",
    "DAILY": "daily",
    "METRICS": "metrics",
}
MAX_BODY = 256 * 1024 * 1024  # Pinned northstar transport's bounded raw/decoded body.
Fetch = Callable[[str, dict[str, Any]], bytes]


class ReadFailure(Exception):
    def __init__(self, status: int | None) -> None:
        self.http_status = status
        super().__init__("Sharadar read failed")


def _csv_bytes(body: bytes) -> bytes:
    if len(body) > MAX_BODY:
        raise ValueError("Response exceeds the upstream body bound")
    if is_zipfile(io.BytesIO(body)):
        with ZipFile(io.BytesIO(body)) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
                raise ValueError("Bulk archive must contain exactly one CSV")
            if members[0].file_size > MAX_BODY:
                raise ValueError("Decoded response exceeds the upstream body bound")
            return archive.read(members[0])  # Read bytes only; never extract a remote path.
    return body


def parse_response(body: bytes) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(
        io.StringIO(_csv_bytes(body).decode("utf-8-sig"), newline=""), strict=True
    )
    names = list(reader.fieldnames or [])
    if not names or any(not n for n in names) or len(names) != len(set(names)):
        raise ValueError("Missing or duplicate table columns")
    rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError("Malformed CSV row")
    return names, rows


def direct_client() -> Fetch:
    key = os.environ.get(KEY_ENV, "")
    if not key or key == "test-api-key" or not key.isascii() or any(ord(c) < 33 for c in key):
        raise ValueError("SHARADAR_API_KEY must be injected through with-keys.sh")
    session = requests.Session()
    session.trust_env = False  # Pinned source: no ambient proxy/netrc credentials.

    def scan(body: bytes) -> None:
        if len(body) > MAX_BODY:
            raise ValueError("Response exceeds the upstream body bound")
        payloads = [body]
        if is_zipfile(io.BytesIO(body)):
            with ZipFile(io.BytesIO(body)) as archive:
                if sum(m.file_size for m in archive.infolist()) > MAX_BODY:
                    raise ValueError("Decoded response exceeds the upstream body bound")
                payloads.extend(archive.read(m) for m in archive.infolist() if not m.is_dir())
        for payload in tuple(payloads):
            try:
                decoded = json.loads(payload, parse_float=str, object_pairs_hook=list)
                payloads.append(json.dumps(decoded, ensure_ascii=False).encode())
            except (ValueError, UnicodeError):
                pass  # CSV need not be JSON; raw/ZIP member bytes are still scanned.
        echoes = (key, quote(key, safe=""), quote_plus(key), json.dumps(key)[1:-1])
        if any(value.encode() in payload for payload in payloads for value in echoes):
            raise ValueError("Response echoed a credential; archival refused")

    def request(url: str, params: dict | None, *, authenticated: bool) -> requests.Response:
        try:
            response = session.get(
                url,
                params=params,
                headers={"x-api-key": key} if authenticated else {},
                allow_redirects=False,
                timeout=(10, 60),
            )
        except requests.RequestException:
            raise ReadFailure(None) from None
        scan(response.content)
        return response

    def fetch(table: str, params: dict[str, Any]) -> bytes:
        if table not in ROUTES or set(params) - {
            "ticker",
            "from",
            "to",
            "fields",
            "format",
            "limit",
            "skip",
            "sort",
            "years",
        }:
            raise ValueError("Unsupported coverage query")
        response = request(f"{BASE}/data/{ROUTES[table]}", params, authenticated=True)
        if response.status_code == 302 and "years" in params:
            location = response.headers.get("Location", "")
            parts = urlsplit(location)
            if (
                parts.scheme != "https"
                or not parts.hostname
                or parts.username
                or parts.password
                or parts.fragment
                or any(v in location for v in (key, quote(key, safe=""), quote_plus(key)))
            ):
                raise ValueError("Unsafe bulk redirect; credentials were not forwarded")
            response = request(location, None, authenticated=False)
        if response.status_code != 200:
            raise ReadFailure(response.status_code)
        return response.content

    return fetch


def probe(
    output: Path,
    *,
    fetch: Fetch | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """One bounded authenticated request, separate from coverage/entitlement acceptance."""
    if output.exists() or output.with_suffix(".csv").exists():
        raise ValueError("Refusing an existing immutable probe")
    mode = "offline_fixture" if fetch is not None else "authenticated"
    fetch = fetch or direct_client()
    params = {"ticker": "TWO", "limit": 1, "format": "csv"}
    started = clock().astimezone(UTC).isoformat()
    result: dict[str, Any] = {
        "client": SOURCE,
        "mode": mode,
        "query": {"table": "TICKERS", "filters": params},
        "requested_at": started,
        "http_status": None,
        "raw_sha256": None,
        "entitlement_verified": False,
        "survivor_only": True,
        "pit_verified": False,
        "implementation_source_sha256": seed._sha(Path(__file__).read_bytes()),
    }
    try:
        body = fetch("TICKERS", params)
        columns, rows = parse_response(body)
        if "ticker" not in columns:
            raise ValueError("Probe schema unavailable")
        seed._publish_once(output.with_suffix(".csv"), body)
        result.update(http_status=200, raw_sha256=seed._sha(body), rows=len(rows))
    except Exception as exc:
        status = getattr(exc, "http_status", None)
        result["http_status"] = status if type(status) is int else None
        result["error"] = "RequestFailed"  # No request/exception/body text is emitted.
    result["received_at"] = clock().astimezone(UTC).isoformat()
    seed._publish_once(output, seed._json(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    if subprocess.check_output(
        ["git", "status", "--porcelain", "--", "src/sextant/research", "pyproject.toml", "uv.lock"],
        cwd=root,
    ):
        parser.error("Commit the implementation and pins before the access probe")
    try:
        result = probe(args.output)
    except Exception:
        parser.exit(2, "Access probe failed; no exception text or credential was emitted.\n")
    print(json.dumps({"http_status": result["http_status"], "entitlement_verified": False}))
    if result["http_status"] != 200:
        parser.exit(2)


if __name__ == "__main__":
    main()
