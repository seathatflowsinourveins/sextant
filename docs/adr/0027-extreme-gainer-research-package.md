# ADR-0027: Use the owner's extreme-gainer package only as a research seed

- **Status:** accepted. Harvested; the package supplies starting evidence, not new trading authority.
- **Date:** 2026-11-06
- **Harvested from:** owner's research package, release asset `seed-research-2026-10-09`, SHA-256 prefix `f581ca7f771bf20ef05e`: `GRAND-MANIFEST.md`; `grand-rank-top100/*.md`; `extreme-gainer-research-package/README.md`, `analysis/ERRATA.md`, `datasets/*-METHODS.md`, `analysis/12-advanced-exits-auto-leverage.md`, `analysis/15-what-happens-after.md`, `analysis/19-extended-hours.md`, `analysis/24-incentive-dossiers.md`, `analysis/25-factor-compendium.md`, `harness/research/advance/jev-stage0-analysis-*.md`; `desk-sota-architecture/04-strategy-repo-manifest.md`, `MANIFEST.md`.
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0007-storage-and-data-catalog.md, whole record including amendments.

## Context
The owner says: "the previous research zip in desktop( treat them as only a start point, sotarepos upstream are the only source of truth" (BRIEF-F.md, 2026-11-06).
The package contains a multi-year collection of selected movers, source-linked dossiers, falsifications, historical ranker output and Jev shadow results. Its scope and measured findings are carried in the [evidence note](../research/2026-11-06-extreme-gainer-package.md).

## Decision
- Retain the package as an owner-supplied research seed. Every implementation still follows a maintained pinned upstream or cited method; a package blueprint, prompt or repository label grants no adoption. [O, S]
- Use event identities, citations, missingness, corrections and negative findings to seed research cards and replay cases. Keep weekly leaders (2021–2023) distinct from daily leader collections (2024–September 2026). Neither is all stocks each day. [D]
- Preserve approximate rows, artifacts, ticker reuse, delistings and missing fields explicitly. Loser controls are selected collapses; they do not supply ordinary non-mover controls. [D]
- Treat the grand ranker's AUC and forward returns as selected-event descriptions. They establish neither pre-move whole-market ranking nor an after-cost entry or exit edge. Fitted weights remain an unadopted proposal. [R]
- Preserve Jev Stage-0's **NOT CLEARED (2/4 bars)** and advisory-only verdict. The old `jev-1.13.0` run is historical evidence; Sextant's paired sim scope and current contract remain in [ADR-0017](0017-jev-judgments.md). [J]
- Exit ladders, trails, turnover gates, regime bands and leverage numbers in chapter 12 are design parameters; it reports no backtests. They do not replace Sextant's harvested policy or calibrate its thresholds. [X]
- Re-derive prices, corporate actions, dated membership, float, feature availability and costs from upstream data before predictive replay. Use the existing one-catalog practice; copy no dataset or package code in this harvest. [D, S]

## Evidence
| Claim | Source (within the hashed package unless a repo pin is given) | Basis |
|---|---|---|
| O: start point only | BRIEF-F.md, owner's quoted ruling, 2026-11-06 | Owner instruction; the package is not an upstream. |
| D: collection and selection | `extreme-gainer-research-package/README.md`; `datasets/LOSERS-METHODS.md`, `SURVIVOR-BIAS.md`; `analysis/ERRATA.md` E12/E90/E168/E173/E183/E212/E272 | 957 gainers, 215 selected losers; weekly/daily coverage and audit discrepancies in the evidence note. |
| R: ranker limits | `grand-rank-top100/GRAND-RANK-LAYER.md`, `grand-rank-backtest.md`, `grand-rank-finetune.md` | 1,037 scored; test AUC 0.986/0.989; top-100 T+20 −6.22% on 55 observations; gainer-only backfill and no non-mover universe. |
| J: failed shadow admission | `extreme-gainer-research-package/harness/research/advance/lane-C-jev-replay.md`, final addendum; `jev-stage0-analysis-20261002T001441Z.md` | 1,172 events; ECE 0.275; fade ratio 1.80× below 2.0×; no promotion. |
| X: exits and leverage | `extreme-gainer-research-package/analysis/12-advanced-exits-auto-leverage.md`, Status and closing paragraph | Explicit design hypotheses and hypothetical arithmetic; no backtests. |
| S: upstream storage practice | northstar-trading@8256c16c31dc:docs/adr/0007-storage-and-data-catalog.md, Decision 1; amendments 2026-11-01/11-05 | Nautilus `ParquetDataCatalog`, one writer, immutable receipts; synthetic capture evidence does not establish operational completeness. |

## Changes for Sextant

- Owner addition on #130 (2026-11-06): size historical trades and event-ordered quotes for seed/control onset windows before any pull, using their actual minute `n` and measured quote/trade calibration. Record rows, bytes, calls against 200/min, wall/stop times and the dated entitlement check. Missing windows, controls or `n` keep the pull held. Minute bars do not establish first-second entry or B's protection sequence; tick replay is separate evidence from installed broker behavior.

Owner ruling for #130, verbatim via #58 (2026-11-06): "that zip is only a start point, we need to using sota referneces, repos, backtest platfrom, stratgies templates, naut native features etc as only sources of truth".

