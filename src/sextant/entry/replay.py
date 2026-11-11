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
from sextant.entry.sizing import SegmentBasis, Sizing, size_entry
from sextant.ranking import registry as ranking_registry
from sextant.ranking.consumer import RankingConsumer
from sextant.ranking.rank_gate import RankGateStatus, decide_rank_gate

ReplayResult = namedtuple(
    "ReplayResult",
    "events orders params_hash fixture_only tier failed failure_reason",
    defaults=("MODELED", False, None),
)
CANCEL_ATTEMPTS = 4  # ADR-0007:27: K + 1 with K = max_retries (3) for one order identity


def _guarded(method):
    def handle(self, *args):
        try:
            if not self.signals.failure or method.__name__ in {"_expire", "on_stop"}:
                method(self, *args)
            if self._due(now := self._stamp(args)):  # N4: each event not failing re-requests
                self._cancel(now)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self.signals.failure = self.signals.failure or reason
            self.events.append(dict(action="FAIL", ts=self._stamp(args), reason=reason))

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
        self.ranking_consumer: RankingConsumer | None = inputs["ranking_consumer"]
        self.rank_gate_enabled = ranking_registry.RANK_GATE_ENABLED.value
        self.quote: model.QuoteTick | None = None
        self.entry: Any = None
        self.first_limit: Decimal | None = None
        self.expiry_ns: int | None = None
        self.basis: Decimal | None = None
        self.events: list[dict[str, Any]] = []
        self.expired, self.tier = False, inputs["tier"]
        self.cancel_attempts, self.cancel_exhausted = 0, False
        self.cancelling = False  # a synchronous PendingCancel dispatch re-enters the guard
        self.cancel_sent_at: int | None = None  # one wire cancel per timestamp
        self.decided_ns: int | None = None

    @_guarded
    def on_start(self) -> None:
        account = self.portfolio.account(self.instrument.venue)
        if account is not None and not self.parameters.first_leg_only:  # N5's basis
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
        if self.signals.void_reason:
            self._record("VOID", reason=self.signals.void_reason, event_ts=trade.ts_event)
        if accepted:
            self._record("TRADE", extension=str(self.signals.extension))
            event_ns = self.signals.reclaim_event_ns
            self._decide()
            if event_ns is not None:
                self.decided_ns = event_ns

    @_guarded
    def on_quote(self, quote: model.QuoteTick) -> None:
        if not 0 <= quote.ts_event <= quote.ts_init <= self.clock.timestamp_ns() or (
            self.quote is not None and quote.ts_event < self.quote.ts_event
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
        if self.parameters.first_leg_only:  # one native size increment, as a fixed trade_size
            refusal = None if self.tier == "MODELED" else "witness sizing is measurement-only"
            witness = "measurement-only witness"
            hash_ = self.parameters.params_hash
            return Sizing(self.instrument.size_increment, None, None, None, witness, refusal, hash_)
        total, free = self._balance("total"), self._balance("free")
        if free is not None and self.entry is not None and self.entry.is_open:
            free += self.entry.leaves_qty.as_decimal() * self.entry.price.as_decimal()
            # Full-order caps include fills, but funding is needed only for the leaves.
            free += self.entry.filled_qty.as_decimal() * funding_unit_cost(
                price, self.commission_rate, self.instrument.quote_currency.precision
            )
        volume = self.signals.flow_dollars(now)
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
        if not 0 < quote.bid_price.as_decimal() <= quote.ask_price.as_decimal():
            return  # crossed or one-sided: UNKNOWN, never the older quote (first_leg.py:550)
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
        # rc8 Strategy callbacks make the decision before OrderFactory/submit_order
        # (docs/concepts/strategies.md:130-136,540-569). OFF never reads the consumer.
        if self.rank_gate_enabled is not False:
            rank, reason = None, None
            if self.rank_gate_enabled is True and self.ranking_consumer is not None:
                rank = self.ranking_consumer.entry_rank(str(self.instrument.id.symbol), now=now)
                reason = self.ranking_consumer.reason
            decision = decide_rank_gate(
                enabled=self.rank_gate_enabled, rank=rank, consumer_reason=reason
            )
            if decision.status is RankGateStatus.REFUSE:
                self._record("REFUSE", stage="RANK", reason=decision.reason)
                return
        expiry_ns: int | None = None
        if not modifying:
            ttl = self.parameters.ns("entry_ttl_s")
            window = self.parameters.ns("first_leg_window_s")
            if setup == "FIRST_LEG":
                surge = self.signals.surge
                assert surge is not None  # first_leg_ready admitted this setup
                end = surge.flag_ts + window
            else:
                end = now + ttl
            expiry_ns = int(min(now + ttl, end))  # Northstar _expire_first_leg's min
            if expiry_ns <= now:  # a submit here would cancel inside its own borrow
                self._record("REFUSE", reason="first_leg_window_s", limit=str(price))
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
        assert expiry_ns is not None  # only a new order reaches this line
        self.setup, self.first_limit = setup, price
        self.entry = self.order_factory.limit(
            self.instrument.id,
            model.OrderSide.BUY,
            sizing.quantity,
            native_price,
            time_in_force=model.TimeInForce.DAY,
            tags=[f"params_hash={self.parameters.params_hash}", f"setup={setup}"],
        )
        self.expiry_ns = expiry_ns
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
        self.expired = True  # the guard sends the cancel; later events re-request it

    def _due(self, now: int) -> bool:  # from the clock, so a faulted TTL callback is not lost
        return self.expiry_ns is not None and now >= self.expiry_ns

    def _stamp(self, args) -> int:  # the event's own ts: nested order dispatch holds the clock
        return getattr(next(iter(args), None), "ts_init", None) or self.clock.timestamp_ns()

    def _cancel(self, now: int) -> None:
        # rc8 marks a pending cancel in the cache before sending (mod.rs:818-828) and its
        # guard (mod.rs:629-631) never sends twice. ADDENDUM-68R11-2: a failed TTL cancel is
        # retried at once, at most K + 1 = 4 attempts for one order identity (ADR-0007:27).
        if (
            self.cancelling
            or self.cancel_exhausted
            or (self.cancel_sent_at is not None and now <= self.cancel_sent_at)
        ):
            return
        self.cancelling = True
        try:
            while self.cancel_attempts < CANCEL_ATTEMPTS:
                try:
                    order = self.cache.order(self.entry.client_order_id)
                except Exception as exc:
                    self.cancel_attempts += 1
                    self._alert(now, f"TTL cancel failed: {type(exc).__name__}: {exc}")
                    continue
                if order is not None and (not order.is_open or order.is_pending_cancel):
                    return  # closed, in flight or already cancelling
                if order is None:
                    return self._page(now, "TTL cancel: entry missing from the cache")
                self.cancel_attempts += 1
                try:
                    self.cancel_order(order.client_order_id)
                except Exception as exc:
                    self._alert(now, f"TTL cancel failed: {type(exc).__name__}: {exc}")
                else:
                    self._record("CANCEL")
                    self.cancel_sent_at = now
                    return
        finally:
            self.cancelling = False
        if self.cancel_sent_at is not None:
            return  # a cancel went out; the pending guard owns any later event
        self.cancel_exhausted = True
        self._page(now, f"TTL cancel failed {CANCEL_ATTEMPTS} times: owner attention")

    def _alert(self, now: int, reason: str) -> None:  # each failed attempt is visible
        self.events.append(dict(action="PAGE", ts=now, reason=reason))

    def _page(self, now: int, reason: str) -> None:  # a cancellation failure pages and latches
        self.signals.failure = self.signals.failure or reason
        self.events.append(dict(action="PAGE", ts=now, reason=reason))

    @_guarded
    def on_stop(self) -> None:  # the window end: an expired entry still open is the owner's
        order = None if self.entry is None else self.cache.order(self.entry.client_order_id)
        if self._due(now := self.clock.timestamp_ns()) and order is not None and order.is_open:
            self._page(now, "entry still open at the window end")

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
    tier: str = "MODELED",
    ranking_consumer: RankingConsumer | None = None,
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
            tier,
            failed=bool(strategy.signals.failure),
            failure_reason=strategy.signals.failure,
        )
    finally:
        engine.dispose()
