# ADR-0009: Preserve the owner's limits and pace every outbound request below capacity

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar@b384d298d217:docs/decisions/0019-execution-topology-lanes-throughput.md
- **Harvested from:** northstar@b384d298d217:docs/decisions/0022-execution-profile-24x5-leverage-throughput.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0003-north-star-data-stack-final.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0004-paper-capacity-policy-2026-10-26.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0006-risk-guard-and-pacing-in-our-layer.md
- **Harvested from:** northstar-trading@8256c16c31dc:configs/lanes.yaml
- **Harvested from:** northstar-lanes@00203275944a:configs/lanes.yaml

## Context
The owner's limits are **1000/minute Alpaca live, 200/minute per Alpaca paper account, and 3000/minute IBKR paper and live**.
Broker requests, wire order actions, new orders and fills are separate counters; a stated limit is not measured account entitlement.

## Decision
- **R1. Count at the wire:** submits, modifies and cancels, each list member and each SDK retry, count as order actions once actually sent. Unsent work does not count. Report new orders, fills and HTTP/TWS requests beside that denominator.
- **R2. Alpaca paper:** its 200/minute account/order/asset trading bucket includes queries. A/B budget 180 order actions/minute; C budgets 150 plus `mcp_reserve_per_min: 50`. Paper is ineligible for the increased trading-API rate. Use `trade_updates` instead of polling. M1's separate 1000/minute clock/calendar bucket does not raise the order bucket; option-contract/announcement membership is **unverified**.
- **R3. Alpaca live:** preserve the owner's 1000/minute limit, counted as all calls including queries. The source ties that rate to Elite; its budget is ≈850–900 order actions/minute, a shared 15/s token bucket, with 870/minute in lanes config. Alpaca, as the owner pasted 2026-11-06: the account moved to the Pro-Line on the owner's 2025-11-20 ticket; Pro Line gives "an API call rate of up to 1,000 calls per minute" and has no DMA, TWAP or VWAP order types; "Paper account are not eligible for the increased API rate." Not yet measured on the account, so trading config retains 200/180 until the live lane measures it. Above 1000 needs FIX or a written raise; FIX is still open with Alpaca.
- **R4. IBKR paper/live:** preserve 3000 wire order actions/minute. Broker request cap is market-data lines ÷ 2 per second: 100 lines gives 50/s, shared by orders, data subscriptions/history and account/reconciliation queries; streamed ticks do not count. Default budget ≤80% of that cap: 40/s all outbound requests. The legacy 30/s IB-data budget retires only once rotation requests pass the pacer; do not multiply capacity across clients.
- **R5. Feasibility:** the source says "3000/min is not feasible at the default." A 3000/minute burst needs ≥200 lines (Quote Booster $30/pack, or about $2M equity) at 50% load. Sustained operation would need about 58.5k fills/day under `OER = (submits + modifies + cancels) / (fills + 1) ≤20/day`. OER paper applicability/account tolerance, Booster counting, fixed/rolling windows and expected peak orders/s remain **unverified** owner/broker inputs. Error 100 and three violations can disconnect when Reject is enabled.
- **R6. Pacing:** one shared per-lane pacer covers submit/modify/cancel/query with CANCEL > REDUCE > MODIFY > QUERY > SUBMIT, FIFO within kind. Reserve protection capacity, recheck admission/session at send, and back off on 429. RiskEngine denies excess rather than queues, charges one list token for N messages and does not throttle cancels; its maximum-one-second-release backstop plus headroom is separate.
- **R7. Data and capital:** Alpaca data REST is per owner, 200/minute Basic or 10,000/minute Algo Trader Plus, separate from C's trading bucket. Algo Trader Plus is $99/month list and owner-confirmed $0 billed at the source; that benefit is separate from live trading-rate entitlement. Databento was dropped as a primary, so its name in older IB configs proves no purchase. Paper full-cap utilization comes through breadth, not churn; it never raises broker limits.

## Evidence
| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| R1, R4, R6, R7 | northstar@b384d298d217:docs/decisions/0019-execution-topology-lanes-throughput.md, Context, 2026-10-23 (2), Finalized picks and 2026-11-05 kept corrections | Wire-accounting convergence; IBKR request pacing and Alpaca API docs; GPT register/DeepSeek correction |
| R2–R5 | northstar@b384d298d217:docs/decisions/0022-execution-profile-24x5-leverage-throughput.md, §3–6, support reply and Finalized register | Alpaca support relayed 2026-10-19; IBKR pacing/OER sources search-indexed after 403; 2026-11-05 review leaves numeric OER/working-order/active-order vendor limits **unverified** |
| R2–R4 | northstar-trading@8256c16c31dc:configs/lanes.yaml, paper C/IBKR/live; northstar-lanes@00203275944a:configs/lanes.yaml, all lanes | Exact configuration, including C reserve and conditional live raise; config is not a broker-capability receipt |
| R6 | northstar-trading@8256c16c31dc:docs/adr/0006-risk-guard-and-pacing-in-our-layer.md, decisions 3/12 and 2026-10-29 acceptance | Nautilus rc7 risk source; existing lane pacer and maximum-release backstop; native reconciliation/emulator coverage remains **unverified** |
| R7 | northstar-trading@8256c16c31dc:docs/adr/0003-north-star-data-stack-final.md, table, top-100 path and paper reconciliation | GPT/Gemini/Claude data convergence; market-data API distinction; owner-confirmed ATP billing |
| R7 | northstar-trading@8256c16c31dc:docs/adr/0004-paper-capacity-policy-2026-10-26.md, Finalized pick and decision 1 | Owner 2026-10-26 utilization direction; later observation/sizing successors, no broker-limit waiver |

## Changes for Sextant
- COMMON.md, owner 2026-11-05/06, verbatim: "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"
- COMMON.md, owner 2026-11-05/06, verbatim: "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"
- BRIEF-B.md requires the exact limits above and `lanes/limits.yaml`; it introduces no new rate mechanism or broker entitlement.

## Code and config to carry
- northstar-trading: configs/lanes.yaml@8256c16c31dc — 166 lines.
- northstar-lanes: configs/lanes.yaml@00203275944a — 46 lines.
- northstar-trading: src/northstar_trading/execution/pacer.py@8256c16c31dc — 205 lines; src/nautilus_alpaca/pacing.py@8256c16c31dc — 259 lines.

## Disagreements
- C is 180 in lanes config versus 150 + 50 reserve in trading; retain the explicit reserve and list both sources in the YAML comment.
- Live is 1000/870 in lanes versus 200/180 in trading. The newest owner ruling keeps 1000 as the limit; the support/account conflict and written-raise condition stay unresolved, with the older fallback recorded.
- The superseded IBKR 2700/minute table loses to the accepted 40/s all-request amendment. The earlier aggregate-paper 3000 target is not the newest per-IBKR-paper/live owner limit. The configured 15 working orders/side/contract stays; the proposed vendor correction to 20 was not kept, and vendor numeric limits remain **unverified**.
- Trading config names IB data; lanes names Databento. Preserve the conditional 30/s field and do not infer a Databento purchase or completed rotation-pacer integration.

## Revisit when
M1/M4 or accounted throughput evidence lands; written account/plan/FIX/window/Booster/OER answers arrive; broker pacing/session rules or native release/pacer coverage changes; accepted budgets or paper-guard/live-limit policy changes; or "multi-model verdict, next version" arrives. The execution lead records the evidence and proposes an amendment; measurement alone never raises a cap.
