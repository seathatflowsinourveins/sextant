# ADR-0024: Rank extreme movers and enter only on causal early-stage evidence

- **Status:** accepted. Harvested; the decision is unchanged unless “Changes for Sextant” says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-10-26-missed-movers.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-10-27-missed-movers.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-10-27-missed-movers.json
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-10-26-premarket-gap.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-10-28-premarket-catalyst-range.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-10-28-premarket-gap-calibration.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-11-01-scanner-early-mover-integration.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-11-01-scanner-premarket-volume.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-11-02-ibkr-advanced-movers/convergence.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-11-02-ibkr-advanced-movers/synthesis-claude-max.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-11-02-ibkr-advanced-movers/synthesis-gpt.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-11-02-pmg-mover-arming.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-11-02-pmg-mover-arming-r2.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-11-02-pmg-mover-keepalive.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-11-02-pmg-mover-rows.json
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-10-27-scanner-recall.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-11-05-extreme-movers-onset.md
- **Harvested from:** northstar-lanes@00203275944a:docs/m2-mover-surge.md
- **Harvested from:** northstar-lanes@00203275944a:docs/adr/0004-ranking-and-feeds.md
- **Harvested from:** northstar-lanes@00203275944a:docs/adr/0005-entry.md
- **Harvested from:** northstar-lanes@00203275944a:src/northstar_lanes/mover.py
- **Harvested from:** northstar-lanes@00203275944a:src/northstar_lanes/classification.py

## Context
The focus is US-equity extreme movers, early entry, gain protection and fast exit, with paper 24/5 and sim 24/7. The measurements and their limits are in the [evidence note](../research/2026-11-06-extreme-mover-evidence.md).

## Decision
- **Candidate history:** the required pinned searches found no committed multi-year daily-candidate/extreme-mover dataset. The checked-in replay is `docs/research/2026-10-27-missed-movers.json`: one session, [04:00,09:30) ET on 2026-10-27, 18 symbols, 3,268,669 bytes. It records 11 +5% movers, 9 no-arm misses and 5 activity-unresolved candidates; coverage is incomplete. “2016+” is historical SIP availability in a decision record; actual premarket coverage is **unverified**, not an existing multi-year candidate history.
- **Ranking:** retain K2's `move × dvol_ratio`, against the latest completed, split-adjusted official RTH close and the symbol's own time-matched segment baseline; acceleration then symbol breaks ties. Recompute on eligible trades, throttle publication by elapsed time, and keep unknown references, coverage and normals unknown. Price, absolute dollars, trade rate and spread do not gate paper ranking. K3 and its thresholds are house rules, **UNCALIBRATED**, with no demonstrated after-cost edge.
- **Early entry:** N1's first leg buys the first rising run inside its flag window and extension cap; a lower trade resets the run. Reclaims require their pullback, higher low and hold. Missing ATR/VWAP is UNKNOWN. Pre-position calendar catalysts; no headline is required for a surge. Event time, first moved print, flag and known-at are distinct; replay timing with synthetic arrivals is not operational latency.
- **Scanner:** preserve the integrated R2 correction: complete daily history uses `RVOL/(1+RVOL)`, or 0 when its profile is unavailable; absolute-dollar/count credit is only for `history_unknown`. Snapshot quote pressure is a disclosed proxy, not classified flow. The saved October 27 replay changed recall by zero percentage points; its earliest @30 was 6/41. Synthetic rank changes are not improved market recall.
- **Premarket:** the original fixed 04:00–04:05 range uses a first-open gap of at least 1%; opt-in trigger mode instead seals the first complete, aligned, bullish five-live-minute block meeting its explicit gap and `sum(close × volume)` thresholds. Neither mode backfills a missed live range. The calibration recommends `max(50000, 0.001 × ADV20)` and $1m prior-post turnover, retaining $5m candidate ADV and unknown-ADV exclusions; these are a single-day paper calibration, not an optimum. Below-5% triggers remain an UNCALIBRATED candidate grid, not a deployed default. Later session extensions supersede the original pre-only clock scope.
- **Mover arming:** the recorded 0.4 share gives 2/5 and 8/20 mover slots, shared with the potential pool; custody counts first, potential fills first, and unused slots pass over. Snapshot `move × RVOL` is the interim score, with RVOL then symbol ties. Keep-alive preserves eligible membership through incomplete session inputs; current entry qualification remains required, quotas win, and 20:00 resets range/attempt against the new close. These are selection and implementation evidence, not measured alpha.
- **IBKR:** carry the reconciled 5 CANDIDATE / 8 REJECT / no ADOPT result. Long-only SIP-L1 OFI is the most immediately replayable candidate; liquid-tier buffered reversal is strongest by the reconciler's published-cost criterion. Its source also reports −66.1/−103.7 bps/week for extreme-quintile configurations; liquid-stock gains are not extreme-mover validation. Borrow, depth, venue and aggregate pacing limits remain explicit. The newer onset study is a NOT_RUN replay/sim specification; K3 remains incumbent, with no measured detector winner.

