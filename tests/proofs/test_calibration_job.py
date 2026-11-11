"""Offline data collection: stub clients, exact source texts, no stored credentials."""

import hashlib
import importlib
import importlib.util
import json
import subprocess
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pyarrow.parquet as pq
import pytest
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from requests import PreparedRequest, Response
from requests.adapters import HTTPAdapter

from sextant.data.alpaca_history import Pacer, nanos
from sextant.paper.sessions import ET

ROOT = Path(__file__).resolve().parents[2]
PARAMETERS = ROOT / "deploy/calibration/parameters.json"
NOW = nanos(datetime(2026, 11, 9, 3, tzinfo=ET))


@pytest.fixture
def job():
    assert importlib.util.find_spec("sextant.data.calibration_job") is not None
    return importlib.import_module("sextant.data.calibration_job")


@pytest.fixture
def setup_job(tmp_path, job):
    universe = tmp_path / "universe.json"
    universe.write_text('{"rows":[{"symbol":"AAPL"}]}')
    parameters = json.loads(PARAMETERS.read_text())
    parameters["rows"]["prior_sessions"]["value"] = 2
    params = tmp_path / "parameters.json"
    params.write_text(json.dumps(parameters))
    out = tmp_path / "data"
    args = ["--universe", str(universe), "--data-dir", str(out), "--parameters", str(params)]
    return args, out


def fake_client(job, *, fail=False, empty=False, baseline=None):
    class Fake(job.CalibrationHistory):
        def __init__(self):
            self.pages = []
            self.requests = []
            self.closed = False

        def get_stock_bars(self, request):
            self.requests.append(request)
            if request.symbol_or_symbols == ["AAPL"]:
                # Existing baseline recipe requests a multi-session, multi-symbol window.
                hours = (0, 1) if request.feed == DataFeed.BOATS else (4, 10, 17)
                return {
                    "AAPL": [
                        {"t": datetime(2026, 11, day, hour, tzinfo=ET), "v": 10, "vw": "2", "n": 1}
                        for day in (5, 6)
                        for hour in hours
                    ]
                }
            return self.capture(request, "bars")

        def get_stock_quotes(self, request):
            self.requests.append(request)
            if baseline is not None:
                assert (baseline / "baselines/manifest.json").exists()
            if fail:
                raise RuntimeError("offline data failure")
            return self.capture(request, "quotes")

        def capture(self, request, kind):
            stamp = request.start.replace(tzinfo=UTC).isoformat()
            row = (
                '{"t":"' + stamp + '","bp":2.1234567890123456789,"ap":2.2,'
                '"bs":1,"as":2,"bx":"Q","ax":"Q","c":[],"z":"C"}'
            )
            if kind == "bars":
                row = '{"t":"' + stamp + '","o":2,"h":3,"l":1,"c":2,"v":10,"vw":2,"n":1}'
            text = (
                '{"'
                + kind
                + '":'
                + ("{}" if empty else '{"AAPL":[' + row + "]}")
                + ',"next_page_token":null}'
            )
            self.pages.append(text)
            return json.loads(text)[kind]

        def close(self):
            self.closed = True

    return Fake()


