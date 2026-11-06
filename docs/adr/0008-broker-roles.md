# ADR-0008: Alpaca executes today; IBKR earns each additional role through paired evidence

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-lanes@00203275944a:docs/adr/0010-broker-roles.md
- **Harvested from:** northstar@b384d298d217:docs/decisions/0019-execution-topology-lanes-throughput.md
- **Harvested from:** northstar@b384d298d217:docs/decisions/0016-L15-trading-stack.md
- **Harvested from:** northstar-trading@8256c16c31dc:configs/lanes.yaml

## Context
US-equity lanes share one engine and keep broker accounts, execution and ownership distinct.
Broker paper compares simulators; it cannot establish live execution quality or entitlement.

## Decision
- **B1.** Alpaca is PRIMARY for current entries, modify/cancel, protection, eligible sessions, easy-to-borrow facts, policy-bounded margin and L1 data. IBKR is a per-function CANDIDATE; depth and TRAIL LIMIT/MIT/LIT/GTD have no Alpaca role. Routing/FIX remains the owner's decision.
- **B2.** At NautilusTrader v2.0.0rc7, IBKR factory brackets/reduce-only and repeated modify cannot carry protection unchanged: #5464 denies reduce-only lists; #5463 allows only the first amend. Emulated trailing stop-limits or native TRAIL/OCA remain candidates pending drills. Exit children attach to the entry; only exit siblings share OCA. Native TRAIL's match to the house backstop is **unverified**.
- **B3.** Use the first-party IBKR adapter. Retain the pinned gnzsnz Gateway 10.50.1f/IBC 3.24.2; ibg-controller v0.16.3 is the accepted qualification target, not a cutover. The separate `nautilus_alpaca` bridge follows the official rc7 Python adapter template and alpaca-py 0.44.0, rather than copying the Rust IB adapter. No qualified upstream Alpaca adapter shipped at the source cut; retire the bridge when one proves the required paper coverage.
- **B4.** Keep three isolated Alpaca paper accounts and IBKR paper; one account has one writer. A/C are the balanced/conservative automated profiles; B keeps owner-entry exit management plus the explicitly scoped focus-aggressive arm. IBKR paper supplies broker-portability evidence. Shared market data does not merge execution ownership. The clean-rebuild target gives A and C their own nodes, like B's exit manager; typed-data delivery under the shared connection budget and protection recovery are **unverified**. Until rebuilt, no shared A/C restart unless both are flat.
- **B5.** Replay is MODELED; sandbox-on-feed is SIMULATED; Alpaca and IBKR paper are BROKER-PAPER. Paired same-symbol/side/second/notional evidence alternates send order and measures each actual book. Neither paper simulator proves live routing, borrow fees/locates, margin entitlement or live limits; those remain **unverified**.
- **B6.** Paper targets 24/5; replay/sim supports 24/7 research. Nautilus rc7 remains the research/paper engine. Actual venue/session/protection eligibility still binds. Live is a separate promoted path governed by the full live-lane decision and its stage/version precedence; the approved plan retains 2.0 final for Stage 2. Broker roles confer no live authority.
- **B7.** Listed sub-$1 prices work through Alpaca; IBKR's static rc7 tick ladder has no such role. Other listing mappings remain candidates (TXSE code **unverified**); OTC has no role without an owner-approved source. Numeric LULD bands have no role at this pin.

