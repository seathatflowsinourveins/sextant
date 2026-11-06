# ADR-0012: Use one skfolio allocator with causal inputs and keep overlap leverage off

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0010-portfolio-construction-and-leverage.md
- **Harvested from:** northstar-trading@8256c16c31dc:src/northstar_trading/portfolio/
- **Harvested from:** northstar@b384d298d217:docs/decisions/0016-L15-trading-stack.md
- **Harvested from:** northstar-trading@8256c16c31dc:configs/lanes.yaml

## Context
Allocate across trading arms without a second optimizer, duplicated evidence votes or leverage feedback.
Allocation research and portfolio proposals stay outside order authority; paper and live retain their own sizing and admission rules.

## Decision
- **P1.** Keep skfolio as the one allocator: HRP with Ledoit–Wolf covariance is the paper composition. Riskfolio-Lib, PyPortfolioOpt, fortitudo-tech and other duplicates are NO-FIT absent a concrete missing capability and matched comparison. Licence is a fact, not a substitute for fit evidence.
- **P2.** Preserve pin history: main inspected skfolio 1.9.6; paper/parity target 1.12.2. The 1.9.6 stationary bootstrap mutates NumPy global RNG; upstream 1.12.1 fixes it. Existing fixed-matrix qualification compares finite weights, constraints, unchanged global RNG, resource use and rollback. Source/tag identity is not installation or a passed qualification.
- **P3.** Research HRP, NCO, scenario CVaR, DRO-CVaR, entropy-pooled views and fractional Kelly inside skfolio. NCO `cv=None` is five-fold KFold; explicitly supply purged chronological splits and untouched outer evaluation. The engine stack keeps chronological walk-forward, CPCV diagnostics and DSR/PBO/trial accounting outside orders; statistical equivalence is **unverified**.
- **P4.** Reject the outside four-pillar sigmoid uplift. Count each independent catalyst family once; price/volume features do not vote. `tier_enabled=False` until matched-total-risk family-by-family ablation shows independent after-cost information. Its contract ends with two-detector replay, 24/7 sim and recorded paper fills in one trial ledger, then its own enabling amendment. Detector source presence is not caller wiring or adoption.
- **P5.** The existing allocator is an offline session-boundary adapter, with no orders, hidden scheduler or broker reads. Build returns from hashed arm ledgers and exact start-period capital; never treat cumulative dollars as percentage returns, double-subtract costs, zero-fill missing observations or mix incomplete accounting days. Sum simultaneous arm returns before compounding periods.
- **P6.** Existing code uses completed daily paper history for mature arms (charter threshold 20 sessions), SIP minute-derived daily priors for cold arms and one joint covariance across sleeves; it never invents zero cross-correlation. Retired arms get zero budget. Apply the receiving account's monetary capacity, preserve Decimal money, report clips/unallocated capital/risk contributions, and publish one atomic generation. A reader rejects a stale/malformed/unknown generation. This callable does not prove runtime adoption.
- **P7.** Keep equal-notional interim sizing, momentum-profile fixed-risk sizing and the OFF-by-default sizing challenger as distinct source paths; their presence does not activate allocator budgets. Pure rotation/re-entry helpers submit nothing: rotation stays OFF absent its profile/caller controls. New policy must earn causal replay/sim/paper evidence; no optimizer result changes custody, config or orders itself.
- **P8.** Live leverage requires the owner's explicit yes on concrete limits under the full live stages; advertised 4×/2× buying power is not entitlement or permission. FINRA's effective 2026-06-04/phase-in-to-2027-10-20 rule allows firms to retain PDT during transition; the $2000 minimum remains. Intraday maintenance/account migration and paper-simulator behavior stay **unverified**; the source's 30% long-share-above-$6 table is overnight, not a universal intraday rate.

