"""Direct Sharadar transport boundaries and the key registry; offline, no network and no key."""

import copy
import csv
import io
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest

from sextant.research import sharadar_client as client

FIXTURE = Path(__file__).parents[1] / "fixtures/sharadar/tables.json"
NOW = datetime(2026, 11, 6, 16, 0, tzinfo=UTC)


class FixtureFetch:
    def __init__(self) -> None:
        self.tables = json.loads(FIXTURE.read_text())
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, table: str, params: dict[str, Any]) -> bytes:
        self.calls.append((table, dict(params)))
        source = copy.deepcopy(self.tables[table])
        names, rows = source["columns"], source["data"]
        if "from" in params and "date" in names:
            rows = [r for r in rows if params["from"] <= r[names.index("date")] <= params["to"]]
        if "ticker" in params:
            rows = [r for r in rows if r[names.index("ticker")] in params["ticker"].split(",")]
        if "limit" in params:
            start = params.get("skip", 0)
            rows = rows[start : start + params["limit"]]
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(names)
        writer.writerows(rows)
        body = stream.getvalue().encode()
        if "years" in params:
            zipped = io.BytesIO()
            with ZipFile(zipped, "w") as archive:
                archive.writestr(f"{table.lower()}.csv", body)
            return zipped.getvalue()
        return body


def test_direct_client_uses_only_the_header_and_refuses_credential_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import requests

    monkeypatch.setenv("SHARADAR_API_KEY", "fixture-not-a-real-api-key")
    calls = []

    def request(self: Any, url: str, **kwargs: Any) -> requests.Response:
        calls.append({**kwargs, "url": url})
        response = requests.Response()
        response.status_code = 200
        response._content = b"ticker,permaticker\nTWO,101\n"
        return response

    monkeypatch.setattr(requests.Session, "get", request)
    fetch = client.direct_client()
    fetch("TICKERS", {})
    assert calls[0]["headers"]["x-api-key"] == "fixture-not-a-real-api-key"
    assert calls[0]["url"] == "https://api.sharadar.com/v1.0/data/tickers"
    assert "fixture-not-a-real-api-key" not in calls[0]["url"]
    assert "api_key" not in calls[0]["params"]
    assert calls[0]["allow_redirects"] is False

    def echo(self: Any, url: str, **kwargs: Any) -> requests.Response:
        response = request(self, url, **kwargs)
        response._content = b'"fixture-not-a-real-api-key"'
        return response

    monkeypatch.setattr(requests.Session, "get", echo)
    with pytest.raises(ValueError, match="credential"):
        fetch("TICKERS", {})

    def escaped_echo(self: Any, url: str, **kwargs: Any) -> requests.Response:
        response = request(self, url, **kwargs)
        response._content = b'"\\u0066ixture-not-a-real-api-key"'
        return response

    monkeypatch.setattr(requests.Session, "get", escaped_echo)
    with pytest.raises(ValueError, match="credential"):
        fetch("TICKERS", {})


def test_missing_environment_key_never_falls_back_to_a_key_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SHARADAR_API_KEY", raising=False)
    with pytest.raises(ValueError, match="SHARADAR_API_KEY"):
        client.direct_client()


def test_csv_numeric_prices_keep_their_exact_decimal_text() -> None:
    _, rows = client.parse_response(b"closeunadj\n0.100000000000000001\n")
    assert rows == [{"closeunadj": "0.100000000000000001"}]


def test_store_lists_the_direct_key_without_a_nasdaq_alias(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(Path(__file__).parents[2] / "scripts/keys.sh"), "list"],
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    states = dict(line.split()[::-1] for line in result.stdout.splitlines())
    assert states["SHARADAR_API_KEY"] == "missing"
    assert "NASDAQ_DATA_LINK_API_KEY" not in states


def test_bulk_redirect_never_forwards_the_account_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    monkeypatch.setenv("SHARADAR_API_KEY", "fixture-not-a-real-api-key")
    calls: list[dict] = []
    body = FixtureFetch()("TICKERS", {"years": "full"})

    def get(self: Any, url: str, **kwargs: Any) -> requests.Response:
        calls.append({**kwargs, "url": url})
        response = requests.Response()
        response.status_code = 302 if len(calls) == 1 else 200
        response._content = b"" if len(calls) == 1 else body
        if len(calls) == 1:
            response.headers["Location"] = "https://downloads.example.invalid/tickers.zip"
        return response

    monkeypatch.setattr(requests.Session, "get", get)
    assert client.direct_client()("TICKERS", {"years": "full"}) == body
    assert calls[0]["headers"]["x-api-key"] == "fixture-not-a-real-api-key"
    assert calls[1]["headers"] == {} and calls[1]["allow_redirects"] is False


def test_bulk_archives_never_extract_paths_and_refuse_multiple_members() -> None:
    zipped = io.BytesIO()
    with ZipFile(zipped, "w") as archive:
        archive.writestr("../../outside.csv", "ticker\nONE\n")
        archive.writestr("second.csv", "ticker\nTWO\n")
    with pytest.raises(ValueError):
        client.parse_response(zipped.getvalue())


def test_access_probe_makes_one_bounded_read_and_records_no_entitlement(tmp_path: Path) -> None:
    fixture = FixtureFetch()
    receipt = client.probe(tmp_path / "probe.json", fetch=fixture, clock=lambda: NOW)
    assert fixture.calls == [("TICKERS", {"ticker": "TWO", "limit": 1, "format": "csv"})]
    assert receipt["http_status"] == 200 and receipt["entitlement_verified"] is False
    assert receipt["mode"] == "offline_fixture"
