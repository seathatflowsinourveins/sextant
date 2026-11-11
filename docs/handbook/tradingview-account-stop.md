# Account quota stops

LEAD-0243/0903 (2026-11-11): quota latches the account until an audited lead clear.

Shared state, budget and durable spacing cover every HTTP method; missing state
refuses. [Contract](../tradingview.md#account-wide-mcp-request-guard-2026-11-11).

Compare transport refusals with the pinned SDK's normal statuses before latching:
GET/DELETE 405 permits the session to continue. Tool `inputSchema`/`outputSchema`
describes metadata; a property named `error` inside it is not an error answer.
Keep unknown answer shapes fail-closed until a vendor wire envelope is sourced.
[Pinned sources and offline proofs](../manifest.md) (2026-11-11 delta-review lesson).
