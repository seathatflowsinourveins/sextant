"""Shared ranking/reader context using #104's actual pinned XNYS calendar.

Session policy is the owning paper.sessions slice, not a new calendar. Only
synthetic cases supply complete curves/reference/asset/heartbeat fixtures.
The recorded arm preserves missing source authority and never backfills it.
"""

import importlib
from datetime import datetime, time, timedelta
from decimal import Decimal

from nautilus_trader.common import MessageBus
from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model import CustomData, TraderId

from sextant.ranking.baseline import BaselineSample, BaselineTable
from sextant.ranking.engine import ReferencePrices, Segment
from sextant.ranking.generation import Coverage, CoverageState
from sextant.ranking.publisher import AssetState, RankingPublisher, ranking_data_type
from sextant.ranking.reader import GenerationReader
from sextant.sandbox.profile import ranking_registry


class MarketStack:
    def __init__(self, account):
        self.account = account
        self.registry = ranking_registry(account.profile)
        self.bus = MessageBus(TraderId(f"{account.binding.client_id}-001"))
        self.segment = self.publisher = self.reader = None
        self.key = None

    def at(self, now: int):
        sessions = importlib.import_module("sextant.paper.sessions")
        session = sessions.session_at(now)
        if session not in {sessions.Session.PRE, sessions.Session.RTH, sessions.Session.POST}:
            self.segment = self.publisher = self.reader = self.key = None
            self.account.counts["unsupported_or_closed_session"] += 1
            return None
        local = datetime.fromtimestamp(now // 1_000_000_000, tz=sessions.ET)
        day = local.date()
        calendar = sessions._calendar(day.year)
        opening = int(calendar.session_open(day).value)
        closing = int(calendar.session_close(day).value)

        def bound(hour):
            return dt_to_unix_nanos(datetime.combine(day, time(hour), sessions.ET))

        start, end = {
            sessions.Session.PRE: (bound(4), opening),
            sessions.Session.RTH: (opening, closing),
            sessions.Session.POST: (closing, bound(17 if closing < bound(16) else 20)),
        }[session]
        key = day.isoformat(), session.value
        if self.key == key:
            return self.segment
        self.key = key
        self.segment = Segment(
            session.name,
            day,
            start,
            end,
            "paper.sessions XNYS calendar 4.13.2; recorded event clock",
        )
        names = tuple(
            sorted(instrument.id.symbol.value for instrument in self.account.instruments.values())
        )
        synthetic = self.account.case != "recorded"
        samples = (
            tuple(
                BaselineSample(
                    name,
                    session.name,
                    (day - timedelta(days=1)).isoformat(),
                    offset,
                    Decimal(amount),
                    Decimal(count),
                )
                for name in names
                for offset, amount, count in ((0, 0, 0), (600, 100, 100))
            )
            if synthetic
            else ()
        )
        baseline = BaselineTable(
            samples,
            "FIXTURE complete curve" if synthetic else "UNAVAILABLE historical curve",
            start - 1,
            "sip",
        )
        self.publisher = RankingPublisher(
            bus=self.bus,
            epoch=f"{self.account.binding.arm_id}:{day}:{session.value}",
            feed="sip",
            segment=self.segment,
            registry=self.registry,
            universe=names,
            universe_source="FIXTURE selected universe"
            if synthetic
            else "#41 selected 54; NOT PIT universe",
            baseline=baseline,
        )
        if synthetic:
            self.publisher.set_coverage(
                Coverage(CoverageState.READY, True, len(names), len(names), 0, 0, 0)
            )
        for name in names:
            self.publisher.set_symbol(
                name,
                references=ReferencePrices(
                    Decimal("10.00") if synthetic else None,
                    start - 1,
                    "FIXTURE close" if synthetic else "UNAVAILABLE close",
                ),
                asset=AssetState(start - 1, end, False, "common", "FIXTURE asset")
                if synthetic
                else None,
            )
        self.reader = GenerationReader(
            self.registry,
            feed="sip",
            segment=self.segment,
            universe_hash=self.publisher.universe_hash,
            baseline_hash=baseline.identity,
            alarm=lambda reason: self.account.counts.update(["ranking_refusals"]),
        )
        self.account.counts["ranking_contexts"] += 1
        return self.segment

    def publish(self, now: int):
        if self.publisher is None or self.reader is None:
            return
        generation = self.publisher.publish(now=now)
        if generation is None:
            return
        self.account.counts["ranking_publications"] += 1
        self.reader.accept_generation(CustomData(ranking_data_type("sip"), generation), now=now)
        if self.account.case != "recorded":
            self.reader.accept_heartbeat(
                at=now, received_ns=now
            )  # explicitly MODELED local publisher

    def rank(self, symbol: str, now: int):
        self.account.counts["ranking_admission_checks"] += 1
        return None if self.reader is None else self.reader.entry_rank(symbol, now=now)
