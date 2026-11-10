# Compaction Is Native Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Claude Code session compact the shared keep list and the role's own state file, using Claude Code's documented `SessionStart` (`compact`) and `PreCompact` hooks.

**Architecture:** One checked-in stdlib script, `scripts/compact_context.py`, serves both documented hook events and a `--check` used by `just session-start`. `SessionStart`/`compact` prints one fixed reminder plus the session role's state-file pointer (path and modification time); `PreCompact` prints the role's extra keep lines for the summarizer. Role resolution is `--role`, else the hook input's documented `agent_type`, else the script prints every known role's pointer rather than guessing.

**Tech Stack:** Python 3.13 stdlib only; pytest proofs under `tests/proofs/`; repo `just` recipes.

**Spec:** the dispatch brief for this task (sha256 18c31887b591d5eb63ee32ca720c6cca4acec682ec7dac5ea2189c812d3faa16), section N1; authority LEAD-2228-native-practice-convergence.md (sha256 65bf019eafb341e18340c61bfe615bdc77d23fbbd46028f58ddf3d6aa0c53043). Native execution (executing-plans) because the dispatch brief says do the task myself, no subagents.

## Global Constraints

- `permissions.deny` in `.claude/settings.json` stays byte-identical; `model` and `env` are untouched.
- Hook commands exit 0 always, print only, make no network call and no git write, never print an environment variable's value or file contents.
- Hook stdout under 10,000 characters per hook (code.claude.com hooks documentation, read 2026-11-09).
- `.claude/hooks/` stays absent; the script lives in `scripts/`.
- Never push; stop after the local checks and the PR body.

## Review Focus

- A session with no state file (fresh host, worker role) must still exit 0 and print a useful pointer, not a traceback.
- A missing script or broken stdin must not block a compaction: PreCompact exit 2 blocks, so the command ends with `|| true` and the script catches all exceptions.
- The hook output must never gain from the state file's contents, so fixture state files carry a sentinel that must not appear.
- A stale dispatcher/lander/tracker snapshot name must not be printed: resolve the newest `STATE-*.md` in the role's directory at run time.
- The output for every role, including the unknown-role table, is measured against the 10,000-character cap.

---

### Task 1: The hook script and its proof

**Files:**
- Create: `scripts/compact_context.py`
- Test: `tests/proofs/test_compact_context.py`

**Interfaces:**
- Produces: `ROLES: tuple[str, ...] = ("lead", "dispatcher", "lander", "tracker", "worker")`; `CAP = 10_000`; `FIXED_REMINDER: str`; `role_from(argv: list[str], hook_input: dict) -> str | None`; `state_pointer(role: str, home: Path) -> str`; `session_start(role: str | None, home: Path, now: datetime) -> str`; `pre_compact(role: str | None) -> str`; `check(root: Path) -> list[str]`; `main(argv: list[str], stdin_text: str, home: Path) -> int`.

- [ ] **Step 1: Write the failing proof**

`tests/proofs/test_compact_context.py` asserts: CLAUDE.md section ≤ 8 non-blank lines and names the owner's words, the role and state-file path, peers, open tasks, the owner wait, a ruling name and hash, and the drop list; settings declare exactly `SessionStart` matcher `compact` and one `PreCompact` entry, each command calling `scripts/compact_context.py` and ending `|| true`; per-role `session-start` output names that role's pointer and mtime, carries `Reminder:` once, never contains the state file's sentinel; `pre-compact` names the role and stays under 10,000 characters; bad stdin and an empty HOME still exit 0; `--check` returns 0 on this repo; the justfile session-start recipe runs the check; the manifest row and the ADR-0022 amendment exist.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --frozen pytest tests/proofs/test_compact_context.py -v`
Expected: FAIL because `scripts/compact_context.py`, the hooks, the CLAUDE.md section, the justfile line, the manifest row and the ADR amendment are missing.

- [ ] **Step 3: Implement `scripts/compact_context.py`**

