# Rank gate at the native entry seam

The rank veto runs in `entry/replay.py::_ReplayEntry._decide`, after first-leg or
held-reclaim qualification and before sizing, order construction or amendment.
`run_replay` accepts the existing `RankingConsumer`; each enabled decision calls
`entry_rank` with the instrument's raw symbol and the native decision clock, then
passes that rank and the same call's reason to `decide_rank_gate`. Refusals journal
`stage=RANK` with the consumer's reason. There is no cached permission or fallback.
A pass clears only ranking; setup, sizing, funding and native risk still decide.
An existing entry's TTL cancellation continues when its rank becomes stale.

The one `RANK_GATE_ENABLED` registry row remains OFF and UNCALIBRATED. The Strategy
snapshots it at construction, so reviewed switch changes occur between runs. OFF
skips consumer access and leaves the decision journal byte-identical to the
unwired starting head (`527340574e828fa3c646371d251355e5e3080373`). The two synthetic
control tapes cover first-leg submit/amend/cancel and held-reclaim submission;
`tests/proofs/entry/rank-gate-off.json` contains their original decision bytes.
The enabled proofs use a real publisher and consumer with fixture-only ages.

This is the existing native replay Strategy, not an account cutover or a running
broker-paper alpha Strategy. `paper/native.py::PaperStrategy` is an intent sink;
C's standalone session and both retired runners receive no changes here. Enablement
still awaits the live heartbeat emitter and reviewed entry-age authority. The
consumer's three deployment freshness ages remain unavailable; fixtures grant no
authority, measured edge, handover or permission to trade.

Lesson: place the consumer read at the Strategy decision that uses it, and pass
the raw symbol rather than the venue-qualified instrument identifier. Preserve the
reader's exact refusal reasons and prove OFF parity against pre-change bytes,
including a supplied consumer that raises if queried. Future native Strategy
integration must preserve this same-call contract rather than cache a passing rank.

Sources: [ADR-0003](../adr/0003-ranking-and-feeds.md):9,24,42;
[ADR-0008](../adr/0008-broker-roles.md) B3/B6; nautechsystems/nautilus_trader
`d53849b216e20f2c122ca01b4dd0da377638b186`, `docs/concepts/strategies.md:130-136,540-569`
(Strategy callbacks, OrderFactory, submit_order); martinfowler.com:
[Release Toggles](https://martinfowler.com/articles/feature-toggles.html#ReleaseToggles),
read 2026-11-10 (ship unfinished behavior disabled and test both toggle states).
