# Native realized P&L implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline; no helpers.

**Goal:** Resolve #129 R98 with zero-difference replay and a negative net src change.
**Architecture:** Delete the display-report sum. Both thin-slice phases read the
single-venue native Portfolio currency map and convert Money to Decimal, preserving
the empty hold-flat zero. Retain the old sum only as a test-side comparison oracle.
**Tech stack:** Locked NautilusTrader rc7, Decimal, pytest.
**Spec:** Owner's R98 follow-up; rc7 `55c0e82053142bce3a5cba4de4221d3929c2d3bc`
`python/nautilus_trader/portfolio/__init__.pyi:60`, `docs/concepts/accounting.md:276-282`,
`docs/concepts/reports.md:224-275`.

## Global constraints and review focus

- Fresh Orca branch from main after #168; keep every existing size cap.
- No market-data acquisition, stream, study/admission or ledger changes.
- Use locally cached pinned upstream fixture bytes; prevent network in new proofs.
- Currency identity, empty controls, partial closes and NETTING archived cycles must
  retain their native semantics. No float money or report-string parsing in src.
- One code push with auto-merge on; `just ao claim` after GitHub CI settles.

## One implementation task

Files: `src/sextant/backtest/thin_slice.py`; new proof under `tests/proofs/`;
existing engine manifest row and a handbook lesson/rule.

- [x] Observe the old collector fail when display-string P&L parsing is prohibited.
- [x] Compare old report totals and native Money totals over both thin-slice windows
  and hold-flat phases; retain measured values and exact zero deltas.
- [x] Exercise real NETTING partial close, full close/reopen and archived-cycle totals.
- [x] Replace both calls with `Portfolio.realized_pnls`, delete the house helper,
  keep empty zero formatting and preserve all other Run/fill/window behavior.
- [x] Run thin-slice proofs and `just ci`: 580 passed, 28 skipped, 7 deselected;
  all static/workflow/secret checks pass on rc7. After #87 advanced main, rebase,
  repeat the eight focused proofs on rc8 (passed), and rerun full CI before push:
  585 passed, 28 skipped, 7 deselected, all static/workflow/secret checks green.
  Net src remains −7 (current main 13,313 → 13,306), caps unchanged.
- [ ] Fill the template with full pins and the quoted manifest row; `just pr` then
  `just ao claim` after CI. GitHub records the external hand-off after code freeze.
