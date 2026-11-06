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
The simulator's BID_ASK native trail is not proof of Alpaca's stop-election basis.
Outside RTH protection, chase and recovery remain dependent on node/feed availability.
The canonical TrialLog writer is still row 10; these arm rows are retained for it and
are never pooled with MODELED research or BROKER-PAPER outcomes.

The [#41 rerun](2026-11-06-exit-study-41.md) has landed and the inherited full-suite test
reruns its hash-checked minute inputs here: hold-to-15:55 still beats all 96 variants.
That tape provides no NBBO or option-B execution latency. The full 371-row PARA minute
snapshot remains unavailable; the seven-row onset excerpt cannot replace it. Qualified
cost-calibrated tick opportunities remain zero in the harvested gain-protection study.
No comparative execution edge, expected-fill loss bound or current account coverage is claimed.
