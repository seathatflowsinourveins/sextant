# ADR-0007: Owner orders stay untouched and each account has one order writer

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-lanes@00203275944a:docs/adr/0008-custody-and-order-writing.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0015-owner-entry-paper-exit-manager.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0017-alpaca-order-reducer.md

## Context

Owner entries need prompt protection without surrendering their orders to the house.
REST answers, stream events, restarts and writer changes must preserve custody and possible-fill exposure.

## Decision

- **Provenance:** act only on house `client_order_id` and durable replacement lineage. Cancel, replace, flatten and adopt never rely on rc7's stamped `strategy_id` or replaced tags. [C1]
- **Owner custody:** never cancel, sell back, resize or adopt an owner order. A report grants no custody. Claim positively reconciled owner fills within `claim_max_latency_s` and protect immediately; an owner add to a strategy-held symbol pauses it and pages. Claim latency and registry reserves remain **unverified/UNCALIBRATED** until measured. [C1–C2]
- **Reservations:** an unlinked owner LIMIT reserves quantity; it is neither protection nor a flattening close. Protect only the unreserved residual. Arm freed quantity on cancel, expiry or partial-fill events; never cancel to seize it or infer attached presets. A fully owner-reserved position emits `owner_reserved_unprotected`, an alert, not a block. [R]
- **Writer scope:** one writer and pacer per broker account, one exit per quantity, never a second full-size exit. Foreign open orders or quantity mismatches freeze the symbol and page. Cutover requires observed old-writer exit, positive flat or explicit custody transfer, reconnect fencing, then new-writer start; copying state transfers no custody. [C3, N]
- **Node scope:** reconcile each account on its own node. Only B's dedicated exit manager uses `external_order_instrument_ids` with `filter_unclaimed_external_orders=True`; A/C never acquire instrument-global claims. Per-account nodes share the ranking publisher and keep their own account trade-update stream. A/C restart requires both accounts' `get_all_positions` empty until restart adoption is resolved. [N]
- **Order path:** pure modules emit intents; the runtime alone constructs orders through the pacer and synchronous reducer. ACK is not fill. Unknown/partial outcomes retain possible-fill exposure. Flat requires a positive broker-flat `FlatReceipt` and terminal lineage for every order. [C5–C6]
- **Pacing:** count Alpaca's orders/positions/account calls in its shared bucket; clock/calendar use their separate 1,000/min bucket. Keep the lane budget below the account cap. Reserve `reserve_per_open_position` and `reserve_per_exiting_position`; entries use the remainder. Prioritize protective amendments/exits, re-entries, then new entries; protection never waits for entry. Target full permitted budget use. [C4]
- **Limits:** carry the owner's Alpaca live 1,000/min, paper 200/min and IBKR paper/live 3,000/min limits. Alpaca paper's 200 calls/min/account is measured; live entitlement and achievable IBKR trade throughput are **unverified**. The inherited IBKR contract's 50 messages/second, subordinate order-action budget, order-efficiency and per-side working-order caps still bind. [L]
- **Synchronous ownership:** one reducer owns venue state, identity maps and native event/report delivery; async transport supplies facts. Keep PATCH, aliases and epochs. Reject stale GET epochs; merge action answers. A cancel blocks repricing, including after pacing. Preserve each DELETE attempt's outcome and each replace attempt's generation; an old answer/read cannot end a newer request. Recheck generation and intent before scheduling and after pacing. [G]
- **Terminal handover:** cancel-to-rearm waits for terminal ownership, then rereads residual shares, including partial fills. A resize retains its 60-second timeout. Asynchronous gaps are explicit; neither ACK nor a retained stop proves continuous protection. [R, G]
- **Recovery:** deliver authoritative order plus real fills together; use the executing order UUID and that generation's cumulative quantity for TradeId. Missing-order synthesis requires complete pages, terminal `filled`/`leaves_qty=0`, exact positive visible-fill sum equal to terminal cumulative quantity, and agreeing identity. A 404 or elapsed time proves none of these. [H]
- **Recovery bounds:** retain the 3-second unknown-order hold, 30-second collection/resolution deadlines, five unchanged-revision resolution passes, five stalled collection passes, 50 wire GETs/pass including successor chains, and 50,000-activity capacity. Cancel `K=config.max_retries` defaults to 3: at most `K+1` wire DELETEs/request/venue identity, normally 4. The separate `unknown_submit_grace_secs` defaults to 60 seconds. Exhaustion stays `EXHAUSTED_UNRESOLVED`; reconciliation cannot report completion. [H, G]
- **Fractional custody:** Alpaca forbids changing a fractional equity order's quantity by PATCH; a size change needs cancel/resubmit, while its price may be replaced. Fractional bracket/OCO submission remains **unverified** pending an Alpaca answer or paper drill before B adopts a fractional owner fill. Owner orders stay untouched. [F]
- **Limits of evidence:** pending queues/cursors are in memory; restart recovery depends on native cache and broker history in lookback. Keep the stdlib default executor. Seed `17413500058062512394`, after-PATCH fill carry, historical verification gaps and default-pool saturation remain unresolved; current runtime/broker acceptance is **unverified**. [H]

