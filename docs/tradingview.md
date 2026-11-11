# TradingView display sync

Issue [#52](https://github.com/seathatflowsinourveins/sextant-archive/issues/52),
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
  when added, so only missing members are added. Re-read 2026-11-09;
  the expanded inventory does not widen the membership adapter below.
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

This implements the source's `ns-display-lists/1` consumer, not a second
ranking/focus producer. Legacy generations without `display-lists.json` refuse.
The deployment-manifest/search mode, position notifications, rendering and
Desktop controllers are outside #52's membership/preset slice.

## Official MCP drift fence

The [official MCP documentation](https://www.tradingview.com/mcp/docs), read
2026-11-09, lists **35 tools** across the nine categories below. This is a
dated documentation inventory, not a hosted `tools/list` or deployment receipt.
The service rolls independently; re-read its documentation on every TradingView PR.

Only `list_watchlists`, `get_watchlist`, `create_watchlist`, `add_to_watchlist`
and `remove_from_watchlist` are admitted by `OfficialTools`. Discovery accepts
their bare names and existing `mcp-watchlist-...` aliases, ignores unknown names
and requires exactly one identity for each admitted operation. Every call must
still pass the operation's argument-key fence and discovered JSON Schema.
Discovery is capability inventory, not authority to use new tools.

| Category | Documented count | Not admitted by the membership adapter |
|---|---|---|
| Watchlists | 8 | `get_active_watchlist`, `delete_watchlist`, `update_watchlist` |
| Market data | 3 | `get_ohlcv`, `get_economic_data`, `get_economic_symbols` |
| Search | 1 | `search_symbols` |
| Screener | 5 | `get_symbol_data`, `run_screener`, `get_symbol_data_batch`, `get_screener_columns`, `get_technicals_rating` |
| News | 2 | `get_news`, `get_news_story` |
| Fundamentals | 3 | `get_forecasts`, `get_financials`, `get_financial_history` |
| Documents | 2 | `get_documents`, `get_document_view` |
| Calendars | 3 | `get_earnings_calendar`, `get_economic_calendar`, `get_dividends_calendar` |
| Alerts | 8 | `create_alert`, `update_alert`, `delete_alert`, `stop_alerts`, `restart_alerts`, `list_alerts`, `get_alerts`, `get_alerts_log` |

`get_active_watchlist` can create or activate a list, so it is not an admitted
read. The inventory lists no broker or order tool; any future such tool is
nevertheless refused by name. The historical notification policy in ADR-0021
does not enable alert tools in this membership-only adapter. No TradingView data
becomes a machine signal; alert/webhook execution bridges remain rejected.

`tests/proofs/test_tradingview.py::test_official_discovery_ignores_every_non_membership_tool`
advertises all 35 names plus a synthetic `place_order` through the real SDK's
in-memory transport, with socket connections denied. Bare and namespaced
membership identities discover exactly the five operations; every other name
is refused by `validate()` and `call()` before a tool request. An admitted list
read still succeeds. This proof changes no production code, dependency or pin
and makes no OAuth, hosted-service, Desktop, broker or owner-acceptance claim.

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
uv run --frozen python -m sextant.tradingview --authorize --keep-login
uv run --frozen python -m sextant.tradingview --research-dir /path/to/top100/latest --authorize --keep-login --apply
uv run --frozen python -m sextant.tradingview --research-dir /path/to/top100/latest --keep-login --apply
uv run --frozen python -m sextant.tradingview --forget-login
uv run --frozen python -m sextant.tradingview --loop --research-dir /path/to/top100/latest --authorize
```

`--authorize --keep-login` with no `--research-dir` is the sign-in-only run: it
opens the session once, so the owner's browser consent completes and the sign-in
is stored, reads no display unit (so it works while no fresh unit exists) and
calls no list tool, then prints one fixed line. Without `--keep-login` that run
is refused, since it would save nothing, and `--apply` is refused with it. The
authorization address goes only to Python's `webbrowser.open`, which honours a
`BROWSER` helper by passing the address as its first argument.

By default each process requires explicit owner consent in the browser and
keeps tokens and client registration in RAM, clearing at exit; unflagged runs
and the tests stay RAM-only. The optional `--keep-login` makes the sign-in last:
the official SDK's tokens and client registration are kept as one JSON line in
the repo's existing encrypted store,
`~/.config/sextant/credentials/TRADINGVIEW_MCP_OAUTH`, encrypted at rest by
`systemd-creds` with the host key ([ADR-0028](adr/0028-local-keys.md)). A
sync-written value reaches the store over `--sealed-stdin` and is read only
through `ns_systemd_read`: there is no plain file, environment variable, argv
value, log line or value on stdout. Every token issue and refresh writes the
rotated value back through the same store, and a stored access token past its
lifetime refreshes through the stored refresh token, so a later run normally
needs no browser. The stored login is deleted only when the token endpoint
refuses the refresh with an RFC 6749 section 5.2 code that means the grant is
dead (`invalid_grant`, `invalid_client` or `unauthorized_client`, on 400 or
401); under `--authorize` one owner browser sign-in then runs, and it never
loops or retries the refused token. A 5xx, a 429, a transport failure or any
other answer stops the run, pages on stderr and leaves the stored value for the
next run. The authorization server publishes its token endpoint on another host,
so before a stored login's first refresh the sync runs the SDK's discovery from
the issuer bound to the stored registration (else the server's protected-resource
well-known); a refresh never goes to the SDK's fallback `<server>/token`, and
without the published metadata the run stops the same way. A browser opens only under `--authorize`: with `--keep-login` alone a
missing, refused or unusable login stops with its owner step and a page, which
is what lets an unattended unit use it. A value that cannot be read stops with
`--forget-login`, then `--authorize --keep-login`. `--forget-login` is the one
command that deletes the local value, and `scripts/with-keys.sh` refuses this
name, so no other command gets it in an environment. The store is per-user, not
a same-UID isolation boundary. `--keep-login` is refused with `--loop`; the loop's
own start and stop schedule stays a later change.

The sign-in uses only the official `https://mcp.tradingview.com/mcp` endpoint
and an ephemeral loopback OAuth callback. Revocation is the owner's, in their
own TradingView account where the OAuth consent was given: revoke the
authorised MCP client there and run `--forget-login`. Local deletion alone is
not server revocation.
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

`--loop` keeps that one owner consent for one process and admits at most one
`sync_research(apply=True)` per J5 cadence tick
(`lanes/tradingview/j5-cadence.params.json`: 150s in the 07:00–10:30 and
15:00–16:00 ET onset windows, 300s otherwise inside 04:00–20:00 ET, 900s above
the 80% weekly-usage mark). It rereads the newest complete unit each tick; a
missing, stale or invalid unit leaves both lists unchanged and pages once per
distinct episode. Pages go straight to stderr, not through `logging`: the
OAuth redaction guard disables logging for the whole consent session. It claims only when the observed `NS movers` and `NS focus`
pair differs from the last completed read-back, so unchanged membership never
calls the cloud. It exits at the 20:00 ET display close with a window-closed
message, and it never holds the OAuth session across the closed window. A failed
apply latches the admitted run for reviewed reconciliation; there is no
automatic retry or reset. A restart also refuses existing state that holds an
active, failed or page-pending run, or that was written by another reviewed
registry, before it opens a new consent session; the reviewed reconciliation or
migration must finish first. On a healthy restart, the startup by-ID read-back
replaces the saved comparison before the first claim, so a sync is judged
against the broker's current lists rather than the previous session's. The default state root is
`~/sextant-data/tradingview-j5` (`--cadence-root`); all cooperating processes
must use the same canonical root. `--weekly-usage-pct`/`--usage-source` exist to
supply the Windows controller's sourced number; when unset, the process states
that it has no Claude surface and the 900s branch is not exercised. The loop
needs one complete display unit; projecting the `sextant.j5-ranked/1`
document into that unit is the bridge's job and is not part of this change.
Every display unit and admission view carries `paper_slot: 2`, the account
whose data key feeds it; slot 3 was revoked on 2026-11-10 (owner, D-46). The
producer writes that label, and the bridge, the cadence claim and the loop's
admission view refuse any other, the revoked 3 included.

## Display parameter registry

These are sourced starting values, not calibrated trading parameters or
evidence of an economic benefit. Manual owner inputs stay unknown when unset.
All source paths below are at the northstar-trading pin above and in ADR-0021/26.

| Parameter | Value / bound | Authority |
|---|---|---|
| Research freshness | 1,200s; override 1–3,600s; age equal to limit refuses | `research.py:read_research_inputs/_envelope` |
| Snapshot lag | ≤600s | `research.py:_envelope` |
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

## Owner import card: the four reviewed Pine presets

The four reviewed v6 `indicator()` files live in
`lanes/tradingview/presets/`; this card is the owner-manual fallback for the
failed indicator-preset automation. It installs nothing and opens no Desktop
session.

| File | Save as a NEW script | Packaged SHA-256 |
|---|---|---|
| `ema_cross.pine` | `NS 2026-11-06 · ema_cross` | `648ec3830d757a90333792711ac6e19642e7ab2bef315d7bb5b21d31b87bdd37` |
| `hurst_vpin.pine` | `NS 2026-11-06 · hurst_vpin` | `bec431f2c9e49e062d0a43e1dea20079774b0827d42266b131351eea256c8b7d` |
| `quote_imbalance.pine` | `NS 2026-11-06 · quote_imbalance` | `86977f1a86f5dc76b808e457fc5ca1849320bda4990094caf8e0a65ac97ad9e7` |
| `exit_levels.pine` | `NS 2026-11-06 · exit_levels` | `210733c3312a4497ef8e2ad8e01ff5f607d9b93c724087d0a87ab2fa7e5029ac` |

Each packaged hash is the file's SHA-256 in
`lanes/tradingview/presets/manifest.json`; the upstream hash there separately
pins the formula bytes, with only the title changed. The local receipt command
in the [lane README](../../lanes/tradingview/README.md) rechecks both. After the
owner acceptances above:

1. Open the file and paste its source into a **NEW** script in the Pine Editor;
   never overwrite, rename or delete an owner script.
2. Save it with the dated ID above, compile it, and add it to the owner's chart
   at 1 minute; record chart type, feed/session, seed and inputs.
3. Recompute SHA-256 of the saved source and compare it with the packaged hash;
   stop if it differs. Restore the owner's layout by numeric ID afterwards.
4. Stop on ambiguity or missing proof.

No install automation exists: the indicator-preset path failed historically,
owner-manual Pine application is the fallback, and no webhook or alert bridge is
part of this card.

## Owner-manual order presets

Broker order presets are owner-manual ticket defaults, not Pine, a machine
signal or an order path. The roster is exactly three named presets:

| Preset | Order type | Entry price | TIF | Children | Confirmation | Scope |
|---|---|---|---|---|---|---|
| `NS ALPACA DAY LIMIT MANAGED` | LIMIT | 0 relative ticks (at the touch, not a fixed price) | DAY | none | ON | managed-paper entries |
| `NS ALPACA DAY LIMIT BRACKET` | LIMIT | 0 relative ticks (at the touch, not a fixed price) | DAY | TP/SL | ON | owner-managed positions only |
| `NS IBKR DAY LIMIT BRACKET` | LIMIT | 0 relative ticks (at the touch, not a fixed price) | DAY | TP/SL | ON | owner-managed positions only |

**Guard:** "TV presets can place brackets without confirmation", so
managed-paper entries stay plain LIMIT, never a bracket. An applied preset can
arm chart Buy/Sell and `Shift+B`/`Shift+S` in that mode, brackets included; the
MANAGED preset therefore carries no TP/SL children. The BRACKET pair is for
owner-managed positions only, where it reserves shares the custodian cannot
also protect. Its illustrative 2% TP / 1% SL are owner placeholders, not the
manager's exit policy ([ADR-0025](adr/0025-gain-protection-and-fast-exit.md));
DAY expiry does not flatten inventory.

Session truth for Alpaca presets: overnight runs 20:00–04:00 ET, is technically
the evening before the trade date, and accepts limit orders only. A DAY order
stays active through the next trading day's RTH and after-hours and cancels at
20:00 ET if unfilled. No overnight session runs immediately before a full NYSE
holiday (the Wednesday before Thanksgiving), and a half-day overnight runs the
full eight hours (the Friday after Thanksgiving). A bracket sets Alpaca's
`extended_hours` to false/omitted. IBKR TP/SL children exist only while the
parent is open and unexecuted; after execution no modification or bracket can
be added, and Pine is not supported for IBKR trading.

Dated sources, all read 2026-11-09:

- **T10:** [TradingView Order presets](https://www.tradingview.com/blog/en/optimize-trading-with-order-presets-48237/)
  (published 2024-11-13) and Help Center Order presets (article 43000742711):
  a preset saves order type, relative price in ticks from bid/ask, brackets
  (relative price or percent) and TIF; 10 presets per broker account;
  without-confirmation mode can place brackets.
- **T11:** [TradingView integration at Alpaca](https://alpaca.markets/learn/trade-with-alpaca-on-tradingview)
  (last updated 2024-11-12) and [Alpaca orders](https://docs.alpaca.markets/docs/orders-at-alpaca)
  (updatedAt 2026-10-13). The learn page does not say whether a paper account
  connects, which order types, TIF or brackets work, or what the ticket shows.
- **T12:** [IBKR TradingView FAQ](https://www.interactivebrokers.com/docs/third-party-integrations/trading-view/faq.md)
  (re-read 2026-11-09): TP/SL children only while the parent is open and
  unexecuted; Pine is not supported for IBKR trading.
- **T13:** [Alpaca 24/5](https://docs.alpaca.markets/us/docs/245-trading)
  (updatedAt 2026-10-12): the session truth above; `src/sextant/paper/sessions.py`
  implements it and `tests/proofs/test_paper_config.py` witnesses it.

No webhook, alert bridge or hotkey submission places an order. TV field→API
session translation (whether a paper account connects, which fields survive,
and same-account fill visibility) remains owner-verified. Quantity/risk
persistence, production list capacity, official result envelopes and session
persistence have not been accepted here. No paper handover or order action
follows.


## J5 to display-lists bridge

`tradingview/bridge.py` is one pure projection from a fresh
`sextant.j5-ranked/1` document to the three-document unit above
(`top100.json`, `focus.json`, `display-lists.json`). It performs no I/O and
reads no clock: the caller supplies sourced `DisplayBounds` (the j5 document
carries no legacy bounds and there is no default), writes the returned
documents, and still lets `read_research_inputs` judge freshness, bounding
`max_age` by the j5 `expires_at_ns` because the target contract has no expiry
field. Movers pair ranked rows with `NS Ranked` in rank order; focus is
exactly the paired `focus_eligible` rows, with no armed name invented. A
refused, unavailable or tampered j5 document raises `BridgeError` with no
documents, never an empty list, and more than 100 members refuse untruncated.

## Slot-3 ranked J5 producer

`tradingview/producer.py` adapts the existing `tv-display-producer@ea95075` to
main's native ranking and the J5 `NS Ranked` contract. Supplied stream tapes and
REST snapshots only; no key, socket, order, TradingView call or scheduler.
The [design, source registry, verified carry, consolidation and owner-consented loop](handbook/rank-live.md)
record the implementation and remaining acceptance. The lead's 2026-11-08
19:21:44 pivot requires it to land after B, with dsh and Google gates. The
19:49:24 owner cadence now runs only through `--loop`: one process consent, one
admitted apply per tick, stale input leaves the lists unchanged and pages, and
`enabled=1` is reviewed in this PR and effective at the next session boundary.
Stream opening and controller activation still require landing and explicit lead
enablement.

## Segment unit producer for the display directory


`tradingview/prestage.py` is the repo entry point that keeps the newest
complete display unit fresh for the current PRE, RTH or POST segment, so the
display loop above reads a fresh `--research-dir` without a manual step. One
operator-started process holds one slot-2 data lease and takes the same
environment seam as the other keyed jobs under ADR-0028:

```sh
scripts/with-keys.sh --strict \
  -k ALPACA_PAPER_2_API_KEY -k ALPACA_PAPER_2_SECRET_KEY -- \
  uv run --frozen python -m sextant.tradingview.prestage \
  --research-dir "$HOME/sextant-data/tradingview-prestage/unit" \
  --nasdaq-listed nasdaqlisted.txt --other-listed otherlisted.txt \
  --symbol-map symbol_map.json
```

`--strict` refuses a missing or empty key. The process reads only
`ALPACA_PAPER_2_API_KEY` and `ALPACA_PAPER_2_SECRET_KEY` from its environment
and passes them to the SDK; no key enters a file, flag, URL or log.

The request budget is its own row in
`lanes/tradingview/prestage-parameters.json`, never a K2 row: 200 requests per
minute, UNCALIBRATED, the lead's 2026-11-11 ruling. The row cites its bound and
measurement; it is the producer's share of a key that Paper B's reads and the
nightly calibration job also use. A row without a value, a REVIEWED scope or a
source still refuses (AGENTS.md Rule 2).

The directory texts are the public NASDAQ Trader files. The
`sextant-tradingview-listings` timer stages them in the producer's state root each
weekday at 03:00 New York time, and keeps the previous good files when a download is
refused (`deploy/listings/README.md`). The producer reads them once at start and does
not refuse an old file, because no maximum age has a source. Each tick receipt's
`universe_source` carries both files' File Creation Time, so the age is visible. An
`otherlisted.txt` row whose Exchange code NASDAQ Trader does not define (A, N, P, Z and V
only) is skipped and never guessed. The symbol map is the exact TradingView map. A
directory name with no mapping, or with `null`, is left out of the display universe
and counted in `universe_source` ("N of M directory symbols mapped, K unmapped
omitted"); a map that resolves no name refuses. The three display bounds
are metadata the bridge validates and never applies, read from
`lanes/tradingview/display-bounds.params.json` (`--display-bounds`, sourced
UNCALIBRATED rows); all three of `--gap-bound`, `--rvol-bound` and
`--bounds-max-age-s` replace the file, and only some refuse. `--once`
publishes one tick and exits, nonzero if that tick is refused. Otherwise it
sleeps the J5 cadence floor (150 s in the 07:00–10:30 and 15:00–16:00 ET onset
windows, 300 s elsewhere in 04:00–20:00 ET; the 900 s weekly-usage floor never
applies because no usage figure is supplied), releases the lease at the segment
boundary, and moves to the next supported segment; after POST it waits for the
next 04:00 ET open.
Overnight is not produced until #138 supplies a BOATS baseline.

`--ranked-view-dir DIR` also writes `DIR/ranked.html` and `DIR/ranked.json` each
tick: every directory name with an official close, ranked with no TradingView map,
so an unmapped name shows by its plain ticker; the unit files do not change. The
page is script-free, mode 600, reloads at the cadence floor, reads STALE past the
display `max_age_s` and UNAVAILABLE with the reason on a refused or idle tick. If the
producer stops, compare its "Stale after" time with the clock.

Each tick fetches the current segment's completed SIP minutes (the in-progress
minute is never replayed) and passes every completed minute through the
bar-fidelity host. The publication clock is read again after the replay, so a
tick whose fetch outlives its segment publishes nothing. The reference close is split-adjusted (`Adjustment.SPLIT`)
and is the same session's official close for POST and the last prior session's
official close for PRE and RTH; that reference session comes from the exchange
calendar, not from the baseline filter, so a 13:00 early close still supplies
the close even when the baseline skips it. The tick rebuilds the five-session
baseline once per segment from the five prior XNYS sessions whose start and
span match the current segment; an early close is skipped rather than treated
as a full session. Halt eligibility stays unknown because this REST path has no
status receipt, so no name is focus-eligible and the NS focus list is empty
until a status source exists. The projected display bound carries the
remaining J5 lifetime, so `read_research_inputs` refuses the generation after
its `expires_at_ns` even when the caller allows a longer age. The tick projects
the fresh J5 document with the bridge, writes the three documents into a
content-addressed generation directory, validates that generation with
`read_research_inputs(max_age=1200)`, and only then switches the display
directory's symlink pointer to it. A refused tick leaves the previous complete
unit in place; a segment whose five-session baseline or reference close cannot
be assembled is skipped with its reason paged, and the producer waits for the
next segment instead of exiting; an interruption before the pointer switch
leaves the previous generation readable, and the switch itself is atomic. No
stream is opened, no TradingView call is made, no order or controller exists,
and no unattended service is installed: the operator starts the process,
exactly as they start the display loop.
