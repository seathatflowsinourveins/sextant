"""ADR-0003 publisher host: one in-process K2 publisher on the lane's own feed.

One ``RankingPublisher`` per segment (``publisher.py:67``; a source/session
change refuses reuse, ``engine.py:130-131``) publishes the existing
``CustomData(RankingGeneration)`` on ``ranking_data_type(feed)`` (view=full)
to the merged ``RankingConsumer`` over one in-process ``MessageBus``. The bus
is thread-local at the rc8 pin, so the caller constructs this host and calls
``on_trade`` on the feed thread; no stream, socket or order surface exists
here (ADR-0003:13 keeps the existing single SIP socket; :27 forbids a
second). References, halt state and coverage arrive only through the
publisher's existing setters (``publisher.py:102,109``); the host computes
none of them. Entry is fail-closed: until every universe symbol has traded
and carries an eligible asset beside an honestly supplied READY coverage,
every publication is DEGRADED and the consumer returns no rank.

The heartbeat is a seam, not an emitter: after each READY publication the
host calls the one injected callable with the published generation. Both
unmerged PR 3 builds expose that shape as ``HeartbeatEmitter.emit`` (the
host, not the publisher, owns the one call, so construct the publisher side
without its own emitter); the emitter's sink takes the reader's exact
``accept_heartbeat(at=..., received_ns=...)`` fields (``reader.py:52``).
This module starts no timer and manufactures no heartbeat (``reader.py:3``).

From its first run the host also appends one JSON line per published
generation and per heartbeat call under the caller-supplied session state
directory (outside git). The record only observes the two interval series;
it computes and registers no threshold, age or default. The directory is
reserved by its epoch, calls refuse from any thread but the constructing
one (the bus aborts across threads), and a DEGRADED veto is never throttled.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from nautilus_trader.common import MessageBus
from nautilus_trader.model import TraderId, TradeTick

from sextant.ranking.baseline import BaselineTable
from sextant.ranking.consumer import RankingConsumer, RawBusHost
from sextant.ranking.engine import ReferencePrices, Segment
from sextant.ranking.generation import Coverage, CoverageState, RankingGeneration
from sextant.ranking.publisher import AssetState, RankingPublisher
from sextant.ranking.registry import Registry

INTERVALS_NAME = "ranking-intervals.jsonl"
EPOCH_NAME = "ranking-epoch.json"


class IntervalLog:
    """Append-only generation/heartbeat interval record; failures never stop the feed."""

    def __init__(
        self,
        path: Path,
        *,
        wall_ns: Callable[[], int] = time.time_ns,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._path, self._wall_ns, self._monotonic_ns = path, wall_ns, monotonic_ns
        self._closed = False
        self.write_errors = 0

    def generation(self, generation: RankingGeneration) -> None:
        self._write("generation", generation, heartbeat_at=None, delivered=None, error=None)

    def heartbeat(
        self, generation: RankingGeneration, *, delivered: bool, error: str | None
    ) -> None:
        self._write(
            "heartbeat",
            generation,
            heartbeat_at=generation.known_at,
            delivered=delivered,
            error=error,
        )

    def _write(self, kind, generation, *, heartbeat_at, delivered, error) -> None:
        if self._closed:
            self.write_errors += 1
            return
        row = {
            "kind": kind,
            "wall_ns": self._wall_ns(),
            "monotonic_ns": self._monotonic_ns(),
            "producer_epoch": generation.generation_id.producer_epoch,
            "sequence": generation.generation_id.sequence,
            "generation_ns": generation.known_at,
            "publication_ns": generation.ts_init,
            "heartbeat_at": heartbeat_at,
            "delivered": delivered,
            "error": error,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
        except Exception:
            self.write_errors += 1

    def close(self) -> None:
        self._closed = True


class RankingHost:
    """Feed-thread owner of one segment's publisher, consumer and records."""

    def __init__(
        self,
        *,
        epoch: str,
        feed: str,
        segment: Segment,
        registry: Registry,
        universe: tuple[str, ...],
        universe_source: str,
        baseline: BaselineTable,
        entry_heartbeat_max_age_s: int,
        entry_generation_max_age_s: int,
        entry_input_max_age_s: int,
        state_dir: Path,
        heartbeat: Callable[[RankingGeneration], bool | None] | None = None,
        alarm: Callable[[str, str | None], None] | None = None,
        clock: Callable[[], int] = time.time_ns,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._thread = threading.get_ident()
        state_dir.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(state_dir / EPOCH_NAME, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise ValueError("state directory already reserved by another ranking host") from None
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps({"producer_epoch": epoch}, sort_keys=True))
        self.publisher = RankingPublisher(
            bus=MessageBus(TraderId.from_str("RANKING-001")),
            epoch=epoch,
            feed=feed,
            segment=segment,
            registry=registry,
            universe=universe,
            universe_source=universe_source,
            baseline=baseline,
        )
        self.consumer = RankingConsumer(
            registry=registry,
            feed=feed,
            segment=segment,
            universe_hash=self.publisher.universe_hash,
            baseline_hash=baseline.identity,
            entry_heartbeat_max_age_s=entry_heartbeat_max_age_s,
            entry_generation_max_age_s=entry_generation_max_age_s,
            entry_input_max_age_s=entry_input_max_age_s,
            alarm=alarm,
        )
        RawBusHost(self.consumer, clock=clock).subscribe(self.publisher.bus)
        self.intervals = IntervalLog(
            state_dir / INTERVALS_NAME, wall_ns=clock, monotonic_ns=monotonic_ns
        )
        self._heartbeat, self._clock, self._alarm = heartbeat, clock, alarm
        self.ingress_errors = self.publish_errors = self.heartbeat_errors = self.alarm_errors = 0
        self.last_error: str | None = None

    def _require_thread(self) -> None:
        if threading.get_ident() != self._thread:
            raise RuntimeError("RankingHost is bound to its constructing thread")

    def set_symbol(
        self, name: str, *, references: ReferencePrices, asset: AssetState | None
    ) -> None:
        def update() -> None:
            previous = self.publisher.references.get(name)
            self.publisher.set_symbol(name, references=references, asset=asset)
            if previous != references:
                self.publisher.states[name] = replace(self.publisher.states[name], latest=None)

        self._update(update)

    def set_coverage(self, coverage: Coverage) -> None:
        self._update(lambda: self.publisher.set_coverage(coverage))

    def on_trade(self, tick: TradeTick) -> RankingGeneration | None:
        """Advance one full-universe trade, then publish; a bad trade only degrades."""
        return self._update(lambda: self.publisher.on_trade(tick))

    def _update(self, update: Callable[[], None]) -> RankingGeneration | None:
        self._require_thread()
        self.consumer.revoke()
        try:
            update()
        except Exception as exc:
            self.publisher.coverage = Coverage(CoverageState.DEGRADED, False)
            self.ingress_errors += 1
            self.last_error = type(exc).__name__
            self._page("ingress_error")
        return self._publish()

    def entry_rank(self, symbol: str, *, now: int) -> int | None:
        self._require_thread()
        return self.consumer.entry_rank(symbol, now=now)

    def ranked_names(self, *, now: int) -> tuple[str, ...]:
        self._require_thread()
        return self.consumer.ranked_names(now=now)

    def close(self) -> None:
        self._require_thread()
        self.intervals.close()

    def _publish(self) -> RankingGeneration | None:
        self._require_thread()
        self.consumer.revoke()
        publisher = self.publisher
        supplied, published_at = publisher.coverage, publisher.published_at
        try:
            now = self._clock()
            ready = (
                supplied.state is CoverageState.READY
                and supplied.complete is True
                and supplied.expected_symbols
                == supplied.observed_symbols
                == len(publisher.universe)
                and supplied.missing_symbols
                == supplied.invalid_symbols
                == supplied.late_symbols
                == 0
                and all(publisher.states[name].latest is not None for name in publisher.universe)
                and all(
                    (reference := publisher.references.get(name)) is not None
                    and reference.prior_close is not None
                    and type(reference.known_at) is int
                    and isinstance(reference.source, str)
                    and bool(reference.source)
                    and 0 <= reference.known_at <= now
                    for name in publisher.universe
                )
                and all(
                    (asset := publisher.assets.get(name)) is not None
                    and type(asset.known_at) is int
                    and type(asset.expires_at) is int
                    and isinstance(asset.source, str)
                    and asset.eligible(now)
                    for name in publisher.universe
                )
            )
            if not ready:
                publisher.set_coverage(Coverage(CoverageState.DEGRADED, False))
                publisher.published_at = None  # a veto publication is never throttled
            generation = publisher.publish(now=now)
        except Exception as exc:
            self.consumer.revoke()  # even a bus failure after consumer delivery revokes it
            publisher.published_at = published_at
            self.publish_errors += 1
            self.last_error = type(exc).__name__
            self._page("publish_error")
            return None
        finally:
            publisher.coverage = supplied
        if generation is None:
            return None
        self.intervals.generation(generation)
        emitted = generation.coverage
        if emitted.state is not CoverageState.READY or not emitted.complete:
            self._page("generation_degraded")
            return generation
        if self._heartbeat is not None:
            delivered, error = True, None
            try:
                delivered = self._heartbeat(generation) is True
            except Exception as exc:
                delivered, error = False, type(exc).__name__
                self.heartbeat_errors += 1
                self.last_error = error
            self.intervals.heartbeat(generation, delivered=delivered, error=error)
        return generation

    def _page(self, reason: str) -> None:
        if self._alarm is not None:
            try:
                self._alarm(reason, None)
            except Exception as exc:
                self.alarm_errors += 1
                self.last_error = type(exc).__name__
