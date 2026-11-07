"""ADR-0029 C3 at the rc8 bump: the fast exit is a reduce-only order the risk engine admits,
never an emulated stop that a halt can deny at release.

Upstream: nautechsystems/nautilus_trader@v2.0.0rc8 d53849b216e20f2c122ca01b4dd0da377638b186,
release note "Changed emulated releases to undergo risk checks; use `REDUCING` for eligible exits,
as `HALTED` denies stops"; `docs/concepts/orders/emulated.md` "Risk checks apply at release";
`docs/concepts/execution/index.md` Trading state; and its own witness,
`crates/risk/tests/risk_engine.rs::test_emulated_release_risk_lifecycle` (commit b4a115e9), whose
cases `halted_stop` (denied `TRADING_HALTED`), `reducing_stop` (released) and `notional` (denied
`NOTIONAL_EXCEEDS_MAX_PER_ORDER`) these tests follow.

rc8's Python wheel binds `RiskEngineConfig` and sizing only (`crates/risk/src/python`), so a
Python node cannot set `HALTED` or `REDUCING`. The HALTED and REDUCING cases are the upstream Rust
witness above. What Python can witness is that a release now passes the risk engine (the `notional`
case), and that Sextant's exit is the order REDUCING admits: reduce-only, with no emulation trigger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, RiskEngineConfig, StrategyConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType,
    Currency,
    Money,
    OmsType,
    OrderSide,
    OrderType,
    Price,
    Quantity,
    QuoteTick,
    TraderId,
    TriggerType,
    Venue,
)
from nautilus_trader.testkit.providers import TestDataProvider, TestInstrumentProvider
from nautilus_trader.trading import Strategy

from sextant.backtest import exit_witness

AUDUSD = TestInstrumentProvider.default_fx_ccy("AUD/USD")


@dataclass
class _Plan:
    stop_qty: str
    reduce_only: bool
    log: list[tuple[str, str]] = field(default_factory=list)
    step: int = 0


class _EmulatedStop(Strategy):
    """Buys 10,000, then rests an emulated SELL STOP_MARKET one tick under the bid."""

    plan: _Plan

    def on_start(self) -> None:
        self.subscribe_quotes(AUDUSD.id)

    def on_quote(self, quote: QuoteTick) -> None:
        if self.plan.step == 0:
            self.plan.step = 1
            buy = self.order_factory.market(AUDUSD.id, OrderSide.BUY, Quantity.from_str("10000"))
            self.submit_order(buy)
        elif self.plan.step == 2:
            self.plan.step = 3
            trigger = Price.from_str(str(quote.bid_price.as_decimal() - Decimal("0.00001")))
            stop = self.order_factory.stop_market(
                AUDUSD.id,
                OrderSide.SELL,
                Quantity.from_str(self.plan.stop_qty),
                trigger,
                emulation_trigger=TriggerType.BID_ASK,
                reduce_only=self.plan.reduce_only,
            )
            self.submit_order(stop)

    def on_order_filled(self, event) -> None:
        self.plan.log.append(("filled", str(event.last_qty)))
        if self.plan.step == 1:
            self.plan.step = 2

    def on_order_released(self, event) -> None:
        self.plan.log.append(("released", ""))

    def on_order_denied(self, event) -> None:
        self.plan.log.append(("denied", str(event.reason).split(":")[0]))


def _run(plan: _Plan, max_notional: str | None) -> list[tuple[str, str]]:
    limits = {str(AUDUSD.id): max_notional} if max_notional else None
    engine = BacktestEngine(
        BacktestEngineConfig(
            trader_id=TraderId.from_str("BACKTESTER-001"),
            risk_engine=RiskEngineConfig(bypass=False, max_notional_per_order=limits),
        )
    )
    engine.add_venue(
        venue=Venue("SIM"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=Currency.from_str("USD"),
        starting_balances=[Money(1_000_000, Currency.from_str("USD"))],
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
    )
    engine.add_instrument(AUDUSD)
    engine.add_data(TestDataProvider.audusd_quotes())
    strategy = _EmulatedStop(StrategyConfig())
    strategy.plan = plan
    engine.add_strategy(strategy)
    engine.run()
    engine.dispose()
    return plan.log


def test_an_emulated_release_now_passes_the_risk_engine() -> None:
    # Upstream case `notional`. On rc7 the same release went straight to execution and filled
    # 100,000; on rc8 the risk engine denies it at release.
    log = _run(_Plan("100000", reduce_only=False), max_notional="50000")
    assert log == [
        ("filled", "10000"),
        ("released", ""),
        ("denied", "NOTIONAL_EXCEEDS_MAX_PER_ORDER"),
    ]


def test_a_reduce_only_emulated_stop_still_releases_and_fills() -> None:
    log = _run(_Plan("10000", reduce_only=True), max_notional=None)
    assert log == [("filled", "10000"), ("released", ""), ("filled", "10000")]


@pytest.fixture(scope="module")
def exit_orders(tmp_path_factory: pytest.TempPathFactory) -> tuple[exit_witness.Arm, list]:
    orders: list = []
    dispose = BacktestEngine.dispose

    def keep_orders(engine: BacktestEngine) -> None:
        orders.extend(engine.cache.orders())
        dispose(engine)

    def risk_on(bypass: bool) -> RiskEngineConfig:
        assert bypass
        return RiskEngineConfig(bypass=False)

    out = Path(tmp_path_factory.mktemp("exit"))
    with (
        mock.patch.object(exit_witness, "RiskEngineConfig", risk_on),
        mock.patch.object(exit_witness.BacktestEngine, "dispose", keep_orders),
    ):
        managed, _, _ = exit_witness.run(out)
    return managed, orders


def test_the_fast_exit_is_a_reduce_only_order_and_never_an_emulated_stop(exit_orders) -> None:
    # With the risk engine on, Sextant's exit sells exactly as it does with bypass: one reduce-only
    # GTC LIMIT, no emulation trigger. REDUCING admits it (upstream `reducing_stop`), and HALTED's
    # denial of emulated stops at release (upstream `halted_stop`) has no exit order to reach.
    managed, orders = exit_orders
    assert managed.exit_label == "managed_sell"
    assert managed.exit == "0.70864"
    sells = [o for o in orders if o.side == OrderSide.SELL]
    assert sells
    for order in sells:
        assert order.is_reduce_only
        assert order.emulation_trigger is None
        assert order.order_type == OrderType.LIMIT
    assert all(o.emulation_trigger is None for o in orders)
