# Slot-3 ranked display publisher, 2026-11-08

This serves the owner's first step: rank potential extreme movers as they start.
It is an offline implementation of the live input/output seam, with no client,
key lookup, stream opener, controller launcher or schedule. It lands after B,
with dsh and Google gates; the lead must rule on cadence before any stream opens
(lead 2026-11-08 19:10:06 EST, item 2, rank-live handoff).

## Data path and sources

The future host owns paper slot 3's **one** account-wide stream. It fans out
native TradeTicks to main's `RankingPublisher`; no consumer creates another
socket. Slot 2 is B's and refuses. `reserve_stream` uses the existing
`WriterLease`/native nonblocking flock in a distinct market-data namespace.
Every cooperating host must use the same canonical lease root and attest the
external stream count before reserving; a local lock cannot detect another
machine or an old process that ignores this protocol. No connection is made to
check it. BOATS/SIP transitions require releasing the old stream first; this
slice admits SIP PRE/RTH/POST only. Overnight is unavailable.

Reuse `ranking/{baseline,engine,publisher,reader,registry,window,generation}.py`
at Sextant `8785a07d404a1076f40f30735361e10967ca0a7e`, not another scorer.
The score remains move times own time-matched dollar-volume ratio, acceleration
as tie-break, with no price/cap floor. The complete universe and every unknown
row stay in the native generation; `top_n` projects display only. A sourced
registry, dated full common/ADR/TXSE universe, official split-adjusted completed
RTH close, prior-session baseline and complete segment-prefix/coverage receipt
must be supplied. No operating ranking registry is manufactured here.

The M2 harness at `abe84324cbe165ab0c0d9ab7853a3f110447c718`,
`research/m2_replay.py:271-440`, `research/m2_two_clocks.py:1-7,97-144,280-284`
and `research/test_m2_two_clocks.py:59-68,128-142` supplies the adapter shape and
two-clock rule. `MARKET_AVAILABLE_AT` drives availability; `ACQUIRED_AT` and the
original native `ts_init` remain provenance, even if acquired months later.
The native computation view uses market availability for `ts_init`; the supplied
tick is never changed. Future availability cannot influence an earlier cutoff.
Separate sourced price/volume masks are mandatory; G/U/Z/6/M/9 update neither
measure, following that pinned clock policy. Corrections, cancels, gaps or invalid
inputs invalidate the epoch; canonical recovery/replay needs a new publisher.

Native `snapshot_request` / `StockSnapshotRequest(feed=SIP)` describes REST snapshots. The existing
`data.alpaca_history.Pacer` provides shared minimum-spacing pacing, explicitly
configured, including every retry/page by the future transport. This module
never sends a request. Snapshots retain raw decimal fields (`vw` and `n`
included), their actual market-availability receipt and separate acquisition
clock. They are diagnostic inputs, not a complete segment prefix, an official
split-adjusted close, or extra trades/volume. In particular, `prevDailyBar.c`
does not supply an official close without independent authority.

Official Alpaca sources, all read **2026-11-08**:

