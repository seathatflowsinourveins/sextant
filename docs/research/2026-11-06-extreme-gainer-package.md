# Extreme-gainer package: selected history, findings and limits

Read 2026-11-06. Owner ruling (BRIEF-F.md): "the previous research zip in desktop( treat them as only a start point, sotarepos upstream are the only source of truth". This is a harvest of reported findings, not a new backtest or an adoption of its framework. See [ADR-0027](../adr/0027-extreme-gainer-research-package.md).
Archive: owner's research package, release asset `seed-research-2026-10-09` on this repo; SHA-256 `f581ca7f771bf20ef05e212ce88aaaacda7325c640500d63926b23a0516d0577`, verified with `sha256sum /mnt/wsl/research-data/sextant-inbox/extreme-gainer-grand-package.zip`.
`P/` below means `extreme-gainer-research-package/` inside that archive; `G/` means `grand-rank-top100/`. `GRAND-MANIFEST.md` records grand revision 11, research wave 93 and desk revision 260. These are historical inventories, not upstream verification receipts.

## Event selection and trading-day coverage

The five `P/datasets/extreme-gainers-*.csv` files hold **957 events**. They are retrospectively chosen leaders, not every candidate or every stock-day. Early years select one weekly leader; later years collect daily leaders plus additional movers, with verification gaps. The nominal ≥50% threshold is not enforced: ERRATA E272 records 170/957 below 50% (floor 4.3%).
The table is a metadata recount, not new performance evidence. Denominators use the archive's observed SPX sessions in `P/harness/research/regime-gate-backtest/lane-A-supplement-spx.csv`, restricted to 2021-01-01–2026-09-22 (1,436 dates; consistent with MARKET-REGIME-METHODS §10).
| Gainer file / event period | Selection | Events | Distinct dates / SPX sessions | Share |
|---|---|---:|---:|---:|
| `2021.csv`: 2021-01-06–12-31 | Weekly leaders, not daily leaders | 52 | 52/252 | 20.6% |
| `2022.csv`: 2022-01-04–12-29 | Weekly leaders, not daily leaders | 52 | 52/251 | 20.7% |
| `2023.csv`: 2023-01-03–12-27 | Weekly leaders; one unresolved week (E173) | 51 | 51/250 | 20.4% |
| `2024.csv`: 2024-01-02–12-31 | Daily leader collection | 279 | 235/252 | 93.3% |
| `2025-2026.csv`, 2025-01-02–12-31 | Daily leader collection, 2025 portion | 281 | 241/250 | 96.4% |
| Same file, 2026-01-02–09-22 | Daily leader collection, 2026 portion | 242 | 176/181 | 97.2% |
Source: README, LLM-FIELD-MANUAL, ERRATA E12/E173/E183/E272 and CSV keys. **Disagreement:** README says 416 recent dates; CSV parsing gives **417**, not 416. Neither count is all stocks each day. The audit below reproduces the table; it does not certify the calendar against an exchange.

```sh
ulimit -v 8388608
uv run --offline --no-project --python 3.13 python - <<'PY'
import csv
from pathlib import Path
p = Path('/mnt/wsl/research-data/sextant-inbox/unpacked/extreme-gainer-research-package')
with (p/'harness/research/regime-gate-backtest/lane-A-supplement-spx.csv').open() as f:
    cal = {r['Date'] for r in csv.DictReader(f) if '2021-01-01' <= r['Date'] <= '2026-09-22'}
for file in sorted((p/'datasets').glob('extreme-gainers-*.csv')):
    with file.open(newline='') as f:
        rows = list(csv.DictReader(f, delimiter=',' if '2025-2026' in file.name else '|'))
    dates = {r['Date'] for r in rows}
    for year in sorted({d[:4] for d in dates}):
        n = sum(d.startswith(year) for d in dates)
        total = sum(d.startswith(year) for d in cal)
        print(file.name, year, sum(r['Date'].startswith(year) for r in rows), n, total, f'{n/total:.1%}')
    assert not dates - cal
PY
```

