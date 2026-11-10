"""ADR-0003 fixtures for the in-process K2 publisher host, not a trial."""

from __future__ import annotations

import ast
import asyncio
import itertools
import json
import threading
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_trader.model import (
    AggressorSide,
    InstrumentId,
    Price,
    Quantity,
    TradeId,
    TradeTick,
)
from test_alpaca_feed import _EQUITY, _factory_for, _FakeStream, _trade
from test_ranking import NS, SCOPE, START, baseline, registry

from sextant.paper.alpaca_feed import AlpacaTickFeed
from sextant.ranking.engine import ReferencePrices
from sextant.ranking.generation import Coverage, CoverageState, RankingGeneration
from sextant.ranking.host import INTERVALS_NAME, RankingHost
from sextant.ranking.publisher import AssetState

ROOT = Path(__file__).parents[2]
HOST = ROOT / "src/sextant/ranking/host.py"
D = Decimal
UNIVERSE = ("PENNY", "ADR", "LARGE")
_TEST_API_KEY = "test-key"
_TEST_API_CREDENTIAL = "test-credential"


def tick(at: int, price: str = "0.50", name: str = "PENNY") -> TradeTick:
    # 100 shares per print reaches the fixture dvol gate, as in the consumer proof.
    return TradeTick(
        InstrumentId.from_str(name + ".NASDAQ"),
        Price.from_str(price),
        Quantity.from_str("100"),
        AggressorSide.BUY,
        TradeId(str(at)),
        at,
        at,
    )


def make_host(tmp_path: Path, *, heartbeat=None, alarm=None):
    now = [START]
    mono = itertools.count(1_000_000_000_000, 1_000_000)
    host = RankingHost(
        epoch="fixture-host-1",
        feed="sip",
        segment=SCOPE,
        registry=registry(),
        universe=UNIVERSE,
        universe_source="fixture selected symbols; NOT PIT universe",
        baseline=baseline(),
        entry_heartbeat_max_age_s=2,
        entry_generation_max_age_s=2,
        entry_input_max_age_s=2,
        state_dir=tmp_path,
        heartbeat=heartbeat,
        alarm=alarm,
        clock=lambda: now[0],
        monotonic_ns=lambda: next(mono),
    )
    host.set_coverage(Coverage(CoverageState.READY, True, 3, 3, 0, 0, 0))
    for name in UNIVERSE:
        host.set_symbol(
            name,
            references=ReferencePrices(D("0.50"), START - NS, "fixture official close"),
            asset=AssetState(START - NS, SCOPE.end_ns, False, "common", "fixture vendor"),
        )
    return host, now


def drive(host: RankingHost, now: list[int], at: int, price: str, name: str):
    now[0] = at
    return host.on_trade(tick(at, price, name))


def warm(host: RankingHost, now: list[int], names: tuple[str, ...] = UNIVERSE) -> None:
    for second in (0, 60, 120, 180, 240, 300):
        for name in names:
            drive(host, now, START + second * NS, "0.50", name)
    for second in (310, 320, 330, 340, 350, 360):
        for name in names:
            drive(host, now, START + second * NS, "0.55" if name == "PENNY" else "0.50", name)


def wired(tmp_path: Path):
    """A host whose heartbeat seam feeds its own consumer, as the PR 3 emitter will."""
    beats: list[RankingGeneration] = []
    holder: dict[str, RankingHost] = {}

    def beat(generation: RankingGeneration) -> bool:
        beats.append(generation)
        return holder["host"].consumer.accept_heartbeat(
            at=generation.known_at, received_ns=generation.known_at
        )

    host, now = make_host(tmp_path, heartbeat=beat)
    holder["host"] = host
    return host, now, beats


def test_full_universe_fixture_reaches_ready_and_entry_rank_ranks(tmp_path: Path) -> None:
    host, now, beats = wired(tmp_path)
    warm(host, now)
    at = START + 360 * NS
    assert host.consumer.reader.generation is not None
    assert host.consumer.reader.generation.coverage.state is CoverageState.READY
    assert host.entry_rank("PENNY", now=at) == 1
    assert host.ranked_names(now=at) == ("PENNY",)
    assert beats and all(gen.coverage.state is CoverageState.READY for gen in beats)
    host.close()


def test_one_missing_symbol_degrades_and_every_entry_rank_is_none(tmp_path: Path) -> None:
    host, now, beats = wired(tmp_path)
    warm(host, now, names=("PENNY", "ADR"))
    at = START + 360 * NS
    generation = drive(host, now, at + NS, "0.56", "PENNY")
    assert generation is not None and generation.coverage.state is CoverageState.DEGRADED
    assert all(row.rank is None for row in generation.rows)
    assert all(host.entry_rank(name, now=at + NS) is None for name in UNIVERSE)
    assert host.ranked_names(now=at + NS) == ()
    assert beats == []
    host.close()


