# Custody, pacing and halt: row 8 mechanism proofs

Issue [#51](https://github.com/seathatflowsinourveins/sextant/issues/51); ADR-0007, ADR-0009 and ADR-0010. These are offline policy/wire-envelope tests and native MODELED mechanism drills. They start no broker client, stream, service or paper writer and do not declare B ready.

## Minimal bridge and fit

Before the fit claim, the pinned source inventory was measured: `src/nautilus_alpaca/execution.py` is 5,818 lines and `order_reducer.py` is 2,370, together 8,188 before parsing, pricing, HTTP, stream and recovery dependencies. `nodes/custody.py`, `custody_lineage.py` and `custody_registry.py` add 559 + 516 + 650 = 1,725. Those trees are not a 2,000-line port.

The Sextant slice is deliberately narrower: one account lease/pacer, durable house client identity and replacement lineage, explicit account/custody facts, reservation/flat-receipt policy, and single-order LIMIT or RTH trailing-SELL commands. It serializes relative API paths and Decimal strings; a caller-supplied transport owns the actual-send hook. The module contains no HTTP implementation, credentials or endpoint selection. The native witness supplies a simulated account through BacktestEngine rather than a substitute live client.

The actual source addition is measured by `wc -l src/sextant/execution/*.py src/sextant/risk/*.py src/sextant/backtest/custody_witness.py`; CI checks the whole tree against 15,000 lines. This proves the scope of this carry, not the fit of a complete Alpaca bridge, B deployment or IBKR runtime. The precise final count is in the PR body.

## Source map

All trading sources below are `seathatflowsinourveins/northstar-trading@paper 8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`, read 2026-11-06. Files were read through GitHub and then a shallow, filtered fetch of the exact commit; no old lane or service was contacted.

| Pinned source | Carry |
|---|---|
| `src/nautilus_alpaca/execution.py` `_lock_account`; `nodes/custody*.py` admission/assignment/lineage | Broker/account-scoped kernel flock, immutable house registrations, supplied positive position authority distinct from reports, foreign/mismatched/unknown freeze, owner-order reservations and complete terminal-lineage flat receipts. |
| `src/nautilus_alpaca/order_reducer.py` `_OrderState`, `_fresh`, `_report_verdict`, submit/cancel/replace transitions | Observation epochs, per-request cancel generations/outcomes, replacement generations, aliases and retained possible-fill exposure. A positive stream event outranks a late REST action answer. ACK, timeout and 404 do not prove terminal cancellation or a fill. |
| `src/nautilus_alpaca/common.py` `make_trade_id`, `format_decimal`, replacement client-ID helpers | Executing-order UUID plus normalized generation cumulative quantity, within native TradeId's 36-character bound; deterministic `__R<n>` replacement identity. |
| `src/northstar_trading/execution/pacer.py`; `src/nautilus_alpaca/pacing.py` | Integer-nanosecond bounded bucket; CANCEL > REDUCE > MODIFY > QUERY > SUBMIT, FIFO; protection reserve, deferred admission, one actual-send hook per request, wire/actions/fills counters, 429 bucket drain and pause. Retries/list members must re-enter pacing individually. |
| `src/northstar_trading/risk/guard.py`; selected `risk/actor.py` `_cancel_entries`, `_reducing_exits`, `_close_residual`, `engage_kill_switch`, `_on_check` | Persist the kill marker before fallible work; cancel only house entries, retain reducing protection, wait the 10-second cancel window, revisit capped residuals on the 2-second tick, preserve a halt through late fills/restarts and release only on positive flat/terminal evidence. |
| `safeguards/__init__.py`, `rows_ibkr.py`; `persist.py` | Lane-derived paper observation, unknown-ID ERROR/enforcement, loss-warning text, crossing/material/reminder/clear records and bounded/prunable edges; same-directory file/fsync/rename/directory-fsync state. Day equity, OER and economic HWM evidence can persist without resetting the economic HWM. |
| `nautechsystems/nautilus_trader@v2.0.0rc7 55c0e82053142bce3a5cba4de4221d3929c2d3bc` native Strategy/BacktestEngine/cache/portfolio/clock/order APIs | Native house LIMIT fills, scoped cancellation/flatten intents and a synthetic owner-labelled resting order. RiskEngine remains `bypass=False`. These are not EXTERNAL claims. |

The accepted house custody/guard composition comes from the harvested ADRs and their pinned northstar-lanes contracts, not a newly invented trading rule. The earlier actor's broad cancel-everything path is not carried: the source's scoped `_cancel_entries` path fits Sextant's owner-order hard line.

The official [Create an Order](https://docs.alpaca.markets/us/reference/postorder) and [Replace Order by ID](https://docs.alpaca.markets/us/reference/patchorderbyorderid-1) schemas, read 2026-11-06, define quantity and price fields as strings. The envelope preserves those strings instead of the old SDK's float conversion. The replace reference also says its success does not guarantee replacement; the reducer waits for a positive successor observation. [Orders at Alpaca](https://docs.alpaca.markets/us/docs/orders-at-alpaca), read 2026-11-06, supplies session/order-shape and price-precision constraints.

## Authority and witnesses

`lanes/custody-parameters.json` records every consumed control with units, source, calibration and last-change date. Cited pacing/halt/observation numbers are UNCALIBRATED starting values. The two position protection reserves remain unavailable. That state permits no new entry through the profile and does not block protection, reducing requests or queries. Fixture rows require explicit fixture opt-in and supply no deployment authority. Wire envelopes, native witness output and persisted guard state retain the parameter hash.

Run serially with at least 20 GiB MemAvailable:

```sh
timeout 180 uv run --frozen pytest tests/proofs/custody
```

The drills cover owner orders untouched; one writer across lane names and a second process; one pacer per writer; owner and pending/unknown close reservations; partial-fill terminal cancellation; missing lineage and stale epochs; late action answers and independent cancel attempts; Decimal fill deduplication; per-send session/lease/admission checks; rolling-window pacing, priority, reserves and 429; durable kill-before-save, marker detection and explicit release; corrupt or semantically unknown state staying halted; paper observations; and equity/OER/HWM persistence.

The 429 recovery regression follows the pinned `src/nautilus_alpaca/pacing.py::RequestPacer.on_success`: a confirmed non-429 reply resets the consecutive-429 streak without clearing an active pause or restoring bucket tokens. The bridge applies this to ACK, REFUSED and NOT_FOUND before order-state early returns, including account queries; UNKNOWN and DEFERRED do not prove a reply. Consecutive 429s still drain the bucket and double the pause up to the existing cap.

Replacement facts preserve the pinned `order_reducer.py::_OrderState.cum_by_vid` and `_emit_fill` venue identity: retired and current facts each carry only their own venue's cumulative fill. The lifecycle total remains separate. The partial-fill replacement regressions check successors with zero and nonzero fills, aggregate fill conservation, and custody refusing an exit larger than the remaining unreserved quantity.

For the shared-node #84 boundary, `Custody.submission_ready(instrument, exclude_client_id=None)` and `available_exit(instrument, exclude_client_id=None)` refuse another submission as soon as an instrument has a registered client ID absent from its authoritative snapshot. The queued request may exclude its own immutable registration during its final pre-wire check. An incomplete/frozen snapshot still refuses it. This is a conservative refusal at the common custody boundary, not a second reservation book; a missing report never releases an earlier intent. `AccountPacer.request(..., position_counts=callback)` reads current open/exiting position counts when an entry leaves the queue; the bridge supplies that callback and refuses unavailable reserve authority before registering a new entry.

The native synthetic drill fills one house entry and one LIMIT exit after an owner kill, observes minimum net quantity zero, reaches flat and remains latched. A separate owner-labelled resting LIMIT remains ACCEPTED and untouched; its possible future fill prevents a flat receipt even after current modeled net reaches zero. Synthetic fees and latency are explicit inputs, not cost or operational measurements. No return comparison or economic arm is claimed; a trading experiment still needs canonical TrialLog custody.

## What remains unverified

There is no real external-owner claim, process death with broker reconciliation, continuously installed protection or paper acceptance here. The lead's #49 ruling stands: rc7 has no Python mock live client/reconciliation stand-in, so none is built; real claim and crash/reconcile evidence belongs to Sandbox/paper before #38 ready.

The slice does not include HTTP/stream lifecycle, pagination/activity recovery, broker admission/funding/calendar/mark producers, complete native reconciliation/emulator pacing coverage, advanced order groups, fractional quantity changes, IBKR execution, financial-anchor parity or deployment. Callers must supply coherent signed account/custody facts and current session/admission decisions; a report alone grants no position authority. Unknown fills, replacement carry or exhausted cancellation stay unresolved rather than being written off. The historical adapter seed/after-PATCH-fill gaps remain open. Its full recovery deadlines/capacities cannot be claimed as implemented by this non-collecting slice.

The B manager remains #49's writer/policy integration. Its cancel-first gaps, external claims and actual broker-terminal receipts must be measured in their admitted tier. This PR supplies mechanisms and seams for that integration; it supplies no ready receipt, starts no writer and places no broker order. Lessons are in the PR body for the lead's single-writer handbook update.
