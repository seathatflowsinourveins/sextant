"""Native shell, ALPACA sandbox registration and the SIMULATED startup ledger."""

import asyncio
import gc
import json
import re
import time
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace as NS
from typing import Any, cast

import pytest
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.common import Environment
from nautilus_trader.config import BacktestEngineConfig, RiskEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel, StaticLatencyModel
from nautilus_trader.model import (
    AccountId,
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

from sextant.paper.native import (
    PaperStrategy,
    PaperStrategyConfig,
    build_shell,
    node_config,
    record_sandbox_run,
    sandbox_client_config,
)
from sextant.ranking.engine import Segment
from sextant.validation.trials import TrialLog, snapshot_hash


def equity(**extra):
    return Equity(
        InstrumentId.from_str("AAPL.XNAS"),
        Symbol.from_str("AAPL"),
        Currency.from_str("USD"),
        2,
        Price.from_str("0.01"),
        0,
        0,
        lot_size=Quantity.from_str("1"),
        **extra,
    )


def test_risk_and_reconciliation_config_cannot_disable_the_shared_fences():
    cfg = node_config(account())
    assert cfg.environment == Environment.SANDBOX
    assert cfg.risk_engine.bypass is False
    assert cfg.risk_engine.max_notional_per_order == {}
    assert cfg.exec_engine.reconciliation is True
    assert cfg.exec_engine.filter_unclaimed_external_orders is True
    # #195: after its retries rc8's in-flight check would mark a lost cancel CANCELED locally
    assert cfg.exec_engine.inflight_check_interval_ms == 0
    assert cfg.data_clients == {} and cfg.exec_clients == {}


def test_inert_live_node_has_the_account_namespace_and_no_connection(boundary):
    boundary.runtime.close()
    built = build_shell(
        boundary.config,
        boundary.runtime.budget,
        boundary.services,
        starting_balance="10000 USD",
    )
    try:
        environment, running = built.node.environment, built.node.is_running
        held = built.runtime.services.writer.held
        config = built.strategy.config
    finally:
        try:
            built.dispose()
        finally:
            del built
            gc.collect()
    assert environment == Environment.SANDBOX
    assert not running
    assert held
    assert config is not None
    assert config.external_order_instrument_ids == []
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
        build_shell(
            boundary.config,
            boundary.runtime.budget,
            boundary.services,
            starting_balance="10000 USD",
        )


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


def run_witness(
    boundary,
    on_quote,
    *,
    balance="10000 USD",
    client_id="XNAS",
    extra=None,
    quotes=1,
    latency=None,
    book=None,
):
    """One quote-driven PaperStrategy in rc7's BacktestEngine, RiskEngine on; `book(n)` gives
    quote n's bid, ask and size."""

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
        latency_model=latency,
    )
    instrument = equity(**(extra or {}))
    engine.add_instrument(instrument)
    start = ns("2026-11-06T10:00:00")

    def tick(n):  # one quote a second
        bid, ask, size = (book or (lambda _n: ("9.99", "10.00", "100")))(n)
        at, depth = start + n * 1_000_000_000, Quantity.from_str(size)
        return QuoteTick(
            instrument.id, Price.from_str(bid), Price.from_str(ask), depth, depth, at, at
        )

    engine.add_data([tick(n) for n in range(quotes)])
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


@pytest.mark.parametrize(
    "bound, quantity, sent",
    [("max_quantity", "5", True), ("max_quantity", "6", False),
     ("min_quantity", "5", True), ("min_quantity", "4", False)],
)  # fmt: skip
def test_a_quantity_outside_the_instruments_bounds_is_refused_before_the_token(
    boundary, bound, quantity, sent
):
    """#187: rc8's RiskEngine denies a quantity above max_quantity or below min_quantity only
    after the pacer's token (crates/risk/src/engine/mod.rs:1782-1799 at d53849b2, strict > and
    <). _prepare refuses exactly those first, so a refusal that can only repeat spends nothing;
    a quantity equal to a bound is sent, as rc8 sends it."""
    assert node_config(account()).risk_engine.full_position_exit_venues == []  # no exemption
    hooks: list[str] = []

    def on_quote(strategy):
        strategy.runtime.request(intent("EXIT", quantity=D(quantity)))
        drain_with(boundary, lambda: hooks.append("hook"))

    extra = {bound: Quantity.from_str("5")}
    engine, strategy = run_witness(boundary, on_quote, extra=extra)
    try:
        order = strategy.cache.order(ClientOrderId.from_str("A001-1"))
        if sent:
            assert hooks == ["hook"] and order is not None
        else:
            assert hooks == [] and order is None and boundary.book.registrations == {}
            assert "minimum and maximum" in (strategy.runtime.last_refusal or "")
    finally:
        engine.dispose()