- [Plans](https://docs.alpaca.markets/us/docs/about-market-data-api), Trading API
  Equities: Basic IEX/30 symbols/200 historical requests per minute; Plus
  SIP/unlimited symbols/10,000. Broker API partner quotas are a different product.
- [Streaming](https://docs.alpaca.markets/us/docs/streaming-market-data), Connection
  limit and Subscription: a second connection commonly returns 406; wildcard
  subscriptions share the same connection. House authority is one per account,
  even where the vendor permits more.
- [Stock stream](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data),
  Trades, Bars, Corrections: nanosecond timestamps and condition/tape fields;
  completed-minute bars can later be revised. Receipt is not exchange time.
- [Snapshots](https://docs.alpaca.markets/us/reference/stocksnapshots-1): multi-symbol
  comma-separated requests, explicit feed, aggregate/latest fields and 429
  handling via X-RateLimit headers. No batch-size maximum is documented there.
- alpacahq/alpaca-py@v0.44.0
  `cc4cb3b7ba50ae250e621983c2779047fb16bb28`,
  `alpaca/data/live/stock.py:17-61,63-133`, `alpaca/data/requests.py:404-419`:
  subscription callbacks/request models only; no SDK client is constructed.

Actual slot-3 entitlement, canonical deployment lease root, existing-stream stop
receipt and shared remaining REST allowance are UNKNOWN. Full-market SIP needs
positive entitlement evidence; Basic/IEX is never relabelled SIP. Use the smaller
of the sourced allocation and documented quota, account for every other REST
consumer, honor remaining/reset headers, stop on 429, then revalidate coverage.
No automatic retry or reconnect is installed here.

## Local J5 input

`LiveProducer.build_unit` validates the complete generation with main's
`GenerationReader`, including its separately supplied heartbeat. It returns one
`sextant.j5-ranked/1` document with native generation/hash, parameter hash,
nanosecond generation/input/heartbeat expiry, exact qualified members of
`NS Ranked`, rank/unknown information and input provenance. `publish_unit`
uses the existing durable atomic JSON writer. Throttling preserves the original
generation clocks; no fallback extends expiry. A refusal writes an explicit
unavailable document with `watchlists: null`, never an empty desired list.

Mappings are explicit, exact, unique and exchange-prefixed; unknown mapping
refuses the projection. The full generation retains every universe row, even
when its score is unknown or it falls outside display `top_n`. No entry-gate
filter is applied to ranked display membership. No `NS B-protected` list is
emitted: a separate authoritative B cache is required, never an account query or
an empty-list default. The old cloud `NS movers`/`NS focus` consumer is separate.

[ADR-0021:55-60](../adr/0021-tradingview-display.md) and the
[J5 lesson](tradingview-watchlists.md) govern the Windows-native Claude consumer:
fresh valid input at **each write**, current whole-run non-use, unique exact
name/numeric ID, already-active target, <=100-entry deltas with both outer
ID/name reads (also after error), by-ID read-back after every write, complete
final membership. First mismatch/error/partial write aborts the whole run;
retain confirmed changes and unknown outcomes. No selection tool or corrective
write on a stop. Membership sync does not promise rank-order sorting. Existing
J5 proofs remain the controller-policy witness; this producer never calls it.

## Registry and cadence proposal

Every ranking knob stays in main's required `Registry` (all twelve rows, explicit
source/date, UNCALIBRATED; no defaults). New rows are documented below; operational
missing authority remains unavailable. No code loads this table as a deployment
configuration. A fixture row cannot authorize a live run.

| Row | Value / bound | Source and state |
|---|---|---|
| `snapshot_requests_per_minute` | explicit allocation, >0 and <=200; no default | Alpaca Plans' lowest documented Trading API data quota; existing Pacer; UNCALIBRATED, actual shared allocation UNAVAILABLE |
| `snapshot_symbols_per_request` | caller supplies explicit nonempty symbol group; no automatic chunking | Alpaca Snapshots / native StockSnapshotRequest; operational group size UNAVAILABLE because endpoint maximum/URL capacity is undocumented |
| `top_n` | main's `top_n`, <=1,000 | main Registry and ADR-0021 list cap; UNCALIBRATED; no new value |
| `j5_sync_interval_s` | propose 300s, disabled | ADR-0026:23's 300s display-notification expiry is only a review starting scale, not a measured watchlist optimum; UNCALIBRATED proposal, no runtime row/value or schedule |
| `paper_slot` / `streams_per_account` | 3 / 1, fixed authority | lead item 2; invariants, not tuning knobs |
| `j5_bulk_entries` | <=100, controller side only | FerroxLabs/tvcontrol@v2.5.3 `85200201f92967db9e4b63a9251d51fcdfe1f3a8` `src/tools/watchlist.js:48,62`; invariant |

Propose one serialized, fresh Windows-native J5 run **no more often than every
five minutes**, and only when membership differs; skip overlaps. Do not hold a
five-minute-old ranking until the next run: capture a fresh producer document at
run entry and again before every batch; existing second-scale ranking freshness
still applies. A headless job may outlast that freshness, which must be measured
before apply. Do not lengthen input TTL to hide controller latency.

At 300s there are at most **12 Claude invocations/hour**, **78 per normal 6.5-hour
RTH session**, **192 per 16-hour PRE/RTH/POST window**, or **288 per 24-hour
display day**; the last is capacity accounting, not overnight readiness. Counts
use half-open sessions with the first run at the start, no extra close run, and
no retries. Changed-only skipping reduces these upper bounds. The lead chooses
the display interval after measurement; the trade clock remains independent.

**One actual J5 run's cost today is UNKNOWN.** No run-cost receipt is in the
repo or supplied/staged J5 handoff reports; no controller is run to fabricate
one. Let `c` be one fresh run's recorded `total_cost_usd`, `u` its per-model token
usage. For an equal-cost planning scenario this is **12c/hour, 78c/RTH session,
192c/16h, 288c/24h**, and the same multipliers of `u`. Actual cost is the sum of
individual runs, whose cache use, deltas and duration differ; `c` is not a fixed
price or a future upper bound. Real dollars and subscription quota percentage
remain UNKNOWN. For comparison 60s would be 60c/hour and 390c/RTH;
900s would be 4c/hour and 26c/RTH. These are arithmetic scenarios, not measured
Claude cost. Source: [Claude headless JSON](https://code.claude.com/docs/en/headless)
and [costs](https://code.claude.com/docs/en/costs), read 2026-11-08: JSON reports
client-estimated `total_cost_usd`/per-model breakdown, resumed conversations
include prior runs, and subscription billing differs from API-equivalent cost.
Obtain the current Windows J5 fresh-run receipt (or difference of resumed totals),
model/effort, tokens/cache use and elapsed time before the lead's cadence ruling.

Lesson: a valid native rank does not prove full-market entitlement, stream
ownership, a fresh Windows apply, rank order in a watchlist or an economic edge.
Mechanical proofs here grant none of those acceptances.

## Verified carry and consolidation

The 19:21:44 EST lead pivot governs this adaptation: reuse ea95075, carry onto
4655276 and aim for <=300 added source lines. The original producer is recorded
in history before consolidation; no parallel fresh publisher remains.

| Receipt | Value |
|---|---|
| Original producer / base | `ea95075450452bdb02ceb16fdb6625f06848d5ef` / `b65b41e36fe2c5b83e0a0c8b7347d91be74fed9a` |
| Main / normalized carry | `4655276269a49a0731064eb74edd8edfca396751` / `788df62b346955ff713cd75ac804a9f6bacd9bdf` |
| Original = carried stable `-U0` patch ID | `069fd78866a85c186ae8678087adbab9b97f6fb5` |
| Independent index overlay = carried tree | `ef3a8962c06459afad217cae5724f1e04dc8ee65` |

The raw clean rebase matched `git merge-tree` but the manifest union driver
duplicated two neighboring rows. Normalizing only those duplicates recovered
the exact original patch ID. The independent overlay applies the original
patch to a temporary main index, preserving main's manifest plus the two
original new rows. Original targeted proofs passed: **83 passed**. Complete
patches, raw and normalized receipts are in the rank-live scratch/carry handoff.

The carried 835 source lines (298 display_lists + 107 display_support + 430
producer) become one 299-line `tradingview/producer.py`, including the live seam:
**-536 versus the carry, +299 versus main**. Scoring, sorting, baseline curves,
coverage/source/feature validation and generation identity delegate to main;
clock interpretation follows M2. Native `WriterLease`, `Pacer`, SDK request
models, qualified-symbol grammar and durable `write_atomic` replace private
implementations. No B file or size guard changes.

The unlanded branch's 50+50 extreme screen, pressure/armed-list assembler,
fixed-time session classifier, alternate potential/2 admission, multi-file
serializer and CLI are retired. They are not needed to display main's ranking
under J5, and its ranking flags do not establish pressure absence or supply
share RVOL. The new document does not pretend to be the legacy cloud
`ns-display-lists/1` contract: the existing cloud consumer and all its proofs
remain untouched. The two branch-only pure-projection test files are retired
with those APIs; producer proofs are adapted to the real ranker/reader, complete
generation hash, two clocks, bounded snapshots, atomic failure and refusals.
J5's controller-policy proofs remain unchanged.
