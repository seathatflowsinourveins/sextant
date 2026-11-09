# Options and Jev: source revisions survive replay

Row 13, [#75](https://github.com/seathatflowsinourveins/sextant-archive/issues/75), carries
[ADR-0016](../adr/0016-options.md) and [ADR-0017](../adr/0017-jev-judgments.md).
The options lane's [rules](../../lanes/options/README.md) apply this lesson.

The pinned catalyst screen keeps distinct source events active together. A later
positive event must not hide a usable negative from another event. Within one event,
its newest known revision replaces the old version even if the new answer is missing
or fails; falling back to the old answer would silently use superseded evidence.
The offline witness initially lost that distinction and now exercises both cases.

Answer readiness also differs from service response time. Replay cannot consume a
response before its recorded availability, and durable readiness at the request budget
is already late. Preserve that LATE status with the original budget and parameter hash;
a later, wider policy cannot turn it into an answered observation. Registry rows retain
the source's 2026-10-31 last-change dates. The policy expires visibility at the exact 20:00 New York accounting
boundary, even on weekends, holidays and DST changes. Unknown token usage remains null.
Each arm uses one answer label; recalled and live-ledgered answers never pool.

Sources, inspected 2026-11-06:

- seathatflowsinourveins/northstar-trading@paper
  `8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`:
  `judgments/catalyst_screen.py` under `src/northstar_trading/`, `_activate`,
  `receive`, `_consume`, `_effect`, `evaluate`; `judgments/jev.py` and `contract.py`;
  `sessions.py:trading_day`; `configs/paper/profiles.yaml:82–87`.
- The copied SDK Noul/Choice question literals have canonical SHA-256
  `9510971fb404689e361a5c775e568a891a7b6ed50ed0460ea9904a11ff06cacb`.
  An AST extraction of the pinned source matched the copied questions exactly.
- typesafe-ai/typesafe-sdk-python@v0.7.5
  `f36e68549ceca3191e5791e5f99ea1baa1a258b5`: typed questions and optional usage.
  The locked PyPI wheel has SHA-256
  `967a8b61494d536abb55ee3f3a2b10e81685cb6baad6ccdcab588bdc6c9b86d2`.
- typesafe-ai/skills@v0.6.2 `302eea662c54bca6730873fe245bec1d69ebc23d`:
  `skills/typesafe-ai/SKILL.md`; [Noul](https://docs.typesafe.ai/primitives/noul.md),
  [Choice](https://docs.typesafe.ai/primitives/choice.md) and
  [confidence](https://docs.typesafe.ai/confidence.md), read 2026-11-06.
- nautechsystems/nautilus_trader@v2.0.0rc7
  `55c0e82053142bce3a5cba4de4221d3929c2d3bc`: `docs/concepts/actors.md` and
  the installed engine/model types. Data actors have no order-management API.

`tests/proofs/test_options_jev.py` is offline software evidence on synthetic US-equity
quotes and fabricated typed answers. It proves no data entitlement, actual model
quality, determinism, latency SLA or after-cost lift. The six starts remain
**UNCALIBRATED**. Options observations remain raw and zero-weight.

Simulation and cumulative-ledger binding are **NOT_RUN** pending #72. No experiment
has run, no second ledger exists and no trial count or effective-N is invented.
After row 10 lands, bind the frozen ON/OFF arms, implementation SHA, source/parameter
hashes, common fill/fee/latency models and seed through its canonical writer, then
record every arm/run and any failure before collecting research results. Revisit on
that binding, a model/question change, a contrary replay or calibration evidence.
