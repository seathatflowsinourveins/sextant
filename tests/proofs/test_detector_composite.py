"""Native rc7 composite delivery witness, fabricated data only; acquisition remains HOLD.

upstream checked: nautilus_trader@55c0e82053142bce3a5cba4de4221d3929c2d3bc:
python/tests/unit/backtest/test_bar_aggregation.py and docs/concepts/data/index.md:218-296.
"""

import socket
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
from nautilus_trader.data import DataEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import AccountType, Bar, Currency, Money, OmsType, Price, Quantity, Venue
from nautilus_trader.trading import Strategy, StrategyConfig

from sextant.data.catalog import equity
from sextant.research.detectors import stocks_in_play as sip


@pytest.mark.parametrize("missing_minute", [None, 3])
def test_real_native_composite_delivers_standard_type_and_preserves_coverage_guard(
    monkeypatch, missing_minute
):
    def deny(*_args, **_kwargs):
        pytest.fail("native composite proof attempted a socket")

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    instrument = equity("FIXTURE")
    active = sip.StocksInPlaySpec(sip.PARAMETERS)
    composite = active.composite_type(instrument.id)
    opened = (
        int(
            datetime.combine(
                date(2026, 11, 6), time(9, 30), ZoneInfo("America/New_York")
            ).timestamp()
        )
        * 1_000_000_000
    )
    bars = []
    for i in range(1, 7):
        if i == missing_minute:
            continue
        price = Decimal(5 + i)
        at = opened + i * 60_000_000_000
        bars.append(
            Bar(
                composite.composite(),
                Price.from_decimal(price),
                Price.from_decimal(price + 1),
                Price.from_decimal(price - 1),
                Price.from_decimal(price + Decimal("0.5")),
                Quantity.from_int(i * 100),
                at,
                at,
            )
        )

    class Collector(Strategy):
        def __init__(self):
            super().__init__(StrategyConfig())
            self.bars = []

        def on_start(self):
            self.subscribe_bars(composite)

        def on_bar(self, bar):
            self.bars.append(bar)

    engine = BacktestEngine(
        BacktestEngineConfig(
            bypass_logging=True,
            run_analysis=False,
            data_engine=DataEngineConfig(
                time_bars_interval_type="left-open",
                time_bars_timestamp_on_close=True,
                time_bars_build_with_no_updates=False,
            ),
        )
    )
    try:
        usd = Currency.from_str("USD")
        engine.add_venue(
            venue=Venue("ALPACA"),
            oms_type=OmsType.HEDGING,
            account_type=AccountType.MARGIN,
            base_currency=usd,
            starting_balances=[Money.from_str("10000 USD")],
            fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
        )
        engine.add_instrument(instrument)
        engine.add_data(bars)
        collector = Collector()
        engine.add_strategy(collector)
        engine.run()
        end = opened + 300_000_000_000
        completed = tuple(b for b in collector.bars if b.ts_event == end)
        assert len(completed) == 1 and completed[0].bar_type == composite.standard()
        window = sip.opening_window(
            completed,
            session_open_ns=opened,
            as_of_ns=end,
            composite_type=composite,
            coverage_complete=missing_minute is None,
            spec=active,
        )
        if missing_minute is not None:
            assert window is None  # Native output can be partial; it grants no coverage.
        else:
            assert window is not None
            assert (window.open, window.close, window.volume) == (
                Decimal(6),
                Decimal("10.5"),
                Decimal(1500),
            )
            assert window.coverage_complete is True and window.composite_type == composite
            assert window.params_hash == active.params_hash
    finally:
        engine.dispose()
