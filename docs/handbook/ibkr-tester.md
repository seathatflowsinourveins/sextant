# IBKR execution tester custody, 2026-11-11

A writer lease does not prove clean custody. The pinned tester bulk-cancels other strategies'
orders on stop. Use its cancel/close stop switches, and check reconciled native cache in an
actor before strategies start. That admission is a startup snapshot; a resting SELL can later
meet the owner's shares. The pinned Python actor has no sourced continuous order/position
event hook. A quote-only check has a gap, and a new timer cadence has no source.

An order-sending start therefore refuses a profile requesting limit SELLs, stop SELLs or
brackets, with reason `no sourced continuous custody fence`, before reading account identity
or constructing the node. Requests are refused before either SELL switch is forced off.
Lifecycle remains available; all six profiles remain available in dry run. Cancel/close on
stop stay disabled, so shutdown never sells back or cancels an owner's order.

IBKR's writer lease uses the account scope and a shared `~/.cache/sextant/locks` directory
across worktrees, ports, client ids and instruments. `--lease-root` remains accepted for
compatibility but cannot select an IBKR lock location. The existing flock and account digest
are reused. A run directory is evidence storage, never a separate writer identity.

Native actor failure must prevent the tester from starting and produce a named refusal
receipt. Use native logging bypass for account-safe diagnostics. The lane remains OFF.
The [manifest custody row](../manifest.md#ibkr-tester-custody) names the pinned paths and
`test_ibkr_node_custody.py` regression; no broker session was used to establish this lesson.
