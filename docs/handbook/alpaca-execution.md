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