def test_an_unanswered_cancel_is_recorded_once_a_late_read_still_shows_the_order_open(boundary):
    """#195: rc8 marks the order PENDING_CANCEL when its cancel leaves and drops every later
    cancel, so a cancel the venue never answers left the entry live with nothing recorded.
    Here rc8's own simulated venue takes 1,000 s to answer, and the entry fills a share a second
    meanwhile: each partial fill keeps it pending but moves its ts_last. Every re-emitted CANCEL is
    refused before the token. The first read taken cancel_timeout_s (10 s) after rc8's
    OrderPendingCancel that still shows the order open records the unknown outcome, names the
    order and marks it durably."""
    steps: list[tuple[int, str | None, bool]] = []
    native: list[tuple[str, D, int]] = []  # rc8's order state after each quote

    def on_quote(strategy):
        now = strategy.clock.timestamp_ns()
        boundary.book.snapshot.known_at = now  # each read still shows the order open
        if not steps:
            strategy.runtime.request(intent(quantity=D("20"), price=D("9.50")))  # rests
        else:
            strategy.runtime.request(intent("CANCEL"))
        drain_with(boundary, lambda: None)
        steps.append((now, strategy.runtime.last_refusal, boundary.guard.active))
        order = strategy.cache.order(ClientOrderId.from_str("A001-1"))
        native.append((order.status.name, order.filled_qty.as_decimal(), order.ts_last))

    lost = StaticLatencyModel(cancel_latency_nanos=1_000 * 1_000_000_000)
    offers = lambda n: ("9.99", "10.00", "100") if n < 2 else ("9.49", "9.50", "1")  # noqa: E731
    engine, _strategy = run_witness(boundary, on_quote, quotes=13, latency=lost, book=offers)
    try:
        stamp = steps[1][0]  # rc8 stamps PENDING_CANCEL as the cancel leaves (mod.rs:891-911)
        assert {status for status, _filled, _last in native[1:]} == {"PENDING_CANCEL"}
        assert native[1][1] == 0 < native[2][1] < native[12][1]  # it fills while it waits
        assert native[11][2] == steps[11][0] > stamp  # each fill moves ts_last, not the stamp
        assert steps[1][1:] == (None, True)
        assert boundary.book.registrations["A001-1"]["cancel_sends"] == 1  # one wire CANCEL
        pending = "native validation refused: native order is already pending cancel"
        assert [step[1:] for step in steps[2:11]] == [(pending, True)] * 9  # 1 s to 9 s later
        unanswered = "cancel unanswered for A001-1"
        assert steps[11][1:] == steps[12][1:] == (unanswered, False)  # 10 s later, and after
        assert _strategy.runtime.last_error == unanswered
        assert boundary.book.registrations["A001-1"]["cancel_unanswered"] is True
    finally:
        engine.dispose()


