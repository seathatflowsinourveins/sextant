# ADR-0014: Features and regime models remain evidence-led research trials

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0008-features-and-microstructure-signals.md (F), whole, including 2026-11-01 and 2026-11-05 amendments.
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0009-models-regime-anomaly-forecasting.md (M), whole, including 2026-11-01, 2026-11-03 and 2026-11-05 amendments.

## Context

US equity features must be causal on Alpaca SIP trades/L1 NBBO and BOATS L1 overnight. There is no depth or aggressor flag (`NO_AGGRESSOR`).
Computability is not trading merit. The finalized sources admit research trials and retain their missing evidence; neither finalization nor a forecast win authorizes orders.

## Decision

- Use inputs already known at decision time, one factor engine and one implementation per transform. Use requires held-out, delayed, after-cost evidence: WF, CPCV, DSR, PBO and 2x cost stress (F §§Requirements, Pick).
- H1 event OFI is the first L1-proxy trial: held-out 30-second delayed markout at 2x costs; its cited ~65% R² is contemporaneous, not forecast evidence. H2 unsigned arrival intensity precedes Hawkes, which must beat a seasonal baseline. H3 is calibrated Stoikov micro-price from the published method, with the author's unlicensed research notebook as a correctness reference: forecast win over mid and weighted mid, then executable exit value. H4 is completed-bar CLV/range/volume. H5 is low-priority RiskLabAI FFD (BSD-3). All five remain TRIAL, none adopted (F §§Pick, Strongest alternatives).
- Qlib Alpha158 definitions are the canonical baseline; qweave is the one offline Polars challenger, decided by H6 semantic-parity/task-cost evidence. Qlib v0.9.8 and qweave v0.6.2 are research references; `tick` and RiskLabAI remain unadopted compatibility studies, with no supported stable lock artifact established (F §Pin disposition).
- VPIN, BVC and trade-sign toxicity stay dropped; depthless feeds cannot compute walls, pulls, icebergs or queue position. Reject alfa.rs for now, aurumq-rl, aqml, the sauloduttra repositories, tape-and-book, Institutional-Quant-Engine, mlfinlab's public `pass` stubs and outside "ADR-008/009" bundles (F §Pick).
- OFI, CLV, micro-price, realized volatility and intensity are one price/volume family, never an independent catalyst vote. Ten names cannot meet qweave's example `min_cs_count=30`; cross-sectional claims require a permitted PIT panel (F §§Pick, Consequences).
- Historical H1/H3 require a one-symbol-day quote probe confirming SIP ordering of quote `t` and manageable request/storage volume. Clock origin and earliest quote history remain **unverified**. Use the fixed U10: MSFT, GOOGL, V, NVDA, ANET, AVGO, PLTR, MA, AAPL, COST; stress receipt latency and confirm forward. The frozen proposed window is 2026-11-01–2026-12-04; a failed probe leaves it primary. Capture is not claimed. The full-market M1 spread poll remains; its dated volume rationale is about 60.45 GB/day for 500 names (F §§Pick, Confirmation, amendment).
- Preserve F's separate post-2026-12-06 SIP 23/5 cohort and original frozen windows; review dates became evidence events, without retrospective extension. A forecast win authorizes no exit, ranking vote, leverage, purchase, model admission or live promotion; Stage-A hazards/retries remain OFF (F §2026-11-01 amendment).
- No forecasting, LOB or RL model is adopted for trading. Add no ONNX/other serving path until a model passes the gates; then use one export path with parity evidence (M §§Pick, E9).
- Checkpoints obey the owner's "never use the 2025 models" rule: repository and every base must be on/after 2026-01-01 before run, bench or export. Off: Chronos-2 (2025-10-30), Chronos-2-small (2025-12-03), TimesFM 2.5 (2025-09-02), Kronos-small (2025-06-30), Moirai 2.0 (2025-08-06) (M §Pick).
- TimesFM 3.0 is a bounded offline TRIAL-CANDIDATE, created 2026-08-24, revision `43046b85ec22d584a13f8098c2ed39c889e129c2`. Its card declares no base; complete initialization/base-chain provenance remains **unverified** and must satisfy the floor first. Use a frozen series, simple baselines, after-cost value, CPU latency/memory under the host cap and L1/session/horizon fit; no order path. Lead scope confirmation is required before the trial and again before node use (M §§Pick, Consequences, E1/E2/E10).
- Record licences as facts: TimesFM weights `timesfm-non-commercial-license-v1.0`; Moirai CC-BY-NC-4.0. The accepted trigger re-decides adopted-model licences before distribution or third-party operation; provider terms, spend and security still bind (M §§Requirements, Pick, E4).
- TimeGPT/TimeGPT-LH remain NO-FIT for hosted egress, key and spend, requiring an owner decision on a named need. DeepLOB/TransLOB/LOBster/TLOB need missing depth; MASTER is CSI daily, PowerMamba electricity. SimLOB is arXiv 2406.19396, 2505.02139 is LOBench, and LOBster has no TransLOB (M §Pick).
- Classical trials stay offline, outside orders: MAPIE 1.6.0 ACI uses `adapt_conformal_inference` (`update` updates scores; old `update(gamma=…)` example is stale); hmmlearn 0.3.3 `predict_proba` smooths, so issue frozen prefix endpoints, never retrospective whole-sequence posteriors; hmmlearn is a comparator, not a gate. ruptures is offline segmentation only; River 0.26.1 ADWIN tests drift; one PyOD IForest abstention arm compares phase-adjusted thresholds (M §§Pick, 2026-11-01 amendment).
- Computability/trial labels and no-model-adoption have two-family support; MAPIE's offline trial has two-family support. RiskLabAI/`tick`, HMM leakage, ADWIN and PyOD were single-family claims; API/source confirmation is not measured alpha. TimesFM skill, CPU cost and every planned trial outcome remain **unverified** (F/M §§Confidence, Confirmation). The Jev amendment retains no-model-adoption; its paired trials and paper-key rules belong to ADR-0017.

