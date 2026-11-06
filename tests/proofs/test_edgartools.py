"""ADR-0003 K4 ADOPT-PART: native document parsing, never a poller or numeric feed.

Source: dgunning/edgartools@v5.62.1 9f2ff388c0ad21cfbaba4c7587ba8be7abe6816d,
tests/sgml/test_filing_sgml.py, tests/conftest.py and edgar/httpclient.py.
"""

import hashlib
import socket
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "edgar" / "0000943374-24-000509.txt"
SHA256 = "521de6ce26894f75f215215cbea9746932d5093908bfc45688b93e10cf43f394"


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def denied(*_args, **_kwargs):
        pytest.fail("EdgarTools document/parser proof attempted network access")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    # Public test identity only; the transport is mocked and sockets are denied.
    monkeypatch.setenv("EDGAR_IDENTITY", "Sextant proof offline@example.invalid")
    monkeypatch.setenv("EDGAR_LOCAL_DATA_DIR", str(tmp_path / "edgar"))


@pytest.mark.parametrize("with_acceptance", [True, False])
def test_native_8k_parser_preserves_archived_identity_and_missing_acceptance(with_acceptance):
    assert version("edgartools") == "5.62.1"
    from edgar import Filing
    from edgar.company_reports import EightK

    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA256
    text = raw.decode("utf-8")
    if not with_acceptance:
        text = text.replace("<ACCEPTANCE-DATETIME>20241227162940\n", "")
    filing = Filing.from_sgml_text(text)
    assert (filing.form, filing.cik, filing.accession_no) == (
        "8-K",
        1847360,
        "0000943374-24-000509",
    )
    assert filing.company == "1895 Bancorp of Wisconsin, Inc. /MD/"
    assert filing.filing_date == "2024-12-27"
    expected = datetime(2024, 12, 27, 16, 29, 40) if with_acceptance else None
    assert filing.header.acceptance_datetime == expected
    report = EightK(filing)
    assert "Item 5.02" in report.items
    section = report["5.02"]
    assert isinstance(section, str) and "employment agreements" in section
    assert isinstance(filing.text(), str)
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == SHA256


def test_native_client_uses_the_environment_identity_and_disables_http_cache(monkeypatch):
    from edgar import httpclient
    from httpxthrottlecache._compat import httpx

    # Adopt upstream tests/conftest.py's setup; do not rely on the stale cache-directory recipe.
    httpclient.close_clients()
    manager = httpclient.get_http_mgr(cache_enabled=False)
    monkeypatch.setattr(httpclient, "HTTP_MGR", manager)
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200, content=FIXTURE.read_bytes())

    # The locked manager selects httpx2 when installed; mock its chosen underlying boundary.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _transport, r: respond(r))
    try:
        assert manager.cache_mode == "Disabled"
        with httpclient.http_client() as client:
            reply = client.get("https://www.sec.gov/Archives/edgar/data/1847360/proof.txt")
        assert hashlib.sha256(reply.content).hexdigest() == SHA256
        assert seen == ["Sextant proof offline@example.invalid"]
    finally:
        manager.close()
