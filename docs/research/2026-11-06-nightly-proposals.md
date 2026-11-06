# L4 nightly tuning: proposals, never parameter writes

Issue [#114](https://github.com/seathatflowsinourveins/sextant/issues/114). Design only, 2026-11-06. **Not implemented, installed or enabled.** This completes the nightly-job design, not the whole learning lane. The reflection precheck and canonical lesson appender are separate work; neither changes here.

## Authority and upstream

[ADR-0018](../adr/0018-evidence-and-learning-loop.md) carries L4: nightly tuning writes proposals only. Its upstream Confirmation is explicit: the tuner never writes a registry row, **not even through a reviewed write**. A different actor may make a reviewed, between-session registry change under L3/L5. Merging a proposal PR does not adopt it, enable an arm, hand over an account or promote a tier.

Sources read at these exact commits on 2026-11-06:

| Source | What is reused; what it does not prove |
|---|---|
| [northstar-lanes@00203275944a22655b3e14b221cfde9a265d549a, ADR-0009](https://github.com/seathatflowsinourveins/northstar-lanes/blob/00203275944a22655b3e14b221cfde9a265d549a/docs/adr/0009-evidence-and-learning-loop.md#L53-L138), L3–L10 and [Confirmation](https://github.com/seathatflowsinourveins/northstar-lanes/blob/00203275944a22655b3e14b221cfde9a265d549a/docs/adr/0009-evidence-and-learning-loop.md#L162-L178) | Consuming-runtime registry; proposal/adoption separation; frozen protocol; one cumulative TrialLog; separate tiers; recorded replay. D059/D078 retain proposal-only tuning and a read-only registry view, not an installed job. |
| [northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa, tuning_runner.py](https://github.com/seathatflowsinourveins/northstar-trading/blob/8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa/src/northstar_trading/reflection/tuning_runner.py#L404-L435) | `candidates_only` replaces the lesson appender; `run.json`/manifest record hashes and insufficient inputs. Reuse the offline binding/output shape, not its paper-profile policy or defaults. |
| [Same pin, tuning.py](https://github.com/seathatflowsinourveins/northstar-trading/blob/8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa/src/northstar_trading/reflection/tuning.py), `ReplayInputs`, `propose`, `nightly`; [runner recipe](https://github.com/seathatflowsinourveins/northstar-trading/blob/8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa/docs/research/nightly-tuning-runner.md) | Explicit recorded bindings, immutable generations, per-target insufficiency and no broker client. Legacy proposal statistics are not the later L5 adoption implementation; its scheduler remained render-only. |
| [stablyai/orca@v1.4.251 a162e08b29b2883b02d8a0dfcc99e26c80b2cfe7, automations.mdx](https://github.com/stablyai/orca/blob/a162e08b29b2883b02d8a0dfcc99e26c80b2cfe7/docs/site/content/docs/cli/automations.mdx); [CLI spec](https://github.com/stablyai/orca/blob/a162e08b29b2883b02d8a0dfcc99e26c80b2cfe7/src/cli/specs/automations.ts) | Existing scheduler, disabled creation, explicit IANA timezone, fresh worktree and scheduled precheck. **Manual Run now bypasses the precheck.** No new daemon or scheduler. |
| [trailofbits/claude-code-devcontainer@062e9e778d6255a87d55452f8a546240a28f67f3](https://github.com/trailofbits/claude-code-devcontainer/tree/062e9e778d6255a87d55452f8a546240a28f67f3), adopted in ADR-0001 | Unattended execution uses the existing devcontainer. This owner's native worker assignment does not authorize an unattended native job. |

Context7's Orca documentation search confirmed the schedule/precheck interfaces; the pinned files above, not rolling documentation, govern this design. Local `orca automations create --help` exposes those flags. No automation was created or run.

## Approach

**Choose the existing Orca scheduler plus the candidate-only runner seam.** A separate named automation, `Nightly tuning proposals`, consumes frozen evidence and produces research PRs. Reuse the existing `Verified reflection` job's fresh-worktree/disabled-install convention without changing its name, schedule, precheck state or prompt. The nightly job does not discover harness session ends.

Alternatives rejected:

- **Port the whole legacy tuning tree:** imports obsolete adoption shorthand and implicit values, adds unrelated policy, and exceeds the thin carry intended by ADR-0018. Adopt the binding/candidate/publication seams only.
- **Add another cron/systemd/GitHub scheduler:** duplicates Orca's scheduling/ownership and cannot supply missing local evidence or calibration. No second dispatcher or numerical store.
- **Fold tuning into reflection:** reflection reads harness sessions/merged PRs; trading tuning needs frozen tapes, protocols and trial custody. Sharing their precheck watermark would confuse those distinct completion events.

## Run contract

The following are implementation requirements, not an available CLI or a new authority schema. Reuse the owning registry/TrialLog contracts once they land; do not create substitute stores for this design.

### Trigger and isolation

- The upstream runner's session-close recipe uses **20:00 America/New_York**, not a fixed UTC offset. Treat it as the sourced nightly wake-up candidate, not proof that all data or all supported sessions have ended. The lead must record the accepted schedule and target setup before installation; no schedule is installed here.
- Each request names an explicit completed session/window and `as_of` cutoff, with its completion/data-ready receipts. The wall clock, a PR merge, or the reflection precheck passing cannot supply these receipts. A 24/5 account may already be in its next window: this job still reads only frozen prior evidence and changes no active state.
- Resolve session identity against the per-date XNYS/`America/New_York` contract, including DST and early closes. A holiday or missing tape is not an empty-return session. Closed-market work may replay earlier recorded sessions. Neither replay nor a proposal authorizes a data stream, broker connection or order.
- Use Orca's `--repo`, `--workspace-mode new-per-run`, `--base-branch origin/main`, `--setup skip`, fresh session and `--disabled` convention. Do not reuse a paper writer's worktree or terminal. Keep the stable precheck entry under the reviewed main checkout, as reflection does; do not point it into a disposable run worktree.
- Unattended execution must resolve to the existing **devc sandbox** with no broker secrets, live credentials or sign-in adoption. The host only launches the approved devc path, never an agent-written checkout script. The Orca-to-sandbox target/launcher receipt is currently unavailable; a native provider flag alone is insufficient. Keep installation unavailable until that source-backed binding is demonstrated. Any GPT runtime retains the approved `sextant-gpt`/`gpt-6.1-sol` max route; no fallback runtime or Claude subscription.
- A cheap scheduled precheck may skip incomplete inputs, an already-published identical request, overlapping ownership, or missing resources. It must not consume the reflection watermark. **The runner repeats readiness checks on every entry, including manual runs**, since Orca intentionally bypasses the scheduled precheck for Run now.

### Required, explicit inputs

| Binding | Required evidence and missing-data disposition |
|---|---|
| Identity | Source hypothesis/ADR, exact implementation SHA, arm/factor mask, configuration/weights identity, target lane/session, registry version and `params_hash`. An absent binding stays unavailable; a fixture is never authority. |
| Registry | Read-only snapshot from the consuming runtime, with name/unit/value/source/calibration/last change. Preserve cited UNCALIBRATED starts as such. Missing value or authority stays null/unavailable, not a tuner's inferred starting value. The proposal-only registry work associated with #96 is a dependency, not recreated here. |
| Frozen protocol | Estimand and paired `decision_id` denominators; train/test/holdout cutoffs; with/without re-entry; incumbent **and hold-flat**; cost/stress model; dependence/multiplicity/search plan and registry-backed numerical settings frozen before results. No defaults for seeds, repetitions, windows, measured noise, purge/embargo, budget or cost. |
| Recorded evidence | Hash-bound immutable catalog/tape references, receipt/known-at clocks, PIT universe/coverage, whole-market labels/missed-movers and counterfactual/reflection references where the protocol needs them. An outcome is eligible only when resolved by `as_of`; unrecorded resolution is unknown. Labels and anecdotes are screening, never adoption. |
| Calibration | Original planned risk and exact cost/calibration bindings appropriate to broker/session/order shape. No reconstruction from current risk; no zero fees/slippage, simulated fill capacity or invented fill/latency model. Unsupported policy or uncalibrated stratum stays unavailable for the claim requiring it. |
| Trial custody | The one cumulative TrialLog's canonical snapshot and acknowledged custodian/writer from #102, including prior rejected/failed/pruned alternatives, total/effective-N provenance and tier/block-set identity. Missing history or writer blocks evaluation; no local empty ledger. |
| Resources | Approved compute/time/spend budget and concurrency ownership; at least the lane's 20 GiB MemAvailable floor. The memory floor is an operational requirement, not a research grid cap. Missing budget blocks evaluation; never invent a trial allowance or cap sim grids at nine neighbors. |

A read verifies the frozen hash before and after loading. References cannot be mutable `latest` pointers or unresolved historical Mac paths. No collector runs here, even GET-only. The owner of each producer supplies missing data through its existing path; this job reports the gap.

### Evaluation and cumulative accounting

1. Validate the request/bindings/resources without changing source artifacts. Record each missing prerequisite and emit an insufficient disposition, with no numerical recommendation for that target. One bad target must not erase another independently bound target's evidence; the batch remains partial/insufficient, not blanket PASS.
2. Before evaluating an alternative, obtain its arm-run receipt through the **one ledger custodian**. The tuner must not create another TrialLog, reset history for a date/code version, or claim a cumulative count from report length. If custody cannot acknowledge the attempt, do not begin it. Evaluation failures and rejected/pruned alternatives still reach that same ledger; a result lacking its accounting receipt cannot become a ready proposal.
3. Use the existing replay/rule/evaluator owners, on explicitly supplied immutable inputs. A parameterized ATR adapter does not stand in for a different exit policy, partial-fill lifecycle, ranking, sizing or rotation. Unsupported adapters report unavailable rather than approximate another policy.
4. Offline tuning evaluations are **MODELED**, even when their input episodes came from BROKER-PAPER. Retain the input provenance separately. An inference view contains one tier and one block set; do not mix sandbox/paper returns into replay or pool mismatched days. Preserve inference-time total/effective-N and history hash with the result. Re-running an evaluation is another counted attempt, not a fresh search history.
5. Link the evaluator's immutable outputs, including negative and inconclusive results. Money/price/quantity/risk stay Decimal or engine types; only the existing statistical-return boundary may use floats. Null n is unknown, not zero; missing returns are not zero-filled or silently dropped.

Use [#102's sanctioned inbox handoff](https://github.com/seathatflowsinourveins/sextant/issues/102#issuecomment-6691367000), not a new ledger API: `/home/sextant/sextant-data/<lane>-<issue>/<attempt>/<reserve|outcome>/`, with `manifest.json` and `rows.jsonl` (`sextant.ledger.handoff/1`). For this lane, use `nightly-114`; bind the lane/issue, kind, count, explicit tier and row hash. Submit the directory and both hashes on #102, wait for its ledger commit/N reservation receipt, then evaluate and hand back one outcome per reserved `arm_run_id`. FAIL/PRUNED carry no invented returns; the custodian closes each attempt once. The implementation is pending in [#110](https://github.com/seathatflowsinourveins/sextant/pull/110), which carries #96. Operational receipts on #102 do not establish that runner binding is landed in this checkout. Do not invoke `just ledger-append` or hold its deploy key from the tuning job.

The later L5 protocol in [ADR-0019](../adr/0019-validation-and-merit.md) remains the adoption authority: positive paired stressed-cost bounds over **both** comparators, circular whole-session cross-sectional blocks calibrated on training data, family StepM, cumulative-trial DSR/PBO, and the sealed confirmatory look. This design does not implement or weaken that evaluator. A screening proposal may ask for the missing experiment/calibration; it may not claim adoption gates passed or provide an authoritative parameter value when they are unavailable. Paper operation is not gated by these research verdicts.

### Output and permitted writes

Use the upstream immutable generation shape: explicit session date/run identity, `run.json`, `manifest.json`, evidence links and candidate output. Durable trial numbers remain in the ledger; narrative remains in the canonical handbook. A research receipt is an index into them, not a second canonical series.

Each run receipt must identify the request, session/cutoff, implementation/configuration/registry hashes, exact input hashes, tier/block set, frozen protocol, ledger receipts and inference snapshot, per-target disposition, reasons and output references. Unavailable fields remain null with a reason. Exit 0 means a receipt exists, not sufficient evidence, calibration or merit. Retain failed/insufficient runs; no mutable success-only latest pointer.

The write boundary is the run's research-artifact output, the sanctioned ledger **inbox** above and its proposal PR; only the custodian writes the ledger. The allowed PR changes are the immutable research receipt/index and source-backed research/handbook **proposal text**. There is **no registry patch**, profile/configuration change, broker/live deployment artifact, promotion record, runtime reload, canonical lesson append or direct ledger write in that PR. A read-only registry rendering, if the owner provides it, is labelled a snapshot; it is not a registry home and changes no active generation. Verify the boundary before committing/publishing, not only with prompt language.

Lesson candidates use the unchanged closed `northstar.handbook.lesson/1` contract: its 15 required fields, `source: nightly-tuning`, `status: open`, linked performance/learning evidence, null sample count when unknown and the precise supported origin lane. Optional `change.param/profile/from/to/registry_version` are research strings, not actions. Only include them when values are actually sourced; never fill missing numbers for schema convenience. Decision/resolution clocks stay in the outcome evidence; do not add fields to the closed lesson schema. Put complete candidates in the proposal PR body for the current single writer, **the lead until an owner-confirmed Paper B handover**. Do not call the appender, even against a run-local duplicate journal. Corrections supersede rather than erase negatives; route `contradicts_adr` to the lead, since an appender receipt is not delivered notification.

Use bounded public failure reasons; do not persist arbitrary loader/SDK exceptions, credentials, environment values or sign-in material. No call path constructs an account client or can reach a live endpoint. The runtime's own injected key is not a trading capability and never appears in outputs.

### Review, adoption and handoff

- A ready proposal opens **one** PR using the existing filled template and `just pr`, with squash auto-merge and normal ci/source/review guards. Link the immutable evidence, protocol, every trial receipt, calibration/authority limits and candidate disposition. A repeated identical publication request reuses its existing PR or no-change disposition; it does not start duplicate proposal branches. Actual reevaluations still count as new ledger attempts.
- Insufficient evidence without a justified research-document change produces a sourced no-change/unavailable report on #114, not a cosmetic PR. A previously unknown value remains unavailable after that report.
- The consuming-runtime owner, not this job, may later author a **separate** L3/L5 reviewed adoption change. It must revalidate the exact registry base/hash and record the between-session window before activation. If a session started or the base changed, defer/revalidate; never treat proposal merge as a window receipt. Live promotion remains ADR-0020's separate authority and is outside this job.
- For this native-roster workflow, post the PR number, verification and any pending checks on #114, then hand the branch to **roster-ops**. Roster-ops runs `just ao claim <PR>` after ci completes, green or red; the worker never claims or sends orchestration commands. `consumer_fenced` is expected for a plain roster tab, not a task blocker. No `checks --watch`, GitHub polling or sleep/retry loop; only the dispatcher reports an actual claim receipt.
- Gather all review comments and failed checks into one fix batch with local proofs green and one push per batch. Stop branch writes at handoff; after AO claims, AO is the only writer. The job never merges manually, bypasses a check, or cancels/resizes an owner's order.

## Source conflicts: deliberately not carried

| Legacy source behavior | Sextant disposition |
|---|---|
| Paired paper-lane agreement and `min_common_window >= 20` | Not L5 adoption. Freeze the later estimand/denominators/protocol; no default 20-session authority or implicit inert C. |
| One-to-nine neighboring values | Do not import. The carried owner residual leaves sim grids uncapped; resources still need an explicit budget. |
| Implicit train/test sizes, seed 7, bootstrap 999, assumed fees, rule-constructor defaults | Not authority. Bind reviewed registry/protocol/calibration explicitly or stay unavailable. |
| `tuning.py`'s fallback canonical lesson append and direct TrialLog writes | Use only the runner's candidate-only seam; integrate the existing designated ledger writer, not these alternate write paths. |
| Recipe suggesting rehearsal output roots outside cumulative history | Output isolation may protect production artifacts, **not erase evaluated alternatives**. Synthetic rehearsal is labelled synthetic; actual evaluated arms always count cumulatively. |
| Numeric results embedded in lesson prose; legacy `accepted` outcome | Link canonical evidence instead. `accepted` is not adopted, calibrated, deployed or promoted. Do not translate it into a passing L5 result. |
| Upstream supervised-run TSV / old render-only scheduler | Historical source only; reuse Orca, not a new supervision journal or an old scheduler bypass. |

## Proof obligations and present evidence

No runtime was added, so a prose/string-matching test would prove neither L4 isolation nor a nightly run. The implementation must carry these **behavioral** witnesses through its real entry point, using isolated artifacts and deny-by-default network access. They are acceptance criteria, **not passing tests in this design PR**.

| Scenario | Required observable result |
|---|---|
| Complete synthetic recorded request | Immutable receipt/candidate output; original registry, runtime configuration and lesson journal byte-identical; no broker/network invocation; synthetic provenance explicit. |
| Manual run with missing authority, value, budget, calibration, tape or ledger custody, each separately | Same insufficient result as scheduled entry; missing value remains null, no evaluation/proposal parameter or registry write. Manual precheck bypass grants nothing. |
| One session's anecdote, future/unresolved outcome, unsupported policy or mutable/hash-mismatched input | No adoption claim or fabricated result; recorded reason and no authoritative parameter recommendation. |
| Mixed MODELED/SIMULATED/BROKER-PAPER or mismatched block sets | Refused inference. Replay over paper inputs remains MODELED with separate input provenance. |
| Rejected/failed/pruned arm and a second date/code/optimizer run | All attempts retained in the same ledger; increasing cumulative accounting, frozen inference snapshots, no history reset or tier pooling. |
| Missing return/cost/noise or only one ready target in a batch | Null/insufficient for the affected target, no zero imputation, no blanket batch PASS; independent target evidence retained. |
| Repeat publication; repeat evaluation | Existing proposal/no-change reused for the former; a distinct counted attempt for the latter. No lost negatives. |
| DST change, holiday, no-tape day, early close and next session already running | Correct dated completed-window identity; no fixed UTC shift, invented data, activation or orders. |
| Attempt registry/config/lesson/ledger mutation through normal or reviewed-write callbacks | Denied before publication; checksums unchanged, no invocation of canonical writers. Ledger operations use only the designated custodian seam. |
| Proposal PR merges while a session is open | Runtime generation and parameters unchanged. A later, separate adoption path requires its own current evidence and between-session receipt. |

Available seam proofs are `tests/proofs/test_reflection.py` (existing reflection separation/precheck behavior), `tests/proofs/test_harvest.py` (carried pins) and the normal repository/source/budget checks. Run them unchanged for compatibility, not as a claim that the future tuner meets the table. A temporary-home invocation of the existing reflection precheck can demonstrate its no-event skip without touching its real watermark. Verification results belong in this PR's How verified section; no operational nightly receipt is claimed.

## Implementation handoff and unavailable prerequisites

The implementation owner first binds the consuming registry (#96), single TrialLog custodian (#102), frozen replay/evaluator adapters, data-ready/resolution clocks, calibration and approved resources. Then carry only the recorded-input/candidate-generation seam into Sextant's reflection area, with the behavioral witnesses above. Add the distinct Orca prompt/precheck/disabled installer under `deploy/wsl/` only after the sandbox dispatch binding is proven. Reuse the reflection install convention and `just pr`/AO path; do not edit reflection's watermark or canonical appender. No dependency, daemon, client, scheduler or numerical store is introduced by this design.

Activation requires an implementation PR with those receipts and proofs, a reviewed stable-main entry point, a demonstrated devc/Orca launch, explicit schedule/provider/resource authority and the lead's enable decision. The schedule, data/calibration/protocol/budget readiness, registry/ledger runtime integration and end-to-end learning efficacy remain **unavailable/unverified** here. Their absence blocks execution, not completion of this design deliverable.
