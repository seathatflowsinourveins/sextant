"""The ranking host inside the account's engine node (LEAD-2325 2c, part N1).

NautilusTrader's shape at the manifest pin: a live node hosts the data client, and a
``DataActor`` carries non-trading logic (docs/concepts/actors.md:1-13). ``on_start`` builds
the host on the node's thread, which the host binds (8850b79 ranking/host.py:132, 169-171),
primes coverage and every universe name, and only then subscribes trade ticks
(``subscribe_trades``). Each tick goes to ``host.on_trade``; each generation it returns is
published with ``publish_data`` as ``ranking_data_type(feed)``, the type a Strategy in the
node takes by ``subscribe_data`` (docs/concepts/message_bus.md:55-65, 180-232). The Actor
opens no socket: the node's data client owns the one market-data socket. An exception from
the host, the priming source or a publish is counted and paged once per stage and type and
never leaves a handler, so neither the Actor nor the data client stops. The Actor holds no
switch or registry row; the priming source is read at start, never at construction.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from nautilus_trader.common import DataActor
from nautilus_trader.config import DataActorConfig
from nautilus_trader.model import CustomData, InstrumentId, TradeTick

from sextant.ranking.engine import ReferencePrices
from sextant.ranking.generation import Coverage, RankingGeneration
from sextant.ranking.publisher import AssetState, ranking_data_type

Page = Callable[[str, str], None]


class RankingHostProtocol(Protocol):
    """RankingHost's surface at 8850b79 (host.py:173-205), injected so N1 runs on main."""

    def on_trade(self, tick: TradeTick) -> RankingGeneration | None: ...

    def set_symbol(
        self, name: str, *, references: ReferencePrices, asset: AssetState | None
    ) -> None: ...

    def set_coverage(self, coverage: Coverage) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class Priming:
    """What the host needs before its first tick (HOST-FACTS 2.6): coverage and every name."""

    coverage: Coverage
    symbols: Mapping[str, tuple[ReferencePrices, AssetState | None]]


class RankingActorConfig(DataActorConfig):
    def __init__(
        self,
        *,
        instrument_ids: Sequence[InstrumentId],
        feed: str,
        host_factory: Callable[[], RankingHostProtocol],
        priming: Callable[[], Priming],
        page: Page | None = None,
        **_kwargs: object,
    ) -> None:
        super().__init__()
        ids = tuple(instrument_ids)
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("the ranking universe needs unique instrument ids")
        if not callable(host_factory) or not callable(priming):
            raise ValueError("the host factory and the priming source must be callables")
        self.instrument_ids, self.feed = ids, feed
        self.host_factory, self.priming, self.page = host_factory, priming, page


class RankingActor(DataActor):
    """Feeds one host from the node's trade ticks and publishes its generations."""

    def __init__(self, config: RankingActorConfig) -> None:
        super().__init__(config)
        self._ids, self._feed = config.instrument_ids, config.feed
        self._factory, self._priming, self._page = config.host_factory, config.priming, config.page
        self.host: RankingHostProtocol | None = None
        self.primed = False
        self.published = 0
        self.errors: dict[str, int] = {}
        self.last_error: str | None = None
        self._paged: set[tuple[str, str]] = set()

    def on_start(self) -> None:
        """Build, then prime, then subscribe: never a tick to an unprimed host."""
        try:
            self.host = self._factory()
        except Exception as exc:
            return self._fault("host_factory", exc)
        try:
            priming = self._priming()
            names = {str(iid.symbol) for iid in self._ids}
            if set(priming.symbols) != names:
                raise ValueError("priming must name exactly the universe")
            self.host.set_coverage(priming.coverage)
            for name in sorted(names):
                references, asset = priming.symbols[name]
                self.host.set_symbol(name, references=references, asset=asset)
        except Exception as exc:
            return self._fault("priming", exc)
        self.primed = True
        self.subscribe_trades(list(self._ids))

    def on_trade(self, trade: TradeTick) -> None:
        host = self.host
        if host is None or not self.primed:
            return
        try:
            generation = host.on_trade(trade)
        except Exception as exc:
            return self._fault("on_trade", exc)
        self._clear("on_trade")
        if generation is None:
            return
        data_type = ranking_data_type(self._feed)
        try:  # a DEGRADED veto is published too, so a consumer drops its names at once
            self.publish_data(data_type, CustomData(data_type, generation))
        except Exception as exc:
            return self._fault("publish", exc)
        self._clear("publish")
        self.published += 1

    def on_stop(self) -> None:
        if self.host is None:
            return
        try:
            self.host.close()
        except Exception as exc:
            self._fault("close", exc)

    def _fault(self, stage: str, exc: Exception) -> None:
        self.errors[stage] = self.errors.get(stage, 0) + 1
        kind = type(exc).__name__
        self.last_error = f"{stage}: {kind}"
        if (stage, kind) in self._paged or self._page is None:
            return
        self._paged.add((stage, kind))
        try:
            self._page(stage, kind)
        except Exception:  # a broken pager never stops the Actor either
            self.errors["page"] = self.errors.get("page", 0) + 1

    def _clear(self, stage: str) -> None:
        self._paged = {key for key in self._paged if key[0] != stage}
