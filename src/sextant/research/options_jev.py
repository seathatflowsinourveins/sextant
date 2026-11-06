"""Row 13's data-only actors, following Nautilus rc7 docs/concepts/actors.md.

No Strategy or order methods. Experiment execution is unavailable pending the one
canonical TrialLog (#72); this module supplies components and a truthful status.
"""

from __future__ import annotations

import json

from nautilus_trader.common import DataActor
from nautilus_trader.config import DataActorConfig
from nautilus_trader.model import InstrumentId, QuoteTick

from sextant.judgments.catalyst import MODEL, SDK_VERSION, Capture, effect
from sextant.judgments.policy import Policy
from sextant.research.options import OptionsFactor


class ResearchObserverConfig(DataActorConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        options: tuple[OptionsFactor, ...],
        captures: tuple[Capture, ...],
        policy: Policy,
        enabled: bool = False,
        **_kwargs,
    ) -> None:
        super().__init__()
        if len({record.answer_label for record in captures}) > 1:
            raise ValueError("one answer label per arm; recalled and live-ledgered never pool")
        if len({record.request.source_version for record in captures}) != len(captures):
            raise ValueError("one recording per source revision required")
        self.instrument_id = instrument_id
        self.options, self.captures = tuple(options), tuple(captures)
        self.policy, self.enabled = policy, enabled


class ResearchObserver(DataActor):
    def __init__(self, config: ResearchObserverConfig) -> None:
        super().__init__(config)
        self.instrument_id = config.instrument_id
        self.options, self.captures = config.options, config.captures
        self.policy, self.enabled = config.policy, config.enabled
        self.observations: list[dict] = []

    def on_start(self) -> None:
        self.subscribe_quotes(self.instrument_id)

    def on_quote(self, quote: QuoteTick) -> None:
        if quote.instrument_id != self.instrument_id:
            return
        now = quote.ts_init
        known_options = [
            r
            for r in self.options
            if r.instrument_id == self.instrument_id and r.available_ns <= now
        ]
        known_answers = [
            r
            for r in self.captures
            if r.request.instrument_id == self.instrument_id and r.request.received_ns <= now
        ]
        # A newer source revision replaces the older one even if its answer is unavailable.
        latest = {}
        for record in sorted(
            known_answers,
            key=lambda r: (r.request.revision_ns, r.request.received_ns, r.request.content_sha256),
        ):
            latest[record.request.event_key] = record
        effects = [
            (record, effect(record, now, self.policy, enabled=self.enabled))
            for record in latest.values()
        ]
        # CatalystScreen.evaluate: any active negative wins; otherwise highest priority.
        shadow = next((result for _, result in effects if result.reason == "negative"), None)
        if shadow is None:
            shadow = max(
                (result for _, result in effects),
                key=lambda r: r.priority_multiplier,
                default=effect(None, now, self.policy, enabled=self.enabled),
            )
        options = {}
        for option in sorted(known_options, key=lambda r: r.available_ns):
            options[option.source, option.metric] = option
        self.observations.append(
            {
                "ts_init": now,
                "options_factors": [
                    {
                        "metric": r.metric,
                        "value": None if r.value is None else str(r.value),
                        "source": r.source,
                        "revision": r.revision,
                        "evidence_sha256": r.evidence_sha256,
                        "available_ns": r.available_ns,
                    }
                    for r in options.values()
                ],
                "options_weight": "0",
                "order_authority": False,
                "jev_reason": shadow.reason,
                "shadow_allowed": shadow.allowed,
                "shadow_priority": str(shadow.priority_multiplier),
                "jev_records": [
                    {"capture": record.to_json(), "reason": result.reason}
                    for record, result in effects
                ],
                "params_hash": self.policy.params_hash,
            }
        )


def simulation_status() -> dict:
    return {
        "simulation": "NOT_RUN",
        "ledger_binding": "NOT_RUN",
        "order_authority": False,
        "reason": (
            "Canonical TrialLog and arm registration/driver binding pending #72; no trials run"
        ),
        "model": MODEL,
        "sdk_version": SDK_VERSION,
        "model_quality": "UNVERIFIED",
        "training_cutoff": "UNVERIFIED",
        "after_cost_lift": "UNVERIFIED",
    }


if __name__ == "__main__":
    print(json.dumps(simulation_status(), sort_keys=True))