def test_job_refreshes_baselines_and_records_exact_history(setup_job, job):
    args, out = setup_job
    client = fake_client(job, baseline=out)
    assert job.main(args, client_factory=lambda: client, now_ns=lambda: NOW) == 0
    assert client.closed
    baseline = json.loads((out / "baselines/manifest.json").read_text())
    assert baseline["as_of"] == "2026-11-09"
    receipts = list((out / "calibration/runs").glob("*.json"))
    receipt = json.loads(receipts[0].read_text())
    assert receipt["status"] == "UNCALIBRATED"
    assert receipt["universe"]["sha256"] == hashlib.sha256(Path(args[1]).read_bytes()).hexdigest()
    assert len(receipt["files"]) == 8  # two sessions, two feeds, quotes plus minute bars
    for record in receipt["files"]:
        path = out / record["path"]
        assert record["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        table = pq.read_table(path)
        assert table.schema.metadata[b"feed"].decode() == record["feed"]
        assert record["rows"] == 1
        if record["kind"] == "quotes":
            raw = json.loads(table["response_json"][0].as_py(), parse_float=Decimal)
            assert raw["quotes"]["AAPL"][0]["bp"] == Decimal("2.1234567890123456789")
    before = {path: path.read_bytes() for path in out.rglob("*.parquet")}
    count = len(client.requests)
    assert job.main(args, client_factory=lambda: client, now_ns=lambda: NOW + 1) == 0
    assert len(client.requests) == count + 2  # only the baseline recipe re-fetches
    assert {path: path.read_bytes() for path in before} == before


def test_failed_history_has_no_completed_receipt_and_closes(setup_job, job):
    args, out = setup_job
    client = fake_client(job, fail=True)
    with pytest.raises(RuntimeError, match="offline data failure"):
        job.main(args, client_factory=lambda: client, now_ns=lambda: NOW)
    assert client.closed
    assert (out / "baselines/manifest.json").exists()
    assert not list(out.rglob("runs/*.json"))


def test_empty_quotes_stay_empty_and_uncalibrated(setup_job, job):
    args, out = setup_job
    job.main(args, client_factory=lambda: fake_client(job, empty=True), now_ns=lambda: NOW)
    receipt = json.loads(next((out / "calibration/runs").glob("*.json")).read_text())
    assert receipt["status"] == "UNCALIBRATED"
    assert {record["rows"] for record in receipt["files"]} == {0}


@pytest.mark.parametrize("bad", [0, -1, True, "20"])
def test_invalid_window_refuses_before_client_or_output(setup_job, job, bad):
    args, out = setup_job
    path = Path(args[-1])
    parameters = json.loads(path.read_text())
    parameters["rows"]["prior_sessions"]["value"] = bad
    path.write_text(json.dumps(parameters))
    with pytest.raises(ValueError, match="prior_sessions"):
        job.main(args, client_factory=lambda: pytest.fail("client constructed"), now_ns=lambda: NOW)
    assert not out.exists()


def test_missing_parameter_authority_refuses_before_client(setup_job, job):
    args, out = setup_job
    path = Path(args[-1])
    parameters = json.loads(path.read_text())
    parameters["rows"]["prior_sessions"].pop("source")
    path.write_text(json.dumps(parameters))
    with pytest.raises(ValueError, match="authority"):
        job.main(args, client_factory=lambda: pytest.fail("client constructed"), now_ns=lambda: NOW)
    assert not out.exists()


def test_closed_xnys_day_skips_without_a_client(setup_job, job):
    args, out = setup_job
    holiday = nanos(datetime(2026, 11, 26, 3, tzinfo=ET))
    assert (
        job.main(
            args, client_factory=lambda: pytest.fail("client constructed"), now_ns=lambda: holiday
        )
        == 0
    )
    assert not out.exists()


@pytest.mark.parametrize(
    "feed,start,end",
    [
        ("sip", "2026-11-06T09:00:00+00:00", "2026-11-07T00:59:59.999999+00:00"),
        ("boats", "2026-11-06T01:00:00+00:00", "2026-11-06T08:59:59.999999+00:00"),
    ],
)
@pytest.mark.parametrize("kind", ["quotes", "bars"])
def test_sdk_fetch_uses_all_pages_and_the_correct_session_window(
    job, monkeypatch, feed, start, end, kind
):
    queries = []
    texts = [
        '{"' + kind + '":{"AAPL":[]},"next_page_token":"next"}',
        '{"' + kind + '":{},"next_page_token":null}',
    ]

    def send(adapter: HTTPAdapter, request: PreparedRequest, **kwargs: Any) -> Response:
        query = parse_qs(urlsplit(str(request.url)).query)
        queries.append(query)
        response = Response()
        response.status_code = 200
        response.request = request
        response._content = texts[len(queries) - 1].encode()
        return response

    monkeypatch.setattr(HTTPAdapter, "send", send)
    client = job.CalibrationHistory.__new__(job.CalibrationHistory)
    StockHistoricalDataClient.__init__(
        client,
        api_key="offline",
        secret_key="offline",  # noqa: S106 - inert SDK fixture
        raw_data=True,
    )
    client.pacer = Pacer()
    client.pages = []
    client._session.hooks["response"].append(client._capture)
    try:
        assert client.fetch_window("AAPL", date(2026, 11, 6), kind, feed) == tuple(texts)
    finally:
        client.close()
    assert queries[0]["start"] == [start]
    assert queries[0]["end"] == [end]
    assert queries[0]["feed"] == [feed]
    assert queries[0]["asof"] == ["2026-11-06"]
    assert queries[0]["sort"] == ["asc"]
    assert queries[1]["page_token"] == ["next"]
    if kind == "bars":
        assert queries[0]["timeframe"] == ["1Min"]
        assert queries[0]["adjustment"] == ["raw"]


def test_script_passes_explicit_paths_without_reading_keys(tmp_path):
    fake = tmp_path / "uv"
    record = tmp_path / "arguments"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$RECORD"\n')
    fake.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/calibration-data.sh"), str(tmp_path / "data")],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin", "RECORD": str(record)},
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert record.read_text().splitlines() == [
        "run",
        "--frozen",
        "python",
        "-m",
        "sextant.data.calibration_job",
        "--data-dir",
        str(tmp_path / "data"),
        "--universe",
        str(tmp_path / "data/universe.json"),
        "--parameters",
        str(ROOT / "deploy/calibration/parameters.json"),
    ]


