# Saved Workflow harvest evidence

Read 2026-11-06. This is the approved plan's native-workflow harvest, not a new orchestrator.

- **upstream checked:** seathatflowsinourveins/northstar@main `b384d298d217d3f8d9aa83356994629536a34795`:`claude/workflows/{research-plan-build,adversarial-verify,backtest-tournament}.js`. Retrieved with `git -C /home/choreo/Developer/northstar show <full-sha>:<path>`; each file starts from those bytes.
- **upstream checked:** the same pin's `evals/workflows/check-syntax.sh`, `check-models.mjs`, `mock-runtime.mjs`, `run-scenarios.mjs` and `scenarios/backtest-tournament.mjs`. The proof adopts its async parser wrapper, reusable alias scanner, deterministic test runtime and null/fault sweeps. Scanner CLI/other-workflow pins and unavailable custom-agent definitions are omitted.
- **upstream checked:** [Claude Code Workflows](https://code.claude.com/docs/en/workflows), read 2026-11-06, “Save the workflow for reuse,” “Pass input,” “Edit a saved script” and “Behavior and limits.” Project saves use `.claude/workflows/*.js`; literal `export const meta` comes first, followed by an async body. The script has no direct shell/filesystem or imports; agents perform that work. Phase titles match metadata. `args` supplies input. Wall clocks/randomness in the script are unavailable.
- That page documents `agent()` returning null on a stopped/failed agent and retaining null pipeline slots. We preserve failed slots and source labels. The offline tests also exercise the source harness's alternative null-short-circuit interpretation.
- The page documents `CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` (1–256) from v2.1.269. This covers Sextant's v2.1.318 pin, so its project settings set `8`. Actual scheduling on v2.1.318 remains **UNVERIFIED**; `claude --version` here returned 2.1.319. No native workflow was launched.

## Local contracts

`AGENTS.md` Rule 1 supplies the source/manifest rule; source-less proposals stop. GitHub Issues replace task records. The repository's cross-family `review` check replaces the optional delegation skill in research-plan-build; absent or wrong-SHA results stay inconclusive. Missing custom agent types and research/MCP/CLI skills are replaced by explicit role prompts and repository/public sources. Existing alias and effort assignments for retained jobs are preserved.

[ADR-0019](../adr/0019-validation-and-merit.md) owns validation and cumulative trial accounting. [ADR-0020](../adr/0020-live-lane.md), “Changes for Sextant,” owns the substitution of exact-SHA two-family review for the old verdict-file gate. Accordingly adversarial-verify returns an on-demand report without the old recorder/helper/hash/quarantine machinery; no required check is added. Tournament occupancy, merge and deployment phases are removed; review identity checks now qualify research candidates in its final report.

The final review reproduced two coverage/identity gaps with the adopted offline runtime. Carrying the source gate's no-base/no-risk-credit rule into the report makes an unresolved branch base INCONCLUSIVE. Reusing research-plan-build's duplicate-ID check before tournament work prevents one variant from overwriting another's review. Both have regressions observed failing before the fixes; no new recorder or deployment gate is introduced.

`rg --files src lanes` at the harvest base showed only the EMA thin slice and its strategy/research card. The general strategy runner, US/PIT catalog, vectorbt sweeps, canonical TrialLog writer on `ledger`, and statistical/merit contract producers are not installed here. Tournament backtest/validation waits for those implementations; it must not start trials without their cumulative writer. Generation, prerequisite diagnosis and the final report can run without claiming merit. The workflow implements none of those missing components.

## Verification and limits

Run `uv run --frozen pytest tests/proofs/test_workflows.py` for syntax, alias routing, obsolete-tool exclusions, resource-setting checks and offline failure scenarios; it also runs in normal pytest discovery. The parser wraps the saved body before `node --check`, as upstream does: a saved workflow's top-level return is not a standalone ES module.

The mock proves script decisions for supplied responses, not agent honesty, Claude's actual loader, permissions, worktree scheduling, API schemas or model availability. It cannot certify live two-family review, TrialLog persistence, statistical calibration, prospective fills or strategy merit. None of the workflows has run in the clean distro yet. Before the lead's first native edit/run, load `/workflow-authoring` and `/reload-skills` as the upstream page directs.
