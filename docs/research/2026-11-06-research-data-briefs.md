# Research evidence briefs for issue #54

Read date: **2026-11-06**. Public documentation and pinned recorded reports only;
no stream, broker call, purchase or new strategy research trial. Account rights,
local throughput and original historical availability are not inferred from
vendor documentation. [#42](https://github.com/seathatflowsinourveins/sextant/issues/42)
remains open on its data/protocol/ledger blockers.

## Near-second onset: coverage and message rate

**Conclusion, an inference from the feed contracts:** discovery over the whole
eligible universe needs timely trade/volume observations for every eligible
symbol, or an equivalent aggregate with proven publication latency. All-symbol
minute bars plus trades on an already selected frontier cannot observe the
first second of an unselected mover. This is a requirement gap, not authority
to change the shared stream owner or a claim that a detector already exists.

[Alpaca's stock channel documentation](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data)
says minute bars arrive after the minute ends; late-trade updates arrive after
the half-minute mark. The trade channel includes conditions, corrections and
cancels. Nanosecond timestamps do not promise nanosecond delivery. Whole-market
quotes are a separate, much larger workload; they are not needed merely to
observe each symbol's trade onset. Executable quotes still matter for entries,
exits and cost evidence.

| Recorded source and scope | Observation | What it does not establish |
|---|---|---|
| [CTA SIP 3Q26 metrics](https://www.ctaplan.com/publicdocs/ctaplan/CTA_SIP_Metrics_3Q_2026.pdf), p2, Tape A/B trades | Peak **232,600 messages/s**; peak 100 ms **80,900** messages; peak day **113.9 million** transactions | Not Tape C, Alpaca's delivered event rate, a typical second, or this host's capacity |
| Same report, p1, Tape A/B quotes | Peak **1,979,000 messages/s**; peak day **2.761 billion** transactions | Different feed and peak; do not sum noncoincident peaks into a measured all-tape rate |
| [Independent user's Alpaca forum recording](https://forum.alpaca.markets/t/best-practice-for-subscribing-to-6k-symbols-in-trades-stream/17678), 2025-08-20, about 15:15–16:15 ET | Reports **20,896,473 trades / 1,424,494 messages** in about one hour; arithmetic gives about **5,805 trades/s / 396 messages/s** | Self-report, one near-server Go client; message/frame batching and completeness not independently verified; not peak capacity |
| [Pinned house SIP probe](https://github.com/seathatflowsinourveins/northstar-trading/blob/8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa/docs/research/2026-10-22-alpaca-sip-session-probe.md), S4/S5/S13 | Wildcard minute bars: max **8,497/min**; open-hour receipt delay p50 **95 ms after minute end**. Its closing minute omitted **2,259/7,929** settled REST bars that day | Bar count is not trade-message throughput; fast receipt after minute close is not first-second detection; raw frames were not rerun here |

The CTA PDF bytes read have SHA-256
`d3cae408f999252946ce207438c3ff745d8096bfb96a5d76bff8f38af78e72f1`.
The tables' units are thousands per second/100 ms and millions per day.
**Unknown:** this account's full-market trade/event/byte peak, Tape C's added
load, burst duration, local queue lag, drops, and sustainable scanner throughput.
No raw all-symbol trade capture was supplied to measure these locally. Keep
these values unavailable; do not substitute minute-bar rates or REST quotas.

[Massive's second-bar channel](https://massive.com/docs/websocket/stocks/aggregates-per-second)
supports wildcard aggregates and documents pre/core/post sessions. It supplies
no end-to-end latency guarantee in the page read. The GPT leg's specific
two-second publication-delay claim was **not reverified here** and is not used
as a measured budget. A future authorized owner of the one feed must qualify
actual delivery and processing from recorded events before claiming capacity.
[Alpaca's connection contract](https://docs.alpaca.markets/us/docs/streaming-market-data)
often permits only one connection; the owner's current limit stays unverified.

## Owned Sharadar versus a purchase

**Recommendation:** audit the already owned Prices entitlement and exports
against ADR-0013's existing delisting/identity acceptance before buying another
daily master. Daily coverage and tick replay solve different requirements.
No vendor's marketing label clears acceptance or supplies receipt history.

| Product | Verified vendor scope and current USD list price | Fit and remaining evidence |
|---|---|---|
| [Sharadar Prices](https://sharadar.com/subscribe) | 10 Years **$199/year**; Full History **$299/year**. Includes `stocks`, `tickers`, `actions`; **daily**, not intraday | Plausible owned source for the 2021+ daily seed/identity audit; actual bill, transferred rights, exports, category coverage and independent delisting sample remain unverified |
| [Massive Advanced](https://massive.com/pricing) | **$199/month**, individual use. [History tables](https://massive.com/knowledge-base/article/how-much-historical-stock-data-does-massive-have) advertise all available trades/quotes and bars, beginning 2003-09-10 | Adds intraday replay capability; require session/schema coverage and corrected-versus-as-received labels. Exact earliest quote/session completeness is not established by the plan label |
| [Norgate US Platinum](https://norgatedata.com/stockmarketpackages.php) | **$630/year** or **$346.50/6 months**; daily histories, delisted formerly major-exchange securities and historical index membership, 1990+ | Daily alternative if owned coverage fails; does not replace tick replay. Do not buy it alongside an accepted daily master without a named gap |

[Sharadar's master](https://sharadar.com/docs/tickers) gives active/delisted
metadata; its [actions](https://sharadar.com/docs/actions) include listing,
delisting and ticker-change events. Its [FAQ](https://sharadar.com/docs/faqs)
explains that renamed histories are rewired and recycled symbols are suffixed;
separate share classes receive separate permatickers. Those data must be
reconciled as dated identities, not joined on today's ticker. Daily delivery
and effective dates do not prove when a historical field became knowable.

[Massive's dated reference endpoint](https://massive.com/docs/rest/stocks/tickers/all-tickers)
is available below Advanced too; Advanced is not required merely to obtain
older ticker reference data on paid plans. Its [security-master note](https://massive.com/knowledge-base/article/does-massive-have-a-downloadable-security-master)
warns about missing fields and the absence of one permanent identifier that
survives every change. Its [float FAQ](https://massive.com/knowledge-base/article/does-massive-have-historical-float-data)
explicitly provides **latest float only**; adding a past date does not create
history. Neither purchasing Advanced nor owning daily prices settles PIT float.

The owner decision is therefore conditional: retain/audit owned Sharadar for
daily membership; consider Massive for a demonstrated tick/quote replay gap;
consider Norgate if the daily identity audit fails. No purchase or entitlement
change is authorized by this brief. #42 still lacks the accepted dated master,
rights, independent sample, ordinary controls, causal labels and canonical ledger.

## NautilusTrader rc8 versus rc7

See the [feature and migration checklist](2026-11-06-nautilus-rc8-checklist.md).
rc8 is verified at `d53849b216e20f2c122ca01b4dd0da377638b186`; installed Sextant
remains pinned to rc7. The checklist is static evidence, not a compatibility
test, migration, adapter qualification or engine-upgrade decision.

## ADR-0025's holding control

The [original XR29 study](https://github.com/seathatflowsinourveins/northstar-trading/blob/8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa/docs/research/2026-10-29-b-exit-replay.md)
explicitly holds each identical entered position until **15:55 ET**. On its
1,025-entry complete-horizon cohort this earns **76.44 versus 54.78 bps** for
the best of 96 active candidates at 3 bps/side, and **70.42 versus 48.76** at
6 bps/side. These are correlated minute approximations, not independent tick
trades or confirmatory OOS merit; October 29 is incomplete/censored.

Call that comparator **hold-to-15:55**. Reserve **hold-flat/no-trade** for the
zero-position control in the EMA thin slice and statistical admission rules.
The wording correction preserves the negative active-exit result and every
existing protection requirement; it grants no permission to remove stops.
ADR-0025 and the harvested evidence note are corrected in this PR.

## Does Alpaca `v2/sip` follow the 2026-12-06 overnight tape?

**Unverified at the endpoint level.** [UTP notice 2026-30](https://www.nasdaqtrader.com/TraderNews.aspx?id=UTP2026-30)
and [FINRA's notice](https://www.finra.org/filing-reporting/technical-notices/extension-of-trf-operating-hours)
name December 6, 2026 and Sunday 21:00 through Friday 20:00 ET with a nightly
20:00–21:00 pause. Those infrastructure notices do not certify a reseller URL.

[Alpaca's 24/5 page](https://docs.alpaca.markets/us/docs/245-trading) now says it
is preparing for that industry launch, subject to dependencies, and describes
partner order-routing continuity. Its [stock-feed page](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data)
still separately identifies `v2/sip`, direct `v1beta1/boats` and derived
`v1beta1/overnight`. Neither page expressly promises this account's `v2/sip`
overnight hours, quote sources, symbols, corrections or entitlements on launch.
Order-routing readiness cannot stand in for market-data endpoint evidence.

Keep SIP and BOATS source identities/denominators separate. The owner needs
Alpaca's explicit feed/plan commitment, then the authorized feed owner needs a
recorded launch-day coverage/latency receipt after handover. This research task
opens no stream, including test streams, and makes no vendor inquiry on behalf
of the owner.
