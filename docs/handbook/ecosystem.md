# The ecosystem map

One page for routing a question to the record that answers it. The generated
[llms.txt](../../llms.txt) lists every decision, lane, handbook page and research note;
this page says which tool to reach for first.

## Session start

Run `just session-start`. It checks the live dsh profile against
`config/dsh/profile.lock.json`, then checks that `llms.txt` is current. Drift stops the
session: fix the profile or the lock, never the check.

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

## The rule behind the table

Every question has one first move and one record owner; a second owner is a duplicate,
not redundancy. The delivery-stage owners are [lifecycle.md](lifecycle.md)'s table, not a
second list here.

## Cite

Every answer names its evidence: `path:line`, a commit or run URL, or a source URL.
"Cite" means the reader can open the same record and check the claim. An uncited claim is
a draft, not a finding.

## Search order

1. The generated index: `llms.txt`.
2. The written record: `docs/`, `lanes/`.
3. The code graph: `codegraph_explore`.
4. Session history: `session_search`.
5. External sources: `Context7`, then the cited paper or page.
6. GitHub and Orca: `gh`, then `orca orchestration`.

If a route is missing, add it here with the same one-owner rule; do not add a second
plugin or a second index.
