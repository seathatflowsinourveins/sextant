"""Native replay observer; emits no order and computes no after-cost comparison.

Seam: nautilus_trader@v2.0.0rc7 55c0e82053142bce3a5cba4de4221d3929c2d3bc
Strategy.subscribe_quotes/on_quote, as used by sextant.exits.engine. Providers
own ranking, positive custody receipts and qualified entry facts at each event.
"""

from collections.abc import Callable
from typing import Any

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import InstrumentId, QuoteTick
from nautilus_trader.trading import Strategy

from sextant.reentry.policy import Decision, Reentry


class ReentryReplayConfig(StrategyConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        controller: Reentry,
        provide: Callable[[QuoteTick], dict[str, Any]],
        **_kwargs: object,
    ):
        super().__init__()
        self.instrument_id, self.controller, self.provide = instrument_id, controller, provide


class ReentryReplay(Strategy):
    """Observer only, including when a fixture supplies an admitted intent."""

    def __init__(self, config: ReentryReplayConfig):
        super().__init__(config)
        self.instrument_id, self.controller, self.provide = (
            config.instrument_id,
            config.controller,
            config.provide,
        )
        self.decisions: list[Decision] = []

    def on_start(self) -> None:
        self.subscribe_quotes(self.instrument_id)

    def on_quote(self, quote: QuoteTick) -> None:
        if quote.instrument_id == self.instrument_id:
            self.decisions.append(
                self.controller.after_sell(now_ns=quote.ts_event, **self.provide(quote))
            )
