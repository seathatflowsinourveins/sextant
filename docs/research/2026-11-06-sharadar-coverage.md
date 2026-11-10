# Sharadar direct-service coverage, row 4

[#42](https://github.com/seathatflowsinourveins/sextant-archive/issues/42), research only. The owner's key comes from `sharadar.com/account`. [Sharadar's own API guide](https://sharadar.com/llms.txt), [authentication](https://sharadar.com/docs/auth) and [query documentation](https://sharadar.com/docs/getting-started), read **2026-11-06**, identify that key with **`https://api.sharadar.com/v1.0`**. The guide explicitly excludes Nasdaq Data Link and its libraries for this key, and documents the **`x-api-key` header**. No key is put in a URL.

The store name is **`SHARADAR_API_KEY`**, a house convention rather than an official SDK environment variable. It is registered in `scripts/keys.sh`; there is no Nasdaq alias. No official direct-service Python SDK was found in the vendor's API index, authentication, querying or bulk documentation, or the linked client search. The matching interface is its documented REST API. The transport is the existing pinned northstar implementation below, using pinned `requests`; no wrapper is presented as an official Sharadar SDK. Access still does not establish transferred rights or PIT acceptance.

## Sources and implementation

- psf/requests@v2.34.2 `6e83187b8feb273ed4c6cdab5efd8d54901dfab3`, `src/requests/sessions.py`, pinned in pyproject and lock. Its `Session.get` is the HTTP client; no HTTP stack is rewritten.
- northstar-trading@`8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`, `src/northstar_trading/data/sharadar.py`: `environment_key`, `parse_csv`, `parse_bulk`, `SharadarSource._response`, `fetch_bulk`, `fetch_slice`, credential-echo refusal and receipt-only availability. This is the minimal direct-service carry, without catalysts/catalog/universe dependencies. Immutable publication reuses the already-carried `candidate_history.py` helper from `alpaca_history.py:publish_once` at that pin.
- [Sharadar bulk](https://sharadar.com/docs/bulk), [tickers](https://sharadar.com/docs/tickers), [actions](https://sharadar.com/docs/actions) and [API guide](https://sharadar.com/llms.txt), read 2026-11-06: full tables use bulk ZIPs; TICKERS is a full snapshot, ACTIONS uses the owned ten-year window. Bounded ticker slices use explicit dates and offset/limit, never the default one-year window. Modern names and legacy SEP/SFP/SF1 codes identify the same tables.
- northstar-trading@`80535ddb8a0906dcdb9a98af196de1e8a8aea1ea`, `docs/research/2026-10-21-alpaca-delisted-coverage.md` and its raw JSON: original probe targets LNKD, YHOO, CELG, LK, TWTR, SIVB, BBBY, FRC, ATVI, XLNX. Those are distinct from independent random delisting acceptance.
- Python 3.13 [CSV](https://docs.python.org/3.13/library/csv.html), [ZIP](https://docs.python.org/3.13/library/zipfile.html), [JSON](https://docs.python.org/3.13/library/json.html) and [hashlib](https://docs.python.org/3.13/library/hashlib.html), read 2026-11-06: exact field strings, bounded ZIP reads without extraction, immutable JSON receipts and SHA-256.

`sharadar_client.py` carries the direct transport, CSV/ZIP parsing and a single-request access probe. It disables ambient proxy/netrc authentication, sends `x-api-key` only to the fixed Sharadar origin, refuses unsafe bulk redirects and follows a documented HTTPS download without the account header. Raw/ZIP-member/URL-encoded/JSON-escaped credential echoes refuse archival. Headers, exception text, download links and request objects are never persisted or printed.

`sharadar_coverage.py` serially captures full TICKERS/ACTIONS bulk responses, exact-session literal-symbol SEP/SFP slices against the unchanged selected seed, and one-row access/schema observations for optional SF1/DAILY/METRICS. A failed/incomplete price request stops that table; subsequent coverage is unknown. Full pages require the next short/empty page, and repeated page bytes refuse completeness. Response bytes, filters, request/receipt clocks, explicit query `asof`, client/code/seed hashes bind the capture. An existing capture cannot be fetched again. Offline reconstruction verifies all raw hashes before publishing the report and session receipts. `sharadar_coverage.py` is the finished one-off coverage study: the runner and its 21-case offline driver proof live on the tagged research branch `research/sharadar-coverage` at `sharadar-coverage-2026-11-09`; gate keeps the reusable `sharadar_client.py`, this receipt and an archive proof that reads the recorded result.

CSV prices and blank fields remain exact strings; raw seed fields and original dated tickers survive. A null/blank price is not zero. Related/recycled master candidates never become accepted identity or rewrite an event. Literal price evidence does not establish issuer identity. Economic action/price/update dates do not create historical knowledge clocks, and the current snapshot is not a historical vendor vintage. `survivor_only: true`, `pit_verified: false`, historical knowledge null and inference ineligibility remain unconditional.

| Operational value | Source | Status |
|---|---|---|
| 10 s connect / 60 s read, 256 MiB raw/decoded bound | Pinned northstar `_response`, `_MAX_BODY` | Uncalibrated transport starting values, not trading parameters. |
| 10,000 rows / 10,000 pages for bounded slices | Official query limit; pinned `fetch_slice` defaults | Operational bounds only; reaching a page bound stays incomplete. Full tables use bulk. |
| TICKERS `years=full`, ACTIONS `years=10` | Official API guide and pinned `fetch_bulk` | Snapshot/owned-history requests, never an expanded purchase. |
| One-row probe on documented ticker TWO | Official API guide's example ticker and query `limit` | Access/schema observation only, not entitlement or coverage acceptance. |
| At least 95% of a frozen independent delisted sample | ADR-0013, inherited data-stack ADR §6 | Acceptance rule; no sample/denominator is invented. |

The [agreed #73 seam](https://github.com/seathatflowsinourveins/sextant-archive/issues/73#issuecomment-6689718543) leaves all universe types with row 11. This report supplies raw evidence, hashes and a `universe_manifest.json` with **`members: []`**, never listing intervals inferred from first/last prices. Ten-exit identity acceptance, the independent sample, recycled-ticker/asof replay and the replacement backtest stay NOT_RUN. Float history, rights, ordinary controls, onset clocks and cumulative TrialLog binding remain unverified/unavailable. Outstanding shares are not public float. This audit starts zero strategy trials without asserting a zero historical count.

## Verification and use

Offline in gate: `uv run --frozen pytest tests/proofs/test_sharadar_client.py tests/proofs/test_sharadar_coverage_archive.py`, then `just ci`. The coverage driver proof (`tests/proofs/test_sharadar_coverage.py`, 21 cases) and the runner are on the tagged research branch `research/sharadar-coverage` at `sharadar-coverage-2026-11-09`; run them from that branch's tree. Fixtures cover CSV/ZIPs, complete/failed/repeated slice pages, missing schema, exact prices, recycled symbols, immutable hashes, the direct key registry and credential/header boundaries. They grant no actual entitlement, coverage, historical identity or trading authority.

Commit the implementation first. Check `scripts/keys.sh list`, names/states only. Once **`SHARADAR_API_KEY` shows set**, make exactly one bounded access call through the wrapper; it writes a hash/clock/status receipt and does not claim entitlement:

```sh
scripts/with-keys.sh --strict -k SHARADAR_API_KEY -- uv run --frozen python -m sextant.research.sharadar_client /home/sextant/sextant-data/sharadar-42/access-probe.json
```

After a successful access check, measure the actual subscription and keep raw data outside git. The requested asof is a query cutoff, never proof of a historical vendor vintage. The capture and report commands run on the research branch, from that tree:

```sh
scripts/with-keys.sh --strict -k SHARADAR_API_KEY -- uv run --frozen python -m research.sharadar_coverage capture /path/to/extreme-gainer-grand-package.zip /home/sextant/sextant-data/sharadar-42/capture /home/sextant/sextant-data/sharadar-42/report --asof 2026-11-06T16:00:00+00:00
uv run --frozen python -m research.sharadar_coverage report /path/to/extreme-gainer-grand-package.zip /home/sextant/sextant-data/sharadar-42/capture /home/sextant/sextant-data/sharadar-42/report
```

Only source/fixture/code/hash metadata is committed. Real coverage and response hashes are reported on #42 after execution; purchases come only from those measured gaps and remain the owner's decision. No order, broker request, stream or old-distro write occurs.

## Measured 2026-11-06

The owner stored the direct key; `keys.sh list` showed set before use. One wrapped, bounded TICKERS access call returned HTTP 200 at 16:58:35 UTC. Then one authenticated coverage capture ran at implementation `4e06da7a32a616794d27d8a042fdcd98501ebe34`, with query cutoff 16:58:52 UTC and receipt window 16:59:17–17:00:10 UTC. [The committed metadata receipt](2026-11-06-sharadar-coverage-receipt.json) binds the seed, code, raw-response index and report hashes. Raw data remains under `/home/sextant/sextant-data/sharadar-42/`.

| Selected cohort | Events | Literal-symbol daily price observed | Price absent | Unknown / ambiguous |
|---|---:|---:|---:|---:|
| Gainers | 957 | 814 | 143 | 0 / 0 |
| Selected losers | 215 | 132 | 83 | 0 / 0 |

SEP supplied 945 price rows and SFP one. All 940 selected sessions per table completed; the 226 absent observations are **literal-symbol gaps, not confirmed vendor-history gaps**. Of these, 224 have master candidates; the two without candidates are SREMF (2025-09-16) and EVTV (2026-01-12), both seed gainers. Dated identity/alias resolution comes before any purchase question.

The full TICKERS snapshot contains 74,543 rows across tables; the stock-price subset has 21,033 unique permatickers, including 14,713 marked delisted, and the fund subset 10,046, including 3,663 marked delisted. These are current reference observations, not accepted listing intervals. ACTIONS yielded 358,920 rows. All ten original probe names have master/action candidates, but several have multiple candidate identities; no ten-exit acceptance passes. SF1/DAILY/METRICS schema probes completed; none of the seven observed schemas has a float-named field, and shares outstanding still supplies no PIT public-float history. A header/schema response alone does not establish paid history or transferred rights.

Offline reconstruction was idempotent. Independent checks matched all **1,887 raw-response hashes**, **1,438 report-artifact hashes** and **1,436 per-session event hashes**. All 1,172 original selected events survive. Coverage remains `survivor_only: true`; the independent fixed delisted sample, identity/asof and replacement-backtest acceptance, historical float, controls/onset and cumulative ledger binding remain unavailable/NOT_RUN. The study's proof suite has 21 offline cases; the 21 coverage plus two key proofs passed together at the measured commit, and `just ci` passed 132 tests after metadata/main integration. Gate now runs the seven transport/key proofs in `test_sharadar_client.py` and the three archive proofs that read this receipt.

Lesson: establish the credential's issuing service before selecting a client/store name. Access/schema observations and exact-date prices have distinct denominators; malformed/denied queries are unknown, and present-day metadata cannot supply historical knowledge. Keep those boundaries in fixtures before a keyed run.
