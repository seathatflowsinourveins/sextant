"""Bar-fidelity host witnesses: bars, universe, baseline, anchors and rank parity."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from alpaca.data.models import BarSet
from alpaca.data.requests import StockBarsRequest
from nautilus_trader.common import MessageBus
from nautilus_trader.model import (
    AggressorSide,
    InstrumentId,
    Price,
    Quantity,
    TradeId,
    TraderId,
    TradeTick,
)

from sextant.ranking.baseline import BaselineSample, BaselineTable
from sextant.ranking.engine import (
    MoverRow,
    MoverState,
    ReferencePrices,
    Segment,
    advance_mover,
    rank_movers,
)
from sextant.ranking.generation import Coverage, CoverageState
from sextant.ranking.publisher import AssetState, RankingPublisher
from sextant.ranking.registry import Registry, RegistryRow
from sextant.ranking.window import TradeWindow
from sextant.tradingview.bars import (
    AlpacaBarSource,
    Bar,
    BarPoll,
    build_universe,
    parse_directory,
)
from sextant.tradingview.baseline import build_baseline
from sextant.tradingview.host import BarFidelityHost, load_symbol_map
from sextant.tradingview.producer import Clocks, reserve_stream

D = Decimal
NS = 1_000_000_000
NY = ZoneInfo("America/New_York")
DAY_START = int(datetime(2026, 11, 9, 4, 0, tzinfo=NY).timestamp()) * NS
SCOPE = Segment(
    "PRE", datetime(2026, 11, 9).date(), DAY_START, DAY_START + 19_800 * NS, "fixture XNYS boundary"
)


def registry() -> Registry:
    values = {
        "mover_min_move": (D("0.03"), "fraction"),
        "mover_min_trades_accel": (D("1.5"), "ratio"),
        "mover_min_dvol_ratio": (D("3"), "ratio"),
        "move_1m_window_s": (60, "seconds"),
        "move_5m_window_s": (300, "seconds"),
        "trades_accel_window_s": (60, "seconds"),
        # Fixture-only: one prior minute keeps the witness inside two polls.
        "trades_accel_baseline_min": (1, "minutes"),
        "publish_min_interval_s": (1, "seconds"),
        "generation_max_age_s": (2, "seconds"),
        "heartbeat_max_age_s": (2, "seconds"),
        "input_max_age_s": (2, "seconds"),
        "top_n": (2, "symbols"),
    }
    return Registry(
        tuple(
            RegistryRow(
                name, unit, value, "fixture only; ADR-0003", "UNCALIBRATED", SCOPE.session_date
            )
            for name, (value, unit) in values.items()
        )
    )


def baseline() -> BaselineTable:
    return BaselineTable(
        tuple(
            BaselineSample(name, "PRE", "2026-11-06", offset, D(dollars), D(0))
            for name in ("AAA", "BBB", "CCC")
            for offset, dollars in ((0, 0), (19_800, 3960))
        ),
        "fixture explicit complete curves; linear within minute",
        DAY_START - NS,
        "sip",
    )


def publisher() -> RankingPublisher:
    bus = MessageBus(TraderId.from_str("HOST-001"))
    pub = RankingPublisher(
        bus=bus,
        epoch="host-fixture-1",
        feed="sip",
        segment=SCOPE,
        registry=registry(),
        universe=("AAA", "BBB", "CCC"),
        universe_source="fixture selected symbols; NOT PIT universe",
        baseline=baseline(),
    )
    pub.set_coverage(Coverage(CoverageState.READY, True, 3, 3, 0, 0, 0))
    for name in pub.universe:
        pub.set_symbol(
            name,
            references=ReferencePrices(D("10.00"), DAY_START - NS, "fixture official close"),
            asset=AssetState(DAY_START - NS, SCOPE.end_ns, False, "common", "fixture vendor"),
        )
    return pub


def bar(
    symbol: str, minute: int, close: str, volume: int, trades: int, *, open_: str = "10.00"
) -> Bar:
    return Bar(
        symbol=symbol,
        start_ns=DAY_START + minute * 60 * NS,
        open=D(open_),
        close=D(close),
        volume=volume,
        trades=trades,
        vw=None,
    )


def duck_tick(symbol: str, price: Decimal, size: Decimal, at: int) -> TradeTick:
    """The e2e adapter's tick shape: no nautilus Quantity constraint."""

    tick = SimpleNamespace(
        instrument_id=InstrumentId.from_str(symbol + ".NASDAQ"),
        price=SimpleNamespace(as_decimal=lambda: price),
        size=SimpleNamespace(as_decimal=lambda: size),
        ts_event=at,
        ts_init=at,
        quote=None,
    )
    return cast(TradeTick, tick)


