# ADR-0010: Retain the guard and shared pacer while paper observes house safeguards

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0006-risk-guard-and-pacing-in-our-layer.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0005-paper-safeguards-observe-and-manifest.md
- **Harvested from:** northstar@b384d298d217:docs/decisions/0022-execution-profile-24x5-leverage-throughput.md

## Context
The engine's Python surface cannot provide the complete kill, custody and request-pacing policy.
The accepted composition retains owner control and broker constraints while paper exposes house-policy failures for learning.

## Decision
- **G1.** Retain the Strategy-derived `RiskGuardActor` and pure guard core. Owner kill remains binding: persist its marker before fallible work, cancel entries through their owners, allow the 10 s cancel window, then reduce until broker net is flat. Revisit on a 2 s flatten tick; retain reducing protection, reserve in-flight leaves and never flip broker net. A halted guard handles late fills and stays latched until its permitted release.
- **G2.** Derive `Lane.safeguard_mode`: paper observes, non-paper enforces; deployment parameters/environment cannot override it. One registry-backed `gate()` owns classification; an unknown ID enforces and logs ERROR. House loss/drawdown, exposure/leverage estimates, unavailable account, persistence/drift, OER entry stops and automatic orphan actions observe on paper. They do not silently become live policy.
- **G3.** Owner kills, protective stops/flatten, dead-feed recovery, broker pacing/native eligibility/rates and required reconciliation preflight still act. Paper boot requires paper mode, an IB D-prefixed account and port 4002 or 7497. Explicit Alpaca deployment sessions/cutoffs enforce again after pacing immediately before POST; IB session/send-window rows still enforce. Entry windows do not block reducing exits/protection. Keep RiskEngine `bypass=False`; remove only its paper native per-order notional map.
- **G4.** One shared lane pacer uses bucket capacity = budget/10 and bounded refill; priority CANCEL > REDUCE > MODIFY > QUERY > SUBMIT, FIFO within kind. Deferred sends recheck admission. RiskEngine denies instead of queues; cancels bypass it and a list spends one token for N wire messages. Its backstop uses maximum one-second bucket release plus headroom. Native reconciliation/emulator-release coverage and broker-terminal cancellation/takeover proof remain **unverified**.
- **G5.** Use shared strategy marks and `equity = C_a + Σ q_i·m_i·mult_i (at the anchor) + (R − R_a) + (U − U_a)`. Anchor on quiet/post-query/post-fill evidence, persist day-start equity across restart and keep NetLiquidation as a drift cross-check. Marks share event-time ordering; the bounded cache and cash-booking lag do not prove perfect parity. Missing marks/anchors are never invented.
- **G6.** Persist halt/day equity, OER counters and leverage high-water mark atomically; reserve queued-entry exposure separately. Unreadable/unloaded state is not overwritten as fresh ACTIVE. Ownership is broker/account scoped. The guard closes only a capped net residual and adopts suitable existing exits. Same-instrument restart/claim limits and terminal evidence remain binding; historical universal emulated-stop policy is superseded by broker/session-specific protection.
- **G7.** Keep the measured IBKR paper restart residual: controlled exit 400 s after the last usable account state, roughly 6–7 min of stale-account use, then measured return to Running about 15 s later. Alpaca paper stale-account age observes: query, retain its cash anchor plus current marks and continue without account-age restart. Aggregate dead market-data recovery still exits; quiet-name/first-mark timing has no proven seconds-level bound.
- **G8.** Observations retain byte-identical loss warnings and fixed JSON keys: crossing, material change (money 1% of limit; would-be leverage 0.01), at most a five-minute reminder, and clearing; discrete boundaries once. Persist at most 500 edges, pruned to held/deployed instruments. Scanner-evidence durability also observes on paper, enforces live, and keeps durable receipts/loss accounting; its outbox is 4096 records/16 MiB.

