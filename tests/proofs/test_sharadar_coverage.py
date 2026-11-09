"""Offline vendor-shaped fixtures; observations never grant PIT or licence authority."""

import copy
import csv
import hashlib
import io
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research import sharadar_coverage as coverage  # noqa: E402

FIXTURE = Path(__file__).parents[1] / "fixtures/sharadar/tables.json"
NOW = datetime(2026, 11, 6, 16, 0, tzinfo=UTC)
EVENTS = [
    {"cohort": "selected_gainer", "session_date": "2021-01-04", "symbol": "OLD", "known_at": None},
    {"cohort": "selected_gainer", "session_date": "2025-01-03", "symbol": "REC", "known_at": None},
    {"cohort": "selected_loser", "session_date": "2025-01-03", "symbol": "LOST", "known_at": None},
]


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


def _capture(tmp_path: Path, fetch: Any = None) -> Path:
    root = tmp_path / "capture"
    coverage.capture(
        EVENTS,
        root,
        asof=NOW,
        seed_sha256="a" * 64,
        implementation_sha="b" * 40,
        fetch=fetch or FixtureFetch(),
        clock=lambda: NOW,
    )
    return root


def _report(tmp_path: Path, fetch: Any = None) -> tuple[dict, list[dict]]:
    root = _capture(tmp_path, fetch)
    report = coverage.report(EVENTS, root, tmp_path / "report", seed_sha256="a" * 64)
    rows = [
        json.loads(line) for line in (tmp_path / "report/events.jsonl").read_text().splitlines()
    ]
    return report, rows


def test_exact_seed_dates_and_selected_cohorts_survive_the_join(tmp_path: Path) -> None:
    result, events = _report(tmp_path)
    assert result["seed_coverage"]["selected_gainer"] == {
        "events": 2,
        "price_observed": 1,
        "absent": 1,
        "unknown": 0,
        "ambiguous": 0,
    }
    assert result["seed_coverage"]["selected_loser"]["price_observed"] == 0
    assert events[0]["symbol"] == "OLD"  # A related ticker is evidence, never a rewrite.
    assert events[0]["prices"]["SEP"]["status"] == "absent"
    assert events[0]["master_candidates"][0]["permaticker"] == "101"
    assert events[1]["prices"]["SEP"]["rows"][0]["closeunadj"] == "0.100000000000000001"
    assert events[2]["prices"]["SEP"]["status"] == "missing_price"
    assert all(e["known_at"] is None and not e["identity_verified"] for e in events)


def test_recycled_ticker_and_latest_updates_never_establish_historical_identity(
    tmp_path: Path,
) -> None:
    result, events = _report(tmp_path)
    assert {r["permaticker"] for r in events[1]["master_candidates"]} == {"201", "202"}
    assert result["survivor_only"] is True and result["pit_verified"] is False
    assert result["historical_known_at"] is None
    assert result["capture_mode"] == "offline_fixture"
    assert result["acceptance"]["independent_delisted_sample"] == {
        "status": "NOT_RUN",
        "minimum_coverage": "0.95",
        "sample_sha256": None,
        "denominator": None,
        "covered": None,
    }
    assert result["acceptance"]["ten_exit_identities"] == "NOT_RUN"
    assert result["float_history"]["status"] == "UNVERIFIED"
    assert result["float_history"]["shares_outstanding_is_float"] is False
    manifest = json.loads((tmp_path / "report/universe_manifest.json").read_text())
    assert manifest["members"] == [] and manifest["pit_verified"] is False


def test_all_receipts_hash_exact_bytes_and_offline_rerun_is_idempotent(tmp_path: Path) -> None:
    result, _ = _report(tmp_path)
    for name, expected in result["artifacts"].items():
        assert hashlib.sha256((tmp_path / "report" / name).read_bytes()).hexdigest() == expected
    assert (
        coverage.report(EVENTS, tmp_path / "capture", tmp_path / "report", seed_sha256="a" * 64)
        == result
    )
    session = json.loads((tmp_path / "report/sessions/2025-01-03.json").read_text())
    assert session["historical_known_at"] is None
    assert session["capture_sha256"] == result["capture_sha256"]
    assert session["asof"] == NOW.isoformat()


def test_denied_table_is_unknown_not_zero_and_never_persists_exception_text(tmp_path: Path) -> None:
    fixture = FixtureFetch()

    def denied(table: str, params: dict) -> bytes:
        if table == "SEP":
            raise RuntimeError("credential-echo-must-not-persist https://unsafe.example")
        return fixture(table, params)

    result, events = _report(tmp_path, denied)
    assert result["seed_coverage"]["selected_gainer"]["unknown"] == 2
    assert events[1]["prices"]["SEP"]["status"] == "unknown"
    assert not any(t == "SEP" for t, _ in fixture.calls)
    assert all(
        b"credential-echo-must-not-persist" not in p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    )


def test_pagination_is_exhausted_before_reporting_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(coverage, "PAGE_SIZE", 1)
    fixture = FixtureFetch()
    result, events = _report(tmp_path, fixture)
    assert len(events[1]["master_candidates"]) == 2
    assert result["tables"]["SEP"]["complete"] is True
    master_calls = [p for t, p in fixture.calls if t == "TICKERS"]
    assert master_calls == [{"years": "full"}]
    assert any(t == "SEP" and p.get("skip") == 2 for t, p in fixture.calls)


