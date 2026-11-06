# ADR-0011: Keep incumbent sizing and test auto-leverage only on independent trading evidence

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-lanes@00203275944a:docs/adr/0011-sizing-and-leverage.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0010-portfolio-construction-and-leverage.md
- **Harvested from:** northstar@b384d298d217:docs/decisions/0022-execution-profile-24x5-leverage-throughput.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0006-risk-guard-and-pacing-in-our-layer.md

## Context
Leverage creates no edge. Halting small-cap movers need planned-risk, funding and gap evidence before a sizing challenger replaces the incumbent.
Paper continues its incumbent experiment; live limits remain separately approved concrete numbers.

## Decision
- **S1.** Keep full-portfolio equal-planned-risk `FixedRiskSizer` sizing, bounded by fresh uncommitted buying power and flow share. The challenger never vetoes the incumbent. Use net per-trade R = P&L / original planned risk for edge; volatility/gap inputs are per dollar of notional, never levered account returns. Record effective leverage `ΣN/E` as an output, never an input.
- **S2.** Challenger entry notional is the smallest of `E × r_cell × m_conf × m_stopout × λ_dd / δ`, fresh uncommitted buying power, `φ × V`, and per-name `θ × B / G`. Hold `ΣN × G ≤ B` and `ΣN ≤ L_ceiling × E`; `G ≥ δ`. Buying power is incremental dollars: never subtract held gross twice or subtract a call-rate reserve from dollars.
- **S3.** `r_cell = c × r* / (1 + (k̄ − 1) × ρ̄)`, `ρ̄ ≥0`; `r* = argmax_r mean(log(1 + r × R))` on out-of-sample R at 2× costs. `c = max(0, 1 − 1/t_D²)`. `λ_dd = clip((E − α × HWM) / ((1 − α) × E), 0, 1)` and `B = E − α × HWM`; α=0.85 is **unverified** as calibrated. The economic HWM never resets through operational recovery. One-sided volatility/regime terms join only after their ablations pass.
- **S4.** A cell is arm × price band × session: MEASURED needs ≥30 independent round trips, ≥5 sessions and `t_D >1`; NEGATIVE means `t_D ≤−1`; otherwise UNMEASURED. Without a MEASURED cell and measured G, the challenger records insufficient and sizes nothing. φ, θ, α, G and regime calibration remain **unverified**. The source's negative-edge cell grants no leverage uplift.
- **S5.** Each order fits fresh broker/session buying power and per-security margin; a tier never creates entitlement. Whole-book capacity is separately bounded by the guard and policy output. Legacy paper policy is fixed ≤2×, with session target ≤1× from ten minutes before the actual close, early closes included, and outside RTH. At configured ≤2× that session row observes; above 2× it enforces the ≤1× ceiling and managed exit clock. Do not claim universal paper enforcement.
- **S6.** Compare A0 fixed 1×, A1 incumbent, A2 full challenger, A3 without regime, A4 replacing c with κ=0.25, A5 capacity+gap only, A6 fixed 2× RTH/1× otherwise; historical-max and p99 gaps give 14 trials. Every later variant enters the cumulative trial ledger. Frozen-entry replay excludes/reports funding-divergent or funding-unverified sessions; the modeled P&L difference resets each session. Adoption needs event replay recomputing funding and rotation.
- **S7.** Per-cell adoption at 2× costs requires dependence-aware lower 95% paired per-session log-growth lift >0 against A1 and A0, plus >0 against hold-flat in every traded cell. Use circular whole-session blocks and the frozen block length; A2–A6 form one StepM family on common support, with insufficient `pbo_min_sessions` INCONCLUSIVE. Keep DSR >0.95, PBO ≤0.05 (CSCV S=16), PSR ≥0.95, the sample floors, and no realized name/book event loss beyond θB/B. Otherwise keep the incumbent and the negative result.
- **S8.** Policy de-levering reduces new entries, never forces sales; the guard's session action remains separate. Halt/LULD status, session change, stop loss, edge decay, regime, buying power or unknown input reduces sizing; no unknown numeric LULD band is invented. The kill switch is untouched and a release never resets sizing upward.
- **S9.** Fixed guard mode recomputes `min(configured, L_dd, L_broker)` each check; paper observation omits applied L_dd while reporting it. Recovery counts cushion below 0.25 and re-anchors only when `zero_days > dd_reset_days` (default 5 trading days); that operational recovery never resets S3's economic HWM. Its calibration is **unverified**. Adaptive estimator modes remain refused. Live stays 1× until the full live gates and owner's concrete above-1× numbers exist; no reasoning-only Kelly adoption.

