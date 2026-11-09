"""House EDGAR Atom poller and bounded document parsers for catalyst arm f.

Sources, pinned: dgunning/edgartools@v5.62.1
``9f2ff388c0ad21cfbaba4c7587ba8be7abe6816d`` — ``edgar/current_filings.py``
(get_current_url, parse_title, parse_summary), ``edgar/xmltools.py``
(xml_parser, find_all_elements, child_text, local_name),
``edgar/_filings.py`` (Filing.from_sgml_text, text_url),
``edgar/sgml/sgml_header.py`` (acceptance_datetime),
``edgar/company_reports/current_report.py`` (EightK),
``edgar/company_reports/sixk.py`` (SixK) and ``edgar/httpclient.py``
(the cache-disabled, identity-bearing client; tests/conftest.py setup).
SEC access guidance (declared User-Agent, at most 10 requests/second):
https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
(read 2026-11-06 for the research recipe; a 2026-11-09 re-read was refused
HTTP 403 to the undeclared fetcher, so no content is claimed from it today).

Clocks stay separate (ADR-0003 K4, ADR-0013): the Atom ``<updated>`` and the
SGML ``ACCEPTANCE-DATETIME`` are source clocks, the poll receipt is the local
clock, and catalyst presence needs both. A missing clock stays unknown; no
clock is ever substituted for another, and no parsed document sets polarity.
This module performs one bounded poll per call: it invents no cadence, retry
or scheduler, because no registry row sources one. The SDK is imported only
inside functions; before the first call, set ``EDGAR_LOCAL_DATA_DIR`` to a
task-owned directory outside git, so the SDK's import-time cache migration
never touches shared data (the research recipe's rule).
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Any

__all__ = [
    "CATALYST_FORMS",
    "MAX_BODY",
    "ArchivedSubmission",
    "AtomNotice",
    "ParsedSubmission",
    "ReadFailure",
    "catalyst_present",
    "default_fetch",
    "fetch_submission",
    "parse_atom_page",
    "parse_submission",
    "poll_once",
]

CATALYST_FORMS = frozenset({"8-K", "8-K/A", "6-K", "6-K/A"})
_PAGE_COUNTS = frozenset({10, 20, 40, 80, 100})  # Upstream get_current_url's accepted set.
_OWNERS = frozenset({"include", "exclude", "only"})
# One count=100 Atom page in the upstream cassette is ~56 KB and the fixture
# 8-K submission is ~161 KB; this bound only refuses a runaway body. It is a
# transport bound, not a trading tunable.
MAX_BODY = 64 * 1024 * 1024
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
Fetch = Callable[[str], bytes]
Clock = Callable[[], datetime]


class ReadFailure(Exception):
    """A bounded SEC read failed; only the HTTP status (if any) is carried."""

    def __init__(self, status: int | None) -> None:
        self.http_status = status
        super().__init__("EDGAR read failed")


def _to_ns(value: datetime) -> int:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("a timezone-aware datetime is required")
    delta = value.astimezone(UTC) - _EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _check_body(raw: object) -> bytes:
    if not isinstance(raw, bytes) or not raw:
        raise ValueError("a non-empty bytes body is required")
    if len(raw) > MAX_BODY:
        raise ValueError("body exceeds the transport bound")
    return raw


@dataclass(frozen=True)
class AtomNotice:
    """One Latest Filings Atom entry, with its own feed-page provenance."""

    form: str
    company: str
    cik: int
    status: str
    filing_date: date
    accession: str
    accepted: datetime
    entry_id: str
    index_url: str
    feed_url: str
    received_ns: int
    raw_sha256: str

    def __post_init__(self) -> None:
        if any(not isinstance(v, str) or not v for v in (self.form, self.company, self.status)):
            raise ValueError("complete Atom title fields are required")
        if type(self.cik) is not int or self.cik <= 0:
            raise ValueError("a positive integer CIK is required")
        parts = self.accession.split("-")
        if (
            len(parts) != 3
            or [len(p) for p in parts] != [10, 2, 6]
            or not all(p.isdigit() for p in parts)
        ):
            raise ValueError("a dashed SEC accession number is required")
        if not isinstance(self.filing_date, date):
            raise ValueError("a filing date is required")
        _to_ns(self.accepted)  # The Atom <updated> must state its own offset.
        if not self.entry_id or not self.index_url.startswith("https://www.sec.gov/"):
            raise ValueError("a SEC entry id and index URL are required")
        if not self.feed_url.startswith("https://www.sec.gov/"):
            raise ValueError("a SEC feed URL is required")
        if type(self.received_ns) is not int or self.received_ns < 0:
            raise ValueError("a nonnegative integer receipt is required")
        if len(self.raw_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.raw_sha256):
            raise ValueError("the feed page SHA-256 is required")

    @property
    def is_catalyst(self) -> bool:
        return self.form in CATALYST_FORMS

    @property
    def accepted_ns(self) -> int:
        return _to_ns(self.accepted)

    @property
    def submission_url(self) -> str:
        """The full-submission .txt URL, in upstream Filing.text_url's shape."""
        from edgar import Filing

        filing = Filing(
            cik=self.cik,
            company=self.company,
            form=self.form,
            filing_date=self.filing_date.isoformat(),
            accession_no=self.accession,
        )
        return str(filing.text_url)


