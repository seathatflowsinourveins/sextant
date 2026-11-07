"""One native entry episode; N1/N2/N4/N5 sources and limits are in ADR-0004."""

from collections import namedtuple
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

from nautilus_trader import model
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, RiskEngineConfig
from nautilus_trader.execution import FeeModel, StaticLatencyModel
from nautilus_trader.trading import Strategy

from sextant.entry.orders import funding_unit_cost, limit_price, within_chase
from sextant.entry.parameters import EntryParameters, number
from sextant.entry.signals import EntryState, Surge, TradeCoverage
from sextant.entry.sizing import SegmentBasis, size_entry

ReplayResult = namedtuple(
    "ReplayResult",
    "events orders params_hash fixture_only tier failed failure_reason",
    defaults=("MODELED", False, None),
)


def _guarded(method):
    def handle(self, *args):
        if self.signals.failure and method.__name__ not in {"_expire", "on_order_event"}:
            return
        try:
            method(self, *args)
        except Exception as exc:
            self.signals.failure = f"{type(exc).__name__}: {exc}"
            self._record("FAIL", reason=self.signals.failure)

    return handle


class _ReplayEntry(Strategy):
    def __new__(cls, *_args: Any, **_kwargs: Any) -> Self:
        return super().__new__(cls)

    def __init__(self, **inputs: Any):
        super().__init__()
        segment, surge = inputs["segment"], inputs["surge"]
        self.instrument, self.parameters = inputs["instrument"], inputs["params"]
        self.signals = EntryState(
            self.instrument.id, self.parameters, segment, start_ns=inputs["segment_start_ns"]
        )
        if surge is not None:
            self.signals.arm(surge)
        self.buffer, self.basis_path = number(inputs["buffer"], "buffer"), inputs["basis_path"]
        self.regular_hours, self.confidence = inputs["regular_hours"], inputs["confidence"]
        self.coverage: TradeCoverage | None = inputs["coverage"]
        self.commission_rate: Decimal | None = inputs["commission_rate"]
        self.quote: model.QuoteTick | None = None
        self.entry: Any = None
        self.first_limit: Decimal | None = None
        self.expiry_ns: int | None = None
        self.basis: Decimal | None = None
        self.events: list[dict[str, Any]] = []
        self.expired = False
        self.decided_ns: int | None = None

    @_guarded
    def on_start(self) -> None:
        account = self.portfolio.account(self.instrument.venue)
        if account is not None:
            store = SegmentBasis(self.basis_path, str(account.id), self.parameters)
            self.basis = store.freeze(
                self.signals.segment, self._balance("free"), first_read="node_start"
            )
        self.subscribe_trades(self.instrument.id)
        self.subscribe_quotes(self.instrument.id)
        self.subscribe_bars(self.signals.bar_type)

    @_guarded
    def on_bar(self, bar: model.Bar) -> None:
        self.signals.on_bar(bar, now=self.clock.timestamp_ns())

    def _record(self, action: str, **terms) -> None:
        self.events.append(dict(action=action, ts=self.clock.timestamp_ns(), **terms))

    @_guarded
    def on_trade(self, trade: model.TradeTick) -> None:
        now = self.clock.timestamp_ns()
        accepted = self.signals.on_trade(trade, now=now)
        if self.signals.failure:
            self._record("FAIL", reason=self.signals.failure)
        if accepted:
            self._record("TRADE", extension=str(self.signals.extension))
            event_ns = self.signals.reclaim_event_ns
            self._decide()
            if event_ns is not None:
                self.decided_ns = event_ns

    @_guarded
    def on_quote(self, quote: model.QuoteTick) -> None:
        if (
            not 0 <= quote.ts_event <= quote.ts_init <= self.clock.timestamp_ns()
            or not 0 < quote.bid_price.as_decimal() <= quote.ask_price.as_decimal()
            or (self.quote is not None and quote.ts_event < self.quote.ts_event)
        ):
            return
        self.quote = quote
        self._decide()

    def _balance(self, name: str):
        account = self.portfolio.account(self.instrument.venue)
        if account is None:
            return None
        balance = getattr(account, f"balance_{name}")(self.instrument.quote_currency)
        return None if balance is None else balance.as_decimal()

    def _sizing(self, price: Decimal, setup: str, now: int):
        total, free = self._balance("total"), self._balance("free")
        if free is not None and self.entry is not None and self.entry.is_open:
            free += self.entry.leaves_qty.as_decimal() * self.entry.price.as_decimal()
            # Full-order caps include fills, but funding is needed only for the leaves.
            free += self.entry.filled_qty.as_decimal() * funding_unit_cost(
                price, self.commission_rate, self.instrument.quote_currency.precision
            )
        volume = self.signals.tape.dollar_volume(
            now - self.parameters.ns("flow_share_window_s"), now
        )
        return size_entry(
            instrument=self.instrument,
            params=self.parameters,
            setup=setup,
            entry=price,
            initial_trigger=price - self.buffer,
            equity=total,
            basis=self.basis,
            buying_power=free,
            dollar_volume=volume,
            confidence=None if setup == "FIRST_LEG" else self.confidence,
            prearm_stopouts=0,
            commission_rate=self.commission_rate,
        )

    def _ready(self, setup: str, price: Decimal, now: int) -> bool:
        if setup == "FIRST_LEG":
            return self.signals.first_leg_ready(price, now)
        return self.signals.reclaim_ready(
            price, self.buffer, now, covered_flow=self.signals.covered_flow(now, self.coverage)
        )

    def _decide(self) -> None:
        now = self.clock.timestamp_ns()
        if self.expiry_ns is not None and now >= self.expiry_ns:
            self._expire(None)
        if self.expired or not self.signals.fresh(now):
            return
        quote = self.quote
        if quote is None or now - quote.ts_event > self.parameters.ns("max_data_age_s"):
            return
        price = limit_price(
            quote.ask_price.as_decimal(), self.instrument.price_increment.as_decimal()
        )
        native_price = model.Price.from_decimal_dp(price, self.instrument.price_precision)
        modifying = self.entry is not None
        if modifying:
            current = self.cache.order(self.entry.client_order_id)
            if current is None or not current.is_open or current.is_inflight:
                return
            self.entry, setup = current, self.setup
            if self.first_limit is None or price <= self.entry.price.as_decimal():
                return
            if not self._ready(setup, price, now):
                return
            if not within_chase(price, self.first_limit, self.parameters):
                self._record("REFUSE", stage="MODIFY", reason="entry_chase_bps", limit=str(price))
                return
        elif self._ready("FIRST_LEG", price, now):
            setup = "FIRST_LEG"
        elif self.signals.reclaim_event_ns != self.decided_ns and self._ready(
            "RECLAIM", price, now
        ):
            setup = "RECLAIM"
        else:
            return
        sizing = self._sizing(price, setup, now)
        reason = sizing.refusal
        if modifying and sizing.quantity.as_decimal() < self.entry.quantity.as_decimal():
            reason = reason or "quantity"
        terms = sizing.journal()
        if modifying:
            terms["stage"] = "MODIFY"
        if reason:
            self._record("REFUSE", reason=reason, **terms)
        elif modifying:
            self._record("MODIFY", limit=str(price), **terms)
            self.modify_order(self.entry.client_order_id, price=native_price)
        if reason or modifying:
            return
        self.setup, self.first_limit = setup, price
        self.entry = self.order_factory.limit(
            self.instrument.id,
            model.OrderSide.BUY,
            sizing.quantity,
            native_price,
            time_in_force=model.TimeInForce.DAY,
            tags=[f"params_hash={self.parameters.params_hash}", f"setup={setup}"],
        )
        self.expiry_ns = expiry_ns = now + self.parameters.ns("entry_ttl_s")
        self._record(
            "SUBMIT",
            setup=setup,
            limit=str(price),
            extension=str(self.signals.extension),
            confidence=(None if setup == "FIRST_LEG" else str(self.confidence)),
            extended_hours=not self.regular_hours,
            order_type="LIMIT",
            contingency_type=getattr(self.entry.contingency_type, "name", None),
            **terms,
        )
        self.clock.set_time_alert_ns("entry-ttl", expiry_ns, callback=self._expire)
        self.submit_order(self.entry, params={"extended_hours": not self.regular_hours})

    @_guarded
    def _expire(self, _event) -> None:
        self.expired = True
        if self.entry is not None:
            self.entry = self.cache.order(self.entry.client_order_id) or self.entry
        if self.entry is not None and self.entry.is_open and not self.entry.is_pending_cancel:
            self._record("CANCEL")
            self.cancel_order(self.entry.client_order_id)

    @_guarded
    def on_order_event(self, event) -> None:
        if isinstance(event, (model.OrderAccepted, model.OrderUpdated, model.OrderModifyRejected)):
            if self.expired:
                self._expire(None)
            elif not isinstance(event, model.OrderModifyRejected):
                self._decide()