def test_unknown_halt_degrades_and_every_entry_rank_is_none(tmp_path: Path) -> None:
    host, now, beats = wired(tmp_path)
    host.set_symbol(
        "PENNY",
        references=ReferencePrices(D("0.50"), START - NS, "fixture official close"),
        asset=None,
    )
    warm(host, now)
    at = START + 361 * NS
    generation = drive(host, now, at, "0.56", "PENNY")
    assert generation is not None and generation.coverage.state is CoverageState.DEGRADED
    assert all(host.entry_rank(name, now=at) is None for name in UNIVERSE)
    assert host.ranked_names(now=at) == ()
    assert beats == []
    host.close()


def test_a_stale_input_degrades_and_every_entry_rank_is_none(tmp_path: Path) -> None:
    host, now, beats = wired(tmp_path)
    warm(host, now)
    at = START + 360 * NS
    assert host.entry_rank("PENNY", now=at) == 1
    ready_beats = len(beats)
    now[0] = at + 10 * NS
    generation = host.on_trade(tick(at + NS, "0.56", "PENNY"))
    assert generation is not None and generation.coverage.state is CoverageState.DEGRADED
    assert all(host.entry_rank(name, now=at + 10 * NS) is None for name in UNIVERSE)
    assert len(beats) == ready_beats
    host.close()


