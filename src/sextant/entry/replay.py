"""One entry episode through native BacktestEngine; no feed or broker client.

Framework shape: Nautilus rc7's backtest example, Strategy, OrderFactory, native
clock, FixedRiskSizer and cash account. N1/N2/N4/N5: pinned entry ADR and runtime
slice in docs/manifest.md. Extended-hours is recorded intent, not bridge proof.
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
    Bar,
    Equity,
    Money,
    OmsType,
    OrderSide,
    Price,
    QuoteTick,
    TimeInForce,
    TradeTick,
)
from nautilus_trader.trading import Strategy

from sextant.entry.orders import funding_unit_cost, limit_price, within_chase
from sextant.entry.parameters import EntryParameters, number
from sextant.entry.signals import EntryState, Surge, TradeCoverage
from sextant.entry.sizing import SegmentBasis, size_entry


@dataclass(frozen=True)
class ReplayResult:
    events: list[dict[str, Any]]
    orders: list[dict[str, str]]
    params_hash: str
    fixture_only: bool
    tier: str = "MODELED"


class _ReplayEntryConfig(StrategyConfig):
    def __init__(self, **inputs: Any):
        super().__init__()
        self.inputs = inputs


class _ReplayEntry(Strategy):
    def __init__(self, config: _ReplayEntryConfig):
        super().__init__(config)
        instrument, params = config.inputs["instrument"], config.inputs["params"]
        segment, surge = config.inputs["segment"], config.inputs["surge"]
        buffer, basis_path = config.inputs["buffer"], config.inputs["basis_path"]
        regular_hours, confidence = config.inputs["regular_hours"], config.inputs["confidence"]
        self.instrument, self.parameters = instrument, params
        self.signals = EntryState(instrument.id, params, segment)
        if surge is not None:
            self.signals.arm(surge)
        self.buffer, self.basis_path = number(buffer, "buffer"), basis_path
        self.regular_hours, self.confidence = regular_hours, confidence
        self.coverage: TradeCoverage | None = config.inputs["coverage"]
        self.commission_rate: Decimal | None = config.inputs["commission_rate"]
        self.quote: QuoteTick | None = None
        self.entry: Any = None
        self.first_limit: Decimal | None = None
        self.expiry_ns: int | None = None
        self.basis: Decimal | None = None
        self.events: list[dict[str, Any]] = []
        self.expired = False
        self.reclaim_decided_ns: int | None = None

    def on_start(self) -> None:
        account = self.portfolio.account(self.instrument.venue)
        if account is not None:
            free = account.balance_free(self.instrument.quote_currency)
            store = SegmentBasis(self.basis_path, str(account.id), self.parameters)
            buying_power = None if free is None else free.as_decimal()
            self.basis = store.freeze(self.signals.segment, buying_power, first_read="node_start")
        self.subscribe_trades(self.instrument.id)
        self.subscribe_quotes(self.instrument.id)
        self.subscribe_bars(self.signals.bar_type)

    def on_bar(self, bar: Bar) -> None:
        self.signals.on_bar(bar, now=self.clock.timestamp_ns())

    def on_trade(self, trade: TradeTick) -> None:
        now = self.clock.timestamp_ns()
        if self.signals.on_trade(trade, now=now):
            self.events.append(dict(action="TRADE", ts=now, extension=str(self.signals.extension)))
            event_ns = self.signals.reclaim_event_ns
            try:
                self._decide()
            finally:
                if event_ns is not None:
                    self.reclaim_decided_ns = event_ns

    def on_quote(self, quote: QuoteTick) -> None:
        if self.quote is not None and quote.ts_event < self.quote.ts_event:
            return
        self.quote = quote
        self._decide()

    def _valid_quote(self, now: int) -> bool:
        q = self.quote
        return bool(
            q is not None
            and 0 <= q.ts_event <= q.ts_init <= now
            and now - q.ts_event <= self.parameters.ns("max_data_age_s")
            and 0 < q.bid_price.as_decimal() <= q.ask_price.as_decimal()
        )

    def _sizing(self, price: Decimal, setup: str, now: int):
        account = self.portfolio.account(self.instrument.venue)
        total = free = None
        if account is not None:
            balance = account.balance_total(self.instrument.quote_currency)
            available = account.balance_free(self.instrument.quote_currency)
            total = None if balance is None else balance.as_decimal()
            free = None if available is None else available.as_decimal()
        if free is not None and self.entry is not None and self.entry.is_open:
            free += self.entry.leaves_qty.as_decimal() * self.entry.price.as_decimal()
            # Full-order caps include fills, but funding is needed only for the leaves.
            free += self.entry.filled_qty.as_decimal() * funding_unit_cost(
                price, self.commission_rate, self.instrument.quote_currency.precision
            )
        volume = sum(
            (
                t.price.as_decimal() * t.size.as_decimal()
                for t in self.signals.trades
                if now - self.parameters.ns("flow_share_window_s") < t.ts_event <= now
            ),
            start=Decimal(0),
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

    def _decide(self) -> None:
        now = self.clock.timestamp_ns()
        if self.expiry_ns is not None and now >= self.expiry_ns:
            self._expire(None)
        if self.expired or not self._valid_quote(now) or not self.signals.fresh(now):
            return
        assert self.quote is not None
        price = limit_price(
            self.quote.ask_price.as_decimal(), self.instrument.price_increment.as_decimal()
        )
        native_price = Price.from_decimal_dp(price, self.instrument.price_precision)
        if self.entry is not None:
            current = self.cache.order(self.entry.client_order_id)
            if current is None:
                return
            self.entry = current
            if self.setup == "FIRST_LEG" and not self.signals.first_leg_ready(price, now):
                return
            if self.setup == "RECLAIM" and not self.signals.reclaim_ready(
                price,
                self.buffer,
                now,
                covered_flow=self.signals.covered_flow(now, self.coverage),
            ):
                return
            if (
                not self.entry.is_open
                or self.entry.is_pending_cancel
                or self.entry.is_pending_update
                or self.first_limit is None
                or not within_chase(price, self.first_limit, self.parameters)
                or price <= self.entry.price.as_decimal()
            ):
                return
            sizing = self._sizing(price, self.setup, now)
            if sizing.quantity.as_decimal() < self.entry.quantity.as_decimal():
                return
            self.events.append(dict(action="MODIFY", ts=now, limit=str(price)))
            self.modify_order(self.entry.client_order_id, price=native_price)
            return
        setup = None
        if self.signals.first_leg_ready(price, now):
            setup = "FIRST_LEG"
        elif (
            self.signals.reclaim_event_ns != self.reclaim_decided_ns
            and self.signals.reclaim_ready(
                price, self.buffer, now, covered_flow=self.signals.covered_flow(now, self.coverage)
            )
        ):
            setup = "RECLAIM"
        if setup is None:
            return
        sizing = self._sizing(price, setup, now)
        if sizing.refusal:
            self.events.append(dict(action="REFUSE", ts=now, reason=sizing.refusal))
            return
        self.setup, self.first_limit = setup, price
        self.entry = self.order_factory.limit(
            self.instrument.id,
            OrderSide.BUY,
            sizing.quantity,
            native_price,
            time_in_force=TimeInForce.DAY,
            tags=[f"params_hash={self.parameters.params_hash}", f"setup={setup}"],
        )
        expiry_ns: int = now + self.parameters.ns("entry_ttl_s")
        self.expiry_ns = expiry_ns
        self.events.append(
            dict(
                action="SUBMIT",
                ts=now,
                setup=setup,
                limit=str(price),
                extension=str(self.signals.extension),
                confidence=(None if setup == "FIRST_LEG" else str(self.confidence)),
                extended_hours=not self.regular_hours,
                order_type="LIMIT",
                contingency_type=(
                    None
                    if self.entry.contingency_type is None
                    else self.entry.contingency_type.name
                ),
                params_hash=self.parameters.params_hash,
            )
        )
        self.clock.set_time_alert_ns("entry-ttl", expiry_ns, callback=self._expire)
        self.submit_order(self.entry, params={"extended_hours": not self.regular_hours})

    def _expire(self, _event) -> None:
        self.expired = True
        if self.entry is not None:
            self.entry = self.cache.order(self.entry.client_order_id) or self.entry
        if self.entry is not None and self.entry.is_open and not self.entry.is_pending_cancel:
            self.events.append(dict(action="CANCEL", ts=self.clock.timestamp_ns()))
            self.cancel_order(self.entry.client_order_id)

    def on_order_updated(self, event) -> None:
        if self.expired:
            self._expire(None)
        else:
            self._decide()

    def on_order_modify_rejected(self, event) -> None:
        if self.expired:
            self._expire(None)

    def on_order_accepted(self, event) -> None:
        if self.expired:
            self._expire(None)
        else:
            self._decide()


def run_replay(
    *,
    instrument: Equity,
    params: EntryParameters,
    data: list,
    basis_path: Path,
    segment: str,
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
    """Offline arm; commission_rate must bound the explicit model's per-fill fees.

    An unavailable fee bound refuses entry. It is never inferred from fixtures.
    """
    starting_cash = number(starting_cash, "starting_cash", zero=True)
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
            latency_model=latency_model,
            fee_model=fee_model,
            trade_execution=False,
            bar_execution=False,
            fill_model=fill_model,
        )
        engine.add_instrument(instrument)
        for kind in (Bar, QuoteTick, TradeTick):
            group = [item for item in data if isinstance(item, kind)]
            if group:
                engine.add_data(group)
        strategy = _ReplayEntry(
            _ReplayEntryConfig(
                instrument=instrument,
                params=params,
                segment=segment,
                surge=surge,
                buffer=buffer,
                basis_path=basis_path,
                regular_hours=regular_hours,
                confidence=confidence,
                coverage=coverage,
                commission_rate=commission_rate,
            )
        )
        engine.add_strategy(strategy)
        engine.run()
        orders = [
            dict(
                client_order_id=str(order.client_order_id),
                status=order.status.name,
                quantity=str(order.quantity),
                filled_qty=str(order.filled_qty),
                price=str(order.price),
                order_type=order.order_type.name,
            )
            for order in engine.cache.orders()
        ]
        return ReplayResult(strategy.events, orders, params.params_hash, params.fixture)
    finally:
        engine.dispose()
