"""#42's sample pre-registration, offline: fixed index, seed and rule give a fixed draw."""

import hashlib
import json
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research import delisted_sample as sample  # noqa: E402

HEADER = b"Form Type   Company Name   CIK   Date Filed   File Name\n" + b"-" * 40 + b"\n"
IDENTITY = "Sextant proof offline@example.invalid"  # Public test identity; transport is mocked.


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """test_edgartools.py's guard: sockets denied and a task-owned EdgarTools data directory."""

    def denied(*_args, **_kwargs):
        pytest.fail("The sample proof attempted network access")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setenv("EDGAR_LOCAL_DATA_DIR", str(tmp_path / "edgar"))
    monkeypatch.delenv("EDGAR_IDENTITY", raising=False)


def _accession(cik: str, day: str, seq: int = 1) -> str:
    return f"{int(cik):010d}-{day[2:4]}-{seq:06d}"


def _index(rows: list[tuple[str, str, str, str, str]]) -> bytes:
    """SEC's form.idx layout: fixed-width form, company, CIK and date, then the file name."""
    lines = [
        f"{form:<12}{name:<62}{cik:<12}{day:<12}edgar/data/{cik}/{accession}.txt"
        for form, name, cik, day, accession in rows
    ]
    return HEADER + "\n".join(lines).encode() + b"\n"


def _filing(cls: str) -> bytes:
    return (
        "<SEC-DOCUMENT><XML><edgarSubmission><issuer><cik>77</cik><entityName>ISSUER"
        f"</entityName></issuer><descriptionClassSecurity>{cls}"
        "</descriptionClassSecurity><ruleProvision>12d2-2(a)(3)</ruleProvision>"
        "</edgarSubmission></XML></SEC-DOCUMENT>"
    ).encode()


def test_index_rows_keep_only_form_25_nse_with_multiword_names() -> None:
    acme = _accession("123", "2017-03-01")
    body = _index(
        [
            ("25-NSE", "ACME HOLDINGS  INC", "123", "2017-03-01", acme),
            ("25", "X", "9", "2017-03-01", _accession("9", "2017-03-01")),
            ("25-NSE/A", "Y", "8", "2017-03-01", _accession("8", "2017-03-01")),
        ]
    )
    assert sample.parse_index(body) == [
        {
            "company": "ACME HOLDINGS INC",
            "cik": "123",
            "filed": "2017-03-01",
            "path": f"edgar/data/123/{acme}.txt",
        }
    ]


@pytest.mark.parametrize(
    ("cls", "common"),
    [
        ("Common Stock, par value $0.01", True),
        ("Class A Common Stock", True),
        ("Common Shares of Beneficial Interest", True),
        ("7% Cumulative Trust Preferred Securities", False),
        ("Warrants to purchase Common Stock", False),
        ("American Depositary Shares, each representing one ordinary share", False),
        ("Units, each consisting of one share of Common Stock", False),
        (None, False),
    ],
)
def test_the_common_stock_rule_is_fixed(cls: str | None, common: bool) -> None:
    assert sample.is_common(cls) is common


def test_the_seeded_walk_is_reproducible_and_skips_other_classes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sample, "N", 3)
    ciks = [str(1000 + i) for i in range(12)]
    rows = [("25-NSE", f"CO {c}", c, "2018-05-01", _accession(c, "2018-05-01")) for c in ciks]
    classes = {c: "Common Stock" if i % 2 else "Preferred Stock" for i, c in enumerate(ciks)}

    def fetch(path: str) -> bytes:
        if path.endswith("form.idx"):
            return _index(rows) if path == "edgar/full-index/2018/QTR2/form.idx" else HEADER
        return _filing(classes[path.split("/")[2]])

    first = sample.draw(fetch, tmp_path / "a")
    again = sample.draw(fetch, tmp_path / "b")
    assert first == again and len(first["indexes"]) == 37  # 2016-Q4 through 2025-Q4.
    assert [s["class"] for s in first["sample"]] == ["Common Stock"] * 3
    assert all(s["class"] == "Preferred Stock" for s in first["skipped_non_common"])
    assert first["candidates"] == 12 and first["seed"] == sample.SEED
    assert first["sample"][0]["issuer_cik"] == "77"


