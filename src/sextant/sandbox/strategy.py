"""The same native strategy composition for S construction and MODELED replay.

Owns no replacement scorer, sizer, exit policy, guard or reservation book.
Entry decisions adapt row 6's native witness; exit policy is inherited, with
explicitly routed sends through the one account service. Missing detector,
reference/curve/heartbeat/receipt authority stays unavailable.
"""

import importlib
import json
from decimal import Decimal
from functools import wraps
from typing import Any, cast
from uuid import uuid4

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import (
    Bar,
    ClientId,
    ClientOrderId,
    OrderSide,
    Price,
    Quantity,
    QuoteTick,
    StrategyId,
    TimeInForce,
    TradeTick,
)

from sextant.execution.pacer import ActionKind
from sextant.exits import policy
from sextant.exits.engine import ExitEngine, ExitEngineConfig
from sextant.reentry.contracts import CampaignState, FastSellFacts, FlatReceipt
from sextant.reentry.policy import Reentry
from sextant.sandbox.profile import entry_parameters, exit_parameters, reentry_parameters, values
from sextant.sandbox.tapes import ScannerFacts, scanner_type

NS = 1_000_000_000


def capture(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as error:
            self.shared.errors.append(
                f"{self.strategy_id}:{method.__name__}:{type(error).__name__}:{error}"
            )
            self.shared.guard.kill("callback_error", now=self.clock.timestamp_ns())

    return call


class StackConfig(ExitEngineConfig):
    def __new__(cls, *, instrument, shared, start_ns):
        name = f"{shared.binding.client_id}.{instrument.id.symbol}-001"
        return cast(Any, StrategyConfig.__new__)(
            cls,
            strategy_id=StrategyId(name),
            # rc7 StrategyConfig requires a distinct tag per trader strategy.
            order_id_tag=f"{shared.binding.order_namespace}.{instrument.id.symbol}",
            use_uuid_client_order_ids=True,
            manage_stop=False,
            manage_gtd_expiry=False,
            manage_contingent_orders=False,
        )

    def __init__(self, *, instrument, shared, start_ns):
        super().__init__(
            instrument_id=instrument.id,
            params=exit_parameters(shared.profile),
            round_trip_cost=instrument.price_increment.as_decimal(),
            session="rth",
        )
        self.instrument, self.shared, self.start_ns = instrument, shared, start_ns


class ReaderView:
    def __init__(self, market, now: int):
        self.market, self.now = market, now

    @property
    def generation_key(self):
        return self.market.reader.generation_key if self.market.reader else ""

    @property
    def known_at(self):
        reader = self.market.reader
        return reader.generation.known_at if reader and reader.generation else 0

    @property
    def fresh(self):
        return bool(self.market.reader and self.market.reader.fresh(self.now))

    def rank_of(self, symbol):
        return self.market.rank(symbol, self.now)


class FullStackStrategy(ExitEngine):
    p: policy.ExitParams

    def __init__(self, config: StackConfig):
        super().__init__(config)
        self.instrument, self.shared, self.start_ns = (
            config.instrument,
            config.shared,
            config.start_ns,
        )
        self.sandbox_binding = self.shared.binding
        self.route = ClientId(self.shared.execution_client)
        self.data_route = ClientId(self.shared.data_client)
        self.parameters = entry_parameters(self.shared.profile)
        entry = importlib.import_module("sextant.entry.signals")
        self.signals = entry.EntryState(self.instrument.id, self.parameters, "UNAVAILABLE")
        self.sizing = importlib.import_module("sextant.entry.sizing")
        self.segment_basis = self.sizing.SegmentBasis(
            self.shared.root / f"basis-{self.instrument.id.symbol}.json",
            self.shared.scope.key,
            self.parameters,
        )
        self.reentry = Reentry(
            reentry_parameters(self.shared.profile), entry=None, sizer=None, lane="replay"
        )
        self.quote: QuoteTick | None = None
        self.segment_key = None
        self.entry_id: ClientOrderId | None = None
        self.entry_deadline = 0
        self.ordered = self.surge_seeded = False
        self.last_sizing: Any = None
        self.campaign: CampaignState | None = None
        self.last_sell: Any = None
        self.reentry_flat: FlatReceipt | None = None
        self.shared.strategies[str(self.instrument.id)] = self

    @capture
    def on_start(self):
        self.shared.open(self)
        self.one_tick = self.instrument.price_increment.as_decimal()
        self.subscribe_quotes(self.instrument.id, client_id=self.data_route)
        self.subscribe_trades(self.instrument.id, client_id=self.data_route)
        self.subscribe_bars(self.signals.bar_type, client_id=self.data_route)
        self.subscribe_data(scanner_type(), client_id=self.data_route)
        self.shared.counts["strategy_starts"] += 1

    def _market(self, now: int):
        market = self.shared.market
        segment = market.at(now)
        if segment is not None and self.segment_key != market.key:
            self.segment_key = market.key
            self.signals.reset_segment(":".join(market.key))
            self.rth = segment.name == "RTH"
            self.breach = policy.BreachRun()
        return segment

    def _cycle(self, now: int):
        self.shared.market.publish(now)
        self.shared.cycle(now)
        self._expire_entry(now)
        self._after_sell(now)

    @capture
    def on_quote(self, quote: QuoteTick):
        if quote.instrument_id != self.instrument.id:
            return
        self.quote = quote
        now = self.clock.timestamp_ns()
        self._market(now)
        self.shared.counts["exit_quote_callbacks"] += 1
        ExitEngine.on_quote(self, quote)
        self.shared.seed_owner(self)
        self._cycle(now)
        self._try_entry(now)

    @capture
    def on_trade(self, trade: TradeTick):
        tick = trade
        if tick.instrument_id != self.instrument.id:
            return
        now = self.clock.timestamp_ns()
        segment = self._market(now)
        if segment is not None and self.shared.market.publisher is not None:
            self.shared.market.publisher.on_trade(tick, quote=self.quote, known_at=now)
            self.shared.counts["ranking_trade_callbacks"] += 1
        tape = values(self.shared.profile, "tape")
        surge_at = self.start_ns + tape["surge_s"] * NS
        if self.shared.case != "recorded" and not self.surge_seeded and now >= surge_at:
            entry = importlib.import_module("sextant.entry.signals")
            self.signals.arm(
                entry.Surge(
                    self.instrument.id,
                    self.signals.segment,
                    surge_at,
                    surge_at,
                    surge_at + self.parameters.ns("first_leg_window_s"),
                    Decimal("10.00"),
                    "FIXTURE predeclared surge, not a detector",
                )
            )
            self.surge_seeded = True
        self.signals.on_trade(tick, now=now)
        self.shared.counts["entry_trade_callbacks"] += 1
        ExitEngine.on_trade(self, tick)
        self.shared.counts["exit_trade_callbacks"] += 1
        self._cycle(now)
        self._try_entry(now)

    @capture
    def on_bar(self, bar: Bar):
        if bar.bar_type.instrument_id != self.instrument.id:
            return
        now = self.clock.timestamp_ns()
        self._market(max(0, bar.ts_event - 1))  # completed minute belongs to its opening session
        self.signals.on_bar(bar, now=now)
        self.shared.counts["entry_bar_callbacks"] += 1
        ExitEngine.on_bar(self, bar)
        self.shared.counts["exit_bar_callbacks"] += 1
        self._cycle(now)

    @capture
    def on_data(self, data):
        fact = getattr(data, "data", data)
        if not isinstance(fact, ScannerFacts):
            return
        payload = json.loads(fact.payload)
        for quote in payload["quotes"]:
            if quote["instrument"] == str(self.instrument.id):
                self.shared.counts["recorded_bbo_facts"] += 1
                if quote["bid_size"] is None or quote["ask_size"] is None:
                    self.shared.counts["bbo_size_unavailable"] += 1
        # Do not manufacture QuoteTick liquidity or a current ranking from these facts.
        self._market(self.clock.timestamp_ns())
        self._cycle(self.clock.timestamp_ns())

    def entry_admitted(self):
        now, quote = self.clock.timestamp_ns(), self.quote
        if (
            quote is None
            or not self.shared.guard.entry_allowed()
            or not 0 <= quote.ts_event <= quote.ts_init <= now
            or now - quote.ts_event > self.parameters.ns("max_data_age_s")
            or (self.entry_deadline and now >= self.entry_deadline)
        ):
            return False
        ask = quote.ask_price.as_decimal()
        return bool(
            self.shared.market.rank(self.instrument.id.symbol.value, now) is not None
            and self.signals.first_leg_ready(ask, now)
            and self.signals.not_extended_at_ask(ask)
        )

    def _try_entry(self, now: int):
        if self.ordered or not self.entry_admitted():
            return
        assert self.quote is not None
        assert self.segment_key is not None
        account = self.portfolio.account(self.instrument.venue)
        total = None if account is None else account.balance_total(self.instrument.quote_currency)
        free = None if account is None else account.balance_free(self.instrument.quote_currency)
        equity, buying_power = (
            None if value is None else value.as_decimal() for value in (total, free)
        )
        basis = self.segment_basis.freeze(
            ":".join(self.segment_key), buying_power, first_read="node_start"
        )
        ask = self.quote.ask_price.as_decimal()
        buffer = policy.buffer(
            self.one_tick,
            self.quote.ask_price.as_decimal() - self.quote.bid_price.as_decimal(),
            ask,
            self._range(now),
            self.p,
        )
        if buffer is None:
            return
        volume = sum(
            (
                tick.price.as_decimal() * tick.size.as_decimal()
                for tick in self.signals.trades
                if now - self.parameters.ns("flow_share_window_s") < tick.ts_event <= now
            ),
            Decimal(0),
        )
        self.last_sizing = self.sizing.size_entry(
            instrument=self.instrument,
            params=self.parameters,
            setup="FIRST_LEG",
            entry=ask,
            initial_trigger=ask - buffer,
            equity=equity,
            basis=basis,
            buying_power=buying_power,
            dollar_volume=volume,
            confidence=None,
            prearm_stopouts=0,
        )
        self.shared.counts["native_sizing_calls"] += 1
        if self.last_sizing.refusal is not None:
            return
        order = self.order_factory.limit(
            self.instrument.id,
            OrderSide.BUY,
            self.last_sizing.quantity,
            self.quote.ask_price,
            time_in_force=TimeInForce.DAY,
            client_order_id=self._cid(),
        )
        self.entry_id, self.ordered = order.client_order_id, True
        self.entry_deadline = now + self.parameters.ns("entry_ttl_s")
        self.submit_order(order, client_id=self.route)

    def _cid(self):
        return ClientOrderId(
            f"{self.shared.binding.order_namespace}.{self.instrument.id.symbol}.{uuid4().hex}"
        )

    def _expire_entry(self, now: int):
        if self.entry_id is None or now < self.entry_deadline:
            return
        order = self.cache.order(self.entry_id)
        if order is not None and order.is_open:
            self.cancel_order(self.entry_id, client_id=self.route)

    def submit_order(self, order, position_id=None, client_id=None, params=None):
        self.shared.submit(self, order, position_id=position_id, client_id=client_id, params=params)

    def modify_order(
        self,
        client_order_id,
        quantity=None,
        price=None,
        trigger_price=None,
        client_id=None,
        params=None,
    ):
        if quantity is not None or trigger_price is not None:
            raise ValueError("S stack amendments are price-only")
        self.shared.action(
            self, client_order_id, kind=ActionKind.MODIFY, client_id=client_id, price=price
        )

    def cancel_order(self, client_order_id, client_id=None, params=None):
        self.shared.action(self, client_order_id, kind=ActionKind.CANCEL, client_id=client_id)

    def reduce(self, quantity: Decimal, price: Price, *, reason: str):
        self.shared.refresh(self.clock.timestamp_ns())
        remaining = min(quantity, self.shared.custody.available_exit(str(self.instrument.id)))
        if remaining <= 0:
            return
        order = self.order_factory.limit(
            self.instrument.id,
            OrderSide.SELL,
            Quantity.from_str(str(remaining)),
            price,
            time_in_force=TimeInForce.GTC,
            client_order_id=self._cid(),
            reduce_only=True,
        )
        self.sell_id, self.amended_ns = order.client_order_id, self.clock.timestamp_ns()
        self.submit_order(order, client_id=self.route)
        self._record(self.amended_ns, reason, limit=price.as_decimal())

    def _sell(self, ts, p):
        assert self.bid is not None and p.trigger is not None
        self.reduce(
            p.qty,
            self._price(
                policy.chase_limit(
                    self.bid, self.last if self.p.chase_min_interval_s is not None else None, self.p
                )
            ),
            reason="breach_sell",
        )

    def _chase(self, ts):
        if self.sell_id is None or self.bid is None or self.p.chase_min_interval_s is None:
            return
        order = self.cache.order(self.sell_id)
        if order is None or not order.is_open or order.is_pending_update:
            return
        if ts - self.amended_ns < int(self.p.chase_min_interval_s * NS):
            return
        price = self._price(policy.chase_limit(self.bid, self.last, self.p))
        if price != order.price:
            self.amended_ns = ts
            self.modify_order(self.sell_id, price=price, client_id=self.route)

    @capture
    def on_order_filled(self, event):
        self.shared.pacer.record_fill()
        self.shared.fills.append(
            dict(
                instrument=str(event.instrument_id),
                side=event.order_side.name,
                quantity=str(event.last_qty),
                price=str(event.last_px),
                event_ns=event.ts_event,
                cid=str(event.client_order_id),
            )
        )
        ExitEngine.on_order_filled(self, event)
        self.shared.counts["native_fill_callbacks"] += 1
        if (
            event.order_side == OrderSide.BUY
            and self.campaign is None
            and self.last_sizing is not None
        ):
            quantity, price = event.last_qty.as_decimal(), event.last_px.as_decimal()
            risk = self.last_sizing.planned_risk
            self.campaign = CampaignState(
                f"{self.shared.binding.arm_id}:{self.instrument.id}",
                self.instrument.id,
                self.instrument.id,
                "paper_unbounded",
                quantity,
                quantity * price,
                risk,
                quantity,
                quantity * price,
                risk,
                Decimal(0),
                Decimal(0),
                True,
                0,
                0,
            )
        elif event.order_side == OrderSide.SELL:
            self.last_sell = event
            self.reentry_flat = None

    def _flat_for_reentry(self, receipt) -> FlatReceipt | None:
        # Reentry.after_sell anchors cooldown to the first confirmed terminal
        # receipt. New account observations of the same lineage do not renew it.
        if receipt is None:
            self.reentry_flat = None
        elif (
            self.reentry_flat is None
            or self.reentry_flat.terminal_order_ids != receipt.terminal_client_ids
        ):
            self.reentry_flat = FlatReceipt(
                self.instrument.id, Decimal(0), receipt.terminal_client_ids, receipt.known_at
            )
        return self.reentry_flat

    def _after_sell(self, now: int):
        if self.last_sell is None or self.campaign is None:
            return
        receipt = self.shared.custody.flat_receipt()
        flat = self._flat_for_reentry(receipt)
        price = self.last_sell.last_px.as_decimal()
        trigger = self.protection.trigger if self.protection and self.protection.trigger else price
        decision = self.reentry.after_sell(
            now_ns=now,
            ranking=ReaderView(self.shared.market, now),
            sell=FastSellFacts(self.instrument.id, trigger, price, self.last_sell.ts_event, flat),
            required_lineage=None if receipt is None else receipt.terminal_client_ids,
            candidates=tuple(instrument.id for instrument in self.shared.instruments.values()),
            held=tuple(
                instrument.id
                for instrument in self.shared.instruments.values()
                if self.portfolio.net_position(instrument.id) != 0
            ),
            campaign=self.campaign,
            stopouts=0,
        )
        self.shared.counts["reentry_admission_checks"] += 1
        self.shared.counts[f"reentry:{decision.kind}:{decision.reason}"] += 1

    def _unscoped(self, *args, **kwargs):
        raise ValueError("broad or unqualified S command refused; use the routed account gate")

    submit_order_list = modify_orders = cancel_orders = cancel_all_orders = _unscoped
    close_position = close_all_positions = market_exit = query_account = query_order = _unscoped

    def on_stop(self):
        self.shared.counts["strategy_stops"] += 1
