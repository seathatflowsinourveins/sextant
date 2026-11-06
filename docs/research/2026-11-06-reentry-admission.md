# Re-entry admission in replay: partial row 9

Issue #74, focus step **5: re-enter or rotate**. This carries the admission and
proposal slice of ADR-0006 against explicit ranking, custody, entry and sizing
seams. It is **not a complete R1–R6 strategy port**. Every decision has zero order
authority; held rotation remains a non-executable proposal until a later flat
receipt. No account, key, broker client, market stream or live path is involved.

## Pin audit and minimal carry

The upstreams were read from shallow clones at these exact commits, not their
moving branch tips. Dates below describe this audit, 2026-11-06.

| Source | Carried role / limitation |
|---|---|
| northstar-lanes@00203275944a22655b3e14b221cfde9a265d549a `src/northstar_lanes/contracts.py` | Narrow native-ID/Decimal records: RankingView, FlatReceipt, FastSellFacts, entry intent and CampaignState. Original campaign identity and remaining ceilings cannot renew; count cannot reset. |
| Same pin, `parameters.py`, `classification.py`, `classified_flow.py` | Inspected, not transplanted: their flow/classifier code does not implement reclaim, whipsaw lifecycle or component confidence. No Lee–Ready coverage acceptance follows. |
| Same pin, `docs/adr/0007-reentry-and-rotation.md`, carried as ADR-0006 | R1–R6 constraints and explicit supersession of legacy paper caps. No new detector or numeric starting value is introduced. |
| northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa `strategies/exit_manager/reentry.py:FocusReentry.prepare`, `signals.py:retry_allowed` | Cooldown/qualification/refusal order, reservation before publishing a draft, original budget ceilings. The old RTH restriction, original-catalyst retry window and paper one-retry cap are superseded and not copied. |
| Same pin, `rotation_wiring.py:RotationPlanner.after_exit`, `portfolio/rotation.py:rotation_target` | Same-symbol precedence, best unheld rank, pair-specific strict cost-aware lift and proposals with `executable=False`. ADR-0006's R4 equation includes its margin; entry's score-ratio seam supplies the weakest holding instead of legacy worst-rank selection. |
| Same pin, `custodian.py`, `config.py`, `execution/pacer.py` | Inspected for ownership and protection-first boundary. Not a custody/pacer port: this code consumes a positive receipt plus complete expected lineage, and constructs no order. |
| Same pin, `strategies/premarket_gap/entry_sizing.py:size_entry` | Missing scored confidence refuses before sizing; multiplier is floor + (1−floor)×confidence. The actual FixedRiskSizer/order lifecycle stays in row 6. |
| NautilusTrader v2.0.0rc7 `55c0e82053142bce3a5cba4de4221d3929c2d3bc` | Native IDs, Quantity, BacktestEngine and Strategy quote events; same API shape as the landed exit engine. No adapter or service is instantiated. |

The proposed `src/northstar_lanes/setups.py` and `reentry.py` are absent at the
lanes pin, as ADR-0006 records. Searches of both pinned `src/` trees found no
implementation for `reclaim_hold_s`, `whipsaw_stopouts_max` or
`reentry_min_confidence`; confidence sizing exists, component scoring does not.
The trading re-entry file is a legacy FocusGate bridge, not the proposed pure
R1–R6 module. This gap must not be hidden by renamed legacy code or fixture flags.

## Boundary behavior proved here

- A receipt must identify the sold instrument and have exact broker net zero;
  its terminal IDs must cover the explicitly supplied expected entry, every
  protection and replacement. Unknown receipt/lineage, future receipt or a
  contradictory held sold symbol yields Wait. This is consumer validation,
  not proof that a production custodian assembled complete lineage.
- Cooldown starts at receipt `ts`, never sell `ts`. The witness refuses one
  nanosecond before and admits at/after `flat.ts + cooldown_seconds × 1e9`.
- A missing, stale, future, invalid or changed ranking generation yields Wait.
  Qualification and sizing bind to the same generation. A fresh quote cannot
  supply ranking or setup authority.
- Same-symbol qualified RECLAIM/BREAKOUT has priority inside the retry band;
  otherwise choose the best unheld independently qualified name in the rotation
  band. A different-symbol FIRST_LEG may be unscored, with confidence and
  multiplier left null. Missing same-symbol confidence refuses before sizing.
