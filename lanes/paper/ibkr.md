# IBKR paper: offline adapter slice

Issue [#81](https://github.com/seathatflowsinourveins/sextant-archive/issues/81). This supplies configuration
for broker-portability evidence. The lane is ON for the paper account only (the owner logs in); this establishes no readiness, custody or trading result.
The shared paper node belongs to #84 and custody/pacer/guard/halt to #51; no node is duplicated here.

`sextant.paper.ibkr.build_client_configs` returns `IbkrClientConfigs(data, execution)`, the native
first-party Nautilus configs at the repository's engine pin. Supply every argument explicitly:
`account: PaperAccount`, `host`, distinct `data_client_id`/`exec_client_id`,
`load_ids: frozenset[InstrumentId]`, `connection_timeout`, `request_timeout`,
`use_regular_trading_hours`, `ignore_quote_tick_size_updates`, `batch_quotes`, and `market_data_type`.
It reads no environment or credentials and constructs no factory, node, Gateway, connection,
stream or order.
It requires the `ibkr-paper` lane and takes both native configs' port and the execution account
directly from that shared account, whose validator requires a bare `D[A-Z]{1,2}[0-9]+` code and
port 4002/7497. There is no second account or port input that could differ from the writer lease.
At rc8 `d53849b216e20f2c122ca01b4dd0da377638b186`, `execution/account.rs` splits a composite
account on `-`; accepting a live second segment would violate the paper boundary. The source's
narrow US-equity scope refuses `=`, `^`, OCC options and generic spreads: `common/symbology.rs`
routes parentheses/`___` grammar through `common/spreads.rs` to BAG contracts.
Identifier acceptance proves neither
contract qualification nor custody. All preload ids must pass: a delisted/OTC held id refuses the
whole call. #81 must supply a deployment-versus-retained contract before this can start a custodian.

[ibkr.toml](ibkr.toml) preserves the gnzsnz 10.50.1f image **including its digest** and IBC 3.24.2
from the pinned deployment, with no launcher or login. ibg-controller v0.16.3 remains a qualification
target. The retained rc7 source required protocol ≥213 for ibapi 5.0.0. The current rc8/Gateway
pairing remains UNVERIFIED until qualification on the first authorized connection.
The 0.5%, 1×, re-entry-OFF, long-first C06 profile
remains a conditional CANDIDATE. Its profile starts are UNCALIBRATED; shared limits and protection
reserves are references to `lanes/limits.yaml` and `lanes/custody-parameters.json`, never copied
starts. Nothing consumes this inventory for sizing or orders. The −66.1/−103.7 bps/week result in
ADR-0024 remains negative evidence, not extreme-mover validation.

The manifest's **Offline IBKR paper configuration** row cites rc8's `src/config.rs`,
`src/python/config.rs` and `src/data/core.rs` (under `crates/adapters/interactive_brokers/`).
The four named TOML data-policy rows are UNCALIBRATED starts. RTH is `false` for ADR-0002's
supported 24/5 sessions; that flag controls historical/bar request hours, not venue entitlement.
`ignore_quote_tick_size_updates=false`, `batch_quotes=true` and `market_data_type="REALTIME"`
follow the native SDK defaults. Size-only quote updates are retained. The cited `exec_tester.py`
chooses `DELAYED` instead; callers can explicitly reproduce that choice, as the forwarding proof
does. REALTIME entitlement is UNVERIFIED, and no registry start authorizes a subscription.
The TOML proof parses and supplies the four starts to native configs; the shared node does not
yet consume this inventory at runtime.

The shared node must supply one account writer/reducer and durable house lineage, complete broker
snapshots, owner-order fences, protection reserves, actual-send admission and a persisted guard kill
path. The 30/s all-request budget stays until rotation is paced; 40/s is conditional. Orders, data,
history, reconciliation, list members and native retries all count. The native client config boundary
does not qualify an actual-send pacer or transport integration. This slice does not prove coverage
of startup/reconciliation/emulator sends; wrapping order intents alone cannot provide that proof.

`timeout 60 uv run --frozen pytest tests/proofs/test_ibkr_paper.py` checks native configuration and
refusal boundaries and parses the TOML registry, including its canonical shared references.
It blocks factory/node/Gateway and historical-client construction during the smoke witness; it is
not a broker or recorded-session drill. The remaining common and IB-specific drills on #81 are
NOT_RUN: B2 bracket/reduce-only/repeated-amend and protection qualification; OER observation and
working-order limits; the guard's own kill-to-flat path (generic REDUCING is unqualified for IB);
the inherited 400-second stale-account/roughly 15-second return residual; sub-$1 refusal at send;
shared request pacing, unknown-state recovery, and cumulative-ledger session receipts.

Gateway startup/login still waits for #38's ready/old-custodian stop receipt and owner handover.
No broker connection, stream, order, enabled unit or automatic startup is supplied here.

**Node entry (#470).** `python -m sextant.paper.node_ibkr` builds the paper node from the engine's
own Interactive Brokers data and execution factories and its built-in `ExecTester` in one of the
adapter's execution profiles (`lifecycle`, `cancel-modify`, `stop`, `stop-limit`, `trailing`,
`bracket`); no execution client of ours. It dry-runs unless `--send-orders` is given, takes the
account from a key NAME (`--account-id-env`), refuses live ports 4001/7496 and any non-`D` code,
takes the account's writer lease, runs on the main thread, and refuses every start while this
registry's `state` is OFF. `tests/proofs/test_ibkr_node.py` proves each refusal without a connection.

Both tester stop switches are false, leaving tester orders/holdings in place. `--send-orders`
refuses foreign open/inflight orders or holdings for the instrument after native reconciliation,
before strategies start. Native logging is bypassed; semantic argument refusals write receipts.
See the [custody lesson](../../docs/handbook/ibkr-tester.md) for sources and offline proofs.