## Evidence

| Claim | Source (repo@sha:path, section or line) | Basis recorded by the source |
|---|---|---|
| Causal L1 trials; dropped signals; one family | northstar-trading@8256c16c31dc:docs/adr/0008-features-and-microstructure-signals.md:17–47 | GPT/Gemini computability convergence; Stoikov published method/notebook; Andersen–Bondarenko critique versus ELO 2016 and Panayides 2019; RiskLabAI BSD-3. |
| Factor and quote references | northstar-trading@8256c16c31dc:docs/adr/0008-features-and-microstructure-signals.md:109–111 | Qlib v0.9.8 `54355232463878d2eebb91fe0ee5fa7fa1f5976c`, loader.py:61–132; qweave v0.6.2 `90b025a5591607a41ec599f801e78f33b59efbd6`, README:114–128 and factor_evaluation:93,109–110; alpaca-py v0.44.0 `cc4cb3b7ba50ae250e621983c2779047fb16bb28`; read 2026-11-01. |
| Freshness and TimesFM provenance | northstar-trading@8256c16c31dc:docs/adr/0009-models-regime-anomaly-forecasting.md:18–38,83 | Owner ruling 2026-10-21; models.lock floor; Hugging Face `createdAt`, card and licence, read 2026-10-29; no complete base-chain proof. |
| No model adopted | northstar-trading@8256c16c31dc:docs/adr/0009-models-regime-anomaly-forecasting.md:34–48 | GPT/Gemini no-adoption agreement; arXiv 2511.18578 reports all long–short Sharpes negative at 20 bp costs on daily data across 94 countries (single-family citation). |
| Classical APIs and exact references | northstar-trading@8256c16c31dc:docs/adr/0009-models-regime-anomaly-forecasting.md:98,137 | MAPIE v1.6.0 `f1cc3d07460b2d7198f557d40d60cd563c51822b`, time_series_regression.py:239–400; hmmlearn 0.3.3 `67c5a95009afe95317923c9fbe75f47962037f48`, base.py:253–286,378–396; River 0.26.1 `64285b9dd6c606804753235fe992bcf25b9856ee`; PyOD v3.6.7 `f0d0967d162ed46150cfa39ca61ffd1e7f78404b`; ruptures v1.1.10 `a3f8c437edf7d54c1a8f90aaa72638363a011765`; source audits 2026-11-01, not installed upgrades. |
| Latest corrections and limits | northstar-trading@8256c16c31dc:docs/adr/0008-features-and-microstructure-signals.md:158–167; northstar-trading@8256c16c31dc:docs/adr/0009-models-regime-anomaly-forecasting.md:203–228 | Blind DeepSeek primary-source audit 2026-11-05: CONFIRM features, CORRECT models; only the false-uniqueness edit was kept. |

upstream checked: the two pinned ADRs above, including their named papers, upstream pins and read dates. External primary sources were not re-read; the cited GPT research files are absent at this allowed pin.

## Changes for Sextant

