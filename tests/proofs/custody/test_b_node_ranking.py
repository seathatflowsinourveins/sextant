"""LEAD-1452 part 3a: native ranking heartbeat ingress to B, offline only."""

from dataclasses import replace
from datetime import date

import pytest

from sextant.ranking import node_ranking, registry
from sextant.ranking.node_session import SegmentedHost
from sextant.ranking.registry import ENTRY_ROWS, RegistryRow

KEY_NAME = "FIXTURE_VARIABLE_NAME"


def ages():
    return tuple(
        RegistryRow(n, "seconds", 2, "synthetic fixture only", "UNCALIBRATED", date(2026, 11, 11))
        for n in ENTRY_ROWS
    )



def replay(tmp_path, *, mid=False, gap=False):
    """The production attach function and B receiver on a native offline engine."""
    from decimal import Decimal

    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import AccountType, CustomData, Money, OmsType, Venue
    from test_ranking import NS, SCOPE, START, baseline
    from test_ranking import registry as fixture_registry
    from test_ranking_actor import IDS, NAMES, equity, ticks
    from test_ranking_node_session import Regular, inputs

    from sextant.alpaca.config import AlpacaDataClientConfig
    from sextant.alpaca.stream_facts import AlpacaStreamGap, gap_type
    from sextant.paper.b_lifecycle import BLifecycle, BLifecycleConfig
    from sextant.ranking.consumer import RankingConsumer
    from sextant.ranking.publisher import universe_digest

    scope = replace(SCOPE, start_ns=START - 600 * NS) if mid else SCOPE
    ranked = node_ranking.RankingArguments(
        NAMES,
        "fixture",
        {"PRE": baseline()},
        fixture_registry(),
        400,
        tmp_path,
        3600,
        None,
        AlpacaDataClientConfig(feed="sip", api_key_env="FIXTURE", api_secret_env=KEY_NAME),
        node_ranking.RankingInputs(
            scope.session_date,
            START - NS,
            dict.fromkeys(NAMES, Decimal("0.50")),
            dict.fromkeys(NAMES, "common"),
            "fixture",
            "fixture",
        ),
    )
    entry = RankingConsumer(
        registry=ranked.registry,
        feed="sip",
        segment=scope,
        universe_hash=universe_digest(NAMES),
        baseline_hash=baseline().identity,
        **registry.entry_ages(ages()),
    )
    events = []

    class Reader(BLifecycle):
        def on_data(self, data):
            super().on_data(data)
            events.append(("generation", self.clock.timestamp_ns()))

        def on_signal(self, signal):
            super().on_signal(signal)
            events.append(("heartbeat", self.clock.timestamp_ns()))

    strategy = Reader(
        BLifecycleConfig(
            namespace="BTEST",
            instrument_ids=(IDS[-1],),
            consumer=entry,
            rank_gate=registry.RANK_GATE_ENABLED,
        )
    )
    engine = BacktestEngine(BacktestEngineConfig(bypass_logging=True, run_analysis=False))
    engine.add_venue(
        Venue("ALPACA"),
        OmsType.NETTING,
        AccountType.CASH,
        [Money.from_str("100000 USD")],
        fee_model=MakerTakerFeeModel(Decimal(0), Decimal(0)),
    )
    for iid in IDS:
        engine.add_instrument(equity(iid))
    engine.add_strategy(strategy)
    actor = node_ranking.attach(engine, ranked, inputs=inputs, segment_of=lambda _: scope)
    actor._facts = Regular("sip")  # recorded fixture prints carry explicit regular conditions
    engine.add_data(ticks())
    if gap:
        at = START + 200 * NS
        engine.add_data([CustomData(gap_type("sip"), AlpacaStreamGap("sip", 1, at, at))])
    try:
        engine.run(start=START - NS, end=START + 360 * NS)
        assert actor.errors == {}
        assert not engine.cache.orders()
        return entry, events, actor
    finally:
        engine.dispose()



def test_native_generation_and_heartbeat_reach_b_consumer(tmp_path):
    from test_ranking import NS, START

    entry, events, actor = replay(tmp_path)
    assert entry.entry_rank("PENNY", now=START + 360 * NS) == 1
    assert sum(k == "generation" for k, _ in events) == 12
    assert actor.published == 13  # one pre-start publication precedes Strategy subscriptions
    assert any(k == "heartbeat" for k, _ in events)
    assert isinstance(actor.host, SegmentedHost)
    assert actor.host.observed is True



@pytest.mark.parametrize("case", ["mid", "gap"])
def test_segment_observation_vetoes_b_consumer(tmp_path, case):
    from test_ranking import NS, START

    entry, _, actor = replay(tmp_path, **{case: True})
    assert entry.entry_rank("PENNY", now=START + 360 * NS) is None
    assert isinstance(actor.host, SegmentedHost)
    assert actor.host.observed is False



@pytest.mark.parametrize("which", ["generation", "heartbeat"])
def test_native_consumer_ages_veto(tmp_path, which):
    from test_ranking import NS, START

    entry, _, _ = replay(tmp_path)
    at = START + 360 * NS
    # Keep the reader's broader display ages fresh while the entry-specific age expires.
    entry.reader.registry = replace(
        entry.reader.registry,
        rows=tuple(
            replace(r, value=10) if r.name.endswith("max_age_s") else r
            for r in entry.reader.registry.rows
        ),
    )
    if which == "generation":
        entry.accept_heartbeat(at=at + 3 * NS, received_ns=at + 3 * NS)
    assert entry.entry_rank("PENNY", now=at + 3 * NS) is None
    assert entry.reason == f"entry_{which}_stale"