## Evidence
| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| G1, G4, G6 | northstar-trading@8256c16c31dc:docs/adr/0006-risk-guard-and-pacing-in-our-layer.md, decisions 1/3/6/11–16; 2026-10-29 acceptance and paper cancellation continuation | Nautilus v2.0.0rc7 risk, NETTING, cancellation and order-emulator APIs; measured regressions; GPT/Google research with Claude acceptance review; DeepSeek 2026-11-05 check |
| G2, G3 | northstar-trading@8256c16c31dc:docs/adr/0005-paper-safeguards-observe-and-manifest.md, Decision and Finalized register | Owner 2026-10-26: “the safeguard itself should not be trading blocking for paper lane in any way, they need to be manifest with sota repo evidences”; lead 2026-10-27 explicit-session exception; rc7 `crates/risk/src/engine/config.rs:48–59` |
| G5, G7 | northstar-trading@8256c16c31dc:docs/adr/0006-risk-guard-and-pacing-in-our-layer.md, §16–17, cash-anchor reconciliation and Finalized E03–E08 | Owner information-parity direction; native Portfolio arithmetic and recorded gateway recovery; accepted stale-account residual; broker-applied-fill proof **unverified** |
| G7 | northstar-trading@8256c16c31dc:docs/adr/0005-paper-safeguards-observe-and-manifest.md, 2026-10-29 stale-account correction | Recorded Alpaca stale-equity restart evidence; IB heartbeat and dead-feed recovery unchanged |
| G8 | northstar-trading@8256c16c31dc:docs/adr/0005-paper-safeguards-observe-and-manifest.md, Decision and 2026-11-03 outbox amendment | Owner observation policy; measured outbox overflow/bursts and lead acceptance; DeepSeek confirmation |
| IB guard state | northstar@b384d298d217:docs/decisions/0022-execution-profile-24x5-leverage-throughput.md, 2026-10-23 amendment and Finalized IB-specific limit | RiskEngine REDUCING requires reduce-only; the official IB adapter denies reduce-only, so guard state and engine state remain distinct |

## Changes for Sextant
- COMMON.md, owner 2026-11-05/06, verbatim: "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"
- Approved plan, "Harvest" and Phase 7: carry guard/pacer/halt code later; retain the complete live decision and its amendments, with exact-SHA two-family review substituting for its old verdict mechanism. No broker, guard or deployment runs in this harvest.

## Code and config to carry
All below are northstar-trading paths; counts use the pinned blobs, not a running node.
- src/northstar_trading/risk/__init__.py@8256c16c31dc — 0 lines.
- src/northstar_trading/risk/actor.py@8256c16c31dc — 2230 lines.
- src/northstar_trading/risk/guard.py@8256c16c31dc — 415 lines.
- src/northstar_trading/risk/leverage.py@8256c16c31dc — 482 lines.
- src/northstar_trading/execution/__init__.py@8256c16c31dc — 0 lines.
- src/northstar_trading/execution/pacer.py@8256c16c31dc — 205 lines.

## Disagreements
The historical guard text enforces house loss/exposure/OER/persistence rules on paper; its 2026-10-29 acceptance explicitly defers to the broader paper-observe successor. Preserve G2/G3 and the explicit-session exception. Old NetLiquidation equity formulas lose to §16 and later anchor repair. Generic engine REDUCING is no IB kill path: its reduce-only admission conflicts with the adapter's denial. Cancellation intent/local terminal state does not prove broker-terminal custody.

## Revisit when
Guard corruption/start-halt, cancel/takeover, cash/mark parity, quiet-feed/restart or leverage-recovery evidence contradicts the contract; engine risk APIs or native release/reconciliation pacing changes (from rc8 a `HALTED` engine denies emulated stops, so protective exits use `REDUCING`: [ADR-0029](0029-second-family-corrections.md) C3); account/custody/session/limits mapping changes; qualified Gateway restart/fencing/authentication evidence arrives; a manifest/gate drifts, scanner evidence is lost or journal rotation lands; a lesson contradicts this record; or "multi-model verdict, next version" arrives. The owning risk/execution lead records evidence and amends the owning decision; immediate owner kills still act.
