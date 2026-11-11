"""ADR-0003 fixtures for the in-process K2 publisher host, not a trial."""

from __future__ import annotations

import itertools
from decimal import Decimal
from pathlib import Path

from nautilus_trader.model import (
    AggressorSide,
    InstrumentId,
    Price,
    Quantity,
    TradeId,
    TradeTick,
)
from test_ranking import NS, SCOPE, START, baseline, registry

from sextant.ranking.engine import ReferencePrices
from sextant.ranking.generation import Coverage, CoverageState, RankingGeneration
from sextant.ranking.host import RankingHost
from sextant.ranking.publisher import AssetState

ROOT = Path(__file__).parents[2]
HOST = ROOT / "src/sextant/ranking/host.py"
D = Decimal
UNIVERSE = ("PENNY", "ADR", "LARGE")
_TEST_API_KEY = "test-key"
_TEST_API_CREDENTIAL = "test-credential"


def tick(at: int, price: str = "0.50", name: str = "PENNY") -> TradeTick:
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
    for second in (310, 320, 330, 340, 350):
        for name in names:
            drive(host, now, START + second * NS, "0.55" if name == "PENNY" else "0.50", name)
    # The last mutation must itself publish: throttled trades revoke entry authority.
    for name in names:
        if name != "PENNY":
            drive(host, now, START + 359 * NS, "0.50", name)
    if "PENNY" in names:
        drive(host, now, START + 360 * NS, "0.55", "PENNY")


def wired(tmp_path: Path):
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


REFS = ReferencePrices(D("0.50"), START - NS, "fixture official close")
GOOD = AssetState(START - NS, SCOPE.end_ns, False, "common", "fixture vendor")
