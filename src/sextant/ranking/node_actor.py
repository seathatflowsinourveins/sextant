"""The ranking host inside the account's engine node (LEAD-2325 2c, part N1).

NautilusTrader's shape at the manifest pin: a live node hosts the data client, and a
``DataActor`` carries non-trading logic (docs/concepts/actors.md:1-13). ``on_start`` builds
the host on the node's thread, which the host binds (8850b79 ranking/host.py:132, 169-171),
primes coverage and every universe name, and only then subscribes trade ticks
(``subscribe_trades``). Each tick goes to ``host.on_trade``; each generation it returns is
published with ``publish_data`` as ``ranking_data_type(feed)``, the type a Strategy in the
node takes by ``subscribe_data`` (docs/concepts/message_bus.md:55-65, 180-232). The Actor
opens no socket: the node's data client owns the one market-data socket. An exception from
the host, the priming source or a publish is counted, never leaves a handler and pages at
most once per stage and type in each caller-set window, so neither the Actor nor the data
client stops. The Actor holds no switch or registry row; the priming source is read at
start, never at construction.

N1c: the universe's native instrument status (``subscribe_instrument_status``,
``InstrumentStatus.action``/``is_trading``) reaches the host through ``set_symbol`` with the
primed references kept; only a halting action or TRADING is classified, everything else is
an unknown halt state, so the ranking refuses the name (``AssetState.eligible`` needs
``halted is False``). A generation a setter returns is published at once, as for a trade.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from nautilus_trader.common import DataActor
from nautilus_trader.config import DataActorConfig
from nautilus_trader.model import (
    CustomData,
    InstrumentId,
    InstrumentStatus,
    MarketStatusAction,
    TradeTick,
)

from sextant.ranking.engine import ReferencePrices
from sextant.ranking.generation import Coverage, CoverageState, RankingGeneration
from sextant.ranking.publisher import AssetState, ranking_data_type

Page = Callable[[str, str], None]
# The engine's own DataActorConfig fields, the only keys the catch-all may carry: the
# documented config pattern passes them through to DataActorConfig.__new__
# (docs/concepts/actors.md:15-21; common stub :132-151). Any other key is refused by name.
ENGINE_FIELDS = frozenset({"actor_id", "log_events", "log_commands"})


def refuse_unknown(kwargs: Mapping[str, object], owner: str) -> None:
    unknown = sorted(set(kwargs) - ENGINE_FIELDS)
    if unknown:
        raise TypeError(f"{owner}() got unexpected keyword arguments {unknown}")


NS = 1_000_000_000
# rc8 crates/model/src/enums.rs:1034-1068: halted, paused, suspended, or not available for trading.
HALTED = frozenset(
    {
        MarketStatusAction.HALT,
        MarketStatusAction.PAUSE,
        MarketStatusAction.SUSPEND,
        MarketStatusAction.NOT_AVAILABLE_FOR_TRADING,
    }
)


def classify(status: InstrumentStatus) -> bool | None:
    """The asset's halt state: True, False only for TRADING not contradicted, else unknown."""
    if status.action in HALTED:
        return True
    if status.action == MarketStatusAction.TRADING and status.is_trading is not False:
        return False
    return None


class RankingHostProtocol(Protocol):
    """RankingHost's surface at 8850b79 (host.py:173-205), injected so N1 runs on main."""

    def on_trade(self, tick: TradeTick) -> RankingGeneration | None: ...

    def set_symbol(
        self, name: str, *, references: ReferencePrices, asset: AssetState | None
    ) -> RankingGeneration | None: ...

    def set_coverage(self, coverage: Coverage) -> RankingGeneration | None: ...

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
        page_window_s: int,
        page: Page | None = None,
        **kwargs: object,
    ) -> None:
        refuse_unknown(kwargs, type(self).__name__)
        super().__init__()
        ids = tuple(instrument_ids)
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("the ranking universe needs unique instrument ids")
        if not callable(host_factory) or not callable(priming):
            raise ValueError("the host factory and the priming source must be callables")
        self.instrument_ids, self.feed = ids, feed
        if type(page_window_s) is not int or page_window_s <= 0:
            raise ValueError("page_window_s must be a positive int the caller supplies")
        self.host_factory, self.priming, self.page = host_factory, priming, page
        self.page_window_s = page_window_s


def withheld(generation: RankingGeneration) -> RankingGeneration:
    """DEGRADED and unranked, as the publisher writes a not-ready generation (publisher.py)."""
    rows = tuple(
        replace(row, score=None, rank=None, completed=False, partial=True, focus_eligible=False)
        for row in generation.rows
    )
    coverage = replace(generation.coverage, state=CoverageState.DEGRADED, complete=False)
    return replace(generation, coverage=coverage, rows=rows)


class StaleGeneration(Exception):
    """A host returned a generation that does not advance the published lineage."""


