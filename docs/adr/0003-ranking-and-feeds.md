# ADR-0003: Rank potential movers from their first prints and primary catalysts

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-lanes@00203275944a:docs/adr/0004-ranking-and-feeds.md, whole record and amendments.

## Context
Discovery must find US equity movers before a late spike, in every supported session.
Ranking supplies entry candidates; it does not establish eligibility, fills or an economic edge.

## Decision
- **Universe (K1, K8):** every active NMS-listed common stock on Tapes A, B and C, every cap and price, sub-$1 included, plus TXSE listings and NMS-listed ADRs labelled `security_type = adr`. OTC stays NONE until an owner-approved data source exists. Price > $5 and ADV > $20M are not ranking floors.
- **Delivery (K1):** one in-node publisher owns the user's existing SIP socket; full-market trades, wildcard minute/updated bars and statuses feed per-symbol state. Quotes cover top-N, holdings and catalyst names. Publish top-N plus full-market generations every second. The in-node sandbox adds no socket; typed ticks and backlog delivery are separate from ranking transport.
- **Overnight (K1, K5):** the publisher owns the separate BOATS endpoint through alpaca-py `url_override`; its quota interaction and wildcard semantics remain **unverified**. Keep overnight source identity and denominators separate from daytime SIP. Preserve vendor bar fields `vw` and `n`.
- **Score (K2):** `move × dvol_ratio`, ties by `trades_accel`. Re-evaluate on every eligible trade; publish at most once per `publish_min_interval_s`. Move uses the most recently completed official regular-session close, split-adjusted; an undocumented fallback gives None. POST uses that day's close, OVERNIGHT the session just ended, PRE/RTH the previous session. Record the RTH open-based move separately.
- `dvol_ratio` is segment-to-date dollar volume divided by the symbol's own time-matched baseline. `trades_accel` compares its short-window count with the prior baseline rate. Require minimum move, `move_1m > 0`, minimum ratio and acceleration. Dollar volume/share never form the score; price, volume, trade rate and spread are observations on paper. Excluded entries still rank with flags.
- **Onset (K3):** anomalous short-window dollar volume, minimum prints, a move off the quiet price and rising at the decision flag a first leg within `first_leg_window_s`; no headline is required.
- **Accumulation (K3b):** a base has price-eligible range over `accum_window_s` within `base_max_range × price`. Average available components: abnormal blocks, condition `F` sweeps at/above ask, exchange `D` TRF prints at/above ask, rising classified buy-minus-sell volume, and time at/above segment VWAP. Flag at `accum_min_score`; feed ACCUMULATION and registered ignition/continuation features. Options calls at ask remain unavailable without quotes.
- **Candidates (K3c):** execution/move/session/halt/catalyst rhythms, microstructure and options flow require cited detectors and measured lift before adoption. The source's 19 taxonomy types are GAP; context types stratify results and never vote.
- **Catalysts (K4):** news, EDGAR, FDA, halts and earnings run 24/5. Each `CatalystEvent` keeps source and receipt times; only source-stated outcomes set polarity. Re-rank immediately; pre-position primary-source calendar names with quotes, baselines, watchers and size.
- **Feed roles (K4):** the house EDGAR Atom poller stays primary pending paired timing; a tie goes to the upstream client. edgartools is ADOPT-PART for documents/parsers behind raw bytes, receipts, Decimal and archived `ACCEPTANCE-DATETIME`, HTTP cache off; exclude its Form 4 numeric/owner-resolution and XBRL float conveniences. SEC PDS buys no lead under either research leg's reading.
- FDA press/specialty announcements give first sight; openFDA validates/backfills only (Drugs@FDA daily weekdays, PMA/510(k) monthly). The FDA/Federal Register calendar pre-positions events. Our Alpaca news WebSocket entitlement has no Benzinga; aggregators are never primary. Benzinga direct is the owner's first timed trial; Unusual Whales follows only if an aggregator adds lead. FMP/pdufa.bio are calendar research, never triggers. No paid feed is adopted.
- **Sessions (K5):** `exchange_calendars` XNYS actual open/close, including early closes; PRE 04:00–open, POST actual close–20:00 ET, OVERNIGHT 20:00–04:00 ET assigned to the next trading date. The actual closing print belongs to no extended segment.
- **Freshness (K6):** generations carry identity, coverage and known-at time; use rc7 message-bus external streams and heartbeats. Missing heartbeat or stale/invalid/incomplete generation raises an alarm and refuses entry, with no fallback. Unknown halt state or an asset snapshot older than vendor refresh makes that symbol ineligible. Nasdaq halt RSS polling is no faster than `<ttl>1</ttl>` (one minute); other listings rely on Alpaca statuses until coverage is verified. Numeric LULD bands are unavailable.
- **Latency/labels (K7–K8):** report publication, vendor receipt, local receipt, generation, entry-eligible and submission times. About one second for full-market discovery is the owner's first target. Label price bands ≥ $5, $1–$5, < $1, venue, common/ADR and L/S liquidity tier with source/as-of time; cap bucket stays null until point-in-time shares exist. Labels never gate ranking. Missing ADR 6-K/20-F coverage means "no catalyst".
- **Experiment:** compare MOVER-v2, CF-EVENT-LEX-v1, CapFocus-Borda-v1 and frozen `CURRENT-native/top100/1+potential/2` with CASH and matched hold-flat at 1× and `cost_stress_multiple`, using walk-forward, CPCV, DSR and PBO. Freeze eligibility for factor comparisons; threshold sweeps are separate families. Do not pool different `implementation_sha` builds. Ablate ratio, acceleration, surge, accumulation and each accumulation component. XGBoost `rank:ndcg` waits until it beats every baseline. Every numeric parameter stays in the registry with calibration state.
- **Limits:** RTH peak protection-path capacity, paid-feed lag/coverage, overnight semantics, ADR catalyst coverage, cap source, backing-store configuration and after-cost advantage remain **unverified**. An RTH regression beyond measured noise moves socket ownership to a separate publisher process that fans out ticks; it never adds a second socket.

