# Practices

*The working practices that survived the harvest. Each line names the record it comes from; a practice with no source is dropped.*

## Rank

- Publish a full-market ranking generation at most once per `publish_min_interval_s`; a missing, stale or invalid generation means no entry, with no fallback. [ADR-0003](../adr/0003-ranking-and-feeds.md)
- Score `move × dvol_ratio` against the symbol's own time-matched segment baseline, ties by `trades_accel`; dollar volume, share count, price and trade rate never form the score. [ADR-0003](../adr/0003-ranking-and-feeds.md)
- Measure the move from the latest completed, split-adjusted official regular-session close, and record the RTH open-based move separately. [ADR-0003](../adr/0003-ranking-and-feeds.md)
- Keep SIP and BOATS denominators, source identity and coverage separate; an unknown coverage is unknown, not zero. [ADR-0013](../adr/0013-us-equity-data-stack.md)
- Carry latency labels — publication, vendor receipt, local receipt, generation, entry-eligible, submission — on every ranking record. [ADR-0003](../adr/0003-ranking-and-feeds.md)

## Enter

- Enter the first leg: a non-decreasing run of eligible trades inside `first_leg_window_s`, no more than `first_leg_max_move` above the quiet price; a lower trade restarts the run. [ADR-0004](../adr/0004-entry.md)
- A missing ATR or VWAP makes extension UNKNOWN, never "not extended"; a fresh spike high is never the entry. [ADR-0004](../adr/0004-entry.md)
- Freeze the buying-power basis at segment start with the segment identity; no read of buying power means no entry. [ADR-0004](../adr/0004-entry.md)
- Send LIMIT at the ask, `extended_hours` outside RTH with `time_in_force` `day` or `gtc`, reprice at most `entry_chase_bps`, cancel at `entry_ttl_s`, never market. [ADR-0004](../adr/0004-entry.md)
- Size from planned risk, not from conviction: `stop_distance = entry − initial_trigger + chase_cap_fraction × entry`, bounded by fresh buying power and a flow-share cap. [ADR-0004](../adr/0004-entry.md), [ADR-0011](../adr/0011-sizing-and-auto-leverage.md)
- Keep mover slots `ceil(0.4 × cap)` and hold the top `3 ×` quota in the candidate pool; custody fills first, potential fills second, unused mover slots pass over. [ADR-0024](../adr/0024-extreme-mover-ranking-and-early-entry.md)

## Protect

- The trigger starts below entry and only rises; keep the setup gap until arming and never rebase an adopted position to the mark. [ADR-0005](../adr/0005-exit-engine.md)
- Every in-gain holding gets broker-held protection that follows the gain — a replaced OCO/bracket stop or one native trailing stop — including reconciled owner fills on B; this is the required policy, not proof of continuous installed protection. B retains its separate cancel-first policy and handover gaps. [ADR-0025](../adr/0025-gain-protection-and-fast-exit.md)
- Arm only on a completed confirmation at `entry + c_RT + noise_floor` with an executable price strictly above the armed trigger; an unknown cost basis, custody or quote stays UNARMED. [ADR-0005](../adr/0005-exit-engine.md)
- Never sell on one quote, print or bar: a breach needs `breach_persist_count` observations over `breach_persist_span_s`. [ADR-0005](../adr/0005-exit-engine.md)
- Chase with one managed LIMIT at `max(bid, last × (1 − chase_cap_fraction))`, at most once per `chase_min_interval_s`, serialized; an acknowledgement is not a fill. [ADR-0005](../adr/0005-exit-engine.md)
- Raise the native backstop in place, never lower it; a DAY order does not flatten inventory, and an outage freezes the backstop at its last acknowledgement. [ADR-0005](../adr/0005-exit-engine.md), [ADR-0020](../adr/0020-live-lane.md)

## Re-enter

