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

`sharadar_coverage.py` serially captures full TICKERS/ACTIONS bulk responses, exact-session literal-symbol SEP/SFP slices against the unchanged selected seed, and one-row access/schema observations for optional SF1/DAILY/METRICS. A failed/incomplete price request stops that table; subsequent coverage is unknown. Full pages require the next short/empty page, and repeated page bytes refuse completeness. Response bytes, filters, request/receipt clocks, explicit query `asof`, client/code/seed hashes bind the capture. An existing capture cannot be fetched again. Offline reconstruction verifies all raw hashes before publishing the report and session receipts.

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

Offline: `uv run --frozen pytest tests/proofs/test_sharadar_coverage.py`, then `just ci`. Fixtures cover CSV/ZIPs, complete/failed/repeated slice pages, missing schema, exact prices, recycled symbols, immutable hashes, the direct key registry and credential/header boundaries. They grant no actual entitlement, coverage, historical identity or trading authority.

Commit the implementation first. Check `scripts/keys.sh list`, names/states only. Once **`SHARADAR_API_KEY` shows set**, make exactly one bounded access call through the wrapper; it writes a hash/clock/status receipt and does not claim entitlement:

```sh
scripts/with-keys.sh --strict -k SHARADAR_API_KEY -- uv run --frozen python -m sextant.research.sharadar_client /home/sextant/sextant-data/sharadar-42/access-probe.json
```

After a successful access check, measure the actual subscription and keep raw data outside git. The requested asof is a query cutoff, never proof of a historical vendor vintage:

