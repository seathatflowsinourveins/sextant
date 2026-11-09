# SEC documents with EdgarTools

EdgarTools supplies archived filing documents and parsers for the catalyst screen that serves ranking/entry, and the house EDGAR Atom poller (`src/sextant/data/edgar_feed.py`, PR-F7) supplies its notices one bounded page per call. This is **K4 ADOPT-PART**, carried by [ADR-0003](../../docs/adr/0003-ranking-and-feeds.md) and [ADR-0013](../../docs/adr/0013-us-equity-data-stack.md). It adds no broker access, inferred polarity or new primary feed. The house Atom poller's primary role and paired-timing requirement remain. A parsed document is not point-in-time availability or trading merit.

## Pin and native use

`uv sync --frozen` installs `edgartools==5.62.1`, MIT, dgunning/edgartools@v5.62.1 `9f2ff388c0ad21cfbaba4c7587ba8be7abe6816d`. GitHub published it 2026-10-23 01:52:53 UTC; both PyPI artifacts were uploaded that day. As read 2026-11-06 it is the latest release and over two weeks old, the lead's #53 selection rule. The lock records the wheel and sdist hashes; no AI/MCP/cloud extras are installed.

Use upstream APIs directly on an already archived full submission, outside git:

```python
from pathlib import Path
from edgar import Filing
from edgar.company_reports import EightK

raw = Path("/path/to/archived-submission.txt").read_bytes()
filing = Filing.from_sgml_text(raw.decode("utf-8"))
report = EightK(filing)  # explicitly an 8-K or 8-K/A, not generic numeric dispatch
sections = {item: report[item] for item in report.items}
accepted_header = filing.header.acceptance_datetime
```

Archive the original bytes/hash and source URL alongside the actual retrieval receipt before parsing. Keep `ACCEPTANCE-DATETIME` as source metadata; the native parser returns a naive datetime or `None`, not an aware receipt. Do not substitute the filing date, retrieval time or a default timestamp for missing acceptance. Unknown receipt/normalization/`knowable_at` stays unknown, and no parsed item assigns polarity by itself. Preserve lexical numbers; any later authorized money arithmetic uses `Decimal` or Nautilus types. Form 4 numeric/owner resolution, XBRL float/financial conveniences and companyfacts/frames normalization are outside this adoption; ADR-0013's Arelle choice remains.

## The house Atom poller and bounded parsers

`src/sextant/data/edgar_feed.py` wraps the pinned upstream pieces and nothing else: `poll_once` builds one Latest Filings Atom URL with upstream `get_current_url` (`count` in 10/20/40/80/100, `owner` include/exclude/only; refused, never silently replaced), fetches that one page, and stamps every entry with the local receipt taken when its bytes arrive. Entries are parsed strictly with upstream `parse_title`/`parse_summary` over `edgar.xmltools`' no-external-resources parser: an HTML error page, a naive `<updated>`, or a category/id that disagrees with the title/summary fails the poll instead of reading as no catalyst (upstream's tolerant empty-feed reading is deliberately not adopted, as its own comment leaves that policy under question). There is no loop, interval or retry: no registry row sources a cadence, so a caller's schedule owns it, and overlap between polls is the caller's record to deduplicate from notice identity (accession, CIK, form).

`catalyst_present(notices, cik=..., as_of_ns=...)` is the arm-f presence test: true only for an 8-K/8-K/A/6-K/6-K/A notice whose Atom acceptance **and** this house's receipt are both at or before `as_of_ns`. Between SEC acceptance and actual receipt the filing is not knowable here, and a later backfill never makes it knowable earlier. `fetch_submission` fetches a notice's full-submission `.txt` once (upstream `Filing.text_url` shape) behind its SHA-256; `parse_submission` then parses archived bytes only — EightK item texts for 8-K family, SixK exhibit types and date of report for 6-K family (cover fields whose upstream path can fetch a primary document stay outside this adoption) — refusing every other form. Storage of the bytes outside git remains the caller's.

## Any later explicit SEC request

Use the SDK's documented **`EDGAR_IDENTITY` environment setting**, containing the real operator/company contact, before importing it. Do not invent a contact or put it in a file, command line or log. `set_identity()` logs its argument at this pin, so use the environment method. Missing identity means no request; do not enter the SDK's interactive identity prompt. No SEC API key is required. Set `EDGAR_LOCAL_DATA_DIR` to a task-owned directory outside git before import so the SDK's import-time cache migration never touches shared/old-lane data.

K4 requires HTTP cache off. Adopt the setup from upstream `tests/conftest.py`, which actually wires this version's client:

```python
import os

if not os.environ.get("EDGAR_IDENTITY"):
    raise SystemExit("Configure the documented SEC contact before making a request")
from edgar import httpclient

httpclient.close_clients()
httpclient.HTTP_MGR = httpclient.get_http_mgr(cache_enabled=False)
```

The pin's configuration page still mentions a `CACHE_DIRECTORY` assignment; its implementation uses `HTTP_MGR`, so that old assignment is not our setup. Retain upstream rate limiting and TLS verification; SEC's published limit is 10 requests/second aggregated across machines. `edgar_feed.default_fetch` is exactly this setup and refuses without `EDGAR_IDENTITY`; its proofs run **no network request**, change no feed cadence and claim no shared-IP capacity. Real bounded requests must account for any other SEC client and keep their source/receipt evidence. No bulk download, subscription, identity-store read or broker credential is part of this row.

## Proof and limits

`uv run --frozen pytest tests/proofs/test_edgartools.py` parses a verbatim upstream 8-K submission with sockets denied, verifies its byte hash, accession/CIK/form and Item 5.02 text, and shows removed acceptance remains `None`. A separate transport-boundary proof uses only a public fixture identity and confirms the native header/cache-disabled setup without contacting SEC. `tests/proofs/test_edgar_atom.py` adds the poller proofs over verbatim-excerpt real Atom entries from the pin's own VCR cassette: feed order and identity, acceptance-versus-receipt presence (never knowable before receipt), strict refusal of error pages and inconsistent entries, archived-byte hashing, the same 8-K parse through `parse_submission`, and SixK dispatch on an in-memory form edit of the fixture (dispatch/identity/exhibits only; real 6-K SGML cover content is not thereby proved). The fixtures grant no clock, tuning or trading authority. Real SEC retrieval (no declared identity in the proof environment), paired Atom-versus-client feed latency, poll cadence/capacity, broader form coverage and catalyst/ledger integration remain unverified.

Sources, read 2026-11-06: the pinned upstream `edgar/_filings.py`, `edgar/company_reports/current_report.py`, `edgar/sgml/sgml_header.py`, `edgar/settings.py`, `edgar/httpclient.py`, `tests/sgml/test_filing_sgml.py`, `tests/conftest.py`; [installation/identity docs](https://edgartools.readthedocs.io/en/latest/installation/), [configuration](https://edgartools.readthedocs.io/en/latest/configuration/), [SEC access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data). Read 2026-11-09 for PR-F7 at the same pin: `edgar/current_filings.py` (`get_current_url`, `parse_title`, `parse_summary`), `edgar/xmltools.py`, `edgar/company_reports/sixk.py` and `tests/cassettes/test_get_all_current_filings.yaml`; an SEC access-guidance re-read that day was refused HTTP 403 to the undeclared fetcher, so no SEC page content is claimed from it. The vendored fixture/attribution is under `tests/proofs/fixtures/edgar/`.
