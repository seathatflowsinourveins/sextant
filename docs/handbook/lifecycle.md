# Delivery lifecycle

One stage, one owner. The 25 pinned skills are shared by dsh and the lane runtimes (`deploy/wsl/lane-runtimes/parity.json`); Claude loads the same 25 from its shelf (`.claude/shelf.lock.json`) and the full compound-engineering plugin beside them. This page routes the rules in [practices](practices.md) and [ADR-0001](../adr/0001-sextant-foundation.md) and holds the delivery process: the stage table, [review routing](#review-routing), and the board, protected-module, owner-direction, settings, relaunch, handoff and consolidation sections below. Each section names its source.

| Stage | dsh | Claude | Gate |
|---|---|---|---|
| Frame | `brainstorming` | `brainstorming` | the question, its non-goals and the owner's words |
| Plan | `writing-plans` | `writing-plans` | the plan is on record before code |
| Isolate | `using-git-worktrees` | `using-git-worktrees` | one task, one Orca worktree |
| Implement | `test-driven-development` | `test-driven-development` | a failing test first |
| Debug | `systematic-debugging` | `systematic-debugging` | root cause before a fix |
| Review | `requesting-code-review` then `receiving-code-review` | the same pair, report-only `ce-code-review` and native `/code-review` pending #180's measurement below | findings answered, or rejected with a reason |
| Verify | `verification-before-completion` | `verification-before-completion` | the command and its output, not a claim |
| PR | `finishing-a-development-branch`, `just pr` | the same | `ci`, `source` and `review` pass (ADR-0001) |
| Feedback | `receiving-code-review`; the `gh` CLI for threads and failed jobs | `ce-resolve-pr-feedback`; the `gh` CLI | every thread resolved or answered |
| Learn | `ce-compound` | `ce-compound` | a lesson in `docs/handbook/` or the append-only lessons |
| Land | squash auto-merge, then Orca worktree removal | the same | GitHub shows MERGED and the head is the PR's head |

## Review routing

- Both families request a review with the Superpowers pair. A review is report-only until the invoker asks for the fix, and receiving one answers every finding or rejects it with a reason.
- Claude adds `ce-code-review`, a report-only pipeline of personas, a validator and a rendered report. It reads its artifact root from `.compound-engineering/config.yaml` (default `docs`), dispatches through the host's subagent and collection semantics, and starts its cross-model peer through compound-engineering's own scripts.
- Claude Code 2.1.321's built-in `/code-review` takes a diff, PR number or branch, an effort level and `--comment` to post findings inline. A Claude-family writer runs it on its branch before `just pr`; a Claude local cross-family reviewer runs it on the branch or PR under review. Default `high`; `xhigh` on `src/sextant/paper/`, `src/sextant/execution/`, `src/sextant/exits/`, `src/sextant/risk/` and `.github/`; `max` only on the owner's word, as the native skill requires.
- Its findings follow the [landing verdict rule](../../.github/workflows/shared/review-rules.md#report) unchanged: only Always-P0 or a concrete failing witness at the exact head blocks; everything else goes to one follow-up issue per PR; from the third reviewed head, only P0 blocks.
- Once #180 lands, compare `/code-review`, `ce-code-review` and the Superpowers pair on the same known-defect set; that measurement decides the Claude Review row's one owner. Until then they run beside each other by the owner's word, not a claim of measured superiority. The lead's first use is once on #197 at `xhigh` with inline findings; afterward this is the reviewers' step, not the lead's.
- Every local review brief names the pinned upstream path and asks whether upstream has moved since the pin in a way that changes the PR. The weekly hosted panel remains the landscape check.
- `ce-code-review` is not copied into dsh. The copy would bind a second owner to compound-engineering's config and peer route, and dsh would fail at a route it does not have. Reopen: compound-engineering publishes a harness-neutral review entry (documented non-Task dispatch and no CE config), then a leg and a row.
- The PR gate is family-blind: one other family reviews, as ADR-0001 routes; live promotion keeps its separate exact-SHA two-family requirement. A session skill outside the 25 is not routed here; a stage's owner is a pinned skill or the native tool in its row.

## Standing authority

The owner, verbatim, 2026-11-09, in the lead's 17:59 EST standing-delegation ruling (SHA-256 `4ab39a83c800866c43416c5ea878a8d7ff3aa8adad811df52163a83686d34ecd`):

> "should we stop all lanes and start a clean sota env with the new era clean sota workflow with every adhrs form sota convergenced repos? and please proceed wiht the sota decision making as long as they are evidance andresearch convergneced sota driven,we can make it as part of our standing rules with prs,/code-review etc also using the sota repos upstream to make sure they land cleanly to be sota aligned at current landscape"

That ruling records the evidence-led delegation, owner-only reservations, draft hold and single lander now in `AGENTS.md`, and the native review step above. GitHub's [changing the stage of a pull request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/changing-the-stage-of-a-pull-request), read 2026-11-09, supplies the hold: a draft cannot merge until marked ready. Restricting who marks it ready and who merges is the owner's policy, not a GitHub permission claim. The review source is the installed Claude Code 2.1.321 runtime's built-in `code-review` skill; upstream release [anthropics/claude-code@v2.1.321](https://github.com/anthropics/claude-code/tree/a4fcccc70a89df6607e66cc30682d551269d0680), `a4fcccc70a89df6607e66cc30682d551269d0680` (`CHANGELOG.md:3-5` identifies the release), checked 2026-11-09. This adds no plugin or hosted gate.

## Feedback and learning

The `gh` CLI reads review threads and failed job logs natively ([manual](https://cli.github.com/manual/), read 2026-11-09), so neither family needs a plugin for the feedback stage. A lesson lands with the PR that taught it, in `docs/handbook/` or the append-only `lessons.jsonl`; `ce-compound` is the skill that turns the solved problem into that artifact. A stopped practice is deleted, not left as a fallback.

## Board and worktrees

A task's card moves to `in-review` when its PR opens and to `completed` when the PR merges; the worker's hand-back or Landing's merge note triggers the move, not a later sweep. A lane parent carries one state line, refreshed when the lane changes. The owner's attention is an unread dot plus the tab name in the lead's message until the tab is brought forward. The sweep's own steps stay in [the lifecycle prompt](../../deploy/wsl/lifecycle-prompt.md).

Authority: LEAD-1712-board-consolidation.md, SHA-256 `2e83e8e370b2e262c6a8a892e2430892bb6a9904e2a95feff9821d7dd16c8421`.

## Protected modules

Before proposing to delete or move a module, check it against this list and against every open plan under the private handoffs that names a `src/` path. "Imported only by tests" is not "unused" while a plan of record depends on the module: the 2026-11-09 IBKR Paper A plan builds its node on `sextant.paper.native` and `sextant.paper.runtime`, and the two were nearly retired on that test-only reading. Protected until the IBKR lane lands or the lead rules otherwise:

`sextant.paper.native`, `sextant.paper.runtime`, `sextant.paper.ibkr`, `sextant.paper.c_session`, `sextant.entry.surge`, `sextant.entry.signals`, `sextant.entry.parameters`, `sextant.entry.orders`, `sextant.execution.alpaca`, `sextant.risk.guard`.

`sextant.paper.ibkr` is loaded by a proof through `import_module`; `sextant.execution.alpaca` carries `OrderCommand` for the PR-4 translator; `sextant.risk.guard` is the PR-6 guard. A proposal that touches a protected module stops and comes to the lead.

Authority: LEAD-1722-protected-modules.md, SHA-256 `9ec44f7e4e3dcb0e98393740f14f2d4f0d50ae62901440cf78f611c1005350ed`.

## Owner directions

The owner's directions are recorded as professional engineering requirements, not raw quotes. Each entry carries a D-number and five fields: requirement, scope, constraint, reading and check. A brief, PR body, ADR or handbook page cites the requirement and its D-number; it does not copy the owner's words into a new record. The working record is `OWNER-DIRECTIONS.md` in the private handoffs, newest first. Older records keep the quotes they already carry.

Authority: LEAD-2358-msg-owner-directions.md (direction D-12), SHA-256 `4bb0c15bdf85d282b42c1a3defd85a275e1ed2f4551459a734e1a9964f6e10fa`.

## GitHub settings

The tracked recipe is `.github/rulesets/apply.sh`. It applies `main.json`, `live.json`, `ledger.json` and `environments.json` through the GitHub REST API; `environments.json` gives the four environments their branch policies (review, hosted-workers and paper allow `main` only; live allows `live` only) and creates them empty, so secrets stay the owner's. `tests/proofs/test_foundation.py` proves the recipe and those policies. The one-time application on 2026-11-09 created the live ruleset and all four policies, and read them back.

Authority: LEAD-2346-msg-245-applied-258-fix.md, SHA-256 `e34d3d817ad14a79a5c627db07ad3d77b889f811b3489b0f8bc07aa32446ded6`; LEAD-FABLE-1939-d5-rulings.md, SHA-256 `21a3f1f1041967bd6037e798e65ecae64648afe297e0a4e455737f2abb54766d`, landed by #245 at `630f106`.

## Relaunch runbook

The relaunch happens when all seven conditions hold, and it waits for nothing else:

a. #258 merged and the runtime doctor green on the host; every runtime row is proven as launched.
b. The model-and-effort table (#267) merged: one table of work, runtime, model and effort in ADR-0030, `AGENTS.md` and the ecosystem map, so the shared settings carry the role levels and the local overrides can be deleted.
c. Compaction native: merged (#260, `5830f0e`). Done.
d. The role-launch PR (PR-2) merged: each role is a checked-in launch definition, so a role starts on its model, effort and first reads with one command.
e. The consolidation PR is merged: the repository frames the practice by itself.
f. Cutover steps P3.8 to P3.12 are done.
g. B and C are running untouched; the relaunch never stops a paper runner.

Then: role sessions write their state; the lead freezes dispatch on events; fresh sessions start from main through the launch definitions; the doctor runs at session start; the local settings overrides and the ruling files' working role end. The files stay as history, indexed by the inventory.

The hard-lines receipt behind the gate is 168 probes: 94 executed probes, run in ten-per-session batches across ten sessions, with no reruns, and 74 matcher-only probes. `deploy/wsl/hard-lines/claude-receipt.json` records the sessions, the 94 executed and the 74 matcher-only entries. An earlier note that said three sessions was a miscount.

Authority: LEAD-2359-consolidation-and-relaunch-gate.md, SHA-256 `1f357de2cf709978d46800eb1632c8adaf4841916c84a156e4bd2328b9432d1a`; the cutover plan is LEAD-1745-fable-era-harness-and-clean-relaunch.md, SHA-256 `8f15f99f5b0df6b4efedc79fe515833a2350bf9d0805f2a768b2cea5b30c4d55`; the receipt is LEAD-0028-msg-accepted-automation.md, SHA-256 `b4298d247474b224df780022e3c40451044a0148b7669328f344af4357645189`.

## Handoff index

The rulings whose operational reports still live outside the repository, under the private handoffs. This index names each one; the report is the record.

- `LEAD-1602-owner-asks-and-trading-lead.md`, SHA-256 `495237a16983756456b84b0d5277e29e4d2823522ea8993d085c464a56a9b3e0`: the owner-ask list and the handover to the trading lead; the ask list is the ruling file.
- `LEAD-FABLE-1634-readiness-rescore.md`, SHA-256 `52039c550aacc7a3fc0a856537970495a8ac4319e77397e664a50c2cf525f1bc`: the readiness re-score; the report is `tasks/readiness-rescore/REPORT.md`.
- `LEAD-FABLE-1720-ibkr-approved.md`, SHA-256 `1f3d01fadf1682363be2235f6431c1a32b32c9dd11762d04e3d13d9d9d8e9c99`: the IBKR Paper A approval; the plan is `ibkr-paper/PLAN.md`.
- `LEAD-FABLE-2016-b-exit-incident.md`, SHA-256 `ad85fbf6f0922860cee8974171da7a3015a36334be279cac793036655960f898`: the B-EXIT-1959 incident dispatch; the report is `tasks/b-exit-1959/REPORT.md`.
- `LEAD-FABLE-2144-tv-wait-codex-verdict.md`, SHA-256 `f2e554ab02b914441f7b202c6fc2e15b881fcc0a8fea6f046704b02a72c49259`: the TradingView wait and the Codex verdict; the verdict is `tasks/b-exit-1959/codex-review-verdict.md`.

## Consolidation and change

The change lessons that survive the fold:

- A cap or limit has one source. A change to one greps the tree for every copy of the old value before its PR opens; the single-source PR makes every other reader load the value.
- A ruling that narrows a running task needs the worker's own acknowledgement before `worker_done`; without it, the task stops.
- An estimate of what a retirement removes cites an import list, not a directory.
- An automation in a frozen repository reports; it never opens a pull request there.

Authority: LEAD-1630-lessons-addendum.md items 1, 2, 4 and 5, SHA-256 `b86cb3b322318895573afa3bdef3d7991db77b8258fb06002b7f777ff5e2bbd8`; item 3 is in [the review rules](../../.github/workflows/shared/review-rules.md#two-author-families).
