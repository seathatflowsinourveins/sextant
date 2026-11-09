# Ranking early-entry e2e harness (research only)

This package runs the frozen K3 development table on one session. It is
the Part 1 harness: it measures the K2 ranking state, the mean-baseline
variant, the premarket gap arm, the keep-alive arm and the Page arm on the
same sealed cohort, with one ledger row per arm and no entry, sizing, fill
or return claim. Evaluation code stays here, never in `src/`.

Protocol authority: `docs/research/2026-11-06-ranking.md`, K3 section
SHA-256 `fecd378a5b40fc2d6d2e03b16dda605c9f82102dad8e95735ffef24a459aca0b`
at commit `ba5116de4dc84444bbd00e62dfe9bc0b1b691001`; K2 section
`fc019b18602429f0f641588eed45467ca555f4bbc568284327f1a346dd33426f`.
The harness refuses to run if either digest moves.

## What it computes

- Cohort: a JSON file of `truth` movers and matched `controls`, plus the
  prior close for each name. The builder reads the e2e-omh
  `metrics.json` and the prior session's daily bars; it emits
  `ranking-e2e.cohort/1`.
- Baselines: five prior XNYS sessions (2026-11-02..06), PRE 04:00-09:30
  (330 minute offsets) and RTH 09:30-11:35 (125), cumulative
  `close x volume` and bar count at each minute, missing minutes carried
  forward. K2 uses the per-offset median; the mean arm uses the mean.
- Replay: one synthetic tick per non-zero-volume minute at bar close,
  zero-size anchor at the segment start, one generation per minute. The
  segment end is widened by one nanosecond so the 09:30 and 11:35 bar
  closes are inside the engine's half-open `[start, end)`.
- Arms: K2 (`move x dvol_ratio`), mean baseline (one discrete change),
  premarket gap (first open gap >= 1%), keep-alive on K2 top-100
  membership, and Page CUSUM (NOT_RUN: its five adapter rows are
  UNAVAILABLE at the seal). OFI and catalyst arms are
  `NOT_IN_FROZEN_PROTOCOL`; the frozen K3 section defines only the four
  named arms plus the K2 and hold-flat comparators.
- Metrics: detected/censored, recall at onset, p50/p90 signed lead
  (Hyndman-Fan type 7), first entry at or before onset, late entries,
  false flags per control-symbol-hour, and separate never-crossed
  control rates. Date is the block; one session is a development table,
  not a trial.

## Use

```
uv run --frozen python -m research.ranking_e2e.build_cohort \
  --metrics <metrics.json> --daily-dir <prior daily bars> --out cohort.json

uv run --frozen python -m research.ranking_e2e.runner \
  --cohort cohort.json --bars-root <raw 1min root> \
  --protocol-doc <ranking doc> --out <session dir>
```

`--protocol-doc` is required until the K3 section is on the checked-out
ranking doc; pass the worktree or checkout that carries commit `ba5116d`.
`--no-verify-protocol` exists only for synthetic tests.

## 2026-11-09 development table

Cohort: 4,647 candidates, 159 truth (bar-close onset), 249 controls,
205 never-crossed controls. One session, SIP raw 1-minute bars
04:00-11:35 ET.

| Arm | Recall @30 | Recall @100 | Rankable at onset | Other |
|---|---|---|---|---|
| K2 | 8/159 (5.03%) | 12/159 (7.55%) | 112 | 133 first entered top-100 at/before onset; 22 late; p50 lead 19,320 s; p90 21,756 s; false 0.1181/control-symbol-hour |
| Mean baseline | 9/159 (5.66%) | 14/159 (8.81%) | 113 | 132 first entered at/before onset; 22 late; false 0.1202 |
| Gap, first open >= 1% | 98/159 detected (61.6%) | - | - | p50 lead 900 s; p90 2,316 s; false 154/249 = 0.0816; never-crossed 124/205 = 0.0798 |
| Keep-alive | 14/159 persisted at onset | - | - | +2 over K2's 12; retained through an incomplete generation; p50 lead 19,320 s; p90 21,756 s |
| Page CUSUM | NOT_RUN | - | - | five adapter rows UNAVAILABLE; river defaults refused |
| OFI / catalyst | NOT_IN_FROZEN_PROTOCOL | - | - | no thresholds in the frozen section |

Onset strata: PRE 04:00-04:30 14, PRE rest 24, RTH 09:30-10:00 87,
RTH rest 34. K2's numbers reproduce the independent e2e-omh replay's
headline (8/159 and 12/159) on the same cohort. The figures are descriptive, one session,
with no interval, significance or after-cost claim (K3.7).

## Seal and ledger

`session.json` carries the eight seal items. At this session:
`session_list`, `cohort_controls`, `market_data`, `baseline` and
`implementation` are AVAILABLE; `registry` is PARTIAL (the 12 operational
rows are reviewed, but the entry/trading ages are UNAVAILABLE);
`triallog` is NOT_RUN pending the custodian ruling; `other_family_review`
is ABSENT. The trial state is therefore NOT_RUN and no row is appended.
`ledger.detection_row` produces the proposed 13-column MODELED row with
empty `days`, `daily_net_returns`, `fold_scores` and a null `objective`;
`ledger.append` refuses without a custodian ruling and never writes a
side ledger.

## Fidelity

- Bar-close replay, not trade ticks: `trades_accel` is a bar-count proxy
  and the bar's `n` field is not a trade stream.
- Freshness ages are not applied to a historical replay.
- RTH ends at 11:35 ET because that is the fetched data end, not the
  16:00 close.
- No PIT membership is available, so the W1 1,436-session cohort and its
  K2 run stay NOT_RUN; the 2026-11-09 e2e cohort is the only intraday
  cohort with bars and controls today.

## Tests

`tests/proofs/test_ranking_e2e.py` covers protocol hashes and the K3
presence gate, cohort validation and hashing, median/mean curves,
interpolation, gap semantics, the CUSUM recurrence, keep-alive membership,
percentiles, detection/ranking metrics and a synthetic end-to-end run.
Run `pytest tests/proofs/test_ranking_e2e.py -q` under the local memory
scope.