## Evidence

| Claim | Source (repo@sha:path, clause or lines) | Basis |
|---|---|---|
| C1–C2: provenance and owner fills | northstar-lanes@00203275944a:docs/adr/0008-custody-and-order-writing.md C1–C2, L44–62, L194–197 | NautilusTrader v2.0.0rc7 `55c0e8205314`: `crates/execution/src/engine/mod.rs`, `crates/live/src/execution/manager.rs`; alpaca-py v0.44.0 `cc4cb3b7ba50`: `alpaca/trading/requests.py`; Google/Claude reads 2026-11-01. |
| C3–C6: writer, pacer, intents and flat | northstar-lanes@00203275944a:docs/adr/0008-custody-and-order-writing.md C3–C6, L64–97 | Owner/harness hard lines and full-budget ruling, record dated 2026-10-30; inherited reducer contract. `none exists:` upstream owner/house custody or protection reserve, L197. |
| N: account nodes and cutover | northstar-lanes@00203275944a:docs/adr/0008-custody-and-order-writing.md amendment 2026-11-02, L218–248; northstar-trading@8256c16c31dc:docs/adr/0015-owner-entry-paper-exit-manager.md amendment 2026-11-05, L13–24 | Owner rebuild direction/LEAD ruling 2026-11-02; rc7 claim/cache APIs; Alpaca streaming docs read 2026-11-02; owner/LEAD handover ruling 2026-11-05. |
| R: reservation and residual protection | northstar-trading@8256c16c31dc:docs/adr/0015-owner-entry-paper-exit-manager.md L94–124, L235–252, L424–440, L545–552 | Owner/LEAD rulings 2026-11-03; alpaca-py 0.44.0 replace schema; rc7 modify API; terminal-cancel/partial-fill contract, read 2026-10-30/11-03. |
| F: fractional replacement and adoption | northstar-lanes@00203275944a:docs/adr/0008-custody-and-order-writing.md L183–184 | Alpaca Replace Order by ID reference, updated 2026-05-27, source read 2026-11-01; submission drill remains pending. |
| L: account budgets and owner limits | northstar-lanes@00203275944a:docs/adr/0008-custody-and-order-writing.md C4, L189–191; northstar-trading@8256c16c31dc:docs/adr/0015-owner-entry-paper-exit-manager.md L150–162; COMMON.md, owner words 2026-11-05/06 | Alpaca paper headers measured 2026-11-03; Alpaca support correspondence 2026-10-30; IBKR message accounting carried in C4; newest owner quote below. |
| G: epochs, generations and wire limits | northstar-trading@8256c16c31dc:docs/adr/0017-alpaca-order-reducer.md L135–145, L383–505, L1409–1499, L1751–1806 | rc7 native events/risk transitions and alpaca-py 0.44.0 GET/PATCH/DELETE contracts, read 2026-10-22/23; bounded local recovery retained, not new machinery. |
| H: recovery and unresolved evidence | northstar-trading@8256c16c31dc:docs/adr/0017-alpaca-order-reducer.md L15–19, PMK2 L157–327, L2060–2084, L2186–2214, amendment 2026-11-05 L2296–2305 | rc7 v2.0.0rc7 reconciliation/IB APIs; Alpaca activities docs read 2026-10-30; CPython 3.13.16 default executor; historical offline evidence; DeepSeek CONFIRM 2026-11-05 retains runtime limits. |

