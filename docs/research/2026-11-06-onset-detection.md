# Onset detection: source and acquisition preflight, not a study result

[#130](https://github.com/seathatflowsinourveins/sextant/issues/130), focus step 1.
Branch `onset-detection` starts at `8ccf6934cdba20d7cd30c0e99129b24026ec462f`.
The [initial plan](https://github.com/seathatflowsinourveins/sextant/issues/130#issuecomment-6692112500)
preceded all data calls. The [tick-sizing revision](https://github.com/seathatflowsinourveins/sextant/issues/130#issuecomment-6692815699)
keeps **all acquisition HOLD**. No market-data request, reserved study run, detector
admission, push or PR occurred. Historical REST only; no stream, orders or writer handover.

## Source authority

The owner's ruling is recorded in [ADR-0027](../adr/0027-extreme-gainer-research-package.md).
The zip supplies identities and dates only; none of its prices, float, ranking weights,
timing or exit ladders are study inputs. Primary references are River 0.26.1 Page-Hinkley
at `64285b9dd6c606804753235fe992bcf25b9856ee`, Adams–MacKay's
[arXiv:0710.3742v1](https://arxiv.org/abs/0710.3742v1), and the published
Zarattini–Barbon–Aziz [Stocks in Play screen](https://doi.org/10.2139/ssrn.4729284).
The author PDF's SHA-256 is
`9423012e9f0199e3f6925c500725815c236d7ddbdd7500d50d10bac2be745e91`.
Existing source cards and receipts preserve pins, licenses and deviations. K2/K3 remain
the labelled house incumbent E0, never authority over those references.

ADWIN, oracle-checked Lee–Mykland, executable-reference symmetric CUSUM, OFI and VPIN
retain the frozen follow-on sequence. BOCPD's observation model, hazard and market alarm
remain unavailable; a paper posterior or fixture grants no parameter authority.
No card receives `compute admitted` until its exact method, inputs, implementation,
parameters/deviations, #102 reservation and applicable #129 native-audit synthesis exist.
Every arm file carries `upstream checked:` or `none exists:`. Replay uses Nautilus
BacktestNode/BacktestEngine and one row-11 ParquetDataCatalog; ATR/VWAP use native features
when the audit confirms applicability. Audit syntheses were unavailable at preflight.

## Measured inventory and tick calibration

Sharadar coverage receipts yield 814 gainers and 132 selected losers, kept separate.
Input `/home/sextant/sextant-data/sharadar-42/report/events.jsonl` SHA-256:
`b830a96e0fe745d1a278a2a623fff6e0d41c9a62965be6df9c0f2b021fc4eeff`.
These are literal vendor price observations, not dated-identity or PIT acceptance.
Keep `survivor_only: true`, `pit_verified: false`, and `hindsight_selected: true`.
Selected losers are not ordinary controls; an event-only panel cannot establish
full-market ranks, recall denominators or false flags/day.

No calibration pull was needed: the old read-only SIP archive contains 2026-10-23
AAPL trades and quotes. [The observed receipt](2026-11-06-onset-tick-calibration.json)
has SHA-256 `86950c39df7f2c063ac31e1fb9715ce613c38a3290597b9c9ba7185a46205c50`.
Its source report SHA-256 is
`9f596a9389f97f68de80dbba4c2a3063150fe7e9960bf78d9d327d15ed85b671`;
the eight native files contributing rows were individually hashed. Method follows
northstar-trading@`8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`:
`src/northstar_trading/data/ticks.py` and
`docs/research/2026-10-25-tick-history-sizing.md`. Counts retain identical timestamps
and all archived conditions; no deduplication or exclusion was introduced.

| UTC window, end exclusive | Trades | Quotes | Quotes/trade |
|---|---:|---:|---:|
| PRE 12:00–12:05 | 218 | 200 | 0.917431 |
| RTH open 13:30–13:35 | 49,220 | 38,195 | 0.776006 |
| RTH midday 16:00–16:05 | 9,266 | 7,161 | 0.772825 |
| POST 20:00–20:05 | 752 | 346 | 0.460106 |

These four windows concern one liquid issuer and one day, not a microcap uncertainty
bound or overnight calibration. Full-day successful raw bodies measured 97.2572125
bytes/trade and 115.3326998 bytes/quote; native Parquet measured 13.5700797 and
8.4113840 bytes/event. These exclude receipt/instrument/catalog overhead and are not
wire-byte measurements. Old-probe throughput is not authority for today's rate.
Its `ts_init=ts_event` is synthetic replay timing, not historical arrival latency.
The pinned tick source also leaves quote-size normalization before 2025-11-03
unverified. Neither these calibration counts nor a synthetic engine clock establish
B's installed protection, broker acknowledgements, or first-second fill reachability.

## Sizing dependencies and hard stop

Official [Alpaca plans](https://docs.alpaca.markets/us/docs/about-market-data-api),
[FAQ](https://docs.alpaca.markets/us/docs/market-data-faq),
[historical trades](https://docs.alpaca.markets/us/reference/stocktrades-1) and
[historical quotes](https://docs.alpaca.markets/us/reference/stockquotes-1), read
2026-11-06: Basic lists history since 2016 and 200 calls/minute; unsubscribed SIP
historical queries must end at least 15 minutes ago. Account-specific entitlement
is untested. Request explicit SIP and event-day `asof`; limit 10,000 rows/page,
drain next-page tokens even after short pages, and respect inclusive API endpoints.

The available 117,486-row minute panel is 2026-10-26–29; the seed ends 2026-09-22.
There are zero matching event-days, which does not mean zero trades. The frozen
ordinary-control manifest and pre/post-onset tick windows are also unavailable.
Therefore full target `sum(n)`, trades, quotes, bytes, requests and wall time remain
**unavailable**. They were not filled from share volume, calendar bounds or the zip.

For each window, use its actual minute `n`. The FAQ counts volume-eligible trades:
measure `g = raw trades / sum(n)` and `r = quotes / raw trades` on matching samples.
Then estimate `T = sum(g * n)` and `Q = sum(r * g * n)`, by admitted session stratum.
The present archive lacks matching minute `n`, so g remains unavailable.
Use measured bytes/event; enumerate separate-window page lower estimates, empty
requests and metadata calls. Short pages mean `ceil(rows/10000)` is no hard bound.
Every actual attempt counts. At R requests, R/200 minutes is the ceiling-rate
duration and R/60 minutes the proposed pacer duration, before transfer/ingest costs.

The earlier coverage-only pilot proposed ACRS 2021-01-19 and SRPT 2021-01-08 plus
20 prior sessions: at most 60,480 minute rows, 42 daily rows, 160 actual requests,
128 MiB and 60/minute. These are administrative caps, not strategy calibration.
The new hold supersedes readiness: permitted acquisition requests are **zero**.
The pilot's 19:00 UTC stop is unchanged; the offline sizing checkpoint is
19:10 UTC, 2026-11-06. No acquisition deadline slides while inputs are missing.
An existing bar/control/window hand-off or explicit minute-only bootstrap release
is needed before a complete tick estimate and later acquisition plan can be posted.

## Prepared implementation and method review

`research/onset_capture.py` extends the adopted SDK transport and row-11 catalog;
it adds no detector or replacement ledger. One budget charges every attempt before
dispatch and bounds response bytes, request count, fixed deadline and memory.
Only historical bars and read-only paper calendar GETs are allowed. Retry is zero;
429, credential echo, non-200, schema/cap failure stop intake with partial coverage
explicit. Completed native partitions retain raw hashes and closed-bar clocks.
The frozen pilot cannot extend past 19:00 UTC. No live endpoint is permitted.

Before any eventual run: fetch canonical `ledger` once, validate the #102 receipt
as an ancestor, read its latest fetched tip, and require one RUNNING row matching
the exact committed implementation and configuration. An old receipt cannot reopen
an attempt closed on that tip. Only the ledger lane appends; intake is not admission.
No reservation was staged because the acquisition prerequisites are still missing.

The first bounded dsh review timed out (exit 124), so it supplies no completed leg.
A second bounded read-only preflight completed (exit 0) at
`/home/sextant/sextant-data/onset-130/method/leg-dsh-v2.md`. It reviewed supplied
source excerpts, not independently retrieved references. Its conditional coverage-only
verdict is superseded by the later hold. It rejected detector/performance admission,
highlighted outcome-selected cohorts and missing model/parameter authority, and required
fail-closed partial coverage reporting. Those findings are retained; no negative became
a passing market result. Offline proofs cover SDK pagination/caps, 429, secret echoes,
native persistence/clocks, ZIP-field exclusion and current canonical reservation state.
