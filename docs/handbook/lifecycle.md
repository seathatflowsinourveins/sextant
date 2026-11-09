# Delivery lifecycle

One stage, one owner. The 25 pinned skills are shared by dsh and the lane runtimes (`deploy/wsl/lane-runtimes/parity.json`); Claude loads the same 25 from its shelf (`.claude/shelf.lock.json`) and the full compound-engineering plugin beside them. This page routes the rules in [practices](practices.md) and [ADR-0001](../adr/0001-sextant-foundation.md); it adds none.

| Stage | dsh | Claude | Gate |
|---|---|---|---|
| Frame | `brainstorming` | `brainstorming` | the question, its non-goals and the owner's words |
| Plan | `writing-plans` | `writing-plans` | the plan is on record before code |
| Isolate | `using-git-worktrees` | `using-git-worktrees` | one task, one Orca worktree |
| Implement | `test-driven-development` | `test-driven-development` | a failing test first |
| Debug | `systematic-debugging` | `systematic-debugging` | root cause before a fix |
| Review | `requesting-code-review` then `receiving-code-review` | the same pair, plus `ce-code-review` for a report-only full review | findings answered, or rejected with a reason |
| Verify | `verification-before-completion` | `verification-before-completion` | the command and its output, not a claim |
| PR | `finishing-a-development-branch`, `just pr` | the same | `ci`, `source` and `review` pass (ADR-0001) |
| Feedback | `receiving-code-review`; the `gh` CLI for threads and failed jobs | `ce-resolve-pr-feedback`; the `gh` CLI | every thread resolved or answered |
| Learn | `ce-compound` | `ce-compound` | a lesson in `docs/handbook/` or the append-only lessons |
| Land | squash auto-merge, then Orca worktree removal | the same | GitHub shows MERGED and the head is the PR's head |

## Review routing

- Both families request a review with the Superpowers pair. A review is report-only until the invoker asks for the fix, and receiving one answers every finding or rejects it with a reason.
- Claude adds `ce-code-review`, a report-only pipeline of personas, a validator and a rendered report. It reads its artifact root from `.compound-engineering/config.yaml` (default `docs`), dispatches through the host's subagent and collection semantics, and starts its cross-model peer through compound-engineering's own scripts.
- `ce-code-review` is not copied into dsh. The copy would bind a second owner to compound-engineering's config and peer route, and dsh would fail at a route it does not have. Reopen: compound-engineering publishes a harness-neutral review entry (documented non-Task dispatch and no CE config), then a leg and a row.
- The PR gate is family-blind: one other family reviews, as ADR-0001 routes; live promotion keeps its separate exact-SHA two-family requirement. A session skill outside the 25 is not routed here; a stage's owner is a pinned skill or the native tool in its row.

## Feedback and learning

The `gh` CLI reads review threads and failed job logs natively ([manual](https://cli.github.com/manual/), read 2026-11-09), so neither family needs a plugin for the feedback stage. A lesson lands with the PR that taught it, in `docs/handbook/` or the append-only `lessons.jsonl`; `ce-compound` is the skill that turns the solved problem into that artifact. A stopped practice is deleted, not left as a fallback.