- Explicit first-print, unknown/extended breakout, negative catalyst and
  unsupported setup labels refuse. A whipsaw count supplied by custody requires
  capped reclaim; this layer neither calculates nor resets that count.
- Held rotation needs the caller's weakest holding/score and a generation-bound
  selected-pair lift. Equality with `2 × c_RT / price + margin_bps / 10000`
  refuses, as does None. Flat-slot rotation needs no lift. A held proposal cannot
  invoke the sizer or create a second entry before flatness.
- Paper proposal counts are recorded without a count/P&L cap. One receipt is
  reserved before sizing so repeated quotes or ranking generations cannot emit
  duplicate proposals. This fence and the journal are in memory; they are not
  durable restart ownership or the canonical TrialLog. Live and IBKR paper
  admission remain OFF. Campaign records prevent original/remaining budget
  renewal, but no promoted live policy is activated or certified.

The entry seam is a trusted **qualified-intent boundary**, not a new detector.
No production provider is installed by this row. Fixture providers demonstrate
admission mechanics; they do not certify the provider's detection/scoring,
custody, live tape, account state or sizing authority. The gate requires the
provider's held-retest confirmation for reclaim; it does not reconstruct that
retest from ticks or turn a quote into a setup.

## Unavailable and NOT_RUN

| Requirement | State / next evidence |
|---|---|
| R3 touch-since-sell, freshness, trade count/span, cap, same-episode held higher-low retest | UNAVAILABLE provider; integrate row 6's shared definitions and segment reset after its source/authority is accepted. Continuation-without-touch and retest/cap historical witnesses are NOT_RUN here. |
| R3a stop-out count lifecycle and reset on armed exit/session boundary | UNAVAILABLE provider; custody/entry must supply the sourced lifecycle. The consumer's post-threshold refusal is tested, the reset itself is NOT_RUN. |
| Confidence component clipping, catalyst receipt/date/live-window and rank/flow/flush normalization | UNAVAILABLE scorer; no invented denominators or default confidence. Only a supplied scored intent and the pinned sizing multiplier are consumed. |
| R3b OVERSELL detector and classifier coverage | UNAVAILABLE; no executable OVERSELL path, even if a fixture names that setup. Classifier admission and flush-low sizing remain unverified. |
| Actual RankingView, positive broker flat lineage, shared entry/sizer and protection-first dispatch | Fixture seams only; rows 5/6/8 integrate these. No row's implementation is duplicated or cherry-picked from an unmerged PR. |
| Live nonrenewing retry cap, approved stage and durable reservation/restart enforcement | OFF / UNAVAILABLE runtime; record monotonicity is not promoted live acceptance. |
| Re-entry versus no-re-entry versus hold-flat, 1× and stressed cost | **NOT_RUN**, waiting for #72's canonical TrialLog. No parallel ledger, return series, arm comparison or merit result was created. |

The 15-minute pause, daily post-loss retry cap, tilt-check, purgedcv and exitkit
retain the source's candidate/watch/reject dispositions. None becomes a gate.

## Verification and limits

`timeout 90 uv run --frozen pytest tests/proofs/test_reentry.py` runs pure
admission and native event-clock witnesses. The native witness reuses the
pinned TestInstrumentProvider AUD/USD fixture solely to drive three quote
events around the cooldown boundary, with risk bypass **False**, an explicit
synthetic zero-fee model and **zero orders**. It is not an equity execution,
economic or classifier-coverage witness, and reports no P&L.

All production values in `lanes/sim/reentry-parameters.json` are null and
UNCALIBRATED. The explicit test values remain FIXTURE_ONLY; no start is inferred
from either fixtures or legacy defaults. Each decision carries its parameter
hash. The measured Python carry is recorded in the PR; ~700 lines is a planning
estimate, not a reservation or acceptance of a full upstream tree.

Lesson for the lead's handbook writer: contract presence is not detector or
broker-flat implementation. The missing pure files, legacy paper caps and
clock-only fixture evidence must remain distinct. Reservation must precede
publishing a draft, and a new rank generation cannot renew the same flat receipt.