def run_replay(
    *,
    instrument: model.Equity,
    params: EntryParameters,
    data: list,
    basis_path: Path,
    segment: str,
    segment_start_ns: int,
    surge: Surge | None,
    buffer: Decimal,
    starting_cash: Decimal,
    regular_hours: bool,
    confidence: Decimal | None,
    fee_model: FeeModel,
    coverage: TradeCoverage | None = None,
    latency_model: StaticLatencyModel | None = None,
    fill_model: Any = None,
    commission_rate: Decimal | None = None,
) -> ReplayResult:
    """Offline arm; an explicit per-fill fee bound is required (ADR-0004)."""
    inputs = locals()
    starting_cash = number(starting_cash, "starting_cash", zero=True)
    engine = BacktestEngine(
        BacktestEngineConfig(bypass_logging=True, risk_engine=RiskEngineConfig(bypass=False))
    )
    try:
        engine.add_venue(
            venue=instrument.venue,
            oms_type=model.OmsType.NETTING,
            account_type=model.AccountType.CASH,
            base_currency=instrument.quote_currency,
            starting_balances=[
                model.Money.from_str(f"{starting_cash} {instrument.quote_currency}")
            ],
            latency_model=latency_model,
            fee_model=fee_model,
            trade_execution=False,
            bar_execution=False,
            fill_model=fill_model,
        )
        engine.add_instrument(instrument)
        if data:
            engine.add_data(data)
        strategy = _ReplayEntry(**inputs)
        engine.add_strategy(strategy)
        engine.run()
        orders = [order.to_dict() for order in engine.cache.orders()]
        for row in orders:
            row["order_type"] = row.pop("type")
        return ReplayResult(
            strategy.events,
            orders,
            params.params_hash,
            params.fixture,
            failed=bool(strategy.signals.failure),
            failure_reason=strategy.signals.failure,
        )
    finally:
        engine.dispose()
