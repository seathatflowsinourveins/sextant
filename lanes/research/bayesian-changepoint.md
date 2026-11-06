# Source card: Bayesian online changepoint detection

Registry ID: `bayesian-online-changepoint`. Status: **candidate; compute not admitted**.

Source: Adams and MacKay (2007), [*Bayesian Online Changepoint Detection*,
arXiv:0710.3742v1](https://arxiv.org/abs/0710.3742v1), submitted 2007-10-19.
This is a versioned paper reference; no unverified repository port is adopted.
SPDX: **NOASSERTION**, informational.

Source `knowable_at`: `2026-11-06T15:28:06+00:00`, this audit's observation of v1.
The public version submission date is separately recorded; no availability
timestamp is fabricated from that date. Historical input `knowable_at`: **unknown**.
Model: the cited Bayesian run-length method; no LLM-generated market factor.

Hypothesis for later research: online inference over the run length might
detect a regime change in a causally specified market series. The paper's
inference result does not establish tradable extreme-mover direction, detection
delay under thin equity tapes, or an after-cost advantage.

Needs: a sourced observation model and hazard specification, source-qualified
trade series, real availability clocks, a frozen comparison protocol and
cumulative trials. These are **unavailable**, not filled by a fixture or a
generic library default. No posterior threshold or trading wrapper is invented.

OSAP/JKP mapping, HXZ t-screen, replication and post-publication market evidence:
**unverified; no pass asserted**. The card is method inventory only and produces
no signal, sizing, prices, orders or replay-ready factor.
