# Shared paper node (#84)

The shared shell is rc7's `LiveNode`, named TradingNode in the issue. One
account config feeds one node, one writer lease and one row-8 pacer/guard.
Account-specific strategies and broker factories remain #78–#81's work.
This change has no broker client, key loader, stream or deployment entrypoint.

Sources inspected at their pins:

- `seathatflowsinourveins/northstar-trading@paper`
  `8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`:
  `nodes/live.py` (builder and account/client routing), `nodes/alpaca.py`,
  `nodes/ibkr.py` (paper preflight and risk config), `sessions.py` (XNYS,
  early-close and IB session composition), `pyproject.toml` (calendar/YAML pins).
  The older shared A/C topology is superseded by ADR-0007/0008's account nodes.
- `nautechsystems/nautilus_trader@v2.0.0rc7`
  `55c0e82053142bce3a5cba4de4221d3929c2d3bc`:
  `examples/live/sandbox/exec_tester.py`, `crates/live/src/python/node.rs`,
  native `Strategy`, `OrderFactory` and `BacktestEngine` APIs in the locked SDK.
- `gerrymanoim/exchange_calendars@4.13.2`
  `dbe38b1f6887434bbdd1a7d2df6ff8f1742a048a`: `exchange_calendar_xnys.py`.
- `yaml/pyyaml@6.0.3` `49790e73684bebad1df05ef8d828fa12f685bffb`:
  `yaml.safe_load`; versions match the pinned trading source.
- ADR-0007/0008/0009/0010 and `lanes/limits.yaml` supply custody, limits,
  paper-observe policy and unknown-state behavior; #51's merged #117 supplies
  their core implementation.

Implementation sequence and review focus:

1. Test account/client/namespace isolation, reject live/invalid IB config, and
   derive pacer caps from the limit sheet. Test actual XNYS early closes,
   holidays, weekends, DST and nanosecond boundaries, then carry the source slice.
2. Test the injected row-8 services and paced native strategy boundary: scope
   mismatches, owner cancellations, pending quantities, halt and unknown state,
   rechecking a queued command after a session boundary, and missing prices.
   Construct orders only inside the paced callback; retain uncertain outcomes.
3. Test inert native-node assembly plus deterministic native backtest fills.
   Exercise real row-8 objects through #117; earlier draft-source fixtures
   prove the plug-in seam, never broker custody or parameter authority.
4. Run default tests and complete local CI; publish the account interface,
   manifest proof, limitations and PR, then hand review fixes to AO.

The source's calendar is a schedule, not proof of broker eligibility. An account
must explicitly supply supported sessions; IB additionally supplies dated
instrument eligibility and its maintenance window. Entry windows do not block
reducing/protective actions, but native session/order-type constraints still do.
No tuned value is introduced here: caps come from the limit sheet, native risk
keeps `bypass=False`, and row-8 registry/reserve authority remains required.

Real external-owner claims, adapter reconciliation after process death, account
handover, paper fills and installed broker protection remain unverified. A/C's
both-empty restart and arm isolation are the account slices' required drills.
The lead remains the single writer of handbook lessons; this PR's Lesson is a
proposal for that path, not a memory-store write.

## Interface and verification boundaries

`PaperAccount` configures identity, namespace, explicit supported entry sessions,
paper port and B-only claims. `load_budget` reads the shared YAML; no account
slice constructs another scheduler. `PaperServices` injects the row-8 objects,
`ActionKind.__members__`, dated `eligible(intent, now_ns)`, an executable
`exit_price(instrument, now_ns)`, and the required custody callback
`submit_allowed(instrument, side, quantity, exclude_client_id)`. That callback
has no runtime default. The last argument is null before registration and the
request's own ID at its final wire recheck. It must exclude only that request's
reservation, never a second request. The row-8 core is merged through #117;
the callback's account binding remains unverified.

SELLs additionally require custody's `submission_ready` and
`available_exit(..., exclude_client_id=...)` from the row-8 interface in #117.
Both the initial and post-registration checks consume that authoritative
residual; only the latter excludes the request's own ID. A missing readiness
method refuses the SELL, and a permissive account callback cannot override
custody. There is no new reservation book. The pinned predecessor fixture is
recorded alongside the older fixture's hashes in the source receipt below.

`PaperRuntime.request` returns queued, never accepted or filled. It fences a
queued action with the row-8 writer token, registers lineage before dispatch,
and allows its own registration during final pacer revalidation. A changed
writer, owner halt, unknown custody or session change refuses the send. It
consumes `Guard.step` without initializing/releasing unknown state. Guard
flattening requires an explicit executable price; no price means no invented
order. Native simulated command counts are not broker-wire counts.