def test_a_filing_listed_under_issuer_and_exchange_is_one_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sample, "N", 1)
    one = _accession("77", "2018-05-01")
    body = _index(
        [
            ("25-NSE", "ISSUER", "77", "2018-05-01", one),
            ("25-NSE", "EXCHANGE", "876661", "2018-05-01", one),  # One accession, two CIK dirs.
        ]
    )

    def fetch(path: str) -> bytes:
        if path.endswith("form.idx"):
            return body if path == "edgar/full-index/2018/QTR2/form.idx" else HEADER
        return _filing("Common Stock")

    result = sample.draw(fetch, tmp_path / "c")
    assert (result["candidates"], result["index_rows"]) == (1, 2)


# The registration the replaced, self-built quarter list and form.idx parser (#133 at 2aac686)
# drew from these indexes.
REPLACED_DRAW = "322cbaf71c5857ca3b75a364c43c733db7674f3d3bbb0082186ebd91033786da"


def test_edgartools_index_reader_changes_no_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zero difference: EdgarTools' quarters and form.idx reader replaced the house parser."""
    monkeypatch.setattr(sample, "N", 4)
    nyse = ("NEW YORK STOCK EXCHANGE LLC", "876661")
    quarters: dict[str, list[tuple[str, str, str, str, str]]] = {
        "2016/QTR4": [
            ("25-NSE", "EARLY  CO", "124", "2016-09-30", _accession("124", "2016-09-30"))
        ],
        "2021/QTR2": [],
        "2025/QTR4": [],
    }
    classes: dict[str, str] = {}
    for i in range(9):
        cik, quarter = str(200 + i), ("2016/QTR4", "2021/QTR2", "2025/QTR4")[i % 3]
        day = {"2016/QTR4": "2016-11-01", "2021/QTR2": "2021-05-03", "2025/QTR4": "2025-12-31"}
        accession = _accession(cik, day[quarter], i)
        quarters[quarter].append(("25-NSE", f"ISSUER {i}  INC", cik, day[quarter], accession))
        if i % 2:
            quarters[quarter].append(("25-NSE", *nyse, day[quarter], accession))
        other = _accession(cik, day[quarter], 100 + i)  # A Form 25 by the issuer: not this form.
        quarters[quarter].append(("25", f"ISSUER {i}  INC", cik, day[quarter], other))
        classes[accession] = ("Common Stock", "Preferred Stock", "Class A Common Shares")[i % 3]

    def fetch(path: str) -> bytes:
        if path.endswith("form.idx"):
            return _index(quarters.get(path.removeprefix("edgar/full-index/")[:9], []))
        return _filing(classes[path.rsplit("/", 1)[-1].removesuffix(".txt")])

    registration = sample.draw(fetch, tmp_path / "raw")
    assert (registration["candidates"], registration["index_rows"]) == (9, 13)
    body = json.dumps(registration, indent=2, sort_keys=True).encode()
    assert hashlib.sha256(body).hexdigest() == REPLACED_DRAW


def test_requests_need_the_environment_identity_and_use_the_cache_off_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No invented contact: EDGAR_IDENTITY or no request; upstream throttle at SecClient's 2/s."""
    with pytest.raises(SystemExit, match="EDGAR_IDENTITY"):
        sample.sec_fetch()
    monkeypatch.setenv("EDGAR_IDENTITY", IDENTITY)
    from edgar import httpclient
    from httpxthrottlecache._compat import httpx

    monkeypatch.setattr(httpclient, "HTTP_MGR", httpclient.HTTP_MGR)  # Restored after the test.
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers["User-Agent"]))
        return httpx.Response(200, content=b"form.idx bytes")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _transport, r: respond(r))
    fetch = sample.sec_fetch()
    manager = httpclient.HTTP_MGR
    try:
        assert (manager.cache_mode, manager.request_per_sec_limit) == ("Disabled", 2)
        assert fetch("edgar/full-index/2017/QTR1/form.idx") == b"form.idx bytes"
        assert seen == [
            ("https://www.sec.gov/Archives/edgar/full-index/2017/QTR1/form.idx", IDENTITY)
        ]
    finally:
        manager.close()
