"""Minimal carry of northstar-lanes@00203275944a:contracts.py.

RankingView, FlatReceipt, FastSellFacts, EnterIntent and CampaignState retain
their source roles. Entry qualification/custody adapters are injected seams,
not implementations or attestations of the missing pure setups/reentry files.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from types import MappingProxyType
from typing import Protocol, Self

from nautilus_trader.model import InstrumentId, Quantity


def decimal(value: object, *, positive=False) -> Decimal:
    if (
        type(value) is not Decimal
        or not value.is_finite()
        or value < 0
        or (positive and value == 0)
    ):
        raise ValueError("A finite nonnegative Decimal is required")
    return value


def integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("A nonnegative integer is required")
    return value


class RankingView(Protocol):
    @property
    def generation_key(self) -> str: ...
    @property
    def known_at(self) -> int: ...
    @property
    def fresh(self) -> bool: ...
    def rank_of(self, symbol: str) -> int | None: ...


@dataclass(frozen=True)
class FlatReceipt:
    instrument_id: InstrumentId
    broker_net_qty: Decimal
    terminal_order_ids: tuple[str, ...]
    ts: int

    def __post_init__(self):
        if not isinstance(self.instrument_id, InstrumentId) or decimal(self.broker_net_qty) != 0:
            raise ValueError(
                "FlatReceipt requires exact zero broker quantity and instrument identity"
            )
        integer(self.ts)
        if (
            not isinstance(self.terminal_order_ids, tuple)
            or len(set(self.terminal_order_ids)) != len(self.terminal_order_ids)
            or any(not isinstance(key, str) or not key for key in self.terminal_order_ids)
        ):
            raise ValueError("Terminal lineage must contain unique explicit order IDs")


@dataclass(frozen=True)
class FastSellFacts:
    instrument_id: InstrumentId
    sell_trigger: Decimal
    sell_price: Decimal
    sell_ts: int
    flat_receipt: FlatReceipt | None

    def __post_init__(self):
        if not isinstance(self.instrument_id, InstrumentId):
            raise ValueError("Native instrument identity required")
        decimal(self.sell_trigger, positive=True)
        decimal(self.sell_price, positive=True)
        integer(self.sell_ts)


@dataclass(frozen=True)
class EnterIntent:
    """A qualified intent from row 6; this row never derives a setup from a quote.

    generation_key is the admission envelope around the source EnterIntent.
    labels retain confirmation/extension facts for the consumer's refusal checks.
    """

    instrument_id: InstrumentId
    ts: int
    generation_key: str
    setup: str
    limit: Decimal
    stop_distance: Decimal
    confidence: Decimal | None
    labels: Mapping[str, str]

    def __post_init__(self):
        if not isinstance(self.instrument_id, InstrumentId):
            raise ValueError("Native instrument identity required")
        integer(self.ts)
        decimal(self.limit, positive=True)
        if decimal(self.stop_distance, positive=True) >= self.limit:
            raise ValueError("Long stop distance must be below entry")
        if self.confidence is not None and decimal(self.confidence) > 1:
            raise ValueError("Confidence must be in [0, 1]")
        if not self.generation_key or not isinstance(self.generation_key, str):
            raise ValueError("Generation identity required")
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in self.labels.items()):
            raise ValueError("Explicit qualification labels required")
        object.__setattr__(self, "labels", MappingProxyType(dict(self.labels)))


@dataclass(frozen=True)
class CampaignState:
    campaign_id: str
    origin_instrument_id: InstrumentId
    current_instrument_id: InstrumentId
    mode: str
    original_qty: Decimal
    original_notional: Decimal
    original_risk: Decimal
    remaining_qty: Decimal
    remaining_notional: Decimal
    remaining_risk: Decimal
    charged_loss: Decimal
    charged_fees: Decimal
    evidence_complete: bool
    reentry_count: int
    version: int

    def __post_init__(self):
        if (
            not isinstance(self.campaign_id, str)
            or not self.campaign_id
            or self.mode not in {"paper_unbounded", "live_nonrenewing"}
            or not isinstance(self.origin_instrument_id, InstrumentId)
            or not isinstance(self.current_instrument_id, InstrumentId)
            or type(self.evidence_complete) is not bool
        ):
            raise ValueError("Invalid campaign identity or mode")
        for suffix in ("qty", "notional", "risk"):
            original = decimal(getattr(self, f"original_{suffix}"), positive=True)
            if decimal(getattr(self, f"remaining_{suffix}")) > original:
                raise ValueError("Remaining budget exceeds original campaign ceiling")
        decimal(self.charged_loss)
        decimal(self.charged_fees)
        integer(self.reentry_count)
        integer(self.version)

    def from_previous(self, **changes) -> Self:
        """Source contract: immutable originals and monotonically nonrenewing budgets."""
        candidate = replace(self, **changes)
        for key in (
            "campaign_id",
            "origin_instrument_id",
            "mode",
            "original_qty",
            "original_notional",
            "original_risk",
        ):
            if getattr(candidate, key) != getattr(self, key):
                raise ValueError("Original campaign field changed")
        for key in ("remaining_qty", "remaining_notional", "remaining_risk"):
            if getattr(candidate, key) > getattr(self, key):
                raise ValueError("Campaign ceiling increased")
        if candidate.version != self.version + 1:
            raise ValueError("Campaign version must rise by one")
        if candidate.reentry_count < self.reentry_count:
            raise ValueError("Campaign count cannot reset")
        return candidate


class EntrySeam(Protocol):
    def qualify(
        self,
        instrument_id: InstrumentId,
        *,
        now_ns: int,
        generation_key: str,
        sell: FastSellFacts | None,
    ) -> EnterIntent | None: ...


class SizingSeam(Protocol):
    def size(
        self, intent: EnterIntent, *, confidence_multiplier: Decimal | None, campaign: CampaignState
    ) -> Quantity | None: ...