def test_a_cancel_of_a_pending_or_closed_native_order_is_refused_before_the_token(boundary):
    """#190 reviews: rc8's Strategy.cancel_order logs and drops a cancel of an order already
    pending cancel or closed (crates/trading/src/strategy/mod.rs:629-631, 822-827). _prepare
    refuses it before the token, so it neither spends one nor counts toward the cap. A cancel
    of an order whose modify is in flight still leaves, as rc8 moves PENDING_UPDATE to
    PENDING_CANCEL (model/src/orders/mod.rs:257). The guard's re-emissions come seconds apart,
    so each step runs on its own quote. rc8's venue never answers the modify and answers the
    cancel 0.5 s after it leaves: the next quote finds it pending, the one after closed."""
    steps: list[tuple[str | None, str]] = []

    def on_quote(strategy):
        if not steps:
            strategy.runtime.request(intent(price=D("9.00")))  # rests below the 9.99 bid
        elif len(steps) == 1:
            strategy.runtime.request(intent("MODIFY", price=D("9.01")))
        else:
            strategy.runtime.request(intent("CANCEL"))
        drain_with(boundary, lambda: None)
        order = strategy.cache.order(ClientOrderId.from_str("A001-1"))
        steps.append((strategy.runtime.last_refusal, order.status.name))

    never = 1_000 * 1_000_000_000
    answer = StaticLatencyModel(update_latency_nanos=never, cancel_latency_nanos=500_000_000)
    engine, _strategy = run_witness(boundary, on_quote, quotes=5, latency=answer)
    try:
        refused = "native validation refused: native order is already"
        assert steps[1:] == [
            (None, "PENDING_UPDATE"),
            (None, "PENDING_CANCEL"),  # leaves although the modify is in flight
            (f"{refused} pending cancel", "PENDING_CANCEL"),
            (f"{refused} closed", "CANCELED"),
        ]
        assert boundary.book.registrations["A001-1"]["cancel_sends"] == 1
    finally:
        engine.dispose()


def test_a_rejected_then_lost_cancel_ages_from_the_lost_cancels_stamp(row8):
    """#198 P2-3, adopted from #88's probe test_r1p_rejected_then_lost (review of #190 at
    1b5835e): rc8 restores an order's prior status on OrderCancelRejected (model/src/orders/
    mod.rs:943-951, 1067-1069), so the next CANCEL leaves and stamps a second OrderPendingCancel.
    The record ages from that latest stamp, never the first; real rc8 order, shipped _prepare,
    row 8's custody, pacer and guard."""
    from nautilus_trader.core import UUID4
    from nautilus_trader.model import (
        AccountId,
        LimitOrder,
        OrderAccepted,
        OrderCancelRejected,
        OrderPendingCancel,
        OrderSide,
        OrderSubmitted,
        StrategyId,
        TimeInForce,
        VenueOrderId,
    )
    from test_paper_row8 import read

    cid, iid = ClientOrderId.from_str("A001-entry00"), InstrumentId.from_str("AAPL.XNAS")
    tid, sid = TraderId.from_str("PAPERA001-001"), StrategyId.from_str("PAPER-A001")
    aid, vid, t0 = AccountId.from_str("ALPACA-A"), VenueOrderId("v0"), row8.clock[0]
    size, price = Quantity.from_str("20"), Price.from_str("9.50")
    order = LimitOrder(tid, sid, iid, cid, OrderSide.BUY, size, price, TimeInForce.DAY, False,
                       False, False, UUID4(), t0)  # fmt: skip
    order.apply(OrderSubmitted(tid, sid, iid, cid, aid, UUID4(), t0, t0))
    order.apply(OrderAccepted(tid, sid, iid, cid, vid, aid, UUID4(), t0, t0, False))
    left: list[int] = []

    def cancel_order(_cid, client_id=None):  # Strategy.cancel_order's marking (mod.rs:818-865)
        if not (order.is_closed or order.is_pending_cancel):
            now = row8.clock[0]
            order.apply(OrderPendingCancel(tid, sid, iid, cid, aid, UUID4(), now, now, False, vid))
            left.append(now)

    instrument = equity()
    native = NS(
        cache=NS(order=lambda c: order if c == cid else None,
                 instrument=lambda i: instrument if i == instrument.id else None),
        clock=NS(timestamp_ns=lambda: row8.clock[0]), account=row8.cfg, cancel_order=cancel_order,
    )  # fmt: skip
    shipped = row8.runtime.prepare
    row8.runtime.prepare = lambda i: (
        PaperStrategy._prepare(cast(Any, native), i) if i.action == "CANCEL" else shipped(i)
    )
    row8.book.register(str(cid), str(iid), "BUY", D("20"), source="FIXTURE resting house entry")
    row8.book.link(str(cid), "v0")
    entry = row8.custody_module.OrderFact(str(cid), str(iid), "BUY", D("20"), D("0"), "NEW", "v0")
    read(row8, {}, [entry])
    kills: list[int] = []
    kill = row8.guard.kill
    row8.guard.kill = lambda reason, **kw: (
        (kills.append(row8.clock[0]) if reason == "unknown_execution_outcome" else None)
        or kill(reason, **kw)
    )
    row8.runtime.open()
    try:
        row8.runtime.halt("owner")  # the first CANCEL leaves at once
        for _tick in range(20):  # 40 s of 2 s pulses; every read still shows the entry open
            row8.clock[0] += 2 * 1_000_000_000
            if len(left) == 1 and order.is_pending_cancel:  # the venue refuses it 0.5 s after
                at = left[0] + 500_000_000
                order.apply(OrderCancelRejected(tid, sid, iid, cid, "venue refused", UUID4(), at,
                                                at, False, vid, aid))  # fmt: skip
            read(row8, {}, [entry])
            row8.runtime.pulse()
        assert len(left) == 2 and row8.book.cancel_sends(str(cid)) == 2  # rejected, then lost
        assert kills and kills[0] - left[-1] >= row8.params.ns("cancel_timeout_s")
    finally:
        row8.runtime.close()


