"""Alpaca execution client shell for the live node.

Follows nautilus_trader@d53849b ``examples/live/_template/execution.py``: the
factory builds the client synchronously and opens no wire. Order submission,
reconciliation and account state arrive with the execution work item; until then
connect refuses, so a paper node cannot run half-wired (one writer per account).
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
