# Fills before order history implementation plan

> **For agentic workers:** Use superpowers:executing-plans; native execution only.

**Goal:** Count unlisted fills older than the venue's order history while retaining
in-window refusal and the engine's unexplained-position startup stop.

**Architecture:** Change only the existing Alpaca fill-coverage boundary and its
aggregate startup trace. Native order inference, reconciliation and gate own state.

**Tech Stack:** Pinned NautilusTrader rc8, alpaca-py 0.44.0, Decimal, pytest.

**Spec:** LEAD-1721, 2026-11-11, stage 1 run 3 second cause.

## Global constraints

- Work alone; local commits only, no push, PR, broker or key access.
- Source net at most +30 lines; raw diff under 45,000 bytes against main.
- No report from historical activities; no lookback, budget or gate changes.
- Diagnostics contain counts only, never venue identifiers or monetary/time values.
- Coordinator clarification: 8,822 = 400 explained + 8,422 pre-history; 398 of
  the 400 explained fills are in unloaded names (the distinct skip count).
- The initial origin/main was d42872a7; #693 later merged as 1dfb44ce with the
  supplied base's exact tree. Cut onto that fresh main; shared teardown is not there.

## Upstream first

**BUILD ON** nautechsystems/nautilus_trader@d53849b216e20f2c122ca01b4dd0da377638b186
`crates/adapters/architect_ax/src/execution.rs:1676-1695` and
`crates/adapters/coinbase/src/execution.rs:751-782`: native fill hooks bound reads
by command start/end without an order-listing cross-check. **USE AS IS**
`crates/live/src/node/mod.rs:992-996`: unresolved positions abort startup.
**KEEP OURS** the existing in-window per-fill refusal, as scoped in LEAD-1721;
the official adapters ship no equivalent listing-coverage check. Searched those
generators and adapter execution paths for generate_fill_reports/start/end;
alpaca-py@cc4cb3b7ba50ae250e621983c2779047fb16bb28
`alpaca/trading/models.py:214-216,241` and `requests.py:202-208` define submitted
times and nested listings. No dependency, engine state machine or pager is rebuilt.

## Review focus

- Equality to the oldest submitted time is in-window; compare nanoseconds.
- An older listed fill still refuses excess cumulative quantity.
- Empty or unusable history never authorizes a pre-history skip.
- Counters reset per invocation and disclose no fill/order payloads.
- A pre-history-only holding cannot pass native startup or the existing gate.

### Task 1: coverage boundary and diagnostic counts

**Files:** Create `tests/proofs/custody/test_alpaca_before_order_history.py`;
modify `src/sextant/alpaca/execution.py`, `src/sextant/paper/node_order.py`,
`docs/manifest.md`, `docs/handbook/practices.md` and generated `llms.txt`.

**Interfaces:** Existing `_generate_fill_reports(command)` returns no activity-derived
reports; `report_trace['fills']` and `startup_cause` expose aggregate counts.

- [x] Write run-3 node/gate proof plus recent-unlisted, excess, empty-listing and
  unexplained-position refusal proofs; add strict-boundary and reset cases.
- [x] Run focused pytest before source changes and preserve RED output.
- [x] Add an oldest-submission boundary for unlisted rows only, with pre-history,
  unlisted-order and excess-quantity counts in receipts and ERROR output.
- [x] Run focused GREEN, update manifest/lesson, regenerate index and run ci-local.
- [x] Review complete diff, measure source/raw sizes, commit locally and report.

Skills: orchestration; writing-plans; systematic-debugging; test-driven-development;
executing-plans; verification-before-completion; requesting-code-review (prepare
handoff for coordinator's separate review, no helpers authorized);
finishing-a-development-branch (keep this branch and worktree as instructed).

Ruling: use a five-second fixture run for 89 paced pages plus the final paced account
verification; the two-second fixture default stopped before verification. No production
pacing or timing changed. RED: 7 failed; focused GREEN: 7 passed.

Ruling: collect failed native-node cycles in this module's fixture teardown after a
combined run failed the next module's LiveNode build (117 passed, 1 failed). This uses
the existing native proof cleanup pattern; the separate shared teardown fix is not
on origin/main at d42872a7 and is not imported from its unmerged branch.

Ruling: #693 merged as 1dfb44ce while verification ran, with the supplied base's
exact tree. Rebase only this task's commits onto that squash so the review window
contains this task alone. Combined regression GREEN: 118 passed, 1 vendor warning.

Verification: ci-local exit 0; 4,961 passed, 9 xfailed, 140 warnings; ruff, pyright,
zizmor, shellcheck, actionlint, budgets and gitleaks passed. Source delta +18 net.
Final review: author review against the skill template; independent max gate review
is a coordinator handoff because this task explicitly forbids helper workers.