def _sandbox_segment() -> Segment:
    return Segment(
        "OVERNIGHT",
        date(2026, 11, 9),
        1_700_000_000_000_000_000,
        1_700_000_360_000_000_000,
        "fixture receipt",
    )


async def _wait_for_sandbox_account(node, account_id):
    portfolio, handle = node.portfolio, node.handle()
    task = asyncio.create_task(node.run_async())
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            account = portfolio.account(account_id=account_id)
            if account is not None:
                return account
            await asyncio.sleep(0.01)
        raise AssertionError("the sandbox client never registered its account")
    finally:
        handle.stop()
        await asyncio.sleep(0.2)
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_sandbox_client_config_binds_the_alpaca_venue_and_the_callers_balance():
    config = sandbox_client_config(account(), "10000 USD")

    assert str(config.venue) == "ALPACA"
    assert str(config.account_id) == "SIM-A001"
    assert [str(balance) for balance in config.starting_balances] == ["10000.00 USD"]
    assert str(config.base_currency) == "USD"
    assert type(config.fee_model).__name__ == "FixedFeeModel"
    assert "Money(0.00, USD)" in repr(config.fee_model)


@pytest.mark.parametrize("starting_balance", ["0 USD", "-10 USD", "10000 EUR", "not money"])
def test_sandbox_client_config_refuses_a_balance_without_authority(starting_balance):
    with pytest.raises(ValueError, match="starting balance"):
        sandbox_client_config(account(), starting_balance)


def test_build_shell_registers_the_sandbox_client_for_the_sandbox_account(boundary):
    boundary.runtime.close()
    built = build_shell(
        boundary.config,
        boundary.runtime.budget,
        boundary.services,
        starting_balance="10000 USD",
    )
    try:
        running_before = built.node.is_running
        sandbox = asyncio.run(_wait_for_sandbox_account(built.node, AccountId.from_str("SIM-A001")))
        balance = sandbox.balances_total()[Currency.from_str("USD")]
        running_after = built.node.is_running
    finally:
        try:
            built.dispose()
        finally:
            del built
            gc.collect()
    assert not running_before
    assert balance == Money.from_str("10000 USD")
    assert not running_after


