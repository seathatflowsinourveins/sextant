from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest
from nautilus_trader.live import LiveNodeConfig
from nautilus_trader.model import TradeTick
from test_ranking import NS, SCOPE, START, baseline, registry
from test_ranking_actor import NAMES, ticks
from test_ranking_node_ranking import argv
from test_ranking_node_session import inputs as fixture_inputs

from sextant.ranking import node_ranking
from sextant.ranking.baseline import dump_baseline
from sextant.ranking.engine import ReferencePrices, Segment
from sextant.ranking.generation import Coverage, CoverageState
from sextant.ranking.node_actor import RankingActor
from sextant.ranking.node_session import SegmentedHost, SegmentInputs
from sextant.ranking.publisher import AssetState
from sextant.paper.sessions import ET
from sextant.tradingview.producer import reserve_stream


def tick_at(timestamp: int) -> TradeTick:
    original = ticks()[-1]
    return TradeTick(
        original.instrument_id,
        original.price,
        original.size,
        original.aggressor_side,
        original.trade_id,
        timestamp,
        timestamp,
    )


def host_at(tmp_path: Path, segment_of, source=fixture_inputs):
    clock = [START - NS]
    host = SegmentedHost(
        feed="sip",
        universe=NAMES,
        universe_source="offline review fixtures only",
        registry=registry(),
        inputs=source,
        segment_of=segment_of,
        clock=lambda: clock[0],
        receipt_dir=tmp_path,
    )
    return host, clock


def pair():
    first = replace(SCOPE, end_ns=START + 300 * NS)
    second = Segment("RTH", first.session_date, first.end_ns, SCOPE.end_ns, "fixture")
    return first, second


def test_refuse_baselines_with_another_universe_digest(tmp_path):
    from test_ranking_inputs import Daily

    from sextant.data import ranking_inputs

    arguments = argv(tmp_path)
    path = tmp_path / "baselines" / "manifest.json"
    manifest = json.loads(path.read_text())
    universe = tmp_path / "universe.json"
    manifest["universe"] = {"path": str(universe), "sha256": hashlib.sha256(universe.read_bytes()).hexdigest()}
    manifest["symbols"] = ["AAPL"]
    path.write_text(json.dumps(manifest))
    universe.write_text(json.dumps({"rows": [{"symbol": "AAPL"}, {"symbol": "IBM"}]}))
    ranking_inputs.produce(tmp_path / "ranking-inputs", universe_artifact=universe, listings_dir=tmp_path / "listings", session=date(2026, 11, 11), daily=Daily({"AAPL": Decimal("10.50"), "IBM": Decimal("200.25")}))
    with pytest.raises(node_ranking.RankingRefused, match="baseline.*universe"):
        node_ranking.parse(arguments)


