# IBKR execution tester custody, 2026-11-11

A writer lease does not prove clean custody. The pinned tester bulk-cancels other strategies'
orders on stop. Use its cancel/close stop switches, and check reconciled native cache in an
actor before strategies start. Native actor failure must prevent the tester from starting and
produce a named refusal receipt. Use native logging bypass for account-safe diagnostics.
The [manifest custody row](../manifest.md#ibkr-tester-custody) names the pinned paths and
`test_ibkr_node_custody.py` regression; no broker session was used to establish this lesson.