def direct_ranks(bars: list[Bar]) -> dict[int, list[tuple[str, int]]]:
    """The e2e bar-fidelity replay: zero-size anchor, one close tick per bar."""
    references = ReferencePrices(D("10.00"), DAY_START - NS, "fixture official close")
    states: dict[str, MoverState] = {}
    by_minute: dict[int, list[Bar]] = {}
    for item in bars:
        by_minute.setdefault((item.start_ns - DAY_START) // (60 * NS), []).append(item)
    out: dict[int, list[tuple[str, int]]] = {}
    for minute in sorted(by_minute):
        rows: list[MoverRow] = []
        for item in by_minute[minute]:
            if item.symbol not in states:
                anchor_price = item.open if item.start_ns == SCOPE.start_ns else D("10.00")
                state, _ = advance_mover(
                    _empty_state(),
                    duck_tick(item.symbol, anchor_price, D(0), SCOPE.start_ns),
                    references,
                    baseline(),
                    segment=SCOPE,
                    feed="sip",
                    registry=registry(),
                )
                states[item.symbol] = state
            tick = duck_tick(item.symbol, item.close, D(item.volume), item.close_ns)
            states[item.symbol], row = advance_mover(
                states[item.symbol],
                tick,
                references,
                baseline(),
                segment=SCOPE,
                feed="sip",
                registry=registry(),
            )
            if row is not None:
                rows.append(row)
        ranked = rank_movers(row for row in rows if row is not None)
        out[minute] = [(row.symbol, row.rank) for row in ranked if row.rank is not None]
    return out


def _empty_state() -> MoverState:
    return MoverState()


def test_counted_twins_match_independent_appends() -> None:
    for count in (1, 4, 50):
        volume = 10 + count
        sizes = [1] * (count - 1) + [volume - (count - 1)]
        partition = tuple(
            TradeTick(
                InstrumentId.from_str("AAA.NASDAQ"),
                Price.from_str("1.2500"),
                Quantity.from_int(size),
                AggressorSide.BUY,
                TradeId(str(index)),
                DAY_START,
                DAY_START,
            )
            for index, size in enumerate(sizes)
        )
        real = TradeTick(
            InstrumentId.from_str("AAA.NASDAQ"),
            Price.from_str("1.2500"),
            Quantity.from_int(volume),
            AggressorSide.BUY,
            TradeId("real"),
            DAY_START,
            DAY_START,
        )
        independent = TradeWindow()
        for item in partition:
            independent = independent.append(item, 400)
        seeded = TradeWindow().append_count(real, count - 1, 400).append(real, 400)
        assert len(seeded.buckets) == len(independent.buckets) == 1
        assert seeded.buckets[0].dollar_volume == independent.buckets[0].dollar_volume
        assert seeded.totals(DAY_START - 60 * NS, DAY_START) == (
            D("1.2500") * volume,
            count,
        )
        assert seeded.totals(DAY_START - 60 * NS, DAY_START) == independent.totals(
            DAY_START - 60 * NS, DAY_START
        )
        seeded_price = seeded.price_at(DAY_START)
        independent_price = independent.price_at(DAY_START)
        assert seeded_price is not None and independent_price is not None
        assert seeded_price.price.as_decimal() == independent_price.price.as_decimal()
        with pytest.raises(ValueError, match="out-of-order"):
            seeded.append(
                TradeTick(
                    InstrumentId.from_str("AAA.NASDAQ"),
                    Price.from_str("1.0000"),
                    Quantity.from_int(1),
                    AggressorSide.BUY,
                    TradeId("early"),
                    DAY_START - NS,
                    DAY_START - NS,
                ),
                400,
            )


def test_directory_parser_keeps_operating_companies_only() -> None:
    nasdaq = "\n".join(
        (
            "File Creation Time: 1109202604:00",
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
            "Round Lot Size|ETF|NextShares",
            "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N",
            "ZTEST|Z Test Corp - Common Stock|Q|Y|N|100|N|N",
            "SPY|SPDR S&P 500 ETF Trust|P|N|N|100|Y|N",
            "ABC$|ABC Corp - Depositary Shares|Q|N|N|100|N|N",
            "WARRANTX|WarrantX Corp - Warrant|Q|N|N|100|N|N",
            "BRK.B|Berkshire Hathaway Inc. - Class B Common Stock|Q|N|N|100|N|N",
        )
    )
    other = "\n".join(
        (
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|"
            "Test Issue|NASDAQ Symbol",
            "IBM|International Business Machines Corporation|N|IBM|N|100|N|IBM",
            "UNT|Unit Corp - Units|N|UNT|N|100|N|UNT",
            "File Creation Time: 1109202604:00",
        )
    )
    assert [item.symbol for item in parse_directory(nasdaq)] == [
        "AAPL",
        "ZTEST",
        "SPY",
        "ABC$",
        "WARRANTX",
        "BRK.B",
    ]
    assert build_universe(nasdaq, other) == ("AAPL", "BRK.B", "IBM")
    assert build_universe(nasdaq, other, active={"AAPL", "IBM"}) == ("AAPL", "IBM")


def test_alpaca_bars_batch_pacer_and_decimal_fields() -> None:
    class Client:
        def __init__(self) -> None:
            self.requests: list[StockBarsRequest] = []

        def get_stock_bars(self, request: StockBarsRequest) -> BarSet:
            self.requests.append(request)
            symbols = request.symbol_or_symbols
            return BarSet(
                {
                    symbol: [
                        {
                            "t": "2026-11-09T09:00:00Z",
                            "o": 10.0,
                            "h": 10.5,
                            "l": 9.9,
                            "c": 10.25,
                            "v": 1200,
                            "n": 7,
                            "vw": 10.1,
                        }
                    ]
                    for symbol in symbols
                }
            )

    waits: list[float] = []

    class Pacer:
        def wait(self) -> None:
            waits.append(1.0)

    client = Client()
    source = AlpacaBarSource(client, Pacer(), batch=2)
    bars = source.minute_bars(
        ("AAA", "BBB", "CCC"),
        start=datetime(2026, 11, 9, 4, 0, tzinfo=NY),
        end=datetime(2026, 11, 9, 4, 5, tzinfo=NY),
    )
    assert len(client.requests) == 2
    assert len(waits) == 2
    assert [item.symbol for item in bars] == ["AAA", "BBB", "CCC"]
    first = bars[0]
    assert first.start_ns == int(datetime(2026, 11, 9, 4, 0, tzinfo=NY).timestamp()) * NS
    assert first.close == D("10.25")
    assert first.volume == 1200
    assert first.trades == 7
    assert first.vw == D("10.1")
    assert (
        source.minute_bars(
            (),
            start=datetime(2026, 11, 9, 4, 0, tzinfo=NY),
            end=datetime(2026, 11, 9, 4, 5, tzinfo=NY),
        )
        == ()
    )
    with pytest.raises(ValueError):
        AlpacaBarSource(client, Pacer(), batch=0)


def test_five_session_baseline_carries_missing_minutes_and_medians() -> None:
    from datetime import date

    sessions = (
        (date(2026, 11, 2), (bar("AAA", 0, "10.00", 100, 1), bar("AAA", 2, "10.00", 100, 1))),
        (date(2026, 11, 3), (bar("AAA", 0, "10.00", 300, 1), bar("AAA", 2, "10.00", 100, 1))),
        (date(2026, 11, 4), (bar("AAA", 0, "10.00", 200, 1), bar("AAA", 2, "10.00", 100, 1))),
    )
    table = build_baseline(
        sessions,
        symbols=("AAA", "BBB"),
        segment=SCOPE,
        known_at=DAY_START - 20 * 3600 * NS,
        provenance="fixture five-session curves",
    )
    assert table.feed == "sip"
    assert table.latest_session == date(2026, 11, 4)
    assert table.known_at == DAY_START - 20 * 3600 * NS

    def dollars(symbol: str, offset: str) -> Decimal:
        value = table.cumulative(symbol, "PRE", D(offset))
        assert value is not None
        return value.dollar_volume

    # Cumulative through minute 0 at offset 60 s, then minute 2 at offset 180 s.
    assert dollars("AAA", "60") == D(2000)
    assert dollars("AAA", "120") == D(2000)  # carried forward
    assert dollars("AAA", "180") == D(3000)
    assert dollars("AAA", "150") == D(2500)  # linear inside the gap
    assert dollars("BBB", "60") == D(0)
    assert table.cumulative("AAA", "PRE", D(-1)) is None
    assert table.cumulative("AAA", "PRE", D(19_800)) is not None
    assert table.cumulative("AAA", "PRE", D(19_801)) is None
    assert table.cumulative("ZZZ", "PRE", D(60)) is None
    assert table.identity


def test_host_ranks_match_direct_bar_fidelity_replay(tmp_path: Path) -> None:
    polls = []
    for minute, row in enumerate((("11.00", "12.00", "10.50"), ("11.50", "11.00", "10.60"))):
        polls.append(
            BarPoll(
                bars=(
                    bar("AAA", minute, row[0], 10, 3),
                    bar("BBB", minute, row[1], 20, 4),
                    bar("CCC", minute, row[2], 10, 2),
                ),
                requested=("AAA", "BBB", "CCC"),
            )
        )
    expected = direct_ranks([item for poll in polls for item in poll.bars])
    with reserve_stream(
        tmp_path / "leases", paper_slot=3, existing_streams=0, source="fixture"
    ) as lease:
        host = BarFidelityHost(
            publisher(),
            lease=lease,
            sip_authority="fixture SIP authority",
            symbol_map={name: f"NASDAQ:{name}" for name in ("AAA", "BBB", "CCC")},
        )
        # Minute 0 only opens the segment prefix: the prior trade window is still empty.
        close_ns = DAY_START + 60 * NS
        assert host.ingest(polls[0], market_ns=close_ns, received_ns=close_ns) == 3
        assert host.heartbeat(at=close_ns, received_ns=close_ns)
        assert expected[0] == []
        close_ns = DAY_START + 120 * NS
        assert host.ingest(polls[1], market_ns=close_ns, received_ns=close_ns) == 3
        assert host.heartbeat(at=close_ns, received_ns=close_ns)
        unit = host.publish(
            tmp_path / "unit.json",
            now=close_ns,
            mapping_clocks=Clocks(close_ns, close_ns, "fixture receipt"),
        )
        assert unit["status"] == "fresh", unit
        generation = host.producer.reader.generation
        assert generation is not None
        published = sorted(
            (row.symbol, row.rank) for row in generation.rows if row.rank is not None
        )
        assert published == sorted(expected[1])
        assert unit["watchlists"] == {"NS Ranked": ["NASDAQ:BBB", "NASDAQ:AAA"]}
        assert unit["paper_slot"] == 3 and unit["display_only"] is True


def test_host_refuses_lookahead_and_skips_stale_bars(tmp_path: Path) -> None:
    with reserve_stream(
        tmp_path / "leases", paper_slot=3, existing_streams=0, source="fixture"
    ) as lease:
        host = BarFidelityHost(
            publisher(),
            lease=lease,
            sip_authority="fixture SIP authority",
            symbol_map={name: f"NASDAQ:{name}" for name in ("AAA", "BBB", "CCC")},
        )
        close_ns = DAY_START + 60 * NS
        first = BarPoll(bars=(bar("AAA", 0, "11.00", 10, 3),), requested=("AAA",))
        host.ingest(first, market_ns=close_ns, received_ns=close_ns)
        state = host.publisher.states["AAA"]
        with pytest.raises(ValueError, match="market clock"):
            host.ingest(
                BarPoll(bars=(bar("AAA", 1, "11.50", 10, 3),), requested=("AAA",)),
                market_ns=close_ns,
                received_ns=close_ns,
            )
        assert host.ingest(first, market_ns=close_ns, received_ns=close_ns) == 0
        assert host.publisher.states["AAA"] == state
        with pytest.raises(ValueError, match="outside the universe"):
            host.ingest(
                BarPoll(bars=(bar("ZZZ", 0, "11.00", 10, 3),), requested=("ZZZ",)),
                market_ns=close_ns,
                received_ns=close_ns,
            )


def prime_two_minutes(host: BarFidelityHost) -> int:
    """Poll minutes 0 and 1 and heartbeat; return the second close clock."""
    for minute, row in (
        (0, ("11.00", "12.00", "10.50")),
        (1, ("11.50", "11.00", "10.60")),
    ):
        close_ns = DAY_START + (minute + 1) * 60 * NS
        host.ingest(
            BarPoll(
                bars=(
                    bar("AAA", minute, row[0], 10, 3),
                    bar("BBB", minute, row[1], 20, 4),
                    bar("CCC", minute, row[2], 10, 2),
                ),
                requested=("AAA", "BBB", "CCC"),
            ),
            market_ns=close_ns,
            received_ns=close_ns,
        )
        assert host.heartbeat(at=close_ns, received_ns=close_ns)
    return DAY_START + 120 * NS


def test_partial_poll_never_clears_the_list(tmp_path: Path) -> None:
    with reserve_stream(
        tmp_path / "leases", paper_slot=3, existing_streams=0, source="fixture"
    ) as lease:
        host = BarFidelityHost(
            publisher(),
            lease=lease,
            sip_authority="fixture SIP authority",
            symbol_map={name: f"NASDAQ:{name}" for name in ("AAA", "BBB", "CCC")},
        )
        close_ns = prime_two_minutes(host)
        unit = host.publish(
            tmp_path / "unit.json",
            now=close_ns,
            mapping_clocks=Clocks(close_ns, close_ns, "fixture receipt"),
        )
        assert unit["status"] == "fresh", unit

        host.ingest(
            BarPoll(bars=(), requested=("AAA", "BBB", "CCC"), failed=("CCC",)),
            market_ns=close_ns + NS,
            received_ns=close_ns + NS,
        )
        host.heartbeat(at=close_ns + NS, received_ns=close_ns + NS)
        degraded = host.publish(
            tmp_path / "unit.json",
            now=close_ns + NS,
            mapping_clocks=Clocks(close_ns + NS, close_ns + NS, "fixture receipt"),
        )
        assert degraded["status"] == "unavailable"
        assert degraded["watchlists"] is None
        written = json.loads((tmp_path / "unit.json").read_text(encoding="utf-8"))
        assert written["status"] == "unavailable"
        assert written["watchlists"] is None


def test_missing_mapping_never_clears_the_list(tmp_path: Path) -> None:
    with reserve_stream(
        tmp_path / "leases", paper_slot=3, existing_streams=0, source="fixture"
    ) as lease:
        host = BarFidelityHost(
            publisher(),
            lease=lease,
            sip_authority="fixture SIP authority",
            symbol_map={name: f"NASDAQ:{name}" for name in ("AAA", "BBB", "CCC")},
        )
        close_ns = prime_two_minutes(host)
        unit = host.publish(
            tmp_path / "unit.json",
            now=close_ns,
            mapping_clocks=Clocks(close_ns, close_ns, "fixture receipt"),
        )
        assert unit["status"] == "fresh", unit

        host.symbol_map.pop("AAA")
        host.heartbeat(at=close_ns + NS, received_ns=close_ns + NS)
        unmapped = host.publish(
            tmp_path / "unit.json",
            now=close_ns + NS,
            mapping_clocks=Clocks(close_ns + NS, close_ns + NS, "fixture receipt"),
        )
        assert unmapped["status"] == "unavailable"
        assert unmapped["watchlists"] is None
        assert "mapping" in unmapped["reason"]


def test_anchor_price_uses_open_only_at_the_segment_start(tmp_path: Path) -> None:
    with reserve_stream(
        tmp_path / "leases", paper_slot=3, existing_streams=0, source="fixture"
    ) as lease:
        host = BarFidelityHost(
            publisher(),
            lease=lease,
            sip_authority="fixture SIP authority",
            symbol_map={name: f"NASDAQ:{name}" for name in ("AAA", "BBB", "CCC")},
        )
        close_ns = DAY_START + 5 * 60 * NS
        host.ingest(
            BarPoll(
                bars=(
                    bar("AAA", 0, "11.00", 10, 3, open_="9.90"),
                    bar("BBB", 4, "11.00", 10, 3, open_="9.90"),
                ),
                requested=("AAA", "BBB", "CCC"),
            ),
            market_ns=close_ns,
            received_ns=close_ns,
        )

        def anchored(symbol: str) -> Decimal:
            tick = host.publisher.states[symbol].history.price_at(DAY_START)
            assert tick is not None
            return tick.price.as_decimal()

        assert anchored("AAA") == D("9.90")
        assert anchored("BBB") == D("10.00")
        assert host.publisher.states["AAA"].segment_dollar_volume == D("11.00") * 10
        assert host.publisher.states["BBB"].segment_dollar_volume == D("11.00") * 10


def test_symbol_map_is_explicit_and_unique(tmp_path: Path) -> None:
    path = tmp_path / "map.json"
    path.write_text('{"AAA": "NASDAQ:AAA", "BBB": null}', encoding="utf-8")
    assert load_symbol_map(path) == {"AAA": "NASDAQ:AAA", "BBB": None}
    path.write_text('{"AAA": "NASDAQ:AAA", "BBB": "NASDAQ:AAA"}', encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_symbol_map(path)
    path.write_text('{"AAA": "SMART:AAA"}', encoding="utf-8")
    with pytest.raises(ValueError, match="exchange"):
        load_symbol_map(path)
    path.write_text('{"AAA": "not a venue"}', encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_symbol_map(path)
