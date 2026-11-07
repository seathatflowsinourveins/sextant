"""Inert rc7 assembly and native simulated execution; no adapter or reconciliation stand-in."""

from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace as NS

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
from test_paper_row8 import row8 as row8

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


def run_witness(boundary, on_quote, *, balance="10000 USD", client_id="XNAS"):
    """One quote-driven PaperStrategy in rc7's BacktestEngine, RiskEngine on."""

    class Witness(PaperStrategy):
        def on_start(self):
            self.runtime.open()
            self.subscribe_quotes(InstrumentId.from_str("AAPL.XNAS"))

        def on_quote(self, quote):
            on_quote(self)

    boundary.runtime.close()
    strategy = Witness(
        PaperStrategyConfig(
            account=replace(boundary.config, client_id=client_id),
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
        starting_balances=[Money.from_str(balance)],
        fee_model=MakerTakerFeeModel(maker_rate=D("0"), taker_rate=D("0")),
    )
    instrument = equity()
    engine.add_instrument(instrument)
    start = ns("2026-11-06T10:00:00")
    quote = (Price.from_str("9.99"), Price.from_str("10.00"), Quantity.from_str("100"))
    engine.add_data([QuoteTick(instrument.id, *quote, quote[2], start, start)])
    engine.add_strategy(strategy)
    engine.run(start=start)
    return engine, strategy


def drain_with(boundary, hook):
    while boundary.queued:
        _kind, send, options = boundary.queued.pop(0)
        if options["admission"]():
            send(hook)


def test_an_rc7_denial_after_the_hook_releases_the_registration(boundary):
    """#151 review: rc7's RiskEngine denies after submit_order; OrderDenied proves no venue."""

    def on_quote(strategy):
        assert strategy.runtime.request(intent(quantity=D("2000")))  # notional > free cash
        drain_with(boundary, lambda: None)

    engine, strategy = run_witness(boundary, on_quote)
    try:
        order = strategy.cache.order(ClientOrderId.from_str("A001-1"))
        assert order is not None and order.status.name == "DENIED"
        assert boundary.book.registrations["A001-1"]["unsent"].startswith("denied before")
        assert boundary.guard.active
    finally:
        engine.dispose()


def test_a_raising_wire_hook_leaves_no_native_order_and_releases_the_row(boundary):
    def refuse_at_hook():
        raise ValueError("one admitted paced action permits one wire request")

    def on_quote(strategy):
        assert strategy.runtime.request(intent())
        drain_with(boundary, refuse_at_hook)

    engine, strategy = run_witness(boundary, on_quote)
    try:
        assert strategy.cache.order(ClientOrderId.from_str("A001-1")) is None
        assert boundary.book.registrations["A001-1"]["unsent"]  # the conforming send released it
        assert boundary.guard.active and boundary.sent == []
    finally:
        engine.dispose()


def test_a_price_finer_than_the_instrument_is_refused_before_the_hook(boundary):
    def on_quote(strategy):
        assert strategy.runtime.request(intent("EXIT", price=D("10.001")))
        drain_with(boundary, lambda: pytest.fail("a refused order must not reach the hook"))

    engine, strategy = run_witness(boundary, on_quote)
    try:
        assert (strategy.runtime.last_refusal or "").startswith("native validation refused")
        assert boundary.book.registrations == {}
        assert strategy.cache.order(ClientOrderId.from_str("A001-1")) is None
    finally:
        engine.dispose()


def test_a_representable_price_or_size_with_trailing_zeros_is_built_exactly(boundary):
    """#163 #88 review P3: 9.990 is 9.99 and 1.0 shares is 1; only finer values are refused."""

    def on_quote(strategy):
        assert strategy.runtime.request(intent(price=D("9.990"), quantity=D("1.0")))
        drain_with(boundary, lambda: None)

    engine, strategy = run_witness(boundary, on_quote)
    try:
        order = strategy.cache.order(ClientOrderId.from_str("A001-1"))
        assert order is not None and order.price == Price.from_str("9.99")
        assert order.quantity == Quantity.from_str("1")
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "changes",
    [dict(instrument="AAPL"), dict(quantity=D("1E+20")), dict(price=D("1E+15"))],
    ids=["venue-less-symbol", "beyond-quantity-range", "beyond-price-range"],
)
def test_rc7_value_errors_before_the_hook_are_native_refusals(boundary, changes):
    """#163 gate P3: a sizing or symbol bug is a quiet refusal, not an account halt."""

    def on_quote(strategy):
        assert strategy.runtime.request(intent(**changes))
        drain_with(boundary, lambda: pytest.fail("a refused order must not reach the hook"))

    engine, strategy = run_witness(boundary, on_quote)
    try:
        assert (strategy.runtime.last_refusal or "").startswith("native validation refused")
        assert boundary.book.registrations == {} and boundary.guard.active
    finally:
        engine.dispose()


def test_a_command_for_an_unregistered_client_is_denied_natively_and_released(boundary):
    """#163 gate P0: only a registered ExecutionClient reaches a wire. rc8's ExecutionEngine
    routes a command only to a registered client (crates/execution/src/engine/mod.rs:2191-2205,
    or OrderDeniedReason::NoExecutionClient) and claims the order for that client before it
    sends (:2524-2541); an order addressed to an unregistered client is denied, never sent,
    and the OrderDenied releases its registration."""

    def on_quote(strategy):
        assert strategy.runtime.request(intent())
        drain_with(boundary, lambda: None)

    engine, strategy = run_witness(boundary, on_quote, client_id="NOWHERE")
    try:
        order = strategy.cache.order(ClientOrderId.from_str("A001-1"))
        assert order is not None and order.status.name == "DENIED" and order.venue_order_id is None
        released = boundary.book.registrations["A001-1"]["unsent"]
        assert released.startswith("denied before the venue") and "client NOWHERE" in released
        assert boundary.guard.active
    finally:
        engine.dispose()


def test_the_shipped_prepare_on_row8_custody_pacer_and_guard_sends_exactly_once(row8):
    """#163 dsh-TUI P2-2: one proof joins the shipped _prepare with row 8's real custody, pacer,
    guard and writer lease in rc8's BacktestEngine. A recheck refused in the hook releases and
    sends nothing; an admitted ENTRY registers, counts one wire request and reaches the venue."""
    joined = NS(runtime=row8.runtime, config=row8.cfg, services=row8.services)
    done: list[str] = []

    def on_quote(strategy):
        if done:
            return
        done.append("quote")
        row8.services.submit_allowed = lambda _iid, _side, _qty, own_id: own_id is None
        assert strategy.runtime.request(intent(cid="A001-refused"))
        row8.services.submit_allowed = lambda *_args: True
        assert strategy.runtime.request(intent(cid="A001-sent"))

    engine, strategy = run_witness(joined, on_quote)
    try:
        assert row8.book.registrations["A001-refused"]["unsent"].startswith("NotSent")
        assert strategy.cache.order(ClientOrderId.from_str("A001-refused")) is None
        sent = strategy.cache.order(ClientOrderId.from_str("A001-sent"))
        assert sent is not None and sent.venue_order_id is not None  # the simulated venue took it
        assert "unsent" not in row8.book.registrations["A001-sent"]
        assert row8.pacer.wire_requests == 1 and row8.guard.entry_allowed()
    finally:
        engine.dispose()