def test_refuse_a_manifest_verified_baseline_from_the_wrong_feed(tmp_path):
    arguments = argv(tmp_path)
    path = tmp_path / "baselines" / "pre.json"
    text = dump_baseline(baseline(feed="boats"))
    path.write_text(text)
    manifest_path = path.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][path.name]["sha256"] = hashlib.sha256(text.encode()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(node_ranking.RankingRefused, match="baseline"):
        node_ranking.parse(arguments)


@pytest.mark.parametrize("gap_first", [False, True])
def test_boundary_gap_degrades_new_segment_in_either_order(tmp_path, gap_first):
    first, second = pair()
    host, clock = host_at(tmp_path, lambda timestamp: first if timestamp < first.end_ns else second)
    clock[0] = START
    host.on_clock(clock[0])
    clock[0] = second.start_ns
    if gap_first:
        host.set_coverage(Coverage(CoverageState.DEGRADED, False))
    host.on_clock(clock[0])
    if not gap_first:
        host.set_coverage(Coverage(CoverageState.DEGRADED, False))
    host.close()
    receipt = json.loads((tmp_path / "ranking-2026-10-27-RTH.json").read_text())
    assert host.observed is False, receipt
    assert host.host.supplied.state is CoverageState.DEGRADED, receipt
    assert receipt["gaps"] == 1, receipt


def test_closed_moment_retains_a_clock_wakeup_for_next_segment(tmp_path):
    first, second = pair()
    host, clock = host_at(tmp_path, lambda timestamp: None if timestamp < second.start_ns else second)
    clock[0] = START
    generation, boundary = host.on_clock(clock[0])
    assert generation is None
    assert boundary is not None and clock[0] < boundary <= second.start_ns


def test_real_closed_sunday_still_arms_a_boundary_without_a_tick(tmp_path):
    from sextant.ranking.baseline import segment_start

    sunday = int(datetime(2026, 11, 15, 19, tzinfo=ET).timestamp()) * NS
    host, clock = host_at(tmp_path, lambda timestamp: segment_start(timestamp)[0])
    clock[0] = sunday
    assert segment_start(sunday)[0] is None
    _, boundary = host.on_clock(sunday)
    assert boundary is not None and boundary > sunday


@pytest.mark.parametrize("clock_first", [False, True])
def test_boundary_tick_and_alert_enter_new_segment_once(tmp_path, clock_first):
    first, second = pair()
    entered = []

    def source(segment):
        entered.append(segment.name)
        return fixture_inputs(segment)

    host, clock = host_at(
        tmp_path, lambda timestamp: first if timestamp < first.end_ns else second, source
    )
    clock[0] = START
    host.on_clock(clock[0])
    clock[0] = second.start_ns
    if clock_first:
        host.on_clock(clock[0])
    host.on_trade(tick_at(clock[0]), facts=(True, ("@",)))
    if not clock_first:
        host.on_clock(clock[0])
    assert entered == ["PRE", "RTH"]
    assert host.host.publisher.last_event == second.start_ns
    assert host.late == 0


def test_late_closed_and_other_feed_ticks_are_counted_and_dropped(tmp_path):
    first, second = pair()
    overnight = replace(second, name="OVERNIGHT", start_ns=second.end_ns, end_ns=second.end_ns + NS)

    def segment_of(timestamp):
        if timestamp < first.end_ns:
            return first
        if timestamp < second.end_ns:
            return second
        if timestamp < overnight.end_ns:
            return overnight
        return None

    host, clock = host_at(tmp_path, segment_of)
    clock[0] = second.start_ns
    host.on_clock(clock[0])
    previous_event = host.host.publisher.last_event
    assert host.on_trade(tick_at(first.start_ns), facts=(True, ("@",))) is None
    assert host.on_trade(tick_at(overnight.start_ns), facts=(True, ("@",))) is None
    assert host.on_trade(tick_at(overnight.end_ns), facts=(True, ("@",))) is None
    assert host.segment == second and host.late == 1 and host.unrouted == 2
    assert host.host.publisher.last_event == previous_event


def test_references_known_at_expiry_are_segment_local(tmp_path):
    first, second = pair()

    def source(segment):
        offset = 0 if segment.name == "PRE" else 2
        return SegmentInputs(
            baseline(),
            dict.fromkeys(NAMES, ReferencePrices(Decimal(offset + 1), START - NS + offset, "fixture")),
            dict.fromkeys(NAMES, AssetState(START - NS + offset, segment.end_ns, None, "common", "fixture")),
        )

    host, clock = host_at(
        tmp_path, lambda timestamp: first if timestamp < first.end_ns else second, source
    )
    clock[0] = START
    host.on_clock(clock[0])
    host.set_symbol("PENNY", references=ReferencePrices(None, 0, "ignored"), asset=AssetState(START + NS, first.end_ns, True, "test", "ignored"))
    clock[0] = second.start_ns
    host.on_clock(clock[0])
    publisher = host.host.publisher
    assert publisher.references["PENNY"].prior_close == Decimal(3)
    assert publisher.references["PENNY"].known_at == START - NS + 2
    assert publisher.assets["PENNY"].expires_at == second.end_ns
    assert publisher.assets["PENNY"].halted is True
    assert publisher.assets["PENNY"].security_type == "common"


@pytest.mark.parametrize("stage", ["turn", "alert"])
def test_clock_turn_or_alert_failures_are_counted_and_paged(stage):
    pages = []

    def turn(now):
        if stage == "turn":
            raise RuntimeError("offline turn fixture")
        return None, now + NS

    def alert(*arguments, **keywords):
        raise RuntimeError("offline alert fixture")

    actor = SimpleNamespace(
        host=SimpleNamespace(on_clock=turn),
        primed=True,
        clock=SimpleNamespace(timestamp_ns=lambda: START, set_time_alert_ns=alert),
        errors={},
        _paged={},
        _page=lambda reason, detail: pages.append((reason, detail)),
        _window_ns=60 * NS,
        _publish=lambda generation: None,
    )
    actor._fault = MethodType(RankingActor._fault, actor)
    actor._on_clock = MethodType(RankingActor._on_clock, actor)
    RankingActor._on_clock(actor, None)
    assert actor.errors == {"clock": 1}
    assert pages == [("clock", "RuntimeError")]


def test_cli_build_wires_a_pager_without_starting_a_node(tmp_path, monkeypatch):
    arguments, _ = node_ranking.parse(argv(tmp_path))
    captured = []

    class InertNode:
        def add_actor(self, actor):
            captured.append(actor)

    class InertBuilder:
        def add_data_client(self, *arguments):
            return self

        def build(self):
            return InertNode()

    monkeypatch.setattr(node_ranking.LiveNodeBuilder, "from_config", lambda *arguments: InertBuilder())
    monkeypatch.setattr(node_ranking, "RankingActor", lambda config: config)
    node_ranking.build(arguments, inputs=node_ranking.file_inputs(arguments), config=LiveNodeConfig())
    pages = []

    def turn(now):
        raise RuntimeError("offline node clock fixture")

    actor = SimpleNamespace(
        host=SimpleNamespace(on_clock=turn),
        primed=True,
        clock=SimpleNamespace(timestamp_ns=lambda: START),
        errors={},
        _paged={},
        _page=captured[0].page,
        _window_ns=60 * NS,
        _publish=lambda generation: None,
    )
    actor._fault = MethodType(RankingActor._fault, actor)
    RankingActor._on_clock(actor, None)
    assert actor.errors == {"clock": 1}
    assert actor._page is not None, "CLI always uses page=None; counted clock failure has no page transport"


def test_execution_client_is_refused_before_any_node_builder(tmp_path, monkeypatch):
    from sextant.alpaca.config import AlpacaExecutionClientConfig

    arguments, _ = node_ranking.parse(argv(tmp_path))

    def refuse_builder(*arguments):
        pytest.fail("a node builder must never be reached")

    monkeypatch.setattr(node_ranking.LiveNodeBuilder, "from_config", refuse_builder)
    config = LiveNodeConfig(exec_clients={"ALPACA": AlpacaExecutionClientConfig(api_key_env="FIXTURE_KEY_NAME", api_secret_env="FIXTURE_SECRET_NAME", account_id="ALPACA-FIXTURE")})
    with pytest.raises(ValueError, match="data-only"):
        node_ranking.build(arguments, inputs=node_ranking.file_inputs(arguments), config=config)


@pytest.mark.parametrize("slot,streams", [(1, 0), (3, 0), (2, 1)])
def test_other_slots_and_an_existing_stream_are_refused_without_a_node(tmp_path, slot, streams):
    with pytest.raises(ValueError):
        with reserve_stream(tmp_path / "lease", paper_slot=slot, existing_streams=streams, source="offline fixture"):
            pytest.fail("lease must refuse")
    assert not (tmp_path / "lease").exists()


@pytest.mark.parametrize("filename", ["references.json", "assets.json"])
def test_modified_priming_file_is_named_before_the_lease(tmp_path, monkeypatch, filename):
    import sextant.tradingview.producer as producer

    arguments = argv(tmp_path)
    path = tmp_path / "ranking-inputs" / filename
    path.write_text("{}")

    def refuse_reservation(*arguments, **keywords):
        pytest.fail("priming failure must precede lease reservation")

    monkeypatch.setattr(producer, "reserve_stream", refuse_reservation)
    with pytest.raises(node_ranking.RankingRefused, match=filename.replace(".", r"\.")):
        node_ranking.main(arguments)


def test_missing_close_does_not_receive_a_score(tmp_path):
    def no_close(segment):
        original = fixture_inputs(segment)
        return replace(original, references=dict.fromkeys(NAMES, ReferencePrices(None, START - NS, "fixture missing close")))

    host, clock = host_at(tmp_path, lambda timestamp: SCOPE, no_close)
    clock[0] = START
    host.on_clock(clock[0])
    host.set_symbol("PENNY", references=ReferencePrices(None, 0, "ignored"), asset=AssetState(START - NS, SCOPE.end_ns, False, "common", "fixture"))
    generations = []
    for trade in ticks():
        clock[0] = trade.ts_init
        generation = host.on_trade(trade, facts=(True, ("@",)))
        if generation is not None:
            generations.append(generation)
    assert generations and all(row.rank is None and row.score is None for generation in generations for row in generation.rows if row.symbol == "PENNY")


def test_boundary_gap_cannot_yield_a_rank(tmp_path):
    first, second = pair()

    def source(segment):
        original = fixture_inputs(segment)
        table = replace(original.baseline, samples=tuple(replace(sample, segment=segment.name) for sample in original.baseline.samples))
        return replace(original, baseline=table)

    host, clock = host_at(tmp_path, lambda timestamp: first if timestamp < first.end_ns else second, source)
    clock[0] = START
    host.on_clock(clock[0])
    clock[0] = second.start_ns
    host.set_coverage(Coverage(CoverageState.DEGRADED, False))
    host.on_clock(clock[0])
    host.set_symbol("PENNY", references=ReferencePrices(None, 0, "ignored"), asset=AssetState(second.start_ns, second.end_ns, False, "common", "fixture"))
    last = None
    shift = second.start_ns - START
    for original in ticks():
        trade = TradeTick(original.instrument_id, original.price, original.size, original.aggressor_side, original.trade_id, original.ts_event + shift, original.ts_init + shift)
        clock[0] = trade.ts_init
        last = host.on_trade(trade, facts=(True, ("@",))) or last
    assert last is not None
    assert all(row.rank is None for row in last.rows), [(row.symbol, row.rank, row.score) for row in last.rows]


def test_daily_producer_uses_sip_split_prior_session_and_one_calibration_pacer(tmp_path, monkeypatch):
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.timeframe import TimeFrame
    from test_ranking_inputs import artifact, staged

    from sextant.data import ranking_inputs
    from sextant.data.alpaca_history import Pacer
    from sextant.data.calibration_job import parameters

    checkout = Path(node_ranking.__file__).parents[3]
    parameter_file = checkout / "deploy/calibration/parameters.json"
    _, expected_rate, _ = parameters(parameter_file)
    pacers = []
    requests = []

    def make_pacer(rate):
        pacer = Pacer(rate)
        pacers.append((rate, pacer))
        return pacer

    class OfflineClient:
        def __init__(self, *, pacer, api_key, secret_key):
            assert pacer is pacers[0][1]
            assert api_key == "offline-fixture-only" and secret_key == "offline-fixture-only"

        def get_stock_bars(self, request):
            requests.append(request)
            return SimpleNamespace(data={"AAPL": [SimpleNamespace(timestamp=datetime(2026, 11, 10, 0, tzinfo=ET), close=Decimal("10.50"))]})

    monkeypatch.setattr(ranking_inputs, "Pacer", make_pacer)
    monkeypatch.setattr(ranking_inputs, "PacedStockBars", OfflineClient)
    monkeypatch.setenv("FIXTURE_KEY_NAME", "offline-fixture-only")
    monkeypatch.setenv("FIXTURE_SECRET_NAME", "offline-fixture-only")
    output = tmp_path / "ranking-inputs"
    result = ranking_inputs.main([
        "--out", str(output),
        "--universe-artifact", str(artifact(tmp_path, "AAPL", "IBM")),
        "--listings-dir", str(staged(tmp_path)),
        "--session", "2026-11-11",
        "--api-key-env", "FIXTURE_KEY_NAME",
        "--api-secret-env", "FIXTURE_SECRET_NAME",
        "--parameters", str(parameter_file),
    ])
    assert result == 0 and len(pacers) == 1 and pacers[0][0] == expected_rate
    assert requests and all(request.feed is DataFeed.SIP and request.adjustment is Adjustment.SPLIT and request.timeframe.value == TimeFrame.Day.value for request in requests)
    assert all(request.start.astimezone(ET).date().isoformat() == "2026-11-10" for request in requests)
    references = json.loads((output / "references.json").read_text())
    assert references["closes"] == {"AAPL": "10.50"}


def test_empty_universe_refuses_before_daily_requests(tmp_path):
    from sextant.data import ranking_inputs

    path = tmp_path / "universe.json"
    path.write_text(json.dumps({"rows": []}))
    daily = SimpleNamespace(daily_closes=lambda *arguments, **keywords: pytest.fail("no daily request is allowed for an empty universe"))
    with pytest.raises(ValueError, match="no rows"):
        ranking_inputs.produce(tmp_path / "out", universe_artifact=path, listings_dir=tmp_path / "absent", session=SCOPE.session_date, daily=daily)


def test_late_tick_cannot_resurrect_a_segment_retired_into_closed_time(tmp_path):
    post = replace(SCOPE, name="POST", end_ns=START + 300 * NS)
    host, clock = host_at(tmp_path, lambda timestamp: post if timestamp < post.end_ns else None, source=lambda segment: None)
    clock[0] = post.start_ns
    host.on_clock(clock[0])
    clock[0] = post.end_ns
    host.on_clock(clock[0])
    assert host.segment is None
    clock[0] += NS
    generation = host.on_trade(tick_at(post.end_ns - NS), facts=(True, ("@",)))
    assert generation is None and host.segment is None and host.late == 1, {
        "returned_generation": generation is not None,
        "segment": host.segment,
        "late": host.late,
        "unprimed": host.unprimed,
    }
