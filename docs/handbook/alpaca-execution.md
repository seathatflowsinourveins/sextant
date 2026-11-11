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

The SDK omits fill commissions. Until an evidenced resolver or registry row
exists, exact fill reports are UNAVAILABLE; never label an inferred fee as an
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
