"""Inert rc7 assembly and native simulated execution; no adapter or reconciliation stand-in."""

from dataclasses import replace
from decimal import Decimal as D

import pytest
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.common import Environment
from nautilus_trader.config import BacktestEngineConfig, RiskEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType,
    ClientOrderId,
    Currency,
    Equity,
    InstrumentId,
    Money,
    OmsType,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    TraderId,
    Venue,
)
from test_paper_config import account, ns
from test_paper_node import boundary as boundary
from test_paper_node import intent

from sextant.paper.native import PaperStrategy, PaperStrategyConfig, build_shell, node_config


def equity():
    return Equity(
        InstrumentId.from_str("AAPL.XNAS"),
        Symbol.from_str("AAPL"),
        Currency.from_str("USD"),
        2,
        Price.from_str("0.01"),
        0,
        0,
        lot_size=Quantity.from_str("1"),
    )


def test_risk_and_reconciliation_config_cannot_disable_the_shared_fences():
    cfg = node_config(account())
    assert cfg.environment == Environment.SANDBOX
    assert cfg.risk_engine.bypass is False
    assert cfg.risk_engine.max_notional_per_order == {}
    assert cfg.exec_engine.reconciliation is True
    assert cfg.exec_engine.filter_unclaimed_external_orders is True
    assert cfg.data_clients == {} and cfg.exec_clients == {}


def test_inert_live_node_has_the_account_namespace_and_no_connection(boundary):
    boundary.runtime.close()
    built = build_shell(boundary.config, boundary.runtime.budget, boundary.services)
    try:
        assert built.node.environment == Environment.SANDBOX
        assert not built.node.is_running
        assert built.runtime.services.writer.held
        assert built.strategy.config is not None
        assert built.strategy.config.external_order_instrument_ids == []
    finally:
        built.dispose()
    assert not boundary.services.writer.held


def test_native_limit_is_created_inside_the_gate_and_fills_in_backtest(boundary):
    events = []

    class Witness(PaperStrategy):
        def on_start(self):
            self.runtime.open()
            self.subscribe_quotes(InstrumentId.from_str("AAPL.XNAS"))

        def on_quote(self, quote):
            if not events:
                self.runtime.request(intent())
                for _kind, send, opts in boundary.queued:
                    if opts["admission"]():
                        send(lambda: None)
                boundary.queued.clear()
                events.append("sent")

        def on_order_filled(self, event):
            events.append(event)

    boundary.runtime.close()
    strategy = Witness(
        PaperStrategyConfig(
            account=replace(boundary.config, client_id="XNAS"),
            budget=boundary.runtime.budget,
            services=boundary.services,
        )
    )
    engine = BacktestEngine(
        BacktestEngineConfig(
            trader_id=TraderId.from_str("PAPERTEST-001"), risk_engine=RiskEngineConfig(bypass=False)
        )
    )
    usd = Currency.from_str("USD")
    engine.add_venue(
        venue=Venue.from_str("XNAS"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        base_currency=usd,
        starting_balances=[Money.from_str("10000 USD")],
        fee_model=MakerTakerFeeModel(maker_rate=D("0"), taker_rate=D("0")),
    )
    instrument = equity()
    engine.add_instrument(instrument)
    start = ns("2026-11-06T10:00:00")
    engine.add_data(
        [
            QuoteTick(
                instrument.id,
                Price.from_str("9.99"),
                Price.from_str("10.00"),
                Quantity.from_str("100"),
                Quantity.from_str("100"),
                t,
                t,
            )
            for t in (start, start + 1_000_000_000)
        ]
    )
    engine.add_strategy(strategy)
    try:
        engine.run(start=start)
        report = engine.generate_order_fills_report()
        assert len(report) == 1
        assert list(report.index) == ["A001-1"]
        assert str(report.iloc[0]["filled_qty"]) == "1"
        assert D(str(report.iloc[0]["avg_px"])) == D("10.00")
        assert "A001-1" in boundary.book.registrations
    finally:
        engine.dispose()


def test_live_or_wrong_account_services_fail_before_native_build(boundary):
    boundary.runtime.close()
    boundary.services.writer.scope.key = "ALPACA:different"
    with pytest.raises(ValueError, match="account mismatch"):
        build_shell(boundary.config, boundary.runtime.budget, boundary.services)


@pytest.mark.parametrize("order_type", ["STOP_MARKET", "STOP_LIMIT"])
def test_gtc_nonlimit_amend_after_close_refuses_without_halting(boundary, order_type):
    wire = []

    class Witness(PaperStrategy):
        def on_start(self):
            self.runtime.open()
            self.subscribe_quotes(InstrumentId.from_str("AAPL.XNAS"))

        def drain(self):
            while boundary.queued:
                _kind, send, options = boundary.queued.pop(0)
                if options["admission"]():
                    send(lambda: wire.append("accounted"))

        def on_quote(self, quote):
            if not boundary.book.registrations:
                assert self.runtime.request(intent())
            elif "A001-stop" not in boundary.book.registrations:
                entry = self.cache.order(ClientOrderId.from_str("A001-1"))
                assert entry is not None
                assert entry.status.name == "FILLED"
                fields = {
                    "STOP_MARKET": dict(price=None, trigger_price=D("9.50")),
                    "STOP_LIMIT": dict(price=D("9.49"), trigger_price=D("9.50")),
                }[order_type]
                assert self.runtime.request(
                    intent(
                        "PROTECT",
                        cid="A001-stop",
                        order_type=order_type,
                        time_in_force="GTC",
                        **fields,
                    )
                )
            self.drain()

    boundary.runtime.close()
    strategy = Witness(
        PaperStrategyConfig(
            account=replace(boundary.config, client_id="XNAS"),
            budget=boundary.runtime.budget,
            services=boundary.services,
        )
    )
    engine = BacktestEngine(
        BacktestEngineConfig(
            trader_id=TraderId.from_str("PAPERTEST-001"), risk_engine=RiskEngineConfig(bypass=False)
        )
    )
    engine.add_venue(
        venue=Venue.from_str("XNAS"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        base_currency=Currency.from_str("USD"),
        starting_balances=[Money.from_str("10000 USD")],
        fee_model=MakerTakerFeeModel(maker_rate=D("0"), taker_rate=D("0")),
    )
    instrument = equity()
    engine.add_instrument(instrument)
    start = ns("2026-11-06T10:00:00")
    engine.add_data(
        [
            QuoteTick(
                instrument.id,
                Price.from_str("9.99"),
                Price.from_str("10.00"),
                Quantity.from_str("100"),
                Quantity.from_str("100"),
                t,
                t,
            )
            for t in (start, start + 1_000_000_000)
        ]
    )
    engine.add_strategy(strategy)
    try:
        engine.run(start=start)
        cid = ClientOrderId.from_str("A001-stop")
        resting = strategy.cache.order(cid)
        assert resting is not None
        assert resting.order_type.name == order_type
        assert resting.time_in_force.name == "GTC"
        assert resting.status.name == "ACCEPTED"
        if not boundary.lease.held:
            strategy.runtime.open()
        strategy.clock.set_time(ns("2026-11-06T17:00:00"))
        assert strategy.runtime.request(intent("MODIFY", cid="A001-stop"))
        before = len(wire)
        strategy.drain()
        assert boundary.guard.active
        assert strategy.runtime.last_refusal is not None
        assert len(wire) == before
        remaining = strategy.cache.order(cid)
        assert remaining is not None
        assert remaining.status.name == "ACCEPTED"
    finally:
        engine.dispose()