## Evidence
| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| History, first detection and misses | northstar-trading@8256c16c31dc:docs/research/2026-10-27-missed-movers.md, table/Coverage; 2026-10-27-scanner-recall.md, Result; 2026-11-05-extreme-movers-onset.md, R03–R07/Y9 | Recorded SIP/snapshot replay; coverage conditional; onset experiment NOT_RUN |
| Ranking, causal setup and classifier | northstar-lanes@00203275944a:docs/adr/0004-ranking-and-feeds.md, K1–K8; docs/adr/0005-entry.md, N1–N7 and November 2 amendments; src/northstar_lanes/classification.py:1–8 | Owner rulings; GPT/Google convergence; Lee–Ready (1991), DOI 10.1111/j.1540-6261.1991.tb02683.x, abstract checked/full text unavailable in source |
| Early replay limits | northstar-lanes@00203275944a:docs/m2-mover-surge.md, Replay measurements and limits | INO interpolated-normal witness; CLRO/CHOW and operational-latency gaps retained |
| Premarket and scanner corrections | northstar-trading@8256c16c31dc:docs/research/2026-10-28-premarket-gap-calibration.md, Recommendation/Amendment 2; 2026-11-01-scanner-early-mover-integration.md, R2 | Zarattini–Barbon–Aziz SSRN 4729284 as original RTH reference, explicitly unvalidated premarket adaptation; single-day measurements and synthetic fixtures |
| Allocation and keep-alive | northstar-trading@8256c16c31dc:docs/research/2026-11-02-pmg-mover-arming-r2.md, Rows; 2026-11-02-pmg-mover-keepalive.md, Round 3 | Owner/spec 2026-11-02; native offline tests; sized r2 rows supersede the one-share description |
| IBKR candidates and dissent | northstar-trading@8256c16c31dc:docs/research/2026-11-02-ibkr-advanced-movers/convergence.md, §§1–4/9 | GPT/Muse legs, Claude/GPT syntheses; Cont–Kukanov–Stoikov, Avellaneda–Lee, de Groot–Huij–Zhou; no house alpha run |

## Changes for Sextant
The approved plan's “Harvest” and Phases 3–5 carry records and source inventories, with sim first. The newest owner rulings are requirements, not measured outcomes (COMMON.md, 2026-11-05/06, verbatim):
> "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"
> "FOCUING ON US EQUALITY, OPTION,STOCKS ETC, AND ALL THE LANES PREVIOSU STATED, PHILOSOPY PREVIOUS STATED, JEV TRADE RELATED RPEOS ETC ,RESEARCH LANE ,AUTO LEVERAGE, PROTFOLIO MANGEMENT AND BEYOND"
> "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"
> "we need to using full sota harness framework.dsh that is fully enhanced with openviking etc"
The batch's newest ruling (BRIEF-E.md, 2026-11-06, verbatim):
> "EVERY LINE WILL BE SOTA SOURCED WITH CLEAN RULES MANFIEST ,SUCH AS THE COMPOUNDING LEARNING ENHANCED BY SOTA MEMORY /RAG REPOS ETC PAPER LANES HANDBOOKS, 24/5 24/7 EXTREME MOVER FOCING EARLY ENTRY AND FAST EXIT WITH LOSS AVOID WITH AUTO GAIN PROTECTION WITH TESTED STRICT TRAILING STOP OR DYNAMIC LIMIT SELL FOR PROTECT THE GAIN ,AND SELL FAST WHEN THE FIRST SIGN OF NON NOISE SELL, WITH RANKING OF MOST POTENICAL EXTREME MOVERS, SUCH AS PREVIOUS RESEARCH ON THE MOST EXTREME MOVERS ALL THE DAILY CANDIDIATES IN THE PASSED YEARS.SO WE CAN ENTER TRULY AT EARLY STAGES.THIS IS THE FOCUS OF OUR ECOSYSTEM"

## Code and config to carry
- northstar-lanes@00203275944a:src/northstar_lanes — 17 files, 3,832 lines; `mover.py` 306 and `classification.py` 118.
- northstar-trading@8256c16c31dc:src/northstar_trading/scanner — 35 files, 18,910 lines; `potential2.py` 1,204 and `reader.py` 364.
- northstar-trading@8256c16c31dc:src/northstar_trading/strategies/premarket_gap — 17 files, 7,405 lines; `scanner.py` 1,986, `signals.py` 259; docs/research/2026-11-02-pmg-mover-rows.json — 84 lines. Inventory only; copy no code.

## Disagreements
- The owner's requested past-years candidate history is not established by the pins. October 27 has 7 non-premarket candidates, 5 tier/liquidity exclusions, 4 late rankings and 2 missing carriers; these are explanatory labels, not fill-denial or missed-profit proof.
- Withdrawn complete-history dollar-volume credit and UPC rank-1 uplift are historical results, not current scoring. The r2 mover-only common-stock refusal is superseded by N7's later labeled-NMS-ADR admission; its old potential-pool admission gap is not a new policy.
- The IBKR Claude synthesis preferred residual convergence including a sector hedge; reconciliation rejects that hedge's off-ranking eligibility and favors liquid-tier buffered reversal. Muse's fade ADOPT remains dissent; neither is promoted here.

## Revisit when
- A point-in-time coverage manifest or multi-year archive, causal onset/score/arming experiment, missing first-leg registry starts, or full-session detector witness lands: research and the owning lane re-check the affected claim and amend it, retaining negatives.
- A relevant upstream/feed change, measured latency/protection regression, owner scope ruling or “multi-model verdict, next version” occurs: the owning lane and lead revisit only that decision.
