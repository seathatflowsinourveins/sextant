# Options lane

**Charter.** Research and simulation only. Options data is a zero-weight factor: it may inform research, but it never moves a rank, an entry, an exit, a size or leverage. No option-contract order is admitted on any lane, including paper, until an admission decision names the account's options level, premium at risk, Greeks, assignment and margin. ([ADR-0016](../../docs/adr/0016-options.md))

**Hours.** Sim 24/7 on the replay clock; no broker session is held open.

**Limits.** None, because the lane submits nothing. OPRA live trades and quotes plus historical trades and bars since 2024-02 are the data ceiling — historical quotes do not exist, and the account is limited to 1,000 quote slots with no wildcard ([ADR-0013](../../docs/adr/0013-us-equity-data-stack.md)).

**What it runs.**
- A zero-weight options factor in the research catalog, evaluated like any other factor and given weight only if a point-in-time lift interval excludes zero ([ADR-0016](../../docs/adr/0016-options.md)).
- Simulated expiry settlement in NautilusTrader: in-the-money physical or cash index, out-of-the-money expires. Early exercise, assignment, DNE and buying-power checks are missing at the pinned engine, so a sim result is not a broker result.
- The `options-strategy-advisor` skill from `tradermonty/claude-trading-skills` at `d8e71ce2f0b069eb5b6fca352857c168c35e6c46` as a reference only; it carries no entitlement, edge or authority ([ADR-0016](../../docs/adr/0016-options.md)).

**Rules.**
- OPRA activity or skew is not the Pan–Poteshman buyer-to-open flow, and no published option strategy transfers a numeric bound into this account.
- A factor earns weight only through measured point-in-time lift; a zero-weight factor is not an admission.
- Advertising an option order needs a design decision, a guard amendment and paper acceptance covering position margin, notifications and expiry reconciliation, in that order.
- Unverified until then: OPRA entitlement, the house options level, margin treatment, the engine-versus-broker expiry divergence and the IB Greeks stream ([ADR-0016](../../docs/adr/0016-options.md)).

**Row 13 components.** `sextant.research.options.OptionsFactor` retains a raw source/revision/hash and integer availability clock, including unknown values, with a fixed weight of zero. It adds no OPRA scoring formula. `sextant.research.options_jev.ResearchObserver` is a Nautilus `DataActor`, with no order methods. A paired ON/OFF software fixture shares one venue, fill/fee/latency models, inputs and `random_seed`; Jev changes shadow annotations only.

The recorded Jev catalyst screen carries the implemented Noul/Choice questions from [ADR-0017](../../docs/adr/0017-jev-judgments.md), using `typesafe-sdk==0.7.5` and exact `jev-1.14.0`. `parameters.json` supplies its six sourced **UNCALIBRATED** starts, without fallback values. Records retain the full response, request/question hashes, source version, clocks, model, usage and answer label. Consumption performs no API or file I/O.

- Keep every distinct source event; a usable negative wins over positive priority. A new revision replaces its predecessor even when its answer fails. Expire answers at 20:00 New York, including DST, holidays and weekends.
- Missing, future, unavailable, late or invalid answers preserve the incumbent with a named reason; never manufacture a neutral answer. Never pool `jev: live-ledgered` and `jev: recalled` in one arm. See the [lesson and source receipts](../../docs/handbook/options-jev.md).
- `jev-rank`/`jev-exit` proposals remain pending their source's sign-offs; this carry does not activate them. There is no order, sizing, leverage, exit or protection integration.

**Run status.** `uv run --frozen python -m sextant.research.options_jev` reports simulation and ledger binding **NOT_RUN**. [Row 10 / #72](https://github.com/seathatflowsinourveins/sextant-archive/issues/72) must land its canonical TrialLog and frozen arm registration before an experiment driver is bound. Every arm and run must enter that one ledger; no local replacement is supplied. The native engine test is a synthetic software fixture, not a research trial, model-quality test or merit receipt. Full row 13 execution remains unfinished.

**Verify.** `uv run --frozen pytest tests/proofs/test_options_jev.py`. No key, stream or service endpoint is used. Future keyed inference uses only `scripts/with-keys.sh -k TYPESAFE_API_KEY -- <one command>` within the approved capture/ledger workflow; this module provides no inference command.

**Sources.** Harvested northstar-lanes/northstar-trading options records, trading ADR-0016 (KEEP) and ADR-0003 P10 at the pins in `docs/manifest.md`.
