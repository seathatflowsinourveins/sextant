# Owner proposal: S data source, before any connection

Issue #111; read 2026-11-06. **Proposed first source: B's account's existing SIP entitlement, for a bounded S probe only after its stream handover is recorded through #38.** The lead reports B free of the old writer. That report alone does not confirm SIP entitlement, an unused websocket, future feed ownership or permission to connect. No connection, key read, subscription, vendor contact or purchase has occurred.

## Stream owner and alternatives

| Proposal | Benefit | Required owner decision and unresolved scope |
|---|---|---|
| B-account SIP, one designated stream owner | Reuses the existing Alpaca data stack and its native/house input shape. S execution remains local and gets no broker execution client. | Confirm data entitlement and stop/ready receipt for the **stream**, name its owner and the bounded S probe, then explicitly hand it over. B's protection has priority: retire S's socket before B takes it. Ongoing S beside B requires a separately qualified single-ingester fanout; no duplicate connection is inferred. |
| Separate Massive Stocks Advanced subscription, **$199/month individual list** | Independent data ownership avoids occupying B's stream; real-time wildcard second aggregates plus trade/quote channels can be evaluated. | Owner approves a purchase and permitted use, and a pinned adapter is qualified before connection. Pre/core/post coverage is documented; full 24/5 overnight coverage and first-second delivery latency remain unverified. Second aggregates alone do not establish first-rising-trade timing or executable BBO. |

I recommend the first route for the initial bounded measurement, with a stop-and-return receipt before B's own data client starts. For continuous independent S operation, the second route is a proposal to investigate those explicit gaps, not an approved replacement for a qualified 24/5 feed. No other old account's stream is reassigned.

[Alpaca's connection contract](https://docs.alpaca.markets/us/docs/streaming-market-data), read 2026-11-06, limits connections by subscription and says many have one; the lane applies the owner's one-stream rule without probing a second connection. [Stock channels](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data), read the same day, distinguish SIP, IEX, delayed SIP, BOATS and derived overnight. These are separate source/coverage identities. Bars arrive after a minute completes; minute bars plus frontier-only trades cannot establish whole-universe first-second discovery. [Massive's second-aggregate documentation](https://massive.com/docs/websocket/stocks/aggregates-per-second), read the same day, supplies the real-time Advanced price, wildcard support and pre/core/post scope; it gives no measured end-to-end budget for this host.

## Message-rate evidence carried from #71

The landed [#71 brief](2026-11-06-research-data-briefs.md#near-second-onset-coverage-and-message-rate) supplies the denominator and limitations. These are workload observations, not configured S capacities:

| Source | Recorded observation | Boundary |
|---|---|---|
| [CTA SIP 3Q26](https://www.ctaplan.com/publicdocs/ctaplan/CTA_SIP_Metrics_3Q_2026.pdf), trade table p2; re-read 2026-11-06 | Tape A/B peak **232,600 messages/s**, **80,900 messages/100 ms**, **113.9 million/day** | Excludes Tape C; not Alpaca's delivered event rate or this host's throughput. |
| Same report, quote table p1 | Tape A/B peak **1,979,000 messages/s**, **2.761 billion/day** | A larger separate workload; do not sum noncoincident peaks. |
| #71's cited independent Alpaca forum recording | **20,896,473 trades / 1,424,494 messages** in about an hour: approximately **5,805 trades/s / 396 messages/s** | Self-report; batching, completeness and peak capacity unverified. Keep frames/messages distinct from parsed trades. |
| Pinned house SIP probe, `northstar-trading@paper 8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:docs/research/2026-10-22-alpaca-sip-session-probe.md` | Wildcard bars max **8,497/minute**, open-hour receipt p50 **95 ms after minute end**; closing-minute omissions **2,259/7,929** settled REST bars | Bar receipt is neither full-market trade throughput nor first-second onset. Raw frames were not rerun here. |

The exact account's whole-market trades/events/bytes, burst duration, Tape C load, queue delay, drops and sustained local capacity remain unavailable. The paid-feed proposal does not repair those missing measurements by quoting a marketing plan.

## What an authorized probe must record

One socket owner records all eligible-universe trades for discovery; executable quotes cover deployed/held/frontier instruments. Preserve conditions, corrections/cancels, source/session identity, event time and actual local receipt time. Record frames, decoded messages, trades, quotes and bytes separately at whole-run, one-second and 100-ms granularity; record queue age/occupancy, parse/dispatch time, reconnects, gaps, unknown instruments, process RSS and minimum MemAvailable. CPU/queue/age acceptance values need sourced registry authority and actual calibration; no new thresholds are set here. The SIP and overnight baselines remain separate, and no overnight switch is authorized by this document.

Before claiming S active, demonstrate routed native A/A account/namespace isolation, halt and retirement, qualified all-stack callback coverage, one TrialLog reservation/outcome per attempt, and recorded feed-to-decision delivery under the owner's accepted gates. The present native binding cannot build two same-venue simulated clients with explicit routing in one node; one isolated node per arm is the available configuration shape, and its one-feed fanout needs its own acceptance. No high-level command counter is labelled broker wire pacing.

## Recorded inputs available now

The three #41 inputs hash-match their recorded identities: **117,486 minute bars, 54 symbols**, plus recorded fills and owner first-order classification. The scanner's `2026-10-27/20261027T084937960584Z.json` was read without changing the old tree and copied to local data storage: SHA-256 `60681e62d2e1645ebadcec1e8f58c2df9b3565425d1341e00af57ef91223ba08`, **36,676,166 bytes**. It supplies bids/asks for all 54 study symbols; all 54 lack bid/ask sizes. Its capture-completion and consumer-receipt clocks are absent. The local reader retains those unknowns and refuses to turn a size-less quote into native executable liquidity. It also refuses hash changes, crossed/invalid prices and quote events after the snapshot cutoff.

This audit is read-only input evidence, not an arm-run or an original acquisition-latency reconstruction. A minute bar is never expanded into invented trades; a saved rank is never asserted to be the current complete ranking generation. The recorded replay and real-feed SIMULATED tiers remain distinct, and no economic merit or S-ready result is claimed.
