# The ecosystem map

One page for routing a question to the record that answers it. The generated
[llms.txt](../../llms.txt) lists every decision, lane, handbook page and research note;
this page says which tool to reach for first.

## Session start

Run `just session-start`. It checks the live dsh profile against
`config/dsh/profile.lock.json`, then checks that `llms.txt` is current. Drift stops the
session: fix the profile or the lock, never the check.

Adding, renaming or deleting a page under `docs/` is not done until
`scripts/ecosystem_index.py --write` runs in the same PR: `llms.txt` is generated, and a
stale index stops the next session.

## Route a question

| Question | First move | Owner |
| --- | --- | --- |
| What Sextant is for, and the trade lifecycle | `docs/design.md`; rank, enter, protect, exit, custody | Design |
| Why a decision was made | Search `docs/adr`; cite the ADR number | Decision record |
| How a lane behaves or is configured | `lanes/<lane>/README.md`, then `config/` | Lane owner |
| Which pick, version, source or proof is in force | `docs/manifest.md`; `just prove` for its test | Manifest |
| Where a symbol is defined or called | `codegraph_explore` first, then `read` | Code |
| What a previous session concluded | `session_search`; then `session_trace` | Session record |
| A library, SDK, CLI or cloud API | `Context7` docs before guessing | Upstream |
| A paper, article or external claim | `paper-search`, `deepread`, or `Exa`; keep the URL | Source |
| A pull request, issue, check or run | `gh pr view`, `gh issue view`, `gh run view` | GitHub |
| A run, worker or automation | `orca orchestration`; `worker-list` for state | Orca |
| A plugin's admission | `docs/handbook/plugins.md`; no row, no install | Plugin gate |
| A lifecycle gap | `handbook/lifecycle.md`, then the owner above | Delivery stage |
| Which runtime, model and effort a job runs on | the model-mix table below; ADR-0030's second amendment | Harness |

### The model mix

| Work | Runtime and model | Effort |
| --- | --- | --- |
| Lead: orchestration, rulings | Claude Fable 5.2 | high |
| `/code-review` of protection, custody, gate, hard-line or live-promotion changes | Claude Fable 5.2: the lead runs the skill, or a Fable reviewer session | high; `max` only when the owner asks |
| Hard writer tasks and hard reviews where the situation needs Claude | Claude Opus 5.5 | high; `xhigh` where a sweep shows a gain |
| Role sessions: dispatcher, lander, tracker | Claude Sonnet 5.5 | high |
| Lookups, inventories | Claude Haiku 5.5 or Sonnet 5.5 (the later `.claude/agents/<role>.md` definitions); dsh; Muse | low or medium |
| Writers on well-specified briefs; bulk and delta reviews | GPT through Codex (`gpt-6.1-sol`) and dsh: main workhorses | per LEAD-2345 |
| Independent screens and second-family checks | dsh, Muse, agy (Google) | the runtime's pin |

Fable's share of Claude weekly use is at most one half; the tracker reports the split by model each pass and alerts past 50% or when the pace would exhaust the week before its reset. Opus 5.5 is for work, not relaying. A Claude review in a class this table names needs no special word; it names its model and effort and is time-bounded. Every Agent call and launch names its model and effort, in the command or in the checked-in role definition it starts; a fork inherits Fable, so forks are only for the owner's side questions. Each value is a registry row with its source, uncalibrated until the sweeps report. [ADR-0030](../adr/0030-latest-sota-models.md)'s second amendment carries the owner-directions requirements D-9, D-10 and D-11, the tracker's 22:50-23:50 split, and why each level is uncalibrated.

Since 2026-11-10, a role session starts from its checked-in definition in `.claude/agents/<role>.md` through `python3 scripts/role_launch.py <role>`: the definition carries the model and the first turn, the launcher adds `--name` and, for the four coordination roles, `--autocompact 200000`, and passes no `--model`, `--effort`, `--settings` or `--advisor`. That supersedes the 2026-11-09 role table's where-pinned cells; the model and effort values above do not move.

## The rule behind the table

Every question has one first move and one record owner; a second owner is a duplicate,
not redundancy. The delivery-stage owners are [lifecycle.md](lifecycle.md)'s table, not a
second list here.

## Cite

Every answer names its evidence: `path:line`, a commit or run URL, or a source URL.
"Cite" means the reader can open the same record and check the claim. An uncited claim is
a draft, not a finding.

A map is an answer: every row carries a `path:line`, a commit or run URL, or a receipt,
never a bare claim, and the map names the exact head it was read at and checks it again
before hand-off.

## Search order

1. The generated index: `llms.txt`.
2. The written record: `docs/`, `lanes/`.
3. The code graph: `codegraph_explore`.
4. Session history: `session_search`.
5. External sources: `Context7`, then the cited paper or page.
6. GitHub and Orca: `gh`, then `orca orchestration`.

If a route is missing, add it here with the same one-owner rule; do not add a second
plugin or a second index.

## Complete B protection reserves

ADR-0007 C4 and Codex review of `602479b` (2026-11-10): reserve B's mandatory positions/open-orders reads at terminal handovers as well as the reviewed 2/1 write floor, including the entry-created position. Optional entry authority that cannot be parsed leaves entries unavailable while protection starts. `test_b_entry_reserve_review.py` retains the executed fill, resize, invalid-control and exiting-position witnesses.

The pinned SDK's retry count is private: prove `_retry` exists on the real 0.44.0 client before disabling retries for a separate entry client. Reuse `b_feed.no_retries`; missing support leaves entry unavailable and pages, without changing protection. One 429/504 attempt is one POST and one pacer wire; refusal waits for the next generation, with no SDK sleep (`test_b_entry_sdk.py` and `test_b_entry_facade_sdk.py`).

Reserve unsettled entries by retained client order ID, once at the wire boundary; a lost acknowledgement keeps its charge, a refused same-ID retry cannot clear it, and a terminal receipt settles only that ID once. Keep settled identities to refuse replay. Withdraw an unsent entry even when an older protective drain raises, before creating any charge. Prove this ledger invariant with fixed-seed event sequences and real SDK lost responses (`test_b_entry_charge_ledger.py`). Measure the whole protective path: one reconcile reads twice, but each resize's terminal cancellation reconciles again, making full rearm 2+4n wires. Burst 18 therefore admits held counts 0-3; sharing a single pair of reads across all handovers under-reserves protection.

An entry needs its stable nonempty client order ID before admission; never coerce the SDK's optional ID into a shared placeholder. For the real SDK, its method call precedes JSON preparation: count the entry wire and create its charge at requests' `Session.send`, after preparation succeeds. Invalid JSON then creates neither; a timeout after dispatch retains its own exposure (`test_b_entry_sdk.py` and `test_b_entry_facade_sdk.py`).


Opus review of `18c6226` (2026-11-10): the entry-created position needs its own partial-fill/full-fill resize path, not only an initial trail. Measure all three reconciles: nine wires at the existing 2/1 rows and two reads per snapshot. Retain that path for every unsettled entry; the additional reserve is two snapshot pairs plus one exiting write floor per new/pending ID. A definitive 403/422 rejection settles its own charge, while uncertain outcomes retain exposure. `test_b_entry_partial_reserve.py` proves the path at 0/1 held and the old boundary's refusal. The earlier held 0-3 admission table is superseded: burst 18 admits a fresh ID at held 0-2 only with 9/13/17 tokens left after it; a second unsettled entry refuses. The 6144-operation proof uses a derived measurement-only bucket for four pending IDs and retains every assertion. Burst changes and the restart/separate-reconcile findings remain separate work under #351.
