# Ranking early-entry e2e harness (research only)

This package runs the frozen K3 development table on one session. It is
the Part 1 harness: it measures the K2 ranking state, the mean-baseline
variant, the keep-alive arm and the premarket gap sub-arm on the same sealed
cohort. Detection-only results stay in the hashed report; they never
become TrialLog rows (custodian ruling, ADR-0019:26). There is no entry,
sizing, fill or return claim. Evaluation code stays here, never in `src/`.

Protocol authority: `docs/research/2026-11-06-ranking.md`, K3 section
SHA-256 `fecd378a5b40fc2d6d2e03b16dda605c9f82102dad8e95735ffef24a459aca0b`
(frozen at base `cb9a290`, on gate since #118) and K2 section
`fc019b18602429f0f641588eed45467ca555f4bbc568284327f1a346dd33426f`.
The harness verifies both digests in the checked-out doc by default and
refuses to run if either moves.

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
- Replay: one synthetic tick per non-zero-volume minute at bar close, one
  generation per minute. No print is fabricated: there is no anchor or
  segment-start tick. A segment's dollar-volume prefix is covered only by
  an explicit prefix receipt (the recording's request window and the
  recorded day's hash, checked against the bar files), which covers every
  recorded symbol from each segment start alike. Without it every name is
  `segment_prefix_unknown` and the ranking arms are `NOT_ESTIMABLE`. The
  segment end is widened by one nanosecond so the 09:30 and 11:35 bar
  closes are inside the engine's half-open `[start, end)`.
- Every generation ranks the full K2 section 5 universe: all computable
  `state.latest` rows, not only the minute-active subset, and respects
  `publish_min_interval_s`. `universe` is recorded per generation.
- Labels read the replayed path only: onsets and never-crossed controls
  use bars from 04:00 that have closed by 11:35 (K3.4's window), so a bar
  closing after 11:35 neither sets an onset nor moves a control. An onset
  keeps its bar's segment: the 09:29 bar's 09:30 onset is judged by PRE's
  09:30 generation (K2 section 5), and the strata follow that segment.
- Arms: K2 (`move x dvol_ratio`); the mean baseline (one discrete change);
  keep-alive on K2 top-100 membership; the premarket gap rule; Page CUSUM.
  Arm (a), ADR-0024's gap rule exactly as recorded, is `NOT_RUN`: its
  recorded calibrations need ADV20 (the $5m candidate-ADV floor, the
  unknown-ADV exclusion and trigger mode's `max(50000, 0.001 x ADV20)`
  floor) and the prior session's post-market turnover (the $1m prior-post
  filter), and the harness takes no receipt for either; trigger mode's
  below-5% gap is an UNCALIBRATED grid. What runs is the fixed-mode
  gap-only sub-arm, `gap_fixed_open_sub_arm` (first open in 04:00-04:05 at
  least 1% over the prior close), a different arm under K3.8. Keep-alive
  retains a member whose row is not computable while its last computable
  row qualified; fresh admits fill first and the retained take free slots
  in K2's own order; `reset` is 20:00. Page CUSUM is `NOT_RUN` (its five
  adapter rows are UNAVAILABLE). OFI and catalyst arms are
  `NOT_IN_FROZEN_PROTOCOL`.
- Metrics: detected, late and censored; recall at onset (a first flag at
  or before `tau`) beside the ever-detected share; signed p50/p90 latency
  in seconds (`flag - onset`; Hyndman-Fan type 7); first entry at or
  before onset; the +/-60/120/300 s windows; per-name flags; paired K2
  contrasts; baseline availability per arm, read from each name's latest
  row at onset (a zero normal is unavailable), with per-mover unknown
  reasons; keep-alive persistence among names first admitted strictly
  before onset. False flags count every control that enters the top 100
  (K2, mean), becomes a member (keep-alive) or gap-flags (sub-arm), over
  two denominators, every control charged the window and each control's
  own row hours, all-control and never-crossed apart, labelled
  `DEVELOPMENT_CHOICE_PENDING_U4_SEAL`. Empty denominators are undefined,
  never zero. Date is the block; one session is a development table, not
  a trial.

## Use

```
uv run --frozen python -m research.ranking_e2e.build_cohort \
  --metrics <metrics.json> --daily-dir <prior daily bars> --out cohort.json

uv run --frozen python -m research.ranking_e2e.runner \
  --cohort cohort.json --bars-root <raw 1min root> \
  --prefix-receipt <prefix-receipt.json> --out <session dir>
```

The prefix receipt is JSON with `schema` `ranking-e2e.prefix-receipt/1`,
`session`, `feed: sip`, `timeframe: 1Min`, `window_et` `{start, end}`, the
recorded day's `data_sha256` (the runner's per-day receipt) and `source`.
`--protocol-doc` overrides the checkout's ranking doc. A verified run
refuses a dirty tree, so the report binds the committed head it ran.
`--no-verify-protocol` exists only for synthetic tests and stamps the
report `SYNTHETIC_NOT_VERIFIED`.

## The development table and its history

No table is kept in this file. The current table is the clean-tree rerun
at the landing head; its report and generations files are hashed, and the
PR body cites those digests with the head, the harness hash, the data
hashes and the `params_hash`. Writing numbers here after the run would
move the head the receipts bind. The table is descriptive, one session,
bar-close U10 sensitivity, with no interval, significance or after-cost
claim (K3.7).

Earlier runs stay on the record as superseded, identified by their own
implementation receipts; none of their numbers is quoted anywhere:

- Run 1, receipt `git_head` `cb9a290` before the harness was committed
  (harness tree `61d54fc4...`): void under round 1's P0 fallback prior
  close and P0 minute-active subset ranking, and every round-2 P1 below.