- Wait for a flat receipt: broker net quantity zero plus terminal lineage for the entry and every protection. [ADR-0006](../adr/0006-reentry-and-rotation.md)
- Retry the same symbol inside `retry_rank_band`, rotate to a better unheld name inside `rotation_rank_band`, otherwise wait. [ADR-0006](../adr/0006-reentry-and-rotation.md)
- Buy a reclaim only on a pullback, a held higher low and a hold, at most `reclaim_max_above_buffers` buffers above the level; never the first print. [ADR-0006](../adr/0006-reentry-and-rotation.md)
- Rotate a held name only when `expected_lift > 2 × c_RT ÷ price + rotation_lift_margin_bps ÷ 10,000`. [ADR-0006](../adr/0006-reentry-and-rotation.md)
- Paper retries are unbounded and ungated; live is `live_nonrenewing` at 1× with retry and rotation OFF until a separate promotion. [ADR-0006](../adr/0006-reentry-and-rotation.md), [ADR-0020](../adr/0020-live-lane.md)

## Custody and budgets

- The owner's orders are never cancelled, sold back, resized or adopted; a reconciled owner fill is claimed within `claim_max_latency_s` and protected at once. [ADR-0007](../adr/0007-custody-and-order-writing.md)
- One writer and one pacer per account, one exit per quantity, never a second full-size exit; a foreign order or a quantity mismatch freezes the symbol and pages. [ADR-0007](../adr/0007-custody-and-order-writing.md)
- Recheck paper submission admission after durable registration, excluding only that request's own reservation; a refusal retains lineage and emits no native command or wire accounting. [ADR-0007](../adr/0007-custody-and-order-writing.md), [shared-node regression](../research/2026-11-06-shared-paper-node.md)
- SELLs require row-8 custody readiness and enough unreserved residual before and after registration; an account callback cannot grant missing custody or bypass an unreported exit. [ADR-0007](../adr/0007-custody-and-order-writing.md), [flatten witness](../research/2026-11-06-shared-paper-node.md)
- Refuse known native validation before accounting without an account halt; once the accounting hook starts, errors retain the unknown-outcome halt. Unexpected and admission errors still halt. [ADR-0009](../adr/0009-order-rate-limits.md), [native boundary witness](../research/2026-11-06-shared-paper-node.md)
- Pace every wire action with priority CANCEL > REDUCE > MODIFY > QUERY > SUBMIT, reserve protection capacity per open and exiting position, and back off on 429. [ADR-0009](../adr/0009-order-rate-limits.md)
- Use about 80% of a lane's action budget over a session, run protection first, and investigate a 15-minute zero-action session rather than forcing a trade. [ADR-0002](../adr/0002-philosophy-and-lanes.md)
- Paper observes the guard; live enforces it, and an unknown gate identifier enforces and logs an error. [ADR-0010](../adr/0010-risk-guard-pacing-and-halt.md)

## Sessions

- Follow the XNYS calendar with actual early closes; outside regular hours every order is LIMIT-only, and A's tiers trade at half risk. [ADR-0002](../adr/0002-philosophy-and-lanes.md)
- Paper runs 24/5 and carries no conservative profile: each arm runs the full factor stack, every factor set has a paired with/without arm, and paper P&L alone still decides nothing. Replay and evaluation run 24/7, with closed markets used for replay, stress, reflection and proposals. [ADR-0018](../adr/0018-evidence-and-learning-loop.md)
- Ask which clock a number came from — historical minute bars end at start + 1 minute, daily bars at the next New York midnight, live bars at receipt — and never clamp a signed skew. [ADR-0013](../adr/0013-us-equity-data-stack.md)

## Evidence and learning

