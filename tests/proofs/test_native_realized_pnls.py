"""#129 R98: software qualification on pinned fixtures, not a market experiment.

upstream checked: nautilus_trader@55c0e82053142bce3a5cba4de4221d3929c2d3bc:
portfolio/__init__.pyi:60, docs/concepts/accounting.md:276-282,
docs/concepts/reports.md:224-275. The retired sum is a test-only comparison oracle
from sextant@8e9e1d2c36d580de56da504b26c3f38715979d5c:backtest/thin_slice.py:82-89.
Also checked and run at rc8 d53849b216e20f2c122ca01b4dd0da377638b186: same pyi,
accounting.md:361-371 and reports.md:224-275; the cached fixture bytes are identical.
"""

import hashlib
import json
import socket
from decimal import Decimal

import nautilus_trader.testkit.providers as provider
import pytest
from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import AccountType, Money, OmsType, OrderSide, Price, Quantity, QuoteTick
from nautilus_trader.trading import Strategy, StrategyConfig

from sextant.backtest import thin_slice as thin

D = Decimal
FIXTURE = "binance/ethusdt-trades.csv"


@pytest.fixture(scope="module")
def pinned_fixture():
    # Local qualification uses the cached rc7 blob; CI may use the existing SDK
    # software-fixture loader. This is not an Alpaca/Sharadar acquisition path.
    body = provider._read_test_data(FIXTURE)
    assert hashlib.sha256(body).hexdigest() == (
        "a90fd7b0a83d32190258651eca7ecb0ecdcaf3deb54f73a17ce028bfe49fdd74"
    )
    return body


@pytest.fixture(autouse=True)
def no_network(monkeypatch, pinned_fixture):
    def fixture(path, branch=None):
        assert path == FIXTURE
        return pinned_fixture

    def deny(*_args, **_kwargs):
        pytest.fail("PnL qualification attempted a socket")

    monkeypatch.setattr(provider, "_read_test_data", fixture)
    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def reference_display_sum(engine):
    """The removed collector, only for paired replay comparison."""
    positions = engine.generate_positions_report()
    return (
        sum((Money.from_str(v).as_decimal() for v in positions["realized_pnl"]), D(0))
        if not positions.empty
        else D(0)
    )


def native_total(engine):
    values = engine.portfolio.realized_pnls(thin.BINANCE_VENUE, target_currency=thin.USDT)
    assert isinstance(values, dict)
    assert all(isinstance(v, Money) and k == v.currency for k, v in values.items())
    money = values.get(thin.USDT)
    return D(0) if money is None else money.as_decimal()


def test_both_thin_slice_windows_match_retired_collector_without_parsing_display(
    monkeypatch, tmp_path
):
    comparisons = []
    real_factory = thin._engine

    class NoDisplayMoney:
        def __new__(cls, *args, **kwargs):
            return Money(*args, **kwargs)

        @staticmethod
        def from_str(_value):
            pytest.fail("production P&L parsed a report display string")

    class EngineTap:
        def __init__(self, ticks):
            self.engine = real_factory(ticks)

        def __getattr__(self, name):
            return getattr(self.engine, name)

        def compare(self, phase):
            old, native = reference_display_sum(self.engine), native_total(self.engine)
            assert old == native
            comparisons.append(
                dict(phase=phase, old=str(old), native=str(native), delta=str(native - old))
            )

        def reset(self):
            self.compare("hold_flat")
            self.engine.reset()

        def dispose(self):
            try:
                self.compare("strategy")
            finally:
                self.engine.dispose()

    monkeypatch.setattr(thin, "Money", NoDisplayMoney)
    monkeypatch.setattr(thin, "_engine", EngineTap)
    runs = []
    for window in thin.WINDOWS:
        runs.append(thin.run_window(window, tmp_path))
        for comparison in comparisons[-2:]:
            comparison["window"] = window
    assert len(comparisons) == 4
    for i, run in enumerate(runs):
        control, strategy = comparisons[2 * i : 2 * i + 2]
        assert run.hold_flat_pnl_usdt == control["old"] == "0"
        assert run.realized_pnl_usdt == strategy["old"]
    (tmp_path / "native-pnl-comparison.json").write_text(json.dumps(comparisons, indent=2))


@pytest.mark.parametrize(
    "operations,expected,remaining,snapshots",
    [
        (((OrderSide.BUY, 10), (OrderSide.SELL, 4)), D(40), D(6), 0),
        (
            ((OrderSide.BUY, 10), (OrderSide.SELL, 10), (OrderSide.BUY, 10), (OrderSide.SELL, 3)),
            D(130),
            D(7),
            1,
        ),
        (
            (
                (OrderSide.BUY, 10),
                (OrderSide.SELL, 10),
                (OrderSide.BUY, 10),
                (OrderSide.SELL, 3),
                (OrderSide.SELL, 7),
            ),
            D(270),
            D(0),
            1,
        ),
    ],
)
def test_netting_partial_close_and_reopened_cycles_match_native_and_report(
    operations, expected, remaining, snapshots
):
    class Orders(Strategy):
        def __init__(self):
            super().__init__(StrategyConfig())
            self.index = 0

        def on_start(self):
            self.subscribe_quotes(thin.ETHUSDT.id)

        def on_quote(self, quote):
            if self.index >= len(operations):
                return
            side, quantity = operations[self.index]
            self.index += 1
            self.submit_order(
                self.order_factory.market(
                    instrument_id=thin.ETHUSDT.id,
                    order_side=side,
                    quantity=Quantity.from_decimal_dp(D(quantity), thin.ETHUSDT.size_precision),
                )
            )

    engine = BacktestEngine(BacktestEngineConfig(bypass_logging=True, run_analysis=False))
    try:
        engine.add_venue(
            venue=thin.BINANCE_VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=None,
            starting_balances=[Money.from_str("1000000 USDT"), Money.from_str("10 ETH")],
            fee_model=MakerTakerFeeModel(maker_rate=D(0), taker_rate=D(0)),
        )
        engine.add_instrument(thin.ETHUSDT)
        quotes = []
        for i in range(len(operations) + 1):
            price = Price.from_decimal_dp(
                D(100 + min(i, len(operations) - 1) * 10), thin.ETHUSDT.price_precision
            )
            at = 1_600_000_000_000_000_000 + i * 1_000_000_000
            quotes.append(
                QuoteTick(
                    thin.ETHUSDT.id,
                    price,
                    price,
                    Quantity.from_decimal_dp(D(1000), thin.ETHUSDT.size_precision),
                    Quantity.from_decimal_dp(D(1000), thin.ETHUSDT.size_precision),
                    at,
                    at,
                )
            )
        engine.add_data(quotes)
        engine.add_strategy(Orders())
        engine.run()
        positions = engine.cache.positions(instrument_id=thin.ETHUSDT.id)
        assert len(positions) == 1 and positions[0].quantity.as_decimal() == remaining
        assert len(engine.cache.position_snapshots(position_id=positions[0].id)) == snapshots
        assert native_total(engine) == reference_display_sum(engine) == expected
    finally:
        engine.dispose()
