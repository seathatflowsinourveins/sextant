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
since #151 it also marks the registration released unsent in custody (see below).
This does not establish row-8 or broker acceptance.

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
`before_wire()` starts is an unsent refusal. Errors after that hook returns still
halt for an unknown outcome. Since #151, a raise inside row 8's hook is a refusal
that releases the registration, because that pacer raises only before it counts
(see the section below). Unexpected exceptions and admission errors also still
halt; their handling is not weakened by the native-validation catch.

Seven cases cover that boundary. Native simulated GTC stop-market and stop-limit
orders remain accepted and unchanged after a refused after-close amend, with no
extra accounting and the guard active. A pre-wire validation case also first
failed against the old path. Controls retain halts for unexpected pre-wire
errors, admission errors, and validation errors after accounting.
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

## Kill-to-flat after merge: one exit in flight, unsent rows released (#123, #151)

The Claude quality-tier review of the merged shell found that a registration refused before
the wire was never reported. Custody's `submission_ready` then refused every later order on
the instrument, the next observation froze it, and `Guard.step` returned nothing for the
whole account. Repro on `main` `1147ba0` with real row-8 objects:
- a PROTECT refused by native validation after registration froze AAPL;
- halt plus four flatten ticks sent `[]`;
- the guard latched `unknown_execution_state`.

Upstream closes a submit that never left locally (`order_reducer.py::_t_cancel_unsent`,
`execution.py::AlpacaSubmitAborted`). The fix has three parts:
- **Registration moves inside the wire hook.** It now happens after the native layer's own
  checks: cache, identity, and price and size precision. rc7's RiskEngine denies a finer
  precision only after `submit_order`, so it is now checked before the hook. A
  deterministic refusal writes no custody row; 20 refused flatten ticks leave the file
  unchanged.
- **Refusals before the pacer counts the wire release the row.** This covers the recheck
  after durable registration, which still excludes only the request's own ID, and a raise
  inside row 8's hook, where the pacer raises only before it counts. The row is marked
  through custody's durable `release_unsent`.
- **rc7 denials release too.** An `OrderDenied` after `submit_order` proves a refusal on this
  node, so `PaperStrategy.on_order_denied` releases as well.

A release applies only to an unlinked row with a non-empty reason, and only if no report
shows it live. A terminal, unfilled, venue-less report is how a node-local refusal looks,
and it agrees with a release. Any other report of a released row freezes its symbol. A
released client ID cannot return. Files holding released rows are written as version 2.

Admission errors in the current send, unexpected errors and any error once the wire is
counted still halt, and an error once the wire is counted never releases. A native send that
skips its hook, or swallows a refusal, halts. A hook called after its send returned
registers nothing.

Row 8's bridge is unchanged. Under its facts composition, its own REJECTED venue-less fact
already resolves a never-sent submit, and custody now agrees with such a report even if the
row was released.

#123's oversell was already closed by the pre-merge `submission_ready` gate, because an
unreported house order holds `available_exit` at zero. The new drill checks this under a
30-second pacer pause: six queued full EXITs, and exactly one 10-share EXIT on the wire once
the pause ends. Against `main`'s source, the #151 drill failed and the #123 drill passed.
The review's mutants are killed by the new proofs.

The #88 lane's adversarial-verify of `6eff414` passed the gate with no P0 or P1. Three of its
findings changed the code:
- **Per-intent isolation.** `pulse()` isolates each kill intent and always drains the pacer.
  An unknown outcome on one instrument, such as an EXIT that counted the wire and then raised,
  halts the account and keeps that row. Every other instrument's FLATTEN still goes out in
  the same pulse.
- **A send that swallows its hook refusal.** It may still have submitted, so its row now
  stays registered and the account halts, with no release.
- **A writer fence on denials.** `denied()` releases only a row this writer registered, while
  it still holds that lease.

The guard's account-wide stop on any frozen symbol remains row 8's call, raised on #51.

The #88 gate review of `9fb329f` found two P1s, each reproduced by three of three refuters:
- **A send swallowed its hook's refusal and then raised, and its row was still released.** Halt
  plus four ticks then sent five full EXITs against a 10-share long. Now a release needs the
  escaping error to be the hook's own exception, or one chained from it. Anything else stays
  unknown and halts.
- **A queued kill command's admission raised at the pacer's drain head and was never popped.**
  MSFT then never flattened. Now every admission error, at request time, at the drain or inside
  the hook, records the reason, halts and returns False, so the pacer pops the item.

The same push also changes four smaller paths:
- A send that skips its hook has its row registered as unknown, so its quantity stays reserved.
- A kill EXIT queued behind a pause goes out only at the current exit price.
- A kill denial retries once per observation instead of once per tick.
- A price or size with trailing zeros (9.990, 10.0) builds exactly. Only a finer one is
  refused.

The #88 gate review of `f1d49b3` found four more P1s. Three of three refuters confirmed P1-A and
P1-D; P1-B and P1-C were left open by the 10-agent cap. All four are fixed.
- **P1-A.** The current-price check ran after the pacer spent a token. Under 429 pacing, six or
  more longs starved: 0 of 6 flattened in 300 s.
  - **Fix.** Every gate now runs in admission, before the token, and a symbol keeps one queued
    kill EXIT unless its price moved.
  - **Probes.** 6, 8 and 12 longs, with a 429 or a 30 s pause, all flatten.
