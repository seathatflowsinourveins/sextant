# Saved lead Workflows

The harvest's [source and contract evidence](../research/2026-11-06-saved-workflows.md) explains what was adopted and what remains unverified. These project workflows become `/research-plan-build`, `/adversarial-verify` and `/backtest-tournament` in Claude Code. Load `/workflow-authoring` before a native edit and `/reload-skills` after changes.

- Research/build takes `{task, test_cmd?, slug?, cross_model?}`. It builds in dependency waves and reports one tested integration branch. `cross_model: true` reads an existing exact-SHA cross-family GitHub review check; missing review evidence is inconclusive. It does not publish or merge the resulting PR.
- Adversarial review takes `{target, base?, lenses?, expect_sha?, date?, notes?}`; optional `{repo, worktree, expect_sha}` reviews a clean frozen worktree. It preserves review lenses and independent refutation, returning findings and exact identity. Its report adds no required check and cannot replace live's two-family review.
- Tournament takes `{hypothesis, universe, period, variants?, date?}` and ends with a report. Lane/deployment arguments are rejected. Its missing prerequisites and the canonical trial writer are documented in the evidence note; no broker endpoints or deployments belong to this workflow.

Lesson: a dead research angle, implementer, reviewer or validator is missing evidence. Preserve its identity and failures in the report. Do not convert missing prerequisites to a passing gate, erase rejected attempts, or substitute a second trial ledger. A syntax proof and a mock run do not establish trading merit; [ADR-0019](../adr/0019-validation-and-merit.md) owns that evidence.
