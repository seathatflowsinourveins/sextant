# B owner-entry manager: custody intents and native sim witnesses (#49)

B now has a sim-only manager over #45's X2–X5 engine. This is a mechanism witness,
not an installed paper writer, an external-fill claim or evidence of profitable exits.
The [receipt](2026-11-06-owner-b-manager/receipt.json) holds the export reproduction,
compact native event/order receipts and the measured intervals; every one of the 32
arm-runs remains in the [append-only trial ledger](2026-11-06-owner-b-manager/trials.jsonl).

## Sources and scope

- Policy: ADR-0005 X2, ADR-0007, ADR-0008 B4 and ADR-0025; option B and its two kill points
  are `northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:docs/adr/0015-owner-entry-paper-exit-manager.md:94–124`.
  This is its owner-approved `none exists:` mechanism: Alpaca has no reduce-only exit
  and cannot pair a trailing stop in OCO. No new house policy is introduced here.
- Engine: NautilusTrader rc7, code commit `55c0e82053142bce3a5cba4de4221d3929c2d3bc`.
  Annotated tag object `27b7c99f4ae0100325dfe3830b793055e38a014f` resolves to that commit.
  Native cache, order factories, cancellation, amendment, BID_ASK emulator and
  `StaticLatencyModel` own the lifecycle. The fixture disables reduce-only support.
- The stopped-component witness uses **Strategy.stop / Strategy.resume** in one engine
  and cache (`crates/common/src/component.rs:164–189,403–404`), with cache access on the
  next normal event. It is labelled **engine stop and start in sim; not a process death
  and not broker reconciliation**, as accepted on #49.
- All parameter values are mandatory UNCALIBRATED inputs. Fixture values supply no authority. If either X5 chase row is unavailable, the B manager refuses configuration before adoption; no cap or cadence is inferred from the core engine's unavailable starts.
  `native_trail_fraction > 0.025` is refused. The cost allowance is a fixture, not measured TCA.

## What ran

The synthetic equity fixture buys ten shares through a separate owner strategy's plain
DAY LIMIT and reserves two with an owner LIMIT. The manager never targets either order.
It protects only the unreserved residual; an add pauses and pages. A fully reserved
holding alerts without blocking later protection when the owner frees the quantity.
Adoption keeps the fill as entry basis and starts H at the adoption mark; an adoption
below entry minus buffer sells only on the first persisted breach, labelled accordingly.

Native option B cancels its trail, waits terminal, then submits one collared LIMIT.
A chase ending unfilled cancels that LIMIT, rereads the residual, then re-arms one trail.
The outside-RTH witness emulates one BID_ASK trailing stop-limit and chases its single
released LIMIT. Pending submissions, cancels and partial fills retain their reservations.
Both stop/resume cases ended with one trail: eight shares after cancel ACK, five after
an accepted LIMIT filled three shares while the manager was stopped. No second sell
or reservation excess was observed. Subscriber callback order is not assumed.

At configured base latencies **100 ms / 200 ms / 1.2 s**, the one-second quote grid
measured cancel-ACK → LIMIT-acceptance intervals **1 s / 1 s / 2 s**. Acceptance → first
fill was **1 s / 1 s / censored**; the last arm did not fill and re-armed its trail.
These three deterministic observations are a discrete mechanism distribution, not a
live latency estimate or bound. A partial first fill is not full liquidation.

The 162-order frozen B export reproduces 31 symbols, owner/node/coordinator labels
118/35/9, 97 matched FIFO lots, gross **−$15,372.014069821952** and the LIFO cross-check
**−$14,810.944196821952**. It retains unmatched sells and open inventory. These are
cumulative order-average summaries, descriptive and unpaired, not individual executions.

The second 16-run batch reflects final review; the earlier batch remains bound to its own
code hash. Earlier custody-drill P&L is superseded development output, never economic
evidence; the final code emits null for these unpaired drills. Normal comparison arms
retain synthetic marked P&L with zero fees, which cannot establish merit.

## Not verified

