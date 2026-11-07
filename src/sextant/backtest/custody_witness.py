"""MODELED house-order kill drill through native rc7 matching/cache/portfolio/clock.

Framework: rc7 BacktestEngine example and Strategy APIs. Guard runtime shape:
pinned risk/actor.py::_cancel_entries/_close_residual/_on_check. An owner-labelled
fixture is NOT a native EXTERNAL claim, process-death test or broker receipt.
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, RiskEngineConfig, StrategyConfig
from nautilus_trader.execution import FeeModel, StaticLatencyModel
from nautilus_trader.model import (
    AccountType,
    ClientOrderId,
    Equity,
    Money,
    OmsType,
    OrderSide,
    Price,
    Quantity,
    QuoteTick,
    TimeInForce,
)
from nautilus_trader.trading import Strategy

from sextant.execution.custody import (
    AccountScope,
    AccountSnapshot,
    Custody,
    OrderFact,
    PositionAuthority,
    WriterLease,
)
from sextant.execution.pacer import AccountPacer, ActionKind
from sextant.risk.controls import Controls
from sextant.risk.guard import Guard


class _Config(StrategyConfig):
    def __init__(self, **inputs: Any):
        super().__init__()
        self.inputs = inputs


class _KillWitness(Strategy):
    def __init__(self, config: _Config):
        super().__init__(config)
        self.inputs = config.inputs
        self.instrument: Equity = self.inputs["instrument"]
        self.controls: Controls = self.inputs["controls"]
        self.quote: QuoteTick | None = None
        self.entered = self.killed = self.close_queued = False
        self.epoch = self.fills = 0
        self.minimum_net = Decimal(0)
        self.cancelled_ids: list[str] = []
        self.house: set[str] = set()
        self.owner_client_id: str | None = None
        self.errors: list[str] = []

    def on_start(self):
        account = self.portfolio.account(self.instrument.venue)
        if account is None:
            raise ValueError("native modeled account unavailable")
        out: Path = self.inputs["out"]
        scope = AccountScope("SIM", str(account.id))
        self.lease = WriterLease(scope, out / "locks", "native-kill-witness")
        self.lease.acquire()
        self.custody = Custody(scope, out / "custody.json", create=True)
        self.guard = Guard(scope, out / "guard.json", out / "kill", self.controls, mode="replay")
        self.pacer = AccountPacer(self.controls, self.clock.timestamp_ns)
        self.lease.bind_pacer(self.pacer)
        self._refresh()
        self.guard.initialize(self.custody.flat_receipt())
        self.subscribe_quotes(self.instrument.id)
        self.clock.set_timer_ns(
            "guard-check", self.controls.ns("flatten_tick_s"), callback=self._on_check
        )

    def _refresh(self):
        net = self.portfolio.net_position(self.instrument.id)
        self.minimum_net = min(self.minimum_net, net)
        facts = []
        for order in self.cache.orders():
            cid = str(order.client_order_id)
            vid = None if order.venue_order_id is None else str(order.venue_order_id)
            if cid in self.house and vid is not None:
                self.custody.link(cid, vid)
            facts.append(
                OrderFact(
                    cid,
                    str(order.instrument_id),
                    order.side.name,
                    order.quantity.as_decimal(),
                    order.filled_qty.as_decimal(),
                    order.status.name,
                    vid,
                    cid == self.owner_client_id,
                )
            )
        self.epoch += 1
        authority = PositionAuthority(net, "MODELED registered house fills, not external claiming")
        self.custody.observe(
            AccountSnapshot(
                self.custody.scope,
                self.epoch,
                {str(self.instrument.id): net},
                {str(self.instrument.id): authority},
                tuple(facts),
                True,
                self.clock.timestamp_ns(),
                "MODELED native cache/portfolio",
            ),
            now=self.clock.timestamp_ns(),
        )

    def on_quote(self, quote: QuoteTick):
        self.quote = quote
        self._on_check(None)

    def _on_check(self, event):
        try:
            self._cycle()
        except Exception as error:
            self.errors.append(type(error).__name__)
            self.guard.kill("witness_error", now=self.clock.timestamp_ns())

    def _cycle(self):
        if self.quote is None:
            return
        self._refresh()
        if not self.entered:
            self.entered = True
            if self.inputs["owner_resting_order"]:
                self._limit(OrderSide.BUY, Decimal(7), Price.from_str("1.00"), owner=True)
            self._limit(OrderSide.BUY, self.inputs["quantity"], self.quote.ask_price)
        now = self.clock.timestamp_ns()
        if not self.killed and now >= self.inputs["start_ns"] + self.inputs["kill_after_ns"]:
            self.killed = True
            self.guard.kill("manual", now=now)
        for intent in self.guard.step(self.custody, now=now):
            if intent.kind == "CANCEL_ENTRY":
                assert intent.client_order_id is not None
                cid = ClientOrderId(intent.client_order_id)

                def cancel(mark, cid=cid):
                    self._refresh()
                    if self.custody.may_cancel(str(cid)):
                        mark()
                        self.cancelled_ids.append(str(cid))
                        self.cancel_order(cid)

                self.pacer.request(ActionKind.CANCEL, cancel, admission=lambda: self.lease.held)
            elif intent.kind == "FLATTEN" and not self.close_queued:
                self.close_queued = True
                assert intent.quantity is not None
                self._limit(OrderSide.SELL, intent.quantity, self.quote.bid_price)
        self.pacer.drain()

    def _limit(self, side: OrderSide, quantity: Decimal, price: Price, *, owner=False):
        def send(mark):
            self._refresh()
            actual = quantity
            if side == OrderSide.SELL:
                actual = min(quantity, self.custody.available_exit(str(self.instrument.id)))
            if actual <= 0:
                self.close_queued = False
                return
            order = self.order_factory.limit(
                self.instrument.id,
                side,
                Quantity.from_str(str(actual)),
                price,
                time_in_force=TimeInForce.DAY,
                client_order_id=ClientOrderId("fixture-owner-entry") if owner else None,
            )
            cid = str(order.client_order_id)
            if owner:
                self.owner_client_id = cid
            else:
                self.house.add(cid)
                self.custody.register(
                    cid,
                    str(self.instrument.id),
                    side.name,
                    actual,
                    source="MODELED native order factory",
                )
            mark()
            self.submit_order(order)
            self.close_queued = False

        kind = ActionKind.REDUCE if side == OrderSide.SELL else ActionKind.SUBMIT
        self.pacer.request(
            kind,
            send,
            admission=lambda: (
                self.lease.held and (owner or side == OrderSide.SELL or self.guard.entry_allowed())
            ),
        )

    def on_order_filled(self, event):
        self.fills += 1
        self.pacer.record_fill()

    def on_stop(self):
        self.lease.close()


@dataclass(frozen=True)
class Witness:
    broker_net: Decimal
    minimum_net: Decimal
    state: str
    flat_receipt: bool
    fills: int
    order_types: set[str]
    entry_allowed: bool
    owner_client_id: str | None
    owner_status: str | None
    cancelled_ids: list[str]
    errors: list[str]
    fixture_only: bool
    params_hash: str
    tier: str = "MODELED"


def run(
    *,
    instrument: Equity,
    quotes: list[QuoteTick],
    out: Path,
    controls: Controls,
    starting_cash: Decimal,
    quantity: Decimal,
    kill_after_ns: int,
    owner_resting_order: bool,
    fee_model: FeeModel,
    latency_model: StaticLatencyModel | None = None,
) -> Witness:
    if not controls.fixture or not quotes:
        raise ValueError("this is a fixture-only native mechanism witness")
    engine = BacktestEngine(
        BacktestEngineConfig(bypass_logging=True, risk_engine=RiskEngineConfig(bypass=False))
    )
    try:
        engine.add_venue(
            venue=instrument.venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=instrument.quote_currency,
            starting_balances=[Money.from_str(f"{starting_cash} {instrument.quote_currency}")],
            fee_model=fee_model,
            latency_model=latency_model,
        )
        engine.add_instrument(instrument)
        engine.add_data(quotes)
        strategy = _KillWitness(
            _Config(
                instrument=instrument,
                out=out,
                controls=controls,
                quantity=quantity,
                start_ns=quotes[0].ts_init,
                kill_after_ns=kill_after_ns,
                owner_resting_order=owner_resting_order,
            )
        )
        engine.add_strategy(strategy)
        engine.run()
        strategy._refresh()
        owner = (
            None
            if strategy.owner_client_id is None
            else engine.cache.order(ClientOrderId(strategy.owner_client_id))
        )
        return Witness(
            engine.portfolio.net_position(instrument.id),
            strategy.minimum_net,
            str(strategy.guard.state),
            strategy.custody.flat_receipt() is not None,
            strategy.fills,
            {o.order_type.name for o in engine.cache.orders()},
            strategy.guard.entry_allowed(),
            strategy.owner_client_id,
            None if owner is None else owner.status.name,
            strategy.cancelled_ids,
            strategy.errors,
            controls.fixture,
            controls.params_hash,
        )
    finally:
        engine.dispose()