- **P1-D.** Any denial suppressed that symbol's kill.
  - **Fix.** Only a denied kill EXIT waits for a new observation.
- **P1-B and P1-C.** A release based on the escaping exception can be fooled: a send can submit
  inside its handler and raise, chain, wrap, or re-raise the hook's own refusal, or skip its
  hook.
  - **Fix.** Only a `@conforming` send's own refusal, which is the shipped `_dispatch`, releases
    at once. Any other row is registered and held, still reserving its quantity, until a complete
    later observation shows it absent (upstream `order_reducer.py::_t_submit_observed`). A
    refusal before the hook must be a `NativeRefusal`.
  - **Probes.** No oversell in any of the reviewer's send shapes.
  - **Conflict.** The reviewer's `native_valueerror` case, a plain `ValueError` before the hook,
    now halts by design, as P1-C asks.

The #88 gate review of `8cdc3f7` found two more P1s, each confirmed by three of three refuters,
and a P2:
- **P1-E.** The first complete read that omitted a held row released it, even while its POST
  could still commit. Alpaca can commit a timed-out POST late (upstream `config.py:273-275`,
  60 s). In 9 of 15 timings, two 10-share EXITs went out against a 10-share long.
- **P1-F.** `NativeRefusal` was trusted from any send. A send that skipped its hook, submitted
  and then raised it registered nothing.
- **P2.** `observe()` wrote custody when it settled a row, with no writer fence.

Every one of P1-1, B, C, E and F needed a send callable that broke its hook contract: one
that skipped, swallowed or re-raised the hook's refusal. Turn 4 vetted the send with a
declaration and a source pin. gh-aw's review of `512660b` found that mechanism had no
upstream source (Rule 1, P0). Turn 5 removes the cause instead of vetting it:
- **The runtime owns the order.** The native layer only prepares: `_prepare` validates and
  builds one native command and never receives the hook. `PaperRuntime` runs its own hook,
  then the command. This is upstream `http.py::RestCaller.call`'s order: `before_send` runs once
  the pacer admits, right before the request leaves, and a raise from it aborts the request.
  NautilusTrader's own Strategy API splits the same way: the OrderFactory builds, and
  `submit_order`, `cancel_order` and `modify_order` send.
- **Only a registered client reaches a wire.** The command goes through rc8's RiskEngine and
  ExecutionEngine. The engine routes it only to a registered client and claims the order for
  that client before sending (`crates/execution/src/engine/mod.rs:2191-2205` and `:2524-2541`
  at `d53849b2`). A drill shows an order addressed to an unregistered client denied natively,
  never sent, and released.
- **No row is held any more.** Every outcome before the wire is the runtime's own control
  flow. A refusal or error in the hook releases at once, because the command never ran, and
  once the command runs the row stays in flight. So the held-row machinery is gone: the
  refused rows, their settlement on observation and the may-have-been-sent mark, and with it
  P2's write path.
- **The writer reloads custody when it (re)acquires the lease.** Upstream takes its account
  lock and then restores custody from its file before any venue connects (`run.py:193-223`,
  `nodes/live.py:489-501`). A reopened writer therefore never registers over another writer's
  rows.
- **Smaller fixes kept from turn 4.** rc7's plain `ValueError`s while preparing (a venue-less
  symbol, or a price or size beyond its range) are `NativeRefusal`s, and a client ID rc7
  refuses fails at load.

#88's delta review of `512660b` raised P1 candidates for a declared send that misbehaves. The
change above makes them unreachable, because no send callable receives the hook any more. It
also raised one P1 on the shipped send: `_dispatch` refused natively only after the pacer
had spent a token, and kill-to-flat re-queued the same refusal every tick, which starved the
symbols that could be sent. The native layer now prepares inside the pacer's admission,
before the token. A native refusal of a kill EXIT waits for a new observation, as an rc8
denial does. The kill EXIT is also validated before any bookkeeping.

**Coverage, stated plainly (dsh-TUI breadth leg on `512660b`).**
- **No shipped driver runs this yet.** `build_shell` is inert by design (#104), so nothing in
  `src` calls `pulse()` or `observe()` today, and kill-to-flat is proven in drills only. B's
  node supplies both: #139's reconcile drives `observe()`, and B's account slice drives
  `pulse()` from a native clock timer at row 8's `flatten_tick_s`.
- **One joined proof.** The shipped `_prepare` runs with row 8's real custody, pacer, guard
  and writer lease in rc8's BacktestEngine. A recheck refused in the hook releases the row
  and sends nothing, and an admitted ENTRY registers, counts one wire request and reaches the
  venue. The row-8 drills cover kill-to-flat with a stub command, and the native drills cover
  `_prepare` with contract stubs.

**Residuals, open.**
- An rc8 denial other than precision, such as notional, is retried once per observation on
  the kill path, and pages nobody.
- A resting kill EXIT is never re-priced while the price falls. This predates the work and is
  tracked as #176.
- The gate's pacer and B's bridge both pace B's orders; #139 records it.

**Revert.** Code from before this change refuses a version-2 custody file ("custody
account/version mismatch") and fails closed. To recover, delete the rows marked `unsent`,
which never reached a broker, and set `version` to 1.
