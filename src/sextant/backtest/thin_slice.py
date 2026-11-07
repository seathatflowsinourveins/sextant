"""The thin slice: NautilusTrader's own EMA-cross example, run forward over one data set.

It proves the trading path, not an edge. Walk-forward, CPCV, DSR and PBO gates arrive in Phase 4.
Each source is pinned in docs/manifest.md:

- Strategy, data, parameters: nautilus_trader's crypto_ema_cross_ethusdt_trade_ticks.py example
- Windows and repeat runs: nautilus_trader docs/concepts/backtesting/apis-and-runs.md
- Hold-flat as the control, and a later window as the sim replay: northstar-lanes ADR-0003, P7 and
  P8, and the owner-approved plan's Phase 2
- The ledger row: the engine's own BacktestResult
- Realized P&L: native Portfolio.realized_pnls; rc7/rc8 accounting and reports API in the manifest
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from nautilus_trader.adapters.binance import BINANCE_VENUE
from nautilus_trader.analysis import PortfolioStatistic
from nautilus_trader.analysis.tearsheet import create_tearsheet
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, RiskEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import AccountType, BarType, Currency, Money, OmsType, TraderId
from nautilus_trader.testkit.providers import TestDataProvider, TestInstrumentProvider

from sextant.strategies.ema_cross import EMACross, EMACrossConfig
from sextant.validation.trials import WITNESS_PATH, TrialLog

ETHUSDT = TestInstrumentProvider.ethusdt_binance()
USDT = Currency.from_str("USDT")
WINDOWS = ("backtest", "replay")


@dataclass(frozen=True)
class Run:
    strategy: str
    window: str
    backtest_start: int | None
    backtest_end: int | None
    total_orders: int
    total_positions: int
    fills: int
    realized_pnl_usdt: str
    hold_flat_pnl_usdt: str
    hold_flat_orders: int
    source: str
    round_trips: int


class TradeCount(PortfolioStatistic):
    """rc8 docs/concepts/portfolio.md statistics example; native archived close cycles."""

    def calculate_from_realized_pnls(self, realized_pnls: list[float]) -> float | None:
        return float(len(realized_pnls))


def _engine(ticks: list) -> BacktestEngine:
    engine = BacktestEngine(
        BacktestEngineConfig(
            trader_id=TraderId.from_str("BACKTESTER-001"),
            risk_engine=RiskEngineConfig(bypass=True),
        ),
    )
    engine.add_venue(
        venue=BINANCE_VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        base_currency=None,
        starting_balances=[Money(1_000_000, USDT), Money(10, Currency.from_str("ETH"))],
        fee_model=MakerTakerFeeModel(maker_rate=Decimal("0.0001"), taker_rate=Decimal("0.0001")),
    )
    engine.portfolio.register_statistic(TradeCount())
    engine.add_instrument(ETHUSDT)
    engine.add_data(ticks)
    return engine


def _config() -> EMACrossConfig:
    return EMACrossConfig(
        instrument_id=ETHUSDT.id,
        bar_type=BarType.from_str("ETHUSDT.BINANCE-250-TICK-LAST-INTERNAL"),
        trade_size=Decimal("0.10"),
        fast_ema_period=10,
        slow_ema_period=20,
    )


def _strategy() -> EMACross:
    return EMACross(_config())


def run_window(window: str, out: Path) -> Run:
    with TrialLog(out / WITNESS_PATH).attempts(
        {"hold_flat": {}, "EMACross": {"ema_cross": "1"}},
        {key: str(value) for key, value in vars(_config()).items()},
        dict(tier="MODELED", block_set_id=window),
    ) as run_id:
        return _run_window(window, out / "reports/thin-slice" / f"{window}-{run_id}")


def _run_window(window: str, out: Path) -> Run:
    """Run the hold-flat control, then the strategy, over one window. Write the fills and page."""
    ticks = TestDataProvider.trades_from_binance_csv(
        instrument=ETHUSDT,
        csv_name="binance/ethusdt-trades.csv",
    )
    first, last = ticks[0].ts_event, ticks[-1].ts_event
    middle = first + (last - first) // 2
    start, end = (first, middle) if window == "backtest" else (middle + 1, last)

    engine = _engine(ticks)
    engine.run(start=start, end=end)
    hold_flat = engine.portfolio.realized_pnls(BINANCE_VENUE, target_currency=USDT).get(USDT)
    hold_flat = hold_flat.as_decimal() if hold_flat is not None else Decimal(0)
    hold_flat_orders = engine.get_result().total_orders

    engine.reset()
    engine.add_strategy(_strategy())
    engine.run(start=start, end=end)
    result = engine.get_result()
    fills = engine.generate_order_fills_report()
    pnl = engine.portfolio.realized_pnls(BINANCE_VENUE, target_currency=USDT).get(USDT)
    pnl = pnl.as_decimal() if pnl is not None else Decimal(0)

    out.mkdir(parents=True, exist_ok=True)
    fills.to_csv(out / f"fills-{window}.csv")
    create_tearsheet(
        engine,
        output_path=str(out / f"tearsheet-{window}.html"),
        title=f"EMACross, {window}: {pnl} USDT realized, hold-flat {hold_flat} USDT",
    )
    record = Run(
        round_trips=int(engine.portfolio.statistics().pnls["USDT"]["Trade Count"]),
        strategy="EMACross",
        window=window,
        backtest_start=result.backtest_start,
        backtest_end=result.backtest_end,
        total_orders=result.total_orders,
        total_positions=result.total_positions,
        fills=len(fills),
        realized_pnl_usdt=str(pnl),
        hold_flat_pnl_usdt=str(hold_flat),
        hold_flat_orders=hold_flat_orders,
        source="nautechsystems/nautilus_trader@55c0e82053142bce3a5cba4de4221d3929c2d3bc:"
        "examples/backtest/crypto_ema_cross_ethusdt_trade_ticks.py",
    )
    engine.dispose()
    return record


if __name__ == "__main__":
    for name in WINDOWS:
        print(run_window(name, Path(__file__).resolve().parents[3]))
