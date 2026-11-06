# SEC documents with EdgarTools

EdgarTools supplies archived filing documents and parsers for the catalyst screen that serves ranking/entry. This is **K4 ADOPT-PART**, carried by [ADR-0003](../../docs/adr/0003-ranking-and-feeds.md) and [ADR-0013](../../docs/adr/0013-us-equity-data-stack.md). It adds no poller, broker access, inferred polarity or new primary feed. The existing Atom feed's role and paired-timing requirement remain. A parsed document is not point-in-time availability or trading merit.

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

The pin's configuration page still mentions a `CACHE_DIRECTORY` assignment; its implementation uses `HTTP_MGR`, so that old assignment is not our setup. Retain upstream rate limiting and TLS verification; SEC's published limit is 10 requests/second aggregated across machines. This row runs **no network request or polling**, changes no feed cadence and claims no shared-IP capacity. Future bounded requests must account for any other SEC client and keep their source/receipt evidence. No bulk download, subscription, identity-store read or broker credential is part of this row.

## Proof and limits

`uv run --frozen pytest tests/proofs/test_edgartools.py` parses a verbatim upstream 8-K submission with sockets denied, verifies its byte hash, accession/CIK/form and Item 5.02 text, and shows removed acceptance remains `None`. A separate transport-boundary proof uses only a public fixture identity and confirms the native header/cache-disabled setup without contacting SEC. The fixture grants no clock, tuning or trading authority. Real retrieval, paired feed latency, broader form coverage and catalyst/ledger integration remain unverified.

Sources, read 2026-11-06: the pinned upstream `edgar/_filings.py`, `edgar/company_reports/current_report.py`, `edgar/sgml/sgml_header.py`, `edgar/settings.py`, `edgar/httpclient.py`, `tests/sgml/test_filing_sgml.py`, `tests/conftest.py`; [installation/identity docs](https://edgartools.readthedocs.io/en/latest/installation/), [configuration](https://edgartools.readthedocs.io/en/latest/configuration/), [SEC access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data). The vendored fixture/attribution is under `tests/proofs/fixtures/edgar/`.
