# Paper B attended entry Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; no helper agents.

**Goal:** One explicitly requested, quote-priced test BUY inside B's admitted Strategy.

**Architecture:** Use the pinned native order factory and submit API inside GatedBLifecycle. Retain one consumed intent and its own order id; stop cleanup uses B's existing guard, and fills use existing reconciliation.

**Tech Stack:** NautilusTrader v2.0.0rc8, Decimal, pytest, existing Alpaca fake venue.

**Spec:** LEAD-1452 part T1; interface refinement: `--attended-test-entry <INSTRUMENT>` only.

## Global Constraints

Roster ops refinement: own diff against d2ccd891 stays under 44,000 raw bytes; Roster ops cuts onto fresh main after the inherited cutover lands. Local commits only; no broker, key, node start or endpoint outside offline proofs. Keep ordinary entries off. Preserve the six cutover commits. Native factory/submit USE AS IS: d53849b216e20f2c122ca01b4dd0da377638b186 common stub:1388-1406 and trading stub:538-543; one consumed intent follows testkit strategy.rs:503-515. KEEP OURS for claim/gate/own-id policy, searched engine Python stubs, testkit and existing paper/entry packages.

### Task 1: Prove and integrate the opt-in hook

Files: `src/sextant/paper/node_order.py`, `lanes/paper/shared-node.params.json`, `tests/proofs/custody/test_b_attended_entry.py`.

- [x] Write parser and fake-node tests: missing argument, default off, outside claims receipt, delayed gate, many quotes/one submit, outcomes, own-id stop cancellation, owner immunity, restart refusal.
- [x] Run `uv run --frozen pytest tests/proofs/custody/test_b_attended_entry.py` and retain RED output externally.
- [x] Add optional parsed intent, sourced quantity row, and claim validation before build; submit a native BUY DAY LIMIT at the fresh accepted ask after admission, consuming the intent before the send; retain a separate id so ordinary repricing never sees it.
- [x] At Strategy stop, pass only that retained open entry id through `_cancel`; leave fills to existing `on_order_filled -> reconcile -> _arm`.
- [x] Re-run focused proofs GREEN.

### Task 2: Document, verify and commit

Files: existing node row in `docs/manifest.md`, one line in `docs/handbook/practices.md`, this plan.

- [x] Extend the existing manifest row with pinned native API, consumed-intent source and proofs; document opt-in custody and witness limits.
- [x] Run registry/manifest/budget proofs, lifecycle drivers and lint; measure source net and raw against origin/main.
- [x] Record named proof counts and ci-local status; the brief forbids a whole-suite run in this worker tab, so the MAX gate owns full ci-local.
- [x] Commit locally as Sextant and hand back exact base/head, RED/GREEN, report hashes and request for the separately assigned Codex MAX review; preserve branch and worktree.

Verification: initial RED 12 failed / 2 passed; named regression GREEN 145 passed; supplemental adapter regression 50 passed. Full ci-local is assigned to the separate MAX gate, per the brief's no-whole-suite rule. Local branch and Orca worktree stay for that handoff.
