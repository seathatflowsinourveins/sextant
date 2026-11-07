# Detector components: parity is not admission or alarm authority

Lesson from [#130](https://github.com/seathatflowsinourveins/sextant/issues/130),
serving the ranking/onset step and applying [ADR-0015](../adr/0015-research-lane-and-strategy-sourcing.md)
and [ADR-0018 L3/L9](../adr/0018-evidence-and-learning-loop.md). The changed rule is
in [practices](practices.md#evidence-and-learning); implementation, exact pins and
integration limits are in [the adapter contract](../../lanes/research/detector-adapters.md).

The Adams–MacKay recurrence gives a run-length posterior, not an authorized equity
alarm. With constant hazard `h`, its changepoint numerator is `h` times the total
predictive mass, so normalization yields `p(r_t=0)=h` regardless of the observation.
Thresholding that coordinate would invent a detector rather than reproduce one.
Keep market hazard, observation-model, boundary and alarm rows unavailable until
their authority exists. The synthetic proof deliberately verifies the constant
coordinate and the nonconstant-hazard hand calculation, not a profitable signal.

River's own implementation is the Page–Hinkley oracle. Wrap it rather than build a
second copy; compare all modes and its next-observation reset. Constructor defaults
are not calibration. A fixture supplying explicit rows permits a software witness,
never a market parameter decision. Missing/future observations do not become zero
or consume warm-up. This scalar seam requires strictly increasing completion
timestamps, not raw equal-time ticks: duplicates/revisions and backward clocks
are refused, not reordered or jittered.

The Stocks in Play screen is only knowable after the completed 09:30–09:35 New York
window and receipt. It compares shares with time-matched prior opening shares.
A valid local screen cannot supply top-20 membership without the eligible
cross-section, and cannot establish first-second onset. Require explicit coverage
and native-ATR readiness; do not fill absent minutes or smoothing authority from
the paper's mention of Wilder. Preserve the paper's long/short and platform/data
scope, including notation ambiguities, when proposing a later adaptation.

The post-merge dsh review (`c7f809d9c0c1bbc18f27e267110d0c3afa0badb7274521f6c1cf0d02803fe035`)
found that decorative rows can hash a method the runtime never used. Consume one
validated immutable mapping; mutate its rows in proofs and require both changed
behavior and changed hashes. Carry that hash, independent coverage and the native
composite configuration into every opening window, and recheck them in the screen.
Native composite delivery strips the source suffix and can emit a partial window:
its presence alone supplies no coverage. Never rebuild its OHLCV arithmetic locally.

Paper conventions need executable distinctions. This component uses equation (4)'s
`H(r+1)` by evaluating a caller's duration hazard at `r+1`, and binds that convention
to identity. Its RVOL denominator row explicitly chooses the prior-window mean
from the hash-pinned paper's §5/p.19, labels §3/p.14's notation as interpreted, and
remains `UNCALIBRATED`. Unequal volumes and a nonconstant duration hazard distinguish
the alternatives. These defect fixes leave the owner's **NOT ADMITTED** ruling and
acquisition HOLD unchanged; no component proof supplies a market result or alarm.

**Witness/installation state:** `tests/proofs/test_detector_arms.py` uses fabricated
samples, denied sockets, installed-source hashes and native bars. The components
have no acquisition, runner, ledger or order writer. No market study or empirical
sample is produced here; merits and cumulative trials remain coordinator-owned.
The original source cards and their hash-bound no-admission receipt are unchanged.

**Sources read 2026-11-06:** River 0.26.1 at
`64285b9dd6c606804753235fe992bcf25b9856ee`, `river/drift/page_hinkley.py` and its
mean/base dependencies; Adams–MacKay arXiv:0710.3742v1, section 2 and Algorithm 1;
Zarattini–Barbon–Aziz DOI 10.2139/ssrn.4729284, hash-pinned author PDF sections
2.1/3/4/5; NautilusTrader rc7 at `55c0e82053142bce3a5cba4de4221d3929c2d3bc` native
model types and row 11's close/availability convention. See the contract for URLs.

**Revisit:** completed #129 syntheses, dsh method review, sourced market parameter
specifications, native-indicator initialization evidence or changed upstream bytes.
Any later experiment still needs the frozen source/input/control/cross-section
identities and the one #102 reservation receipt; these tests waive no admission
or expired checkpoint. This is a repo-native implementation lesson, not an append
to the single-writer `lesson/1` journal or a second numerical record store.
