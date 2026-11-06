# ADR-0019: Trading merit requires frozen out-of-sample evidence over every trial

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-trading@8256c16c31dc:src/northstar_trading/validation/
- **Harvested from:** northstar-trading@8256c16c31dc:src/northstar_trading/reflection/merit.py and merit_thresholds.py
- **Harvested from:** northstar@b384d298d217:plugins/northstar-trading/skills/backtest-validation/SKILL.md
- **Harvested from:** northstar@b384d298d217:docs/decisions/0023-ab-testing-and-fine-tuning.md
- **Harvested from:** northstar@b384d298d217:docs/decisions/0053-live-lane-automated-evidence-gated.md
- **Harvested from:** northstar-lanes@00203275944a:docs/adr/0009-evidence-and-learning-loop.md

## Context

Merit is attributable evidence for one exact strategy/arm, code, parameters, data and cost model. A profitable curve or a paper proposal is insufficient.
Offline comparisons select methods; prospective sim/paper establishes execution and operational fidelity. Statistical failure never blocks paper operation and never grants live authority.

## Decision

- Use survivorship-free, corporate-action-adjusted, timezone-correct data with recorded source/feed and point-in-time membership. Features must be knowable by decision time; bars must be closed. State commissions, fees, spread/slippage and borrow. Missing data or prerequisites remain missing/**unverified**, never PASS. [H]
- Freeze estimand, opportunity/decision pairing, windows, costs, parameters, dependence, replication and multiplicity before results. Rank choices use portfolio-days; exit/sizing choices need frozen-entry confirmation and event replay. Model-training-window LLM replay is screening only. [A]
- Walk-forward uses rolling/expanding train/test windows and per-fold results; median OOS Sharpe >0 and ≥60% positive folds. CPCV explicitly sets purge and embargo, each at least the label/holding horizon; use independently evaluated OOS paths. The contract producer checks lower-quartile path Sharpe >0. Recombined selected returns are not train-only fitting. [CV]
- Compare paired A/B on the same catalog, fill/fee/latency models and random seed. Report Diebold–Mariano HAC, Ledoit–Wolf Boot-TS (p<0.05 and positive Sharpe difference); SPA/StepM/MCS covers >2 variants. These methods are not asserted equivalent. [AB]
- Fine-tuning uses Optuna 5.0.0 multivariate TPE for this scalar single-objective study, 5–8 parameters, 100–300 trials, lower-quantile CPCV-path Sharpe and Wilcoxon fold pruning. Log every attempted configuration, rejected/failed/pruned alternatives included. Never reset cumulative trial history for a version or optimizer run. [AB, N]
- DSR >0.95 uses the effective trial count with skew/kurtosis and complete search provenance. PBO ≤0.05 uses CSCV, S=16; 0.20 is only a loose first screen. PSR ≥0.95; preserve the result's sign at 2× all costs and inspect 3× slippage, regimes, parameter neighborhoods and capacity. Finish with an untouched one-shot 12–24-month holdout. [G]
- Adoption requires both paired lower bounds over incumbent AND hold-flat >0 at stressed cost; circular whole-session blocks retain the symbol cross-section, studentized by block-bootstrap mean SE. Calibrate/freeze block length on training data with longer-block sensitivity (Ledoit–Wolf Algorithm 3.1). Across a family use Romano–Wolf StepM on stacked arm×condition columns, `arch` 8.0.0 `bootstrap="cbb"`, α=1−`adoption_lower_bound_level`; every column must reject. DSR/PBO and one confirmatory look also bind adoption; further preregistered looks use Bonferroni, revealed holdout becomes development data. Below `pbo_min_sessions`, PBO is INCONCLUSIVE. [A]
- One `TrialLog` retains all arms/runs with MODELED, SIMULATED or BROKER-PAPER labels; no pooled tiers/block sets, no missing-return zero imputation or silent dropping. Freeze each inference's cumulative N/effective-N snapshot. Code counts unknown correlations independently and uses the larger return-correlation/upstream-autocorrelation count, not an ONC claim. [N]
- Decision 2a merit needs independent flat-to-flat round trips reaching measured MinTRL at PSR ≥0.95, with ≥30 round trips over ≥5 sessions covering every traded session type; replay correlation ≥0.9, slippage ≤1.5× modeled, zero unexplained risk events and an actual dossier. No calendar minimum. A floor is not statistical power. [M]
- Bind all 18 decision-2a gate values, exact reports/hashes, code/parameter/arm identity, session coverage, PIT/feed fidelity and paper/sim safety drills. P&L uses native attribution; fees already in net P&L are not deducted twice. Money/quantity stay engine types or Decimal; only statistical return arrays use floats. Merit produces a Stage-0 draft, never admission, deployment or automatic promotion. [M]
- Report OOS tearsheet, gates, source/feed, biases, search history and unknowns under `reports/validation/<strategy>/<date>/`; link it to the strategy record and obtain the skill's skeptic review before proposing a candidate. Live additionally obeys [ADR-0020](0020-live-lane.md), including its holdout, engine, exit-plan and staged gates. [H, M]

## Evidence

| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| H: hygiene and reporting | northstar@b384d298d217:plugins/northstar-trading/skills/backtest-validation/SKILL.md:8–29,55–60 | Bailey–López de Prado DSR/PSR/MinTRL; Bailey et al. PBO; skfolio WalkForward/CPCV; recorded skill practice. |
| CV: fold/path contracts | northstar-trading@8256c16c31dc:src/northstar_trading/validation/cv.py:26–84; northstar-trading@8256c16c31dc:src/northstar_trading/validation/contract_gates.py:510–626 | Adopted skfolio APIs; exact 1-observation contract receipts; source-prescribed independent fitting, not a run. |
| AB: paired tests and search | northstar@b384d298d217:docs/decisions/0023-ab-testing-and-fine-tuning.md:13–43,54–66,95–115 | Ledoit–Wolf 2008; arch 8.0.0; Optuna v5.0.0 `01ddd17ab9f36c3d2817aed9afe376e1cb047d35`; GPT register, DeepSeek CONFIRM. |
| G: fixed thresholds and methods | northstar-trading@8256c16c31dc:src/northstar_trading/reflection/merit_thresholds.py:13–40; northstar-trading@8256c16c31dc:src/northstar_trading/validation/stats.py:1–12,51–125 | ADR-0053 decision 2a; purgedcv 0.1.11 with independent DSR formula check; published DSR/PBO methods. |
| A: frozen adoption | northstar-lanes@00203275944a:docs/adr/0009-evidence-and-learning-loop.md:62–82,235–245,272–277 | Later three-family factor-assignment convergence; Ledoit–Wolf 2008; arch v8.0.0 `038d78b709e75f2590890757af32705817a6fad8`; adopted skfolio v1.12.5 `0db206ed812622088cbd33af2e34a0f4762fa71e`. |
| N: cumulative accounting | northstar-trading@8256c16c31dc:src/northstar_trading/validation/trials.py:36–58,245–303,305–405,622–714 | Existing TrialLog/purgedcv composition, preserving attempted alternatives and immutable inference snapshots. |
| M: exact merit, floors and authority | northstar@b384d298d217:docs/decisions/0053-live-lane-automated-evidence-gated.md:95–108,368–384,759–777; northstar-trading@8256c16c31dc:src/northstar_trading/reflection/merit.py:324–494,527–663; northstar-trading@8256c16c31dc:src/northstar_trading/validation/contract_inputs.py:265–327 | Owner 2026-10-22/26; existing arm-ledger/1 decision-2a contract; native NautilusTrader rc7 attribution. |
| New-code merit limitation | northstar-trading@8256c16c31dc:src/northstar_trading/reflection/ledger.py:667–726,983–991,1057–1062 | Source records code SHA but its prior-arm guard checks params/lane/strategy; caller enforcement of the plan's reset is unverified. |

## Changes for Sextant

The approved plan, Validation row and Phases 2/4/7, carry skfolio 1.12.5 CV, checked DSR/PBO and TrialLog. Irreplaceable trials and merit records use `ledger`. No thresholds change. Phase 7's only verdict substitution is exact-SHA two-family review; merit remains evidence, never automatic live admission.
Newest relevant owner direction, verbatim from COMMON.md (2026-11-05 and 06):

> "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"
> "FOCUING ON US EQUALITY, OPTION,STOCKS ETC, AND ALL THE LANES PREVIOSU STATED, PHILOSOPY PREVIOUS STATED, JEV TRADE RELATED RPEOS ETC ,RESEARCH LANE ,AUTO LEVERAGE, PROTFOLIO MANGEMENT AND BEYOND"
> "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"

## Code and config to carry

All trading paths are at northstar-trading@8256c16c31dc; each count is `git show <pin>:<file> | wc -l`. No code copied.

- `src/northstar_trading/validation/`: `__init__.py` 5; `backtest.py` 244; `contract_gates.py` 916; `contract_inputs.py` 363; `cv.py` 84; `gates.py` 450; `optimize.py` 168; `sealed.py` 23; `stats.py` 290; `trials.py` 749. Total 10 files, 3,292 lines.
- `src/northstar_trading/reflection/merit.py` 663 and `merit_thresholds.py` 64; the one arm-ledger writer is `src/northstar_trading/reflection/ledger.py` 1,096. The source skill at northstar@b384d298d217:plugins/northstar-trading/skills/backtest-validation/SKILL.md has 60 lines.

## Disagreements

- The skill and legacy `validation/gates.py:343–346` retain ≥60 paper days. northstar ADR-0023's October 24/November 1 amendments explicitly retire that calendar table; ADR-0053's newer owner ruling and the trip-level contract use ≥30 independent trips, ≥5 sessions and measured MinTRL. The old 684-day/10.9-year examples are assumption-bound, not impossibility rules.
- northstar ADR-0023/skill mention effective-count correlation or ONC; the supplied code implements the documented correlation/autocorrelation maximum. Its legacy `gates.py:101–108` always reports unreplicated published DSR tables, Boot-TS calibration and selected-parameter OOS limitations. Keep those **unverified**; contract-grade fresh-fold evidence is distinct from diagnostic gates.
- The adopted/plan skfolio pin is 1.12.5; trading `pyproject.toml:27` still pins 1.12.2 and `cv.py:1` says 1.9.6. This harvest installs nothing and does not turn stale source labels into the adopted version. The lanes record also resolves its earlier DSR/PBO-live-only wording in favor of the later adoption-specific convergence (:235–237).
- The approved plan's Phase 7 requires new code to start a new merit record. The supplied arm-ledger producer records code SHA but can accumulate prior periods without checking SHA in its prior-arm identity guard. These modules alone do not prove that reset; caller enforcement remains **unverified** (ledger source above).

## Revisit when

- The owning validation method, live gate or pinned Nautilus/arch/Optuna/skfolio behavior changes; an independent DSR/PBO/CPCV/StepM evaluation changes the evidence; or a contradictory lesson, calibrated protocol, new holdout or inference result arrives: validation/research lead checks the primary evidence and amends (ADR-0023 E23-1–5; lanes L5).
- An independent-family verdict arrives: lead records the “multi-model verdict, next version” amendment. Published-model/card claims remain non-operative until their own evidence/admission; this harvest verifies no strategy merit, power, live readiness or end-to-end workflow.
