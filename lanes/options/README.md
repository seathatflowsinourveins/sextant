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

**Sources.** Harvested northstar-lanes/northstar-trading options records, trading ADR-0016 (KEEP) and ADR-0003 P10 at the pins in `docs/manifest.md`.