## Changes for Sextant

- Newest owner limits, verbatim (COMMON.md, 2026-11-05/06): "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"
- Source requirement, verbatim (COMMON.md, 2026-11-05/06): "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"
- The approved plan ("Your answers" and Phases 6–7, read 2026-11-06) starts sim-only. Paper handover needs owner account confirmation, a closed-market window and the old writer stopped first. Live authority remains the live-environment job on the live branch; this harvest authorizes no deployment or order.
- **Wash-trade refusal (A2, 2026-11-07):** Alpaca answers HTTP 403, in paper too, to a sell at or below a working opposite-side BUY LIMIT and to any pairing with a MARKET or plain STOP order; trailing stops and complex orders are exempt ([User Protection](https://docs.alpaca.markets/docs/user-protection), updatedAt 2026-09-16, read 2026-11-07; northstar-trading@8256c16c31dc:docs/research/2026-10-23-lane-api-convergence.md:33, both families STRONG). Owner orders are never canceled, so an owner's working BUY makes the house exit fail closed with a page, never a silent hold: the replay and sim engine freezes on any working order the house didn't send (Writer scope above), and B checks for an owner BUY before its trail cancel, so the exempt trail stays.

## Code and config to carry

Inventory only; counts measured with `git show <pin>:<path> | wc -l`. These named directories do not cover a complete port.

- northstar-lanes: `src/northstar_lanes/contracts.py@00203275944a` — 704 lines.
- northstar-trading: `src/northstar_trading/execution/pacer.py@8256c16c31dc` — 205 lines.
- northstar-trading: `src/northstar_trading/strategies/base.py@8256c16c31dc` — 2,247 lines.
- northstar-trading: `src/northstar_trading/strategies/exit_manager/books.py@8256c16c31dc` — 191 lines.
- northstar-trading: `src/northstar_trading/strategies/exit_manager/config.py@8256c16c31dc` — 518 lines.
- northstar-trading: `src/northstar_trading/strategies/exit_manager/custodian.py@8256c16c31dc` — 499 lines.
- northstar-trading: `src/northstar_trading/strategies/exit_manager/protection.py@8256c16c31dc` — 804 lines.
- northstar-trading: `src/northstar_trading/strategies/exit_manager/strategy.py@8256c16c31dc` — 2,285 lines.

## Disagreements

- ADR-0015's historical shared A/B/C namespace and disabled B preparation are superseded by lanes' 2026-11-02 account-node target and trading's 2026-11-05 non-gated B handover pointer. No handover completion is inferred.
- ADR-0015 L158–159 leaves IBKR's 3,000/min owner-stated without paper/live scope and says nothing targets live 1,000/min then. COMMON's newer ruling explicitly covers IBKR paper and live; actual broker accounting, unverified entitlement and Sextant's sim-first boundary remain explicit.
- ADR-0017's historical open proposal to remove PATCH never landed and closed without landing; its 2026-10-31 and 2026-11-01 amendments retain PATCH.

## Revisit when

- A custody witness fails, broker accounting or rc7 external-order stamping changes, an account cuts over, or a lesson names this decision in `contradicts_adr` (lanes ADR-0008 L156–167).
- Reservation/partial-fill/restart/terminal-flat evidence changes custody, the claim/replace API changes, recovery exhausts, a named runtime residual is resolved or default-executor saturation is measured reachable (trading ADR-0015 L308–324; ADR-0017 L21–38).
- A new family verdict changes the evidence. Custody/runtime owners raise the issue and amend the operative record; the lead owns the second-family review event. These events grant no deployment or order authority (same source registers).
