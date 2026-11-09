# Doublecheck spec

## Goal
Land one PR on gate that makes upstream authority mechanical: a six-surface authority map, a base-branch danger check that refuses a governed path without its owner, and a proof that page and gate agree; then start the real end-to-end run.

## Scope
In: docs/handbook/sources.md; dangerfile.js AUTHORITY map and check; tests/repo/test_dangerfile.py; tests/proofs/test_sources.py; one docs/manifest.md In-use row. Out: freshness detector (follow-up issue), .github governance, plugins, src behavior, live/paper orders.

## Acceptance criteria
New danger tests fail before the rule and pass after (23 in the file); the page's six surfaces, owners and paths equal dangerfile's; a fork on a governed path fails, the owner passes, docs-only passes; full pytest, ruff and pyright green on the branch head; PR merges on gate.

## Failure modes
Overlapping surfaces (lanes/paper, lanes/tradingview) must not double-fail a legitimate owner; docs-only PRs stay ungoverned; .github/ stays ungoverned so test_a_sourced_gate_edit_needs_no_owner_label keeps passing; danger must run from base so a PR cannot edit its own check; budgets unaffected.

## Priorities
A correct, tamper-proof gate over broad path coverage; land now with the freshness detector deferred; no new dependencies.

## Non-goals
Do not add a freshness workflow in this PR; do not port ce-code-review to dsh; do not change .github governance or live/paper behavior.
