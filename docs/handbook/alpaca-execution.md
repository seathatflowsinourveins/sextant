# Alpaca execution boundary

The adapter follows NautilusTrader's pinned Python client hooks. The core owns
order state; the adapter retains venue identity and replacement evidence. A
PATCH response is a proposal: a confirmed successor must link both ways before
an engine update changes the venue identity. A foreign successor never acquires
house mutation authority through its parent.

Keep monetary payloads as decimal strings through the SDK's low-level REST
methods. Its typed request models coerce these fields to floats. Disable the
SDK's internal retries: each actual REST request must pass through the one
account pacer, including queries. A cancelled queued await must cancel its
admission; a wire call already running in a thread must be joined on shutdown.
Missing reserve authority produces an explicit refusal, never a dropped await.

Sources: NautilusTrader d53849b, `docs/developer_guide/python_adapters.md` and
`crates/adapters/architect_ax/src/execution.rs`; alpaca-py cc4cb3b7,
`alpaca/common/rest.py`, `alpaca/trading/requests.py`; Alpaca orders and replace
references, read 2026-11-10; ADR-0007/0009. The execution-boundary proofs witness
these constraints offline; broker qualification and economic merit remain open.

A failed or unsupported row is incomplete coverage, with the original payload
retained. An empty successful list has a different meaning. Replacement queries
must follow the confirmed successor, and stale predecessor state cannot move
active authority backwards. Known exit fills and triggers revoke queued
mutation admission even before a fresh REST observation. Entry remainders can
still be cancelled. Stream callbacks keep only a weak client reference and
dereference it on the node loop. Shutdown cancels the SDK coroutine on its own
loop, closes the socket and joins the executor work, including stalled connects.

The SDK omits fill commissions. The execution factory reads the two sourced
paper rows in `lanes/paper/shared-node.params.json` through
`sextant.alpaca.commission.paper_commission_resolver` and hands the client its
`commission_for_fill` hook; a missing, invalid or non-paper row leaves fill
reports UNAVAILABLE and connect refuses. Never label an inferred fee as an
observed fee. Nonempty historical activities also need an evidenced identity
mapping to stream executions. The registry authority belongs with the shared
node's rows (`lanes/paper/shared-node.params.json`), not in a fixture default.
The native core can infer fills from cumulative status reports; that is inferred
execution evidence, not an exact fee or stream/history identity proof.

The native account balance follows rc8's IBKR mapping: net liquidation as total,
available funds clamped to total for a nonnegative account, locked derived after
currency rounding. Raw buying power remains separately identified in account
info. Sources: IBKR `execution/account.rs:397-419`, `types/balance.rs:149-172`.

Successor binding uses only the venue-named identifier; similar order fields
supply no lineage authority. The fake gives a pending successor its own venue
identifier, so an independent order stays separate.
Source: Alpaca replace reference above; E5 lead addendum, SHA-256
`12adedf8056ad17fb9bb4d6b941b7f6f283a293bbfd61c41222b9c4d510aa9b8`.

Nautilus's client command FIFO must not await a paced wire receipt. Schedule
owned command tasks through `create_task`, as the pinned AX adapter does, and
let the account gateway choose among ready requests. Shutdown cancels and joins
those tasks before joining wire work. A house entry cancelled while still queued
is withdrawn using the gateway's positive not-sent fact, without an absence query
or a later submission; once sent, its outcome remains a reconciliation question.
Only gateway transmission facts are retained here, not a second order reducer.
Sources: Python adapter guide, “Process commands in order”; AX `execution.rs`;
the existing bridge's `_unsent`/`cancel` admission rule from its pinned source.

An unavailable fill-report capability also keeps the writer unavailable at
startup. Without an evidenced commission resolver, connect refuses before
credential lookup or SDK construction; a running writer must not discard its
first fill merely because its report cannot yet carry a commission. This applies
the lead's no-invented-fee ruling and the adapter guide's fail-startup contract.

The request budget has one authority: the reviewed account control rows. The
client must not add another numeric pin after parsing them; otherwise another
paper profile or a later sourced rate change needs a code change. The pacer still
validates the budget against the broker ceiling and retains per-position reserves.