Real external owner-fill claiming and claim latency remain owed to Sandbox on a live
feed; no mock reconciliation substitute was built. Process death, durable lineage,
broker reconciliation, custody/pacer/halt and paper installation remain #51/#78 work.
The in-hours native trail now triggers on LAST_PRICE, because Alpaca elects stops on the consolidated print (docs read 2026-11-06). rc8 accepts that trail only once a trade is cached, so B waits for the first print and never pauses, and B's node must cache SIP trades (#139). The simulator still elects on any print, with no NBBO or session filter, so it is not proof of Alpaca's stop-election basis.
Outside RTH protection, chase and recovery remain dependent on node/feed availability.
The canonical TrialLog writer is still row 10; these arm rows are retained for it and
are never pooled with MODELED research or BROKER-PAPER outcomes.

The [#41 rerun](2026-11-06-exit-study-41.md) has landed and the inherited full-suite test
reruns its hash-checked minute inputs here: hold-to-15:55 still beats all 96 variants.
That tape provides no NBBO or option-B execution latency. The full 371-row PARA minute
snapshot remains unavailable; the seven-row onset excerpt cannot replace it. Qualified
cost-calibrated tick opportunities remain zero in the harvested gain-protection study.
No comparative execution edge, expected-fill loss bound or current account coverage is claimed.

---

### PR-3 e2e replay: the owner's fill, the catalyst and the first leg, then B's protection

PR-3 of the clean-B plan. A historical end-to-end replay on the recorded tape: enter at
the owner's fill (or a labelled stand-in), then run B's broker-held protection. The
template is NautilusTrader's official trailing-stop example strategy, with entry changed
to "the owner's fill at time T". The protection is the same 2.5% `trailing_stop_market`
the live owner-B protector submitted for the owner's PARA fill.

The replay is research code (`src/sextant/backtest/b_e2e.py`); the minimal proof fixture
is `tests/fixtures/b-e2e-owner-fill.json` with `tests/proofs/test_b_e2e.py`. Every run
writes MODELED rows to the one TrialLog, rejected arms included.

### Inputs

| Case | Session | Tape | Source |
|---|---|---|---|
| PARA | 2026-11-03 | SIP 1-minute bars and the trade tape 13:45–15:00Z, plus the pre-market/RTH closes | C1 `ParquetDataCatalog`, `source=alpaca_sip`, `feed=sip`, `adjustment=raw` |
| SPCX | 2026-10-21 | SIP 1-minute bars and the trade tape 08:00–14:14:10Z | the same catalog |
| OMH | 2026-11-09 | 1-minute SIP bars 04:00–11:35 ET, the first 200 prints, and the recorded K2 generations | the e2e-omh replay's arrays and generations (handoff data, not committed) |

Every input file's SHA-256 is written into the case report and into each arm's
`config.sandbox_config.data` in the TrialLog. The proof fixture's tape is pinned at
`87fc4a24a654f26466a07058bbf3d63c2e61254274e05677768997463f26636a`.

### Method

1. **Entry arms.** `reference` buys the owner's fill (PARA: 50 @ 7.63 at
   2026-11-03T14:50:46.382818Z; SPCX and OMH have no owner entry, so their labelled stand-in
   is the first observable print). `catalyst` buys the first print at or after the EDGAR
   `knowable_at` (SPCX's 8-K accepted 2026-10-20T20:00:51Z). `first_leg` arms on the recorded
   K2 rows and buys the first non-decreasing run of the four REVIEWED rows in
   `lanes/sim/entry-parameters.json`: 5 prints inside 120 s, spanning at least 2 s, at most
   3% above the quiet price, with a lower print restarting the run.
2. **B's protection.** On the position-opened event the strategy submits one reduce-only
   `trailing_stop_market` SELL at `trailing_offset=2.5%` of price, `TrailingOffsetType.BASIS_POINTS`,
   `TriggerType.LAST_PRICE`, `TimeInForce.DAY` — the official example's shape and the live
   owner-B submission. H is the high of eligible prints; the trail level is H − 2.5%.
3. **Ledger.** `TrialLog` through `src/sextant/validation/trials.py`, tier MODELED,
   `block_set_id` the session, one row per arm plus the hold-flat control. The ledger is
   cumulative and never reset; this run appends 12 rows to `reports/research/trials.parquet`.

### Results

| Case | Arm | Entry | H | Trail | Exit | Protected | Hold-flat |
|---|---|---|---|---|---|---|---|
| PARA | reference | 7.63 at 14:50:46Z | 7.87 | 7.67325 | 7.67 at 14:52:56Z | **+0.52%** | −64.48% |
| PARA | catalyst | rejected: no scheduled catalyst is recorded for this case | | | | | |
| PARA | first_leg | rejected: no recorded K2 rank path for this case | | | | | |
| SPCX | reference | 161.21 at 08:00:00Z | 163.97 | 159.87075 | 159.87 at 10:13:18Z | **−0.83%** | −1.20% |
| SPCX | catalyst | 161.21 at 08:00:00Z (first observable print) | 163.97 | 159.87075 | 159.87 at 10:13:18Z | **−0.83%** | −1.20% |
| SPCX | first_leg | rejected: no recorded K2 rank path for this case | | | | | |
| OMH | reference | 14.89 at 04:00:00 ET | 14.9208 | 14.54778 | 14.30 | **−3.96%** | +169.71% |
| OMH | catalyst | rejected: no scheduled catalyst is recorded for this case | | | | | |
| OMH | first_leg | rejected: first print 15.56 is +111.4% above the 7.36 quiet price, beyond the 3.0% cap | | | | | |

The hold-flat controls: PARA −64.48%, SPCX −1.20%, OMH +169.71%.

### Findings

- **PARA's trail protects the downside.** The replay arms the trail at T and exits at 7.67,
  **+0.52%**, against the close's −64.48%. The owner's live trail was submitted at
  14:52:56.460531Z, after the 7.85–7.87 prints, and filled at 7.12 (the gap-through); the
  replay's earlier arming is the difference, and both records are in the report.
- **A 2.5% trail cannot hold a parabolic move.** OMH's reference exits at 14.30 for **−3.96%**
  while holding to the last recorded bar returned +169.71%. The trail is a floor, not a
  participation rule; PR-4's calibration starts from this.
- **The first-leg rule cannot enter after the gap.** OMH's first K2 row arrives at 04:40 with
  the price already +111.4% above the 7.36 quiet price, so the 3% cap rejects it. On this
  1-minute tape a 120-second window also holds only two prints, so the five-print run cannot
  form; the rule needs the trade tape.
- **SPCX's catalyst entry is not measurable locally.** The 8-K was accepted at 20:00:51Z, but
  the 20:00Z tape is not in the catalog; the first observable SIP print is the next morning at
  161.21, already +8.96% on the 147.95 close. The trail exits at 159.87 (−0.83%) before the
  later 168.50 high, because the first 2.5% pullback ends the position. The catalyst arm and
  the reference arm are identical for that reason.

### Limitations

- No universe K2 snapshot exists for PARA or SPCX in the local data, so their ranking arm is
  a rejected row, not a measurement. Only OMH's recorded K2 path can run that arm.
- OMH's tape is 1-minute bars, not prints; its first-leg arm cannot form a five-print run.
- The outside-RTH emulated BID_ASK trail needs `chase_cap_fraction`, which is UNAVAILABLE;
  the replay records the in-hours LAST_PRICE trail as a MODELED substitution.
- No broker, paper or live execution; no order left outside the engine. Nothing is selected:
  all rows are MODELED, and PR-4's calibration is the next step.

### Addendum: the six-mover cohort

The owner's 2026-11-09 cross-section (sextant-next #4, comment 6746927782) adds today's six
movers: ONDS, NWGL, TTD, MF, OMH and CKX. `src/sextant/backtest/b_e2e_cohort.py` replays the
same first-leg policy on the SIP tapes and the e2e-omh K2 generations, then runs B's 2.5%
trail and ADR-0024's slots.

### Inputs

- The six SIP tapes (`/tmp/multi-<SYM>.json`, OMH's day tape and its run quote slice), the
  e2e-omh `ranks.npz`, `cohort.json` and `multi-plan.json`, and each file's SHA-256 in the
  run's `report.json` and `summary.md`. The six flags, quiet prices, last prints and marks
  come from the cross-section's `multi_scan.py`, whose flag is the run's first print; the
  entry moment, the run's completion and the 15:28 ET marks are distinct clocks.
- The four REVIEWED rows in `lanes/sim/entry-parameters.json`: 120 s window, 5 prints, 2 s
  span, 3% cap; `max_data_age_s=5` is the REVIEWED quote-freshness row.

### Method

1. Find each symbol's first run with the cross-section's scan: the quiet price is the print
   before the outer print; the run grows while prints stay above quiet and non-decreasing;
   a lower print restarts it; the first five-print, two-second, inside-3%-cap run wins. Its
   first print is the flag and its last is the confirmation.
2. K2 rank = the last computable generation at or before the flag (the e2e replay's rank 0
   means unranked). The 14:31–14:36Z generations are not computable, so every flag in that
   gap uses the 14:29 generation; this is recorded, not hidden.
3. Enter at the run's completion with the then-current two-sided ask; an ask older than 5 s at
   completion is the thin-quote refusal class. The entry is refused when `max(last, ask)` is
   beyond quiet × 1.03. The flag stays the onset timestamp, never the fill time.
4. B's protection is the same 2.5% reduce-only `trailing_stop_market`, modeled at the
   triggering print. A position the tape never stops is HELD: its exit is unset, its last
   print is reported as an unrealized mark, and the ledger scores it `HELD/NOT_EXITED` rather
   than a protected return. The each-case hold-flat control uses the entry price, or the
   run-last price when the entry was refused.
5. Arms: (a) ADR-0024's 2/5 slots in time order, never freed; (b) 8/20; (c) 2/5 plus ADR-0006's
   flat-slot rotation after a fast sell to the best-ranked pending name, with no lift and no
   held rotation (no expected-lift estimate exists). Every case and arm is a MODELED row,
   refusals included.

### Results

| Arm | Case | State | K2 rank | Slot | Entry | H | Exit | Protected | Hold-flat |
|---|---|---|---|---|---|---|---|---|---|
| 2/5 | ONDS | COMPLETE | 147 | 1 | 5.43 | 5.56 | 5.42 | −0.18% | +8.98% |
| 2/5 | NWGL | COMPLETE | 8 | 2 | 3.36 | 3.3999 | 3.31 | −1.49% | +8.04% |
| 2/5 | TTD | FAIL | 37 | — | — | — | — | — | +7.70% (no slot) |
| 2/5 | MF | FAIL | 0 | — | — | — | — | — | +25.74% (3% cap) |
| 2/5 | OMH | FAIL | 2 | — | — | — | — | — | +215.40% (no slot) |
| 2/5 | CKX | FAIL | 0 | — | — | — | — | — | +11.04% (thin quote) |
| 8/20 | ONDS | COMPLETE | 147 | 1 | 5.43 | 5.56 | 5.42 | −0.18% | +8.98% |
| 8/20 | NWGL | COMPLETE | 8 | 2 | 3.36 | 3.3999 | 3.31 | −1.49% | +8.04% |
| 8/20 | TTD | HELD | 37 | 3 | 13.90 | 14.335 | held @ 14.2955 | not scored | +7.70% |
| 8/20 | MF | FAIL | 0 | — | — | — | — | — | +25.74% (3% cap) |
| 8/20 | OMH | COMPLETE | 2 | 4 | 23.44 | 24.67 | 24.01 | +2.43% | +215.40% |
| 8/20 | CKX | FAIL | 0 | — | — | — | — | — | +11.04% (thin quote) |
| 2/5-rotation | ONDS | COMPLETE | 147 | 1 | 5.43 | 5.56 | 5.42 | −0.18% | +8.98% |
| 2/5-rotation | NWGL | COMPLETE | 8 | 2 | 3.36 | 3.3999 | 3.31 | −1.49% | +8.04% |
| 2/5-rotation | TTD | HELD | 37 | 2 | 14.00 | 14.335 | held @ 14.2955 | not scored | +6.93% (rotated) |
| 2/5-rotation | MF | FAIL | 0 | — | — | — | — | — | +25.74% (3% cap) |
| 2/5-rotation | OMH | FAIL | 2 | — | — | — | — | — | +215.40% (no slot) |
| 2/5-rotation | CKX | FAIL | 0 | — | — | — | — | — | +11.04% (thin quote) |

### Findings

- **Four of six enter, as the cross-section recorded**: ONDS, NWGL, TTD and OMH. MF is refused
  by the binding 3% cap (last 15.27, ask 15.71, quiet 15.00, ceiling 15.45). CKX is refused by
  the thin quote at the run's completion: its last quote is 36.425Z and the completion is
  42.322Z, 5.9 s later, past the REVIEWED 5 s freshness row.
- **The 2/5 control takes ONDS and NWGL; OMH never gets a slot.** The 8/20 arm admits TTD and
  OMH. The rotation arm gives TTD the first freed slot at 14.00 (the ask at the freed moment)
  and still has no slot for OMH, because the two slots are held by ONDS/NWGL then ONDS/TTD.
- **Protection vs hold-flat**: the trail is a floor, not a participation rule. ONDS/NWGL exit
  −0.18%/−1.49% while holding to the 15:28 marks returns +8.98%/+8.04%; OMH protects +2.43%
  while holding returns +215.40%. TTD never trips its trail: entry 13.90, H 14.335, last print
  14.2955 is +2.85% unrealized but the row is HELD, not a protected exit.
- **The K2 rank is context, not the trigger.** ONDS ranks 147 and TTD 37 at their flags; OMH
  ranks 2 but the 2/5 control still has no slot; MF and CKX rank 0. The rank orders the
  rotation and reports the arm, while the first-leg scan is the causal entry rule.
- The 3% cap and the 5 s freshness are the two refusal classes here; PR-4's Optuna/CPCV gets
  `first_leg_max_move` and the freshness row as proposals, never selections.

### Limitations

- The cross-section's flags are an ex post scan over the day's tapes; the case set is the
  owner's cross-section. The flag is the onset, but the fill is at the run's confirmed ask,
  so the entry can be seconds after the flag. This is a research case study, not a live
  detector: the detectors remain unadmitted.
- The K2 ranks have no computable generation from 14:31 to 14:36Z, and MF/CKX rank 0 at their
  flags. The rank is recorded as context only.
- The marks are the cross-section's 15:28 ET prices; the trails are modeled at print prices,
  not broker fills. No paper or live execution, nothing selected, every row MODELED.
- The 2/5 slot order is the run-flag time order from the cross-section; the rotation's
  pending order is (rank, flag, case). A different tie-break would change which name rotates.

## PR-4: the tuning harness on these MODELED rows

`src/sextant/validation/tuning.py` and `src/sextant/research/b_tuning.py` search six reviewed rows
(the trail fraction up to ADR-0025's 2.5% cap; the first-leg window, count, span and max move; and
the quote-freshness window) with 100-300 Optuna multivariate TPE trials, scoring the lower
quartile of six CPCV folds. Every trial is one MODELED TrialLog row, refusals and prunes included.
The report holds proposals with `adoption: none`; a proposal needs an untouched 365-730 day
holdout, DSR > 0.95, PBO <= 0.05 and at least 30 training sessions.

The run on these rows is NOT_EVALUABLE by construction. The six-mover cohort is one session
(2026-11-09), and the three replay sessions (2026-10-21, 11-03, 11-09) cannot supply a 12-24 month
holdout or 30 sessions. No TrialLog file and no proposals were written, which is the honest
result; `test_b_tuning.py` proves the mechanism on a synthetic 60-session series instead.

Two boundaries are deliberate. K2's thresholds are not tuned: they can only enter as paired arms
against TV-REG's UNCALIBRATED rows, and the per-name features they gate are absent from these
rows. K3's premarket-gap arm waits until the K3 section of `2026-11-06-ranking.md` freezes.

The objective is the fold-level lower quartile, not upstream's path-level one: a trial is one
fixed parameter set, so recomposing a path's held-out blocks would return the same full-series
Sharpe for every path. The fold-level score keeps the combinatorial design and the coverage
assertion; the difference is recorded here rather than hidden.