def test_timer_calendar_has_the_registered_morning_time():
    import configparser

    timer = configparser.ConfigParser(interpolation=None)
    timer.read(ROOT / "deploy/calibration/sextant-calibration-data.timer")
    expression = timer["Timer"]["OnCalendar"]
    parameters = json.loads(PARAMETERS.read_text())
    assert expression == parameters["rows"]["on_calendar"]["value"]
    result = subprocess.run(["systemd-analyze", "calendar", expression], capture_output=True)
    assert result.returncode == 0, result.stderr


def test_receipt_hashes_the_parameters_actually_used(setup_job, job):
    args, out = setup_job
    path = Path(args[-1])
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    client = fake_client(job)
    original = client.get_stock_quotes

    def change_after_load(request):
        path.write_text("{}")
        return original(request)

    client.get_stock_quotes = change_after_load
    job.main(args, client_factory=lambda: client, now_ns=lambda: NOW)
    receipt = json.loads(next((out / "calibration/runs").glob("*.json")).read_text())
    assert receipt["parameters_sha256"] == expected


def test_broken_page_chain_never_lands_a_partition(tmp_path, job):
    client = fake_client(job)
    client.fetch_window = lambda *args: (
        '{"quotes":{},"next_page_token":null}',
        '{"quotes":{},"next_page_token":null}',
    )
    with pytest.raises(ValueError, match="continuation"):
        job.archive(client, tmp_path, "AAPL", date(2026, 11, 6), "quotes", "sip", NOW)
    assert not list(tmp_path.rglob("*.parquet"))


@pytest.mark.parametrize(
    "page",
    [
        '{"quotes":{"MSFT":[]},"next_page_token":null}',
        '{"quotes":{"AAPL":[{"t":"2026-11-06T12:00:00Z"}]},"next_page_token":null}',
        '{"quotes":{},"next_page_token":"unread"}',
        '{"quotes":{}}',
        '{"bars":{},"next_page_token":null}',
    ],
)
def test_malformed_or_incomplete_history_never_lands(tmp_path, job, page):
    client = fake_client(job)
    client.fetch_window = lambda *args: (page,)
    with pytest.raises(ValueError):
        job.archive(client, tmp_path, "AAPL", date(2026, 11, 6), "quotes", "sip", NOW)
    assert not list(tmp_path.rglob("*.parquet"))


def test_invalid_universe_refuses_before_client(setup_job, job):
    args, out = setup_job
    Path(args[1]).write_text('{"rows":[{"symbol":"AAPL.ALPACA"}]}')
    with pytest.raises(ValueError, match="bare vendor"):
        job.main(args, client_factory=lambda: pytest.fail("client constructed"), now_ns=lambda: NOW)
    assert not out.exists()