```sh
scripts/with-keys.sh --strict -k SHARADAR_API_KEY -- uv run --frozen python -m sextant.research.sharadar_coverage capture /path/to/extreme-gainer-grand-package.zip /home/sextant/sextant-data/sharadar-42/capture /home/sextant/sextant-data/sharadar-42/report --asof 2026-11-06T16:00:00+00:00
uv run --frozen python -m sextant.research.sharadar_coverage report /path/to/extreme-gainer-grand-package.zip /home/sextant/sextant-data/sharadar-42/capture /home/sextant/sextant-data/sharadar-42/report
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

Offline reconstruction was idempotent. Independent checks matched all **1,887 raw-response hashes**, **1,438 report-artifact hashes** and **1,436 per-session event hashes**. All 1,172 original selected events survive. Coverage remains `survivor_only: true`; the independent fixed delisted sample, identity/asof and replacement-backtest acceptance, historical float, controls/onset and cumulative ledger binding remain unavailable/NOT_RUN. The proof suite has 21 offline cases; the 21 coverage plus two key proofs passed together, and `just ci` passed 132 tests after metadata/main integration.

Lesson: establish the credential's issuing service before selecting a client/store name. Access/schema observations and exact-date prices have distinct denominators; malformed/denied queries are unknown, and present-day metadata cannot supply historical knowledge. Keep those boundaries in fixtures before a keyed run.

## Row 4 dated-master acceptance, first run (#42)

**Survivor-only stays true.** ADR-0002 §6's universe tests ran over #107's raw Sharadar capture.
The ten exits and the `asof` bars pass, and BBBY is corrected to the measured 2 issuers. **The
pre-registered independent sample fails, 27 of 40 against 38.** The replacement backtest has not
run. [Receipt](2026-11-06-pit-acceptance-receipt.json),
[sample registration](2026-11-06-delisted-sample-registration.json).

- **Tests:** ADR-0013 (Universe) carrying northstar-trading@`8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`:`docs/adr/0002-data-api-stack.md:96`.
- **Dated identities:** the share-class interval core of the same pin's `data/sharadar.py`
  (lines 62–101, 470–956) with its 71 pure-interval tests, in `src/sextant/data/sharadar_master.py`.
- **Inputs:** #107's complete `TICKERS` (full) and `ACTIONS` (`years=10`) bulks, verified against
  their receipt hashes. `ACTIONS` starts 2016-09-30, which is the coverage floor upstream's
  `_bulk_actions_start` rule sets. Scope `SEP+SFP`, window 2016-01-01 to 2026-11-05.

| ADR-0002 §6 test | Result |
|---|---|
| All ten probed exits | **PASS, 10/10.** Each issuer chosen by 08u.1's own probe `asof` ends on an explicit exit action: LNKD, CELG, TWTR (`acquisitioncash`), XLNX (`acquisitionstock`), YHOO, ATVI, FRC (`delisted`), LK (`regulatorydelisting`), SIVB, BBBY (`bankruptcyliquidation`). LNKD's probe day, 2016-06-15, precedes the 10-year floor: only a probe before the ACTIONS coverage floor may fall back to a sole holder of the name, and an empty dated lookup inside coverage stays uncovered. |
| ≥95% of a fixed independent random delisted sample | **FAIL, 27/40 (38 needed).** The sample was pre-registered on #42 before any check: SEC EDGAR Form 25-NSE common-stock filings 2016-10 to 2025-12, 8,327 unique filings, seed 20261106, N=40, registration sha256 `ba970d72…`. The match criterion was amended there before any check (CIK match; explicit exit on or before filing + 10 days, 12d2-2(d)(1); the credited security must belong to the sampled common class, so a preferred or unknown Sharadar class never credits a common-stock filing). The 13 misses: 5 have no Sharadar CIK match; 4 rows are excluded by the carried code's own fail-closed rules, carrying 5 named reasons (4 `tickerchange_target_mismatch` on EDR1, WR1, WOOF1 and AT2; 1 `ended_before_actions_coverage` on VCAI); 4 (TLF, CCUR, SEII, GIGAQ) left the exchange through an `exchangeto OTC` move 57 days to 6 months before the filing, with no exit action by filing + 10 days. Whether a venue exit counts is the lead's call, and it needs a new draw, not a rescore. |
| Recycled ticker: distinct master ids | `META` on 2021-12-01 is the Roundhill ETF (`sharadar:635599`, now `METV`) and `FB` is Meta (`sharadar:194817`): **distinct.** `BBBY` has **2** master issuers, Bed Bath & Beyond (`197799`, to 2023-05-02) and Overstock/Beyond (`195902`, 2025-08-29 to 2026-08-16, then `NXH`). The ADR expects 3. Sharadar's dated `namechange` rows make Beyond Inc., the 2025 "Bed Bath & Beyond Inc." and Neighborhood Intelligence one permaticker. **The source decides (lead, #42): 2 measured, the ADR's "3" UNVERIFIED,** amended in ADR-0013. |
| Recycled ticker: `asof` bars match the master's issuer | **PASS, 4/4.** Alpaca SIP daily RAW with `asof` equals Sharadar's unadjusted close for the master's issuer, to the cent: META and FB on 2021-12-01, BBBY on 2022-06-01 and 2025-10-01. |
| Replacement backtest | **NOT_RUN.** |
| Float history | **UNVERIFIED.** #107 found no float field in the subscription's schemas. |

**Members manifest.** 24,503 dated intervals, sha256 `e8394fb2…`, are outside git under
`~/sextant-data/pit-42/`. The manifest is identical across three builds and loads in row 11's
`manifest_universe` at its hash. It omits the venue, so OTC tail days (SIVBQ on 2023-03-28) are
members, and a consumer that ranks listed names must filter them. Exclusions are named per
security, with 10,273 `ended_before_actions_coverage` out of 31,079 inputs.

**Run** (run-3, with `--sample <registration.json>`): `scripts/with-keys.sh --strict -k ALPACA_PAPER_1_API_KEY:APCA_API_KEY_ID -k ALPACA_PAPER_1_SECRET_KEY:APCA_API_SECRET_KEY -k SHARADAR_API_KEY -- uv run --frozen python -m sextant.research.pit_acceptance <capture> <out> --end 2026-11-05 --asof-prices`.
That is 4 Alpaca historical bar requests and 4 Sharadar price reads, with no stream, order or account call.

**Reader swaps, zero difference (#133).** The capture is now read by #107's own `sharadar_coverage`
reader, and the sample's quarters, `form.idx` reader and SEC client are EdgarTools'. Rerun offline
over the same capture and registration, both readers give byte-identical output: acceptance
sha256 `1636a3c8…` and the members manifest `e8394fb2…`, as run-3 recorded. Only the 37 indexes'
hashes were archived, not their bytes, so a re-draw needs the owner's `EDGAR_IDENTITY` contact.
The offline proofs pin the replaced code's output.
