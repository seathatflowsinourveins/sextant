# Full-stack S recorded replay implementation plan

**Spec:** issue #111 and the accepted ADR-0002/0004/0005/0006/0007/0009/0010/0018; the pre-stream plan and source map in `2026-11-06-sandbox-plan.md`. Execute inline, no helper workers. No stream, broker factory, key or ledger writer in this lane. One push after all local work/proofs; AO owns later fixes in one batch.

**Architecture:** identical native strategy objects compose ranking/reader, entry/sizing, exit, account custody/pacer/guard and re-entry admission. Live construction uses #134's S binding; recorded replay uses native BacktestEngine with the source's explicit venue-client/account translation, and remains MODELED. One account service owns all per-instrument strategies. The source's per-symbol ExitEngine is inherited, with its sends routed through the common pacer/custody boundary; no second risk or exit policy.

## Sources and rulings

- Nautilus rc7 `55c0e82053142bce3a5cba4de4221d3929c2d3bc`: LiveNodeBuilder, BacktestEngine/cache/portfolio/Strategy and custom data APIs.
- northstar-trading `8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`: source S0 sandbox/routing/witness, entry sizing, guard/custody/pacer and TrialLog. northstar-lanes `00203275944a22655b3e14b221cfde9a265d549a`: carried composition contracts.
- Reuse owning Sextant modules; #117 is landed. #134's original seam commit is stacked here without writing its AO-owned branch. Until #68 lands, the replay may load a hash-recorded read-only archive of its actual entry modules at `4770af0473e019f6190425dfeaf6146ad8bb6d20`; this is draft integration evidence, never a mock entry engine or merged/runtime acceptance.
- Ruling: BacktestEngine's venue-named ALPACA client/account are an explicit MODELED translation, as in the pinned S0 witness. They do not prove multi-client live S isolation.
- Ruling: #41 bars and scanner snapshots lack eligible trades, quote sizes, complete baseline/heartbeat/asset authority and receipt clocks. Preserve UNKNOWN, do not expand OHLC into prints or saved ranks into a new complete generation. The recorded arm may finish PRUNED with no returns. Separate synthetic arms, with FIXTURE_ONLY registry values, prove connected native transitions; their fills are not historical/economic evidence.
- Ruling: every actual arm, including failed/repeated mechanism arms, needs its own reserved canonical RUNNING row before native engine work. Only #102 writes the ledger. CI tests validate contracts/pure transitions and constructor boundaries, not unreserved full-stack runs.

## Task 1: frozen profile and single-writer handoff

Files: `sandbox/handoff.py`, fixture profile, `tests/proofs/test_sandbox_replay.py`.

- [x] RED/GREEN tests for strict no-float handoff, unchanged byte hashes, reserved identity/state/tier/config/code matching, duplicate refusal and failed outcomes with no returns.
- [x] Use the sanctioned `sandbox-111/<attempt>/{reserve,outcome}` inbox and TrialLog's JSON hash shape. Verify a posted reservation commit is on the protected ledger history and read its Parquet; never append a local/canonical log.
- [x] Freeze exact source/input/parameter identities and one fresh arm-run per process; retain attempts if resources or execution fail. Commit validation rejects modified/untracked code, profile or locked runtime; execution rechecks every frozen hash.

## Task 2: shared native stack

Files: `sandbox/{account,market,strategy,profile}.py`, node seam extension.

- [x] Construct real owning components with explicit registry values and no production defaults. Share one writer/pacer/guard/custody book across instrument strategies; keep current native account/terminal-lineage facts coherent.
- [x] Inherit exit policy, use row-6 first-leg/ATR and FixedRiskSizer, coherent ranking generations and re-entry refusal. Every native submit/modify/cancel is explicitly routed and paced, with final custody/session/halt checks and immutable registration before dispatch.
- [x] Capture component callback counts, native fills, route/namespace evidence, owner-order status, minimum net and halt/flat receipts. Refuse unsupported broad/unrouted actions. Runtime acceptance remains pending the reserved arms.

## Task 3: recorded/fixture tape and gated runner

Files: `sandbox/tapes.py`, `sandbox/replay.py`, source/parameter evidence.