## Evidence
| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| Universe, score, onset, accumulation, experiment | northstar-lanes@00203275944a:docs/adr/0004-ranking-and-feeds.md, K1–K3c, K8, "How the score is chosen" | Owner rulings 2026-10-30; GPT/Google capital-focus legs; GPT/Google/Claude universe/factor convergence. Accumulation papers and score edge are **unverified** in the source. |
| Source roles and paid-feed boundary | northstar-lanes@00203275944a:docs/adr/0004-ranking-and-feeds.md, K4, Evidence, amendment 2026-11-02 | GPT/Google SEC/FDA supplement; edgartools v5.62.1, commit `9f2ff388c0ad21cfbaba4c7587ba8be7abe6816d`, `edgar/current_filings.py`; owner trial ruling 2026-10-31. |
| Socket, session and generation seams | northstar-lanes@00203275944a:docs/adr/0004-ranking-and-feeds.md, K1, K5–K7, upstream checked | alpaca-py v0.44.0 `cc4cb3b7ba50ae250e621983c2779047fb16bb28`, `alpaca/data/live/stock.py`; NautilusTrader v2.0.0rc7 `55c0e82053142bce3a5cba4de4221d3929c2d3bc`, `MessageBusConfig`; exchange_calendars 4.13.2 `exchange_calendar_xnys.py`, read 2026-10-30/31. Backing-store setup remains **unverified**. |
| House policy, not an upstream score | northstar-lanes@00203275944a:docs/adr/0004-ranking-and-feeds.md, Evidence, "none exists" | The source explicitly found no upstream mover-times-volume score or earliest-stage detector; this harvest adds no mechanism. |

## Changes for Sextant
None to the score or feed picks. The newest owner source requirement (2026-11-05/06, COMMON.md) is verbatim:
> "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"
The approved plan keeps this a source-backed harvest; the broader owner scope is carried verbatim in [ADR-0002](0002-philosophy-and-lanes.md).

## Code and config to carry
Inventory only, not a deployment or calibration claim; counts measured with `git show <pin>:<path> | wc -l`.
- northstar-lanes@00203275944a:src/northstar_lanes/mover.py (306 lines); northstar-lanes@00203275944a:src/northstar_lanes/surge.py (167 lines); northstar-lanes@00203275944a:src/northstar_lanes/accumulation.py (194 lines).
- northstar-lanes@00203275944a:src/northstar_lanes/raw_accumulation.py (410 lines); northstar-lanes@00203275944a:src/northstar_lanes/classified_flow.py (346 lines); northstar-lanes@00203275944a:src/northstar_lanes/classification.py (118 lines).
- northstar-lanes@00203275944a:src/northstar_lanes/baseline.py (239 lines); northstar-lanes@00203275944a:src/northstar_lanes/contracts.py (704 lines); northstar-lanes@00203275944a:src/northstar_lanes/parameters.py (95 lines).

## Disagreements
The GPT control led with dollar volume; the owner's ruling makes move times unusual volume the pick. Both research operators remain controls. The SEC legs differ on public-before-PDS versus simultaneous delivery; neither shows a PDS lead. No purchase follows. Earlier $5/$20M ranking floors do not survive K1; entry rules have a separate home.

## Revisit when
RTH peak shadow measures capacity; the score experiment reports; paired EDGAR timing posts; the owner's Benzinga trial posts; overnight semantics are measured; a new MATERIAL feed/ranking repo appears; or a lesson contradicts this decision. Capacity/score: paper/data owner; EDGAR/overnight/new sources: research owner; purchase: owner/lead. Each changed policy returns through evidence and an amendment.