The following owner directions (2026-11-05/06, harvest COMMON.md) apply verbatim; they enact no feature/model adoption:

- "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"
- "FOCUING ON US EQUALITY, OPTION,STOCKS ETC, AND ALL THE LANES PREVIOSU STATED, PHILOSOPY PREVIOUS STATED, JEV TRADE RELATED RPEOS ETC ,RESEARCH LANE ,AUTO LEVERAGE, PROTFOLIO MANGEMENT AND BEYOND"
- "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"

## Code and config to carry

Pointers only; no code copied or new trial implementation admitted. Each path is in northstar-trading; counts are `git show <full-pin>:<path> | wc -l`.

- `src/northstar_trading/data/ranking.py@8256c16c31dc`: 558 lines; immutable Decimal feature/known-at records.
- `src/northstar_trading/data/ticks.py@8256c16c31dc`: 533 lines; raw SIP quotes/trades, native wranglers, `NO_AGGRESSOR`, synthetic replay receipt time.
- `src/northstar_trading/scanner/scoring.py@8256c16c31dc`: 304 lines; existing Decimal scanner features, distinct from adoption of these research trials.
- `src/northstar_trading/scanner/top100_technical.py@8256c16c31dc`: 462 lines; cited offline OHLCV hypotheses and visibility checks, never execution signals.
- `configs/backtest/scan/README.md@8256c16c31dc`: 166 lines; data-preparation/PIT limitations.
- `configs/backtest/templates/universe.yaml@8256c16c31dc`: 46 lines; explicitly survivorship-biased universe.
- `configs/backtest/sec_c1_universe.yaml@8256c16c31dc`: 30 lines; fixed dated research list, not historical membership.

## Disagreements

- F's older 112,012 historical-quote calls and plan-at-$0 claim are **unverified** by its 2026-11-05 amendment: neither is in the audited cost note, which plans 63,253 fixed calls with 70,000/100,000 attempt ceilings and allows a raised ceiling. No new price or measured count is inferred.
- M's older "one post-floor TSFM" is corrected on 2026-11-05: Datadog/Toto-2.0-313m (2026-04-14), ibm-granite/granite-timeseries-patchtst-fm-r2 (2026-08-07), theforecastingcompany/t0-gamma (2026-10-12) and mistralai/Timestral-209M (2026-10-14) also existed; none is benched in the record. The correction changes no trial/adoption decision.
- M's DeepSeek summary says the TimesFM licence forbids commercial/production use of self-hosted weights and outputs, including any live arm, and says the checkpoint trigger is already met; its final "Proposed and not kept" rejects those three edits, leaving the accepted distribution/third-party trigger and E3 text in force. Preserve that conflict; do not enact the summary's proposals.
- M records the literal 2026-10-28 "local models only for RAG/memory roles" directive alongside a numerical offline trial. Its accepted lead-confirmation-before-trial-and-node condition stands; the 2026-11-01 stronger owner-only rewording is explicitly an unadopted proposal. F/M's other drafter rewrites likewise remain proposals.

## Revisit when

- F E0–E6/E9/E10: quote clock/ordering, manageable pages/bytes/coverage and supported history boundary; sealed H1–H5 delayed/costed results; H6 parity/task-cost result; permitted PIT coverage; or measured clock/delay/cost invalidation. Owners: research lead, with data lead for quotes/PIT.
- F E7/E8: compatible classifier validation or a clearly unsigned proxy beating volume/volatility at 2x costs; an evidenced source/session change with a separately frozen cohort. alfa.rs reopens only for an H6 qweave gap. Owners: research/data leads; execution lead owns any exit use.
- M E1–E3/E7–E11: official complete base chain; eligible frozen forecast/after-cost/baseline/CPU/forward report; an entirely post-floor checkpoint, then bounded comparison before trial; MAPIE correctness/coverage/width/utility; separately counted causal HMM, phase-adjusted ADWIN and IForest evidence; gate-qualified serving need plus native/export parity, latency, RSS and decision equivalence; scope confirmation; or changed pinned upstream contracts. Owners: research/execution leads, owner/lead for scope.
- M E4–E6: distribution/third-party operation; an owner-approved hosted need/spend/key/egress; or admitted depth plus queue/fill protocol and costed model replay. Owners: owner/lead and data/execution/research leads. Neither calendar dates nor exports admit models.
- F E11 / M E12: "multi-model verdict, next version". Owner: lead; response: second-family leg, then amendment. Other events receive the named owner's evidence/convergence/review amendment; negative or inconclusive results retain research-only/dropped status. Frozen studies are not extended.