- [x] Read #41's verified catalog and scanner BBO without inventing ticks/sizes/receipt clocks. Feed recorded facts through registered native custom data at generation time, with no claimed delivery latency.
- [x] Predeclare recorded, duplicate A/A fixture, kill/owner fixture and corrupt-state fixture cases; fixture values and event shapes come from the owning proofs/native examples and are labelled uncalibrated.
- [x] Gate engine construction on a real canonical reservation; run serially under timeout with MemAvailable >=20 GiB. Finish each attempt with a result or failure and absent economic returns when not qualified. A/A compares native fill times/side/price/quantity and final net with only order identity removed; no economic return is fabricated.

## Task 4: canonical runs and landing

- [x] First batch: freeze implementation, stage reservation rows, post both file hashes on #102, wait for the ledger commit/N receipt, then execute the reserved arms in fresh processes.
- [x] First batch: post matching outcomes and verify the sole writer's finish receipt. Its failure is preserved; changed/repeated runs need fresh reservations.
- [ ] Inspect exact results against the declared assertions, update source/manifest evidence and the PR-body lesson; run local CI and author review. Open once with `just pr`, then claim via AO after ci completes; no live-feed/S-ready/economic claim.

## Review focus

Source/parameter changes after reservation must refuse; fixture metadata cannot authorize a stream. An order absent from the last snapshot must reserve quantity immediately. Retiring/reacquiring a writer must not revive queued work. Explicit client routes and order namespaces must survive native callbacks. Unknown source, account or guard state must not become an entry or a zero return. Generation clocks stay distinct from capture/receipt clocks. Each failure/retry stays counted in the canonical history.

## Initial freeze checkpoint

At the initial freeze the contract/constructor suite passed locally (23 focused proofs); `just ci` passed 405 tests, one skipped and seven deselected. The recorded arm intentionally has no complete eligible trade feed, baseline/close/asset/heartbeat authority or executable BBO size, so its admissible result is no order with those gaps preserved. Synthetic arms exercise the connected first-leg/sizing, fast LIMIT exit or kill path, native terminal lineage and re-entry refusal. Re-entry has no qualified entry/sizing provider; native broker-held protection, owner-fill claim, crash recovery, multi-client S runtime and real-feed SIMULATED acceptance remain separate unproved capabilities.

## Counted first attempt and fix batch

`stack-b6ea54c-1` was reserved at `3487877f6d7c15380ee192bef6a2e3239731460f` and closed at protected ledger commit `e5a02968ae6484f72b04bf076a46e5723167dac6`, cumulative N=112. Trial 107 retains FAIL: native registration rejected the shared order tag before recorded events replayed. Trials 108–111 are PRUNED with their four mechanism results and no returns. The A/A native fills match exactly after removing only order IDs; kill flattened house net while retaining the owner fixture order, and unknown persisted state denied entry. [Sole-writer receipt](https://github.com/seathatflowsinourveins/sextant/issues/102#issuecomment-6694235022).

[Compact first-attempt observations](2026-11-06-sandbox-replay/first-attempt.json) retain the exact selected native counters, fills, terminal states and both handoff hashes; the canonical ledger keeps the full results. The batched fix passed `timeout 300 just ci`: 407 passed, one skipped, seven deselected; lint, format, types, workflow linters and secret scan passed. The two new regressions each failed before the corresponding implementation change and pass afterwards. No changed-code arm has run at this checkpoint.

The fix follows rc7 `crates/trading/src/strategy/config.rs` and `crates/system/src/trader.rs`: native order tags are unique per instrument strategy while retaining the arm prefix. The owning `Reentry.after_sell` cooldown uses the first positive flat receipt's clock; repeated observations of unchanged terminal lineage retain that anchor, while unavailable custody or changed lineage invalidates it. RED/GREEN constructor-only and pure clock proofs cover both defects, without an unreserved native engine. A/A runtime acceptance now also requires cooldown to expire into the explicit missing-provider refusal. All five changed-code retries need fresh reserved IDs before any engine construction; no earlier attempt is overwritten or reset. The branch remains unclaimed and unpushed until those drills finish, then uses the current B-chain merge hold and AO handoff rules.
