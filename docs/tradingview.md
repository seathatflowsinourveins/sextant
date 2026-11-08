# TradingView display sync

Issue [#52](https://github.com/seathatflowsinourveins/sextant/issues/52),
[ADR-0021](adr/0021-tradingview-display.md) and
[ADR-0026](adr/0026-tradingview-sync-and-order-presets.md) govern this slice.
It supplies no universe selection, machine signal, market feed or order path.

## Source and scope

The membership adapter follows
`seathatflowsinourveins/northstar-trading@paper
8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`:
`src/northstar_trading/tradingview/{research,sync,contracts,auth,auth_safety}.py`,
`scanner/{display_lists,timestamps,sessions}.py`, `sessions.py`,
`tests/tradingview/{test_sync,test_readback_verify}.py` and
`docs/tradingview/presets/*.pine`. The four Pine files retain every upstream
formula byte; only the `indicator()` title changes to its dated immutable ID.
Their manifest records both the original and packaged SHA-256. Runtime receipts
verify both: replace the first dated title with `upstream_title` in the source
bytes, then compare that digest to `upstream_sha256`, not just the packaged hash.
The overlapping-session logging guard adopts `auth_safety.py:sensitive_logging`
from that same pin: a lock/count restores the original logging policy only when
the final user exits, including cancellation and session cleanup.

Timestamp arithmetic delegates to NautilusTrader rc8 at
`d53849b216e20f2c122ca01b4dd0da377638b186`,
`python/nautilus_trader/core/datetime.py:_datetime_to_unix_nanos`.
This pinned private helper preserves the bridge's full Python datetime range;
the public parser uses pandas' narrower nanosecond range. Wire syntax, explicit
timezone and fractional-nanosecond checks remain the producer contract.
Literal witnesses cover both range boundaries, offsets and nanosecond rounding;
the helper's availability and behavior must be rechecked on a pin upgrade.

MCP uses `modelcontextprotocol/python-sdk@v2.3.0
2118f14f8a19bc158d8a1cf90af58d85d187f849`,
`docs_src/oauth_clients/tutorial001.py` and `docs/client/index.md`.
Its `docs/troubleshooting.md` explains that `Client` task groups wrap body
exceptions: catch trusted `SyncError` inside, close normally, then re-raise the
same error outside. Unknown failures remain sanitized. `docs/advanced/pagination.md`
supplies the low-level paginated `Server` fixture; discovery pages and the first
following tool request share the same serialized 0.75s limiter.
Calendar attribution follows `gerrymanoim/exchange_calendars@4.13.2
dbe38b1f6887434bbdd1a7d2df6ff8f1742a048a` and the upstream scanner's
20:00–04:00 ET BOATS trade-date rule. It reads no market data.
`mcp==2.3.0`, `httpx2==2.16.0`, `jsonschema==4.26.0` and
`exchange-calendars==4.13.2` retain the upstream optional dependency pins.

Official sources read 2026-11-06:

- [TradingView MCP](https://www.tradingview.com/mcp/docs): official endpoint,
  OAuth 2.1, Streamable HTTP, Essential+ non-trial, batch watchlist operations
  and approximately 100 calls/minute/user. Existing members move to the end
  when added, so only missing members are added.
- [Pine higher-timeframe data](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/):
  confirmed values use an expression offset with `barmerge.lookahead_on`.
- [Pine repainting](https://www.tradingview.com/pine-script-docs/concepts/repainting/):
  the prior completed higher-timeframe value avoids unconfirmed HTF updates.

Boundary sources read 2026-11-07:

- [RFC 3339 §5.6](https://www.rfc-editor.org/rfc/rfc3339#section-5.6): offset
  hours are 00–23 and minutes 00–59; reject malformed offsets before Python can
  normalize them. Existing producer compact offsets and space separators remain
  supported; this is not a claim of strict RFC 3339 syntax in every field.
- [Python 3.13 dates](https://docs.python.org/3.13/library/datetime.html#datetime.date):
  unsupported calendar bounds raise `ValueError`; translate it to `InputError`
  before OAuth, with no fabricated calendar or clamped date.
- [Python 3.13 SHA-256](https://docs.python.org/3.13/library/hashlib.html#usage):
  hash the packaged and title-normalized bytes for the local receipt. Receipt
  failures have a fixed, nonzero local diagnostic, not a session/write warning.

The sync implements the source's `ns-display-lists/1` consumer. The offline
producer below adapts an existing Sextant ranking; it does not run another
ranker. Legacy generations without `display-lists.json` refuse.
The deployment-manifest/search mode, position notifications, rendering and
Desktop controllers are outside #52's membership/preset slice.

## Offline and owner commands

```sh
uv sync --frozen --extra tradingview
uv run --frozen python -m sextant.tradingview --presets lanes/tradingview/presets
timeout 180 uv run --frozen pytest tests/proofs/test_tradingview.py
```

The first two commands install the lock and print **local artifact receipts**.
They do not certify a Pine compile, save, study binding or Desktop installation.
The tests use the real official SDK with an in-memory MCP peer; no account,
service, browser, broker or Desktop debug-port connection is made.

The following commands are owner-session steps, **not run by this worker**:

```sh
uv run --frozen python -m sextant.tradingview --research-dir /path/to/top100/latest --authorize
uv run --frozen python -m sextant.tradingview --research-dir /path/to/top100/latest --authorize --apply
```

Each process requires explicit owner consent in the browser. It uses only the
official `https://mcp.tradingview.com/mcp` endpoint and an ephemeral loopback
OAuth callback. Tokens and client registration stay in RAM and clear at exit;
there is no persistence flag or file/keychain/environment credential fallback.
The owner must ensure only one sync process runs at a time: there is no
cross-process lock, and concurrent processes are unsupported. The in-process
limiter and logging guard do not confer cross-process ownership. Run it on the
display schedule, independently of the trade clock; no unattended service is installed.

Input is one resolved producer unit: `top100.json` (`morning-pack.candidates/1`),
`focus.json` (`top100.focus/1`) and `display-lists.json` (`ns-display-lists/1`).
All three must share clocks, session date, snapshot hash and generation labels.
Comparisons retain nanoseconds. The display producer owns membership and
ranking; focus can include armed names outside movers. No score or account
payload goes to TradingView. Missing/stale/invalid input never clears a list.

A dry run plans membership changes but reports `applied: false`. Apply
preflights every operation against discovered schemas, serializes calls,
rechecks expiry after pacing and reads back both lists. It omits at most five
unmapped names, tolerates at most five distinct rejected names without retry,
and removes unexpected storage once before rereading. A remaining mismatch,
quota error, ambiguous mutation or unknown envelope stops. Earlier writes may
have succeeded: re-inventory before another plan; there is no automatic
mutation replay or rollback. A refused/dry run records no successful-sync time.

## Offline ranking-to-display producer

`src/sextant/tradingview/producer.py` is a file-only adapter, not a feed,
scheduler, strategy or ticket writer. It carries
`scanner/display_lists.py` and the applicable pure projection tests from
northstar-trading@`8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`.
The contract is separately pinned at
`d957d8e9a791f470b6085861a10726dd939bdea1`:
`docs/research/2026-11-02-ns-display-lists-contract.md:19-55`. It is **not an
ancestor** of the carry pin; that file is absent at the carry pin. The
`-implementation.md` evidence is at the carry pin, not the contract pin.
The lead authorized these two distinct source pins (2026-11-08,
`msg_e200b1ba2777`).

The module is unchanged except imports and the lead's exact method-guard
ruling (`msg_dca669a359c1`): only `potential/2` and
`MOVER-v2@00203275944a22655b3e14b221cfde9a265d549a` pass both guards.
The ruling called them lines 65/174; the actual upstream predicates are at
62/168. No wildcard, prefix, score rewrite or method relabeling is allowed.
`display_support.py` extracts only the needed flags, Decimal parser,
exchange mapping/qualification, phase and timestamp helpers; it does not
import the 4.4k-line upstream `top100.py`. Qualification retains upstream
`tradingview/inputs.py:ticker` semantics: strip only a known engine venue
suffix, preserve share-class dots, never trim/case-correct a symbol.
Timestamp parsing reuses the existing exact rc8 bridge described above.

```sh
UV_OFFLINE=1 uv run --frozen python -m sextant.tradingview.producer \
  --ranking /path/to/full-ranking-generation.json \
  --symbol-map /path/to/verified-symbol-map.json \
  --out /path/to/research
```

`--ranking` is the full canonical `RankingGeneration` JSON (schema version
2), not a top-N file, receipt summary, catalog of bars or legacy snapshot.
`--symbol-map` is an explicit verified object such as
`{"AAPL":"NASDAQ:AAPL"}`; no broker/routing venue supplies listing identity.
Without enough mappings, the consumer refuses publication rather than
inventing exchanges. `--generated-at` is an optional aware replay clock;
ordinary use records current UTC. Success prints each list's count,
`as_of` and `generated_at`; unavailable input prints a reason and exits 2.
The CLI never searches catalogs, reads keys, connects to a broker/TradingView,
or discovers journals. The Python API alone accepts explicitly captured
`ArmedSet` journal text under the carried validation rules.

### Field provenance

Paths in the northstar column are relative to `src/northstar_trading/` at
the carry pin above, except the separately pinned contract. Sextant paths
are relative to `src/sextant/` at this branch's base
`b65b41e36fe2c5b83e0a0c8b7347d91be74fed9a`.

| Output fields | Sextant source and mapping | Northstar definition |
|---|---|---|
| `schema`, `snapshot_status`, `status`, `empty_top100`, `boundary`, `sizing` | Candidate/focus/display schema names; only a verified complete fresh generation is `observed/fresh`; nonempty ranking required; `risk_usd` remains `OWNER INPUT`; display-only boundary | `scanner/top100.py:4057-4082,4110-4121`, `validate_candidate_contract`; `top100_focus.py:650-674`; `display_lists.py:231-252`; `docs/tradingview/README.md:146-170` |
| `session_date`, `as_of_snapshot`, `as_of`, `generated_at` | `ranking/generation.py:RankingGeneration.session_date/input_cutoff`; cutoff retains integer nanoseconds; both publication clocks use the explicit producer clock. Snapshot `generated_at` retains `ts_init` | `scanner/top100.py:4057-4062`; `top100_focus.py:651-657`; `display_lists.py:165-176,231-241` |
| `generation`, `sources.snapshot`, frozen inputs | SHA-256 of canonical `inputs/display-snapshot.json` plus exact cutoff. Snapshot's `ranking_generation_sha256` binds **all** canonical `inputs/ranking.json` rows, including unranked ones, via `ranking/generation.py:canonical_bytes/generation_digest` | `display_lists.py:165-176,240-249`; contract's one-generation rule; `scanner/top100_schedule.py:848-910` freezes/hashes complete input |
| `symbol`, `rank`, `score`, `adjusted_rank`, `adjusted_score`, `ranking_policy` | Preserve `RankingRow` identity, order, Decimal score and rank without new adjustments; retain actual method/profile/ranker versions. `potential2_rank/score` are null for MOVER, never relabeled | `scanner/top100.py:3853-3873,4086-4109`; `display_lists.py:_rows`; Sextant `ranking/publisher.py:256-284` |
| `tradingview_symbol`, `tradingview_symbol_source`, snapshot `exchange` | Only caller's explicit verified map qualifies a symbol (`symbol_map`); snapshot exchange stays null. No `instrument_id`/ALPACA suffix supplies a primary listing exchange | `scanner/top100.py:112-127,2517-2543,3862-3863`; Sextant publisher does not populate `RankingRow.instrument_id` |
| Snapshot `coverage.security_type` | Clocked, unexpired `ASSET` reason from `ranking/publisher.py:AssetState,181-185`; `common` maps to `common_stock`, ADR remains ADR, missing subtype remains null | `display_lists.py:70-73`; `scanner/potential2.py:1092` string subtype; contract also permits nested `.type` |
| Snapshot `inputs.price/previous_close/rvol`, `ranking_features`; candidate `price/price_status`, `signals` | Exact named, completed, clocked `RankingFeature` values as Decimal text. Publisher's `price` exists; `previous_close` and share `rvol` do not. Only explicit features of those names fill them; `dvol_ratio` is **not** share RVOL. Gap signal stays null | `scanner/top100.py:3876-3898`; `display_lists.py:190-204` requires price, previous close and RVOL; Sextant `ranking/publisher.py:240-255` |
| `sell_pressure_flags`, `adjustment_terms`, `daily_metrics`, `catalyst_refs`, `score_breakdown`, `b_account_notes`, `ticket` | All six pressure flags and adjustment terms `UNVERIFIED`; points/ATR22/high60/breakdown/ticket null; refs/notes empty, not negative evidence. No sizing, allocation, account read or new score | `scanner/top100.py:92-99,3853-3928`, `validate_candidate_contract`; unknown-evidence policy at 4102-4108 |
| Focus `rule`, `candidates`, `excluded`, `tradingview_watchlist` | Conservative strict projection: all top candidates excluded as `unverified_sell_pressure`; empty focus and empty watchlist. `focus_eligible` proves no absence of pressure | `scanner/top100_focus.py:338-362,650-734` |
| `ranking_context`, `research_inputs`, `ranking_source` | Preserve single identical per-row `SOURCE` reason from `ranking/publisher.py:161-175`, cutoff, full-generation hash and explicit map. Intraday feed is SIP or BOATS by phase; daily SIP history is labeled `UNVERIFIED`, not supplied | `display_lists.py:234-238`; `scanner/top100_inputs.py:68-76` (`overnight_context`); `scanner/sessions.py:scanner_session`; `docs/tradingview/README.md:166-174` |
| `ns_movers`, `ns_focus`, labels/counts/bounds/armed sources | Carried projection: first 50 eligible common/ADR rows plus up to 50 full-snapshot extremes, deduplicated; focus unions valid captured armed sets and focus candidates. Unknown pressure remains labeled; unknown extreme inputs counted, not zero-filled | `display_lists.py:107-149,152-252`; separately pinned display contract |

A full-universe hash, complete READY coverage/counts, exact method, single
source identity, sourced segment/session and nonfuture input/feature clocks
are checked before mapping. An empty ranking or empty mapped movers cannot
replace `latest`; a valid empty focus can. This is not the ranking entry
gate: no heartbeat, execution qualification, rescoring or broker authority
is fabricated. The source ranking remains the authority for its scores.

### Publication and test applicability

Following `scanner/top100_focus.py:794-909`, publication writes fresh exclusive
files in `.generations/<session>-<unique>/`, fsyncs the files/directories,
and calls the existing complete-unit consumer before atomically replacing
`latest` with a relative symlink. Older cutoffs refuse; previous units are
never modified. A failed attempt may leave an unadvertised directory for
audit, but cannot expose a partial unit through `latest`. No `last_valid`
fallback or multi-writer locking is added; one writer per output root is
required. The consumer resolves `latest` once. Its datetime-only validation
clock is ceiled to microseconds, never floored; all wire clocks and exact
source/freshness comparisons retain nanoseconds. At the expiry boundary
this may conservatively refuse less than 1 microsecond early, never admit
future evidence.

The carry retains 18 byte-identical test/helper function bodies, yielding
24 upstream pure-projection cases. Eight scanner tests are inapplicable
without the uncarried scheduler/compression stack:
`test_schedule_writes_atomically_from_the_frozen_snapshot_and_not_current_source`,
`test_display_failure_preserves_top100_unit`,
`test_stale_schedule_unit_includes_stale_display_without_last_valid_reuse`,
`test_schedule_cli_passes_explicit_registered_bounds_and_arm_paths`,
`test_schedule_composed_handover_hashes_the_same_complete_rows`,
`test_schedule_display_hashes_logical_bytes_after_frozen_input_compression`,
`test_overnight_display_compresses_composed_bytes_and_keeps_readers_compatible`,
and `test_overnight_display_compression_failure_preserves_ranking`.
The upstream `tests/tradingview/test_display_lists.py` targets a different
two-path reader signature, legacy fallback, mapping injection and full
scheduler contract. It is not import/path-only compatible with Sextant's
preexisting complete-unit/no-fallback reader and is not carried. Existing
`test_tradingview.py` covers that reader's generation, clocks, omissions,
refusals and outside-movers focus; new `test_tradingview_producer.py` tests
the real Sextant publisher through file publication and the existing reader,
including all five write-failure boundaries and full-universe binding.

## Display parameter registry

These are sourced starting values, not calibrated trading parameters or
evidence of an economic benefit. Manual owner inputs stay unknown when unset.
All source paths below are at the northstar-trading pin above and in ADR-0021/26.

| Parameter | Value / bound | Authority |
|---|---|---|
| Research freshness | 1,200s; override 1–3,600s; age equal to limit refuses | `research.py:read_research_inputs/_envelope` |
| Snapshot lag | ≤600s | `research.py:_envelope` |
| Producer snapshot freshness | <600s at publication; equality refuses | `scanner/top100.py:4076-4080`; existing consumer's strict age boundary |
| Display early/extreme slots | first 50 eligible ranks + up to 50 extremes, deduplicated, ≤100 movers | `scanner/display_lists.py:183-216` |
| Extreme bounds | move ≥0.05 (5%); explicit share RVOL ≥2; no producer override | `scanner/display_lists.py:GAP_BOUND/RVOL_BOUND`; contract §NS movers |
| Captured armed-set age | ≤600s, nonfuture; last current matching refresh only | `scanner/display_lists.py:107-149,MAX_AGE_S`; contract §NS focus |
| Unmapped / rejected names | ≤5 distinct in each budget across the pair | `research.py:MAX_UNCONFIRMED_RESEARCH/verify_readback_sync` |
| Parent / movers size | ≤100; mapped movers nonempty; focus has no subset veto | `research.py:_candidates/_display_inputs` |
| Tool spacing / discovery | 0.75s, below documented ~100/min; ≤100 discovery pages | `sync.py:OfficialTools` |
| Owner callback / HTTP timeouts | callback 300s; poll 1s; HTTP 30s/read 60s | `auth.py:OwnerCallback/_official_client` |
| EMA | 10/30; first-close seed; confirmed closes; optional reset time | `presets/ema_cross.pine` |
| Hurst / flow proxy | 128 returns, R/S lags 4/8/16/32; flow 50 bars; thresholds .55/.50/.30 | `presets/hurst_vpin.pine` |
| Manual quote sizes | larger strictly >100; smaller/larger strictly <.2; zero means unknown | `presets/quote_imbalance.pine` |
| Exit C5 | completed 5-minute Wilder ATR22 ×3; tightens only | `presets/exit_levels.pine` |
| R / cost display | max(entry−OR low, 10% prior daily ATR14, 3×spread); 6bps total RT cost; lock strictly above BE | `presets/exit_levels.pine` |
| Opening range / horizon | five confirmed 09:30–09:34 ET minutes; lines start 09:35; path ends 15:55 | `presets/exit_levels.pine` |

The producer's display bounds (gap/RVOL/armed freshness) are validated as
metadata and never applied or retuned by this consumer. There is no new
top-20 fallback without a measured cap. No trial or backtest was performed for
these display artifacts; Pine formula paths are not fills or bot parity.

## Owner acceptance still required

The reviewed IDs are `NS 2026-11-06 · ema_cross`, `NS 2026-11-06 · hurst_vpin`,
`NS 2026-11-06 · quote_imbalance` and `NS 2026-11-06 · exit_levels`.
With a clean editor and no ambiguous/unsaved work, create each as a **new**
immutable script; do not overwrite, rename or delete owner scripts. Read back
its saved ID, source hash, compiler result, study binding and inputs; reopen
and check persistence and unchanged unrelated inventories. Record chart type,
1-minute timeframe, feed/session, seed and entry inputs. Confirm completed C5,
provisional R when spread is unset and opening-range availability, then restore
the owner's layout by numeric ID. Stop acceptance on ambiguity or missing proof.
Indicator-preset automation remains failed historically; owner-manual Pine
application is the fallback. No Desktop access is authorized on this distro.

Broker order presets remain owner-manual. Managed-paper tickets use plain
LIMIT, no attached bracket; outside RTH follow the broker's session rules.
`NS ALPACA DAY LIMIT BRACKET` / `NS IBKR DAY LIMIT BRACKET` are historical
owner-managed presets, with illustrative TP/SL placeholders, not manager exit
policy. Quantity/risk persistence, account translation, fill visibility,
production list capacity, official result envelopes and session persistence
have not been accepted here. No paper handover or order action follows.
