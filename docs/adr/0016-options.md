# ADR-0016: Research US equity options in a zero-weight factor and sim before admitting orders

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0016-momentum-rotation-philosophy-and-lane-profiles.md, whole record including every amendment.
- **Harvested from:** sextant@db326993b58b:docs/research/2026-11-05-foundations-convergence.md, J6.
- **Other inputs:** approved `/home/choreo/Developer/sextant/.superpowers/sdd/sextant-plan/plan.md`, Options row and Phase 5; supplied `COMMON.md`, owner rulings of 2026-11-05/06.

## Context
US equity options belong in Sextant's research and sim scope. Access to options data, an advisory skill and a simulator's option instruments each establish different capabilities; none establishes account permission or options-order admission [O1–O5].

## Decision
- The harvested KEEP decision leaves orders in option contracts unadmitted on every old lane, paper included. Options data may remain a zero-weight research factor, with no rank, entry, exit, size or leverage influence [O1].
- New factors earn weight only through measured point-in-time lift intervals excluding zero. OPRA activity/skew is not Pan–Poteshman's buyer-to-open flow dataset; no transferable option strategy or numerical admission bound was supplied [O1, O2].
- Sextant carries the approved design ADR, zero-weight factor and sim scope. An option order still needs a later admission ADR and the account's options level [O3].
- The recorded admission event is a published method or upstream template with pinned rules, plus a guard amendment naming premium at risk, Greeks, assignment and margin. The historical rule's owning home is lanes ADR-0003 P10. This harvest does not replace that requirement with a new path [O4].
- Separate non-order account evidence from order evidence: configured level, account options fields and OPRA authentication can be checked first; paper option acceptance, position margin, NTAs and expiry reconciliation come only after admission [O4].
- rc7 supplies option instruments, Greeks/chains and simulated expiry settlement. ITM longs and shorts settle by physical delivery, or cash for index underlyings; OTM contracts expire. Its inspected expiry path lacks early exercise/assignment, DNE instructions and buying-power/share-capacity checks [O5].
- `options-strategy-advisor` is the converged options skill reference. It supplies no account entitlement, measured edge or order authority [O6].

## Evidence
| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| O1: KEEP and zero influence | northstar-trading@8256c16c31dc:docs/adr/0016-momentum-rotation-philosophy-and-lane-profiles.md, 2026-11-04 options amendment, lines 230–240; E1 at 1028 | Existing policy; GPT leg, Claude/GPT syntheses and source reconciliation; DeepSeek agreement has unconfirmed-effort caveat. |
| O2: flow is not an admitted method | Same record, lines 241–245 and 1183 | Pan & Poteshman (2006), DOI 10.1093/rfs/hhj024, informed opening volume; publicly observable effect reverses after one or two trade days. |
| O3: Sextant scope and orders | Approved plan, lines 168–169, 195–198 | Owner-approved override: design ADR, zero-weight factor and sim; later ADR plus options level for orders; live retains its separate full admission decision. |
| O4: admission and evidence ordering | northstar-trading@8256c16c31dc:docs/adr/0016-momentum-rotation-philosophy-and-lane-profiles.md, E17–E19, lines 278–284 | Account fields in alpaca-py v0.44.0; sourced candidate and premium/Greeks/assignment/margin guard requirement; no option-order evidence before admission. |
| O5: engine and broker contracts | Same record, lines 246–265, 302–305 | nautechsystems/nautilus_trader v2.0.0rc7 (`55c0e82053142bce3a5cba4de4221d3929c2d3bc`), `crates/execution/src/matching_engine/settlement.rs` and `examples/backtest/notebooks/databento_option_exercise.py`; Alpaca/IBKR pages read 2026-11-04 by the reconciler. |
| O6: skills | sextant@db326993b58b:docs/research/2026-11-05-foundations-convergence.md, J5/J6 and final limitations | GPT/DeepSeek converge on `options-strategy-advisor` from tradermonty/claude-trading-skills at `d8e71ce2f0b069eb5b6fca352857c168c35e6c46`; no trading result verified. |

## Changes for Sextant
The approved plan adds the options design/sim work to Sextant. It does not carry the old blanket exclusion into that design scope, and it does not admit broker orders [O3]. The newest owner rulings are requirements, verbatim from supplied `COMMON.md` (2026-11-05/06):
- "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"
- "FOCUING ON US EQUALITY, OPTION,STOCKS ETC, AND ALL THE LANES PREVIOSU STATED, PHILOSOPY PREVIOUS STATED, JEV TRADE RELATED RPEOS ETC ,RESEARCH LANE ,AUTO LEVERAGE, PROTFOLIO MANGEMENT AND BEYOND"
- "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"
The quoted rates remain the owner's stated limits; this record supplies no options-specific rate, account permission or guard calibration.

## Code and config to carry
None for option orders: the harvested record says the house adapter, deployment check and guards are equity-only (lines 238–240). Shared OPRA/data and scanner carry paths belong to [ADR-0013](0013-us-equity-data-stack.md) and [ADR-0014](0014-features-and-regime-models.md). No code is copied here.

## Disagreements
- OPRA entitlement is "in use … entitlement measured" in the data record but UNVERIFIED in the options pack; neither receipt was readable there. The latest dsh re-check also leaves the internal entitlement probe unverified (source lines 8, 268–280). Feed access is not order admission.
- alpaca-py v0.44.0's docstring says options TIF `day`; the reconciler's Alpaca validation read allows `day` or `gtc`. Preserve the conflict (source line 272); no automatic widening.
- Engine expiry settlement and broker-paper NTAs are distinct evidence; their actual divergence, house levels, paper acceptance, options margin and IB Greeks stream remain **unverified**. The latest dsh re-check also marks "next-day paper NTAs" **unverified** (source lines 8, 240, 264–273).

## Revisit when
- E17: non-order account level/options fields or OPRA authentication evidence arrives; data/venue owners reconcile it and amend the record.
- E19: a sourced bounded candidate and the named guard amendment arrive; the architecture lead conducts the recorded convergence and admission amendment before E18's option-order evidence.
- E20: a later Nautilus release changes expiry, early exercise/assignment, DNE or IB exercise submission, or measured broker-paper settlement diverges; venue owner reviews and amends.
- E06/E07/M1: vendor validation/levels or SDK option enums change, the owner rules on options trading, or "multi-model verdict, next version" arrives; the owning lead re-reads the evidence and amends.