## Evidence
| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| B1, B2, B5, B7 | northstar-lanes@00203275944a:docs/adr/0010-broker-roles.md, B1–B4 and Confirmation | GPT/Claude broker convergence; DeepSeek 2026-11-05 confirmation; Nautilus rc7 issues #5463/#5464, IBKR OCA/bracket docs and both paper-model docs, read 2026-10-31 |
| B3 | northstar@b384d298d217:docs/decisions/0016-L15-trading-stack.md, 2026-10-23/24 picks and 2026-11-05 amendments | Official `docs/developer_guide/python_adapters.md`, `examples/live/_template`, alpaca-py v0.44.0; RFC #3374; GPT research with Claude review, later DeepSeek source check |
| B3 Gateway, B4 | northstar@b384d298d217:docs/decisions/0019-execution-topology-lanes-throughput.md, Finalized picks and 2026-11-02 amendment | Accepted controller qualification target and retained incumbent; lead custody ruling 2026-11-02; rc7 instrument-keyed external claims; Alpaca subscription-dependent connection limits, read 2026-11-02 |
| B4 lane roles | northstar-trading@8256c16c31dc:configs/lanes.yaml, roles and charters | Exact paper A/B/C and IBKR role declarations; no deployment or custody receipt inferred |
| B6 | northstar@b384d298d217:docs/decisions/0019-execution-topology-lanes-throughput.md, 24/5 amendment; docs/decisions/0016-L15-trading-stack.md, Finalized disposition | Owner 2026-10-23 session direction; GPT design/Claude cross-check; project-owned live-stage precedence |

## Changes for Sextant
- COMMON.md, owner 2026-11-05/06, verbatim: "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"
- COMMON.md, owner 2026-11-05/06, verbatim: "FOCUING ON US EQUALITY, OPTION,STOCKS ETC, AND ALL THE LANES PREVIOSU STATED, PHILOSOPY PREVIOUS STATED, JEV TRADE RELATED RPEOS ETC ,RESEARCH LANE ,AUTO LEVERAGE, PROTFOLIO MANGEMENT AND BEYOND"
- COMMON.md, owner 2026-11-05/06, verbatim: "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"
- Approved plan, "Your answers" and Phases 6/7: sim first; paper handover stops the old writer and needs owner confirmation. Live retains the full inherited gates, with exact-SHA two-family review replacing the old verdict mechanism. This harvest copies no adapter and hands over no account.

## Code and config to carry
All below are measured at northstar-trading@8256c16c31dc; no code is copied.
- src/nautilus_alpaca/__init__.py@8256c16c31dc — 55 lines.
- src/nautilus_alpaca/common.py@8256c16c31dc — 157 lines.
- src/nautilus_alpaca/config.py@8256c16c31dc — 363 lines.
- src/nautilus_alpaca/data.py@8256c16c31dc — 1260 lines.
- src/nautilus_alpaca/execution.py@8256c16c31dc — 5818 lines.
- src/nautilus_alpaca/factories.py@8256c16c31dc — 441 lines.
- src/nautilus_alpaca/http.py@8256c16c31dc — 211 lines.
- src/nautilus_alpaca/order_reducer.py@8256c16c31dc — 2370 lines.
- src/nautilus_alpaca/pacing.py@8256c16c31dc — 259 lines.
- src/nautilus_alpaca/parsing.py@8256c16c31dc — 1246 lines.
- src/nautilus_alpaca/pricing.py@8256c16c31dc — 118 lines.
- src/nautilus_alpaca/providers.py@8256c16c31dc — 176 lines.
- src/nautilus_alpaca/ranking_data.py@8256c16c31dc — 91 lines.
- src/nautilus_alpaca/screener.py@8256c16c31dc — 104 lines.
- src/nautilus_alpaca/streams.py@8256c16c31dc — 364 lines.

## Disagreements
The original one-node-per-venue topology is narrowed by the 2026-11-02 per-account A/C rebuild target (B4); delivery/restart design remains **unverified**. The broker-role source's long-only paper baseline does not establish the newer owner's options or broader lane scope as executable broker capability. The Gateway register proposed non-use of a new controller; its recorded lead ruling retains the accepted ibg-controller qualification target and leaves that contrary disposition for a next-version reconciliation.

## Revisit when
Paired broker evidence or replay/sandbox calibration lands; a pinned release fixes #5463/#5464 or changes adapter coverage; brokers change rates, simulators or sessions; the owner decides routing/FIX; custody/data/restart evidence changes; a lesson contradicts this decision; or "multi-model verdict, next version" arrives. The relevant execution/research lead reviews evidence and proposes an amendment.