**Non-movers:** no systematic ordinary/non-mover stock-day cohort is present in the event datasets or grand-rank experiment. `P/datasets/extreme-losers-2021-2026.csv` contains 215 selected declines (2021-01-08–2026-09-03), not non-movers: 52/52/52 weekly news-linked losers in 2021/2022/2023, then 24/26/9 selected 2024/2025/2026 collapses. LOSERS-METHODS describes StockTitan's news filter, current-cap/turnover filters and survivorship caveat; the later 59 are not an exhaustive daily feed. Narrative award-screen false positives in METHODS-B are case studies, not a matched control cohort.

| Other dataset(s), under `P/` unless `G/` | Selection and period; sample size |
|---|---|
| `datasets/forward-returns-2021-2026.csv`, `concreteness-tags.csv`, `market-regime-map.csv` | Joins to all 957 selected gainer keys, Jan 2021–Sep 22 2026; no additional stock universe. |
| `datasets/incentive-dossiers.csv`, `deep-dossiers.csv` | Same 957 keys; deep tiers 12/26/48 events ≥300% researched, 871 below 300% deterministically enriched. Incentive confidence: 111 High / 636 Medium / 210 Low (INCENTIVE-/DEEP-DOSSIER-METHODS). |
| `datasets/alias-map.csv`, `forward-returns-recovered-supplement.csv` | All 265 NO_DATA events in the historical gainer universe; 77 same-company alias recoveries, 188 unrecovered (SURVIVOR-BIAS). |
| `datasets/13d-preceded-events.csv`, `form4-preceded-events.csv` | Screen 234 events: 195 recent ≥100% gainers plus 39 2021–2024 ≥300% gainers; 12 filing rows / 234 event rows. 13D uses filing dates; Form 4 uses transaction dates, not demonstrated availability (13D-/FORM4-METHODS). |
| `datasets/extended-hours.csv` | 100 ≥100% gainers, 50 each from 2025/2026, stratified by catalyst; PHIO researched under its wrong date, clean n=99 if excluded (EXTENDED-HOURS-METHODS). |
| `datasets/premarket-movers-2026-09.csv`, `options-listing-sample.csv` | 25 top-five premarket rows over five verifiable Sep-2026 sessions; 20 sampled ≥100% names originally called 2026, with PHIO re-dated to 2025 (README; ERRATA E6/E12/E126). Options are a check-date snapshot. |
| `datasets/halt-flags.csv`, `halt-reopen-validation.csv` | All 86 ≥300% events, Jan 2021–Sep 2026; 19 worked validation cases. 20 Y / 65 unknown / 1 N; QMMM's Y is weakly sourced (HALTS-METHODS; E160/E163/E312). |
| `datasets/rs-preceded-events.csv` | 90 positive RS-before-event rows from the 957-event search; strict effective date 1–365 days before the spike; 75 EDGAR / 12 dossier-note / 3 unverified. A 244/871 <300% CIK gap remains (chapter 32, final). |
| `datasets/outside-factor-calendar.csv`, `outside-factor-tags.csv` | 103 researched shocks, Jan 27 2021–Feb 24 2026; ±5-trading-day/keyword joins to 957 events yield 1,449 tag rows. Not a prospective or exhaustive shock calendar (OUTSIDE-FACTOR-METHODS). |
| `datasets/fda-calendar-pipeline.csv` | 43 documented rows from a 74-event test: 21 ≥300% biotech catalysts plus seeded 53/265 sample; 2021–Sep 2026. Original tested 74 not preserved as one file; later reconstruction yields 76 (METHODS-A; E92). |
| `datasets/usaspending-award-screen.csv` | Four matches from all 43 Gov=Y gainer events, 2021–Sep 2026; strict preceding federal award within 60 calendar days, inclusive adds LOI/OTA (METHODS-B). |
| `datasets/discrepancy-resolution.csv`; preliminary dossier supplements | 26 flagged price/date cases audited; 4 incentive and 5 deep preliminary rows kept outside the final 957 (E12; INCENTIVE-/DEEP-DOSSIER-METHODS). |
| `G/grand-rank-top100.csv`; Jev results in `harness/research/advance/` | Top 100 selected from scored gainer events; represented dates 2021-04-13–2026-08-19. Jev pilot stratifies 98 gainers + 22 losers; full run uses all 1,172 selected gainers/losers (G layer; Lane C). |

