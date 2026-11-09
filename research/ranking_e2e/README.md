# Ranking early-entry e2e harness (research only)

This package runs the frozen K3 development table on one session. It is
the Part 1 harness: it measures the K2 ranking state, the mean-baseline
variant, the premarket gap arm and the keep-alive arm on the same sealed
cohort. Detection-only results stay in the hashed report; they never
become TrialLog rows (custodian ruling, ADR-0019:26). There is no entry,
sizing, fill or return claim. Evaluation code stays here, never in `src/`.

Protocol authority: `docs/research/2026-11-06-ranking.md`, K3 section
SHA-256 `fecd378a5b40fc2d6d2e03b16dda605c9f82102dad8e95735ffef24a459aca0b`
at commit `ba5116de4dc84444bbd00e62dfe9bc0b1b691001`; K2 section
`fc019b18602429f0f641588eed45467ca555f4bbc568284327f1a346dd33426f`.
The harness verifies both digests by default and refuses to run if either
moves on the checked-out doc.

## What it computes

- Cohort: a JSON file of `truth` movers and matched `controls`, each with
  an official prior-session daily close and its source. The builder reads
  the e2e-omh `metrics.json` and the prior session's daily bars; a missing
  official close stays `prior_close: null`, is counted as an exclusion,
  and is never derived from `last_close` or the mover percentage.
- Labels: `survivor_only`, `pit_verified` and `inference_eligible` travel
  with the cohort verbatim. The 2026-11-09 table is not a dated PIT
  universe, so the W1 1,436-session K2 run stays `NOT_RUN`.
- Baselines: five prior XNYS sessions (2026-11-02..06), PRE 04:00-09:30
  (330 minute offsets) and RTH 09:30-11:35 (125), cumulative
  `close x volume` and bar count at each minute, missing minutes carried
  forward. K2 uses the per-offset median; the mean arm uses the mean.
- Replay: one synthetic tick per non-zero-volume minute at bar close,
  one generation per minute. There is no synthetic prior-close or
  segment-start tick: a zero-size anchor at a segment boundary uses that
  segment's first bar open only when the first bar starts exactly at the
  boundary. The segment end is widened by one nanosecond so the 09:30 and
  11:35 bar closes are inside the engine's half-open `[start, end)`.
- Every generation ranks the full K2 section 5 universe: all computable
  `state.latest` rows, not only the minute-active subset, and respects
  `publish_min_interval_s`. `universe` is recorded per generation.
- Arms: K2 (`move x dvol_ratio`), mean baseline (one discrete change),
  premarket gap (only the fixed 04:00-04:05 first open; trigger mode
  `NOT_RUN` because the frozen ADR-0024 does not record numeric
  thresholds), keep-alive on qualified K2 top-100 membership (current
  entry qualification, quota cap, 20:00 reset), and Page CUSUM
  (`NOT_RUN`: its five adapter rows are UNAVAILABLE at the seal). OFI and
  catalyst arms are `NOT_IN_FROZEN_PROTOCOL`; the frozen K3 section
  defines only the four named arms plus the K2 and hold-flat comparators.
- Metrics: detected/late/censored, recall at onset, signed p50/p90
  latency in seconds (`flag - onset`; Hyndman-Fan type 7), first entry at
  or before onset, late entries, false flags per control-symbol-hour,
  separate never-crossed control rates, the +/-60/120/300 s windows,
  per-name flag counts and paired K2 contrasts on identical names. Date
  is the block; one session is a development table, not a trial.

## Use

```
uv run --frozen python -m research.ranking_e2e.build_cohort \
  --metrics <metrics.json> --daily-dir <prior daily bars> --out cohort.json

uv run --frozen python -m research.ranking_e2e.runner \
  --cohort cohort.json --bars-root <raw 1min root> \
  --protocol-doc <ranking doc> --out <session dir>
```

`--protocol-doc` points at the checkout that carries the frozen K3
section (commit `ba5116d`); omit it to verify the checked-out doc.
`--no-verify-protocol` exists only for synthetic tests and stamps the
report `SYNTHETIC_NOT_VERIFIED`.

## 2026-11-09 development table

Cohort: 4,647 candidates, 159 truth (bar-close onset), 249 controls,
205 never-crossed controls, 0 excluded. One session, SIP raw 1-minute
bars 04:00-11:35 ET. Full-generation ranking leaves 111 rankable at
onset and 48 with no rank.

