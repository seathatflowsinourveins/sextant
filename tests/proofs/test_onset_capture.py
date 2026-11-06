"""#130 bounded historical REST intake: no stream, orders or invented observations."""

import json
import subprocess
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from requests import PreparedRequest, Response
from requests.adapters import HTTPAdapter

from sextant.research.onset_capture import (
    BoundedHistory,
    CaptureBudget,
    CaptureStopped,
    canonical_snapshot,
    ingest_partition,
    pilot_events,
    require_reservation,
)

NOW = datetime(2026, 11, 6, 18, 30, tzinfo=UTC)


def budget(**changes: Any) -> CaptureBudget:
    return CaptureBudget(
        max_requests=changes.pop("max_requests", 2),
        max_bytes=changes.pop("max_bytes", 100_000),
        deadline=changes.pop("deadline", NOW + timedelta(minutes=1)),
        requests_per_minute=Decimal(60),
        now=lambda: NOW,
        wait=lambda: None,
        memory_ok=lambda: True,
        **changes,
    )


def test_budget_refuses_before_dispatch_and_charges_every_attempt() -> None:
    bounded = budget(max_requests=1)
    bounded.before_http("GET", "https://data.alpaca.markets/v2/stocks/bars")
    with pytest.raises(CaptureStopped, match="request_budget"):
        bounded.before_http("GET", "https://data.alpaca.markets/v2/stocks/bars")
    assert bounded.requests == 1
    for method, url in [
        ("POST", "https://paper-api.alpaca.markets/v2/orders"),
        ("GET", "https://api.alpaca.markets/v2/calendar"),
        ("GET", "https://data.alpaca.markets/v2/stocks/quotes/latest"),
    ]:
        with pytest.raises(CaptureStopped, match="endpoint"):
            budget().before_http(method, url)
    with pytest.raises(CaptureStopped, match="stop_time"):
        budget(deadline=NOW).before_http("GET", "https://data.alpaca.markets/v2/stocks/bars")
    with pytest.raises(ValueError, match="frozen stop"):
        budget(deadline=datetime(2026, 11, 6, 19, 1, tzinfo=UTC))


class Pages(HTTPAdapter):
    def __init__(self, pages: list[dict], status: int = 200) -> None:
        super().__init__()
        self.pages = pages
        self.status = status
        self.requests: list[PreparedRequest] = []

    def send(
        self,
        request: PreparedRequest,
        stream: Any = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> Response:
        self.requests.append(request)
        response = Response()
        response.status_code = self.status
        response.url = request.url or ""
        response.request = request
        response._content = json.dumps(self.pages[len(self.requests) - 1]).encode()
        response._content_consumed = True
        return response


def history(
    monkeypatch: pytest.MonkeyPatch, bounded: CaptureBudget, pages: Pages
) -> BoundedHistory:
    monkeypatch.setenv("APCA_API_KEY_ID", "fixture-key-not-authority")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "fixture-secret-not-authority")
    client = BoundedHistory(bounded)
    client._session.mount("https://", pages)
    return client


def test_sdk_pages_keep_dated_asof_and_cannot_escape_the_request_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = Pages(
        [
            {"bars": {"ACRS": []}, "next_page_token": "next"},
            {"bars": {"ACRS": []}, "next_page_token": None},
        ]
    )
    bounded = budget(max_requests=1)
    client = history(monkeypatch, bounded, pages)
    try:
        with pytest.raises(CaptureStopped, match="request_budget"):
            client.fetch("ACRS", date(2021, 1, 19), "1min")
    finally:
        client.close()
    assert len(pages.requests) == 1
    query = parse_qs(urlsplit(pages.requests[0].url or "").query)
    assert query["asof"] == ["2021-01-19"]
    assert query["feed"] == ["sip"] and query["adjustment"] == ["raw"]
    assert bounded.requests == 1


def test_429_is_one_charged_failure_and_response_echo_is_never_archived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = Pages([{"message": "rate limited"}], status=429)
    bounded = budget()
    client = history(monkeypatch, bounded, pages)
    with pytest.raises(CaptureStopped, match="http_status_429"):
        client.fetch("ACRS", date(2021, 1, 19), "1min")
    assert len(pages.requests) == 1 and bounded.requests == 1
    assert client.pages == []
    client.close()
    pages = Pages([{"bars": {}, "echo": "fixture-secret-not-authority"}])
    client = history(monkeypatch, budget(), pages)
    with pytest.raises(CaptureStopped, match="credential_echo"):
        client.fetch("ACRS", date(2021, 1, 19), "1min")
    assert client.pages == []
    client.close()


def test_capture_limit_refuses_before_a_large_body_is_landed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = Pages([{"bars": {"ACRS": []}, "padding": "x" * 1000}])
    client = history(monkeypatch, budget(max_bytes=100), pages)
    with pytest.raises(CaptureStopped, match="byte_budget"):
        client.fetch("ACRS", date(2021, 1, 19), "1min")
    assert client.pages == []
    client.close()


