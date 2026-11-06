# Sandbox S: implementation plan and connection boundary

Issue #111, 2026-11-06. The owner's accepted architecture is ADR-0002/0008: the same ranking, entry, sizing, exit, custody, pacer and guard objects run on native simulated execution, with one cumulative TrialLog. This delivery supplies the inert native constructor, recorded BBO reader and written data proposal. Full-stack wiring and recorded arm runs remain pending. No stream or broker connection is authorized. The owner's PR freeze is lifted after #92; `[tool.pytest.ini_options]` stays untouched and the new proof is collected by its directory.

## Sources and approach

Use `nautechsystems/nautilus_trader@v2.0.0rc7 55c0e82053142bce3a5cba4de4221d3929c2d3bc` native LiveNode, SandboxExecutionClientConfig/Factory and MarketDataClient/DataClientFactory. The inspected installed Python sources construct a data client without network work; its async connection hook starts separately. The house wiring is `seathatflowsinourveins/northstar-trading@paper 8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`: `sim_lanes/{sandbox,sandbox_routing,sandbox_witness}.py`, `nodes/alpaca.py` and `nautilus_alpaca/{data,factories}.py`.

The node keeps venue ALPACA, with a distinct simulated client, matching account issuer and strategy/order namespace per arm. Adopt the accepted ADR's account-issuer rule over the old S0 plan's ALPACA-prefixed account. Wired strategies must name their client on every execution command; that routing/runtime acceptance remains owed. Two configured arms use random IDs. RiskEngine stays enabled. Only the native sandbox factory is registered for execution. The pre-stream data-adapter seam has no network transport and refuses connection activation.

Native construction exposed a binding limit at this pin: `LiveNodeBuilder.add_simulated_exec_client` accepts no routing argument and does not populate `exec_client_routing` (`crates/live/src/node/builder.rs:544–564`). Two sandbox clients on ALPACA consequently fail the ambiguity check at lines 763–779. The generic `add_exec_client` refuses the SANDBOX factory extractor. The supported local build therefore selects exactly one registered arm per node, retaining distinct identities across nodes, consistent with the source witness's isolated-arm shape. A two-arm runtime with one authorized feed/fanout still owes its acceptance; the failed mixed-client build is retained as negative mechanism evidence, not hidden behind a fallback/default route.

A direct broker-paper client violates S's simulated execution role. Copying the old full strategy/adapter trees would duplicate the lane owners' mechanisms and their unresolved gaps. Compose the lane modules instead; fixture seams prove only what is labelled as a fixture. No dependency skip or inert configuration is a full-stack acceptance receipt.

## Work sequence

- [x] Add a native sandbox plan/builder and an offline data-client seam; test distinct account issuers, clients/namespaces, factory selection and disabled connection. Construction reads no environment/key.
- [x] Add a recorded BBO reader and audit #41's bytes through its existing hash checks. Read scanner files only; preserve their byte hashes, quote event times and generation clocks. Do not make ticks from minute OHLC, invent missing BBO, or turn old ranks into a current complete ranking generation.
- [ ] Compose landed ranking #66, entry #68, exit, custody #117, re-entry #116 and TrialLog #96/#110 through the same native Strategy callbacks and explicit routes. Missing authority stays unavailable. Test owner/namespace isolation, paced admission, halt and unknown-state refusal using the owning modules.
- [ ] Reserve every actual arm-run through #102's single writer before executing; retain failure outcomes, input/code/config/parameter identities and tier. Finish through that same writer. No replacement ledger or local canonical-path assertion.
- [ ] Run bounded recorded replay from #41 and scanner data with at least 20 GiB MemAvailable, record actual node/runtime limits and distinguish MODELED replay from live-feed SIMULATED acceptance. Minute bars cannot qualify first-second onset or tick fills.
- [x] Complete the owner's data proposal, source map, manifest row and eight proofs; run local checks. The PR body carries the lesson for the lead's single-writer handbook journal. Land through `just pr`, then `just ao claim` when `ci` completes.

## Current dependencies

The initial checkpoint was built on `3f6faa5`; the PR rebases onto current main. Ranking #66, entry #68, custody #117, shared node #104 and TrialLog #96/#110 were unmerged at the initial inspection and remain owned by their lanes/AO; entry #68 and custody #117 are still open at PR preparation. Their pending mechanisms are not copied into this constructor.

The ledger lane supplied the sanctioned inbox on [#111](https://github.com/seathatflowsinourveins/sextant/issues/111#issuecomment-6691367354), formalized by #110: `/home/sextant/sextant-data/sandbox-111/<attempt>/{reserve,outcome}/`, each with `manifest.json` and `rows.jsonl` in `sextant.ledger.handoff/1` format. The lane posts directory and byte hashes on #102, waits for the ledger commit/N reservation receipt, runs, then posts the matching outcome. Recorded replay uses MODELED; a later live-feed sandbox run uses SIMULATED, without pooling. Only the ledger lane verifies/appends through `just ledger-append`. No S arm-run or reservation has started in this constructor/input-audit delivery, and no local substitute ledger is written.

## Review focus

An ALPACA account issuer can silently resolve the wrong execution client. Missing explicit routes, reused namespaces, default clients or cross-arm cancel-all must refuse. Generation time is not a historical delivery receipt. Missing reserve/mark/baseline/ATR/session authority supplies no entry. A lost process must leave a retained RUNNING/failed attempt rather than reset N. The full-stack and two-arm runtime receipts remain owed until actually measured; no live stream, B takeover or promotion follows from this plan.
