# Sim lane

**Charter.** Prove a rule before any broker sees it: replay recorded data as MODELED, then run the same strategy against a live feed as SIMULATED in a sandbox that owns its own socket, client, account id and namespace. Replay selects methods; the sandbox proves the stack survives live data. Neither proves live routing, borrow, margin or broker limits. ([ADR-0008](../../docs/adr/0008-broker-roles.md), [ADR-0002](../../docs/adr/0002-philosophy-and-lanes.md))

**Hours.** Replay 24/7, on demand; the continuous coordinator that would keep it running is OFF (below). Sandbox 24/5, on the live feed, with LIMIT orders only outside regular hours.

**Limits.** No broker credentials and no submitted broker order in replay. One fresh arm-run per process, replay concurrency 1 rising only on measured peak RSS, costs at 1× and `cost_stress_multiple`. The sandbox sends `client_id` on every command and shares no account with paper or live ([ADR-0002](../../docs/adr/0002-philosophy-and-lanes.md)).

**How it is built.** Replay (R) is NautilusTrader `BacktestNode` for bars-only and `BacktestEngine` where catalysts must interleave, over the one `ParquetDataCatalog`, one fresh arm-run per process, at 1× and 2× costs. Sandbox (S) is the same strategy objects on the live Alpaca feed, SIMULATED, in its own client, account id and namespace. Broker paper is the tier above. Every run from all three appends to the one `TrialLog` under its tier label; tiers are never pooled and a missing return is never imputed as zero ([ADR-0018](../../docs/adr/0018-evidence-and-learning-loop.md), [ADR-0013](../../docs/adr/0013-us-equity-data-stack.md)).

**The continuous replay lane is OFF.** Its unit is render-only, nothing is installed, and 0 of 8 enable steps are receipted; no auto-restart, timer or boot enable is authorized. The [reviewed redesign (#536)](https://github.com/seathatflowsinourveins/northstar-trading/blob/a8c3f86a3890085e4c69ce2522e603df886d7442/docs/research/2026-11-05-sim-lane-entry.md) supersedes the 09:35:05 ET proposal: prestart the parent with a bounded instrument superset, bind receipt authority when the receipt exists, deliver a registered custom-data envelope, and check a separate entry-age budget at the last hop, with three distinct acknowledgements. The fixed cutoff is no earlier than 09:36:00 plus a measured whole-set capture-to-receipt budget; **09:36:05 is only the earliest candidate; no number is approved**. The eight, each a recorded receipt before the next: (1) a reviewed immutable build with dispatch resolved; (2) the publisher's measured Redis-outage and slow-consumer acceptance; (3) one cumulative-ledger custody; (4) source receipts — native Equity exports covering every instrument once, PIT generation/history/corporate actions/universe/BBO, truthful cutoff and construction clocks; (5) a fresh OFF config; (6) an actual OFF CLI run that reports OFF and touches nothing; (7) an isolated bounded foreground probe — four-PID readiness, dispatch-age margins, entry/exit/refusal books, source loss, SIGTERM, child loss, full process-tree retirement; (8) the explicit enable decision, with the unit re-rendered and re-hashed before `ENABLED` exists. V0–V3, publisher V4 and the explicit enable decision remain required. The old cold 20-name start took 6.14 s against the 5 s gate (one observation, not an upper bound; [enable checklist](https://github.com/seathatflowsinourveins/northstar-trading/blob/8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa/docs/research/2026-11-05-sim-lane-coordinator-inputs.md#L100-L113)).

**What it runs.**
- NautilusTrader `BacktestNode` for bars-only and `BacktestEngine` where catalysts must interleave, on one `ParquetDataCatalog` per environment, sorted by `ts_init`; events after bars for equal timestamps ([ADR-0013](../../docs/adr/0013-us-equity-data-stack.md)).
- Identical fill, fee and latency models plus the same `random_seed` for every A/B pair; a comparison changing two things at once is not a result ([ADR-0015](../../docs/adr/0015-research-lane-and-strategy-sourcing.md)).
- Optuna 5.0.0 single-objective multivariate TPE, 5–8 parameters, 100–300 trials, lower-quantile CPCV-path Sharpe with `WilcoxonPruner` across folds ([ADR-0015](../../docs/adr/0015-research-lane-and-strategy-sourcing.md)).
- The extreme-mover arm, its ranking publisher and the exit study, replayed from the catalog so their tables reproduce exactly ([ADR-0024](../../docs/adr/0024-extreme-mover-ranking-and-early-entry.md)).

**Negative evidence.** On 1,025 October 26–28 entries at assumed 3/6 bps per side, Hold 15:55 returned 76.44/70.42 bps versus the best active exit's 54.78/48.76; it beat all 96 active variants. The later six-arm minute approximation tied at −$55.14 gross and −$62.67 modelled net on two opportunities per arm, with zero qualified calibrated tick opportunities. Neither result validates gain protection or re-entry; retain the policy as a requirement and test its economics ([ADR-0025](../../docs/adr/0025-gain-protection-and-fast-exit.md)).

**Rules.**
- Register criteria and the estimand before results; walk-forward with purge and embargo; DSR > 0.95 at the effective trial count, PBO ≤ 0.05 by CSCV with S=16, PSR ≥ 0.95, sign kept at 2× costs, one untouched 12–24-month holdout ([ADR-0019](../../docs/adr/0019-validation-and-merit.md)).
- Hold-flat is the control, not a formality: a strategy that does not beat it after costs has not earned a promotion ([ADR-0002](../../docs/adr/0002-philosophy-and-lanes.md)).
- A replay with synthetic arrivals is not operational latency, and a minute-bar study is not tick execution; say which one a number came from.

**Sources.** NautilusTrader `v2.0.0rc8` (`d53849b216e20f2c122ca01b4dd0da377638b186`); skfolio 1.12.5 for allocator experiments; harvested northstar-lanes ADR-0009 and northstar-trading ADR-0013/0019 at the pins in `docs/manifest.md`; sim-lane build and enable gates from northstar-lanes ADR-0003's 2026-11-05 amendment and the trading checklist record.

**Row 6 mechanism proofs.** `timeout 180 uv run --frozen pytest tests/proofs/entry` exercises the entry reducer and native LIMIT lifecycle on explicit synthetic inputs. [Carry and limitations](../../docs/adr/0004-entry.md#replay-evidence); [entry registry](entry-parameters.json) retains unavailable values, including the six missing starts. This enables no account or continuous lane.

**Row 8 mechanism proofs.** `timeout 180 uv run --frozen pytest tests/proofs/custody` checks source-adapted custody, pacing and latched halt, with native MODELED house-order kill-to-flat and an untouched owner-labelled fixture. [Minimal bridge and limits](../../docs/research/2026-11-06-custody-replay.md); [controls](../custody-parameters.json). This is neither native external claiming nor a broker crash/reconciliation or B-ready receipt.

**Row 9, focus step 5.** `sextant.reentry` consumes fixture ranking, custody,
qualified-entry and sizing seams in a native replay observer, with zero orders.
It proves admission/cooldown/lift, not a complete R1–R6 detector or account port.
Missing detectors, confidence/whipsaw lifecycle, live/IBKR admission and durable
restart ownership remain unavailable. All production values in
`reentry-parameters.json` are null/UNCALIBRATED. Economics stays **NOT_RUN** for
#72's TrialLog; [source/capability evidence](../../docs/research/2026-11-06-reentry-admission.md).