| Arm | Recall @30 | Recall @100 | Rankable at onset | Other |
|---|---|---|---|---|
| K2 | 3/159 (1.89%) | 10/159 (6.29%) | 111 | 13 first entered top-100 at/before onset; 18 late; p50 lead -300 s; p90 14,580 s; false 0 |
| Mean baseline | 4/159 (2.52%) | 10/159 (6.29%) | 111 | 13 first entered at/before onset; 18 late; false 0 |
| Gap, fixed 04:00-04:05 | 29/159 detected (18.24%) | - | - | p50 -8,280 s; p90 -60 s; false 55/249 = 0.0291; never-crossed 45/205 = 0.0290; windows 60/120/300 = 13/14/14 |
| Keep-alive | 3/4 persisted (75%) | - | - | 3 unconditional members at onset; qualified fresh only, quota capped |
| Page CUSUM | NOT_RUN | - | - | five adapter rows UNAVAILABLE; river defaults refused |
| OFI / catalyst | NOT_IN_FROZEN_PROTOCOL | - | - | no thresholds in the frozen section |

Onset strata: PRE 04:00-04:30 14, PRE rest 24, RTH 09:30-10:00 87,
RTH rest 34. The earlier minute-active replay's 8/159 and 12/159 were
flattered by ranking only rows printed in the generation minute; the
full K2 section 5 universe gives 3/159 and 10/159. The figures are
descriptive, one session, with no interval, significance or after-cost
claim (K3.7).

## Review fixes

- **P0-1 no fallback prior close**: `build_cohort` keeps a missing
  official close as null, records `missing_official_prior_close`, counts
  the exclusion, and never derives a reference. Witness:
  `test_build_cohort_from_metrics_and_daily_closes`.
- **P0-2 full K2 section 5 generations**: every generation ranks all
  computable `state.latest` rows, not the minute-active subset. Witness:
  `test_full_generation_ranks_carried_rows`.
- **P1 gap anchor**: one session-scoped 04:00-04:05 arm, first open only;
  trigger mode `NOT_RUN`. Witness:
  `test_gap_arm_uses_only_the_fixed_opening_window`.
- **P1 keep-alive**: current entry qualification, quota cap and 20:00
  reset. Witness:
  `test_keep_alive_requires_current_qualification_and_quota`.
- **P1 metric set**: signed latency in seconds, late vs censored, windows,
  per-name flags, baseline-available and universe counts, paired K2
  contrasts. Witness: `test_signed_latency_late_flag_and_windows`.
- **P1 PIT labels**: labels are required and travel verbatim; the W1 K2
  run stays `NOT_RUN`. Witness: `test_cohort_requires_pit_labels`.
- **P1 CLI verification**: verification is the default; the override is
  explicit and labels a synthetic run. Witness:
  `test_runner_cli_verifies_by_default`.
- **P1 N1 -> B leg**: `entry_protection.status = UNKNOWN` because PR-3's
  harness (#83) is not on gate; no parallel harness was built.
- **TrialLog custodian ruling**: `ledger.detection_row` and `append`
  refuse every detection-only row; the runner builds no row. Witness:
  `test_ledger_refuses_every_detection_only_row`.
- **P2/P3**: signed lead, percentiles in seconds, no fabricated
  prior-close anchor, no cross-segment merge of first-entry times, no
  internal `sharadar-42` path in the cohort docstring, and a
  `params_hash`-bearing registry receipt.

All eight witnesses fail at `5a2167c` and pass at the fix head.

## Seal and ledger

`session.json` carries the eight seal items. At this session:
`session_list`, `cohort_controls`, `market_data`, `baseline` and
`implementation` are AVAILABLE; `registry` is PARTIAL (the 12 operational
rows are reviewed, but the entry/trading ages are UNAVAILABLE);
`triallog` is NOT_RUN pending the custodian ruling; `other_family_review`
is ABSENT. The trial state is therefore NOT_RUN and no row is appended.
`ledger.detection_row` and `ledger.append` raise `LedgerRefused` for
detection-only content; there is no side ledger.

## Fidelity

- Bar-close replay, not trade ticks: `trades_accel` is a bar-count proxy
  and the bar's `n` field is not a trade stream. This is the U10
  sensitivity, not K3's trade-tape primary; `primary_estimand` is
  `NOT_RUN`.
- Freshness ages are not applied to a historical replay.
- RTH ends at 11:35 ET because that is the fetched data end, not the
  16:00 close.
- No PIT membership is available, so the W1 1,436-session cohort and its
  K2 run stay NOT_RUN; the 2026-11-09 e2e cohort is the only intraday
  cohort with bars and controls today.

## Tests

`tests/proofs/test_ranking_e2e.py` has 19 tests covering protocol hashes
and the K3 presence gate, cohort labels/validation/hashing, mean/median
curves, interpolation, the fixed gap window, the CUSUM recurrence,
qualified keep-alive membership, percentiles, signed latency/windows,
the full-generation witness, the CLI verification default, no
detection-only ledger row, the missing-close witness and a synthetic
end-to-end run. Run `pytest tests/proofs/test_ranking_e2e.py -q` under
the local memory scope.