def test_partial_run_resumes_only_unfinished_partitions(setup_job, job):
    args, out = setup_job
    client = fake_client(job)
    original = client.get_stock_quotes
    reads = 0

    def fail_second_window(request):
        nonlocal reads
        reads += 1
        if reads == 2:
            raise RuntimeError("offline second window failed")
        return original(request)

    client.get_stock_quotes = fail_second_window
    with pytest.raises(RuntimeError, match="second window"):
        job.main(args, client_factory=lambda: client, now_ns=lambda: NOW)
    completed = {path: path.read_bytes() for path in out.rglob("*.parquet")}
    assert len(completed) == 2
    assert not list(out.rglob("runs/*.json"))
    client.get_stock_quotes = original
    before = len(client.requests)
    assert job.main(args, client_factory=lambda: client, now_ns=lambda: NOW + 1) == 0
    assert len(client.requests) - before == 8  # two baselines and six unfinished partitions
    assert all(path.read_bytes() == raw for path, raw in completed.items())


def test_user_unit_injects_keys_only_into_the_job_command():
    import configparser
    import shlex

    service = configparser.ConfigParser(interpolation=None)
    service.read(ROOT / "deploy/calibration/sextant-calibration-data.service")
    command = shlex.split(service["Service"]["ExecStart"])
    assert command[:4] == ["/usr/bin/bash", "%h/sextant/scripts/with-keys.sh", "--strict", "-k"]
    assert command[4:8] == [
        "ALPACA_PAPER_2_API_KEY:APCA_API_KEY_ID",
        "-k",
        "ALPACA_PAPER_2_SECRET_KEY:APCA_API_SECRET_KEY",
        "--",
    ]
    assert command[8:] == [
        "/usr/bin/bash",
        "%h/sextant/scripts/calibration-data.sh",
        "%h/sextant-data/calibration",
    ]
    assert "EnvironmentFile" not in service["Service"]


def test_history_availability_is_recorded_after_the_response(setup_job, job):
    args, out = setup_job
    client = fake_client(job)
    clock = [NOW]
    original = client.get_stock_quotes

    def delayed_response(request):
        clock[0] += 1
        return original(request)

    client.get_stock_quotes = delayed_response
    job.main(args, client_factory=lambda: client, now_ns=lambda: clock[0])
    receipt = json.loads(next((out / "calibration/runs").glob("*.json")).read_text())
    assert receipt["files"][0]["known_at"] == NOW + 1
    assert receipt["known_at"] == NOW + 4


def test_service_memory_limit_matches_its_uncalibrated_registry_row():
    import configparser

    service = configparser.ConfigParser(interpolation=None)
    service.read(ROOT / "deploy/calibration/sextant-calibration-data.service")
    row = json.loads(PARAMETERS.read_text())["rows"]["memory_max"]
    assert row["status"] == "UNCALIBRATED" and row["source"]
    assert service["Service"]["MemoryMax"] == row["value"]
    assert service["Service"]["MemorySwapMax"] == "0"


@pytest.mark.parametrize("tokens", [("repeat", "repeat", None), ("a", "b", "a", None)])
def test_repeated_sdk_pagination_token_never_lands(tmp_path, job, monkeypatch, tokens):
    pages = [json.dumps({"quotes": {}, "next_page_token": token}) for token in tokens]
    requests = []

    def send(adapter: HTTPAdapter, request: PreparedRequest, **kwargs: Any) -> Response:
        requests.append(request)
        response = Response()
        response.status_code = 200
        response.request = request
        response._content = pages[len(requests) - 1].encode()
        return response

    monkeypatch.setattr(HTTPAdapter, "send", send)
    client = job.CalibrationHistory.__new__(job.CalibrationHistory)
    StockHistoricalDataClient.__init__(
        client,
        api_key="offline",
        secret_key="offline",  # noqa: S106 - inert SDK fixture
        raw_data=True,
    )
    client.pacer = Pacer()
    client.pages = []
    client._session.hooks["response"].append(client._capture)
    try:
        with pytest.raises(ValueError, match="repeated"):
            job.archive(client, tmp_path, "AAPL", date(2026, 11, 6), "quotes", "sip", NOW)
    finally:
        client.close()
    assert not list(tmp_path.rglob("*.parquet"))