- Reconcile selected seeds without changing their weekly/daily selection, raw missingness or dated tickers. An unrepresented session is not a negative, selected losers are not ordinary controls, and unknown availability or cumulative trials remain null. [ADR-0027](../adr/0027-extreme-gainer-research-package.md); [lesson and witness](candidate-history.md)
- Every exit leaves its counterfactual: hold-to-now, matched hold-flat, managed policy, managed plus re-entry, and each shadow arm, with n, censoring and costs at 1× and stressed. [ADR-0018](../adr/0018-evidence-and-learning-loop.md)
- Each tunable value has a registry row and source. A sourced value without calibration is an uncalibrated starting value, never measured success. If the value or its authority is missing, keep it unavailable; fixtures supply no default authority. Reviewed changes occur between sessions, and nightly tuning only proposes. [ADR-0018](../adr/0018-evidence-and-learning-loop.md) B's quote simulator refuses missing chase rows before adoption. [B witness](../research/2026-11-06-owner-b-manager.md)
- Separate source-component parity from admission: a posterior is not an alarm or a completed-window screen a rank/first-second trigger. Runtime mappings govern behavior and hashes; carry coverage/source evidence through each window and bind interpreted paper conventions. [#130 source/admission contract](../../lanes/research/detector-adapters.md); [review lesson and witnesses](detector-components.md)
- One cumulative trial ledger, tiers never pooled, history never reset, rejected variants kept. [ADR-0018](../adr/0018-evidence-and-learning-loop.md)
- Adoption needs a dependence-aware lower bound above the incumbent and above hold-flat at stressed costs; otherwise keep the incumbent and record the negative. [ADR-0019](../adr/0019-validation-and-merit.md)
- Merit is ≥30 independent round trips over ≥5 sessions at PSR ≥ 0.95 with replay correlation ≥0.9 and slippage ≤1.5× modelled; it produces a draft, never a promotion. [ADR-0019](../adr/0019-validation-and-merit.md)
- Nightly reflection and tuning write proposals only; a label or a one-day anecdote never adopts a change. [ADR-0018](../adr/0018-evidence-and-learning-loop.md)
- Read outcomes only as of the cutoff; keep superseded and negative lessons. [ADR-0018](../adr/0018-evidence-and-learning-loop.md)

## Harness

- One manifest row per pick or practice, with pin, application and `just prove` command; nothing enters without one and a stopped practice is deleted. When merging parallel lane work, retain main's rows and append the lane's new rows at the end of their existing section. [ADR-0001](../adr/0001-sextant-foundation.md); lead direction for [PR #70](https://github.com/seathatflowsinourveins/sextant/pull/70), 2026-11-06; [merge lesson](retrieval.md)
- A PR lands through squash auto-merge only when ci, source and review pass. Danger enforces the manifest/source rule in source; gh-aw supplies review. These run from the base branch, so the PR cannot change its own checks. A branch-only `just ci` pass does not validate CI's merged tree: retain both branches' registered proofs when resolving conflicts, then test the combined tree. [ADR-0001](../adr/0001-sextant-foundation.md)
- Keep always-loaded rules short and enforce boundaries instead of hooks; the only hooks are the secret scan and the skills runtime. [ADR-0001](../adr/0001-sextant-foundation.md)
- Agent sessions remain local. ci, source and gh-aw review run on GitHub-hosted runners; ci executes PR code with a read-only token, no secrets and no caches. A local runner is deferred until a job needs a private network or broker connection. [ADR-0001](../adr/0001-sextant-foundation.md)
- After a lane worker hands off, AO is the branch's only writer for CI/review fixes. Claiming records ownership only: check out the PR head and confirm its SHA before editing. [AO hand-off evidence](../research/2026-11-06-agent-orchestrator.md)
- Run harness proof subprocesses with explicit fixture environments; inherited Bash functions or startup files must not replace fake tools with the running service. [AO proof isolation](../research/2026-11-06-agent-orchestrator.md#offline-proof-isolation)
- Probe a replacement router key before publishing its sealed value; a failed probe keeps the previous sealed bytes and router key. Check both in the regression. Hermes's gateway and sessions keep their launch key, so relaunch its clients and restart its gateway before revoking. [Renewal lesson](omni-keys.md)
- Only the owner signs in, stores external keys and approves/applies live limits. The owner may halt at any time; the sanctioned guard and runner also halt automatically under their recorded causes, and the lead promotes, stages and demotes with a record. [ADR-0020](../adr/0020-live-lane.md)

## Lessons from the clean distro's first day (2026-11-06, lead)
- **Make setup steps converge, never skip.** A step that does nothing once its target exists never delivers later fixes: the daily sweep kept its first prompt until `lifecycle.sh` learned to edit in place (#55).
- **No shared list that every lane appends to.** One `testpaths` line naming proof files made every lane PR conflict with every other. Configure by directory and marker once (#92).
- **Measure the right column.** A memory floor written as "free" paused two lanes while 45 GB was available; say MemAvailable ([issue #44](https://github.com/seathatflowsinourveins/sextant/issues/44)).
- **One shared token is one budget.** About 20 agents polling GitHub REST emptied 5,000 requests in under an hour. AO's ETag-guarded polls were not the cause; loops in lanes were. No polling, GraphQL reads first ([issue #44](https://github.com/seathatflowsinourveins/sextant/issues/44)).

