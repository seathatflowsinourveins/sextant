# ADR-0006: Re-enter on a confirmed reclaim or rotate after proven flatness

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-lanes@00203275944a:docs/adr/0007-reentry-and-rotation.md, whole record and amendments.
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0019-managed-exits-and-ranked-reentry.md, whole record and amendments.

## Context
A fast protective sell can forfeit the rest of a mover's run.
Re-entry must earn its extra round trips, preserve custody and use a current rank.

## Decision
- **Flat first (R1):** broker net quantity zero plus terminal lineage for entry, every protection and replacement. Unknown/partial is never flat. Start cooldown at this receipt, not the sell: `now_ns ≥ flat_receipt.ts + cooldown_seconds × 1_000_000_000`.
- **Choice (R2):** retry the same symbol when its setup fires and parent rank is within `retry_rank_band`; otherwise rotate to the best unheld independently qualified name within `rotation_rank_band`; otherwise wait.
- **Reclaim (R3):** since our sell and within `reclaim_lookback_s`, the name must have traded at/below the sell trigger or segment VWAP, then above it for `reclaim_trades_count` spanning `reclaim_trades_span_s`, with covered flow. A continuation that never returned to the level is not a reclaim.
- Cap the buy at `reclaim_max_above_buffers` buffers above the level, in [0, 1], so the new trigger stays at/below it. Require entry's held higher-low retest for `reclaim_hold_s`; never buy the first print. `first_print` is shadow only. Breakout needs NOT_EXTENDED. Read rising/flow on live eligible trades at the decision; use [ADR-0004](0004-entry.md)'s shared setup definitions and segment reset.
- **Held rotation (R4):** pair-specific `expected_lift`, a fraction of notional over the pair's horizon, must be strictly greater than `2 × c_RT ÷ price + rotation_lift_margin_bps ÷ 10_000`. None means no held rotation. Flat-slot rotation after a fast sell needs no lift. When buying power is committed, the entry score-ratio rule selects the weakest holding.
- **Freshness (R5):** missing/stale/invalid/ambiguous ranking means `Wait`, even with a fresh quote. No stale fallback; `RankingView` binds to generation identity.
- **Whipsaw (R3a):** after `whipsaw_stopouts_max` consecutive pre-arm stop-outs on one symbol, its next entry requires capped reclaim, or qualifying OVERSELL; rising alone is insufficient. Reset the count on armed exit or session boundary.
- **OVERSELL flush (R3b):** after sell at `P_s`, price-eligible trades below `P_s × (1 − flush_min_depth)` within `flush_window_s` establish low `L`. Exhaustion needs all three: sell-classified dollar volume over `climax_window_s` ≥ `climax_ratio` times recent average; a higher low ≥ `L + one_tick` held for `oversell_hold_s`; and buy/sell classified volume ≥ `buy_flow_ratio` over `flow_window_s`.
- Classify eligible trades against the prevailing quote with Lee–Ready. An uncovered window is unknown. Until classifier coverage is witnessed, OVERSELL stays shadow/replay only. rc7 Hurst/VPIN is documented non-use on this feed because `NO_AGGRESSOR` trades form no VPIN.
- OVERSELL also needs a still-live catalyst if present and rank within `retry_rank_band`. Buy at most `oversell_max_above_buffers` above the higher low; initial trigger `L − buffer`. Carry `stop_distance = entry − (L − buffer) + chase_cap_fraction × entry`; retain that wider gap until gain lock arms. Its flush-low risk exempts it from the VWAP extension rule.
- **Confidence:** OVERSELL averages four clipped components (catalyst, rank, flush, buy flow); RECLAIM/BREAKOUT average catalyst, rank and buy flow. Catalyst strength is 1 for live source-stated positive, 0.5 for live unknown polarity, 0 for none/expired; negative means no re-entry. Live means within `catalyst_live_window_s` of receipt on the same trading date.
- Same-symbol re-entry requires `confidence ≥ reentry_min_confidence`; missing confidence is refused before sizing, never treated as 1. Size through entry's confidence multiplier, with `confidence_size_floor` in [0, 1]. A different-symbol flat-slot rotation into an independently qualified fresh first leg may be explicitly unscored, without a multiplier or invented score.
- **Modes (R6):** `paper_unbounded` has no count cap and no renewing-budget limit; journal count, setup, cooldown, reclaim level and rotation lift. Paper re-entries may cross a session boundary within the account's session rules. `live_nonrenewing` enforces `reentry_max` and original campaign risk/notional/quantity; profits, owner adds, restarts and rejects never refill it. Live stays 1x with retry/rotation OFF until their own promotion under the carried live gates. IBKR paper re-entry stays OFF.
- Every threshold is a registry row, UNCALIBRATED until its calibration record exists. Compare re-entry with no re-entry and hold-flat at stressed costs; after-cost recovery versus churn remains **unverified**. Keep negative/inconclusive results; never move a witness's anchor/cap/hold to force a pass.
- **Newcomers:** the 15-minute pause, one-post-loss-retry-per-day cap, tilt-check, purgedcv and exitkit in the 2026-11-04 supplement retain candidate/watch/reject dispositions and their evidence triggers. None replaces R1–R6. The 2026-11-05 second-family verdict changes no pick.