## Evidence
| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| S1–S8 | northstar-lanes@00203275944a:docs/adr/0011-sizing-and-leverage.md, Requirements, S1–S8, Evidence and 2026-11-05 correction | Independent GPT/Claude auto-leverage convergence; Kelly and Grossman–Zhou published methods; Nautilus rc7 FixedRiskSizer; arch v8.0.0 StepM; later DeepSeek check |
| S5, S9 | northstar-trading@8256c16c31dc:docs/adr/0010-portfolio-construction-and-leverage.md, decisions 5/6 and Finalized register | Owner 2026-10-28 concrete-live-limit requirement; fixed paper/live distinction; empirical adaptive evidence still absent |
| S9 and configured 4× distinction | northstar-trading@8256c16c31dc:docs/adr/0006-risk-guard-and-pacing-in-our-layer.md, 2026-10-29 acceptance, decisions 17–19 and `y2p.34` amendment | Fixed-mode/recovery implementation; owner-authorized paper exception; explicit implementation-versus-acceptance limit and native account-evidence conditions |
| S9 and historical formula | northstar@b384d298d217:docs/decisions/0022-execution-profile-24x5-leverage-throughput.md, §2 and Finalized current picks | Grossman–Zhou (1993), NBER w22208, Cederburg et al., Liu/Tang/Zhou, Barroso/Detzel (2021); later project sizing policy supersedes architectural intent |

## Changes for Sextant
- COMMON.md, owner 2026-11-05/06, verbatim: "FOCUING ON US EQUALITY, OPTION,STOCKS ETC, AND ALL THE LANES PREVIOSU STATED, PHILOSOPY PREVIOUS STATED, JEV TRADE RELATED RPEOS ETC ,RESEARCH LANE ,AUTO LEVERAGE, PROTFOLIO MANGEMENT AND BEYOND"
- COMMON.md, owner 2026-11-05/06, verbatim: "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"
- No new threshold or fitted parameter. The approved plan preserves sim-first work, the cumulative trial ledger and live-stage gates.

## Code and config to carry
All are northstar-trading paths at the pin; source presence is not adoption.
- src/northstar_trading/risk/leverage.py@8256c16c31dc — 482 lines.
- src/northstar_trading/portfolio/challenger.py@8256c16c31dc — 232 lines.
- src/northstar_trading/portfolio/sizing_adoption.py@8256c16c31dc — 284 lines.
- src/northstar_trading/portfolio/sizing.py@8256c16c31dc — 180 lines.
- src/northstar_trading/portfolio/profiles.py@8256c16c31dc — 214 lines.

## Disagreements
- Harness §2's daily `min(L_vol,L_kelly,L_dd,L_broker)`, rebalance move >0.15 and ≤0.5 shrunk-Kelly term are historical intent; its later Finalized text delegates current policy to the project. They do not supersede S1–S9 or enable adaptive mode.
- Lanes S2/trading allocator policy retain interim effective ≤2×. Paper implementation accepts configured ≤4×: the risk record's `y2p.34` amendment explicitly says implementation is not acceptance/deployment and ≤2× remains until landing/acceptance. That acceptance is **unverified** here. Above 2× implementation needs same-account native evidence aged ≤120 s inclusive, neither timestamp future, multiplier ≥4 and usable buying power; outside RTH ≤1× and a full flatten five minutes before actual RTH close (15:55 normally, 12:55 on a 13:00 close). These implementation facts do not raise today's accepted cap.
- GPT's fixed κ=0.25 survives only as A4; the data-driven shrink is the rule. Gap limits stay challenger-only. DeepSeek's 2026-11-04 volatility-at-1× newcomer does not remove the existing ablation gate.

## Revisit when
S4's replay result, a MEASURED cell/G/calibration or S5 event-replay result arrives; the guard cap/session mode, broker margin or owner live numbers change; causal adaptive evidence or a newcomer meets its named gate; a lesson contradicts this record; or "multi-model verdict, next version" arrives. The sizing/execution lead reviews the evidence and amends the relevant policy.
