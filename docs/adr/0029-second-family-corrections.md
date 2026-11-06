# ADR-0029: Carry the old records' second-family corrections, re-measured at their upstreams

- **Status:** accepted.
- **Date:** 2026-11-06
- **Harvested from:** northstar-lanes@a5c8a2712833:docs/adr/0004-ranking-and-feeds.md, amendment 2026-11-05, "Kept corrections", lines 353–395.
- **Harvested from:** northstar-lanes@a5c8a2712833:docs/adr/0005-entry.md, amendment 2026-11-05, DeepSeek's CONFIRM, lines 464–470.
- **Harvested from:** northstar-lanes@a5c8a2712833:docs/adr/0006-exit-engine.md, amendment 2026-11-05, DeepSeek's CONFIRM, lines 354–360.
- **Inventory:** [campaign harvest](../research/2026-11-06-campaign-harvest.md), issue #61.

## Context
#33 harvested the lanes records at `00203275944a`. After that pin each finalized lanes record received a blind DeepSeek leg, which re-read its upstream citations. Three of those findings change a line Sextant carries, in ranking, entry and the fast exit. The rest confirm or touch no Sextant line (the inventory lists each).

## Decision
- **C1, halt feed (amends [ADR-0003](0003-ranking-and-feeds.md) K6).** The Nasdaq trade-halt RSS already carries halts of listings beyond Nasdaq; Alpaca's `statuses` cross-check it rather than stand in for it. Poll it at most once a minute: the feed's `<ttl>1</ttl>` and its guidance page say the same. Coverage of every venue stays **unverified**, so an unknown halt state still makes a symbol ineligible.
- **C2, extended-hours entry (amends [ADR-0004](0004-entry.md) N4).** An `extended_hours` order is a LIMIT with `time_in_force` `day` or `gtc`; Alpaca rejects every other type and TIF.
- **C3, the fast exit at the rc8 bump (binds [ADR-0010](0010-risk-guard-pacing-and-halt.md) G1 and [ADR-0005](0005-exit-engine.md)).** From NautilusTrader `v2.0.0rc8`, emulated order releases pass the RiskEngine, and `HALTED` denies their stops. A halt or kill that must still let protective exits out uses `REDUCING`. Sextant stays on rc7 until the bump PR, which tests this before it lands.

## Evidence
| Claim | Source | Re-measured 2026-11-06 |
|---|---|---|
| C1 | lanes 0004 at `a5c8a2712833`, kept corrections `0004:145`/`:146`; both refuters failed to refute | `https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts` 15:36Z: `<ttl>1</ttl>`, `ndaq:Market` NASDAQ 37, Non NASDAQ 4, NYSE 2, NYSE Arca 1. `Trader.aspx?id=TradeHaltRSS`: "Please do not query the data more than once a minute." |
| C2 | lanes 0005 at `a5c8a2712833`, DeepSeek CONFIRM: "LIMIT-only extended hours (with an added day/gtc TIF condition the record does not state)" | [Orders at Alpaca](https://docs.alpaca.markets/docs/orders-at-alpaca), read 2026-11-06: "Only limit orders with time_in_force set to day or gtc orders are accepted as extended hours eligible." |
| C3 | lanes 0006 at `a5c8a2712833`, DeepSeek CONFIRM: rc8 "makes emulated releases undergo risk checks (HALTED denies stops; use REDUCING)" | nautechsystems/nautilus_trader@v2.0.0rc8 `d53849b216e20f2c122ca01b4dd0da377638b186`, release notes: "Changed emulated releases to undergo risk checks; use `REDUCING` for eligible exits, as `HALTED` denies stops" |

Convergence: each lanes record was finalized on two-family research legs plus a cross-family review (line 3 of each). The DeepSeek leg is the second family, and the amendment carrying it had its own cross-family review (northstar-lanes #81). The upstream read above is this record's own measurement, not a copy of the leg's.

## Consequences
- Entry and exit code sets `time_in_force` on every extended-hours LIMIT. `src/sextant/exits/engine.py` already sends a reduce-only `GTC` LIMIT with no emulation trigger, so it meets C2 and C3 does not reach it.
- A halt-feed reader can treat a non-Nasdaq `ndaq:Market` item as a real halt; a symbol missing from the feed is not thereby un-halted.
- The IB order-list post-only correction (lanes 0008) and the register renumbering (lanes 0003) touch no Sextant line, so none is carried.

## Revisit when
- The rc8 or later bump PR: prove a protective emulated release under the guard's halt state in a test. Owner: the lead.
- A halt-feed reader lands: re-read `ndaq:Market` coverage and record which venues arrive. Owner: the research lane.
- Alpaca changes its extended-hours TIF table: Renovate or the docs re-read opens the PR. Owner: the lead.
