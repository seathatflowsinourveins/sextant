"""LEAD-1452 part 3: B consumes native ranking and heartbeat on its existing node."""

from dataclasses import replace
from datetime import date

import pytest
from nautilus_trader.model import InstrumentId
from test_ranking_node_ranking import argv as ranking_argv

from sextant.paper import node_order
from sextant.ranking import node_ranking, registry
from sextant.ranking.node_session import SegmentedHost
from sextant.ranking.registry import ENTRY_ROWS, RegistryRow

from .test_b_order_node import TIMING, AccountVenue, Stand, argv

KEY_NAME = "FIXTURE_VARIABLE_NAME"


def ages():
    return tuple(
        RegistryRow(n, "seconds", 2, "synthetic fixture only", "UNCALIBRATED", date(2026, 11, 11))
        for n in ENTRY_ROWS
    )


def prepared(tmp_path):
    root = tmp_path / "rank"
    root.mkdir()
    ranked, _ = node_ranking.parse(ranking_argv(root))
    flags = [
        *argv(tmp_path),
        "--ranking-universe-artifact",
        str(root / "universe.json"),
        "--ranking-baseline-dir",
        str(root / "baselines"),
        "--ranking-inputs-dir",
        str(root / "ranking-inputs"),
    ]
    args = node_order.parse(flags)
    return replace(args, universe=(InstrumentId.from_str("AAPL.ALPACA"),), ranking=ranked)


def test_absent_ages_preserve_default_node_and_refusals(tmp_path):
    args = node_order.parse(argv(tmp_path))
    assert args.ranking is None
    args = replace(args, universe=node_order.read_universe(args.universe_artifact)[0])
    stand = Stand(AccountVenue())
    node, strategy = node_order.build(
        args, consumer=None, data_factory=stand.data, exec_factory=stand.exec, timing=TIMING
    )
    try:
        assert strategy.consumer is None
        assert "ranking_consumer" in strategy.missing
        assert strategy.rank_gate.value is False
    finally:
        node.dispose()


@pytest.mark.parametrize("missing", list(ENTRY_ROWS))
@pytest.mark.parametrize("unsourced", [False, True])
def test_any_missing_or_unsourced_age_never_builds_consumer(
    tmp_path, monkeypatch, missing, unsourced
):
    rows = tuple(
        replace(r, source="") if unsourced and r.name == missing else r
        for r in ages()
        if unsourced or r.name != missing
    )
    monkeypatch.setattr(registry, "B_ENTRY_AGE_ROWS", rows)
    args = node_order.parse(argv(tmp_path))  # no priming paths: age refusal must come first
    assert args.ranking is None


def test_valid_ages_require_all_verified_ranking_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "B_ENTRY_AGE_ROWS", ages())
    with pytest.raises(node_order.OrderModeRefused, match="ranking"):
        node_order.parse(argv(tmp_path))


def test_rank_universe_must_include_claims_and_fit_startup_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "B_ENTRY_AGE_ROWS", ages())
    args = prepared(tmp_path)
    stand = Stand(AccountVenue())
    args = replace(args, universe=(InstrumentId.from_str("OTHER.ALPACA"),))
    with pytest.raises(node_order.OrderModeRefused, match="ranking_universe"):
        node_order.build(args, consumer=None, data_factory=stand.data, exec_factory=stand.exec)
    assert args.ranking is not None
    many = tuple(f"Z{i}" for i in range(1025))
    args = replace(args, universe=(), ranking=replace(args.ranking, universe=many))
    with pytest.raises(node_order.OrderModeRefused, match="ranking_capacity"):
        node_order.build(args, consumer=None, data_factory=stand.data, exec_factory=stand.exec)


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


def test_order_node_constructs_one_client_and_deduplicates_trade_subscriptions(
    tmp_path, monkeypatch
):
    import threading
    from types import SimpleNamespace

    from nautilus_trader.live.clients import DataClientFactory
    from test_ranking import NS

    from sextant.ranking.baseline import segment_start
    from sextant.ranking.node_actor import RankingActor
    from sextant.ranking.node_session import SegmentedHost

    monkeypatch.setattr(registry, "B_ENTRY_AGE_ROWS", ages())
    args = prepared(tmp_path)
    assert args.ranking is not None
    ranked = replace(args.ranking, universe=("AAPL", "ZA"))
    args = replace(args, ranking=ranked)
    # This build-only time selects the fixture's primable PRE session; LiveNode owns its clock.
    at = 1794387600 * NS  # 2026-11-11 04:00 New York
    segment = segment_start(at)[0]
    assert segment is not None and segment.name == "PRE"
    monkeypatch.setattr(node_order, "time", SimpleNamespace(time_ns=lambda: at))
    from .test_b_order_node import NUMBER

    monkeypatch.setenv(node_order.EXPECTED_FULL_ENV, NUMBER)
    stand, clients, actors = Stand(AccountVenue()), [], []

    class Data(DataClientFactory):
        @staticmethod
        def create(**kwargs):
            clients.append((kwargs["name"], kwargs["config"]))
            client = stand.data.create(**kwargs)

            async def statuses(command):
                pass

            client._subscribe_instrument_status = statuses
            return client

    original = node_ranking.attach

    def attach(*a, **kw):
        actor = original(*a, **kw)
        actors.append(actor)
        return actor

    monkeypatch.setattr(node_ranking, "attach", attach)
    node, strategy = node_order.build(
        args, consumer=None, data_factory=Data, exec_factory=stand.exec, timing=TIMING
    )
    timer = threading.Timer(2, node.handle().stop)
    try:
        timer.start()
        node.run()
        assert strategy.gate.open
        assert strategy.consumer is not None
        assert strategy.rank_gate.value is False
        assert len(actors) == 1 and isinstance(actors[0], RankingActor)
        assert isinstance(actors[0].host, SegmentedHost)
        assert len(clients) == 1 and clients[0][0] == "ALPACA"
        assert set(clients[0][1].instrument_provider.load_ids) == {"AAPL.ALPACA", "ZA.ALPACA"}
        assert tuple(map(str, strategy._config.instrument_ids)) == ("AAPL.ALPACA",)
        assert stand.connected == 1 and stand.subscribed == 2
        assert all(r[0] == "GET" for r in stand.venue.requests)
    finally:
        timer.cancel()
        node.dispose()