def test_the_heartbeat_seam_fires_once_per_ready_publication_and_never_otherwise(
    tmp_path: Path,
) -> None:
    calls: list[RankingGeneration] = []
    host, now = make_host(tmp_path, heartbeat=calls.append)
    warm(host, now)
    ready = [
        gen
        for gen in _interval_generations(tmp_path)
        if gen["sequence"] in {call.generation_id.sequence for call in calls}
    ]
    assert len(ready) == len(calls) >= 1
    assert all(call.coverage.state is CoverageState.READY for call in calls)
    before = len(calls)
    host.set_symbol(
        "ADR",
        references=ReferencePrices(D("0.50"), START - NS, "fixture official close"),
        asset=None,
    )
    generation = drive(host, now, START + 362 * NS, "0.56", "PENNY")
    assert generation is not None and generation.coverage.state is CoverageState.DEGRADED
    assert len(calls) == before
    # A throttled READY publication returns None and fires nothing.
    host.set_symbol(
        "ADR",
        references=ReferencePrices(D("0.50"), START - NS, "fixture official close"),
        asset=AssetState(START - NS, SCOPE.end_ns, False, "common", "fixture vendor"),
    )
    assert drive(host, now, START + 362 * NS + NS // 2, "0.56", "ADR") is None
    assert len(calls) == before
    host.close()


def test_the_interval_file_holds_both_interval_series(tmp_path: Path) -> None:
    host, now, _ = wired(tmp_path)
    warm(host, now)
    drive(host, now, START + 362 * NS, "0.56", "PENNY")
    host.close()
    lines = [json.loads(line) for line in (tmp_path / INTERVALS_NAME).read_text().splitlines()]
    generations = [row for row in lines if row["kind"] == "generation"]
    heartbeats = [row for row in lines if row["kind"] == "heartbeat"]
    assert len(generations) >= 2 and len(heartbeats) >= 2
    assert [row["sequence"] for row in generations] == list(range(len(generations)))
    published = [row["publication_ns"] for row in generations]
    beat_times = [row["heartbeat_at"] for row in heartbeats]
    # DEGRADED vetoes are unthrottled, so generations are only non-decreasing.
    assert all(b >= a for a, b in itertools.pairwise(published))
    assert all(b > a for a, b in itertools.pairwise(beat_times))
    assert all(row["generation_ns"] == row["publication_ns"] for row in generations)
    assert all(row["heartbeat_at"] == row["generation_ns"] for row in heartbeats)
    assert {row["producer_epoch"] for row in lines} == {"fixture-host-1"}
    monos = [row["monotonic_ns"] for row in lines]
    walls = [row["wall_ns"] for row in lines]
    assert monos == sorted(monos) and walls == sorted(walls)
    by_sequence = {row["sequence"]: row for row in generations}
    assert all(
        row["sequence"] in by_sequence
        and by_sequence[row["sequence"]]["generation_ns"] == row["heartbeat_at"]
        for row in heartbeats
    )


def test_the_host_imports_no_stream_socket_or_order_surface() -> None:
    imported: set[str] = set()
    tree = ast.parse(HOST.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").lower())
            imported.update(alias.name.lower() for alias in node.names)
    forbidden = ("alpaca", "socket", "stream", "order", "execution", "broker", "account")
    assert not [name for name in imported if any(word in name for word in forbidden)]
    assert not hasattr(RankingHost, "submit_order")
    # The publisher heartbeat stays unset: the host owns the one seam call.
    builds = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "RankingPublisher"
    ]
    assert len(builds) == 1
    assert "heartbeat" not in {kw.arg for kw in builds[0].keywords}


def _interval_generations(tmp_path: Path) -> list[dict]:
    path = tmp_path / INTERVALS_NAME
    if not path.exists():
        return []
    return [
        row
        for row in (json.loads(line) for line in path.read_text().splitlines())
        if row["kind"] == "generation"
    ]


def _feed(*, on_trade, ranking_ingress=None):
    fake = _FakeStream()
    feed = AlpacaTickFeed(
        {"AAPL.ALPACA": _EQUITY},
        on_trade=on_trade,
        on_quote=lambda _tick: None,
        api_key=_TEST_API_KEY,
        secret_key=_TEST_API_CREDENTIAL,
        stream_factory=_factory_for(fake),
        ranking_ingress=ranking_ingress,
    )
    return feed, fake


def test_a_feed_without_ranking_ingress_delivers_identically() -> None:
    plain_ticks: list[TradeTick] = []
    plain, plain_stream = _feed(on_trade=plain_ticks.append)
    plain.start()
    assert plain_stream.trade_handler is not None
    asyncio.run(plain_stream.trade_handler(_trade()))
    wired_ticks: list[TradeTick] = []
    forwarded: list[TradeTick] = []
    wired_feed, wired_stream = _feed(on_trade=wired_ticks.append, ranking_ingress=forwarded.append)
    wired_feed.start()
    assert wired_stream.trade_handler is not None
    asyncio.run(wired_stream.trade_handler(_trade()))
    shape = lambda ticks: [  # noqa: E731 - ts_init is the live receipt clock
        (str(t.instrument_id), str(t.price), str(t.size), t.ts_event) for t in ticks
    ]
    assert shape(plain_ticks) == shape(wired_ticks) == shape(forwarded)
    assert plain_stream.trade_symbols == wired_stream.trade_symbols == ("AAPL",)
    assert plain.ranking_ingress_errors == wired_feed.ranking_ingress_errors == 0


def test_the_wired_feed_opens_one_stream_and_a_raising_ingress_never_stops_it() -> None:
    ticks: list[TradeTick] = []

    def refusing(_tick: TradeTick) -> None:
        raise RuntimeError("ranking host down")

    feed, stream = _feed(on_trade=ticks.append, ranking_ingress=refusing)
    feed.start()
    assert stream.trade_handler is not None
    asyncio.run(stream.trade_handler(_trade()))
    asyncio.run(stream.trade_handler(_trade(i=43)))
    assert stream.run_calls == 1 and len(ticks) == 2
    assert feed.ranking_ingress_errors == 2 and feed.failure is None


def test_a_degraded_publication_bypasses_the_publish_interval(tmp_path: Path) -> None:
    host, now, _ = wired(tmp_path)
    warm(host, now)
    at = START + 360 * NS
    assert host.entry_rank("PENNY", now=at) == 1
    half = at + NS // 2  # inside publish_min_interval_s (1 s fixture)
    generation = drive(host, now, half, "0.56", "OUTSIDE")
    assert generation is not None and generation.coverage.state is CoverageState.DEGRADED
    assert generation.ts_init == half
    assert all(host.entry_rank(name, now=half) is None for name in UNIVERSE)
    host.close()


def test_a_second_host_on_one_state_dir_refuses(tmp_path: Path) -> None:
    host, _ = make_host(tmp_path)
    with pytest.raises(ValueError, match="reserved"):
        make_host(tmp_path)
    host.close()
    with pytest.raises(ValueError, match="reserved"):
        make_host(tmp_path)


def test_a_wrong_thread_call_refuses_and_the_host_survives(tmp_path: Path) -> None:
    host, now = make_host(tmp_path)
    refused: list[BaseException] = []

    def foreign() -> None:
        try:
            host.on_trade(tick(START, name="PENNY"))
        except BaseException as exc:  # noqa: BLE001 - the refusal is the witness
            refused.append(exc)

    worker = threading.Thread(target=foreign)
    worker.start()
    worker.join()
    assert len(refused) == 1 and isinstance(refused[0], RuntimeError)
    assert drive(host, now, START, "0.50", "PENNY") is not None
    host.close()


@pytest.mark.parametrize("returned", [None, 0, "", False, True])
def test_heartbeat_delivered_only_for_a_real_delivery(tmp_path: Path, returned) -> None:
    state = tmp_path / ("real" if returned is True else f"fake-{type(returned).__name__}")
    host, now = make_host(state, heartbeat=lambda _gen: returned)
    warm(host, now)
    host.close()
    lines = [json.loads(line) for line in (state / INTERVALS_NAME).read_text().splitlines()]
    beats = [row["delivered"] for row in lines if row["kind"] == "heartbeat"]
    assert beats and all(delivered is (returned is True) for delivered in beats)


def test_every_degraded_generation_pages_the_alarm(tmp_path: Path) -> None:
    pages: list[tuple[str, str | None]] = []
    host, now = make_host(tmp_path, alarm=lambda reason, symbol: pages.append((reason, symbol)))
    warm(host, now, names=("PENNY", "ADR"))  # LARGE never trades: always DEGRADED
    host.close()
    generations = _interval_generations(tmp_path)
    assert pages.count(("generation_degraded", None)) == len(generations) >= 2
