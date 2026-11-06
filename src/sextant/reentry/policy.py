"""ADR-0006's source-backed admission slice, not the absent R1-R6 detector port.

Carry: trading@8256c16c exit_manager/reentry.py, rotation_wiring.py,
signals.py:retry_allowed, portfolio/rotation.py; lanes@00203275944a contracts.
ADR-0006 supersedes the legacy one-retry, RTH-only and paper budget caps.
R3 qualification, component confidence and stop-out lifecycle stay external and
unavailable without their providers. No function submits or constructs orders.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from decimal import Decimal

from nautilus_trader.model import InstrumentId, Quantity

from sextant.reentry.contracts import (
    CampaignState,
    EnterIntent,
    EntrySeam,
    FastSellFacts,
    FlatReceipt,
    RankingView,
    SizingSeam,
    decimal,
    integer,
)

__all__ = [
    "CampaignState",
    "EnterIntent",
    "FastSellFacts",
    "FlatReceipt",
    "Lift",
    "Params",
    "Reentry",
]
NS = 1_000_000_000


@dataclass(frozen=True)
class Params:
    """No starts. Explicit fixture values prove mechanisms, never deployment authority."""

    cooldown_seconds: Decimal
    retry_rank_band: int
    rotation_rank_band: int
    reentry_min_confidence: Decimal
    confidence_size_floor: Decimal
    rotation_lift_margin_bps: Decimal
    rotation_score_ratio: Decimal
    whipsaw_stopouts_max: int

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name in {"retry_rank_band", "rotation_rank_band", "whipsaw_stopouts_max"}:
                if integer(value) < 1:
                    raise ValueError("Rank bands and stop-out threshold must be positive")
            else:
                decimal(value)
        if self.reentry_min_confidence > 1 or self.confidence_size_floor > 1:
            raise ValueError("Confidence thresholds must lie in [0, 1]")
        if self.rotation_score_ratio < 1:
            raise ValueError("Rotation ratio must be at least one")
        if self.cooldown_seconds * NS != int(self.cooldown_seconds * NS):
            raise ValueError("Cooldown must resolve to whole nanoseconds")

    @property
    def params_hash(self) -> str:
        # Same canonical Decimal JSON representation as lanes contracts.py:Params.
        values = {
            k: {"$decimal": str(v)} if isinstance(v, Decimal) else v
            for k, v in asdict(self).items()
        }
        return hashlib.sha256(
            json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class Lift:
    from_instrument_id: InstrumentId
    to_instrument_id: InstrumentId
    generation_key: str
    expected_lift: Decimal | None
    c_rt: Decimal
    price: Decimal


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str
    ts: int
    generation_key: str
    params_hash: str
    from_instrument_id: InstrumentId | None = None
    to_instrument_id: InstrumentId | None = None
    setup: str | None = None
    confidence: Decimal | None = None
    confidence_multiplier: Decimal | None = None
    quantity: Quantity | None = None
    count: int | None = None
    cooldown_started_ns: int | None = None
    reclaim_level: Decimal | None = None
    expected_lift: Decimal | None = None

    @property
    def executable(self) -> bool:
        return False  # Pinned rotation_wiring.RotationProposal's custody boundary.


class Reentry:
    def __init__(
        self, params: Params, *, entry: EntrySeam | None, sizer: SizingSeam | None, lane: str
    ):
        self.p, self.entry, self.sizer, self.lane = params, entry, sizer, lane
        self.journal: list[dict] = []
        # Source FocusReentry.prepare reserves before returning a draft. This
        # replay fence is in-memory only; durable restart ownership is row 8.
        self.reserved: set[tuple[str, InstrumentId, int]] = set()

    def _decision(self, kind: str, reason: str, now: int, key: str = "", **values) -> Decision:
        return Decision(kind, reason, now, key, self.p.params_hash, **values)

    @staticmethod
    def _key(ranking: RankingView | None, now: int) -> str | None:
        if ranking is None:
            return None
        try:
            key, known, fresh = ranking.generation_key, ranking.known_at, ranking.fresh
            if (
                isinstance(key, str)
                and key
                and type(known) is int
                and 0 <= known <= now
                and fresh is True
            ):
                return key
        except (ValueError, TypeError, AttributeError):
            pass
        return None

    def _lane_ok(self, campaign: CampaignState) -> bool:
        return (
            self.lane in {"alpaca-paper-a", "alpaca-paper-b", "alpaca-paper-c", "replay"}
            and campaign.mode == "paper_unbounded"
        )

    def _entry(
        self,
        iid: InstrumentId,
        now: int,
        key: str,
        sell: FastSellFacts | None,
        *,
        same: bool,
        stopouts: int,
    ) -> tuple[EnterIntent | None, str]:
        if self.entry is None:
            return None, "entry_provider_unavailable"
        intent = self.entry.qualify(iid, now_ns=now, generation_key=key, sell=sell)
        if intent is None:
            return None, "entry_not_qualified"
        if intent.instrument_id != iid or intent.ts != now or intent.generation_key != key:
            return None, "entry_generation_mismatch"
        if intent.setup not in {"FIRST_LEG", "RECLAIM", "BREAKOUT", "OVERSELL"}:
            return None, "setup_unavailable"
        if intent.labels.get("confirmation") == "first_print":
            return None, "first_print_shadow_only"
        if intent.labels.get("catalyst_polarity") == "negative":
            return None, "negative_catalyst"
        if intent.setup == "OVERSELL":
            return None, "oversell_detector_unavailable"
        if intent.setup == "BREAKOUT" and intent.labels.get("extension") != "NOT_EXTENDED":
            return None, "extension_unknown_or_extended"
        if same:
            if intent.confidence is None:
                return None, "missing_confidence"
            if intent.confidence < self.p.reentry_min_confidence:
                return None, "confidence_below_minimum"
            if intent.setup not in {"RECLAIM", "BREAKOUT"}:
                return None, "same_symbol_needs_reclaim_or_breakout"
            if stopouts >= self.p.whipsaw_stopouts_max and intent.setup != "RECLAIM":
                return None, "whipsaw_needs_capped_reclaim"
        elif intent.confidence is None and intent.setup != "FIRST_LEG":
            return None, "unscored_rotation_requires_fresh_first_leg"
        if intent.setup == "RECLAIM" and intent.labels.get("confirmation") != "retest":
            return None, "held_retest_not_confirmed"
        return intent, "qualified_by_entry_seam"

    def after_sell(
        self,
        *,
        now_ns: int,
        ranking: RankingView | None,
        sell: FastSellFacts,
        required_lineage: tuple[str, ...] | None,
        candidates: tuple[InstrumentId, ...],
        held: tuple[InstrumentId, ...],
        campaign: CampaignState,
        stopouts: int,
    ) -> Decision:
        integer(now_ns)
        integer(stopouts)
        key = self._key(ranking, now_ns)
        if not self._lane_ok(campaign):
            return self._decision("WAIT", "live_or_ibkr_reentry_off", now_ns)
        if key is None:
            return self._decision("WAIT", "ranking_unavailable", now_ns)
        flat = sell.flat_receipt
        if (
            flat is None
            or flat.instrument_id != sell.instrument_id
            or sell.instrument_id in held
            or campaign.current_instrument_id != sell.instrument_id
            or not sell.sell_ts <= flat.ts <= now_ns
            or not required_lineage
            or len(set(required_lineage)) != len(required_lineage)
            or not set(required_lineage) <= set(flat.terminal_order_ids)
        ):
            return self._decision("WAIT", "flat_lineage_unavailable", now_ns, key)
        if now_ns < flat.ts + int(self.p.cooldown_seconds * NS):
            return self._decision("WAIT", "cooldown", now_ns, key)
        reservation = (campaign.campaign_id, sell.instrument_id, flat.ts)
        if reservation in self.reserved:
            return self._decision("WAIT", "flat_receipt_already_reserved", now_ns, key)
        if len(set(candidates)) != len(candidates) or len(set(held)) != len(held):
            return self._decision("WAIT", "ambiguous_membership", now_ns, key)
        assert ranking is not None
        try:
            ranks = {
                iid: ranking.rank_of(iid.symbol.value) for iid in (*candidates, sell.instrument_id)
            }
        except (ValueError, TypeError, AttributeError):
            return self._decision("WAIT", "ranking_unavailable", now_ns, key)
        if any(rank is not None and (type(rank) is not int or rank < 1) for rank in ranks.values()):
            return self._decision("WAIT", "invalid_rank", now_ns, key)
        retry_rank = ranks.get(sell.instrument_id)
        choices = []
        if (
            retry_rank is not None
            and retry_rank <= self.p.retry_rank_band
            and sell.instrument_id not in held
        ):
            choices.append(sell.instrument_id)
        alternatives = [
            (iid, rank)
            for iid, rank in ranks.items()
            if iid in candidates
            and iid != sell.instrument_id
            and iid not in held
            and rank is not None
            and rank <= self.p.rotation_rank_band
        ]
        choices.extend(
            iid for iid, _ in sorted(alternatives, key=lambda row: (row[1], str(row[0])))
        )
        refusal = "no_qualified_choice"
        for iid in choices:
            if self._key(ranking, now_ns) != key:
                return self._decision("WAIT", "ranking_generation_changed", now_ns, key)
            same = iid == sell.instrument_id
            intent, reason = self._entry(
                iid,
                now_ns,
                key,
                sell if same else None,
                same=same,
                stopouts=stopouts if same else 0,
            )
            if intent is None:
                if refusal == "no_qualified_choice" or same:
                    refusal = reason
                continue
            if self._key(ranking, now_ns) != key:
                return self._decision("WAIT", "ranking_generation_changed", now_ns, key)
            if self.sizer is None:
                return self._decision("WAIT", "sizing_unavailable", now_ns, key)
            self.reserved.add(reservation)
            multiplier = (
                None
                if intent.confidence is None
                else (
                    self.p.confidence_size_floor
                    + (1 - self.p.confidence_size_floor) * intent.confidence
                )
            )
            qty = self.sizer.size(intent, confidence_multiplier=multiplier, campaign=campaign)
            if not isinstance(qty, Quantity) or qty.as_decimal() <= 0:
                return self._decision("WAIT", "sizing_refused", now_ns, key)
            if self._key(ranking, now_ns) != key:
                return self._decision("WAIT", "ranking_generation_changed", now_ns, key)
            count = campaign.reentry_count + 1
            decision = self._decision(
                "REENTER" if same else "ROTATE",
                "fixture_seam_proposal",
                now_ns,
                key,
                from_instrument_id=sell.instrument_id,
                to_instrument_id=iid,
                setup=intent.setup,
                confidence=intent.confidence,
                confidence_multiplier=multiplier,
                quantity=qty,
                count=count,
                cooldown_started_ns=flat.ts,
                reclaim_level=sell.sell_trigger if same and intent.setup == "RECLAIM" else None,
            )
            self.journal.append(
                {
                    "count": count,
                    "setup": intent.setup,
                    "generation_key": key,
                    "cooldown_started_ns": flat.ts,
                    "reclaim_level": str(decision.reclaim_level),
                    "expected_lift": None,
                    "params_hash": self.p.params_hash,
                }
            )
            return decision
        return self._decision("WAIT", refusal, now_ns, key)

    def held_rotation(
        self,
        *,
        now_ns: int,
        ranking: RankingView | None,
        campaign: CampaignState,
        held: tuple[InstrumentId, ...],
        weakest_id: InstrumentId | None,
        weakest_score: Decimal | None,
        target: InstrumentId,
        target_score: Decimal,
        lift: Lift | None,
    ) -> Decision:
        integer(now_ns)
        key = self._key(ranking, now_ns)
        if not self._lane_ok(campaign) or key is None:
            return self._decision("WAIT", "lane_or_ranking_unavailable", now_ns)
        if (
            weakest_id is None
            or weakest_id not in held
            or target in held
            or lift is None
            or lift.from_instrument_id != weakest_id
            or lift.to_instrument_id != target
            or lift.generation_key != key
            or lift.expected_lift is None
        ):
            return self._decision("WAIT", "pair_lift_unavailable", now_ns, key)
        try:
            decimal(weakest_score, positive=True)
            decimal(target_score, positive=True)
            decimal(lift.expected_lift)
            decimal(lift.c_rt)
            decimal(lift.price, positive=True)
        except ValueError:
            return self._decision("WAIT", "invalid_lift_or_score", now_ns, key)
        assert weakest_score is not None and ranking is not None
        threshold = 2 * lift.c_rt / lift.price + self.p.rotation_lift_margin_bps / 10_000
        if (
            lift.expected_lift <= threshold
            or target_score < self.p.rotation_score_ratio * weakest_score
        ):
            return self._decision("WAIT", "insufficient_rotation_lift_or_score", now_ns, key)
        try:
            rank = ranking.rank_of(target.symbol.value)
        except (ValueError, TypeError, AttributeError):
            return self._decision("WAIT", "target_rank_unavailable", now_ns, key)
        if type(rank) is not int or not 1 <= rank <= self.p.rotation_rank_band:
            return self._decision("WAIT", "target_rank_unavailable", now_ns, key)
        intent, reason = self._entry(target, now_ns, key, None, same=False, stopouts=0)
        if intent is None or self._key(ranking, now_ns) != key:
            return self._decision("WAIT", reason, now_ns, key)
        return self._decision(
            "HELD_ROTATION",
            "flat_proof_required_before_entry",
            now_ns,
            key,
            from_instrument_id=weakest_id,
            to_instrument_id=target,
            expected_lift=lift.expected_lift,
            setup=intent.setup,
        )