def catalyst_present(
    notices: Sequence[AtomNotice],
    *,
    cik: int,
    as_of_ns: int,
    forms: frozenset[str] = CATALYST_FORMS,
) -> bool:
    """True only when a catalyst filing was accepted *and* received by as_of.

    Presence is deliberately not knowable between SEC acceptance and this
    house's actual poll receipt, and never from a later backfill: that gap is
    exactly the look-ahead the historical arm must not take for free.
    """
    if type(cik) is not int or cik <= 0 or type(as_of_ns) is not int or as_of_ns < 0:
        raise ValueError("a positive CIK and nonnegative integer as-of are required")
    return any(
        n.cik == cik and n.form in forms and n.accepted_ns <= as_of_ns and n.received_ns <= as_of_ns
        for n in notices
    )


def parse_atom_page(raw: bytes, *, feed_url: str, received_ns: int) -> tuple[AtomNotice, ...]:
    """Parse one Atom page strictly; any malformed entry refuses the page.

    Upstream's own page reader tolerates an HTML error page as an empty feed
    (its comment records that as inherited behavior under separate question).
    A catalyst clock cannot take that reading: an error page, a naive
    ``<updated>``, or a category/id that disagrees with the title/summary is
    a failed poll, never silently no catalyst.
    """
    body = _check_body(raw)
    if not feed_url.startswith("https://www.sec.gov/"):
        raise ValueError("a SEC feed URL is required")
    if type(received_ns) is not int or received_ns < 0:
        raise ValueError("a nonnegative integer receipt is required")
    import lxml.etree as etree
    from edgar.current_filings import parse_summary, parse_title
    from edgar.xmltools import child_text, find_all_elements, local_name, xml_parser

    try:
        root = etree.fromstring(body, parser=xml_parser())
    except Exception:
        raise ValueError("the feed page is not well-formed XML") from None
    if root is None or local_name(root) != "feed":
        raise ValueError("the feed page is not an Atom feed")
    page_sha = _sha(body)
    notices: list[AtomNotice] = []
    for entry in find_all_elements(root, "entry"):
        title, summary = child_text(entry, "title"), child_text(entry, "summary")
        updated, entry_id = child_text(entry, "updated"), child_text(entry, "id")
        if not title or not summary or not updated or not entry_id:
            raise ValueError("an Atom entry is missing title, summary, updated or id")
        form, company, cik_text, status = parse_title(title)
        filing_date, accession = parse_summary(summary)
        accession = str(accession)
        categories = find_all_elements(entry, "category")
        for category in categories:
            term = category.get("term")
            if term is not None and term != form:
                raise ValueError("an Atom entry category disagrees with its title form")
        marker = "accession-number="
        if marker in entry_id and entry_id.rsplit(marker, 1)[1] != accession:
            raise ValueError("an Atom entry id disagrees with its summary accession")
        index_url = None
        for link in find_all_elements(entry, "link"):
            if link.get("rel") in (None, "alternate"):
                index_url = link.get("href")
                break
        if not index_url:
            raise ValueError("an Atom entry is missing its index link")
        try:
            accepted = datetime.fromisoformat(updated)
        except ValueError:
            raise ValueError("an Atom entry updated time is not ISO format") from None
        notices.append(
            AtomNotice(
                form=str(form),
                company=str(company),
                cik=int(cik_text),
                status=str(status),
                filing_date=filing_date,
                accession=accession,
                accepted=accepted,
                entry_id=entry_id,
                index_url=str(index_url),
                feed_url=feed_url,
                received_ns=received_ns,
                raw_sha256=page_sha,
            )
        )
    return tuple(notices)