def test_repeated_slice_page_retains_partial_evidence_without_claiming_completeness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(coverage, "PAGE_SIZE", 1)
    fixture = FixtureFetch()

    def repeated(table: str, params: dict) -> bytes:
        return fixture(table, {**params, "skip": 0} if table == "SEP" else params)

    result, _ = _report(tmp_path, repeated)
    assert result["tables"]["SEP"]["complete"] is False
    assert result["dated_universe"]["status"] == "UNVERIFIED"


@pytest.mark.parametrize("fault", ["raw_hash", "seed_hash", "events_hash"])
def test_modified_sources_refuse_before_publishing_report(tmp_path: Path, fault: str) -> None:
    root = _capture(tmp_path)
    events = copy.deepcopy(EVENTS)
    seed_hash = "a" * 64
    if fault == "raw_hash":
        next((root / "raw").iterdir()).write_text("{}")
    elif fault == "seed_hash":
        seed_hash = "c" * 64
    else:
        events[0]["symbol"] = "CHANGED"
    with pytest.raises(ValueError, match=r"hash|SHA"):
        coverage.report(events, root, tmp_path / "report", seed_sha256=seed_hash)
    assert not (tmp_path / "report").exists()


def test_a_second_capture_refuses_even_when_the_first_used_fixtures(tmp_path: Path) -> None:
    _capture(tmp_path)
    with pytest.raises(ValueError, match=r"existing|immutable"):
        _capture(tmp_path)


def test_naive_cutoff_and_future_seed_dates_refuse_before_fetch(tmp_path: Path) -> None:
    fixture = FixtureFetch()
    for cutoff in (NOW.replace(tzinfo=None), NOW.replace(year=2020)):
        with pytest.raises(ValueError):
            coverage.capture(
                EVENTS,
                tmp_path / "capture",
                asof=cutoff,
                seed_sha256="a" * 64,
                implementation_sha="b" * 40,
                fetch=fixture,
                clock=lambda: NOW,
            )
    assert fixture.calls == []


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
    fetch = coverage.direct_client()
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
        coverage.direct_client()


def test_csv_numeric_prices_keep_their_exact_decimal_text() -> None:
    _, rows = coverage.parse_response(b"closeunadj\n0.100000000000000001\n")
    assert rows == [{"closeunadj": "0.100000000000000001"}]


def test_missing_required_vendor_column_is_unknown_instead_of_an_absent_price(
    tmp_path: Path,
) -> None:
    fixture = FixtureFetch()

    def malformed(table: str, params: dict) -> bytes:
        if table == "SEP" and "from" in params:
            return b"unrelated\nretained source text\n"
        return fixture(table, params)

    result, events = _report(tmp_path, malformed)
    assert result["seed_coverage"]["selected_gainer"]["unknown"] == 2
    assert events[0]["prices"]["SEP"]["status"] == "unknown"


def test_duplicate_price_rows_are_ambiguous_and_never_deduplicated(tmp_path: Path) -> None:
    fixture = FixtureFetch()
    fixture.tables["SEP"]["data"].append(copy.deepcopy(fixture.tables["SEP"]["data"][0]))
    result, events = _report(tmp_path, fixture)
    assert result["seed_coverage"]["selected_gainer"]["ambiguous"] == 1
    assert len(events[1]["prices"]["SEP"]["rows"]) == 2


def test_completed_price_queries_have_complete_coverage_even_with_a_schema_probe(
    tmp_path: Path,
) -> None:
    result, _ = _report(tmp_path)
    assert result["tables"]["SEP"]["complete"] is True
    assert result["tables"]["SF1"]["complete"] is False


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
    assert coverage.direct_client()("TICKERS", {"years": "full"}) == body
    assert calls[0]["headers"]["x-api-key"] == "fixture-not-a-real-api-key"
    assert calls[1]["headers"] == {} and calls[1]["allow_redirects"] is False


def test_bulk_archives_never_extract_paths_and_refuse_multiple_members() -> None:
    zipped = io.BytesIO()
    with ZipFile(zipped, "w") as archive:
        archive.writestr("../../outside.csv", "ticker\nONE\n")
        archive.writestr("second.csv", "ticker\nTWO\n")
    with pytest.raises(ValueError):
        coverage.parse_response(zipped.getvalue())


def test_access_probe_makes_one_bounded_read_and_records_no_entitlement(tmp_path: Path) -> None:
    from sextant.research.sharadar_client import probe

    fixture = FixtureFetch()
    receipt = probe(tmp_path / "probe.json", fetch=fixture, clock=lambda: NOW)
    assert fixture.calls == [("TICKERS", {"ticker": "TWO", "limit": 1, "format": "csv"})]
    assert receipt["http_status"] == 200 and receipt["entitlement_verified"] is False
    assert receipt["mode"] == "offline_fixture"


def test_row_11_admits_the_empty_member_manifest_at_its_reported_hash(tmp_path: Path) -> None:
    # The #42/#73 seam: row 11's loader reads row 4's manifest only at the receipt's hash,
    # yields no members until acceptance, and keeps the selection survivor_only.
    from datetime import date

    from sextant.data.universe import manifest_universe

    result, _ = _report(tmp_path)
    path = tmp_path / "report/universe_manifest.json"
    universe = manifest_universe(
        path,
        sha256=result["artifacts"]["universe_manifest.json"],
        start=date(2021, 1, 4),
        end=date(2025, 1, 3),
    )
    selection = universe.universe_for_date(date(2025, 1, 3))
    assert selection.symbols == ()
    assert selection.provenance.report_fields()["survivor_only"] is True
    assert selection.provenance.pit_verified is False
