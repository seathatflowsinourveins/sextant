# ADR-0025: Protect earned gains and test every fast-exit policy against holding

- **Status:** accepted. Harvested; the decision is unchanged unless “Changes for Sextant” says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-10-29-b-exit-replay.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-10-29-exit-manager.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-10-23-qfk33-emulated-trailing-activation.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-11-02-pmg-trail-c5.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-11-02-pmg-trail-c5-r3.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-11-03-b-gain-protection-replay.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0019-managed-exits-and-ranked-reentry.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0015-owner-entry-paper-exit-manager.md
- **Harvested from:** northstar-trading@8256c16c31dc:deployments/exit-manager.paper.json
- **Harvested from:** northstar-lanes@00203275944a:docs/adr/0006-exit-engine.md
- **Harvested from:** northstar-lanes@00203275944a:docs/adr/0003-philosophy-and-operating-principles.md

## Context
The owner's tight-exit requirement and the economics are separate facts. [ADR-0024](0024-extreme-mover-ranking-and-early-entry.md) carries the newest extreme-mover ruling verbatim; the [evidence note](../research/2026-11-06-extreme-mover-evidence.md) preserves the negative replays.
**2026-11-06 clarification (#54):** XR29's control holds each entered position to **15:55 ET**; call it **hold-to-15:55**, distinct from the zero-position hold-flat/no-trade control. This corrects terminology, not the protection policy or the negative comparison.

## Decision
- **Managed trigger, X2–X3:** `buffer=max(one_tick, eligible_spread, prearm_buffer_fraction×entry, prearm_range_multiple×R_w)`; before arming, `trail=max(buffer, setup_gap)`. With eligible running high H, `gain_lock=max(entry+c_RT, H-max(noise_floor, g×(H-entry)))`, where `noise_floor=max(one_tick, eligible_spread)`. `R_w` is the eligible-trade range over the configured window; `setup_gap=entry-initial_trigger` comes from the setup. The trigger is `max(previous_trigger, H-trail, gain_lock if armed)`; it never loosens. Chandelier is a counterfactual in this lanes policy, not another trigger term.
- **First non-noise sell:** X4 requires consecutive eligible observations at/below the trigger for the registry's `breach_persist_count` and `breach_persist_span_s`; rebound resets. Use bids in RTH and eligible trades outside. Gain-lock arming needs both confirmation at `entry+c_RT+noise_floor` (default: a completed 1-minute close at/above it; alternative: the configured qualifying trade run) and an executable price strictly above the proposed armed trigger. A lone quote/print is insufficient. Earlier flow, VWAP and structure exits remain candidate arms until their formula, persistence and replay earn adoption.
- **Dynamic LIMIT:** X5 amends the owned managed sell, `limit=max(bid,last×(1-chase_cap_fraction))`, with bounded repricing, serialized acknowledgements and protection-first pacing. Halt/close has its separate authority. Finite take-profits roll upward with H, never downward; `take_profit_above_h_fraction > take_profit_step_fraction`. Desired, sent and acknowledged levels differ: a pending roll can cap a runner. Fixed-at-entry targets are counterfactual only.
- **Backstop and custody:** X6's separate venue protection is never a second full-size competing exit. A cap or trigger is not a realized-loss guarantee; gaps, nonfills and asynchronous handovers remain. B's later amendments specifically allow rc7 BID_ASK trailing stop-limits outside RTH, superseding the older IBKR-only emulation wording for B. An unactivated emulated order reserves quantity but is not executable protection.
- **B's scoped policy:** the November 3/5 owner-entry record keeps C5/gain-lock as the comparison baseline, a 0.025 cap, and the tight policy class. Its later RTH option B cancels the native trail, awaits ACK, sends one collared/chased LIMIT and re-arms unfilled residual shares. Outside RTH it selects the upstream emulated trailing stop-limit; the node and feed must remain available. Owner reservations remain owner-owned. Policy acceptance does not prove installation or continuous protection.
- **Expected fill, not trigger:** B's protective level includes entry plus expected spread, size/session slippage and fees. The PLTG witness was 5,555 shares bought at 16.47, native-trail HWM 16.92 and stop 16.497, filled 16.36: −611.05 USD gross. TCA sets the cost rows; a stop above entry did not prevent a losing fill.
- **What was tested:** the October study searched 96 combinations of 1/5-minute Chandelier, ATR14/22, multipliers 2/2.5/3, momentum/VWAP trigger sets and overlay on/off, at 3/6 bps per side. It also tested active PATCH, cancel→market, resting-stop execution, four entry-spread filters and three spread-width floors. These are minute-bar studies, not tick execution or confirmatory merit. f=0.25 and m=3 remained provisional; their combination was not tested.
- **Later evidence:** November 3 compares bounded C5, 100-bp monotone ratchet, Wilder SAR, halt-aware C5 and illustrative published tiers with a separate 3% reference. There are zero qualified cost-calibrated tick opportunities. All six minute approximations tie negatively; no winner or runner-up is supported and the research arms remain OFF. PMG native protection/partial-fill/route tests and callback benchmarks verify mechanisms, not an after-cost advantage.

## Evidence
| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| Trigger, arming, persisted breach and dynamic limit | northstar-lanes@00203275944a:docs/adr/0006-exit-engine.md, X2–X7 and November 3 fold | Owner rulings; secure-gains GPT/Google convergence; NautilusTrader 2.0.0rc7 modify/OCO seams; all parameters UNCALIBRATED |
| Negative holding comparison and unknown economics | northstar-trading@8256c16c31dc:docs/research/2026-10-29-b-exit-replay.md, §§1–3/r2; northstar-lanes@00203275944a:docs/adr/0003-philosophy-and-operating-principles.md, Confidence | 1,025 paired entries: holding to 15:55 beat every active-exit variant. The separate philosophy's no-trade control and unknown full-policy economics remain unchanged. |
| B exceptions, fill-cost target and gaps | northstar-trading@8256c16c31dc:docs/adr/0015-owner-entry-paper-exit-manager.md, November 3 (2)–(4), November 5 owner pointer | Owner/lead rulings; measured PLTG failure; scoped upstream OrderEmulator and Alpaca order semantics |
| Native release and PMG tests | northstar-trading@8256c16c31dc:docs/research/2026-10-23-qfk33-emulated-trailing-activation.md, six-case output; 2026-11-02-pmg-trail-c5.md, protection first; 2026-11-02-pmg-trail-c5-r3.md, handovers | NautilusTrader 2.0.0rc7 native-stub tests; Chandelier reference as read in source; no broker-fill guarantee |
| Later stricter-gain variants | northstar-trading@8256c16c31dc:docs/research/2026-11-03-b-gain-protection-replay.md, §§1/3/7 | Actual ExitManager/native matching; Wilder SAR (1978); vendor tiers explicitly secondary; 2 minute opportunities, qualified tick n=0, NOT ESTIMABLE |
| Current moved-policy scope | northstar-trading@8256c16c31dc:docs/adr/0019-managed-exits-and-ranked-reentry.md, Finalized and November 5 verdict | Moved lanes policy and B's separate scope; DeepSeek confirmation of the negative replay, not new alpha evidence |

## Changes for Sextant
Harvest the policies and negative evidence; the approved plan's Phases 2–3/5 require sim evidence and no broker handover here. COMMON.md's newest owner rulings (2026-11-05/06), verbatim:
> "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"
> "FOCUING ON US EQUALITY, OPTION,STOCKS ETC, AND ALL THE LANES PREVIOSU STATED, PHILOSOPY PREVIOUS STATED, JEV TRADE RELATED RPEOS ETC ,RESEARCH LANE ,AUTO LEVERAGE, PROTFOLIO MANGEMENT AND BEYOND"
> "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"
> "we need to using full sota harness framework.dsh that is fully enhanced with openviking etc"

## Code and config to carry
- northstar-trading@8256c16c31dc:src/northstar_trading/strategies — 123 files, 31,828 lines as an inventory, not a wholesale import.
- northstar-trading@8256c16c31dc:src/northstar_trading/strategies/exit_manager — 10 files, 4,929 lines; `strategy.py` 2,285, `protection.py` 804, `rules.py` 92, `signals.py` 114.
- northstar-trading@8256c16c31dc:src/northstar_trading/strategies/premarket_gap/exits.py — 144 lines; src/northstar_trading/strategies/exits/active.py — 674 lines. [ADR-0024](0024-extreme-mover-ranking-and-early-entry.md) inventories the other PMG files. Copy no code.

## Disagreements
- **Owner requirement versus measured returns:** the newest rule requires tested strict trails or dynamic limit sells and fast sale on the first non-noise selling. Hold-to-15:55 beat **every one of 96 active variants**: **+76.44 versus +54.78 bps/trade** at 3 bps/side, **+70.42 versus +48.76** at 6. The overlay lost **38.09 bps/trade**. Both the requirement and the negative result stand; no finding proves the requested policy profitable.
- B's C5 comparison baseline and its later native/emulated handovers are scoped exceptions, not a replacement of lanes X2–X4. Option B has two unbounded outage intervals: no resting exit between cancel ACK and LIMIT acceptance, then an unchased LIMIT until fill/reconciliation. Its two kill-point witnesses remain **unverified** in the ADR.
- The pinned B deployment still has 24 rows at `backstop_start_fraction="0.03"` with hazard on; the newer ruling caps B at 0.025 and the source warns current config refuses above-cap starts. Do not treat those rows, or the lone-quote hazard, as proof of compliant persisted fast exit. The November 5 correction attributes IONQ's raises to the owner, not the manager.

## Revisit when
- A qualified tighter-exit/hold-flat/re-entry result, paper fill-against-stop or TCA cost calibration lands: research and the lane record the winner, negative or inconclusive result in the trial ledger and amend the policy.
- A protection gap, option-B kill-point/session receipt, cap/hazard correction, governing upstream change or “multi-model verdict, next version” appears: the custodian and lead revisit the affected mechanism, preserving the one-exit and owner-order rules.