def default_fetch() -> Fetch:
    """The adopted upstream client: declared identity, cache off, upstream pacing.

    Refuses before any request when ``EDGAR_IDENTITY`` is unset; the identity
    is read by the SDK from the environment and never logged here. Callers
    set ``EDGAR_LOCAL_DATA_DIR`` to a task-owned directory before this first
    SDK import, exactly as the research recipe requires.
    """
    if not os.environ.get("EDGAR_IDENTITY"):
        raise ValueError("EDGAR_IDENTITY must name the declared SEC contact before a request")
    from edgar import httpclient

    httpclient.close_clients()
    httpclient.HTTP_MGR = httpclient.get_http_mgr(cache_enabled=False)

    def fetch(url: str) -> bytes:
        if not url.startswith("https://www.sec.gov/"):
            raise ValueError("only SEC URLs may be fetched")
        try:
            with httpclient.http_client() as client:
                reply = client.get(url)
        except Exception:
            raise ReadFailure(None) from None
        if reply.status_code != 200:
            raise ReadFailure(int(reply.status_code))
        return _check_body(reply.content)

    return fetch


def poll_once(
    *,
    fetch: Fetch | None = None,
    clock: Clock = lambda: datetime.now(UTC),
    form: str = "",
    count: int = 100,
    start: int = 0,
    owner: str = "include",
) -> tuple[AtomNotice, ...]:
    """One bounded Atom poll: one page, receipt-stamped when its bytes arrive.

    ``count``/``owner`` outside upstream's accepted sets are refused rather
    than silently replaced (upstream's URL builder falls back to 40/include,
    a substitution a recorded poll must not hide). No loop or interval is
    supplied; a caller's schedule owns cadence, and overlap/deduplication
    across polls is the caller's record to keep from these notices' identity.
    """
    if count not in _PAGE_COUNTS:
        raise ValueError(f"count must be one of {sorted(_PAGE_COUNTS)}")
    if owner not in _OWNERS:
        raise ValueError(f"owner must be one of {sorted(_OWNERS)}")
    if type(start) is not int or start < 0:
        raise ValueError("a nonnegative integer start is required")
    if not isinstance(form, str):
        raise ValueError("form must be a string filter, empty for every form")
    from edgar.current_filings import get_current_url

    url = str(get_current_url(atom=True, count=count, start=start, form=form, owner=owner))
    raw = _check_body((fetch or default_fetch())(url))
    return parse_atom_page(raw, feed_url=url, received_ns=_to_ns(clock()))