## Carried measurements, including negatives

Unless stated otherwise, these are the package's Jan 2021–September 2026 selected-event results, transcribed rather than rerun. Each row names its source and denominator; horizons have missing observations.
| Finding | Exact reported result and qualification | File / sample |
|---|---|---|
| Price audit | 21 gains corrected, 3 events re-dated, 2 removed; 959→957 events. Morning/intraday/AH prints were mistaken for regular closes; ticker reuse and thin-print artifacts persist as flags. | ERRATA E12; 26 flagged cases, 2021–Sep 2026; not new market-data validation |
| Corrected forward sample | 686 OK + 265 NO_DATA + 6 EVENT_BAR_MISSING = 957; 8 EXCLUDE flags leave 678 rows. Metadata recount: only 671/662/646 contain T+1/T+5/T+20. | `P/analysis/15-what-happens-after.md`; E90/E174; forward CSV |
| Base fade | T+1 −2.75%, T+5 −6.76%, T+20 −14.23%; positive 41.7%/40.8%/35.3%. | Chapter 15, reported analysis set n=678 |
| Concreteness | Concrete n=514: −2.34/−5.27/−11.20%; narrative n=164: −7.42/−10.20/−28.61% at T+1/5/20; 2.6× T+20 fade. | Chapter 15; selected surviving data, not a rule's returns |
| Gain size | <100% n=428 T+20 −6.12%; 100–200% n=154 −29.88%; 200–500% n=72 −35.33%; ≥500% n=24 −65.95%. | Chapter 15; E12's −65.79% is inconsistent; use regenerated table |
| Survivor bias | 77 recoveries T+20 −24.73% vs −13.75% original comparison; observed combined T+20 −14.98%, n=730. 122/265 missing names acquired. | `P/datasets/SURVIVOR-BIAS.md`, pre-correction 959 frame; not the regenerated 957 frame |
| Bias uncertainty | Conservative T+20 −11.15% and worst-case −28.91% are assumptions, not observations; acquisition-at-zero can reverse the sign of bias. | SURVIVOR-BIAS scenarios, n=918 at T+20 |
| Premarket | 47/61 known leaders (77%) already led premarket; 32/33 (97%) with PM catalysts. Magnitude vs final gain ρ=0.04, n=41; median news-to-open 1.83h, n=43. | `P/analysis/19-extended-hours.md`; 100 events, 2025–2026 |
| Premarket limits | Volume 5/100, open gap 8/100, AH behavior 8/100. Sep pilot leader→#1 closer 2/5 (40%), correlation ≈0.44, not 4/5; timestamp convention matters. | Chapter 19; EXTENDED-HOURS-METHODS; E6/E126 |
| Options scope | Listed options on 5/20 sampled names (25%); check-date observation, not historical whole-market coverage. PHIO's re-dating invalidates the all-2026 description. | `P/datasets/options-listing-sample.csv`; README; DEEP-DOSSIER-METHODS §6; E12 |
| Halt non-result | Confirmed incidence 7/48 (14.6%), 6/26 (23.1%), 7/12 (58.3%); lower bounds. Fade cells n=2–5 yield no reliable directional edge; 0/19 verified halt/reopen price pairs. | HALTS-METHODS; E254/E312; validation CSV |
| 13D falsification | 6/234 (2.6%) at 30 days; 15/234 (6.4%) at 60; 21/234 (9.0%) at 90. Seven of 12 filings exit notices; true 13D is sponsor plumbing. | `P/datasets/13D-METHODS.md`; E11 |
| Form 4 falsification | 449 documents; 5/234 (2.1%) at 30 days, 9/234 (3.8%) at 60; median lead 43 days; zero 30-day buys in the 38-event ≥500% tier. | `P/analysis/FORM4-METHODS.md`; supersedes chapter 24/25's provisional setup |
| Calendar/award negatives | FDA strict 11/74 (14.9%), inclusive 32/74 (43.2%), median lead 63d; 66 trial-readout losers lose 26%–91.5%. Awards strict 2/43 (4.7%), inclusive 4/43 (9.3%); both strict hits lack obligated dollars. | `P/harness/research/next-pipelines/lane-a/METHODS-A.md`, `lane-b/METHODS-B.md`; timing is not direction |
| Regime/context | GREEN 614/957 (64.2%) vs 726/1,436 days (50.6%), 1.27×; 43.5% on down/flat SPX days. Macro 654/957 (68.3%) vs 984/1,436 (68.5%), lift 1.00×; rebalance 17.3% vs 17.4%, lift 1.00×. | `P/analysis/21-market-factor-regimes.md`; same-day closes are not pre-open features |
| Outside/incentive limits | High/Medium attribution 26/957 (2.7%); 975 Low tags are coincidence, never features. Exogenous 380 + M&A 169 + Unknown 167 underpin the chapter's "~75%" not systematically pre-positionable claim. | OUTSIDE-FACTOR-METHODS; `P/analysis/24-incentive-dossiers.md`, `25-factor-compendium.md`; label assessment, not measured trading odds |
| RS correction | ≥300% events: 24/86 (27.9%), not "~half"; median lead 94.5d, n=24. Separate Jan-2024–Jan-2025 RS cohort: 25/46 (54.3%) spike ≥100% in ~370d, 12/58 lack prices. | `P/analysis/32-reverse-splits.md`; latest full-universe positives 90/957 (9.4%) |
| RS follow-through | Final full-universe T+20: RS-preceded −38.0% (n=73), other −11.9% (n=579), ~3.2× fade. Earlier −37.6%/−13.3% figures describe a smaller cut and persist in the chapter's implications. | Chapter 32 §32.5, final 90-positive frame; other events are not proven RS-free |
| Volume/float limits | E212: numeric turnover 111/957 and volume multiple 329/957; 69%/91% approximate. E168: two turnover constructions disagree on 38/71 overlapping rows; often outstanding shares, not public float. | ERRATA E168/E212; 2021–Sep 2026; no canonical validated turnover feature |
| Exits/leverage | **No backtests** in chapter 12; ladders, ATR trails, time stops, Kelly, CPPI and leverage thresholds are design parameters, worked examples hypothetical/arithmetic. | `P/analysis/12-advanced-exits-auto-leverage.md`, Status, B.1/B.7/B.8; no measured strategy sample |

