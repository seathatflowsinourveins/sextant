# Slot-3 ranked display publisher, 2026-11-08

This serves the owner's first step: rank potential extreme movers as they start.
It is an offline implementation of the live input/output seam, with no client,
key lookup, stream opener, controller launcher or running schedule. The gate
branch's `ci`, `source` and `review` policy governs this port; it merges only
after the budget PR #27. The 2026-11-09 TV-LOOP ruling starts the owner-consented
loop and ships the cadence registry `enabled=1` in the same reviewed PR; the
change takes effect at the next session boundary (ADR-0018). Stream opening, B's
feed check and explicit lead enablement of the Windows controller remain
separate (lead 2026-11-08 19:10:06, 19:21:44 and 19:49:24 EST, rank-live
handoff; LEAD-1219-tv-pr3-skills.md, SHA-256
`045f4b2e01128f3e5db21acef340f451451cca4a99994f4fb69287659de266a1`).

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

## Registry and owner-consented loop

Every ranking knob stays in main's required `Registry` (all twelve rows, explicit
source/date, UNCALIBRATED; no defaults). The shipped operational rows live in
[`k2-ranking.params.json`](../../lanes/tradingview/k2-ranking.params.json): the
eight mover/publication values and `top_n` are pinned, and the DISPLAY
deployment ages take the display registry's sourced freshness bounds
(`input_max_age_s` 600, `generation_max_age_s` 1200, `heartbeat_max_age_s`
1200; see [the display parameter registry](../tradingview.md#display-parameter-registry)),
so an operational display `Registry` builds from the file. The trading/entry
deployment's ages stay UNAVAILABLE until sourced. The explicit snapshot allocation remains
`snapshot_requests_per_minute` (>0 and <=200, no default; source: Alpaca's lowest
documented data quota and native Pacer). Symbol groups are explicit inputs with
no default size or undocumented maximum. `top_n` remains main's row, bounded by
ADR-0021's 1,000-name limit. Fixed authorities are slot 3, one stream, and J5
batches <=100. Missing operational authority stays unavailable.

The owner replaced the five-minute proposal in lead **2026-11-08 19:49:24 EST,
item 1** (`LEAD-1949-cadence.md`, SHA-256
`3d6cfe285839d122b2637f928ea26976e5ed821f1e41209818bcc8b041aecab6`).
`cadence.py` is an offline admission gate, with no timer, worker, controller,
network call, credential access or alternative J5 client. The shipped
[`j5-cadence.params.json`](../../lanes/tradingview/j5-cadence.params.json) is the
runtime registry. Every row has its unit, value, source, date and UNCALIBRATED
state. There are no missing-value or fixture defaults.

| Registry row | Shipped value | Meaning |
|---|---|---|
| `enabled` | 1 | Enabled by the 2026-11-09 TV-LOOP ruling; effective at the next session boundary. A remaining `0` copy refuses before any state or page |
| `changed_only` | 1 | Compare exact sets with complete confirmed read-back, ignoring rank/order/score |
| `max_concurrent_runs` | 1 | Serialized admission and a durable active-run receipt |
| `max_retries` | 0 | Failed/abandoned runs latch; no retry or automatic recovery |
| `overnight_enabled` | 0 | Wait for Paper B's overnight-feed check, then reviewed policy change |
| `onset_floor_s` | 150 | 07:00–10:30 and 15:00–16:00 ET, start-inclusive/end-exclusive |
| `regular_floor_s` | 300 | Other times within 04:00–20:00 ET |
| `usage_floor_s` | 900 | Higher floor when weekly Claude usage passes 80% |
| `weekly_usage_backoff_pct` | 80 | Strictly greater; exactly 80% retains the ordinary floor |
| `display_start_minute_et` / `display_end_minute_et` | 240 / 1200 | 04:00 / 20:00 ET |
| `am_start_minute_et` / `am_end_minute_et` | 420 / 630 | 07:00 / 10:30 ET |
| `pm_start_minute_et` / `pm_end_minute_et` | 900 / 960 | 15:00 / 16:00 ET |

The ET conversion and trading-date check reuse `tradingview.inputs.ET/_session`;
UTC offsets and DST are not guessed. Elapsed time is counted from the previous
run's start against the floor at the current decision time. Unknown/nonfinite
weekly usage or a missing source receipt refuses admission. A current high-usage
receipt emits the injected owner-page callback once per crossing, even when
membership is unchanged or rank data is unavailable. The high flag persists
across restarts; a failed page latches admission and leaves `page_pending`.

Call `Cadence.claim` with a fresh producer unit, aware supplied clock and sourced
Windows weekly-use percentage. Shipped `enabled=1` is the reviewed between-session
change after landing; a copy still carrying `0` refuses before any state or page.
The caller attests those receipts; this offline gate cannot verify remote landing
or the lead's identity. `--loop` supplies the landed SHA from its own checkout,
the enabled row's source as the enable receipt, and a complete by-ID membership
read-back for the initial comparison; unknown inventory never authorizes a clear
or a first-run guess.

Every cooperating J5 admission process uses the same canonical state root.
Native `WriterLease` serializes read/claim/finish, and `write_atomic` durably binds
the active run, last start, confirmed membership, usage crossing and parameter
hash. A second process observes the active receipt and refuses, even after a
crash. Failed or abandoned runs need reviewed read-back/reconciliation; no
automatic reset, catch-up queue, overlap or retry is provided. A registry change
with existing state requires reviewed migration. This local protocol cannot
exclude an external host or controller that ignores it; existing Windows J5
single-controller/allowlist/non-use gates remain required.

## Owner-consented loop

`tradingview/loop.py --loop` starts the process that consumes the admission gate.
It preflights the registry, landed SHA and enable source without opening a
session, opens exactly one `official_client` consent context, and performs one
complete by-ID read-back before the first compare. No unit is pre-read before
consent.

Each tick sleeps to the current floor, rereads `--research-dir` (the newest
complete display unit; a symlinked `latest` may be atomically replaced), reads
the two explicit memberships into a display-admission view, and calls
`Cadence.claim`. Only an admitted run calls `sync_research(apply=True)`; a
verified `applied` result with both read-back keys calls `finish(successful=True)`
with the operation count and read-back sizes as its receipt. A refused or stale
unit never becomes an empty desired list: it leaves both lists unchanged and
pages once per distinct episode. The page is written straight to stderr
because the OAuth redaction guard disables `logging` for the consent session,
so an ERROR record would be dropped. A sync failure finishes the run as failed,
latching the same no-retry policy, and stops the process. The loop exits at the
20:00 ET display close rather than holding OAuth across the closed window, and it
has no catch-up queue.

The admission comparison is the observed pair `NS movers` and `NS focus`, not
their union: a name that moves between lists changes both sets even when the
union is unchanged, and it must sync. The window and floors come only from the
registry; the loop adds no timer, service, alternate transport or second client.
`--weekly-usage-pct`/`--usage-source` let a caller supply the Windows controller's
sourced number; when unset, the default is zero with a source stating that this
process has no Claude surface, so the 900s branch is not exercised. The default
state root is `~/sextant-data/tradingview-j5`; every cooperating process must use
the same canonical root. A restart refuses state that holds an active, failed or
page-pending run, or that was written by another reviewed registry, before it
opens a new consent session; the reviewed reconciliation or migration must finish
first.

Only an admitted `run_id` may be handed to the existing Windows-native Claude
controller after enablement. The loop spends its admitted run on the no-LLM cloud
MCP sync itself; that separate controller path still has no launcher here. The
controller must still validate fresh input before **each** batch under ADR-0021;
the cadence does not extend second-scale producer expiry. `finish` accepts only
the matching outcome/read-back receipt. Unknown completion keeps the active
receipt blocked.

The recorded first-session measurement is **`first_session_j5_run_time_ns`**:
UTC receipt end minus admitted start for the first completed J5 run, including
a failed completion, with `first_session_date` and `run_receipt_source`. Later
runs record `last_j5_run_time_ns` without replacing the first measurement. It is
**null in the shipped registry**, and no J5 measurement is made in this turn.
All witness durations are labelled synthetic fixture clocks. In the first
enabled session the real Windows result supplies both timestamps and its receipt;
record controller model/effort, tokens/cache use and `total_cost_usd` alongside it.

Capacity accounting before changed-only skipping, runtime or back-off: up to
24 runs/hour during onset windows, 12/hour otherwise; a normal 6.5-hour RTH
session has an upper-bound scenario of 102 runs, and a 16-hour 04:00–20:00 day
246. At the 900s floor the scenarios are 4/hour, 26/RTH and 64/16h. These are
invocation scenarios, not measured Claude cost. For equal-cost runs at `c` USD
and `u` tokens each, multiply the counts by `c` and `u`; actual spend is the sum
of individual runs. One actual J5 run's current USD cost, tokens, duration and
subscription usage remain UNKNOWN. [Claude headless JSON](https://code.claude.com/docs/en/headless)
and [costs](https://code.claude.com/docs/en/costs), read 2026-11-08, identify the
client-estimated cost/model fields, cumulative resumed totals and subscription
distinction. No new controller run is authorized to obtain them here.

## Contract-first acceptance

Per the lead's 19:47:09 contract-first practice, `test_j5_cadence.py` and the
body's named acceptance checks were written before cadence code/config. All 43
initial cases were RED for the absent implementation, then GREEN. A separate
RED witness caught paging suppressed by unavailable rank data; moving usage
handling before rank admission fixed it. Full RED/GREEN logs are in the handoff.
Witnesses cover every owner rule, minute/second boundaries, Eastern DST/XNYS,
restart and cross-process serialization, failed/abandoned runs, strict usage
threshold/paging, missing authority, and synthetic first-session receipt timing.
No test under `tests/repo` is edited; the no-LLM client research remains separate.
The 2026-11-09 TV-LOOP tests were RED first for the absent loop and two-list
admission, then GREEN against the real SDK seam. They cover the startup
read-back, one sync per admission, unchanged-member skip, a cross-list move with
an unchanged union, stale-page-once with no write, the failed-apply latch, the
20:00 ET exit and CLI wiring.

Lesson: a membership retry is not a new change; keep the active/failed receipt
through restarts. Cadence acceptance needs clocked controller receipts and
weekly-use provenance, while display freshness remains independent.

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
producer) became one 299-line `tradingview/producer.py` at `29d2cd4`, including the live
seam: **-536 versus the carry, +299 versus main before the cadence follow-up**.
The cadence follow-up adds a 290-line admission module: **+589 versus main,
+290 this turn, -246 versus the original carry**. Total source is 16,718 under
the unchanged <20,800 guard; the combined post-B tree still needs checking. Scoring,
sorting, baseline curves,
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

## Gate port receipt, 2026-11-09

The T1 ruling carries the four source commits in order: `788df62b346955ff713cd75ac804a9f6bacd9bdf`,
`29d2cd4a327ca4c0d33c47a6e213e210d9909674`, `506639935de0da6eb8bcbe1ba0b758dcfd6bf518`
and `7f353a5420e5dbce67990bb3376ce0bee3460a5b`. Against gate
`6db8dae20ab930c1511d5e1a4e0000fe4f9b717b`, the implementation, registry and
proofs match that final source exactly. No source conflict needed a design choice.
The manifest retains every gate row and adds only the three rank-live rows.
Gate's instructions, review rules, workflows and size tests remain unchanged.

Measured Python source is **16,129 + 589 = 16,718 lines**, below gate's cap of
**21,550**. The +589 is the 299-line producer plus 290-line cadence module;
there is no new dependency, scorer, controller or running service. The earlier
<20,800 receipt above describes the original carry, not gate's current cap.

Lesson: a source carry does not carry its old landing policy. Preserve the
target branch's rules and manifest union, compare the implementation to its
pin, and measure against the target's actual size guard before handoff
(`6db8dae20ab930c1511d5e1a4e0000fe4f9b717b`:
`docs/handbook/practices.md`, Harness; `tests/proofs/test_manifest_union.py`).
The owner has unblocked live ranking; rollout starts when B is ready, under the
trading lead's six-step rollout. This port enables the cadence (`enabled=1`) for
the owner-consented loop only, keeps overnight OFF and all display-only
boundaries, and performs no rollout or controller apply.