class RankingActor(DataActor):
    """Feeds one host from the node's trade ticks and publishes its generations."""

    def __init__(self, config: RankingActorConfig) -> None:
        super().__init__(config)
        self._ids, self._feed = config.instrument_ids, config.feed
        self._factory, self._priming, self._page = config.host_factory, config.priming, config.page
        self._window_ns = config.page_window_s * NS
        self._primed: dict[str, tuple[ReferencePrices, AssetState | None]] = {}
        self.ignored_statuses = 0
        self.host: RankingHostProtocol | None = None
        self.primed = False
        self.published = 0
        self.errors: dict[str, int] = {}
        self.last_error: str | None = None
        self._paged: dict[str, int] = {}  # last page time per stage: a bounded key set (F6)
        self._lineage: tuple[str, int] | None = None  # the last published (epoch, sequence)
        self._retired: set[str] = set()
        self._last: RankingGeneration | None = None  # the last generation on the bus
        self._early: dict[str, InstrumentStatus] = {}  # statuses before priming (review F1)
        self._veto: dict[str, tuple[bool | None, int, str]] = {}  # unapplied statuses (F2)

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
            self._publish(self.host.set_coverage(priming.coverage))
            for name in sorted(names):
                references, asset = priming.symbols[name]
                self._publish(self.host.set_symbol(name, references=references, asset=asset))
            self._primed = dict(priming.symbols)
        except Exception as exc:
            return self._fault("priming", exc)
        self.primed = True
        for name in sorted(self._early):  # applied in name order, the latest per name
            self.on_instrument_status(self._early.pop(name))
        try:  # a registration failure faults and pages; the shared node runs on (review F4)
            self.subscribe_trades(list(self._ids))
            self.subscribe_instrument_status(list(self._ids))
        except Exception as exc:
            self._fault("subscribe", exc)

    def on_instrument_status(self, status: InstrumentStatus) -> None:
        """Map one status to the host, keeping that name's primed references and asset."""
        name = str(status.instrument_id.symbol)
        if not self.primed:
            if status.instrument_id in self._ids:
                self._early[name] = status  # kept, never dropped: applied once primed (F1)
            return
        if self.host is None or status.instrument_id not in self._ids or name not in self._primed:
            self.ignored_statuses += 1
            return
        why = f"instrument status {status.action.name}"
        self._apply(name, classify(status), status.ts_init, why)

    @property
    def vetoed(self) -> set[str]:
        return set(self._veto)

    def _apply(self, name: str, halted: bool | None, at: int, why: str) -> None:
        """One status into the host. If the host refuses it, the name is unknown until a retry
        succeeds, and every generation is withheld meanwhile (review F2)."""
        references, asset = self._primed[name]
        updated = (
            None  # no primed asset: the name stays ineligible (publisher.py AssetState)
            if asset is None
            else replace(asset, known_at=at, halted=halted, source=f"{asset.source}; {why}")
        )
        try:
            assert self.host is not None
            generation = self.host.set_symbol(name, references=references, asset=updated)
        except Exception as exc:
            self._veto[name] = (True if halted is True else None, at, why)
            self._fault("instrument_status", exc)
            return self._withdraw()
        self._veto.pop(name, None)
        self._publish(generation)

    def on_trade(self, trade: TradeTick) -> None:
        host = self.host
        if host is None or not self.primed:
            return
        for name in sorted(self._veto):  # retry an unapplied status before the next tick
            self._apply(name, *self._veto[name])
        try:
            generation = host.on_trade(trade)
        except Exception as exc:
            return self._fault("on_trade", exc)
        self._publish(generation)

    def _withdraw(self) -> None:
        """Republish the last generation in its withheld form at once, so a consumer drops the
        rank now rather than at its age bound (review P2). A DEGRADED copy is refused before
        the reader's sequence check (reader.py:110-116), so it never moves the lineage."""
        if self._last is None:
            return
        data_type = ranking_data_type(self._feed)
        try:
            self.publish_data(data_type, CustomData(data_type, withheld(self._last)))
        except Exception as exc:
            self._fault("publish", exc)

    def _publish(self, generation: RankingGeneration | None) -> None:
        """A returned generation reaches the node bus at once; None publishes nothing."""
        if generation is None or not self._advances(generation):
            return
        if self._veto:  # an unapplied status: the publisher's own not-ready form, every row
            generation = withheld(generation)
        data_type = ranking_data_type(self._feed)
        try:  # a DEGRADED veto is published too, so a consumer drops its names at once
            self.publish_data(data_type, CustomData(data_type, generation))
        except Exception as exc:
            return self._fault("publish", exc)
        identity = generation.generation_id
        self._lineage = (identity.producer_epoch, identity.sequence)
        self._last = generation
        self.published += 1

    def _advances(self, generation: RankingGeneration) -> bool:
        """Only a generation past the last published one leaves (review F3; reader.py:220-235)."""
        identity, last = generation.generation_id, self._lineage
        epoch, sequence = identity.producer_epoch, identity.sequence
        if epoch in self._retired or (
            last is not None and epoch == last[0] and sequence <= last[1]
        ):
            self._fault("lineage", StaleGeneration(f"{epoch}/{sequence}"))
            return False
        if last is not None and epoch != last[0]:
            self._retired.add(last[0])
        return True

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
        now, last = self.clock.timestamp_ns(), self._paged.get(stage)
        if self._page is None or (last is not None and now - last < self._window_ns):
            return  # at most one page per stage in each window, whatever the error type
        self._paged[stage] = now
        try:
            self._page(stage, kind)
        except Exception:  # a broken pager never stops the Actor either
            self.errors["page"] = self.errors.get("page", 0) + 1
