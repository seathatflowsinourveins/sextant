# TradingView display implementation plan

**Goal:** Implement issue #52's fixture-tested official MCP membership sync and
four immutable Pine display presets under ADR-0021 and ADR-0026.
**Spec:** `docs/adr/0021-tradingview-display.md`,
`docs/adr/0026-tradingview-sync-and-order-presets.md`, issue #52.
**Execution:** Dispatched worker implements this task itself; gh-aw provides the
required other-family PR review. No helper workers or owner-session attempts.

## Source and approach

Adapt the minimal research membership/readback slice from
`seathatflowsinourveins/northstar-trading@paper
8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`: `tradingview/research.py`,
`sync.py`, `auth.py`, `scanner/display_lists.py` and the four Pine files.
Use MCP Python SDK v2.3.0 (`2118f14f8a19bc158d8a1cf90af58d85d187f849`)
and official TradingView MCP/Pine documentation read 2026-11-06.
The accepted ADRs choose batch membership/readback; per-symbol search belongs to
the separate deployment mode and Desktop controllers have no authority here.
Consume the producer's display unit without rebuilding ranking or focus policy.
Keep RAM-only SDK OAuth behind an explicit owner command; no stored grant.

## Constraints and review focus

- Only `NS movers` and `NS focus`; membership changes never reorder survivors.
- Reject missing, stale, future, mixed-generation and empty movers input before
  OAuth; default freshness 1,200s, configurable 1–3,600s; snapshot lag ≤600s.
- Omit at most five unmapped names, with exact cross-list venue identity.
- Discover/preflight schemas before writes; serialize and check expiry after
  pacing. Unknown envelopes and ambiguous writes stop without replay/rollback.
- Read both lists; one corrective removal for extras; never retry rejected
  additions. More than five distinct rejections or a residual mismatch fails.
- No orders, quotes/feeds, broker tools, debug-port connection or persistent
  tokens. Dated `NS <date> · <stem>` script titles and source hashes.
- Pine remains the upstream display formulas, including completed ATR22 ×3 on
  five-minute bars. Compilation, bindings, inputs and persistence need owner
  readback; local file validation never claims those acceptances.

## Tasks

### Task 1: Producer input and MCP sync

- [x] Add fixture proof for generation/freshness, mappings, membership diffs,
  identity/schema refusals, partial/ambiguous replies, readback rejection limits,
  corrective removal and expiry while paced; observe RED.
- [x] Implement `src/sextant/tradingview/{inputs,sync}.py` with
  `read_research_inputs(unit, now, max_age)` and
  `sync_research(tools, inputs, apply=False)` using the pinned contract.
- [x] Run the proof and full suite; observe GREEN.

### Task 2: Owner entry point and Pine artifacts

- [x] Add failing offline CLI/OAuth-boundary and preset package tests.
- [x] Add `auth.py`, `__main__.py`, four Pine files and a hash manifest; adapt
  the SDK memory store and callback with no credential-bearing diagnostics.
- [x] Verify offline CLI plus fixture proofs; document owner acceptance separately.

### Task 3: Evidence and landing

- [x] Add the single TradingView manifest row, source/read-date evidence,
  parameter provenance and lane operating instructions. Put Lesson in PR body;
  the lead owns the handbook write (issue #52, ADR-0018).
- [ ] Run required checks, review the diff, commit and open one PR with `just pr`.
- [ ] Report checks, PR link and pending owner acceptance on #52; report to the
  coordinator once the required checks are green or a concrete blocker remains.

Evidence before landing: 35 TradingView proofs pass; `timeout 300 just ci`
passes with 92 tests, clean lint/type/workflow checks and no secret findings.
After rebasing onto the landed exit engine, `timeout 300 just ci` passes with
108 tests. `timeout 300 just prove` reports 112 passed and two unchanged
container-only failures on the native distro: firewall chain and restricted
sudo. No host permissions/firewall changes were made to satisfy those tests.
The calendar emits four upstream pandas deprecation warnings. The display
slice is 798 Python source lines; row 12's ~800-line figure is an estimate,
not reserved capacity or proof that paper/IBKR components fit it.
