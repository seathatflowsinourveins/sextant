# Source card: Page–Hinkley as an onset component

Registry ID: `river-page-hinkley`. Status: **candidate; compute not admitted**.

Source: [River 0.26.1](https://github.com/online-ml/river/blob/64285b9dd6c606804753235fe992bcf25b9856ee/river/drift/page_hinkley.py),
commit `64285b9dd6c606804753235fe992bcf25b9856ee`, BSD-3-Clause.
The implementation cites Page (1954), *Continuous Inspection Schemes*, and
Sebastião–Fernandes (2017). It detects changes in the mean of successive values;
it supports increasing, decreasing and two-sided modes and has no warning zone.

Source `knowable_at`: `2026-11-06T15:28:06+00:00`, observed in this audit only.
Historical input `knowable_at`: **unknown**. Model: none; upstream statistical
component. Cutoff: this source observation. No frozen market factor is emitted.

Hypothesis for later work: this maintained component might improve the timing
of one existing onset component at matched alert coverage. It is neither an
extreme-mover ranker nor a complete trading strategy. Its generic toy example
establishes execution, not equity false-alarm control or net returns.

The [previous reconciled onset record](https://github.com/seathatflowsinourveins/northstar-trading/blob/8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa/docs/research/2026-11-05-extreme-movers-onset.md)
keeps the incumbent and requires separately registered ablations; it finds no
complete upstream method for the literal target. No new normalization, wrapper,
label, threshold or selection rule is built here. Upstream constructor defaults
are software defaults, **not Sextant calibration or registry authority**.

Needs: coverage-qualified eligible trade observations, source/receipt clocks,
own-symbol baseline, frozen causal controls and the cumulative trial ledger.
OSAP/JKP and HXZ strategy screen: **not established**; this generic detector has
no claimed return statistic to pass it. Missing protocol/input authority keeps
the card unavailable for compute under ADR-0015 and #42.