Review exposed a missing post-registration call to admission. The final check
now runs after durable registration and before native dispatch, using the own-ID
exclusion. Seven regression cases first failed against the old path: ENTRY,
EXIT and PROTECT each need the exclusion and must honor final refusal, and an
owner halt during registration must prevent dispatch. All four paper proof
modules then passed with 55 passed and four pending row-8 skips. A refused final
check leaves lineage registered and performs no dispatch or wire accounting;
this does not establish row-8 or broker acceptance.

The duplicate-flatten review added eight admission cases that first failed:
missing custody readiness, refused custody despite a permissive callback, the
own-ID exclusion, and residual changes after registration, for EXIT and PROTECT.
All passed after requiring the row-8 methods. Against #117 at
`cc9c44caddaf24d17074c65845dcc7cd08286eaf`, all 75 paper proofs passed. Its real
custody, guard and pacer sent one 10-share EXIT, refused another full EXIT, and
sent nothing over four more flatten ticks without a new snapshot, even with
`submit_allowed` returning true. The [source receipt](2026-11-06-shared-paper-node-row8-fixture.json)
preserves both pre-merge fixture versions. After #117 landed, this branch merged
main at `b3fbdd4202e057c4be458bdef84fda6e48f4ec17`. Normal test collection now
executes all five row-8 integration tests against that merged core, including
the repeated-flatten witness, without fixture injection.

Native validation has a separate boundary: a `ValueError` from dispatch before
`before_wire()` starts is an unsent refusal. The accounting hook is marked as
started before invoking it, so errors inside or after that hook still halt for
an unknown outcome. Unexpected exceptions and admission errors also still halt;
their handling is not weakened by the native-validation catch.

Seven cases cover that boundary. Native simulated GTC stop-market and stop-limit
orders remain accepted and unchanged after a refused after-close amend, with no
extra accounting and the guard active. A pre-wire validation case also first
failed against the old path. Controls retain halts for unexpected pre-wire
errors, admission errors, and validation errors inside or after accounting.
The four paper modules passed with 62 passed and four pending row-8 skips. A
trailing fixture was denied by native risk before amend for unavailable market
data; it supplies no accepted-trailing or broker proof.

Focused checks cover the config/calendar fences and native simulated fills.
Before #117 landed, `test_paper_row8.py` explicitly skipped unavailable modules.
Its initial four drills also passed against a read-only snapshot of that
worker's actual modules: one writer refused twice,
the shared pacer bounded a 240-request/60-second fixture, owner halt cancelled
only the house entry, and corrupt guard bytes remained unavailable and halted.
The [source hashes](2026-11-06-shared-paper-node-row8-fixture.json) identify that
draft; those earlier results are fixture-seam evidence, not broker acceptance.

Earlier snapshot runs appended its `sextant/` directory to `sextant.__path__`.
Ordinary `pytest` and `just prove` now use the merged modules directly.

Author review caught and tested a mutable external-claim list and revival of a
queued command after writer reacquisition; both now fail closed. The required
other-family review remains the PR's gh-aw check, and AO owns its fix/review
loop after handoff. Account-specific profiles, live-feed claim tests, actual
IB all-request pacing, crash/reconciliation, ledger fills and handovers are
still unverified. None is converted into a ready or performance claim.

After #117's merge, main advanced again to `95c8055`; the follow-up merge keeps
both the AO isolation lesson and main's router-key renewal lesson.
`just ci` passed: 502 passed, one skipped,
seven container/local deselections, and two unchanged upstream warnings.
Main's complete pytest configuration remains unchanged. Native `just prove`,
with the installed pinned QMD on PATH, ran all proofs: 482 passed, one opt-in
study skipped, and two environment failures. The firewall and sudo witnesses
expect the dev container; this host deliberately has open private routes and
passwordless sudo (`docs/start.md`).

All non-container proofs passed in that run. The three container-marked proofs
passed separately in a session-labelled rootless `devc` container, using the
cached project image, matching firewall/post-install source, a read-only source
mount and no forwarded credentials. The proof container was then stopped.
Their test and container source are unchanged by the follow-up main merge;
the complete proof set has 484 passing witnesses across their proper contexts
and the one opt-in skip.
No firewall, sudo policy, marker or required check was changed to pass a test.