- Run 2, `git_head` `5a2167c` from a dirty tree (harness tree
  `ff481c58...`): void under round-2 P1s 1-5 and the provenance P1.
- Run 3, `git_head` `5a2167c` from a dirty tree (harness tree
  `5dcefe85...`; the committed `53b9e8a` tree hashes `cf163da7...`), the
  table the round-2 head quoted: void under round-2 P1s 1-5 and the
  provenance P1.

## Review fixes

Round 1 (witnesses fail at `5a2167c`): no fallback prior close
(`test_build_cohort_from_metrics_and_daily_closes`); full K2 section 5
generations (`test_full_generation_ranks_carried_rows`); one
session-scoped 04:00-04:05 gap window
(`test_gap_arm_uses_only_the_fixed_opening_window`); PIT labels required
(`test_cohort_requires_pit_labels`); verification by default
(`test_runner_cli_verifies_by_default`); no detection-only TrialLog row
(`test_ledger_refuses_every_detection_only_row`).

Round 2, the six P1s by their Fix lines (witnesses fail at `53b9e8a`,
rebased as `e80f6ee`):

1. **Keep-alive never retained**: it carries each name's last computable
   qualification and K2 order key itself, retains an uncomputable member
   that last qualified, orders retained names by K2's own key, and counts
   persistence only for first entry strictly before `tau`. Witnesses:
   `test_keep_alive_retains_a_member_whose_row_turns_uncomputable`,
   `test_keep_alive_persistence_needs_first_entry_strictly_before_onset`,
   `test_keep_alive_quota_fills_fresh_first_then_k2_order`.
2. **Structural-zero ranking false flags**: flags are read from the
   per-segment first-entry maps with controls included, beside coverage
   hours per control. Witness:
   `test_ranking_false_flags_count_controls_that_enter_the_top_100`.
3. **Baseline availability and recall**: availability comes from each
   name's latest row at onset per arm; recall at onset excludes late
   flags. Witnesses:
   `test_baseline_availability_reads_the_latest_state_per_arm`,
   `test_signed_latency_late_flag_and_windows`.
4. **Synthetic coverage tick**: the anchor is gone; coverage comes from
   the prefix receipt for every recorded symbol, or ranking is
   `NOT_ESTIMABLE`. Witnesses:
   `test_prefix_receipt_covers_every_recorded_symbol_without_a_synthetic_print`,
   `test_no_prefix_receipt_leaves_ranking_not_estimable_with_reasons`,
   `test_prefix_receipt_for_other_bytes_is_refused`.
5. **Arm (a)'s name**: arm (a) is `NOT_RUN` with its missing quantities;
   the run is `gap_fixed_open_sub_arm`. Witness:
   `test_arm_a_stays_not_run_and_the_gap_sub_arm_carries_its_own_name`.
6. **Provenance**: a verified run refuses a dirty tree and records
   `tree_clean`; the table is the clean rerun at the landing head. Witness:
   `test_verified_run_refuses_a_dirty_tree_and_binds_a_clean_one`.

Hosted review of `1e95678`, two P1s (witnesses fail there): an onset from
the 09:29 PRE bar was judged in RTH, which has no generation before 09:31
(`test_a_boundary_bar_onset_keeps_its_pre_segment`); onsets and
never-crossed controls read bars past 11:35
(`test_price_path_labels_stay_inside_the_replay_window`). With strata
following the onset's segment, an 11:35 onset now lands in the last
stratum too.

The round-2 P2 and P3 findings not subsumed here, and the hosted review's
P2s, are in the follow-up issue #199, including the seal items'
derivation and the arm tier labels.

## Seal and ledger

`session.json` carries the eight seal items and the implementation
receipt (`git_head`, `tree_clean`, harness and ranking-code SHAs). The
custodian ruled that detection-only rows are refused and only trading
arms through N1 then B's protection write MODELED rows, so the trial
state is `NOT_RUN` and no row is appended; the `triallog` seal item's
reason text still predates that ruling (follow-up issue).
`ledger.detection_row` and `ledger.append` raise `LedgerRefused` for
detection-only content; there is no side ledger. The N1 -> B leg is
`NOT_RUN` here: #83 on gate carries the first-leg picks and B's
protection replay, and wiring these arms into it is a separate successor
task under its own frozen, costed protocol (K3.7).

## Fidelity

- Bar-close replay, not trade ticks: `trades_accel` is a bar-count proxy
  and the bar's `n` field is not a trade stream. This is the U10
  sensitivity, not K3's trade-tape primary; `primary_estimand` is
  `NOT_RUN`.
- Freshness ages are not applied to a historical replay.
- RTH ends at 11:35 ET, the cohort's evaluation window (K3.4), not the
  16:00 close; the recording runs to 11:40, and bars closing after 11:35
  are not replayed.
- No PIT membership is available, so the W1 1,436-session cohort and its
  K2 run stay NOT_RUN; the 2026-11-09 e2e cohort is the only intraday
  cohort with bars and controls today.

## Tests

`tests/proofs/test_ranking_e2e.py` has 31 tests: protocol hashes and the
K3 presence gate, cohort labels/validation/hashing, mean/median curves,
the fixed gap window, the CUSUM recurrence, keep-alive retention and
quota order, percentiles, signed latency and recall at onset, the false
flag table, the full-generation witness, the CLI verification default,
no detection-only ledger row, the missing-close witness, and a
three-prior-session run that witnesses each round-2 P1, and a
window-edge run for the onset segment and the replayed path. Run
`pytest tests/proofs/test_ranking_e2e.py -q` under the local memory scope.
