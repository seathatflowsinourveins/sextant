"""PR-F7 (reconcile C7/C8): house EDGAR Atom poller + bounded document parsers.

Source: dgunning/edgartools@v5.62.1 9f2ff388c0ad21cfbaba4c7587ba8be7abe6816d,
edgar/current_filings.py (get_current_url, parse_title, parse_summary),
edgar/xmltools.py (xml_parser, find_all_elements, child_text),
edgar/_filings.py (Filing.from_sgml_text, text_url), company_reports
(current_report EightK, sixk SixK); the Atom fixture entries are verbatim
excerpts of that pin's tests/cassettes/test_get_all_current_filings.yaml
(real SEC Latest Filings Atom bytes). Sockets are denied: no real SEC
request, paired timing or catalyst merit is claimed.
"""

import hashlib
import socket
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from sextant.data import edgar_feed

ATOM = Path(__file__).parent / "fixtures" / "edgar" / "atom-current-excerpt.xml"
SGML = Path(__file__).parent / "fixtures" / "edgar" / "0000943374-24-000509.txt"
ATOM_SHA256 = "43e2f8f71b960d96a480008dc2ae3203c5378b410eeda53803860f974900631b"
FEED_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent"
    "&count=100&start=100&type=&owner=include&output=atom"
)
RECEIVED = datetime(2025, 12, 12, 23, 4, 0, tzinfo=UTC)  # 18:04:00-05:00, after every entry


def _ns(value: datetime) -> int:
    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


RECEIVED_NS = _ns(RECEIVED)


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def denied(*_args, **_kwargs):
        pytest.fail("EDGAR Atom proof attempted network access")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    # Public test identity only; sockets are denied and transports are faked.
    monkeypatch.setenv("EDGAR_IDENTITY", "Sextant proof offline@example.invalid")
    monkeypatch.setenv("EDGAR_LOCAL_DATA_DIR", str(tmp_path / "edgar"))


def _notices() -> tuple:
    return edgar_feed.poll_once(fetch=lambda _url: ATOM.read_bytes(), clock=lambda: RECEIVED)


def test_atom_poll_preserves_feed_order_identity_and_clocks() -> None:
    raw = ATOM.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ATOM_SHA256
    seen_urls: list[str] = []

    def fetch(url: str) -> bytes:
        seen_urls.append(url)
        return raw

    notices = edgar_feed.poll_once(fetch=fetch, clock=lambda: RECEIVED)
    assert seen_urls == [FEED_URL.replace("&start=100", "&start=0")]
    assert [n.form for n in notices] == ["8-K", "6-K", "4"]
    eight_k, six_k, form4 = notices
    assert (eight_k.company, eight_k.cik, eight_k.status) == (
        "Flux Power Holdings, Inc.",
        1083743,
        "Filer",
    )
    assert eight_k.filing_date == date(2025, 12, 12)
    assert eight_k.accession == "0001493152-25-027595"
    assert eight_k.entry_id == "urn:tag:sec.gov,2008:accession-number=0001493152-25-027595"
    assert eight_k.index_url.endswith("/0001493152-25-027595-index.htm")
    assert eight_k.accepted == datetime.fromisoformat("2025-12-12T17:31:08-05:00")
    assert six_k.accepted == datetime.fromisoformat("2025-12-12T17:25:02-05:00")
    for notice in notices:
        assert notice.received_ns == RECEIVED_NS
        assert notice.raw_sha256 == ATOM_SHA256
        assert notice.feed_url == seen_urls[0]
        assert notice.accepted_ns == _ns(notice.accepted)
    # Only 8-K/6-K families feed the catalyst arm; a Form 4 never does.
    assert [n.is_catalyst for n in notices] == [True, True, False]
    assert form4.status == "Issuer"
    # Upstream Filing.text_url shape, from the notice identity alone.
    assert eight_k.submission_url == (
        "https://www.sec.gov/Archives/edgar/data/1083743/"
        "000149315225027595/0001493152-25-027595.txt"
    )