Taxonomy caveats: the frozen 15-category taxonomy mixes rumor/definitive M&A; ERRATA E304 specifies a 16th category without rewriting the files, and E310 withdraws a mislabeled M&A interaction. E311 says squeeze/meme is a price-action label, not verified SI/borrow/gamma mechanics. Dossiers and class counts are annotation seeds, not primary-source or PIT guarantees.

## What the historical ranker actually tests

`G/GRAND-RANK-LAYER.md`: 1,037 scored events, 135 skipped without Tiingo bars. Its 959-gainer input wording conflicts with corrected 957; 957+215=1,172 is the frozen input frame. `grand-rank-finetune.md` trains on 512 pre-2025 events (378 winners/134 losers), tests on 525 from 2025 onward (491/34), using 13 varying factors and balanced L2 logistic regression on `is_winner`.
Reported AUCs: train prior **0.972**, fitted **0.981**; test prior **0.986**, fitted **0.989**, described as "within noise" by the package. Its recommendation is KEEP priors; fitted weights are a proposal. No noise estimate or independent predictive replication is supplied here.
`G/grand-rank-backtest.md`, T+1/5/20 respectively: top-100 forward observations **55/55/55**, medians **−0.28/−3.95/−6.22%**, positive rates **49.1/47.3/38.2%**; all-scored-gainer baseline n=**653/642/627**, medians **−2.53/−5.93/−12.76%**, positive rates **42.1/41.6/35.9%**. These are post-spike close returns from the Yahoo-derived overlay, not at-open fill P&L.
Score deciles are non-monotonic: T+20 D1 −5.86% (n=52), D2 −15.51% (43), D7 −1.20% (63), D8 −2.04% (73), D10 −18.55% (70). The top 100's 55 observed outcomes do not establish a positive median return.
**Can AUC/forward results support ranking stocks before they move? No:** `is_winner` distinguishes retrospectively selected gainers from selected losers without ordinary stock-day negatives, while the forward test ranks already-selected gainers and measures what happens after their spike closes. The package also discloses gainer-only RS/13D backfill, absent delisted bars and constant/artifact features; calling this "at-open" does not validate point-in-time availability or pre-ignition whole-market recall.
Factor audit caveats in `grand-rank-finetune.md`: rvol 1,036/1,037 at 0, one missing-baseline artifact; insider_13d one scored hit; rs_recency inflated by gainer-only backfill; new_high/gap collinearity r=0.78. GRAND-MANIFEST says 11/31 varying and 20 constant; layer/fine-tune prose also says 13 varying and 19 constant. These counts are not reconciled by this harvest.
The 31 factor columns and seven families (ignition .34, no-sell-pressure .24, incentive .16, squeeze-fuel .14, structural .05, relative .04, options .03) are an archival candidate inventory, not Sextant defaults (`G/grand-rank-top100.csv`; desk strategy manifest S-53). Desk G-06 still lacks true-VWAP/cost evidence and paper fills; GREEN labels do not close it.

