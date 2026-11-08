# TradingView review round implementation plan

> **For agentic workers:** Use `executing-plans` inline, task by task. The handoff selects one GPT fix round; the independent dsh delta review is a later gate.

**Goal:** Address #64 comment 6712693142's three P2s and inexpensive P3s in exactly one push.

**Architecture:** Preserve local domain errors outside the SDK task groups; reuse one serial limiter for discovery and tool calls; adopt the pinned northstar reference-counted logging guard. Tighten local input/receipt boundaries without expanding the display-only surface.

**Tech Stack:** Existing Python 3.13, MCP SDK 2.3.0, pytest, stdlib logging/threading, exchange_calendars 4.13.2.

**Spec:** `/home/sextant/sextant-data/handoffs/pr64-r1/HANDOFF.md`, SHA-256 `819ea52a075cc99ca0f8b283d98cb88c526019f1319b22b0daab502f02ffae09`; the specified dsh comment and four bot reviews read by ID. The handoff already selects the changes and inline execution; no new feature design is proposed.

## Global constraints

- Start at exactly `de57a22da57c8e1c8b2d89bff3524a4f92ec6044` in the supplied Orca worktree; no other writer/worktree touched.
- No TradingView sign-in, OAuth, SDK call to TradingView, network call to TradingView, Desktop debug port, keys, broker or order action. SDK in-memory fixtures only.
- One non-force push to `seathatflowsinourveins/lane-tradingview`; never main. No merge/owner acceptance in this round.
- Name each source in the existing manifest row and operating notes. P2-3 copies `auth_safety.py:sensitive_logging` from northstar-trading `8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`.
- Run `just ci` and `just prove`; report every failure without bypassing guards or changing unrelated infrastructure.
- Any remaining P3 goes to one GitHub follow-up issue; write the final report at the requested handoff path.

## Approaches

The lead has selected preserving trusted errors, one limiter and upstream reference counting. A separate discovery limiter would miss the discovery-to-first-call gap; forbidding overlap would avoid rather than implement the selected upstream guard. For P3-6, explicitly document owner-enforced single-process use, rather than adding a new lock mechanism. Real OAuth and official envelopes cannot be accepted under this round's no-network boundary.

## Review focus

- SDK task groups wrap body errors: exercise the real in-memory Client through `official_client`, not just a fake client.
- Discovery-to-first-tool spacing: three pages plus a following call must share one monotonic timeline.
- Logging overlap: exit the first context while another remains, including cancellation and pre-disabled logging.
- Invalid timestamp offsets and extreme calendar years: fail with InputError rather than normalized clocks/raw ValueError.
- Local receipt corruption: upstream hash/title mismatch and CLI failure must never imply a session opened.

## Tasks

### Task 1: Trusted sync errors (P2-1, P3-7)

Files: `auth.py`, `tests/proofs/test_tradingview.py`.

- [x] Verify baseline: 55 TradingView proofs passed; head and clean worktree checked.
- [x] Add an in-memory official-client fixture; trigger real readback mismatch and ambiguous mutation through it. Assert domain message/identity survives.
- [x] Run the new tests red; capture failure before implementation.
- [x] Catch trusted body SyncError inside Client (SDK troubleshooting guidance), close SDK contexts normally and re-raise outside; keep unknown errors sanitized.
- [x] Run targeted tests green and the full TradingView file.

### Task 2: Shared discovery limiter (P2-2, P3-7)

Files: `sync.py`, `tests/proofs/test_tradingview.py`.

- [x] Add a three-page low-level in-memory Server test recording request times and a following watchlist call; expect every gap >=0.75s.
- [x] Run red, extract the existing delay/freshness/timestamp logic into `_pace`, use it under the same lock for each page and call, then run green.
- [x] Retain schema preflight, bounded discovery and freshness-after-wait witnesses.

### Task 3: Sensitive logging (P2-3, P3-7)

Files: `auth.py`, `tests/proofs/test_tradingview.py`.

- [x] Add two overlapping official-client tasks; first exit must not restore logging, final exit restores exactly the initial disable level. Cover reverse exit, cancellation and already-disabled logging.
- [x] Run red, adopt upstream lock/count `sensitive_logging` unchanged in behavior and wrap the full session/cleanup, then run green.

### Task 4: Local receipts and input diagnostics (P3-1–P3-4, P3-7)

Files: `presets.py`, `inputs.py`, `__main__.py`, `tests/proofs/test_tradingview.py`.

- [x] Test normalized upstream hash/title corruption, run red, verify normalized bytes against upstream_sha256 at runtime, run green.
- [x] Move invalid +/-00:60 offset witnesses to refusal tests, add compact-form/hour bounds and valid boundary witnesses; run red, enforce RFC3339 section 5.6 offset ranges, run green.
- [x] Test calendar year 1/9999 as InputError, run red, translate date/calendar ValueError to InputError without fabricating a calendar, run green.
- [x] Test offline preset CLI failures separately from sync, run red, return fixed receipt-specific nonzero diagnostic without raw exception text, run green.

### Task 5: Sources, operating rules and handoff (P3-5–P3-7)

Files: `lanes/tradingview/README.md`, `docs/tradingview.md`, `docs/manifest.md`, `docs/handbook/practices.md`.

- [x] Align RAM-only/no-persistence documentation and state single-process ownership is owner-enforced with concurrent runs unsupported.
- [x] Cite northstar pin, SDK pagination/troubleshooting, RFC3339 section 5.6 and Python 3.13 datetime/hashlib docs (read 2026-11-07) for the relevant fixes. Record the task-group/overlap lesson and governing practice.
- [x] Run full TradingView proofs, `just ci`, `just prove`, diff/budget/secret checks; self-review only, keeping the blind dsh delta separate.
- [ ] Commit reviewed changes, check remote branch still matches the starting head, make exactly one push.
- [ ] File one issue for remaining real OAuth/official schema-envelope acceptance in P3-7, with later owner-consent/delta gate intact.
- [ ] Write `REPORT.md` with new head, finding-to-test map, verification results and follow-up issue; leave branch/worktree for the later delta review.

The three post-commit steps above are receipted in the external `REPORT.md` after
the one push, not by a second plan-update push. The supplied Orca worktree is
preserved pending the dsh delta; no merge or owner acceptance is part of this round.
