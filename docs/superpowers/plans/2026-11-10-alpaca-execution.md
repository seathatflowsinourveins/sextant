# Alpaca execution client implementation plan

> **For agentic workers:** Use executing-plans in this session; the dispatch forbids helper workers.

**Goal:** Translate engine commands and reconciliation through one paper account gateway.

**Architecture:** Follow the pinned Python ExecutionClient hooks and let the core own order state. Reuse AccountPacer for every REST request; retain only venue succession evidence in the adapter. A deterministic fake implements the documented venue constraints.

**Tech Stack:** NautilusTrader d53849b, alpaca-py cc4cb3b7; Decimal and native money types.

**Spec:** ADR-0008; LEAD-2201 (eeebb468c3478c4311ca1050cfebf7bfe48f472c36ac8c5fe289badceb8d75f3), adapter review addendum (6aedd0b7a45d96c86308e6bf98942b06cf7eab4817cee50a821008c1c681c3e7).

## Global constraints

- Paper-only construction; explicit credential names and account identity; no broker calls in development.
- Fail before implementation; local commits only; source pin and manifest proof for every pick.
- Unknown or unrepresentable rows mean incomplete coverage, never absence or flatness.
- House namespace before mutation; no account-wide operations; triggered or partly filled exits remain untouched.

## Review focus

- A replacement races with a fill: do not promote a proposal or discard a late fill.
- An owner's successor replaces a house order: never acquire mutation authority through linkage alone.
- An unknown enum appears beside valid rows: retain failures and prevent absence inference.
- Account pacing defers work: check admission again at the actual wire boundary.
- A reconnect loses fills: recover reports, and retain unknown fee/identity evidence explicitly.

### Task 1: gateway and exact command translation

Files: execution gateway and request helpers in `src/sextant/alpaca/`; proof in `tests/proofs/test_alpaca_execution.py`.
Interfaces: native order and ModifyOrder input; decimal-text SDK payload output; AccountPacer is the sole REST admission point.
- [x] Write and run failing tests for namespace, exact serialization, trail offset and quantity PATCH, exit mutation refusal and pacing.
- [x] Implement only these surfaces from the adapter guide and SDK REST methods.
- [x] Run proof and commit the independently testable gateway.

### Task 2: client, reports and venue witness

Files: `src/sextant/alpaca/execution.py`, config integration, `tests/proofs/test_alpaca_execution.py` and fake venue support.
Interfaces: Task 1 gateway; E3 report builders; E2 configuration and factory; native execution events and reports output.
- [x] Write and run failing tests for native command hooks, confirmed succession, owner successor refusal, mixed-row coverage, stream strings, reports and engine configuration.
- [x] Implement hooks and fake venue from the pinned template and Alpaca order/stream pages.
- [x] Rebase onto the corrected E3/E2 base, add manifest and handbook evidence, run focused proofs and ci-local with empty temporary HOME/XDG.
- [x] Record exact counts and sizes; commit and hand back local tips for cross-family MAX custody/protection review.