## Evidence
| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| Flat proof, choice, lift, modes | northstar-lanes@00203275944a:docs/adr/0007-reentry-and-rotation.md, R1–R6, Evidence | Owner continuous-paper-re-entry ruling 2026-10-30; accepted E5 design `2026-10-30-reentry-rotation-design.md`; GPT/Google/Claude template-library convergence. |
| Held retest, whipsaw, confidence | northstar-lanes@00203275944a:docs/adr/0007-reentry-and-rotation.md, R3/R3a/R3b | Owner "reentry again at suitable point" and no-first-print rulings 2026-10-30; source's replay witnesses. |
| Flow feasibility | northstar-lanes@00203275944a:docs/adr/0007-reentry-and-rotation.md, R3b, Evidence | Lee and Ready (1991), "Inferring Trade Direction from Intraday Data", Journal of Finance 46(2); modern accuracy/delay/condition handling **unverified**. NautilusTrader v2.0.0rc7 Hurst/VPIN Buy/Sell-only path, `strategy.rs:437–445`. |
| Paper caps retired; IBKR/live scope | northstar-trading@8256c16c31dc:docs/adr/0019-managed-exits-and-ranked-reentry.md, Finalized amendment, D9, amendment (1) | Owner paper-never-gated ruling 2026-10-30; GPT/Google exit convergence; accepted policy move to lanes, not a runtime cutover. |
| Alternatives remain alternatives | northstar-lanes@00203275944a:docs/adr/0007-reentry-and-rotation.md, amendments 2026-11-04 and 2026-11-05 | Blind DeepSeek supplement and CORRECT verdict; no new pick; stale 1-of-3 detector count corrected to 1-of-5. |
| Upstream boundary | northstar-trading@8256c16c31dc:docs/adr/0019-managed-exits-and-ranked-reentry.md, upstream checked / none exists | NautilusTrader v2.0.0rc7 `55c0e82053142bce3a5cba4de4221d3929c2d3bc` claims/OMS and alpaca-py v0.44.0 `cc4cb3b7ba50ae250e621983c2779047fb16bb28` order types, read 2026-10-30. Source found no upstream ranked choice behind flat proof; no new mechanism here. |

## Changes for Sextant
The approved plan carries the live gates in full, substitutes two-family review on the exact SHA for the old adversarial-verify verdict, and reserves authorization of Sextant's sole live path to the owner at Phase 7. No live authority is activated here. The owner's newest source rule (2026-11-05/06, COMMON.md), verbatim:
> "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"
The owner's verbatim lane/throughput scope is in [ADR-0002](0002-philosophy-and-lanes.md); paper's uncapped retry policy remains subject to custody, protection-first pacing, broker limits and owner halt.

## Code and config to carry
Inventory only; `git show <pin>:<path> | wc -l` supplies counts, not adoption or deployment proof.
- northstar-lanes@00203275944a:src/northstar_lanes/contracts.py (704 lines); northstar-lanes@00203275944a:src/northstar_lanes/parameters.py (95 lines); northstar-lanes@00203275944a:src/northstar_lanes/classification.py (118 lines); northstar-lanes@00203275944a:src/northstar_lanes/classified_flow.py (346 lines).
- northstar-trading@8256c16c31dc:src/northstar_trading/strategies/exit_manager/reentry.py (272 lines); northstar-trading@8256c16c31dc:src/northstar_trading/strategies/exit_manager/rotation_wiring.py (153 lines); northstar-trading@8256c16c31dc:src/northstar_trading/strategies/exit_manager/custodian.py (499 lines).
- northstar-trading@8256c16c31dc:src/northstar_trading/strategies/exit_manager/config.py (518 lines); northstar-trading@8256c16c31dc:src/northstar_trading/execution/pacer.py (205 lines). The proposed pure `src/northstar_lanes/setups.py`/`reentry.py` are absent at the lanes pin; a complete R1–R6 port is **unverified**.

## Disagreements
Trading ADR-0019's historical non-renewing paper campaign budget, one-retry and rotation-OFF design are superseded by its accepted 2026-10-30 amendment and lanes R6. Non-renewal still binds promoted live retry. Its old outside-RTH entry gate is permanently lifted for paper; newer per-account session rules still apply. The newcomer 15-minute pause and daily cap are not adopted paper limits. Economic superiority remains unproven.

## Revisit when
Calibration compares re-entry with no re-entry; the carried live gates promote live re-entry; a lesson contradicts this record; a named newcomer's registered gate/trigger is reached; or "multi-model verdict, next version" arrives. Paper/research owns calibration and newcomers; lead/live owner owns promotion; lead obtains the second-family verdict and amendment. Preserve the source's exact newcomer gates rather than adopting an elapsed-time rule.