@dataclass(frozen=True)
class ArchivedSubmission:
    """Filing bytes as received, hashed before any parsing. Storage is the caller's."""

    accession: str
    source_url: str
    received_ns: int
    raw_sha256: str
    raw: bytes = field(compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.raw_sha256 != _sha(_check_body(self.raw)):
            raise ValueError("archived bytes do not match their SHA-256")
        if type(self.received_ns) is not int or self.received_ns < 0:
            raise ValueError("a nonnegative integer receipt is required")


def fetch_submission(
    notice: AtomNotice,
    *,
    fetch: Fetch | None = None,
    clock: Clock = lambda: datetime.now(UTC),
) -> ArchivedSubmission:
    """Fetch one notice's full submission once, behind its byte hash."""
    url = notice.submission_url
    raw = _check_body((fetch or default_fetch())(url))
    return ArchivedSubmission(
        accession=notice.accession,
        source_url=url,
        received_ns=_to_ns(clock()),
        raw_sha256=_sha(raw),
        raw=raw,
    )


@dataclass(frozen=True)
class ParsedSubmission:
    """A bounded 8-K/6-K parse over archived bytes; no polarity is assigned."""

    form: str
    company: str
    cik: int
    accession: str
    filing_date: str
    acceptance: datetime | None
    source_url: str
    received_ns: int | None
    raw_sha256: str
    items: Mapping[str, str]
    exhibit_types: tuple[str, ...]
    date_of_report: date | None

    def __post_init__(self) -> None:
        if self.form not in CATALYST_FORMS:
            raise ValueError("only the bounded 8-K/6-K families are parsed")
        if self.acceptance is not None and self.acceptance.tzinfo is not None:
            raise ValueError("archived acceptance is kept exactly as upstream returns it")
        if self.received_ns is not None and (
            type(self.received_ns) is not int or self.received_ns < 0
        ):
            raise ValueError("receipt must be a nonnegative integer or unknown")


def parse_submission(
    raw: bytes,
    *,
    source_url: str,
    received_ns: int | None = None,
) -> ParsedSubmission:
    """Parse archived full-submission bytes with the pinned native parsers.

    8-K/8-K/A returns EightK item texts keyed by upstream's item spellings.
    6-K/6-K/A returns SixK's exhibit document types and date of report; the
    cover fields whose upstream path can fetch a primary document when the
    SGML lacks one are outside this bounded adoption. Any other form is
    refused. Numbers stay inside the item text as the filer wrote them.
    """
    body = _check_body(raw)
    if not isinstance(source_url, str) or not source_url:
        raise ValueError("an archived source URL is required")
    from edgar import Filing

    try:
        text = body.decode("utf-8")
        filing = Filing.from_sgml_text(text)
        form = str(filing.form)
        if form not in CATALYST_FORMS:
            raise ValueError(f"unsupported form for the bounded catalyst parsers: {form!r}")
        items: dict[str, str] = {}
        exhibit_types: tuple[str, ...] = ()
        report_date: date | None = None
        if form in ("8-K", "8-K/A"):
            from edgar.company_reports import EightK

            report = EightK(filing)
            for item in report.items:
                section: Any = report[item]
                if not isinstance(section, str):
                    raise ValueError("an 8-K item did not parse to text")
                items[str(item)] = section
        else:
            from edgar.company_reports import SixK

            report = SixK(filing)
            exhibit_types = tuple(
                str(att.document_type) for att in report.exhibits if att.document_type
            )
            report_date = report.date_of_report
        acceptance = filing.header.acceptance_datetime
    except ValueError:
        raise
    except Exception:
        raise ValueError("the archived bytes are not a parseable SEC submission") from None
    return ParsedSubmission(
        form=form,
        company=str(filing.company),
        cik=int(filing.cik),
        accession=str(filing.accession_no),
        filing_date=str(filing.filing_date),
        acceptance=acceptance,
        source_url=source_url,
        received_ns=received_ns,
        raw_sha256=_sha(body),
        items=MappingProxyType(items),
        exhibit_types=exhibit_types,
        date_of_report=report_date,
    )
