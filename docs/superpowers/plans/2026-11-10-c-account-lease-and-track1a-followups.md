# C's Account-Scoped Lease and Track 1a Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. This dispatch is one worker doing the work itself: execute inline, no helper agents.

**Goal:** C's single-writer lease is keyed to the account in one fixed lock directory, so two starts on the same account exclude each other whatever `--state` they use; the remaining #239 1a items are closed (custody refusals write a receipt and a FAIL ledger row, a failed or empty boundary ranking keeps the held names, retained names join in sorted order, the allocator's own mover membership is carried forward), the dotted-ticker mapping has one helper with a `BRK.B` proof, and the governing docs record C's 5-name capacity and ten first-leg rows.

**Architecture:** `c_live_main.py` gains one module constant `DEFAULT_LEASE_ROOT = Path.home() / "sextant-data" / "locks"` and builds the lease from `WriterLease(AccountScope(account.broker, account.account_id), DEFAULT_LEASE_ROOT, "c-live")`, the same account key and helper B uses (`src/sextant/paper/b_protector_main.py:249`); the lock file name stays the helper's sha256 digest, so no account identifier appears in the path. The three `_retained_symbols(book)` call sites are wrapped in `except LiveRefusal`, the initial and boundary arming sites substitute an empty `_Arming`, `_Arming` gains `mover_armed`, the failure and empty ranking paths carry `tuple(sorted(retained))`, and the retained append iterates `sorted(retained)`. Both instrument-to-symbol sites call the existing `bare_symbol` helper (`src/sextant/ranking/baseline_coverage.py:22`). Governing docs are amended in place without growing their line budgets.

**Tech Stack:** Python 3.12, pytest proofs with fake broker/data/feed, `flock`-backed `WriterLease`, ruff.

