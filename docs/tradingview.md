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

This implements the source's `ns-display-lists/1` consumer, not a second
ranking/focus producer. Legacy generations without `display-lists.json` refuse.
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

Broker order presets remain owner-manual. Managed-paper tickets use plain
LIMIT, no attached bracket; outside RTH follow the broker's session rules.
`NS ALPACA DAY LIMIT BRACKET` / `NS IBKR DAY LIMIT BRACKET` are historical
owner-managed presets, with illustrative TP/SL placeholders, not manager exit
policy. Quantity/risk persistence, account translation, fill visibility,
production list capacity, official result envelopes and session persistence
have not been accepted here. No paper handover or order action follows.


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
The [design, source registry, verified carry, consolidation and disabled owner cadence](handbook/rank-live.md)
record the implementation and remaining acceptance. The lead's 2026-11-08
19:21:44 pivot requires it to land after B, with dsh and Google gates. The
19:49:24 owner cadence is implemented DISABLED. Stream opening and controller
activation still require landing and explicit lead enablement.