## Evidence
| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| P1–P4, P8 | northstar-trading@8256c16c31dc:docs/adr/0010-portfolio-construction-and-leverage.md, decisions 1–6 and Finalized register | GPT/Gemini portfolio convergence; three-family regulatory checks; skfolio v1.12.1 changelog; SEC Release 34-105226/FINRA RN 26-10; DeepSeek 2026-11-05 confirmation |
| P4 | northstar-trading@8256c16c31dc:docs/adr/0010-portfolio-construction-and-leverage.md, 2026-11-03 ablation amendment | Lead's unchanged matched-risk rule and incentive-overlap contract; replay/sim/recorded-fill evidence before enabling |
| P5, P6 | northstar-trading@8256c16c31dc:src/northstar_trading/portfolio/allocator.py, lines 1–9, 129–268, 394–731 | skfolio 1.12.2 HRP/RiskBudgeting/MeanRisk/EmpiricalPrior/LedoitWolf/attribution APIs; Harvey et al. (2018), doi:10.3905/jpm.2018.45.1.014; inspected offline implementation, not an executed result |
| P6 charter threshold | northstar-trading@8256c16c31dc:configs/lanes.yaml, each charter's cold_start | Existing `arm_prior_after_sessions: 20` and SIP minute-return prior; these are source settings, not newly calibrated numbers |
| P7 | northstar-trading@8256c16c31dc:src/northstar_trading/portfolio/interim_size.py; src/northstar_trading/portfolio/sizing.py; src/northstar_trading/portfolio/challenger.py; src/northstar_trading/portfolio/rotation.py | Cited temporary lead policy, Nautilus rc7 FixedRiskSizer, Zarattini et al. (2024), SSRN 4729284, Jegadeesh/Titman (1993); pure proposals and default-OFF dispatch |
| P3 and authority boundary | northstar@b384d298d217:docs/decisions/0016-L15-trading-stack.md, 2026-10-24 pick and Finalized disposition | Official Nautilus adapters/templates, skfolio/purgedcv/arch libraries, research-artifact roles; no second production engine or order authority |

## Changes for Sextant
- COMMON.md, owner 2026-11-05/06, verbatim: "FOCUING ON US EQUALITY, OPTION,STOCKS ETC, AND ALL THE LANES PREVIOSU STATED, PHILOSOPY PREVIOUS STATED, JEV TRADE RELATED RPEOS ETC ,RESEARCH LANE ,AUTO LEVERAGE, PROTFOLIO MANGEMENT AND BEYOND"
- COMMON.md, owner 2026-11-05/06, verbatim: "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"
- Approved plan, "The full ecosystem": Sextant targets skfolio 1.12.5. The source record identifies its peeled source commit `0db206ed812622088cbd33af2e34a0f4762fa71e` separately from annotated tag object `60e14d1a0348542b9abad15084672eb19314713c`. This changes the target pin only; installation/compatibility/results remain **unverified**. No library or code is copied here.

## Code and config to carry
All below are northstar-trading paths; the whole directory was read at the pin.
- src/northstar_trading/portfolio/__init__.py@8256c16c31dc — 1 line.
- src/northstar_trading/portfolio/allocator.py@8256c16c31dc — 731 lines.
- src/northstar_trading/portfolio/challenger.py@8256c16c31dc — 232 lines.
- src/northstar_trading/portfolio/interim_size.py@8256c16c31dc — 217 lines.
- src/northstar_trading/portfolio/profiles.py@8256c16c31dc — 214 lines.
- src/northstar_trading/portfolio/rotation.py@8256c16c31dc — 115 lines.
- src/northstar_trading/portfolio/sizing.py@8256c16c31dc — 180 lines.
- src/northstar_trading/portfolio/sizing_adoption.py@8256c16c31dc — 284 lines.

## Disagreements
The old allocator's volatility-target leverage output is not permission to enable the refused adaptive guard estimator. Its ≤2× post-market broker bound is not the later sizing-policy ≤1× outside-RTH ceiling or evidence of universal enforcement. Main/paper pins differ; the approved plan's 1.12.5 target does not supply the missing parity/runtime result. The 2026-11-01 source amendment corrects older "proposed" paper-utilization wording to accepted policy without claiming deployment.

## Revisit when
Pin/RNG/fixed-fixture qualification or chronological after-cost allocator/Kelly evidence arrives; matched-risk overlap ablation reports; a concrete missing capability is evidenced; broker margin/migration or simulator observations change; causal adaptive evidence or owner's concrete live-limit decision arrives; a relevant dependency/regulatory contract changes or a margin deficit occurs; or "multi-model verdict, next version" arrives. The allocator/research/execution owner records evidence and amends the owning decision.