A sent command is resolved locally only by a venue refusal (4xx). A malformed
2xx body, a 5xx or a transport error after send stays unresolved; the next
authoritative read of that order settles a lost PATCH unless the order is
`pending_replace`. An older successor arriving after a newer one is bound is
not a first binding. A pacer refusal is a not-sent refusal for every caller.
The paper node claims external orders for the house universe and limits
reconciliation to it (lead ruling 2026-11-11): the owner's filled shares in a
universe symbol are the position the Strategy protects, while no order outside
the house namespace is ever modified or cancelled. Owner rows the engine would
skip (replaced without fills) are withheld with their payload. Terminal rows in
an unloaded instrument are also withheld, across every namespace, only when the row
and every nested leg at every depth are terminal; a working or unknown-status leg
refuses startup by name before the gate, including a missing status. Withheld
instruments lose bulk position coverage; an owner
bracket refuses startup by name. The engine's lookback stays unbounded and the
order listing pages newest first by `until`, past the 500-row cap, so a holding
whose fills are old is still explained by its order; a failed or non-contiguous
page, a page without progress, or a listing needing more requests than the
registered request budget is incomplete coverage and startup refuses. A read that finds an order unchanged after an unanswered
modify or cancel returns it to its venue state before the engine's in-flight
ladder would close it, and disconnect rejects a queued entry it never sent.
Sources: pinned NautilusTrader `manager.rs` (external-order claim and filter,
no-instrument skip, reconciliation scope, unresolved positions, in-flight
ladder); alpaca-py `rest.py:197-210`; Alpaca order statuses, read 2026-11-10;
E5 fix-round design note.

On-wire evidence is recorded at one send boundary, the gateway's on-wire hook,
before any reply: a sent DELETE's venue id, a submit's or PATCH's sent flag
beside its reserved proposal. An exception, a cancellation or a destroyed task
never creates it. A 2xx that acknowledges an attempt (DELETE 204, PATCH 200)
never clears it; only a terminal venue event, a venue refusal or the next
authoritative read does, and the first such answer settles the command once.
Unsent work is refused once, even before its first step or when it cannot be
scheduled. Sources: Alpaca order API, read 2026-11-10; CPython 3.13 asyncio.

Every trade update passes one identity resolution before it is forwarded, fills
included. Unknown lineage is incomplete coverage, never another order's id, and
the active binding moves only forward by house successor number. Sources:
alpaca-py `trading/enums.py:321-333`; reviews e5r3-99ac5bf and e5max-99ac5bf.

A windowed listing merges rows by string venue id; a row with no such id goes on to
its own row boundary, keeping its payload and its siblings. Source: review e5r3-99ac5bf.

Every safety fact a trade update carries (executing, terminal, refused) is recorded on
arrival, keyed by the venue order id it names, before the first await. Lineage work after
it only adds the stable binding, and every value read before an await is re-validated after
it. A successor fill that arrives before its lineage is confirmed is incomplete coverage,
held until any path confirms it, then forwarded once. Sources: review e5r4-266edf5, PR 588,
NT Hyperliquid and Polymarket.

One cancel and one replacement per order are unresolved at a time, each answered only by
its own answer: its HTTP error, a terminal event or a confirmed replacement, a stream
refusal, or a read issued after its own call ended. A read that refuses one owes the next
stream refusal, which then answers nothing. Source: PR 569 gate reviews.

Fill history needs no fill report where an order report already explains it. A FILL
activity carries no stream execution id and no fee (account activities reference, read
2026-11-11), so none is built from it. The engine infers each fill an order report shows
(`reconciliation/orders.rs:1065-1145`): at the venue average price, with the client's
commission hook, and with a deterministic reconciliation trade id. The client reads every
FILL page. A row whose order is listed with at least its cumulative quantity passes;
any other row is refused. A holding that no order report explains stops the start in the
engine itself (`node/mod.rs:992-996`, `generate_missing_orders` off).

Entry chase allowance never grants exit chase authority. The B exit mapping reads
only B-scoped rows and keeps both exit chase fields unavailable, with gain-lock
cost still unavailable.

A failed startup reconciliation names its cause. The engine keeps only "Failed to get mass
status" (`python/node.rs:676`), so each report generator records its requests, rows and
first failure (class, HTTP status, our own reason text). It also counts terminal unloaded
history skipped per stage, in successful receipts as well as a failed stage's ERROR line;
one aggregate warning names only stage and count. Terminal skipped rows remain in the
gate's existing replacement-lineage input. Fill activities still require a listed order
covering their cumulative quantity, including those tied to skipped terminal history;
working unloaded orders never disappear. No value is recorded. Sources: stage 1 starts
1 and 2; NT d53849b2 `crates/adapters/binance/src/spot/execution.rs:3542-3545`.

Rehearse on the failed history's shape, including unloaded terminal orders and their
fills, rather than only the claim list. The run-2 regression uses the real order node,
engine and gate over the fake venue; it proves flat admission, named refusal for unloaded
working orders in every namespace, nested working legs behind terminal parents, and
unresolved replacement refusal. A terminal parent alone does not prove a compound order
has ended: inspect all recursive `Order.legs` (alpaca-py cc4cb3b7 `models.py:241`) before
skipping either its order or explained fills. All-terminal nests remain counted once
per skipped parent or fill activity; loaded owner compound orders still refuse. It establishes
no broker behavior or permission to trade (`test_alpaca_unloaded_history.py`).
