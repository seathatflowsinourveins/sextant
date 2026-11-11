"""Paper B's lifecycle as one NautilusTrader Strategy (LEAD-2201 S1, component map row 1).

S1-1 carries the ranking input only: ``on_start`` subscribes to the ranking data type and
``on_data`` feeds the reviewed ``RankingConsumer``, the code ``RankingDataActor`` runs
(consumer.py:221-232), moved into the Strategy because a Strategy is an Actor (rc8 trading
stub ``subscribe_data`` :690-695, ``on_data`` :632). Each candidate decision reads the
consumer's current ``entry_rank`` and the default-off rank gate; a stale, missing or refused
generation gives no candidate and the consumer's reason (ADR-0003, ADR-0006 R5). The heartbeat
reaches ``consumer.accept_heartbeat`` from its host; this Strategy never manufactures one.
Nothing here submits, modifies or cancels an order.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import CustomData, InstrumentId, StrategyId, TradeTick
from nautilus_trader.trading import Strategy

from sextant.ranking.consumer import RankingConsumer
from sextant.ranking.publisher import ranking_data_type
from sextant.ranking.rank_gate import RankGateDecision, RankGateStatus, decide_rank_gate
from sextant.ranking.registry import RegistryRow

Journal = Callable[[dict[str, Any]], None]


class BLifecycleConfig(StrategyConfig):
    def __new__(cls, *, namespace: str, **_kwargs: Any):
        # rc8's PyO3 configs initialize their native fields in __new__ (native.py's shape).
        return cast(Any, super().__new__)(
            cls, strategy_id=StrategyId.from_str(f"BLIFECYCLE-{namespace}"), order_id_tag=namespace
        )

    def __init__(
        self,
        *,
        namespace: str,
        instrument_ids: Sequence[InstrumentId],
        consumer: RankingConsumer,
        rank_gate: RegistryRow,
        journal: Journal | None = None,
    ) -> None:
        super().__init__()
        ids = tuple(instrument_ids)
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("B needs unique instrument ids")
        if not all(isinstance(iid, InstrumentId) for iid in ids):
            raise ValueError("B instrument ids must be native InstrumentIds")
        if not isinstance(consumer, RankingConsumer):
            raise ValueError("B needs the reviewed RankingConsumer")
        if not isinstance(rank_gate, RegistryRow) or rank_gate.name != "rank_gate_enabled":
            raise ValueError("B needs the rank_gate_enabled registry row")
        self.namespace, self.instrument_ids = namespace, ids
        self.consumer, self.rank_gate, self.journal = consumer, rank_gate, journal


@dataclass(slots=True)
class _Book:
    """Per-instrument state; later parts add entry, protection and campaign state."""

    instrument_id: InstrumentId
    gate: RankGateDecision | None = None
    gate_ns: int | None = None


class BLifecycle(Strategy):
    """One writer's Strategy for every instrument B trades or protects (LEAD-2201 A1)."""

    def __init__(self, config: BLifecycleConfig) -> None:
        super().__init__(config)
        self.consumer, self.rank_gate = config.consumer, config.rank_gate
        self._journal = config.journal
        self.journal_errors = 0
        self.books = {iid: _Book(iid) for iid in config.instrument_ids}

    def on_start(self) -> None:
        self.subscribe_data(ranking_data_type(self.consumer.feed))
        for iid in self.books:
            self.subscribe_trades(iid)

    def on_data(self, data: CustomData) -> None:
        now = self.clock.timestamp_ns()
        accepted = self.consumer.handle(data, now=now)
        self._record(kind="generation", ts=now, accepted=accepted, reason=self.consumer.reason)

    def on_trade(self, trade: TradeTick) -> None:
        book = self.books.get(trade.instrument_id)
        if book is not None:
            self.candidate(book, self.clock.timestamp_ns())

    def candidate(self, book: _Book, now: int) -> bool:
        """The rank gate over one current ``entry_rank``; DISABLED means no house entry."""
        enabled = self.rank_gate.value
        rank = None
        if enabled is True:
            rank = self.consumer.entry_rank(str(book.instrument_id.symbol), now=now)
        decision = decide_rank_gate(
            enabled=cast(bool, enabled), rank=rank, consumer_reason=self.consumer.reason
        )
        book.gate, book.gate_ns = decision, now
        allowed = decision.status is RankGateStatus.PASS
        self._record(
            kind="rank",
            ts=now,
            instrument=str(book.instrument_id),
            status=decision.status.name,
            reason=decision.reason,
            rank=rank,
            candidate=allowed,
        )
        return allowed

    def _record(self, **row: Any) -> None:
        if self._journal is None:
            return
        try:
            self._journal(row)
        except Exception:  # containment: evidence never changes a decision
            self.journal_errors += 1
