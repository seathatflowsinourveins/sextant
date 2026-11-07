# Detector components for #130

**Scope:** offline implementation support for ranking/onset research, not a study
runner, admitted market arm or first-second entry method. The hash-bound source
cards and `research/sources.yaml` remain unchanged. The coordinator on
`onset-detection` owns acquisition, the one catalog, dated identities/actions,
controls, the candidate cross-section, native indicators and the #102 ledger
handoff. K2/K3 remain **house-incumbent E0 comparisons**, not source truth.

## Sources checked 2026-11-06

- **River 0.26.1**, BSD-3-Clause, `online-ml/river` at
  `64285b9dd6c606804753235fe992bcf25b9856ee`:
  [`river/drift/page_hinkley.py`](https://github.com/online-ml/river/blob/64285b9dd6c606804753235fe992bcf25b9856ee/river/drift/page_hinkley.py),
  `river/stats/mean.py`, `river/base/drift_detector.py`. The adapter uses the locked
  library directly; the proof hashes all three installed files against the pinned
  source bytes and compares each update in all three modes, including resets.
- **Adams–MacKay, [arXiv:0710.3742v1](https://arxiv.org/html/0710.3742v1)**,
  section 2, equation (3), sections 2.1–2.2 and Algorithm 1 steps 3–7. This is a
  transcription of the recurrence, not an adopted third-party repository port.
  The paper's section 4 explicitly separates inference from the observation model.
  Informational paper reference, SPDX `NOASSERTION`; no paper text/code is vendored.
- **Zarattini–Barbon–Aziz, [DOI 10.2139/ssrn.4729284](https://doi.org/10.2139/ssrn.4729284)**,
  [author PDF](https://concretumgroup.com/wp-content/uploads/2026/02/A-Profitable-Day-Trading-Strategy-For-The-U.S.-Equity-Market.pdf),
  SHA-256 `9423012e9f0199e3f6925c500725815c236d7ddbdd7500d50d10bac2be745e91`,
  sections 2.1, 3 and 4, pp. 9, 14–15. SPDX `NOASSERTION`, informational.
  The supported denominator interpretation is the mean of the configured prior
  opening windows, following section 5, p. 19's previous-days average. Section 3,
  p. 14 prints `t-1` under the sum indexed by `i`, which would give the previous
  day's volume if read literally. The `denominator` row is explicitly
  `UNCALIBRATED`, cites both passages and is included in the active hash; this is
  a disclosed interpretation, not verified full-paper replication or admission.
- **NautilusTrader v2.0.0rc7**, LGPL-3.0,
  `nautechsystems/nautilus_trader@55c0e82053142bce3a5cba4de4221d3929c2d3bc`:
  native `Bar`, `InstrumentId`, `Price` and `Quantity`; composite syntax in
  `docs/concepts/data/index.md:218-296` and standard internal output in
  `python/tests/unit/backtest/test_bar_aggregation.py`. Native aggregation owns
  OHLCV arithmetic. Row 11's `sextant.data.catalog` supplies the close-stamp convention.
  `common.Parameter` follows ADR-0018 L3 and the existing ranking registry's
  explicit rows and canonical SHA-256 identity, with missing/specification values.

## Integration seams

Import modules from `sextant.research.detectors`; none performs I/O or writes a
ledger. Detector outputs, factory opening windows and screens carry `params_hash`.
This identifies parameter/source specifications only, **not** complete input
provenance, code SHA or admission. `DailyFacts` is a caller-owned input. The
coordinator must bind all remaining identities separately.

- **Page–Hinkley:** `PageHinkleyArm(rows, observation_source=...)` requires exactly
  the five named `PARAMETERS` rows. Every shipped value is `None/UNAVAILABLE`;
  River constructor defaults grant no authority. Numeric statistical parameters
  are finite `Decimal`, `min_instances` is an integer, `mode` is explicit. The
  caller supplies a separately sourced dimensionless series and its specification;
  no normalization or price-to-float conversion is supplied. Only this statistical
  series and parameters cross River's floating-point API. Warm-up returns
  `detected=None`; River resets on the observation *after* a detection. A drift,
  even in `up` mode, is not a bullish extreme-mover or execution signal.
- **BOCPD:** `BocpdArm(rows, initial=...)` takes the three inference rows from
  `PARAMETERS` (`hazard`, `observation_model`, `boundary_condition`); the separate
  `alarm_rule` row stays unavailable and is not accepted by this inference API.
  The explicit boundary vector indexes run lengths from zero. `update` requires
  one predictive density per old run length and a callable `hazard=H(tau)`.
  The adapter evaluates it at `tau=r+1`: **equation (4), H(r+1)**, included with
  its source in `params_hash`. Algorithm 1 prints H(r), a different index; this
  component explicitly chooses equation (4), not an asserted abbreviation. The caller
  owns sufficient statistics and their causal update (step 8), model input
  identity and alignment. State advances only after successful inference. The
  recurrence normalizes each step using `Decimal` arithmetic (subject to its
  numeric context), with no tail cap, pruning, auto-reset or invented model.
  Zero predictive evidence raises rather than inventing a posterior. Constant
  hazard makes `p(r_t=0)` constant: no alarm/direction field or threshold exists.
  Per-step space/work grows linearly; total work is quadratic without pruning.
- **Stocks in Play:** `StocksInPlaySpec(rows)` validates and freezes the complete
  named mapping, including units, values, states and sources; both functions accept
  `spec=`. Every threshold, opening duration and lookback comes from this mapping;
  each output hashes the actual active mapping, including unavailable screens.
  The default `PARAMETERS` retain the paper's opening duration, lookback and filter
  values. Reviewed overrides are adaptations and grant no calibration authority.
  `spec.composite_type(instrument_id)` gives the native subscription, by default
  `...-5-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL`. The coordinator requests/subscribes
  to it; `opening_window` consumes one resulting bar with explicit `composite_type=`.
  It accepts the native delivered standard internal type, keeps the composite
  configuration, and performs **no** five-1m aggregation. Exactly matching configured
  completion after 09:30 New York and row-11 availability by `as_of_ns` are required.
  Independent `coverage_complete=True` remains required: native output can be partial.
  The flag, active hash and composite source travel in `OpeningWindow`; `screen`
  rechecks them on current and every prior window. Missing coverage/source stays
  unavailable and mismatched hashes/types are refused. Bare construction is only an
  explicit fixture/receipt seam, never a way to infer missing source evidence.
  `screen` requires exactly the configured prior sessions and matching `DailyFacts`.
  RVOL uses **share volume** and the bound mean interpretation, never dollars or
  trade count. `PUBLISHED` numeric rows are replication specifications, not success.
  `top_n` remains informational: selection needs the external eligible cross-section;
  a local pass is not top-20 membership. Missing coverage, dates, zero denominator
  or unavailable daily facts stay unknown. Native ATR's period, smoothing,
  initialization/extra warm-up, daily-session definition, raw/action basis and
  input receipts must be resolved under #129 and bound at admission. No ATR is
  computed here; an uninitialized value stays `None`. Row 11's conservative daily
  boundary is next New York midnight. The original paper uses CRSP/IQFeed/MATLAB
  and long/short ORB orders; replacing those inputs/platforms or using only this
  screen is an explicit adaptation, not a full replication. There is no breakout,
  direction filter, stop, sizing, leverage or order implementation here.

`Observation` carries native instrument identity, event/completion time and
availability time. One adapter instance consumes one scalar series with strictly
increasing completion timestamps and nondecreasing availability. A second value
at the same completion timestamp is refused even with a later receipt: without
an independent sample identity it cannot be distinguished from a revision or
duplicate. This is **not a raw-tick adapter**; ranking's canonical equal-time ticks
are not interchangeable with this scalar seam. A tick-derived series needs its
own separately sourced construction/identity specification at admission; do not
jitter timestamps, discard legitimate ticks or aggregate them by an invented rule.
Future/missing inputs and missing authority do not advance state. A missing sample
does not become zero. The coordinator owns coverage/gap policy and starts a fresh
instance when the frozen protocol requires a reset; these components invent no
missing-data policy. Synthetic replay `ts_init` cannot establish real receipt latency.

## Proof and admission boundary

`uv run --frozen pytest tests/proofs/test_detector_arms.py tests/proofs/test_detector_composite.py` is sockets-denied,
synthetic software evidence: River source/update parity, hand-computed BOCPD
vectors and constant-hazard behavior, explicit missing authority, numeric/clock
failures, warm-up/reset, DST-aware completed windows and exact published local
filter boundaries, mutated parameter behavior/hashes, varying-volume denominator,
nonconstant elapsed-duration hazards, and native composite engine delivery/partial
coverage. It is **not** a market experiment or a cumulative trial count.
The separate source-card proofs verify their unchanged hash-bound bytes.

**NOT ADMITTED**, following the owner's #130 ruling and dsh review SHA-256
`c7f809d9c0c1bbc18f27e267110d0c3afa0badb7274521f6c1cf0d02803fe035`.
This follow-up fixes its five Important findings; a passing proof is not a new
method-admission ruling. Both #129 syntheses motivate native composite use (R18).
No `compute admitted` card, acquisition, market replay, study result or threshold search
is produced by this lane. #130's frozen source/method and acquisition stop times
are not extended. #129's completed native-feature syntheses and dsh method review,
source-qualified inputs/controls/cross-section, explicit market parameter/model
specifications and the canonical ledger reservation still gate the coordinator.
The later #130 acquisition HOLD is unchanged. ADWIN, Lee–Mykland, symmetric CUSUM,
OFI and VPIN remain frozen follow-ons, not implemented substitutes.