- #130's primary references are River Page-Hinkley 0.26.1 at `64285b9dd6c606804753235fe992bcf25b9856ee`, Adams–MacKay arXiv:0710.3742v1, and Zarattini–Barbon–Aziz DOI 10.2139/ssrn.4729284's published Stocks in Play opening relative-volume screen. Label each adaptation; K2/K3 are house incumbent E0 comparisons, not truth. Record compute admission on each card actually run.
- The frozen follow-ons are ADWIN, oracle-checked Lee–Mykland, symmetric CUSUM once an executable reference exists, and OFI/VPIN once their inputs exist. Missing sources/inputs stay unavailable; no tuning or invented replacements.
- The zip supplies event identities/dates only; re-derive prices, actions, float and timing from historical Alpaca/Sharadar evidence, excluding zip weights/exit ladders. Use native BacktestNode/BacktestEngine over the one ParquetDataCatalog, native VWAP/ATR where applicable, and an `upstream checked:` or `none exists:` line in each arm. #129's landed syntheses govern native-feature choices. Historical REST only, with hashed reserve/outcome hand-offs through #102 before runs; this ruling grants no stream, order, admission or promotion.

The owner admits this archive as a starting source only. Correct the design's claim that no multi-year list exists, while retaining the missing complete PIT ranking universe; exact replacements are in the handoff's `DESIGN-CHANGES.md`.
Newest owner rulings, verbatim from COMMON.md (2026-11-05/06):
- "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"
- "FOCUING ON US EQUALITY, OPTION,STOCKS ETC, AND ALL THE LANES PREVIOSU STATED, PHILOSOPY PREVIOUS STATED, JEV TRADE RELATED RPEOS ETC ,RESEARCH LANE ,AUTO LEVERAGE, PROTFOLIO MANGEMENT AND BEYOND"
- "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"
- "we need to using full sota harness framework.dsh that is fully enhanced with openviking etc"

## Code and config to carry
**Code/config: none.** Candidate seed files below are pointers only, measured with standard-library CSV parsing, `stat` and line counts; no import occurs. Paths are under `extreme-gainer-research-package/datasets/` in the hashed archive unless stated otherwise.
| Seed pointers | Records; bytes; lines |
|---|---|
| `extreme-gainers-{2021,2022,2023,2024,2025-2026}.csv` | 52/52/51/279/523; 34,838/37,082/33,890/182,802/222,795; 53/53/52/280/524 |
| `extreme-losers-2021-2026.csv` | 215; 91,616; 216 |
| `deep-dossiers.csv`; `incentive-dossiers.csv` | 957/957; 1,416,839/771,244; 958/958 |
| `discrepancy-resolution.csv`; `alias-map.csv`; `concreteness-tags.csv` | 26/265/957; 12,477/74,124/68,269; 27/266/958 |
| `forward-returns-2021-2026.csv`; `forward-returns-recovered-supplement.csv` | 957/77; 152,366/7,592; 958/78; historical comparisons only |
| `extended-hours.csv`; `halt-flags.csv`; `halt-reopen-validation.csv` | 100/86/19; 54,934/18,946/11,094; 101/87/20 |
| `13d-preceded-events.csv`; `form4-preceded-events.csv`; `rs-preceded-events.csv` | 12/234/90; 3,104/16,300/13,444; 13/235/91 |
| `market-regime-map.csv`; `outside-factor-calendar.csv`; `outside-factor-tags.csv` | 957/103/1,449; 82,477/39,056/235,862; 958/104/1,450; context, not PIT features |
| `grand-rank-top100/grand-rank-top100.csv` (archive root) | 100; 20,110; 101; comparison artifact only |
Prices/returns, stable dated identifiers, delisted membership, true float/turnover, as-of catalysts, all-stock non-mover controls and execution costs must be re-derived from upstream data [D, S]. Do not import fitted weights, prompts, package scripts, stale watchlists or the architecture's old pins as policy.

## Disagreements
- README reports 416 recent trading dates; the frozen CSV has 417 (241 in 2025, 176 in 2026). Grand-layer prose also mixes 959 with the corrected 957 gainers and inconsistent factor counts. Preserve the discrepancies; see the evidence note [D, R].
- Chapter 24/25's provisional Form 4 setup is superseded by the completed negative Form 4 study. Chapter 73's NOT-RUN header is superseded by the final Lane C addendum and analysis files [J; `analysis/FORM4-METHODS.md`].
- Desk GREEN labels and chapter-12 prescriptions do not establish costs, fills or upstream adoption. Its old pins and historical risk numbers do not supersede newer Sextant records [X; `desk-sota-architecture/04-strategy-repo-manifest.md`, G-06].

## Revisit when
- Corrected closes, identifiers, missing-data outcomes or an original sample manifest arrives: the research owner reconciles the affected claims and amends this record (ERRATA E12/E92/E168).
- True intraday/VWAP/halt-print data and recorded paper fills arrive: the research owner tests the named design hypotheses, retaining the negative results (chapter 12 calibration questions; desk G-06).
- A new model or reproducible judgment-calibration result arrives: the Jev owner applies ADR-0017's paired evidence path; the archived Stage-0 verdict grants no authority.
