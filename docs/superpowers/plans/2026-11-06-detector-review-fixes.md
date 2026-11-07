# Detector method-review fixes implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline, without helpers.

**Goal:** Fix all five Important findings in dsh review `c7f809d9c0c1bbc18f27e267110d0c3afa0badb7274521f6c1cf0d02803fe035` in one PR.
**Architecture:** A validated immutable Stocks in Play specification drives construction, filters and result identity. Native composite bars own aggregation; completion/coverage and specification identity travel with each opening window. BOCPD explicitly implements equation (4)'s elapsed-duration hazard convention.
**Tech stack:** Locked NautilusTrader rc7, Decimal, existing Parameter/digest, pytest.
**Spec:** Owner ruling on #130 and `~/sextant-data/onset-130/method-review-r1/review-dsh.md`, Important 1–5.

## Global constraints

- Fresh Orca worktree from main; no data acquisition, market trial, ledger write or compute admission; HOLD remains.
- Keep source cards and pytest configuration unchanged. All sources retain exact pins.
- One completed local fix batch, `just ci`, one `just pr` push with auto-merge on, then `just ao claim`.

## Review focus

- Mutated threshold, window and lookback rows must change behavior and active hashes, including unavailable results.
- Native composite delivery strips its source suffix; retain the subscribed composite type and reject incompatible source/type or close clocks.
- Native aggregation can emit partial windows; coverage remains independent, is retained, and is checked by screen.
- Unequal prior volumes distinguish the interpreted average from the literal repeated-previous-day denominator.
- Nonconstant elapsed-duration hazard distinguishes H(r+1) from H(r), including identity.

## Task 1: Governing specification, native windows and coverage

Files: `src/sextant/research/detectors/stocks_in_play.py`, `tests/proofs/test_detector_arms.py`.

- [x] Observe four threshold mutation failures and missing coverage/hash-field failures, then add window/lookback, native composite, varying-volume and immutable-mapping proofs. Retain calendar/DST/close/receipt and missing-input refusals.
- [x] Add `StocksInPlaySpec(rows)` with validated immutable row mapping and a hash of that mapping. Both public functions accept `spec`; no behavioral threshold/lookback/opening duration literals remain outside registry rows.
- [x] `opening_window(..., composite_type=..., coverage_complete=..., spec=...)` consumes one native composite result (including its standard internal delivered type), not five manually combined bars. `OpeningWindow` carries composite type, coverage evidence and active hash; screen validates all three.
- [x] Bind the supported denominator interpretation as an UNCALIBRATED specification row sourced to the hash-pinned paper §5/p.19, explicitly disclosing §3/p.14's notation. Test varying volumes and reject unknown interpretations.
- [x] Run detector proofs: governing rows, coverage and native delivery green. The native fixture also confirms partial output supplies no independent coverage.

## Task 2: Elapsed-duration hazard convention

Files: `src/sextant/research/detectors/bocpd.py`, detector proofs.

- [x] Write a nonconstant callable H(tau) proof with H(0), H(1) and H(2) distinct; observe the missing callable API failure; assert requested durations and the hand-computed posterior.
- [x] Accept H(tau) at the arm seam, evaluate at r+1, retain vector recurrence as a mathematical primitive, and include the equation-(4) convention/source in parameter identity. Preserve unavailable-input/no-alarm behavior.
- [x] Run the detector suite: 53 passing cases, including two native engine fixtures.

## Task 3: Source/lesson reconciliation and landing

Files: existing detector lane contract, handbook lesson/rule and manifest row; PR template.

- [x] Update API, native composite source/standard delivery, paper interpretations and the NOT ADMITTED ruling with full pins and review hash. No numerical journal append.
- [x] Run `timeout 300 just ci`: 569 passed, 28 skipped, 7 deselected; all static/workflow/secret checks pass. Review the complete diff against all five findings before committing.
- [ ] Fill the PR template with all source pins, proof results, limits and revert instructions. Run `just pr`, keeping auto-merge on under the owner's latest instruction, then `just ao claim`; leave later branch fixes to AO.

Ruling: implement the mean-prior-window denominator as an explicit UNCALIBRATED
interpretation of the pinned paper §5/p.19, disclosing §3/p.14. The varying-volume
proof distinguishes the literal previous-day reading; this choice grants no admission.
Ruling: equation (4)'s H(r+1) defines the callable duration API, rather than the
different printed index in Algorithm 1. Bind it in identity and prove requested durations.
Ruling: accept the standard internal BarType emitted by the pinned native composite
engine while retaining the explicit subscribed composite type and independent coverage.