## Jev Stage-0: retain the failed verdict

Sources: `P/harness/research/advance/jev-stage0-analysis-20261001T235524Z.md` (pilot), `jev-stage0-analysis-20261002T001441Z.md` (full); `lane-C-jev-replay.md`, final addendum; `P/analysis/73-jev-stage0-shadow-replay.md`, §§2–4.
Historical model `jev-1.13.0`; full run 2,420 calls, 0 errors, completed 2026-10-02 UTC, **1,172 selected events**. Train 2021–2023 n=155; validate 2024-02-16–12-31 n=246; test 2025-02-02–2026-09-23 n=504, embargoes applied; losers used whole for separation. Pilot n=120, J1 splits 18/26/49, is a pipeline check.
| Metric | Pilot | Full run / denominator |
|---|---|---|
| J1 test agreement / D1; AUC | 0.531/0.408; 0.868 | 0.683/0.498; 0.818; n=504, threshold frozen at 0.395 |
| Test ECE | 0.278 | **0.275**, fails ≤0.10; train/validate 0.196/0.259 |
| Fade-AUC vs LightGBM | 0.559 vs 0.500, n=38 | 0.586 vs 0.497, n=369 |
| Concrete / narrative T+20; ratio | −12.76%/−0.10%, n=10/28; 0.01× | −11.89%/−21.36%, n=198/171; **1.80×**, fails ≥2.0× |
| Gainer/loser separation AUC | 0.421, n=120 | **0.361**, n=1,172, below 0.65 bar |
| J6 trap precision / recall; AUC | 0.361/0.361; 0.550 | **0.455/0.467; 0.645**, n=1,172; precision fails 0.50 |
| J5 regime; J7 agreement/AUC; J8 hit | 0.265 (98); 1.000/1.000 (3); 0.500 (2) | 0.328 (957); 0.833/0.912 (24); 0.231 (13) |
Final source verdict: **NOT CLEARED (2/4 bars); advisory-only**. Thresholds were design parameters. Redaction retains potentially identifying prose; the date-shift canary was specified but unimplemented, and calendar-label reconstruction yielded 76 rather than the original 74. No promotion or trading-edge claim follows.

## What Sextant still needs

Use the package's citations, IDs, dossiers and falsifications as seeds; sizes and line counts are in ADR-0027. Re-derive upstream prices/corporate actions, dated share-class membership including delistings/ticker reuse, actual public float and information-availability clocks; retain missing outcomes and build ordinary non-mover controls across every eligible stock-day. Pre-ignition labels, extended-hours/tick coverage, executable fills, costs and the complete cumulative trial family remain **unverified**.
The existing source practice is one Nautilus catalog, one writer and immutable receipts: northstar-trading@8256c16c31dc:docs/adr/0007-storage-and-data-catalog.md, Decision 1 and all amendments; upstream `ParquetDataCatalog`/`StreamingConfig` references are carried there. This harvest changes no data vendor, engine, rank formula, risk limit, Jev contract or options admission, adds no manifest row and executes no package Python.
