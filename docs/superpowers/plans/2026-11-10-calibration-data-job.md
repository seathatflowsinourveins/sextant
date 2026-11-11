# Calibration data job Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans; the dispatch requires native execution without helpers.

**Goal:** Refresh C's baselines each morning and retain quotes/minute bars for width calibration.

**Architecture:** Reuse baseline_recipe.run, AlpacaHistory capture/pacing, SDK pagination and the write-once Parquet publisher. A script and user timer inject keys only inside the unit.

**Tech Stack:** Pinned alpaca-py, PyArrow, systemd user units.

**Spec:** D-44, LEAD-2127 §5; the calibration data job manifest row.

## Global Constraints

Local commits only; no push, install, keyed command or broker call. Stub external requests. src <31,000 lines; raw diff <44,000 bytes. No width adoption; ADR-0019 still governs.

## Review Focus

Empty windows never qualify widths; failed runs have no complete receipt; retries preserve raw partitions; invalid input refuses before clients; XNYS holidays skip and timer timezone follows DST.

### Task 1: Morning data job

**Files:** `src/sextant/data/calibration_job.py`, `scripts/calibration-data.sh`, `deploy/calibration/`, `tests/proofs/test_calibration_job.py`, manifest and handbook.

**Interfaces:** Consume baseline_recipe.load_universe/run, prior_xnys_sessions, AlpacaHistory and _land_pages; produce main(argv, client_factory, now_ns), raw partitions and a hashed receipt.

- [x] Write offline proofs; capture RED before implementation.
- [x] Implement SDK requests, baseline-first orchestration, registry and units.
- [x] Verify touched proofs, shell/unit syntax and the external roster ops ci-local harness; record exact results in the handback.
- [x] Review source; prepare template body, commit locally and hand back for independent review.

## Execution ledger

- Pre-flight: one concern, no shared task interfaces.
- Ruling: the native/no-push dispatch overrides skill handoff prompts and helper reviews; roster ops owns the independent review and publication.
- Ruling: 03:00 New York weekdays is an UNCALIBRATED starting schedule before PRE, under the lead's morning refresh direction; completion time is unmeasured.
- RED: missing module/artifacts; then 15 proofs GREEN. Integrity RED (parameter mutation, broken page chain) became GREEN (22).
- First ci-local: 3306 passed, 1 xfailed; final source review added RED for wrong payload kind and pre-response availability. Both were fixed; final touched proofs: 103 passed. Final ci-local results belong in the handback.
- Installation, data entitlement/size/timing measurement, C's baseline path and calibration trials remain with the lead after merge.