def test_catalyst_presence_needs_both_acceptance_and_local_receipt() -> None:
    notices = _notices()
    eight_k = notices[0]
    # Before acceptance: not present.
    assert not edgar_feed.catalyst_present(notices, cik=1083743, as_of_ns=eight_k.accepted_ns - 1)
    # After acceptance but before our poll actually received it: still not
    # knowable here (no look-ahead from a later receipt or backfill).
    assert not edgar_feed.catalyst_present(notices, cik=1083743, as_of_ns=RECEIVED_NS - 1)
    # At the receipt instant it becomes knowable, and stays so.
    assert edgar_feed.catalyst_present(notices, cik=1083743, as_of_ns=RECEIVED_NS)
    assert edgar_feed.catalyst_present(notices, cik=2018462, as_of_ns=RECEIVED_NS + 10**9)
    # A Form 4 for another CIK is never this arm's catalyst.
    assert not edgar_feed.catalyst_present(notices, cik=1785530, as_of_ns=RECEIVED_NS)
    assert not edgar_feed.catalyst_present(notices, cik=9999999, as_of_ns=RECEIVED_NS)
    assert not edgar_feed.catalyst_present((), cik=1083743, as_of_ns=RECEIVED_NS)


def test_poll_rejects_unsourced_page_shape_instead_of_silent_fallbacks() -> None:
    raw = ATOM.read_bytes()
    clock = lambda: RECEIVED  # noqa: E731
    with pytest.raises(ValueError):
        edgar_feed.poll_once(fetch=lambda _u: raw, clock=clock, count=41)
    with pytest.raises(ValueError):
        edgar_feed.poll_once(fetch=lambda _u: raw, clock=clock, owner="everyone")
    with pytest.raises(ValueError):
        edgar_feed.poll_once(fetch=lambda _u: raw, clock=clock, start=-1)
    # A naive receipt clock cannot stamp a PIT receipt.
    with pytest.raises(ValueError):
        edgar_feed.poll_once(fetch=lambda _u: raw, clock=lambda: datetime(2025, 12, 12))
    # An HTML error page (SEC 503 shape) is a failure, never an empty feed.
    with pytest.raises(ValueError):
        edgar_feed.poll_once(
            fetch=lambda _u: b"<html><head><title>503</title></head></html>", clock=clock
        )
    with pytest.raises(ValueError):
        edgar_feed.poll_once(fetch=lambda _u: b"", clock=clock)
    with pytest.raises(ValueError):
        edgar_feed.poll_once(
            fetch=lambda _u: raw.replace(b'term="8-K"', b'term="10-K"'), clock=clock
        )
    with pytest.raises(ValueError):
        edgar_feed.poll_once(
            fetch=lambda _u: raw.replace(
                b"accession-number=0001493152-25-027595", b"accession-number=0001493152-25-999999"
            ),
            clock=clock,
        )
    # A naive <updated> has no stated zone: refused, never assumed ET/UTC.
    with pytest.raises(ValueError):
        edgar_feed.poll_once(
            fetch=lambda _u: raw.replace(b"2025-12-12T17:31:08-05:00", b"2025-12-12T17:31:08"),
            clock=clock,
        )
    with pytest.raises(ValueError):
        edgar_feed.poll_once(fetch=lambda _u: raw + b"x", clock=clock)


def test_fetch_submission_archives_bytes_hash_and_receipt_before_parse() -> None:
    notice = _notices()[0]
    body = SGML.read_bytes()
    seen: list[str] = []

    def fetch(url: str) -> bytes:
        seen.append(url)
        return body

    archived = edgar_feed.fetch_submission(notice, fetch=fetch, clock=lambda: RECEIVED)
    assert seen == [notice.submission_url]
    assert archived.raw == body
    assert archived.raw_sha256 == hashlib.sha256(body).hexdigest()
    assert archived.source_url == notice.submission_url
    assert archived.received_ns == RECEIVED_NS
    assert archived.accession == notice.accession

    def oversized(_url: str) -> bytes:
        return b"x" * (edgar_feed.MAX_BODY + 1)

    with pytest.raises(ValueError):
        edgar_feed.fetch_submission(notice, fetch=oversized, clock=lambda: RECEIVED)
    with pytest.raises(ValueError):
        edgar_feed.fetch_submission(notice, fetch=lambda _u: b"", clock=lambda: RECEIVED)