**Spec:** Dispatch BRIEF `/home/sextant/sextant-data/handoffs/tasks/c-1ai/BRIEF.md` sha256 `1e877bfb3079aebfa2a031b877cf83717032096b5b369e637ddc63548831e76d`, "TRACK 1a-i" (issues #251 and #239 items 7, 9, 10, 11, 12, 14, 15; LEAD-0441).

## Global Constraints

- No custody logic, no exit/reprice code, no order placement/cancel/replace/sizing change: exit and reprice stay untouched (1a-ii).
- No `--lease-root` argument, no config-directory root, no account identifier in any public file name, log or receipt.
- `guard.py`'s fresh-start rule is unchanged.
- `src` stays under the 28,000-line budget; `tests/repo/test_budgets.py` is never edited.
- `Decimal`, never floats, for money values.
- One concern, one commit; no push.
- Never touch the running C node pid 2293134 or `/tmp/c24-state-20cc408`, B, a broker or a live endpoint.

## Review Focus

- Two runners on one account with different `--state` must not both acquire the lease; the second refuses with "account already has a writer", and the only lock file lives in the one fixed directory with a sha256 name.
- Every custody refusal in `main()` still writes the receipt and exactly one FAIL trial-ledger row, and the process exits 1.
- A failed or empty boundary ranking records the held names as armed, keeps them in the receipt `symbols`, and writes one FAIL row.
- Retained names join the armed tuple in sorted order, and the boundary arming receives the allocator's own `Allocation.mover_armed`, not the whole previous symbol set.
- `BRK.B.ALPACA` maps to `BRK.B` on both the broker request and the house client id; no inline `split`/`rsplit` mapping remains.
- `docs/adr/0002` stays at 80 lines and the other amended docs stay inside their budgets.

---

### Task 1: Account-scoped lease in one fixed directory

**Files:**
- Modify: `src/sextant/paper/c_live_main.py` (constant near the other root constants; `main()` lines 998-1015)
- Test: `tests/proofs/test_c_live_main.py`

**Interfaces:**
- `DEFAULT_LEASE_ROOT: Path = Path.home() / "sextant-data" / "locks"` — module constant, no argument
- `WriterLease(AccountScope(account.broker, account.account_id), DEFAULT_LEASE_ROOT, "c-live")`

- [ ] **Step 1: Write the failing proofs.** Add `state: Path | None = None` to `invoke()`; monkeypatch `c_live_main.DEFAULT_LEASE_ROOT` to `live_env / "locks"` in the `live_env` fixture with `raising=False`. Rewrite `test_a_second_writer_cannot_acquire_the_lease` to hold `WriterLease(AccountScope("ALPACA", "C001"), live_env / "locks", "other-writer")` and assert the refusal message, one submitted order set empty. Add a threaded proof: runner A blocks inside `FakeFeed.start()` on an `Event` after releasing a normal replay, runner B starts with `state=live_env / "state-b"`, must raise `SystemExit` whose message contains "account already has a writer", then release A and assert A returned 0. Add a fixed-directory proof: after a normal run, `live_env / "locks"` holds exactly one `[0-9a-f]{64}.lock`, `ACCOUNT` is not in the name, and neither `state/writer.lock` nor a second lock exists.
- [ ] **Step 2: Run and watch them fail** (current code locks `state/writer.lock` with the broker account number, so B proceeds).
- [ ] **Step 3: Implement** the constant and the `WriterLease` call; change the scope key to `account.account_id`.
- [ ] **Step 4: Run the proofs green** and check `git diff` has no other lease call site.

### Task 2: Custody refusals write the receipt and a FAIL row (#239 item 7)

**Files:**
- Modify: `src/sextant/paper/c_live_main.py` (initial arming ~1055, loop config ~1487, boundary arming ~1528)
- Test: `tests/proofs/test_c_live_main.py`

**Interfaces:** none new; `except LiveRefusal as exc` sets `failure = f"refused: {exc}"`.

- [ ] **Step 1: Write the failing proof.** Monkeypatch `sextant.paper.c_live_main._retained_symbols` to raise `LiveRefusal("custody symbols unavailable for C arming")`, parametrised over the first and second call (initial arming and the loop's `_config_for`), invoke a universe run, and assert exit code 1, one receipt with the right `final_segment`, exactly one FAIL row in `TrialLog(live_env / "trials.parquet")`, and the error recorded.
- [ ] **Step 2: Run and watch it fail** (the exception escapes `main()`).
- [ ] **Step 3: Implement** the three `try/except LiveRefusal` wrappers; the arming sites record `_Arming(0, 0, (), None, str(exc), params["max_armed_symbols"])`.
- [ ] **Step 4: Run the proof green.**

### Task 3: Held names survive a failed or empty boundary ranking, sorted (#239 items 9, 10)

**Files:**
- Modify: `src/sextant/paper/c_live_main.py` (`_Arming`, `_arm_universe` failure/empty/normal paths, `_record_arming`)
- Test: `tests/proofs/test_c_live_main.py`

**Interfaces:** `_Arming.mover_armed: frozenset[str] = frozenset()`; `_record_arming` adds `"mover_armed": sorted(arming.mover_armed)`.

- [ ] **Step 1: Write the failing proofs.** A universe run fills `OMH` in POST and then breaks the OVERNIGHT ranking (parametrised: `data.fail = True`, and `data.bars_by_symbol = {}`); assert exit 1, `final_segment == "OVERNIGHT"`, `arming[1]["custody_open"] == 1`, `arming[1]["armed"] == ["OMH.ALPACA"]`, receipt `symbols == ["OMH.ALPACA"]`, and one FAIL row. Add a direct `_arm_universe` proof with six retained names and one ranked candidate that is not chosen (full retained pool), asserting `arming.armed == tuple(sorted(retained))`.
- [ ] **Step 2: Run and watch them fail** (failure paths return `armed=()`, and the append follows frozenset order).
- [ ] **Step 3: Implement** the retained tuple in the failure and empty returns, `sorted(retained)` in the append, and the `mover_armed` field/record.
- [ ] **Step 4: Run the proofs green.**

### Task 4: Carry the allocator's mover membership (#239 item 11)

**Files:**
- Modify: `src/sextant/paper/c_live_main.py` (normal arming return, `main()` initial and boundary calls)
- Test: `tests/proofs/test_c_live_main.py`

**Interfaces:** `current_mover_armed: frozenset[str]` in `main()`; passed as `mover_armed=` to both `_arm_universe` calls and updated from `arming.mover_armed`.

- [ ] **Step 1: Write the failing proof.** A direct `_arm_universe` proof with retained `OLD.ALPACA`, candidates `M0..M4`, `max_armed_symbols=5`, empty `mover_armed`: assert `arming.armed == ("M0.ALPACA", "M1.ALPACA", "M2.ALPACA", "M3.ALPACA", "OLD.ALPACA")` and `arming.mover_armed == frozenset({"M0.ALPACA", "M1.ALPACA", "M2.ALPACA", "M3.ALPACA"})`; assert the receipt's `mover_armed` is that sorted membership.
- [ ] **Step 2: Run and watch it fail** (`_Arming` has no `mover_armed`; the receipt has no field).
- [ ] **Step 3: Implement** the field, normal-path `mover_armed=allocation.mover_armed`, the record field, and the `main()` threading.
- [ ] **Step 4: Run the proof green.**

### Task 5: One dotted-ticker mapping (#239 item 3)

**Files:**
- Modify: `src/sextant/paper/c_live_main.py` (`_house_cid` line 355, `_request_for` line 426, import)
- Test: `tests/proofs/test_c_live_main.py`

**Interfaces:** `from sextant.ranking.baseline_coverage import bare_symbol`; `symbol = bare_symbol(command.instrument)` at both sites.

- [ ] **Step 1: Write the failing proof.** A `BRK.B.ALPACA` `OrderCommand` maps through `_request_for` to a `LimitOrderRequest` with `symbol == "BRK.B"` and through `_house_cid` to a cid containing `BRK.B-`; an end-to-end universe run whose ranked row is `BRK.B` submits a BUY request with `symbol == "BRK.B"` (and the baseline helper's own `BRK.B` proof stays green).
- [ ] **Step 2: Run it** — the behaviour is already correct on main (`rsplit`), so this is a refactor guard; record that in the PR body. The red step for this item is the pre-fix branch witness W3, not reproduced here.
- [ ] **Step 3: Implement** the import and the two call sites; confirm no inline `split`/`rsplit` mapping remains in `c_live_main.py`.
- [ ] **Step 4: Run the proofs green.**

### Task 6: Record C's capacity in the governing docs (#239 items 14, 15)

**Files:**
- Modify: `docs/design.md` (C row line 44, "No conservative profile" paragraph line 52, "What is not settled" bullet line 161)
- Modify: `lanes/paper/README.md` (C row line 15, "No conservative profile" paragraph line 22)
- Modify: `docs/adr/0002-philosophy-and-lanes.md` (line 62, inline amendment; file must stay 80 lines)
- Modify: `docs/adr/0004-entry.md` (line 59: Ten first-leg starts, `max_armed_symbols` in both lists)
- Test: `tests/repo/test_budgets.py` (line budgets only)

- [ ] **Step 1: Amend the docs** with the dated authority (LEAD-1759 §2 item 3, confirmed by LEAD-1808 #201, 2026-11-09; UNCALIBRATED; 5 names, mover quota 2), keeping replacement risk and leverage explicitly unresolved.
- [ ] **Step 2: Run** `uv run --frozen pytest tests/repo/test_budgets.py -q` and check each amended doc's line count.
- [ ] **Step 3: Cross-check** every amended sentence against `lanes/sim/entry-parameters.json:137-145` and the 28-row registry.

### Task 7: Verification and handoff

- [ ] **Step 1:** Run the touched proofs: `uv run --frozen pytest tests/proofs/test_c_live_main.py tests/proofs/test_baseline_coverage.py tests/repo/test_budgets.py -q`.
- [ ] **Step 2:** Run `bash /home/sextant/sextant-data/roster-ops/ci-local.sh` from the worktree root under `systemd-run --user --scope -p MemoryMax=8G -p MemorySwapMax=0`; record the exit and any pre-existing host-only failure as UNKNOWN with its name.
- [ ] **Step 3:** Re-run the item-12 evidence subset and state each #239 item as fixed-on-main, fixed-here, or still-open.
- [ ] **Step 4:** Write `scratch/pr-body.md` from the repo template with the `## Manifest row` first cell `"C live main: SIP feed, witness entry and broker-held trail"` (the lease sentence names `src/sextant/paper/b_protector_main.py:249` and `src/sextant/tradingview/loop.py:44` as the fixed-root precedent), one `Agent-Family dsh` marker and no other routing marker, no private paths.
- [ ] **Step 5:** Commit one concern as Sextant, report the head, check outputs, acceptance checks and body path, and STOP without pushing.

## Acceptance Checks (named before any push)

1. `uv run --frozen pytest tests/proofs/test_c_live_main.py -q` — all pass, including the three new lease proofs, the custody-refusal receipt proof, the failed/empty boundary proofs, the sorted retained proof, the mover-membership proof and the `BRK.B` proofs.
2. `bash /home/sextant/sextant-data/roster-ops/ci-local.sh` — exit 0; any failure reported by name and marked UNKNOWN only if it reproduces on `origin/main` without this diff.
3. `git diff --check` clean; `uv run --frozen ruff check` on the touched Python files.
4. `python - <<...` line count of `src` is below 28,000; amended ADR-0002 is still 80 lines and ADR-0004 at most 80.
5. `grep -n "split\|rsplit" src/sextant/paper/c_live_main.py` shows no instrument-to-symbol mapping outside `bare_symbol`.
6. `git status --short` shows one commit's files only, with no state, receipt or lock artifact.