def test_record_sandbox_run_writes_one_receipt_and_one_simulated_row(tmp_path):
    ledger = tmp_path / "reports" / "research" / "trials.parquet"
    segment = _sandbox_segment()
    receipt = record_sandbox_run(
        account=account(),
        run_id="sim-run-1",
        symbols=("OMH.ALPACA",),
        segment=segment,
        started_ns=segment.start_ns,
        starting_balance="10000 USD",
        entry_params_hash="a" * 64,
        ledger_path=ledger,
        reports_dir=tmp_path / "reports" / "sim",
    )

    assert receipt == tmp_path / "reports" / "sim" / "sim-run-1" / "session.json"
    payload = json.loads(receipt.read_text())
    assert payload["tier"] == "SIMULATED"
    assert payload["lane"] == "sim"
    assert payload["account_suffix"] == "A001"
    assert payload["receipt_id"] == "sim-run-1"
    assert payload["symbols"] == ["OMH.ALPACA"]
    assert payload["entry_params_hash"] == "a" * 64
    assert payload["stopped_ns"] is None
    assert payload["final_segment"] is None
    assert payload["segment"] == {
        "name": "OVERNIGHT",
        "session_date": "2026-11-09",
        "start_ns": segment.start_ns,
        "end_ns": segment.end_ns,
    }
    sandbox = payload["sandbox_config"]
    assert sandbox == {
        "tier": "SIMULATED",
        "venue": "ALPACA",
        "account_id": "SIM-A001",
        "starting_balance": "10000.00 USD",
        "block_set_id": f"sim:2026-11-09:OVERNIGHT:{segment.start_ns}",
    }
    assert payload["sandbox_config_hash"] == snapshot_hash(sandbox)

    rows = TrialLog(ledger).records
    assert len(rows) == 1
    row = rows[0]
    config = json.loads(row["config"])
    params = json.loads(row["params"])
    assert row["strategy"] == "sim-sandbox"
    assert row["state"] == "RUNNING"
    assert row["n_trials"] == 1
    assert row["effective_n"] == 1.0  # archive #110 no-discount count fallback
    assert config["tier"] == "SIMULATED"
    assert config["arm_id"] == "sim-sandbox"
    assert config["arm_run_id"] == "sim-run-1"
    assert config["block_set_id"] == sandbox["block_set_id"]
    assert config["sandbox_config"] == sandbox
    assert config["sandbox_config_hash"] == snapshot_hash(sandbox)
    assert config["params_hash"] == snapshot_hash(params)
    assert config["implementation_sha"] == payload["implementation_sha"]
    assert re.fullmatch(r"[0-9a-f]{40}", config["implementation_sha"])
    assert config["factor_mask"] == []
    assert config["funding_divergent_session_count"] is None
    assert config["funding_unverified_session_count"] is None
    assert config["condition_returns"] == {}
    assert params["symbols"] == ["OMH.ALPACA"]
    assert params["segment"] == "OVERNIGHT"
    assert params["session_date"] == "2026-11-09"
    assert params["started_ns"] == segment.start_ns
    assert params["entry_params_hash"] == "a" * 64


def test_record_sandbox_run_refuses_a_reused_run_id(tmp_path):
    ledger = tmp_path / "trials.parquet"
    reports = tmp_path / "reports" / "sim"
    kwargs: dict[str, Any] = dict(
        account=account(),
        run_id="sim-run-1",
        symbols=("OMH.ALPACA",),
        segment=_sandbox_segment(),
        started_ns=_sandbox_segment().start_ns,
        starting_balance="10000 USD",
        entry_params_hash="a" * 64,
        ledger_path=ledger,
        reports_dir=reports,
    )
    record_sandbox_run(**kwargs)

    with pytest.raises(ValueError, match="arm_run_id already logged"):
        record_sandbox_run(**kwargs)
    assert len(TrialLog(ledger).records) == 1


@pytest.mark.parametrize("run_id", ["../escape", "a/b", "", "."])
def test_record_sandbox_run_refuses_an_unsafe_run_id(tmp_path, run_id):
    with pytest.raises(ValueError, match="run id"):
        record_sandbox_run(
            account=account(),
            run_id=run_id,
            symbols=("OMH.ALPACA",),
            segment=_sandbox_segment(),
            started_ns=_sandbox_segment().start_ns,
            starting_balance="10000 USD",
            entry_params_hash="a" * 64,
            ledger_path=tmp_path / "trials.parquet",
            reports_dir=tmp_path / "reports" / "sim",
        )
    assert not (tmp_path / "reports").exists()


def test_record_sandbox_run_refuses_a_malformed_entry_parameter_hash(tmp_path):
    with pytest.raises(ValueError, match="entry_params_hash"):
        record_sandbox_run(
            account=account(),
            run_id="sim-run-1",
            symbols=("OMH.ALPACA",),
            segment=_sandbox_segment(),
            started_ns=_sandbox_segment().start_ns,
            starting_balance="10000 USD",
            entry_params_hash="not-a-hash",
            ledger_path=tmp_path / "trials.parquet",
            reports_dir=tmp_path / "reports" / "sim",
        )
    assert not (tmp_path / "reports").exists()
