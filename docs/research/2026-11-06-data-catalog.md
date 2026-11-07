# Row 11: the replayable catalog and the dated universe

Read and run 2026-11-06 for issue #73, against [ADR-0013](../adr/0013-us-equity-data-stack.md). The pins and the proof are in [the manifest](../manifest.md).

## What was carried, and why this slice
From northstar-trading@`8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`, read from a shallow clone at that commit:

| File | Lines here | Carried as |
|---|---|---|
| `data/alpaca_history.py` | 301 | Verbatim: the clocks, the immutable raw envelope (`land_raw`, `publish_once`), `asof`-dated REST history through alpaca-py |
| `data/catalog.py` | 467 | Carried typed writers, per-partition `asof` proofs and refusal of overlapping or rawless rewrites; one environment variable renamed, the backtest catalog configuration migrated to rc8 and the engine provenance label updated |
| `catalysts/pit.py` | 185 | Verbatim: news, FRED/ALFRED, FINRA short-interest and Reg SHO known-at clocks, on the SEC business-day calendar they share |
| `data/universe.py` | 192 | The dated-membership core: share-class intervals, overlap refusal, `universe_for_date`, the survivor fallback, plus a hash-checked loader for row 4's manifest |

The rc8 configuration migration follows nautechsystems/nautilus_trader@`d53849b216e20f2c122ca01b4dd0da377638b186`, `docs/concepts/backtesting/apis-and-runs.md`: `BacktestDataConfig` takes `catalog=DataCatalogConfig(path=...)` in place of `catalog_path`. PR #87's engine-bump manifest row records this adaptation.

Catalog metadata now records `nautilus_trader: 2.0.0rc8`, the pinned engine that reads and writes it. The carried metadata-equality guard rejects an existing rc7 root and requires re-ingestion into a fresh root. It preserves the existing `metadata.json`; do not relabel an old root in place.

The proofs need nothing else. Left for the rows that use them: `completeness.py` (coverage reports), `fidelity.py` (the catalog→backtest probe), `scanner/security_master.py` (ranking identity), and `sharadar.py` (rights unconfirmed, #29 §5). The EDGAR-partial and asset-snapshot universe providers need northstar's catalysts store and are not carried.

**Universe provenance change from upstream.** Upstream's `report_provenance` lifted `survivor_only` for Sharadar. ADR-0013's decision says to keep it true until acceptance, so here no source lifts it; the PR that brings an acceptance receipt changes this.

**The universe seam with #42** (agreed on #42, and PR #107 matches it): row 11 owns `src/sextant/data/universe.py`; row 4 supplies member manifests and their sha256. A manifest loads only at its recorded hash.

## Proof (design row 11)
`tests/proofs/test_data_catalog.py`, 23 offline cases:
- **Engine provenance:** a fresh catalog records the installed engine version; opening a catalog labelled rc7 requires re-ingestion and preserves its metadata bytes.
- **`asof` replay:** a replay of 2024-11-29 at 10:00 New York reads exactly the 30 minute bars that opened 09:30–09:59, each known by 10:00.
- **A later revision leaves it unchanged:** a revised raw response for the same session lands nowhere (the receipt is immutable), a rewrite of the catalog's bars is refused, and the replay's bytes are identical before and after.
- **Determinism:** two fresh catalogs from the same receipts give byte-identical replays and provenance.
- **Recycled ticker:** `META` resolves to Roundhill's ETF on 2021-12-01 and to Meta Platforms on 2023-01-03. Alpaca's `asof` request returns the dated issuer's bar offline.
- **Clocks:** upstream's worked examples for news (for example 13:00:01 is visible at 13:06:00), FRED vintages, FINRA (publication 16:40 ET) and Reg SHO (18:00 ET). Minute bars are known at open + 1 minute, daily bars at the next New York midnight.
- **`survivor_only`:** every source, Sharadar included, reports `survivor_only: true` and `pit_verified: false`, and a provenance claiming otherwise is refused. Row 10's hygiene gate [H] therefore cannot pass on this universe (upstream `validation/gates.py` fails it on `survivor_only`).

## Acceptance: NOT_RUN
No dated master is accepted, so each of ADR-0013's acceptance items is **NOT_RUN**: all 10 probed exits; at least 95% of a fixed independent random delisted sample; recycled-ticker/`asof` checks on real data (the witnesses above are synthetic); and the first replacement backtest.

## Not run here
No Alpaca request was made: no historical REST call, no stream and no key. The catalog holds only test fixtures. A real ingest is a later, keyed step through `scripts/with-keys.sh`, one command at a time.
