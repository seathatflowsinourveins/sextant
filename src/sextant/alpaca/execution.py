"""Alpaca execution client shell for the live node.

Follows nautilus_trader@d53849b216e20f2c122ca01b4dd0da377638b186
``examples/live/_template/execution.py`` and
``docs/developer_guide/python_adapters.md``: the factory constructs the client
synchronously with the venue and account identity, and opens no wire. Order
submission, reconciliation and account state land with the execution work item;
until then connect refuses, so a paper node cannot run half-wired against the
broker account it would trade (one writer per account).
"""

from __future__ import annotations

from nautilus_trader.live.clients import ExecutionClient

from .constants import NOT_IMPLEMENTED


class AlpacaExecutionClient(ExecutionClient):
    """Execution client for the ALPACA venue."""

    async def _connect(self) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    async def _disconnect(self) -> None:
        """Disconnect from Alpaca: this shell opens no wire to close."""
