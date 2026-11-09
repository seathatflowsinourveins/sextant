# Paper C profile derivation: preregistration (#80)

**Status: proposed protocol; NOT_RUN.** This fixes the candidate profiles,
comparisons, metrics and decision rule before results. The execution seal is
unavailable (§6): this document alone cannot run a trial or size C. No profile,
broker connection, stream, order, handover or live permission is approved here.

## 1. Authority and method

The owner asked the lead to propose C's profile from replay and sim, then obtain
owner approval ([#44 decision][owner], carried on [#80][brief]). Full-factor paired
testing in supported 24/5 sessions replaces the conservative profile. A's suggested
1.0% is a hypothesis, not C's default. Whether session-end-minus-five flattening
survives is a question for evidence and the owner. C's leverage tiers remain OFF.

Follow [ADR-0019](../adr/0019-validation-and-merit.md),
[ADR-0018](../adr/0018-evidence-and-learning-loop.md) L3/L9 and
[ADR-0011](../adr/0011-sizing-and-auto-leverage.md) S1/S4/S6/S7: frozen-entry sizing
confirmation, then event replay with recomputed funding and rotation; paired
inference against a reference and hold-flat; one cumulative TrialLog. The upstream
preregistration (§8) supplies the treatment/registration shape. The later L5
protocol governs inference, superseding its withdrawn stationary bootstrap.

## 2. Profiles and controls

Form the Cartesian product below: **24 full-stack profile candidates**. All are
UNCALIBRATED research treatments. Sources justify testing these values, not
deploying them on C. All other registry-backed parameters stay identical.
The table records candidate values/units, source and UNCALIBRATED state; its
declaration date is 2026-11-06. It changes no consuming runtime's registry.

| Axis | Registered alternatives | Source and scope |
|---|---|---|
| Risk per trade | `0.01`, `0.02` (fractions) | ADR-0002 A/B starts; upstream `profiles.yaml` balanced/aggressive. Use incumbent FixedRiskSizer, not a new risk formula. |
| Exposure ceiling | `L0`: fixed 1×; `L6`: fixed 2× RTH, 1× outside RTH | ADR-0011 S6 A0/A6. L6 is a research challenger; C's rank/overlap leverage tiers stay OFF. Fresh broker/session buying power still binds. |
| Target names | `5`, `8`, `10` | ADR-0002 A's five-name profile and upstream `profiles.yaml` aggressive/balanced/conservative `params.max_positions`. Target slots, not permission to evict custody or add a paper count safeguard. |
| Boundary | `F5`: flat by each actual segment end −5 minutes, no carry; `CARRY`: omit that extra five-minute flatten and keep managed exits across supported boundaries | F5 is the superseded C clause in ADR-0002, retained only as a counterfactual. CARRY follows A's carried policy and upstream balanced `carry_tiers: [L]`. Only supported/protected Tier L carry is tested; no Tier S carry is added. |

Keep A/C's carried L/S eligibility, half-risk outside RTH, S half-risk/1×, flow,
liquidity and protection rules fixed. Outside RTH all orders are LIMIT and exposure
is ≤1×. The old C 0.25%, 20-name shape and `rth_only: true` are not fallbacks.

**A reference:** L risk 1%, five target names, rank ceilings 2×/1.5×/1×, outside-RTH
half-risk/≤1× and its carried boundary/carry policy (ADR-0002). Bind its exact
registry/config hash. It is a replay comparator, not C's approved incumbent and
not a change to A's account.

**Controls:** source roles `hold_flat`, `duplicate_incumbent` and `cash`. Each
profile's matched hold-flat uses its frozen entry/notional, held to that entry's
declared segment flat boundary; it never inherits an arm-selected exit clock.
Cash never enters. Duplicate the A reference for the A/A check; unexplained
nonzero lift invalidates interpretation. Seal event-replay control decision
pairing before running. Controls and every repeat enter cumulative N.

Arm IDs identify all four axes, tier, factor mask and cost condition. The exact
finite inventory, including twins and controls, must be registered through #72
before any run. A treatment declaration is not an outcome or trading permission.

## 3. Factor pairs, clocks and support

The full stack is ranking, first leg, extension/reclaim, entry sizing, gain lock,
persistent breach/chase, backstop, take-profit roll, re-entry/rotation and catalyst
screens. Each factor set has a with/without twin with otherwise identical code,
inputs, fill/fee/latency models and random seed, including with/without re-entry.
The seal enumerates exact factor IDs, masks, availability and count. Missing
implementations are explicitly OFF and make a claimed full-stack result
NOT_ESTIMABLE; no stand-in looks present. Hard lines are never ablated. Options
remain zero-weight; Jev retains its separately admitted sim-only scope.

Use recorded catalog data with immutable receipts, dated universe/identities,
corporate actions, native trades/quotes, ranking generations and actual availability
clocks. First-leg/bid-breach claims require ticks/quotes: selected-mover seeds,
retrospective rankings and minute approximations cannot substitute. Key pairing
by `decision_id`; every input must be knowable at that decision.

Freeze the complete eligible cohort and session IDs before outcomes are read.
Cover PRE/RTH/POST/supported overnight, actual early closes and DST through XNYS
and America/New_York. F5 stops new entries at the flat boundary and measures
terminal completion, residuals and missed onsets; cancel ACK or DAY expiry is not
flat. CARRY retains supported funding/feed/protection and marked inventory across
boundaries, without resetting its economic account history.

Frozen-entry screening shares entries and reports funding-divergent/unverified
sessions separately (S6); common-support screening cannot adopt. Event confirmation
recomputes ranking, selection, buying power, partial/nonfills, re-entry and rotation
on the same tape. Retain all attempts/refusals and planned/observed/paired/excluded
denominators with reasons. Missing returns, costs or coverage stay missing, never 0.

## 4. Estimands, costs and reports

**Sizing/exposure primary:** paired per-session log-growth difference against the
A reference AND hold-flat at **2× costs** (ADR-0011 S7), with 1× reported too.
Returns use native net P&L including marked open inventory over the same
flow-adjusted start equity; record denominator and cash flows. Nonpositive wealth
makes log growth undefined, not a dropped observation or finite winning score.
Name/selection and boundary effects additionally report portfolio-day net-return
differences (ADR-0019 A); dollar P&L across different funding is not performance.

Primary blocks are whole XNYS trading dates, keeping their symbol cross-section
and PRE/RTH/POST/overnight evidence together, under the paper README's 20:00 New
York roll. Carry dependencies may span blocks. Session/tier/price-band breakdowns
are not independent replications or additional confirmatory looks.

At 1×/2× include sourced fees/commissions, measured pre-entry spread, slippage,
square-root impact and applicable financing. Do not double-deduct fees already in
native net P&L. Inspect ADR-0019's 3× slippage sensitivity separately, not 3× every
cost. Seal model coefficients, calibration periods and unavailable cells. Unknown
funding/gap costs leave the affected carry/leverage comparison unverified.

Report drawdown, net per-trade R/original planned risk, effective gross exposure,
capital utilization, fill/nonfill/partial counts, slippage versus model, MFE capture
and gain giveback, missed movers, re-entry/rotation counts/outcomes, boundary
residuals/gaps and custody/protection/halt incidents. Separate actions, requests
and fills. C retains **150 actions/min plus a distinct 50/min MCP reserve** within
the 200/min trading bucket (ADR-0009 R2); no reserve spending policy is inferred.
P&L, utilization, loss and trade counts never become paper operating gates.
Money and quantity use engine types or Decimal; floats are only for statistical
return arrays, never for order quantities, prices, fees or account arithmetic.

## 5. Decision rule

Freeze walk-forward/CPCV partitions and label/holding horizons first. Explicit
purge and embargo each cover the horizon, including carry. An unknown/unbounded
carry horizon supplies no valid CV setting: report NOT_ESTIMABLE, never add an
expiry to force a pass. ADR-0019 requires median OOS Sharpe >0, ≥60% positive
folds and lower-quartile independently fitted CPCV path Sharpe >0.

Use studentized circular whole-session blocks with the cross-section intact.
Calibrate block length on training data by Ledoit–Wolf Algorithm 3.1, freeze it,
and show longer-block sensitivity. Freeze registry-backed repetition count/seed;
neither a fixture nor the upstream prototype block length is calibration. S7's
95% paired lower bounds must exceed zero against BOTH reference and hold-flat
at stressed costs.

One Romano–Wolf StepM family covers all 24 profiles and factor/cost/comparator
conditions, using the same blocks, α=1−0.95, `arch==8.0.0`, `bootstrap="cbb"`.
Every required column must reject; no favorable axis/segment gets an uncorrected
test. Require DSR >0.95 at cumulative effective N, PBO ≤0.05 (CSCV S=16) and
PSR ≥0.95. Below the sourced `pbo_min_sessions`, report INCONCLUSIVE; its value
and authority must be supplied by the registry, with no default here. S4's ≥30
independent round trips over ≥5 sessions and measured gaps apply to any claim
of a measured sizing cell; floors alone establish no statistical power.

Only complete full-stack event confirmation with required support, funding,
costs and integrity evidence supports a proposal. Among eligible profiles propose
the highest stressed-cost OOS mean log-growth lift over A, following the source
winner rule, showing adjusted
bounds and all competitors. If profiles are indistinguishable within paired noise,
report no unique winner; use no arbitrary tie-break. If none qualifies, retain
the negative/INCONCLUSIVE result and leave C's choices unavailable. A is not
installed as a fallback. Later searches add trials; N never resets.

Use one untouched confirmatory look. Further preregistered looks need the source
Bonferroni correction; revealed holdout becomes development data. ADR-0019's
untouched 12–24-month holdout remains necessary for merit, with exact dates sealed
before results; unavailable history means unavailable validation. MODELED never
substitutes for SIMULATED evidence. Subsequent sim uses the same sealed profiles
and broker/session/order-shape calibration, within its own tier; no current stream
is authorized. Report proposed numbers with uncertainty for **owner approval**,
never automatic adoption, account activation, promotion or live permission.

## 6. Execution seal and dependencies — unavailable

Before any trial, a reviewed immutable execution-seal change must bind:

- #84's shared-node plug-in and #51's custody/pacer/guard/halt seams, implementation
  SHA and full factor inventory. C writes no duplicate node, pacer or guard.
- #72's actual TrialLog registration/append API, canonical path/custodian and
  append receipt. Bind protocol/arm/run/config/params/data/weights hashes, tier/block
  set, funding uncertainty, failed/rejected/repeated attempts and inference-time
  N/effective-N snapshots. **Ledger binding: NOT_RUN until #72 lands.**
- Exact catalog/session/universe receipts and hashes, control/decision pairing,
  capital treatment, fill/latency/fee/cost calibration, random seed, train/test/
  holdout dates, horizons, CV splits and inference registry values.
- The reviewed six first-leg starts: count, span, maximum move, VWAP-extension
  coefficient, chase bps and TTL. Upstream C-local rows are sourced UNCALIBRATED
  starts, not a Sextant reviewed-change receipt or measured success.
- Other-family review, exact protocol/arm inventory hashes and the one-look
  record, all before outcomes. No results are gathered to choose the seal afterward.

This PR runs no strategy trial. Until these land, record NOT_RUN; create no side
ledger or synthetic full-stack substitute. Owner profile approval and #38's
readiness, old-writer stop/flat receipt and owner-confirmed handover remain
separate unmet requirements for any C broker activity.

## 7. Reporting and amendments

Every attempted arm, negative and unavailable cell carries its exact command,
covered interval, source/code/parameter/model hashes, tier and canonical ledger
receipt. Present all four profile choices together and by session, with bounds,
stressed costs, missed movers, support, multiplicity and limitations. Distinguish
screening, a supported proposal and insufficient evidence. An owner decision
amends ADR-0002 Changes for Sextant and C's registry between sessions; the lead
alone writes the handbook lesson. Do not write a completed paper-session note
before an observed roll. Changing this protocol after exposure retains the old
registration and search history; a fresh holdout/registered look is required.

## 8. Upstream references, read 2026-11-06

- [northstar-lanes@main 00203275944a22655b3e14b221cfde9a265d549a][lanes]:
  `docs/adr/0009-evidence-and-learning-loop.md` L3/L5/L9/L10;
  `docs/adr/0011-sizing-and-leverage.md` S1/S4/S6/S7, carried by ADR-0018/0019/0011.
- [northstar-trading@paper 8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa][trading]:
  `docs/research/2026-11-03-protection-and-early-entry-preregistration.md`
  §2/§4 F4/§5/amendment A2; `configs/paper/profiles.yaml` risk/slot/carry rows and
  six C-local starts; `src/northstar_trading/sim_lanes/registry.py` FrozenProtocol,
  ArmRegistration, CONTROL_ROLES and declaration hashes; `sim_lanes/grids.py`
  control construction at lines 479–498 distinguishes matched hold-flat from cash.
  Prototype values and
  superseded profiles are not imported as runtime defaults.
- [NautilusTrader@v2.0.0rc7 55c0e82053142bce3a5cba4de4221d3929c2d3bc][nautilus]:
  BacktestEngine, FixedRiskSizer and native money/quantity types; no replacement
  simulator, sizing formula or live-client stand-in is proposed.

[owner]: https://github.com/seathatflowsinourveins/sextant-archive/issues/44#issuecomment-6688786219
[brief]: https://github.com/seathatflowsinourveins/sextant-archive/issues/80
[lanes]: https://github.com/seathatflowsinourveins/northstar-lanes/tree/00203275944a22655b3e14b221cfde9a265d549a
[trading]: https://github.com/seathatflowsinourveins/northstar-trading/tree/8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa
[nautilus]: https://github.com/nautechsystems/nautilus_trader/tree/55c0e82053142bce3a5cba4de4221d3929c2d3bc