stdlib only; `ROOT = Path(__file__).resolve().parent.parent`; state mapping `lead: ("handoffs", "LEAD-STATE.md")`, `dispatcher: ("roster-ops/claude-successor", None)`, `lander: ("landing", None)`, `tracker: ("handoffs/practice-tracker", None)`, `worker: None`; a `None` filename selects the newest `STATE-*.md` in that directory. Hook modes catch every exception, print the fixed reminder (session-start) or the unknown-role extras (pre-compact), and return 0.

- [ ] **Step 4: Run the proof to verify it passes**

Run: `uv run --frozen pytest tests/proofs/test_compact_context.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/compact_context.py tests/proofs/test_compact_context.py
git commit -m "feat(harness): add the compaction context hook script"
```

### Task 2: Settings hooks and the shelf proof

**Files:**
- Modify: `.claude/settings.json` (add `hooks` after `permissions`)
- Modify: `tests/proofs/test_claude_shelf.py`
- Modify: `docs/manifest.md` (Superpowers row proof name)

- [ ] **Step 1: Update the shelf proof first (red)**

Remove `assert "hooks" not in settings` from `_server()`; rename `test_superpowers_is_a_version_pinned_native_plugin_without_project_hooks` to `test_superpowers_is_a_version_pinned_native_plugin`; keep `assert not (ROOT / ".claude/hooks").exists()` and assert every declared project hook command calls `scripts/compact_context.py`.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --frozen pytest tests/proofs/test_claude_shelf.py -v`
Expected: FAIL because no `hooks` key is declared yet.

- [ ] **Step 3: Add the two documented entries**

`SessionStart: [{"matcher": "compact", "hooks": [{"type": "command", "command": "python3 -I \"${CLAUDE_PROJECT_DIR}/scripts/compact_context.py\" session-start || true"}]}]` and `PreCompact: [{"hooks": [{"type": "command", "command": "python3 -I \"${CLAUDE_PROJECT_DIR}/scripts/compact_context.py\" pre-compact || true"}]}]`.

- [ ] **Step 4: Run the proof to verify it passes**

Run: `uv run --frozen pytest tests/proofs/test_claude_shelf.py -v`
Expected: PASS.

### Task 3: CLAUDE.md keep list, session-start check, manifest, ADR, research note

**Files:**
- Modify: `CLAUDE.md`, `justfile`, `docs/manifest.md`, `docs/adr/0022-memory-rag-and-enhanced-dsh.md`, `docs/research/2026-11-06-claude-shelf.md`, `llms.txt`

- [ ] **Step 1: Run the proof (red)**: `uv run --frozen pytest tests/proofs/test_compact_context.py -v` — FAIL on the missing section, justfile line, manifest row and ADR amendment.
- [ ] **Step 2: Add `# Compact instructions`** with exactly eight non-blank lines (owner's words; role and state-file path; peers; open tasks and the owner wait; rulings by name and hash; decisions and why; exact paths/commands/errors/values; drop tool output, fetched pages, finished work).
- [ ] **Step 3: Add `python3 -I scripts/compact_context.py --check` to `just session-start`.**
- [ ] **Step 4: Append the manifest row** first cell `Compaction is native` at the end of `## Claude shelf`, with the five code.claude.com pages and their read date.
- [ ] **Step 5: Amend ADR-0022** with `**Amended 2026-11-09 (compaction is native):**` and the research note with its dated sentence.
- [ ] **Step 6: Regenerate `llms.txt`**: `python3 scripts/ecosystem_index.py --write`.
- [ ] **Step 7: Green**: `uv run --frozen pytest tests/proofs/test_compact_context.py tests/proofs/test_claude_shelf.py -v`.

### Task 4: Whole change verification and PR body

- [ ] **Step 1:** Run the Roster ops local CI runner (`ci-local.sh`) from the worktree root; record the output, any killed run, and any host-only failure as UNKNOWN with its evidence.
- [ ] **Step 2:** Write the PR body to the dispatch's scratch `pr-body.md` with the template headings, one family marker line, no other routing-marker text and no private paths.
- [ ] **Step 3:** Commit everything as one concern and stop with no push.