@pytest.mark.parametrize("with_acceptance", [True, False])
def test_parse_submission_8k_keeps_source_acceptance_separate_from_receipt(
    with_acceptance: bool,
) -> None:
    raw = SGML.read_bytes()
    text = raw.decode("utf-8")
    if not with_acceptance:
        text = text.replace("<ACCEPTANCE-DATETIME>20241227162940\n", "")
        raw = text.encode("utf-8")
    url = (
        "https://www.sec.gov/Archives/edgar/data/1847360/"
        "000094337424000509/0000943374-24-000509.txt"
    )
    parsed = edgar_feed.parse_submission(raw, source_url=url, received_ns=RECEIVED_NS)
    assert parsed.raw_sha256 == hashlib.sha256(raw).hexdigest()
    assert (parsed.form, parsed.cik, parsed.accession) == (
        "8-K",
        1847360,
        "0000943374-24-000509",
    )
    assert parsed.company == "1895 Bancorp of Wisconsin, Inc. /MD/"
    assert parsed.filing_date == "2024-12-27"
    assert parsed.source_url == url and parsed.received_ns == RECEIVED_NS
    # Upstream returns the archived acceptance as a naive datetime or None;
    # it is preserved exactly, never converted or substituted.
    expected = datetime(2024, 12, 27, 16, 29, 40) if with_acceptance else None
    assert parsed.acceptance == expected
    assert "Item 5.02" in parsed.items
    assert "employment agreements" in parsed.items["Item 5.02"]
    assert parsed.exhibit_types == () and parsed.date_of_report is None
    # Unknown receipt stays unknown.
    unknown = edgar_feed.parse_submission(raw, source_url=url)
    assert unknown.received_ns is None


def test_parse_submission_6k_dispatch_and_unsupported_forms() -> None:
    text = SGML.read_text()
    sixk_text = text.replace(
        "CONFORMED SUBMISSION TYPE:\t8-K", "CONFORMED SUBMISSION TYPE:\t6-K"
    ).replace("<TYPE>8-K", "<TYPE>6-K")
    parsed = edgar_feed.parse_submission(sixk_text.encode(), source_url="fixture://6k")
    # In-memory form edit of the verbatim fixture: this proves SixK dispatch,
    # identity and exhibit listing only, not real 6-K cover content.
    assert parsed.form == "6-K"
    assert parsed.items == {}
    assert "EXCEL" in parsed.exhibit_types and "ZIP" in parsed.exhibit_types
    assert parsed.date_of_report == date(2024, 12, 20)
    other = text.replace(
        "CONFORMED SUBMISSION TYPE:\t8-K", "CONFORMED SUBMISSION TYPE:\t10-K"
    ).replace("<TYPE>8-K", "<TYPE>10-K")
    with pytest.raises(ValueError):
        edgar_feed.parse_submission(other.encode(), source_url="fixture://10k")
    with pytest.raises(ValueError):
        edgar_feed.parse_submission(b"not a submission", source_url="fixture://junk")
    with pytest.raises(ValueError):
        edgar_feed.parse_submission(b"", source_url="fixture://empty")


def test_default_fetch_refuses_without_declared_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EDGAR_IDENTITY")
    with pytest.raises(ValueError, match="EDGAR_IDENTITY"):
        edgar_feed.default_fetch()


def test_default_fetch_sends_the_declared_identity_with_cache_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same mocked transport boundary as test_edgartools.py; sockets stay denied.
    from edgar import httpclient
    from httpxthrottlecache._compat import httpx

    seen: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200, content=ATOM.read_bytes())

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _t, r: respond(r))
    notices = edgar_feed.poll_once(clock=lambda: RECEIVED)
    assert [n.form for n in notices] == ["8-K", "6-K", "4"]
    assert seen == ["Sextant proof offline@example.invalid"]
    assert httpclient.HTTP_MGR.cache_mode == "Disabled"
    httpclient.close_clients()


def test_module_top_level_never_imports_the_sdk() -> None:
    # This file imported sextant.data.edgar_feed before any identity existed in
    # the process environment setup for SDK data dirs; the SDK is only pulled
    # in inside functions, so it is not bound as a module attribute.
    assert not hasattr(edgar_feed, "Filing")
    assert edgar_feed.CATALYST_FORMS == frozenset({"8-K", "8-K/A", "6-K", "6-K/A"})
