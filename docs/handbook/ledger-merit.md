# Native statistics do not qualify a session

The crypto fixture provides no qualified US-equity session or whole-session return. Native P&L, portfolio statistics and closed-cycle counts describe its recorded execution; they grant no admission. Archived NETTING cycles count even when the current position ID is reused. Both synthetic exit arms are MODELED, with a separate execution label.

Sources: NautilusTrader rc8 `d53849b216e20f2c122ca01b4dd0da377638b186`, `docs/concepts/portfolio.md` statistics/TradeCount example; [ADR-0018](../adr/0018-evidence-and-learning-loop.md) and [ADR-0019](../adr/0019-validation-and-merit.md).

A writer holds the sourced reentrant flock across registration, execution and terminal publication. On the next acquisition, a known local writer's abandoned RUNNING rows become FAIL without losing attempts. Active leases block another writer; unknown legacy or foreign ownership requires owner resolution. A second-registration failure terminalizes the first. Every rerun gets fresh IDs and native artifact directories; old rows and Parquet metadata survive append.

Source: northstar-trading@`8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`, `validation/trials.py`, `sim_lanes/runner.py:writer_lock`, `persist.py`. The canonical path and protected-ref custody remain #110's contract. Code binding stays UNVERIFIED; no receipt hash certifies another producer's claim.

The owner's size ruling defers custom merit, inference, appender and registry code to #147. Remove unsupported verification paths rather than treating a matched hash as proof of the measurement inside. Preserve historical source hashes when retiring superseded notes; the published qualifying-leg convergence is immutable and remains byte-for-byte unchanged.

At CI handoff, a missing merge ref is not a test result. Merge the landed base, keep main's full pytest section, regenerate the lock with uv lock, and run just ci. New proofs belong under tests/proofs without a testpaths edit. Practices are proposed in the PR body for the program lead's single writer.

[Scope, source map and budget hold](../research/2026-11-06-ledger-merit.md).

## TrialLog dependencies for the ledger writer

Archive #110 at `fbe075a49f673b07ec8cf98b2ae580605123e34c`,
`src/sextant/validation/trials.py:77-357`, carries legacy rows without arm identities,
current-N refresh and once-only terminal payload updates. The schema and terminal outcomes
stay frozen while n_trials and effective_n refresh to N on every row at each commit:
n_trials is the file's current N over all tiers, not the count when the row was written, and
effective_n is float(N), the upstream no-discount fallback, never a measured effective count.
No reader may treat it as measured; inference freezes its own snapshot (ADR-0019). Keep these dependencies with the
writer's proofs: schema compatibility alone does not establish cumulative custody.
This dependency commit adds no protected-ref writer or producer-root migration.
