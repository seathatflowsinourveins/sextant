# C's Four Per-Segment Baselines by One Tracked Recipe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This dispatch is one worker doing the work itself: execute inline, no helper agents.

**Goal:** One tracked command builds C's overnight, pre, rth and post baseline files from one run and records them in a manifest next to the files, and arming checks per-symbol baseline coverage instead of silently arming a symbol with no slice.

**Architecture:** A new `sextant.data.baseline_recipe` module calls the two reviewed fetchers (`fetch_overnight_baseline` for the boats overnight table, `fetch_baseline` for the sip daytime table), splits each table into one segment per file, verifies every file carries the other three's schema and complete symbol coverage, writes them under a staging directory and moves them into place, then writes `manifest.json` (command, as_of, symbols, window, feed, sha256) last as the commit record. A new `sextant.ranking.baseline_coverage` module answers "does this table hold a slice for this symbol and segment", partitions arming candidates before the slot pool allocates, and produces the per-symbol receipt field. `c_live_main.py` and `c_session.py` are not touched; the report names the exact call sites to wire.

**Tech Stack:** Python 3.12, alpaca-py data requests as already used by `baseline_bars`, pytest proofs with hand-built minute bars.

**Spec:** Dispatch BRIEF `/home/sextant/sextant-data/handoffs/tasks/c-track2/BRIEF.md` sha256 `e1b31d067cc09d299c2db73ad6db0fecfa4382d1cebfdb99ef34b23ce8608382`, "Track 2" (issue #235, ruling LEAD-0216). Reuses `docs/adr/0024-paper-lane-c-24-5.md` K2 universe and the manifest rows "Time-matched baseline builder for live arming" and "Overnight baseline fetcher for the 24/5 lane".

## Global Constraints

- `src/sextant/paper/c_live_main.py` and `src/sextant/paper/c_session.py` are owned by the track-1 writer: no edit. The report lists the exact wire-up lines.
- Market data only: proofs use a fake `BarsClient`; no vendor call, no network, no clock, no key, and the recipe is never run for real here.
- No secret in any file, log or argv; no private path in the PR body.
- `Decimal`, never floats, for every money value.
- The existing coverage rule is reused (`build_baseline` receipts: explicit complete coverage, linear within minute, first POST minute omitted). No reimplementation.
- `src` must stay under the 28,000-line budget; growth names its upstream call in the manifest row, not a new dependency.
- One concern, one commit; ruff line length 100; no push.

## Review Focus

- A file that does not carry all four segments' schema and all requested symbols stops the whole publish, not a partial write.
- The manifest's sha256s describe the bytes that actually landed (hashing the staged file, then the same bytes are moved).
- The `--universe` mode uses the K2 scanner's own artifact, records which source it used, and never re-ranks.
- A missing slice must be visible (refused or `baseline_missing`) and must not consume a slot.
- Tickers containing dots (`BRK.B`) map to their baseline key; only the trailing `.ALPACA` venue is stripped.
- `just c-baselines` is the only advertised path; no ad-hoc `python -c` call.

---

### Task 1: BaselineTable coverage primitives

**Files:**
- Modify: `src/sextant/ranking/baseline.py` (add two methods to `BaselineTable`, after `window`/`_median`, before `dump_baseline`)
- Test: `tests/proofs/test_baseline_coverage.py`

**Interfaces:**
- `BaselineTable.covers(self, symbol: str, segment: str) -> bool`
- `BaselineTable.sessions(self, symbol: str, segment: str) -> tuple[str, ...]` — ISO session dates ascending, empty when absent

- [ ] **Step 1: Write the failing proof** for a table with AAPL on two PRE sessions, `BRK.B` on one PRE session, and no RTH slice: `covers("AAPL","PRE")` true, `covers("MF","PRE")` false, `covers("AAPL","RTH")` false; `sessions` returns the two ISO dates in order and `()` for a missing key.
- [ ] **Step 2: Run it and watch it fail** (methods absent).
- [ ] **Step 3: Implement** `covers` as `bool(self._curves(symbol, segment))` and `sessions` as `tuple(curve[0].session for curve in self._curves(symbol, segment))`.
- [ ] **Step 4: Run the proof** green.

### Task 2: Coverage partition and receipt field

**Files:**
- Create: `src/sextant/ranking/baseline_coverage.py`
- Test: `tests/proofs/test_baseline_coverage.py`

**Interfaces:**
- `bare_symbol(symbol: str) -> str` — strips one trailing `.ALPACA` venue suffix only; `BRK.B.ALPACA` -> `BRK.B`
- `partition_covered(baseline: BaselineTable, symbols: Iterable[str], segment: str) -> tuple[tuple[str, ...], tuple[str, ...]]` — `(covered, missing)` in caller order, caller spelling kept
- `coverage_receipt(baseline: BaselineTable, symbols: Iterable[str], segment: str) -> dict[str, dict[str, object]]` — per name `{"segment", "state": "covered"|"baseline_missing", "sessions": int, "latest_session": str|None}`

- [ ] **Step 1: Write failing proofs** for the partition order, the missing name landing in the second tuple, `BRK.B.ALPACA` mapping, and the receipt's covered/missing states with session counts.
- [ ] **Step 2: Run and watch fail.**
- [ ] **Step 3: Implement** on top of `BaselineTable.covers`/`sessions`; no new coverage rule.
- [ ] **Step 4: Run green.**

### Task 3: The recipe module

**Files:**
- Modify: `src/sextant/data/baseline_bars.py` (rename private `_prior_sessions` to public `prior_xnys_sessions`; update its two callers; no behaviour change)
- Create: `src/sextant/data/baseline_recipe.py`
- Test: `tests/proofs/test_baseline_recipe.py`

**Interfaces:**
- `RECIPE_SEGMENTS = ("OVERNIGHT", "PRE", "RTH", "POST")`
- `SEGMENT_FILES = {"OVERNIGHT": "overnight.json", "PRE": "pre.json", "RTH": "rth.json", "POST": "post.json"}`
- `segment_table(table: BaselineTable, name: str) -> BaselineTable` — one segment's samples, same provenance/known_at/feed
- `build(client: BarsClient, symbols: Sequence[str], *, as_of: date, known_at: int, prior_sessions: int = 20) -> dict[str, BaselineTable]` — overnight from `fetch_overnight_baseline`, PRE/RTH/POST from `fetch_baseline(feed="sip")`
- `verify(tables: Mapping[str, BaselineTable], symbols: Sequence[str]) -> None` — every segment present, exactly one segment per table, feed `boats` for OVERNIGHT and `sip` otherwise, sample symbols exactly the requested set; raises `ValueError` naming the defect
- `render(tables) -> dict[str, str]` — filename -> `dump_baseline` text plus newline, `load_baseline` round-trip checked, identity preserved
- `publish(out: Path, tables, *, command, as_of, symbols, sessions, known_at, prior_sessions, source, universe) -> dict[str, Any]` — verify, stage, hash, move data files, write `manifest.json` last
- `run(client, symbols, out, *, command, as_of, known_at, prior_sessions=20, source="symbols", universe=None) -> dict[str, Any]`
- `resolve_universe(path: Path) -> tuple[str, ...]` — reads `rows[*].symbol` from a `python -m sextant.paper.c_universe --out` artifact, order preserved, duplicates removed
- `main(argv=None, *, client_factory=None, now_ns=time.time_ns) -> int` — `--out` required; mutually exclusive required `--symbols` or `--universe`; `--as-of` default the current segment's session date; `--prior-sessions` default 20; known_at = now

**Manifest shape:** `{"command", "as_of", "known_at", "prior_sessions", "window": {"first_session", "last_session"}, "symbols", "source": "symbols"|"k2_universe", "universe", "files": {filename: {"segment", "feed", "sha256", "samples", "symbols"}}}`.

- [ ] **Step 1: Write failing proofs**: four files, one segment each, identical schema keys, complete symbols; manifest matches published sha256s, command, as_of, window, feeds; each file loads with `load_baseline`; a deferred `verify` case rejects a table set missing a symbol in one file; a fetch refusal leaves the output directory without baseline files; `--universe` path from a K2 artifact wires through `main`; the fake bars client gets one boats request and one sip request.
- [ ] **Step 2: Run and watch fail.**
- [ ] **Step 3: Implement** the module and the `prior_sessions` rename.
- [ ] **Step 4: Run green.**

### Task 4: The tracked command and its documentation

**Files:**
- Modify: `justfile` (add `c-baselines` before host-only recipes)
- Modify: `lanes/paper/README.md` (C baseline build paragraph; four files, manifest, coverage-checked arming, `--universe` source)
- Modify: `docs/manifest.md` (new row after "Overnight baseline fetcher for the 24/5 lane")
- Modify: `docs/superpowers/plans/2026-11-10-c-per-segment-baselines.md` (check off steps)

**Interfaces:**
- `just c-baselines --out DIR --symbols SYM...` or `just c-baselines --out DIR --universe PATH` -> `uv run --frozen python -m sextant.data.baseline_recipe ...`

- [ ] **Step 1: Add the recipe** and read the parser help through it (no vendor call).
- [ ] **Step 2: Add the lane README paragraph and the manifest row** naming both proof files.
- [ ] **Step 3: Run `just --list`** and confirm the recipe is advertised.

### Task 5: Verification and hand-off report

**Files:**
- Create: `/home/sextant/sextant-data/handoffs/tasks/c-track2/scratch/pr-body.md` (not committed)

- [ ] **Step 1:** Run the two new proof files and `just prove`.
- [ ] **Step 2:** Run `bash /home/sextant/sextant-data/roster-ops/ci-local.sh` from the worktree root; record the result and any pre-existing host-only failure as UNKNOWN with evidence.
- [ ] **Step 3:** Confirm `git diff --stat` touches no owned file, no secret, no private path.
- [ ] **Step 4:** Write the PR body with the five required sections, the exact manifest row in double quotes, upstream references with dates, and the one marker line. Commit; do not push.
- [ ] **Step 5:** Send worker_done with head, checks, acceptance checks, exact `c_live_main.py` wire-up sites, and the body path.