def test_real_catalog_ingest_preserves_raw_receipts_and_closed_bar_clocks(tmp_path: Path) -> None:
    page = json.dumps(
        {
            "bars": {
                "ACRS": [
                    {
                        "t": "2021-01-19T14:30:00Z",
                        "o": "8.00",
                        "h": "8.20",
                        "l": "7.90",
                        "c": "8.10",
                        "v": "100",
                        "n": 5,
                        "vw": "8.05",
                    }
                ]
            },
            "next_page_token": None,
        }
    )
    result = ingest_partition(
        tmp_path / "raw", tmp_path / "catalog", "ACRS", date(2021, 1, 19), "1min", (page,)
    )
    assert result["bars"] == 1 and result["known_at_first"] == "2021-01-19T14:31:00+00:00"
    assert result["survivor_only"] is True and result["pit_verified"] is False
    assert len(result["raw_sha256"]) == 64
    again = ingest_partition(
        tmp_path / "raw", tmp_path / "catalog", "ACRS", date(2021, 1, 19), "1min", (page,)
    )
    assert again == result


def test_pilot_takes_only_vendor_covered_identities_and_dates() -> None:
    rows = [
        dict(
            symbol="ZZZ",
            session_date="2021-01-01",
            cohort="selected_gainer",
            prices={"SEP": {"status": "absent"}},
            raw_fields={"Prior_Close": "999"},
        ),
        dict(
            symbol="ACRS",
            session_date="2021-01-19",
            cohort="selected_gainer",
            prices={"SEP": {"status": "observed"}},
            raw_fields={"Prior_Close": "999"},
        ),
        dict(
            symbol="SRPT",
            session_date="2021-01-08",
            cohort="selected_loser",
            prices={"SEP": {"status": "observed"}},
            raw_fields={"Prior_Close": "999"},
        ),
    ]
    assert pilot_events(rows) == [
        dict(symbol="ACRS", day="2021-01-19", cohort="selected_gainer"),
        dict(symbol="SRPT", day="2021-01-08", cohort="selected_loser"),
    ]


def test_reservation_binds_running_code_and_exact_frozen_inputs(tmp_path: Path) -> None:
    params = {"events": [{"symbol": "ACRS", "day": "2021-01-19"}], "max_requests": 160}
    row = dict(
        trial_id=107,
        n_trials=108,
        state="RUNNING",
        params=json.dumps(params),
        config=json.dumps(
            dict(
                arm_run_id="coverage-130-1",
                implementation_sha="a" * 40,
                tier="MODELED",
                sandbox_config=params,
            )
        ),
    )
    path = tmp_path / "trials.parquet"
    pq.write_table(pa.Table.from_pylist([row]), path)
    assert require_reservation(path, "coverage-130-1", params, "a" * 40)["trial_id"] == 107
    for attempt, expected, code in [
        ("missing", params, "a" * 40),
        ("coverage-130-1", {**params, "max_requests": 161}, "a" * 40),
        ("coverage-130-1", params, "b" * 40),
    ]:
        with pytest.raises(CaptureStopped, match="reservation"):
            require_reservation(path, attempt, expected, code)
    row["state"] = "COMPLETE"
    pq.write_table(pa.Table.from_pylist([row]), path)
    with pytest.raises(CaptureStopped, match="reservation"):
        require_reservation(path, "coverage-130-1", params, "a" * 40)


def test_old_receipt_cannot_reopen_an_attempt_closed_on_the_canonical_tip(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return (
            subprocess.check_output(
                ["git", "-c", "user.name=Proof", "-c", "user.email=proof@example.invalid", *args],
                cwd=tmp_path,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )

    git("init", "-q")
    ledger = tmp_path / "reports/research/sim-runner/trials.parquet"
    ledger.parent.mkdir(parents=True)
    params = {"max_requests": 160}
    row = dict(
        trial_id=107,
        n_trials=108,
        state="RUNNING",
        params=json.dumps(params),
        config=json.dumps(
            dict(
                arm_run_id="old", implementation_sha="a" * 40, tier="MODELED", sandbox_config=params
            )
        ),
    )
    pq.write_table(pa.Table.from_pylist([row]), ledger)
    git("add", "reports")
    git("commit", "-qm", "reserve")
    receipt = git("rev-parse", "HEAD")
    row["state"] = "COMPLETE"
    pq.write_table(pa.Table.from_pylist([row]), ledger)
    git("add", "reports")
    git("commit", "-qm", "close")
    tip = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/ledger", tip)
    snapshot_sha, raw = canonical_snapshot(tmp_path, receipt)
    assert snapshot_sha == tip and raw == ledger.read_bytes()
    copy = tmp_path / "snapshot.parquet"
    copy.write_bytes(raw)
    with pytest.raises(CaptureStopped, match="reservation"):
        require_reservation(copy, "old", params, "a" * 40)
