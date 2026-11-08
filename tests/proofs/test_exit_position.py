"""R86 (#129 §4 item 1): the exit engine protects the native position, not its first fill.

Offline BacktestEngine witnesses on scripted quotes (sextant.backtest.exit_position_witness). The
fixture's 100.02 entry has an initial trigger of 99.81996 (buffer 0.002 x entry), so bids of 99.50
breach it, and three of them over 2 s persist (ADR-0005 X4).
"""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal as D

import pytest
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggerConfig, RiskEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel, StaticLatencyModel
from nautilus_trader.model import (
    AccountType,
    AggressorSide,
    ClientOrderId,
    Money,
    OmsType,
    OrderFilled,
    OrderPendingCancel,
    OrderSide,
    Price,
    Quantity,
    QuoteTick,
    TimeInForce,
    TradeId,
    TradeTick,
    TriggerType,
    Venue,
)
from nautilus_trader.trading import Strategy

from sextant.backtest.exit_position_witness import (
    EQUITY,
    NS,
    START,
    USD,
    Buy,
    Quote,
    Result,
    run,
)
from sextant.backtest.exit_witness import FIXTURE
from sextant.exits import engine as engine_module
from sextant.exits.engine import ExitEngine, ExitEngineConfig
from sextant.exits.policy import ExitParams

FLAT = Quote("100.00", "100.02")
LOW = Quote("99.50", "99.52")
THIN = Quote("100.00", "100.02", ask_size="6")


def _kinds(r: Result) -> list[str]:
    return [e["event"] for e in r.events]


def _breach_sells(r: Result) -> list[dict[str, str]]:
    return [e for e in r.events if e["event"].startswith("breach_sell")]


def test_one_fill_protects_the_position_and_sells_it_flat() -> None:
    r = run([FLAT] * 5 + [LOW] * 6, [Buy(0, "10")])
    assert [(q, p) for _c, q, p in r.buy_fills] == [("10", "100.02")]
    assert _kinds(r)[:2] == ["protected_from_fill", "initial_trigger"]
    assert D(r.events[0]["qty"]) == 10
    (sell,) = _breach_sells(r)
    assert D(sell["qty"]) == 10
    assert [(D(q), D(f)) for _c, q, f in r.sells] == [(D(10), D(10))]
    assert r.position == 0 and _kinds(r)[-1] == "flat"
    assert not r.paused and r.pages == []


def test_an_entry_filled_6_then_4_is_protected_as_10_and_the_breach_sell_covers_10() -> None:
    r = run([THIN, THIN] + [FLAT] * 3 + [LOW] * 6, [Buy(0, "10")])
    assert [(q, p) for _c, q, p in r.buy_fills] == [("6", "100.02"), ("4", "100.02")]
    assert len({c for c, _q, _p in r.buy_fills}) == 1  # one entry order, two fills
    assert "add_paused" not in _kinds(r) and r.pages == []
    grown = [
        D(e["qty"]) for e in r.events if e["event"] in ("protected_from_fill", "protected_qty")
    ]
    assert grown == [D(6), D(10)]
    (sell,) = _breach_sells(r)
    assert D(sell["qty"]) == 10
    assert [(D(q), D(f)) for _c, q, f in r.sells] == [(D(10), D(10))]
    assert r.position == 0


def test_a_buy_from_a_different_order_pauses_the_symbol_and_pages() -> None:
    """ADR-0007:17: an owner add to a strategy-held symbol pauses it and pages. The add is an order
    the house never sent (ADR-0007:16); a second house order's fill is not one (below)."""
    t = tape_run([FLAT] * 5 + [LOW] * 6, [Order(0, "10"), Order(2, "5", owner=True)])
    assert t.paused and t.pages == ["owner_add"]
    assert [e["event"] for e in t.events].count("add_paused") == 1
    assert _sold(t) == 0 and t.net == 15  # paused: the later breach sells nothing


def test_a_close_then_a_re_entry_is_protected_again() -> None:
    again, lower = Quote("99.60", "99.62"), Quote("99.30", "99.32")
    r = run([FLAT] * 5 + [LOW] * 3 + [again] * 3 + [lower] * 6, [Buy(0, "10"), Buy(9, "10")])
    entries = [D(e["entry"]) for e in r.events if e["event"] == "protected_from_fill"]
    assert entries == [D("100.02"), D("99.62")]
    assert len(_breach_sells(r)) == 2 and _kinds(r).count("flat") == 2
    # Each exit waits for its own persisted breach: the close clears the first one's crossing.
    assert [e["ts"] for e in _breach_sells(r)] == [str(START + 7 * NS), str(START + 13 * NS)]
    assert [(D(q), D(f)) for _c, q, f in r.sells] == [(D(10), D(10))] * 2
    assert r.position == 0 and not r.paused and r.pages == []


def test_the_decimal_basis_is_the_positions_avg_px_open() -> None:
    """rc8's `Position.avg_px_open` is a Decimal (positions.md:419): within one cycle it equals the
    opening order's `Order.avg_px`; across a close it does not (#169, below)."""
    r = run([THIN] + [FLAT] * 4 + [LOW] * 6, [Buy(0, "10", market=True)])
    assert [(q, p) for _c, q, p in r.buy_fills] == [("6", "100.02"), ("4", "100.03")]
    (avg,) = r.buy_avg_px.values()
    assert type(avg) is D and avg == D("100.024")
    bases = [e["entry"] for e in r.events if e["event"] in ("protected_from_fill", "protected_qty")]
    assert [D(b) for b in bases] == [D("100.02"), avg]
    (sell,) = _breach_sells(r)
    assert D(sell["qty"]) == 10 and r.position == 0


def test_a_same_order_remainder_is_canceled_before_it_buys_into_the_breach() -> None:
    """ADR-0005:36 (#169): the breach cancels the entry's remainder and proves it terminal before
    the one exit, so the remainder never buys into the breach and the venue never resizes the exit
    over it. The chase is off (#98), so the resting sell pages. Each later bid moves up through the
    resting limit, because an L1 maker fill needs a market move (fill-prices-and-matching.md, "L1
    books"); each move fills the bid's displayed 2."""
    wide = Quote("99.50", "100.05", bid_size="2")  # breaches; the ask is above the entry limit
    through = Quote("99.60", "100.01", bid_size="2")  # would have filled the remaining 4
    rising = [Quote(f"99.6{d}", "100.05", bid_size="2") for d in (2, 4, 6, 8)]
    no_chase = dataclasses.replace(FIXTURE, chase_cap_fraction=None, chase_min_interval_s=None)
    r = run([THIN] + [wide] * 3 + [through] + rising, [Buy(0, "10")], no_chase)
    assert [(q, p) for _c, q, p in r.buy_fills] == [("6", "100.02")]
    (sell,) = _breach_sells(r)
    assert D(sell["qty"]) == 6 and "entry_fill" not in _kinds(r)
    assert [(D(q), D(f)) for _c, q, f in r.sells] == [(D(6), D(6))]
    assert r.max_working_sells == 1 and r.position == 0 and _kinds(r)[-1] == "flat"
    assert not r.paused and r.pages == ["chase_unavailable"]


def test_every_position_event_follows_its_order_fill() -> None:
    """The order the engine relies on: rc7 docs/concepts/events/index.md:123-160."""
    r = run([THIN, THIN] + [FLAT] * 3 + [LOW] * 6, [Buy(0, "10")])
    assert r.calls == [
        "filled_buy",
        "position_opened",
        "filled_buy",
        "position_changed",
        "filled_sell",
        "position_closed",
    ]


# Tapes with buyer-initiated prints and owner orders (#169-#171, #209-#212, A2), one item a second
# from START. An
# owner order goes through `Strategy.submit_order` itself, never the engine's own path, so the
# house never registers it (ADR-0007:16). Its fills still land in the one NETTING position, as in
# #166's owner model: the account's merged net quantity.
@dataclass(frozen=True)
class Trade:
    price: str


@dataclass(frozen=True)
class Order:
    """A LIMIT sent just before the engine reads quote item `at`: at `price`, else that quote's
    ask (a BUY) or bid (a SELL)."""

    at: int
    qty: str
    side: OrderSide = OrderSide.BUY
    price: str | None = None
    owner: bool = False
    emulated: bool = False  # held locally by rc8's OrderEmulator until its BID_ASK trigger
    cancel_at: int | None = None  # canceled just before the engine reads quote item `cancel_at`
    expire_s: int | None = None  # a GTD order the venue expires at START + expire_s seconds
    external: bool = False  # an owner order placed outside this engine: its events never reach it


@dataclass(frozen=True)
class Tape:
    events: list[dict[str, str]]
    pages: list[str]
    paused: bool
    fills: list[tuple[int, str, str, str, bool]]  # (second, side, qty, price, owner)
    status: dict[str, str]  # each order's final status, keyed "house-1", "owner-1", ...
    net: D
    timeline: list[tuple[int, str, str]]  # (second, order, native event), each order's in order
    sent: dict[
        str, list[int]
    ]  # each order's cancel requests, ns after START (rc8 stamps the clock)


class Paged:
    """Stands in for the strategy's logger, to count the page lines."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def __getattr__(self, _name: str) -> object:
        return lambda *_a, **_k: None


class Scripted(ExitEngine):
    script: tuple[Order, ...] = ()
    paged = Paged()

    @property
    def log(self) -> Paged:  # type: ignore[override]
        return self.paged

    def on_start(self) -> None:
        super().on_start()
        self.seen = 0
        self.owner_ids: set[str] = set()
        self.names: dict[str, str] = {}
        self.sent: dict[int, ClientOrderId] = {}
        self.external: set[ClientOrderId] = set()

    def on_quote(self, quote: QuoteTick) -> None:
        for i in (i for i, o in enumerate(self.script) if o.cancel_at == self.seen):
            Strategy.cancel_order(self, self.sent[i])
        for i, o in ((i, o) for i, o in enumerate(self.script) if o.at == self.seen):
            ref = quote.ask_price if o.side == OrderSide.BUY else quote.bid_price
            price = ref if o.price is None else Price.from_str(o.price)
            qty = Quantity.from_str(o.qty)
            trigger = TriggerType.BID_ASK if o.emulated else None
            gtd = o.expire_s is not None
            order = self.order_factory.limit(
                EQUITY.id,
                o.side,
                qty,
                price,
                time_in_force=TimeInForce.GTD if gtd else TimeInForce.GTC,
                expire_time=START + (o.expire_s or 0) * NS if gtd else None,
                emulation_trigger=trigger,
            )
            self.sent[i] = order.client_order_id
            if o.external:
                self.external.add(order.client_order_id)
            cid, who = str(order.client_order_id), "owner" if o.owner else "house"
            self.names[cid] = f"{who}-{sum(n.startswith(who) for n in self.names.values()) + 1}"
            if o.owner:
                self.owner_ids.add(cid)
                Strategy.submit_order(self, order)
            else:
                self.submit_order(order)
        self.seen += 1
        super().on_quote(quote)

    def on_trade(self, trade: TradeTick) -> None:
        for i, o in ((i, o) for i, o in enumerate(self.script) if o.at == self.seen):
            assert o.price is not None and not o.owner  # a print gives no quote to price from
            order = self.order_factory.limit(EQUITY.id, o.side, Quantity.from_str(o.qty),
                                             Price.from_str(o.price))  # fmt: skip
            self.sent[i] = order.client_order_id
            self.names[str(order.client_order_id)] = f"house-{len(self.names) + 1}"
            self.submit_order(order)
        self.seen += 1
        super().on_trade(trade)

    def on_order_canceled(self, event) -> None:  # type: ignore[override]
        if event.client_order_id not in self.external:
            super().on_order_canceled(event)


def _tick(start: int, i: int, item: Quote | Trade) -> QuoteTick | TradeTick:
    ts = start + i * NS
    if isinstance(item, Trade):
        price, size = Price.from_str(item.price), Quantity.from_str("1")
        return TradeTick(EQUITY.id, price, size, AggressorSide.BUY, TradeId(str(i)), ts, ts)
    bid, ask = Price.from_str(item.bid), Price.from_str(item.ask)
    sizes = Quantity.from_str(item.bid_size), Quantity.from_str(item.ask_size)
    return QuoteTick(EQUITY.id, bid, ask, *sizes, ts, ts)


def _late(tick: QuoteTick | TradeTick, delay_ns: int) -> QuoteTick | TradeTick:
    """A quote received `delay_ns` after its event (#214 round 7); prints keep their own stamps.
    Applied after `_tick`, so a witness that stands in for `_tick` keeps its signature."""
    if not delay_ns or not isinstance(tick, QuoteTick):
        return tick
    ts_event, sizes = tick.ts_event - delay_ns, (tick.bid_size, tick.ask_size)
    return QuoteTick(
        tick.instrument_id, tick.bid_price, tick.ask_price, *sizes, ts_event, tick.ts_init
    )


def tape_run(
    items: Sequence[Quote | Trade],
    script: Sequence[Order],
    params: ExitParams = FIXTURE,
    *,
    session: str = "rth",
    risk: RiskEngineConfig | None = None,
    latency: StaticLatencyModel | None = None,
    start: int = START,
    quote_delay_ns: int = 0,
    bars: Sequence[object] = (),
    bar_type: str | None = None,
) -> Tape:
    """`bars` are external bars, added as given, for an engine armed on `bar_type`."""
    engine = BacktestEngine(
        BacktestEngineConfig(
            logging=LoggerConfig(bypass_logging=True),
            risk_engine=risk or RiskEngineConfig(bypass=False),
        )
    )
    try:
        engine.add_venue(
            venue=Venue("SIM"),
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            starting_balances=[Money(1_000_000, USD)],
            base_currency=USD,
            fee_model=MakerTakerFeeModel(maker_rate=D(0), taker_rate=D(0)),
            use_reduce_only=True,
            liquidity_consumption=True,
            latency_model=latency,
        )
        engine.add_instrument(EQUITY)
        ticks = [_late(_tick(start, i, item), quote_delay_ns) for i, item in enumerate(items)]
        engine.add_data(sorted([*ticks, *bars], key=lambda d: d.ts_init))  # type: ignore[attr-defined]
        strategy = Scripted(
            ExitEngineConfig(
                instrument_id=EQUITY.id,
                params=params,
                round_trip_cost=D("0.01"),
                session=session,
                arm_bar_type=bar_type,
            )
        )
        strategy.script = tuple(script)
        engine.add_strategy(strategy)
        engine.run()
        orders = engine.cache.orders(instrument_id=EQUITY.id)
        fills = sorted(
            (
                (e.ts_event - start) // NS,
                e.order_side.name,
                str(e.last_qty),
                str(e.last_px),
                str(e.client_order_id) in strategy.owner_ids,
            )
            for o in orders
            for e in o.events()
            if isinstance(e, OrderFilled)
        )
        net = sum((D(q) if s == "BUY" else -D(q) for _t, s, q, _p, _o in fills), D(0))
        name, seen = {}, []  # the engine's own orders: engine-SELL, then engine-SELL-2, ...
        for o in orders:
            seen.append(o.side.name)
            n = seen.count(o.side.name)
            label = f"engine-{o.side.name}" + (f"-{n}" if n > 1 else "")
            name[o.client_order_id] = strategy.names.get(str(o.client_order_id), label)
        status = {name[o.client_order_id]: o.status.name for o in orders}
        timeline = sorted(
            (
                ((e.ts_event - start) // NS, name[o.client_order_id], type(e).__name__)
                for o in orders
                for e in o.events()
            ),
            key=lambda x: x[0],
        )
        return Tape(
            list(strategy.events),
            list(strategy.pages),
            strategy.paused,
            fills,
            status,
            net,
            timeline,
            {
                name[o.client_order_id]: [
                    e.ts_event - START for e in o.events() if isinstance(e, OrderPendingCancel)
                ]
                for o in orders
            },
        )
    finally:
        engine.dispose()


NO_CHASE = dataclasses.replace(FIXTURE, chase_cap_fraction=None, chase_min_interval_s=None)
STARTS = ExitParams.starts()
PRE = START - 3600 * NS  # 08:30 ET, pre-market (sextant.paper.sessions)


def _kinds_of(t: Tape) -> list[str]:
    return [e["event"] for e in t.events]


def _sold(t: Tape, *, owner: bool | None = None) -> D:
    return sum((D(q) for _t, s, q, _p, o in t.fills if s == "SELL" and owner in (None, o)), D(0))


def test_a_partial_entrys_remainder_is_canceled_and_terminal_before_the_breach_sell() -> None:
    """#169, ADR-0005:36: cancel a partial entry's remainder and prove it terminal before a close.
    The LIMIT BUY 10 @ 100.50 takes 6 @ 100.02, bids of 99.50 persist, then the ask comes back to
    the limit. The remainder never fills, so the position never reopens on the old order."""
    thin = Quote("100.00", "100.02", ask_size="6")
    wide, back = Quote("99.50", "100.55"), Quote("100.48", "100.50")
    t = tape_run([thin] + [wide] * 4 + [back] * 6, [Order(0, "10", price="100.50")])
    assert [(s, q, p) for _t, s, q, p, _o in t.fills] == [
        ("BUY", "6", "100.02"),
        ("SELL", "6", "99.50"),
    ]
    assert t.status == {"house-1": "CANCELED", "engine-SELL": "FILLED"}
    kinds = [e["event"] for e in t.events]
    assert kinds.count("protected_from_fill") == 1 and t.net == 0
    # The breach persisted at second 3: the crossing is retained exit intent, not permission
    # (ADR-0005:36). The remainder's cancel was terminal at once, and its event sent the sell.
    assert (3, "house-1", "OrderCanceled") in t.timeline
    crossed = next(e for e in t.events if e["event"] == "crossed")
    sell = next(e for e in t.events if e["event"] == "breach_sell_prearm")
    assert crossed["ts"] == sell["ts"] == str(START + 3 * NS)


def test_a_crossing_is_retained_through_a_rebound_while_the_remainder_cancels() -> None:
    """ADR-0005:36: a price rebound cannot clear the crossing's exit intent, and the crossing
    freezes the levels. The breach persists at second 3; the remainder's cancel takes 2.5 s (rc8
    StaticLatencyModel). A print at 100.40 and a rebound above the trigger come while it waits;
    the house still sells its 6 once the cancel is terminal (delivered with the data at second 6),
    recorded at the crossing's trigger."""
    thin = Quote("100.00", "100.02", ask_size="6")
    wide, rebound = Quote("99.50", "100.55"), Quote("100.00", "100.55")
    late = StaticLatencyModel(cancel_latency_nanos=2_500_000_000)
    items: list[Quote | Trade] = [thin] + [wide] * 3 + [Trade("100.40")] + [rebound] * 3
    t = tape_run(items, [Order(0, "10", price="100.50")], latency=late)
    crossed = next(e for e in t.events if e["event"] == "crossed")
    (sell,) = [e for e in t.events if e["event"].startswith("breach_sell")]
    assert sell["ts"] == str(START + 6 * NS) and sell["trigger"] == crossed["trigger"]
    assert sell["qty"] == "6" and t.status["house-1"] == "CANCELED"


def test_the_cancel_first_exit_cancels_only_the_houses_own_orders() -> None:
    """ADR-0007:16-19: cancel acts only on house orders, and a working order the house didn't send
    freezes the symbol and pages before any cancel. An owner BUY LIMIT rests below the market."""
    owner_bid = Order(1, "5", price="99.00", owner=True)
    t = tape_run([FLAT] * 3 + [LOW] * 4, [Order(0, "10"), owner_bid])
    assert _sold(t) == 0 and t.paused and t.pages == ["foreign_order"]
    assert t.status["owner-1"] == "ACCEPTED"
    assert not [x for x in t.timeline if x[1] == "owner-1" and "Cancel" in x[2]]


def test_a_reopened_position_takes_its_basis_from_its_own_fills() -> None:
    """#169: the opening order's lifetime `Order.avg_px` blends the fills of a position that has
    closed. rc8's `Position.avg_px_open` is a Decimal of this position's own fills."""
    thin = Quote("100.00", "100.02", ask_size="6")
    above, back = Quote("100.00", "100.55"), Quote("100.48", "100.50")
    owner_sells_6 = Order(1, "6", side=OrderSide.SELL, owner=True)
    t = tape_run([thin] + [above] * 2 + [back] * 3, [Order(0, "10", price="100.50"), owner_sells_6])
    assert [(s, q, p) for _t, s, q, p, _o in t.fills] == [
        ("BUY", "6", "100.02"),
        ("SELL", "6", "100.00"),
        ("BUY", "4", "100.50"),
    ]
    entries = [D(e["entry"]) for e in t.events if e["event"] == "protected_from_fill"]
    assert entries == [D("100.02"), D("100.50")]  # never the blended 100.2120


def test_an_owner_buy_after_a_house_exit_is_never_adopted_or_sold() -> None:
    """#209, ADR-0007:16-17: only a position a house order opened is protected. After the house's
    exit, an owner BUY on the flat symbol pauses it and pages; its shares are never sold."""
    dip, lower = Quote("99.60", "99.62"), Quote("99.30", "99.32")
    items = [FLAT] * 3 + [LOW] * 3 + [dip] * 3 + [lower] * 6
    t = tape_run(items, [Order(0, "10"), Order(6, "5", owner=True)])
    assert _sold(t) == 10 and t.net == 5  # the house sold its own 10, never the owner's 5
    assert [D(e["entry"]) for e in t.events if e["event"] == "protected_from_fill"] == [D("100.02")]
    assert t.paused and t.pages == ["quantity_mismatch"]


def _remainder_tape() -> list[Quote | Trade]:
    """#210's tape: a LIMIT BUY 10 @ 5.07 meets 6 at 5.01; the quote holds 5.06/5.08 with prints at
    5.06, the lock arms; at second 71 the ask ticks to 5.07 and the remaining 4 fill there."""
    items: list[Quote | Trade] = [Quote("5.00", "5.01", ask_size="6")]
    items += [Quote("5.06", "5.08"), Trade("5.06")] * 35
    return items + [Quote("5.06", "5.07"), Trade("5.06")] * 30


def test_a_remainders_own_fill_never_raises_h_so_an_unchanged_bid_never_sells() -> None:
    """#210 cause 1, ADR-0005:27: H is the high of eligible trades, and the house's own fill is
    not one. Raising H to the remainder's 5.07 put the lock on the unchanged 5.06 bid."""
    for params in (FIXTURE, STARTS):
        t = tape_run(_remainder_tape(), [Order(0, "10", price="5.07")], params)
        assert [(s, q, p) for _t, s, q, p, _o in t.fills] == [
            ("BUY", "6", "5.01"),
            ("BUY", "4", "5.07"),
        ]
        assert "armed" in [e["event"] for e in t.events]
        assert _sold(t) == 0 and t.net == 10


def test_a_cancel_that_never_ends_pages_at_the_60_second_deadline() -> None:
    """ADR-0005:36: the first cancellation wait has a 60-second escalation deadline. The remainder's
    cancel takes 100 s (a venue that never answers in time), so the engine pages at 63 s and sells
    only on the cancel's terminal event at 103 s, never beside a live remainder."""
    thin, wide = Quote("100.00", "100.02", ask_size="6"), Quote("99.50", "100.55")
    late = StaticLatencyModel(cancel_latency_nanos=100_000_000_000)
    t = tape_run([thin] + [wide] * 110, [Order(0, "10", price="100.50")], latency=late)
    page = next(e for e in t.events if e["event"] == "page")
    assert page["reason"] == "partial_entry_cancel_timeout" and page["ts"] == str(START + 63 * NS)
    (sell,) = [e for e in t.events if e["event"].startswith("breach_sell")]
    assert sell["ts"] == str(START + 103 * NS) and t.net == 0


def test_a_late_quote_pages_the_deadline_60_s_after_the_crossings_clock_time() -> None:
    """The deadline starts with the first cancellation wait on the engine's clock, as northstar
    starts its wait at `s._now()` and checks `s._now() - wait.started_ns` (strategies/alpaca.py:
    942, :991; base.py:711), never at the quote's own event time. With every quote 1 s late, the
    crossing's cancel goes out at 3 on the clock, and the timeout pages exactly 60 s later."""
    thin, wide = Quote("100.00", "100.02", ask_size="6"), Quote("99.50", "100.55")
    late = StaticLatencyModel(cancel_latency_nanos=100_000_000_000)
    t = tape_run(
        [thin] + [wide] * 110, [Order(0, "10", price="100.50")], latency=late, quote_delay_ns=NS
    )
    page = next(e for e in t.events if e["event"] == "page")
    assert page["reason"] == "partial_entry_cancel_timeout" and t.sent["house-1"][0] == 3 * NS
    assert int(page["ts"]) - START - t.sent["house-1"][0] == 60 * NS


def test_outside_rth_the_terminal_cancel_sends_the_exit_without_waiting_for_a_print() -> None:
    """Outside RTH only a print steps the engine, and prints can be minutes apart. The remainder's
    terminal cancel itself sends the retained exit (a #169 review finding)."""
    thin, wide = Quote("100.00", "100.02", ask_size="6"), Quote("99.40", "100.55")
    items: list[Quote | Trade] = [thin, Trade("100.02"), wide] + [Trade("99.50")] * 3
    items += [wide] * 70  # quotes only: no print after the crossing
    t = tape_run(items, [Order(0, "10", price="100.50")], session="outside")
    crossed = next(e for e in t.events if e["event"] == "crossed")
    (sell,) = [e for e in t.events if e["event"].startswith("breach_sell")]
    assert sell["ts"] == crossed["ts"] and t.pages == []  # the deadline never pages a sent exit


def test_a_second_house_orders_fill_grows_the_protection_and_never_pages() -> None:
    """ADR-0007:16: provenance is the house set, not the opener alone. The owner sells house-1's 6
    flat while house-1's remainder works; house-2 re-enters, then house-1's last 4 fill. Those
    4 are the house's, so they join the protection instead of paging owner_add."""
    thin, above, back = (
        Quote("100.00", "100.02", ask_size="6"),
        Quote("100.40", "100.55"),
        Quote("100.48", "100.50"),
    )
    owner_sells_6 = Order(1, "6", side=OrderSide.SELL, owner=True)
    t = tape_run(
        [thin, above, above, back], [Order(0, "10", price="100.50"), owner_sells_6, Order(2, "10")]
    )
    assert t.pages == [] and not t.paused
    grown = [
        D(e["qty"]) for e in t.events if e["event"] in ("protected_from_fill", "protected_qty")
    ]
    assert grown[-1] == 14 and t.net == 14


def test_a_pause_clears_on_a_verified_flat_so_a_house_re_entry_is_protected() -> None:
    """#171: an owner add pauses the symbol; the owner then sells all 15, so the account is flat
    with every order terminal. A later house re-entry is protected afresh and sold on a breach."""
    script = [
        Order(0, "10"),
        Order(1, "5", owner=True),
        Order(3, "15", side=OrderSide.SELL, owner=True),
        Order(4, "10"),
    ]
    t = tape_run([FLAT] * 6 + [LOW] * 6, script)
    assert t.pages == ["owner_add"]
    entries = [D(e["entry"]) for e in t.events if e["event"] == "protected_from_fill"]
    assert entries == [D("100.02"), D("100.02")]
    assert _sold(t, owner=False) == 10 and t.net == 0 and not t.paused
    (cleared,) = [int(e["ts"]) for e in t.events if e["event"] == "pause_cleared"]
    assert cleared == START + 3 * NS  # at the close itself, a verified flat


def test_a_pause_on_an_owner_position_clears_once_the_owner_sells_it_flat() -> None:
    """#171 through #209: an owner BUY after the house's exit pauses the symbol; the owner then
    sells those 5, a verified flat, so the house's later re-entry is protected and sold."""
    dip, lower = Quote("99.60", "99.62"), Quote("99.30", "99.32")
    script = [
        Order(0, "10"),
        Order(6, "5", owner=True),
        Order(8, "5", side=OrderSide.SELL, owner=True),
        Order(10, "10"),
    ]
    t = tape_run([FLAT] * 3 + [LOW] * 3 + [dip] * 5 + [lower] * 6, script)
    assert t.pages == ["quantity_mismatch"] and not t.paused
    entries = [D(e["entry"]) for e in t.events if e["event"] == "protected_from_fill"]
    assert entries == [D("100.02"), D("99.62")] and _sold(t, owner=False) == 20 and t.net == 0
    assert _kinds_of(t).count("flat") == 3  # the owner's own cycle ends on the symbol too


def test_a_close_with_an_owner_order_still_working_keeps_the_pause() -> None:
    """#171's other side: only a verified flat clears a pause. The owner adds 5, which pauses, and
    rests another BUY below the market; the owner's sell of all 15 leaves that BUY working, so
    the symbol stays paused and the later house entry is never protected."""
    script = [
        Order(0, "10"),
        Order(1, "5", owner=True),
        Order(2, "5", price="99.00", owner=True),
        Order(3, "15", side=OrderSide.SELL, owner=True),
        Order(4, "10"),
    ]
    t = tape_run([FLAT] * 6 + [LOW] * 6, script)
    assert t.paused and t.pages == ["owner_add", "quantity_mismatch"]
    assert _sold(t, owner=False) == 0 and t.status["owner-2"] == "ACCEPTED"


def test_each_page_reaches_a_person_once_as_an_error_line() -> None:
    """ADR-0007:17 "pages a person": a page is one ERROR log line naming its kind, reason and
    instrument (northstar-trading@8256c16c exit_manager/strategy.py:1307), never memory alone."""
    Scripted.paged = Paged()
    script = [Order(0, "10"), Order(2, "5", owner=True), Order(3, "5", owner=True)]
    t = tape_run([FLAT] * 5 + [LOW] * 6, script)
    assert t.pages == ["owner_add"] and _kinds_of(t).count("add_paused") == 2  # each add recorded
    assert Scripted.paged.errors == ["add_paused: owner_add on PTEST.SIM"]


def test_an_emulated_house_order_is_canceled_and_terminal_before_the_exit() -> None:
    """The cancel-first wait counts every house order that is not closed, including one rc8's
    OrderEmulator holds locally: an emulated BUY left working would reopen the position."""
    script = [Order(0, "10"), Order(1, "5", price="99.00", emulated=True)]
    t = tape_run([FLAT] * 3 + [LOW] * 3 + [Quote("98.90", "98.92")] * 4, script)
    assert t.status["house-2"] == "CANCELED" and _sold(t) == 10 and t.net == 0


def test_a_remainder_that_fills_while_its_cancel_is_in_flight_is_sold_with_the_position() -> None:
    """ADR-0005:36: "a price rebound, cancel rejection or late fill cannot clear that intent". The
    remainder fills 4 @ 100.50 at second 4, before its 1.5 s cancel lands, so there is no cancel
    event; the retained crossing sells all 10 on the next bid although the bid has rebounded."""
    thin, wide = Quote("100.00", "100.02", ask_size="6"), Quote("99.50", "100.55")
    back = Quote("100.00", "100.50")  # the ask touches the remainder's limit
    late = StaticLatencyModel(cancel_latency_nanos=1_500_000_000)
    t = tape_run([thin] + [wide] * 3 + [back] * 4, [Order(0, "10", price="100.50")], latency=late)
    assert t.status["house-1"] == "FILLED" and _sold(t) == 10 and t.net == 0


def test_a_late_cancel_from_a_closed_cycle_never_sells_the_next_position() -> None:
    """The crossing belongs to its position. Its remainder's cancel takes 3 s; meanwhile the owner
    sells the 6 flat (a reset) and the house re-enters 10. The old cancel then lands, and the new
    position, which never breached, is not sold."""
    thin, wide = Quote("100.00", "100.02", ask_size="6"), Quote("99.50", "100.55")
    again = Quote("100.40", "100.55")  # the ask stays above the remainder's 100.50 limit
    late = StaticLatencyModel(cancel_latency_nanos=3_000_000_000)
    owner_sells_6 = Order(4, "6", side=OrderSide.SELL, owner=True)
    script = [Order(0, "10", price="100.50"), owner_sells_6, Order(5, "10")]
    t = tape_run([thin] + [wide] * 4 + [again] * 6, script, latency=late)
    assert t.status["house-1"] == "CANCELED" and _sold(t, owner=False) == 0 and t.net == 10


def test_a_pause_clears_once_the_blocking_order_ends_so_a_house_re_entry_is_protected() -> None:
    """#171's late edge (the #214 dsh leg's P2-1): the owner's resting BUY keeps the pause through
    the close; it is canceled at second 6, so from then the account is flat with every order
    terminal, a verified flat (ADR-0007:21). The next observation clears the pause, and the house's
    re-entry at second 9 is protected and sold on the breach."""
    script = [
        Order(0, "10"),
        Order(1, "5", owner=True),
        Order(2, "5", price="99.00", owner=True, cancel_at=6),
        Order(3, "15", side=OrderSide.SELL, owner=True),
        Order(9, "10"),
    ]
    t = tape_run([FLAT] * 11 + [LOW] * 6, script)
    assert t.status["owner-2"] == "CANCELED" and t.pages == ["owner_add"]
    entries = [D(e["entry"]) for e in t.events if e["event"] == "protected_from_fill"]
    assert entries == [D("100.02"), D("100.02")] and "pause_cleared" in _kinds_of(t)
    assert _sold(t, owner=False) == 10 and t.net == 0 and not t.paused
    # It clears on the cancel's own terminal event at second 6, not at the next quote (F3).
    (cleared,) = [int(e["ts"]) for e in t.events if e["event"] == "pause_cleared"]
    assert cleared == START + 6 * NS


def test_a_second_owner_add_after_a_cleared_pause_pages_and_records_again() -> None:
    """The #214 dsh leg's P2-2: a page is once per reason in each episode, not once in the engine's
    life. The owner's first add pauses; the owner sells all 15 flat, which clears it; the house
    re-enters and the owner adds again. That second add pauses, records and pages again."""
    Scripted.paged = Paged()
    script = [
        Order(0, "10"),
        Order(1, "5", owner=True),
        Order(3, "15", side=OrderSide.SELL, owner=True),
        Order(4, "10"),
        Order(6, "5", owner=True),
    ]
    t = tape_run([FLAT] * 8 + [LOW] * 4, script)
    assert t.pages == ["owner_add", "owner_add"] and len(Scripted.paged.errors) == 2
    assert _kinds_of(t).count("add_paused") == 2
    assert t.paused and _sold(t, owner=False) == 0 and t.net == 15


def test_outside_rth_the_cancel_deadline_pages_on_the_clock_without_a_print() -> None:
    """The #214 dsh leg's P2-3: ADR-0005:36's 60-second deadline runs on the clock, as rc8 expires
    a GTD order by a time alert, never on market data. Outside RTH only quotes follow the crossing
    and the remainder's cancel takes 100 s; the page still comes 60 s after the crossing, and the
    exit goes out on the terminal cancel."""
    thin, wide = Quote("100.00", "100.02", ask_size="6"), Quote("99.40", "100.55")
    late = StaticLatencyModel(cancel_latency_nanos=100_000_000_000)
    items: list[Quote | Trade] = [thin, Trade("100.02"), wide] + [Trade("99.50")] * 3
    items += [wide] * 110  # quotes only: no print after the crossing
    t = tape_run(items, [Order(0, "10", price="100.50")], session="outside", latency=late)
    crossed = next(int(e["ts"]) for e in t.events if e["event"] == "crossed")
    pages = [(e["reason"], int(e["ts"]) - crossed) for e in t.events if e["event"] == "page"]
    (sell,) = [int(e["ts"]) - crossed for e in t.events if e["event"].startswith("breach_sell")]
    assert pages == [("partial_entry_cancel_timeout", 60 * NS)] and sell == 100 * NS


def _in_flight(
    insert_s: float, flat: int = 12, cancel_ns: int = 400_000_000, quote_delay_ns: int = 0
) -> Tape:
    """House-2 (a resting BUY 5 @ 99.00) is still in flight to the venue when the breach crosses,
    so the venue rejects each cancel that arrives first, "Order ... not found" (rc8
    crates/execution/src/matching_engine/mod.rs:3888-3920), and house-2 then rests. The entry
    lands after the same latency, so `flat` seconds keep it filling before the fall."""
    latency = StaticLatencyModel(
        insert_latency_nanos=int(insert_s * NS), cancel_latency_nanos=cancel_ns
    )
    script = [Order(0, "10"), Order(flat - 1, "5", price="99.00")]
    return tape_run(
        [FLAT] * flat + [LOW] * 80, script, latency=latency, quote_delay_ns=quote_delay_ns
    )


def _cancels(t: Tape, name: str = "house-2") -> list[int]:
    return [s for s, n, e in t.timeline if n == name and e == "OrderPendingCancel"]


def _retries(t: Tape) -> list[int]:
    """Each re-send's time after START, to the nanosecond: 5 s from the last request, not from
    the rejection that came back after the cancel latency."""
    return [int(e["ts"]) - START for e in t.events if e["event"] == "cancel_retry"]


def test_a_rejected_cancel_is_retried_so_the_exit_still_goes_out() -> None:
    """The #214 dsh leg's P2-4: a cancel rejection cannot clear the retained intent (ADR-0005:36),
    so house-2's cancel goes out again once it rests, and the 10 are sold."""
    t = _in_flight(4.0)
    rejected = [e for _s, n, e in t.timeline if n == "house-2"].count("OrderCancelRejected")
    assert rejected >= 1 and t.status["house-2"] == "CANCELED"
    assert _sold(t) == 10 and t.net == 0 and t.pages == []


def test_a_rejected_cancel_is_not_sent_again_at_once() -> None:
    """The #214 dsh review at dd6edd7: no upstream re-sends a rejected GTC cancel at once. As
    northstar's cancel-first wait does, it goes out again once 5 s have passed since that order's
    last cancel request (northstar-trading@8256c16c strategies/base.py:101,1728-1754,2186-2189).
    The crossing cancels in-flight house-2 at second 14 and the venue rejects it; house-2 rests at
    15, and the cancel goes out again at 19, never at 15."""
    t = _in_flight(4.0)
    assert _cancels(t) == [14, 19] and _retries(t) == [19 * NS]
    assert t.status["house-2"] == "CANCELED" and _sold(t) == 10 and t.pages == []


def test_a_rejected_cancel_goes_out_again_5_s_after_its_last_send_while_the_order_works() -> None:
    """Each re-send waits 5 s from that order's last cancel request, as northstar's wait re-requests
    each unfinished reservation's cancel through that throttle (strategies/alpaca.py:977-978).
    House-2 is in flight until second 21, so the re-sends follow the crossing's cancel at 14 at 19
    and 24; the one at 24, after it rests, cancels it, and the 10 are sold with no page."""
    t = _in_flight(10.0)
    assert _cancels(t) == [14, 19, 24] and _retries(t) == [19 * NS, 24 * NS]
    assert t.status["house-2"] == "CANCELED" and _sold(t) == 10 and t.net == 0 and t.pages == []


def test_a_rejection_that_comes_back_after_5_s_sends_the_cancel_again_at_once() -> None:
    """If the 5 s have already passed when the rejection comes back, the cancel goes out at once,
    as rc8 cancels an order whose expiry has already passed (crates/trading/src/strategy/
    mod.rs:2216-2219). Each cancel takes 6 s: the crossing's, sent at 14, is rejected at 20 and
    goes out again then; house-2 rests at 21, so that one cancels it and the 10 are sold."""
    t = _in_flight(10.0, cancel_ns=6 * NS)
    assert _cancels(t) == [14, 20] and _retries(t) == [20 * NS]
    assert t.status["house-2"] == "CANCELED" and _sold(t) == 10 and t.pages == []


@pytest.mark.parametrize("delay_ns", [0, 1, NS, 4 * NS])
def test_the_re_send_waits_5_s_of_engine_clock_however_late_the_quote(delay_ns: int) -> None:
    """The #214 GPT delta gate at c76c77b: a re-send waits 5 s from the cancel's actual request,
    on the engine's clock, as northstar's throttle reads `self._now()` (strategies/base.py:711,
    :1743), never from the quote's own event time. A quote that arrives `delay_ns` after its
    event once brought the re-send 5 s minus that delay after the request. The longest delay is
    4 s: since #231's r4 R2 a quote past `quote_max_age_s` (5 s here) on the engine clock is
    stale, so the old 6 s case no longer reaches the crossing."""
    t = _in_flight(4.0, quote_delay_ns=delay_ns)
    first, second = t.sent["house-2"][:2]
    assert second - first == 5 * NS


@pytest.mark.parametrize("delay_ns", [0, NS])
def test_a_late_quote_never_spends_the_cancel_bound_before_the_order_lands(delay_ns: int) -> None:
    """The gate's witness: with 17.5 s insert latency house-2 lands at 36.5. Quotes 1 s late once
    sent its cancels at 22, 26, 31 and 36, spending K+1 before it landed, so it stayed working,
    nothing sold the 10, and both pages fired. Timed on the clock, the fourth, at 37, cancels it."""
    t = _in_flight(17.5, flat=20, quote_delay_ns=delay_ns)
    assert _cancels(t) == [22, 27, 32, 37] and t.status["house-2"] == "CANCELED"
    assert _sold(t) == 10 and t.net == 0 and t.pages == []


def test_a_cancel_rejected_past_its_bound_pages_and_never_sells_beside_the_order() -> None:
    """ADR-0007:27 bounds the retries: at most K+1 = 4 cancels for one order, each 5 s after the
    last. The breach crosses at 32 and every cancel lands before house-2 does (at 49), so the
    fourth rejection pages cancel_rejected, the deadline pages at 60 s, and the exit never goes
    out beside the working BUY."""
    t = _in_flight(20.0, flat=30)
    rejected = [e for _s, n, e in t.timeline if n == "house-2"].count("OrderCancelRejected")
    assert _cancels(t) == [32, 37, 42, 47] and rejected == 4
    assert t.pages == ["cancel_rejected", "partial_entry_cancel_timeout"]
    assert t.status["house-2"] == "ACCEPTED" and _sold(t) == 0 and t.net == 10


def test_the_cancel_retry_interval_is_an_uncalibrated_row_at_its_source() -> None:
    """Rule 2: the 5 s re-send interval is a registry row with its source, an uncalibrated start
    (northstar-trading@8256c16c strategies/base.py:101, `CANCEL_RETRY_NS = 5 * SEC`)."""
    (row,) = engine_module.REGISTRY
    assert (row.name, row.start, row.state) == ("cancel_retry_s", D(5), "UNCALIBRATED")
    pin = "northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa"
    assert row.source == f"{pin}:src/northstar_trading/strategies/base.py:101"
    assert engine_module.CANCEL_RETRY_NS == 5 * NS


def test_an_owner_sell_fill_is_never_recorded_as_the_houses_exit() -> None:
    """The #214 dsh leg's P3: `sell_fill` is the house's own exit. An owner's sell is recorded as
    `owner_sell_fill`, so merit and the ledger never count it as the engine's."""
    script = [
        Order(0, "10"),
        Order(1, "5", owner=True),
        Order(3, "15", side=OrderSide.SELL, owner=True),
    ]
    t = tape_run([FLAT] * 5, script)
    assert "owner_sell_fill" in _kinds_of(t) and "sell_fill" not in _kinds_of(t)


def test_the_deadline_never_pages_a_paused_symbol() -> None:
    """The deadline escalates an exit the engine still owes and manages. An owner BUY pauses the
    symbol while the remainder's 10 s cancel is in flight (a working foreign order freezes it, then
    its fill is an add); that pause has paged a person, so at 60 s the deadline adds no page."""
    thin, wide = Quote("100.00", "100.02", ask_size="6"), Quote("99.50", "100.55")
    late = StaticLatencyModel(cancel_latency_nanos=10_000_000_000)
    t = tape_run(
        [thin] + [wide] * 70,
        [Order(0, "10", price="100.50"), Order(4, "5", owner=True)],
        latency=late,
    )
    assert t.status["house-1"] == "CANCELED" and t.pages == ["foreign_order", "owner_add"]
    assert _sold(t) == 0


def _reservation_tape(after: Quote) -> list[Quote | Trade]:
    """Outside RTH: house buys 10, rests a house BUY 5 @ 99.00 at second 2; three prints at 99.50
    persist the breach (second 5); then only quotes. The resting BUY's cancel takes 100 s."""
    return [FLAT, Trade("100.02"), FLAT] + [Trade("99.50")] * 3 + [after] * 75


def test_a_reservation_that_fills_terminal_sends_the_owed_exit_without_a_print() -> None:
    """The #214 GPT gate's F1: a reservation can end by filling, not only by its cancel. The house
    BUY 5 @ 99.00 fills at second 6, before its 100 s cancel returns; the crossing is owed, so the
    exit of all 15 goes out at that fill, with no later print (rc8 dispatches each terminal kind,
    crates/trading/src/strategy/mod.rs:1370-1393,1445-1464)."""
    late = StaticLatencyModel(cancel_latency_nanos=100 * NS)
    script = [Order(0, "10"), Order(2, "5", price="99.00")]
    t = tape_run(
        _reservation_tape(Quote("98.98", "99.00")), script, session="outside", latency=late
    )
    (sell,) = [e for e in t.events if e["event"].startswith("breach_sell")]
    assert t.status["house-2"] == "FILLED" and sell["qty"] == "15"
    assert int(sell["ts"]) == START + 6 * NS and t.pages == []


def test_a_reservation_that_expires_sends_the_owed_exit_without_a_print() -> None:
    """F1's other terminal kind: the resting house BUY is GTD and expires at second 7, before its
    cancel returns. The owed exit of 10 goes out at the expiry, with no later print."""
    late = StaticLatencyModel(cancel_latency_nanos=100 * NS)
    script = [Order(0, "10"), Order(2, "5", price="99.00", expire_s=7)]
    t = tape_run(_reservation_tape(LOW), script, session="outside", latency=late)
    (sell,) = [e for e in t.events if e["event"].startswith("breach_sell")]
    assert t.status["house-2"] == "EXPIRED" and sell["qty"] == "10"
    assert int(sell["ts"]) == START + 7 * NS and t.pages == []


def test_a_close_while_the_crossed_entry_is_unfinished_keeps_the_owed_exit() -> None:
    """F2, ADR-0007:21: a position close is not a verified flat while the entry's remainder is
    unfinished. The owner sells the 6 that filled while the remainder's 100 s cancel is pending.
    That SELL is a working order the house didn't send, so it freezes the symbol first (ADR-0007:19,
    PR 2). The close keeps the crossing owed, and the remainder's late 4 reopen the position on the
    frozen symbol, which pages again rather than protecting them afresh with a new trigger."""
    thin, wide = Quote("100.00", "100.02", ask_size="6"), Quote("99.50", "100.55")
    back = Quote("100.40", "100.50")  # the ask touches the remainder's limit
    late = StaticLatencyModel(cancel_latency_nanos=100 * NS)
    owner_sells_6 = Order(4, "6", side=OrderSide.SELL, owner=True)
    t = tape_run(
        [thin] + [wide] * 4 + [back] * 75,
        [Order(0, "10", price="100.50"), owner_sells_6],
        latency=late,
    )
    assert t.status["house-1"] == "FILLED" and t.paused and t.net == 4
    assert t.pages == ["foreign_order", "quantity_mismatch"]
    assert "initial_trigger" not in _kinds_of(t)[_kinds_of(t).index("flat") :]


def test_a_pause_clears_on_the_blocking_orders_own_terminal_event() -> None:
    """F3, #171: the verified flat is recognized when the last blocking order ends, not at the
    next quote. The owner's resting BUY is canceled with 2 s latency and ends at second 6; a house
    BUY 10 goes out on that same quote, so no quote re-checks in between. It is protected and
    sold on the breach."""
    script = [
        Order(0, "10"),
        Order(1, "5", owner=True),
        Order(2, "5", price="99.00", owner=True, cancel_at=4),
        Order(3, "15", side=OrderSide.SELL, owner=True),
        Order(6, "10"),
    ]
    t = tape_run(
        [FLAT] * 9 + [LOW] * 8, script, latency=StaticLatencyModel(cancel_latency_nanos=2 * NS)
    )
    assert (6, "owner-2", "OrderCanceled") in t.timeline and t.pages == ["owner_add"]
    assert _sold(t, owner=False) == 10 and t.net == 0 and not t.paused


def test_each_owner_position_pages_its_own_quantity_mismatch() -> None:
    """Pages are once per reason in each position cycle (#214 dsh P2-2): an owner position opened
    after the house's exit pages; the owner sells it flat, which clears the pause; the owner's
    second position pages again."""
    dip = Quote("99.60", "99.62")
    script = [
        Order(0, "10"),
        Order(6, "5", owner=True),
        Order(8, "5", side=OrderSide.SELL, owner=True),
        Order(10, "5", owner=True),
    ]
    t = tape_run([FLAT] * 3 + [LOW] * 3 + [dip] * 8, script)
    assert t.pages == ["quantity_mismatch", "quantity_mismatch"] and t.net == 5


def test_an_external_blocking_orders_end_is_caught_on_the_next_quote() -> None:
    """The #214 dsh leg's P2-1: an owner order placed outside this engine never sends it events.
    Its cancel at second 6 still ends the pause on the next quote, at second 7, so the house's
    re-entry at second 9 is protected and sold."""
    script = [
        Order(0, "10"),
        Order(1, "5", owner=True),
        Order(2, "5", price="99.00", owner=True, cancel_at=6, external=True),
        Order(3, "15", side=OrderSide.SELL, owner=True),
        Order(9, "10"),
    ]
    t = tape_run([FLAT] * 11 + [LOW] * 6, script)
    (cleared,) = [int(e["ts"]) for e in t.events if e["event"] == "pause_cleared"]
    assert cleared == START + 7 * NS and t.status["owner-2"] == "CANCELED"
    assert _sold(t, owner=False) == 10 and t.net == 0 and not t.paused


def test_a_second_reservation_that_reopens_after_a_close_is_sold() -> None:
    """The #214 GPT delta gate's remaining F2: every reservation the crossing canceled keeps its
    exit owed, not only the entry (northstar ADR-0002:354-366, "cancel all reservations"). House-2,
    a BUY 5 @ 100.50 resting since second 2, is pending its 100 s cancel when the owner sells the 10
    flat; its 5 then fill and reopen the position. Under PR 2's freeze (ADR-0007:19) the owner's
    SELL froze the symbol first, so those 5 page again and are held, never protected afresh."""
    wide, back = Quote("99.50", "100.55"), Quote("100.40", "100.50")
    late = StaticLatencyModel(cancel_latency_nanos=100 * NS)
    items = [FLAT] * 2 + [Quote("100.00", "100.55")] + [wide] * 4 + [back] * 75
    script = [
        Order(0, "10"),
        Order(2, "5", price="100.50"),
        Order(6, "10", side=OrderSide.SELL, owner=True),
    ]
    t = tape_run(items, script, latency=late)
    assert t.status["house-2"] == "FILLED" and t.paused and t.net == 5
    assert t.pages == ["foreign_order", "quantity_mismatch"]
    assert "initial_trigger" not in _kinds_of(t)[_kinds_of(t).index("flat") :]


def _kept_cycle(script: list[Order]) -> Tape:
    """House-1's LIMIT BUY 10 @ 100.50 fills 6 and the breach crosses at second 3; the owner then
    closes the position while the remainder's 3 s cancel is pending, which ends it at second 6."""
    thin, wide = Quote("100.00", "100.02", ask_size="6"), Quote("99.50", "100.55")
    items = [thin] + [wide] * 4 + [Quote("100.40", "100.55")] * 8 + [LOW] * 70
    return tape_run(items, script, latency=StaticLatencyModel(cancel_latency_nanos=3 * NS))


def test_a_kept_cycle_retires_when_its_last_reservation_ends_flat() -> None:
    """The delta gate's D1, ADR-0007:21: once the kept cycle's last reservation is terminal and no
    position is open, the flat is verified. The kept crossing retires, the owner add's pause clears,
    and the fresh house BUY at second 8 is protected and sold on the breach."""
    owner = [Order(4, "5", owner=True), Order(5, "11", side=OrderSide.SELL, owner=True)]
    t = _kept_cycle([Order(0, "10", price="100.50"), *owner, Order(8, "10")])
    assert t.status["house-1"] == "CANCELED" and "pause_cleared" in _kinds_of(t)
    assert _sold(t, owner=False) == 10 and t.net == 0 and not t.paused


def test_a_kept_cycle_that_retires_never_pages_its_deadline() -> None:
    """D1: the owner sells the 6 flat while the remainder's cancel is pending (under PR 2 that SELL
    freezes the symbol first, ADR-0007:19); the cancel ends at second 6 with nothing left owed, so
    the kept cycle retires, the freeze clears and the 60 s deadline never pages."""
    t = _kept_cycle(
        [Order(0, "10", price="100.50"), Order(4, "6", side=OrderSide.SELL, owner=True)]
    )
    assert t.status["house-1"] == "CANCELED" and t.net == 0 and not t.paused
    assert t.pages == ["foreign_order"]


def test_a_reservation_whose_cancel_is_rejected_after_a_close_keeps_its_exit_owed() -> None:
    """The #214 GPT delta gate at 34bff6b: a rejected cancel must not erase a reservation's
    identity (northstar ADR-0002:354-366, a cancel rejection cannot clear that intent). The
    owner's SELL closes the position at second 10 while house-2's cancel, which reached the venue
    before house-2 did, is rejected; house-2 then lands and fills 5 at second 13. Those 5 belong to
    the crossing. Under PR 2's freeze (ADR-0007:19) the owner's working SELL froze the symbol first,
    so they page again and are held, never protected afresh with a new trigger."""
    t = _rejected_then_filled()
    rejected = [e for _s, n, e in t.timeline if n == "house-2"].count("OrderCancelRejected")
    assert rejected >= 1 and t.status["house-2"] == "FILLED" and t.paused and t.net == 5
    assert t.pages == ["foreign_order", "quantity_mismatch"]
    assert "initial_trigger" not in _kinds_of(t)[_kinds_of(t).index("flat") :]


def _rejected_then_filled() -> Tape:
    wide, back = Quote("99.50", "100.55"), Quote("100.40", "100.50")
    latency = StaticLatencyModel(insert_latency_nanos=5 * NS, cancel_latency_nanos=1 * NS)
    script = [
        Order(0, "10"),
        Order(5, "10", side=OrderSide.SELL, price="99.00", owner=True),
        Order(8, "5", price="100.50"),
    ]
    return tape_run([FLAT] * 7 + [wide] * 6 + [back] * 70, script, latency=latency)


def test_a_rejected_cancel_is_never_sent_again_once_its_order_has_ended() -> None:
    """The re-send goes out only while the order still works (northstar-trading@8256c16c
    strategies/base.py:2186-2189, "if still working"). House-2's cancel at second 9 is rejected;
    house-2 lands and fills at 13, before its re-send falls due at 14, so no cancel goes out
    again. Under PR 2's freeze its 5 are held on the frozen symbol."""
    t = _rejected_then_filled()
    assert _cancels(t) == [9] and _retries(t) == [] and t.status["house-2"] == "FILLED"
    assert t.paused and t.net == 5


def test_an_owner_add_while_the_managed_sell_rests_is_never_sold_back() -> None:
    """#170, ADR-0007:17: the venue resizes a resting reduce-only sell to the position, so after an
    owner add it would sell the owner's shares. The pause cancels the house's resting sell."""
    wide, owner_fill = (
        Quote("99.50", "100.05", bid_size="2"),
        Quote("99.50", "100.01", bid_size="2"),
    )
    rising = [Quote(f"{D('99.52') + D('0.02') * i}", "100.05", bid_size="2") for i in range(10)]
    script = [Order(0, "10"), Order(4, "5", price="100.05", owner=True)]
    t = tape_run([FLAT] + [wide] * 3 + [owner_fill] + rising, script, NO_CHASE)
    assert _sold(t) == 2 and t.net == 13  # no sell fill after the owner's 5 landed
    # The owner's working BUY beside the resting sell freezes first (C1, ADR-0007:19), then its
    # fill is the add; either way the house's sell is canceled before the venue resizes it.
    assert t.paused and t.pages == ["chase_unavailable", "foreign_order", "owner_add"]
    assert t.status["owner-1"] == "FILLED" and t.status["engine-SELL"] == "CANCELED"


def test_a_resting_sell_with_the_chase_unavailable_pages() -> None:
    """#211 part 1: with the chase rows unavailable (#98) the sell rests at the breach bid and never
    follows the price, so a person is paged. The control's chase sells out."""
    thin_low = Quote("99.50", "99.52", bid_size="2")
    falling = [
        Quote(f"{D('99.48') - D('0.02') * i}", f"{D('99.50') - D('0.02') * i}") for i in range(20)
    ]
    t = tape_run([FLAT] * 5 + [thin_low] * 3 + falling, [Order(0, "10")], NO_CHASE)
    assert _sold(t) == 2 and t.net == 8
    assert t.pages == ["chase_unavailable"] and not t.paused
    control = tape_run([FLAT] * 5 + [thin_low] * 3 + falling, [Order(0, "10")], FIXTURE)
    assert control.net == 0 and control.pages == []


def test_outside_rth_a_stale_bid_never_prices_the_exit() -> None:
    """#211 part 2, ADR-0005 X2: a quote needs age <= quote_max_age_s on every path that prices
    the exit. One quote at second 0, then only falling prints; the breach persists at second 6."""
    items: list[Quote | Trade] = [Quote("100.00", "100.02")] + [Trade("100.02")] * 3
    items += [Trade(f"{D('99.70') - D('0.10') * i}") for i in range(12)]
    t = tape_run(items, [Order(0, "10")], session="outside", start=PRE)
    assert not [e for e in t.events if e["event"].startswith("breach_sell")]
    assert t.pages == ["awaiting_quote"] and t.net == 10


def test_outside_rth_a_zero_bid_never_prices_the_exit() -> None:
    """#211 part 2: a one-sided quote (bid 0.00) never prices the sell; it was denied
    PRICE_NOT_POSITIVE and then held with no retry and no page."""
    items: list[Quote | Trade] = [Quote("100.00", "100.02")] + [Trade("100.02")] * 3
    items += [Quote("0.00", "100.02", bid_size="0")]
    items += [Trade(f"{D('99.70') - D('0.10') * i}") for i in range(10)]
    t = tape_run(items, [Order(0, "10")], NO_CHASE, session="outside", start=PRE)
    assert "engine-SELL" not in t.status
    assert t.pages == ["awaiting_quote"] and t.net == 10


def test_a_stale_quote_at_the_entry_never_anchors_the_crossing() -> None:
    """The dsh review at f320927 (5817797458, #264): an anchor takes a bid only when the quote
    passes `_quote_ok` (ADR-0005:27; northstar's `quote_fresh`, exit_manager/strategy.py:2165-2173).
    The 2.10 bid is 2 s old (starts' age limit is 1 s) when the one share fills at 2.03, so the
    entry bid is unknown. A fresh 2.00 bid then puts entry - buffer, 2.0097, in the market, and
    with no entry bid it is never a crossing: it pages, and nothing sells."""
    items: list[Quote | Trade] = [Quote("2.10", "2.12")] + [Trade("2.03")] * 3
    items += [Quote("2.00", "2.02")] * 8
    t = tape_run(items, [Order(2, "1", price="2.03")], STARTS)
    assert t.net == 1 and _sold(t) == 0 and t.pages == ["quote_unavailable", "trigger_in_market"]


def test_a_stale_quote_at_a_new_high_never_anchors_the_raise() -> None:
    """#264, dsh's own case: the 102.00 bid is 7 s old (the age limit is 5 s) when prints make H
    100.50, then 101.00, so H's bid is unknown, and the raise is judged against the fresh 100.70
    bid. H minus the trail, 100.80, is above that bid, so the trigger stays put. With the stale bid
    as H's bid, `cap = max(100.70, 102.00)` raised the trigger into the bid, and the bid sold."""
    items: list[Quote | Trade] = [Trade("100.00"), Quote("102.00", "102.02")]
    items += [Trade("100.00")] * 6 + [Trade("100.50"), Trade("101.00")]
    items += [Quote("100.70", "100.72")] * 10
    t = tape_run(items, [Order(0, "1", price="100.02")])  # one share: each print fills one
    assert t.net == 1 and _sold(t) == 0
    assert not any(e["event"].startswith("breach_sell") for e in t.events)


def test_a_stale_quote_at_a_minute_close_never_confirms_arming() -> None:
    """X3 (ADR-0005:29): an unavailable quote stays unarmed, and the bar's arming level takes its
    noise floor from the spread, so a stale quote cannot set it. The quotes stop at 49 s and the
    minute closes at 60 s with the last quote 11 s old (starts' limit is 1 s), so that close
    confirms nothing, and fresh quotes from 63 s arm nothing before the next minute."""
    items: list[Quote | Trade] = [Quote("5.00", "5.01")]
    items += [Quote("5.06", "5.07"), Trade("5.06")] * 24 + [Trade("5.06")] * 14
    items += [Quote("5.06", "5.07"), Trade("5.06")] * 15
    t = tape_run(items, [Order(0, "10")], STARTS)
    assert "armed" not in _kinds_of(t) and _sold(t) == 0 and t.net == 10


def test_a_one_sided_rth_quote_is_never_a_breach_observation() -> None:
    """The RTH breach input is the bid only from a quote that passes `_quote_ok` (#264's class).
    With the trigger set at 99.81996, four one-sided quotes (bid 0.00) are no breach run, so no
    crossing is retained, and the fresh bids at 100.00 that follow sell nothing. Counted as
    breaches, they retained a crossing that sold all 10 on the first fresh bid."""
    one_sided = Quote("0.00", "100.02", bid_size="0")
    t = tape_run([FLAT, FLAT] + [one_sided] * 4 + [FLAT] * 3, [Order(0, "10")])
    assert "crossed" not in _kinds_of(t) and _sold(t) == 0 and t.net == 10


def test_a_locked_quote_is_valid_and_anchors_the_crossing() -> None:
    """ADR-0005:27 aligned with its own pin (lead ruling, 2026-11-08): a quote needs
    0 < bid <= ask, so a locked quote is valid, as northstar's `quote_fresh` reads it
    (exit_manager/strategy.py:2171). #98's replay opens each entry on one
    (exit_econ_98.py:153-156). The entry fills on a locked 100.00/100.00 quote, so the entry bid
    is 100.00, and the bid falls to 98.00 before starts' first print: the level, 99.00, was below
    the entry bid, so the fall is a crossing and the persisted bids sell."""
    crash = Quote("98.00", "98.02")
    items = [Quote("100.00", "100.00"), crash, crash, Trade("98.01")] + [crash] * 4
    t = tape_run(items, [Order(0, "10")], STARTS)
    assert "trigger_in_market" not in t.pages and _sold(t) == 10 and t.net == 0


def test_a_crossed_quote_is_never_valid_and_never_anchors() -> None:
    """The other side of the pin's rule: a crossed quote (bid above ask) fails 0 < bid <= ask, so
    the entry filled on a 100.04/100.02 quote has no entry bid. The same fall to 98.00 is then
    never a crossing: the level pages `trigger_in_market`, and nothing sells."""
    crash = Quote("98.00", "98.02")
    items = [Quote("100.04", "100.02"), crash, crash, Trade("98.01")] + [crash] * 4
    t = tape_run(items, [Order(0, "10")], STARTS)
    assert "trigger_in_market" in t.pages and _sold(t) == 0 and t.net == 10


def test_a_denied_managed_sell_pauses_and_pages() -> None:
    """#211: a denied or rejected managed sell is never left as the exit with no page. RiskEngine's
    submit throttle (one order per 10 s) denies the sell 5 s after the entry."""
    risk = RiskEngineConfig(bypass=False, max_order_submit_rate="1/00:00:10")
    t = tape_run([FLAT] * 3 + [LOW] * 6, [Order(0, "10")], risk=risk)
    assert t.status["engine-SELL"] == "DENIED"
    assert t.paused and t.pages == ["sell_refused"] and t.net == 10


def test_an_owner_resting_sell_freezes_the_symbol_instead_of_a_second_exit() -> None:
    """#212, ADR-0007:18-19: an owner SELL LIMIT 10 @ 100.50 reserves the 10. A foreign open order
    freezes the symbol and pages; the house never adds a second full-size exit."""
    up = Quote("100.50", "100.52")
    owner_tp = Order(1, "10", side=OrderSide.SELL, price="100.50", owner=True)
    t = tape_run([FLAT] * 3 + [LOW] * 4 + [up] * 3, [Order(0, "10"), owner_tp])
    assert _sold(t, owner=False) == 0 and t.net == 0  # only the owner's own sell: never short
    # The owner's fill left the account flat with every order terminal, which clears the pause.
    assert t.pages == ["foreign_order"] and not t.paused


def test_an_owner_resting_buy_at_the_house_sell_fails_closed_with_a_page() -> None:
    """A2, Alpaca User Protection (read 2026-11-07): a SELL LIMIT at or below an opposite-side
    resting BUY LIMIT is refused with HTTP 403, in paper too. The owner's BUY is never canceled,
    so the house never sends that sell: the symbol freezes and pages, never a silent hold."""
    owner_bid = Order(1, "5", price="99.50", owner=True)  # rests: the ask stays above it
    t = tape_run([FLAT] * 3 + [LOW] * 4, [Order(0, "10"), owner_bid])
    assert "engine-SELL" not in t.status and t.net == 10
    assert t.status["owner-1"] == "ACCEPTED"  # untouched
    assert t.paused and t.pages == ["foreign_order"]


def test_a_close_with_a_foreign_order_still_working_keeps_the_pause() -> None:
    """#171's other side: only a verified flat clears a pause. The breach freezes on the owner's
    resting BUY; the owner then sells the 10 flat, but that BUY still works, so the symbol stays
    paused and the house never re-arms."""
    owner_bid = Order(1, "5", price="99.00", owner=True)
    owner_sells = Order(8, "10", side=OrderSide.SELL, owner=True)
    t = tape_run([FLAT] * 3 + [LOW] * 7, [Order(0, "10"), owner_bid, owner_sells])
    assert t.net == 0 and "flat" in [e["event"] for e in t.events]
    assert t.paused and t.pages == ["foreign_order"] and t.status["owner-1"] == "ACCEPTED"


def test_a_level_at_the_bid_is_refused_pages_and_is_set_once_the_bid_moves_up() -> None:
    """#210 cause 2, a lead ruling at the boundary of two sourced rules: a $2 entry at the 2.03 ask
    with a 0.03 spread puts entry - buffer on the unchanged 2.00 bid. rc8 rejects a stop already
    in the market (matching_engine/mod.rs:4311-4330) and investor.gov enters a sell stop below the
    market, so the level is refused and pages, and nothing sells. A tick up sets it."""
    q, up = Quote("2.00", "2.03"), Quote("2.01", "2.03")
    t = tape_run([q, Trade("2.03")] + [q] * 8 + [up] * 3, [Order(0, "10")], STARTS)
    assert _sold(t) == 0 and t.net == 10 and t.pages == ["trigger_in_market"]
    (first,) = [e for e in t.events if e["event"] == "initial_trigger"]
    assert first["ts"] == str(START + 10 * NS) and D(first["trigger"]) < D("2.01")


def test_a_level_the_bid_already_crossed_sells_after_persistence() -> None:
    """ADR-0005:26 governs the other side of that boundary: starts' range is unknown until a print,
    and the bid falls through entry - buffer before it. The level is set strictly above the bid,
    and the persisted breach (X4: three bids over 1 s) sells; nothing sells at once."""
    crash = Quote("98.00", "98.02")
    t = tape_run([FLAT, crash, crash, Trade("98.01")] + [crash] * 4, [Order(0, "10")], STARTS)
    (first,) = [e for e in t.events if e["event"] == "initial_trigger"]
    assert first["ts"] == str(START + 4 * NS) and D(first["trigger"]) > D("98.00")
    (sell,) = [e for e in t.events if e["event"].startswith("breach_sell")]
    assert sell["ts"] == str(START + 6 * NS) and t.net == 0 and t.pages == ["chase_unavailable"]


def test_a_level_above_the_entry_bid_is_never_a_crossing_when_the_bid_falls() -> None:
    """The dsh review at 9b0c6dd (5817618864, P1): a fall since the entry is not a fall through the
    level. M1's setup: the entry fills at the 2.03 ask over a 2.00 bid, and entry - buffer is
    2.0097, already in the market at the entry. When the bid then falls to 1.99, the level was
    never placeable (rc8 rejects a stop already in the market, and investor.gov enters a sell stop
    below the market), so it is refused and pages, and nothing sells on it."""
    entry, rest, fall = Quote("2.00", "2.03"), Quote("2.00", "2.02"), Quote("1.99", "2.01")
    t = tape_run([entry, Trade("2.03")] + [rest] * 3 + [fall] * 8, [Order(0, "10")], STARTS)
    assert _sold(t) == 0 and t.net == 10 and t.pages == ["trigger_in_market"]
    assert "initial_trigger" not in _kinds_of(t)


def test_a_level_on_the_entry_bid_is_never_a_crossing_when_the_bid_falls() -> None:
    """The same P1 at its boundary: with a 0.03 spread, entry - buffer sits on the 2.00 entry bid,
    which rc8 already counts as in the market (a SELL stop matches at market <= stop,
    crates/execution/src/matching.rs:426-437). A fall to 1.99 does not make it placeable at the
    entry, so it is refused and pages, and nothing sells."""
    q, fall = Quote("2.00", "2.03"), Quote("1.99", "2.02")
    t = tape_run([q, Trade("2.03")] + [q] * 3 + [fall] * 8, [Order(0, "10")], STARTS)
    assert _sold(t) == 0 and t.net == 10 and t.pages == ["trigger_in_market"]
    assert "initial_trigger" not in _kinds_of(t)


def test_a_bid_that_falls_exactly_to_a_placeable_level_has_crossed_it() -> None:
    """The other edge: a level the entry bid was above has crossed once the bid is at it, as
    northstar's exit manager counts a stop crossed at reference <= stop (northstar-trading@8256c16c
    strategies/exit_manager/strategy.py:1731-1733) and rc8 matches at market <= stop. The entry
    fills at 100.00 over a 99.99 bid, and the bid falls to 99.00 before starts' first print makes
    the level known: entry - buffer is exactly 99.00, so it is set on the bid, and the persisted
    bids at it sell."""
    at = Quote("99.00", "99.02")
    items = [Quote("99.99", "100.00"), at, at, Trade("99.01")] + [at] * 4
    t = tape_run(items, [Order(0, "10")], STARTS)
    (first,) = [e for e in t.events if e["event"] == "initial_trigger"]
    assert D(first["trigger"]) == D("99.00") and "trigger_in_market" not in t.pages
    assert _sold(t) == 10 and t.net == 0


def test_a_level_in_the_market_with_no_entry_bid_is_never_a_crossing() -> None:
    """With the entry filled before any quote, nothing shows the trigger started below the market,
    so a first level at or above the first bid is refused and pages, and nothing sells: the one
    share fills on the 100.00 print, entry - buffer is 99.00, and the first quotes bid 98.00."""
    items: list[Quote | Trade] = [Trade("100.00")] + [Quote("98.00", "98.02")] * 8
    t = tape_run(items, [Order(0, "1", price="100.02")], STARTS)
    assert t.net == 1 and _sold(t) == 0 and t.pages == ["trigger_in_market"]
    assert "initial_trigger" not in _kinds_of(t)


def test_a_lock_raised_onto_the_unchanged_bid_is_refused_in_both_sessions() -> None:
    """#210 cause 2's third path (rc8 update_stop_market_order, mod.rs:6774-6812, refuses a modify
    into the market): the lock arms below a flat 5.06/5.07 quote; one print at the ask raises H to
    5.07, so H - spread lands on the 5.06 bid. The raise is refused against the bid in both
    sessions, though outside RTH the breach input stays the trade."""
    items: list[Quote | Trade] = [Quote("5.00", "5.01")]
    items += [Quote("5.06", "5.07"), Trade("5.06")] * 35
    items += [Quote("5.06", "5.07"), Trade("5.07")]
    items += [Quote("5.06", "5.07"), Trade("5.06")] * 30
    for session, start in (("rth", START), ("outside", PRE)):
        t = tape_run(items, [Order(0, "10")], STARTS, session=session, start=start)
        assert "armed" in [e["event"] for e in t.events]
        assert _sold(t) == 0 and t.net == 10, session


def test_a_raise_made_while_the_bid_followed_the_high_stands_through_a_fast_drop() -> None:
    """The other side of #210's raise rule (lead ruling): a raise that lands in the market only
    because the bid fell after the high is a real drop, not a spike the bid never followed. The
    print at 100.50 comes with the bid at 100.48, so the raise to 100.29996 stands, and the bid's
    fall to 100.20 is a persisted breach (X4) that sends the exit."""
    up, drop = Quote("100.48", "100.50"), Quote("100.20", "100.22")
    t = tape_run([FLAT] * 3 + [up, Trade("100.50")] + [drop] * 4, [Order(0, "10")])
    (sell,) = [e for e in t.events if e["event"].startswith("breach_sell")]
    assert D(sell["trigger"]) == D("100.29996") and sell["ts"] == str(START + 7 * NS)


def test_outside_rth_an_unknown_bid_keeps_the_previous_level_until_the_bid_recovers() -> None:
    """Lead ruling with #211: a zero or stale bid can't judge a level, so it is unknown, never "in
    the market". The level set at second 1 stands while the bid is 0.00 and prints rise; the
    persisted trade breach then pages once, awaiting a quote, and the fresh quote at second 9
    sends the exit itself, never a later print (O5, M2)."""
    items: list[Quote | Trade] = [Quote("100.00", "100.02"), Trade("100.02")]
    items += [Quote("0.00", "100.02", bid_size="0")]
    items += [Trade(p) for p in ("100.30", "100.50", "99.70", "99.60", "99.50", "99.45")]
    items += [Quote("99.40", "99.42"), Trade("99.40"), Quote("99.40", "99.42")]
    t = tape_run(items, [Order(0, "10")], session="outside", start=PRE)
    (first,) = [e for e in t.events if e["event"] == "initial_trigger"]
    (sell,) = [e for e in t.events if e["event"].startswith("breach_sell")]
    assert sell["trigger"] == first["trigger"]  # never raised by the prints at 100.30-100.50
    assert int(sell["ts"]) == PRE + 9 * NS and t.pages == ["awaiting_quote"]


def test_outside_rth_no_level_is_set_against_an_unknown_bid_and_it_pages_once() -> None:
    """Never refuse every level against a zero bid, and never set one from it: with no level yet,
    a one-sided quote pages quote_unavailable once and the level is set when the bid returns."""
    items: list[Quote | Trade] = [Quote("100.00", "100.02"), Quote("0.00", "100.02", bid_size="0")]
    items += [Trade("100.02")] * 3 + [Quote("100.00", "100.02"), Trade("100.02")]
    t = tape_run(items, [Order(0, "10")], session="outside", start=PRE)
    assert t.pages == ["quote_unavailable"] and t.net == 10
    (first,) = [e for e in t.events if e["event"] == "initial_trigger"]
    assert int(first["ts"]) == PRE + 6 * NS


def test_outside_rth_a_resting_sell_is_never_repriced_from_a_stale_bid() -> None:
    """#211: the chase reprices only from a quote within quote_max_age_s (5 s here). The bid shows
    no size, so the sell rests whatever its collar. The quote at second 6 reprices it at second 7;
    from second 12 that quote is stale, so the sell keeps its price and a person is paged."""
    items: list[Quote | Trade] = [Quote("100.00", "100.02"), Trade("100.02")]
    items += [Quote("99.40", "99.42", bid_size="0")]
    items += [Trade(p) for p in ("99.70", "99.65", "99.60")]
    items += [Quote("99.20", "99.22", bid_size="0")]
    items += [Trade(p) for p in ("99.15", "99.10", "99.05", "99.00", "98.95", "98.90")]
    t = tape_run(items, [Order(0, "10")], session="outside", start=PRE)
    chases = [int(e["ts"]) for e in t.events if e["event"] == "chase"]
    # One reprice, from the fresh quote at second 6: at that quote (a bid-only collar) or at the
    # next print (max(bid, last x (1 - cap))), never once the quote is stale.
    assert len(chases) == 1 and PRE + 6 * NS <= chases[0] <= PRE + 7 * NS
    assert t.pages == ["awaiting_quote"]


def _handover(items: list[Quote | Trade], session: str, start: int) -> Tape:
    return tape_run(items, [Order(0, "10")], session=session, start=start)


def test_an_outside_exit_hands_over_at_0930_by_a_terminal_cancel() -> None:
    """ADR-0005 venue limits, "terminal cancel precedes handover", on sextant.paper.sessions' XNYS
    clock: a pre-market exit rests (the bid shows no size, the prints sit below it) and chases from
    09:29:45. At 09:30:00 the engine switches to bids, cancels that sell and waits until it is
    terminal; only then does the RTH exit go out. The pre-market sell is never repriced after
    09:30."""
    items: list[Quote | Trade] = [Quote("100.00", "100.02")]
    for i in range(1, 40):
        px = D("99.80") - D("0.01") * i
        bid, ask = px + D("0.30"), px + D("0.50")
        items.append(Trade(f"{px}") if i % 2 else Quote(f"{bid}", f"{ask}", bid_size="0"))
    t = _handover(items, "outside", START - 20 * NS)  # 09:29:40; second 20 is 09:30:00
    pre = [(s, e) for s, n, e in t.timeline if n == "engine-SELL"]
    rth = [(s, e) for s, n, e in t.timeline if n == "engine-SELL-2"]
    assert max(s for s, e in pre if e == "OrderUpdated") < 20 and (20, "OrderCanceled") in pre
    assert min(s for s, e in rth if e == "OrderSubmitted") >= 20


def test_a_rejected_cancel_goes_out_again_on_the_clock_never_waiting_for_a_quote() -> None:
    """PR 2's GPT gate F1: a rejected cancel goes out again without waiting for a fresh quote.
    #214 round 6 times that re-send on the clock, 5 s after the order's last cancel request, as
    northstar's cancel-first wait does (northstar-trading@8256c16c strategies/base.py:101,
    :1728-1754, :2186-2189; ADR-0007:27 bounds it). So house-2's cancel goes out again at 20, not
    at its acceptance at 17 as PR 2's next-event retry sent it. Outside RTH the last quote is at
    second 12 and only prints follow: the crossing's cancel at 15 reaches the venue before house-2
    does and is rejected, and the re-send at 20, with no quote since 12, cancels it. The exit
    itself then waits for a fresh quote, as it must, and pages."""
    latency = StaticLatencyModel(insert_latency_nanos=6 * NS, cancel_latency_nanos=400_000_000)
    items: list[Quote | Trade] = [FLAT] * 12 + [LOW] + [Trade("99.50")] * 75
    script = [Order(0, "10", price="100.02"), Order(11, "5", price="99.00")]
    t = tape_run(items, script, session="outside", start=PRE, latency=latency)
    retries = [int(e["ts"]) - PRE for e in t.events if e["event"] == "cancel_retry"]
    assert _cancels(t) == [15, 20] and retries == [20 * NS] and t.status["house-2"] == "CANCELED"
    assert "awaiting_quote" in t.pages and t.net == 10


def test_a_new_high_before_the_first_trigger_keeps_the_entry_bid_as_its_anchor() -> None:
    """PR 2's GPT gate F2: the first level's "has the bid fallen" test is anchored on the bid at
    the entry, never on a later H's bid. The bid falls from 100.00 to 98.00, then a print at
    100.03 makes a new H before any trigger exists; the fall is real, so the level is set and the
    persisted breach sells."""
    items: list[Quote | Trade] = [FLAT, Quote("98.00", "100.05"), Trade("100.03")]
    items += [Quote("98.00", "98.02")] * 8
    t = tape_run(items, [Order(0, "10", price="100.02")], STARTS)
    assert "initial_trigger" in _kinds_of(t) and _sold(t) == 10 and t.net == 0


def test_a_later_handover_cancel_never_trips_the_original_deadline() -> None:
    """#231's GPT delta gate N1: the 60-second deadline belongs to the crossing's own reservations
    and to an exit still owed with nothing working; a later close is not an original reservation
    (northstar-trading ADR-0002:366-372). The crossing sells at second 5 before the open; at 09:30
    the hand-off cancels that sell with 20 s latency, spanning the old alert at second 65. No
    timeout is paged, and the replacement exit goes out on the terminal cancel at second 75."""
    start = START - 55 * NS
    low = Quote("99.40", "99.42", bid_size="0")
    items: list[Quote | Trade] = [FLAT, Trade("100.02"), low] + [Trade("99.50")] * 3 + [low] * 125
    late = StaticLatencyModel(cancel_latency_nanos=20 * NS)
    t = tape_run(items, [Order(0, "10")], session="outside", start=start, latency=late)
    sells = [(int(e["ts"]) - start) // NS for e in t.events if e["event"].startswith("breach_sell")]
    assert sells == [5, 75] and "partial_entry_cancel_timeout" not in t.pages


# #231's GPT delta gate N2: a house SELL resting before the crossing is an original reservation.
RESTING_SELL = Order(1, "5", side=OrderSide.SELL, price="101.00")


def _deadline_tape(items: Sequence[Quote | Trade], entry: Order) -> tuple[Tape, list, list]:
    late = StaticLatencyModel(cancel_latency_nanos=100 * NS)
    t = tape_run(items, [entry, RESTING_SELL], latency=late)
    pages = [(e["reason"], (int(e["ts"]) - START) // NS) for e in t.events if e["event"] == "page"]
    sells = [(int(e["ts"]) - START) // NS for e in t.events if e["event"].startswith("breach_sell")]
    return t, pages, sells


def test_an_original_house_sell_beside_the_remainder_keeps_the_deadline() -> None:
    """#231's GPT delta gate N2: the deadline pages while any original reservation still works;
    only a later close is exempt (northstar-trading ADR-0002:366-372). Six of ten fill, and a
    house SELL of five rests from second 1, before the crossing at second 3. Both cancels take
    100 s, so the timeout pages at 63, and the exit goes out only once both end, at 103."""
    thin, wide = Quote("100.00", "100.02", ask_size="6"), Quote("99.50", "100.55")
    t, pages, sells = _deadline_tape([thin] + [wide] * 110, Order(0, "10", price="100.50"))
    assert (103, "house-2", "OrderCanceled") in t.timeline
    assert pages == [("partial_entry_cancel_timeout", 63)] and sells == [103] and t.net == 0


def test_an_original_house_sell_alone_keeps_the_deadline() -> None:
    """#231's GPT delta gate N2, with the entry filled: the resting house SELL alone is still an
    original reservation, so its 100 s cancel pages the timeout 60 s after the crossing at 5."""
    t, pages, sells = _deadline_tape([FLAT] * 3 + [Quote("99.50", "100.55")] * 110, Order(0, "10"))
    assert (105, "house-2", "OrderCanceled") in t.timeline
    assert pages == [("partial_entry_cancel_timeout", 65)] and sells == [105] and t.net == 0


def test_a_handed_over_exit_that_ended_leaves_the_owed_exit_paging() -> None:
    """Only a working later close is exempt from the deadline: once the handed-over exit has
    ended, the exit is owed with nothing working, and the deadline still pages (F1). The crossing
    sells at second 5 before the open; at 09:30 the hand-off cancels that sell, which ends at 56.
    The last quote, at 50, is stale by then, so the exit waits, the timeout pages at 65, and the
    first fresh quote, at 70, sends it again."""
    start = START - 55 * NS
    low = Quote("99.40", "99.42", bid_size="0")
    items: list[Quote | Trade] = [FLAT, Trade("100.02"), low] + [Trade("99.50")] * 3 + [low] * 45
    items += [Trade("99.50")] * 19 + [low] * 10
    late = StaticLatencyModel(cancel_latency_nanos=1 * NS)
    t = tape_run(items, [Order(0, "10")], session="outside", start=start, latency=late)
    pages = [(e["reason"], (int(e["ts"]) - start) // NS) for e in t.events if e["event"] == "page"]
    sells = [(int(e["ts"]) - start) // NS for e in t.events if e["event"].startswith("breach_sell")]
    assert (56, "engine-SELL", "OrderCanceled") in t.timeline and sells == [5, 70]
    assert pages == [("awaiting_quote", 56), ("partial_entry_cancel_timeout", 65)]


def _freeze_then_handover(
    owner_at: int,
    insert_s: int,
    *,
    owner_price: str = "90.00",
    wake_at: int | None = None,
    cancel_ns: int = 400_000_000,
) -> Tape:
    """#231's GPT delta gate D1 tape (6719461061). Pre-market, the house sells its 10 at second 39;
    an owner BUY at `owner_at` freezes the symbol, so the house cancels its own sell; XNYS opens
    at second 42, and the hand-off reaches that sell while its cancel is still pending."""
    start = START - 42 * NS
    low = Quote("99.40", "99.42", bid_size="0")
    items: list[Quote | Trade] = [FLAT] * 35 + [Trade("100.02"), low]
    items += [Trade("99.50")] * 3 + [low] * 100
    if wake_at is not None:  # a displayed bid that can fill a still-working house sell
        items[wake_at] = Quote("99.60", "100.05", bid_size="20")
    script = [Order(0, "10"), Order(owner_at, "1", price=owner_price, owner=True)]
    latency = StaticLatencyModel(insert_latency_nanos=insert_s * NS, cancel_latency_nanos=cancel_ns)
    return tape_run(items, script, session="outside", start=start, latency=latency)


def test_a_fill_before_the_first_quote_never_raises_the_trigger_into_the_bid() -> None:
    """The required dsh review at 18eef6f (5817265821): with the entry filled before any quote and
    H made by prints before one, no bid is known at H. A raise leg is then judged against the
    current bid, as rc8 rejects a stop modified into the market and keeps the old one (crates/
    execution/src/matching_engine/mod.rs:6774-6812). The one-share entry fills on the first
    print at 100.00, prints make H 101.00, and the first quote bids 100.70: H minus the trail
    is above that bid, so the trigger stays put, and the bid never sells on noise."""
    items: list[Quote | Trade] = [Trade("100.00"), Trade("100.50"), Trade("101.00")]
    items += [Quote("100.70", "100.72")] * 10
    t = tape_run(items, [Order(0, "1", price="100.02")])  # one share: each print fills one
    triggers = [D(e["trigger"]) for e in t.events if e["event"] == "initial_trigger"]
    assert t.net == 1 and _sold(t) == 0 and triggers and triggers[0] < D("100.70")
    assert not any(e["event"].startswith("breach_sell") for e in t.events)


def _b_adopted_above_the_bid() -> object:
    """B's adoption path with no bid known at H, after test_owner_b_sim's
    `outside_before_any_quote`: outside RTH the owner's entry fills on prints at 100.00, and B
    adopts on a print at 101.00, before any quote, so H is 101.00 and `high_bid` stays unset.
    Quotes then bid 100.70, and prints at 100.75 are the outside-RTH observations."""
    from nautilus_trader.config import StrategyConfig

    from sextant.backtest.owner_b_witness import B_FIXTURE, BASE, USD
    from sextant.backtest.owner_b_witness import EQUITY as B_EQUITY
    from sextant.exits import policy
    from sextant.exits.owner_b import adopt
    from sextant.exits.owner_b_sim import BManager, BManagerConfig

    config = BManagerConfig(
        instrument_id=B_EQUITY.id,
        params=FIXTURE,
        round_trip_cost=D("0.01"),
        session="outside",
        b_params=B_FIXTURE,
        owner_order_ids=("owner-entry",),
    )
    manager = BManager(config)

    class Owner(Strategy):
        def __init__(self, config: StrategyConfig) -> None:
            super().__init__(config)
            self.entry: D | None = None
            self.filled_ns = 0

        def on_start(self) -> None:
            self.subscribe_trades(B_EQUITY.id)

        def on_trade(self, trade: TradeTick) -> None:
            if not self.cache.orders():
                order = self.order_factory.limit(
                    B_EQUITY.id,
                    OrderSide.BUY,
                    Quantity.from_str("10"),
                    Price.from_str("100.02"),
                    time_in_force=TimeInForce.DAY,
                    client_order_id=ClientOrderId("owner-entry"),
                )
                self.submit_order(order)
            elif self.entry is not None and manager.protection is None:
                buffer = policy.buffer(D("0.01"), D("0.02"), self.entry, None, FIXTURE)
                assert buffer is not None
                adoption = adopt(
                    entry=self.entry,
                    mark=trade.price.as_decimal(),
                    quantity=D(10),
                    owner_reserved=D(0),
                    buffer=buffer,
                    filled_ns=self.filled_ns,
                    now_ns=trade.ts_event,
                    reconciled=True,
                    claim_max_latency_s=B_FIXTURE.claim_max_latency_s,
                )
                manager.adopt_position(adoption, total_quantity=D(10))

        def on_order_filled(self, event: OrderFilled) -> None:
            self.entry, self.filled_ns = event.last_px.as_decimal(), event.ts_event

    def print_at(px: str, ns: int) -> TradeTick:
        size = Quantity.from_str("100")
        return TradeTick(
            B_EQUITY.id, Price.from_str(px), size, AggressorSide.SELL, TradeId(str(ns)), ns, ns
        )

    data: list = [
        print_at(px, BASE + i * NS) for i, px in enumerate(["100.00", "100.00", "101.00"])
    ]
    data += [
        QuoteTick(B_EQUITY.id, Price.from_str("100.70"), Price.from_str("100.72"),
                  Quantity.from_str("100"), Quantity.from_str("100"), at, at)
        for at in (BASE + i * NS + NS // 2 for i in range(3, 7))
    ]  # fmt: skip
    data += [print_at("100.75", BASE + 7 * NS + k * 200_000_000) for k in range(5)]
    engine = BacktestEngine(BacktestEngineConfig(logging=LoggerConfig(bypass_logging=True)))
    engine.add_venue(
        Venue("SIM"),
        OmsType.NETTING,
        AccountType.MARGIN,
        [Money(1_000_000, USD)],
        base_currency=USD,
        fee_model=MakerTakerFeeModel(maker_rate=D(0), taker_rate=D(0)),
        latency_model=StaticLatencyModel(base_latency_nanos=200_000_000),
        use_reduce_only=False,
        liquidity_consumption=True,
    )
    engine.add_instrument(B_EQUITY)
    engine.add_data(data)
    owner = Owner(StrategyConfig())
    engine.add_strategy(owner)
    engine.add_strategy(manager)
    try:
        engine.run()
        assert owner.entry is not None and manager.protection is not None
        return manager
    finally:
        engine.dispose()


def test_a_b_adoption_with_no_bid_at_h_never_raises_the_trigger_into_the_bid() -> None:
    """The dsh review's B case: adopting before any quote, `adopt_position` has no bid to record,
    so `high_bid` stays unset and the raise is judged against the current bid, as rc8 keeps the
    old stop when a modify would put it in the market
    (crates/execution/src/matching_engine/mod.rs:6774-6812). B adopts at 101.00 with no quote, the
    bid is 100.70, and prints at 100.75 follow: H minus the trail is above that bid, so B's
    trigger stays below the bid and the prints are no breach."""
    manager = _b_adopted_above_the_bid()
    assert manager.protection.trigger < D("100.70")  # type: ignore[attr-defined]
    assert "persisted_breach" not in [e["event"] for e in manager.events]  # type: ignore[attr-defined]


def _b_adopted_after_its_bid() -> object:
    """B's adoption with its bid known at H, in a fixed order. In RTH the owner's entry fills at
    100.02, and B adopts on the print at 102.00 one nanosecond after the 102.00 bid, so the manager
    already holds that bid. (The B witness adopts on the quote itself, which rc8 delivers to
    equal-priority strategies in handler-id order, `<ptr>-<uuid4>`, so the order varies by process:
    crates/common/src/msgbus/typed_handler.rs:269-273, typed_router.rs:64-70.) The bid then falls
    to 101.70."""
    from nautilus_trader.config import StrategyConfig

    from sextant.backtest.owner_b_witness import B_FIXTURE, BASE, USD
    from sextant.backtest.owner_b_witness import EQUITY as B_EQUITY
    from sextant.exits import policy
    from sextant.exits.owner_b import adopt
    from sextant.exits.owner_b_sim import BManager, BManagerConfig

    manager = BManager(
        BManagerConfig(
            instrument_id=B_EQUITY.id,
            params=FIXTURE,
            round_trip_cost=D("0.01"),
            session="rth",
            b_params=B_FIXTURE,
            owner_order_ids=("owner-entry",),
        )
    )

    class Owner(Strategy):
        def __init__(self, config: StrategyConfig) -> None:
            super().__init__(config)
            self.entry: D | None = None
            self.filled_ns = 0

        def on_start(self) -> None:
            self.subscribe_trades(B_EQUITY.id)

        def on_trade(self, trade: TradeTick) -> None:
            if not self.cache.orders():
                self.submit_order(
                    self.order_factory.limit(
                        B_EQUITY.id,
                        OrderSide.BUY,
                        Quantity.from_str("10"),
                        Price.from_str("100.02"),
                        time_in_force=TimeInForce.DAY,
                        client_order_id=ClientOrderId("owner-entry"),
                    )
                )
            elif self.entry is not None and manager.protection is None:
                buffer = policy.buffer(D("0.01"), D("0.02"), self.entry, None, FIXTURE)
                assert buffer is not None
                adoption = adopt(
                    entry=self.entry,
                    mark=trade.price.as_decimal(),
                    quantity=D(10),
                    owner_reserved=D(0),
                    buffer=buffer,
                    filled_ns=self.filled_ns,
                    now_ns=trade.ts_event,
                    reconciled=True,
                    claim_max_latency_s=B_FIXTURE.claim_max_latency_s,
                )
                manager.adopt_position(adoption, total_quantity=D(10))

        def on_order_filled(self, event: OrderFilled) -> None:
            self.entry, self.filled_ns = event.last_px.as_decimal(), event.ts_event

    size = Quantity.from_str("100")
    data: list = [
        QuoteTick(B_EQUITY.id, Price.from_str(bid), Price.from_str(f"{D(bid) + D('0.02'):.2f}"),
                  size, size, BASE + i * NS, BASE + i * NS)
        for i, bid in enumerate(["100.00", "100.00", "102.00", "101.70"])
    ]  # fmt: skip
    data += [  # the claim stays inside B_FIXTURE's 2 s claim latency
        TradeTick(B_EQUITY.id, Price.from_str(px), size, AggressorSide.BUY, TradeId(str(t)), t, t)
        for px, t in (("100.00", BASE + 1), ("102.00", BASE + 2 * NS + 1))
    ]  # fmt: skip
    engine = BacktestEngine(BacktestEngineConfig(logging=LoggerConfig(bypass_logging=True)))
    engine.add_venue(
        Venue("SIM"),
        OmsType.NETTING,
        AccountType.MARGIN,
        [Money(1_000_000, USD)],
        base_currency=USD,
        fee_model=MakerTakerFeeModel(maker_rate=D(0), taker_rate=D(0)),
        latency_model=StaticLatencyModel(base_latency_nanos=200_000_000),
        use_reduce_only=False,
        liquidity_consumption=True,
    )
    engine.add_instrument(B_EQUITY)
    engine.add_data(sorted(data, key=lambda d: d.ts_init))
    owner = Owner(StrategyConfig())
    engine.add_strategy(owner)
    engine.add_strategy(manager)
    try:
        engine.run()
        assert owner.entry is not None and manager.protection is not None
        return manager
    finally:
        engine.dispose()


def test_a_b_adoption_after_its_bid_judges_the_raise_against_that_bid() -> None:
    """The dsh review's B case with the bid known at H: B's adoption records the bid at H as the
    engine's fill path does (engine.py:260-261), so a raise is judged against it (M3) in either
    delivery order. B adopts at 102.00 holding a 102.00 bid, and the bid falls to 101.70: H minus
    the trail is below the bid at H, so B's trigger rises above 101.70. With the bid left unset,
    the raise was judged against 101.70 and dropped whenever the manager took the adoption's quote
    first, so the B witness's breach came 6 s late in about one process in three."""
    manager = _b_adopted_after_its_bid()
    assert manager.protection.trigger > D("101.70")  # type: ignore[attr-defined]


def _b_adopted_on_a_stale_quote() -> object:
    """B's adoption with the manager's last quote stale. In RTH the owner's entry fills at 100.02,
    the bid shows 102.00 at 2 s, and no quote follows until 8 s. B adopts on the print at 101.00
    at 7.5 s, when that bid is 5.5 s old (the age limit is 5 s). The fixture's claim latency is
    widened to 10 s so the adoption is admitted that late. Fresh bids at 100.70 follow at 8 s and
    9 s, two observations, fewer than X4's three, so nothing sells."""
    import dataclasses as dc

    from nautilus_trader.config import StrategyConfig

    from sextant.backtest.owner_b_witness import B_FIXTURE, BASE, USD
    from sextant.backtest.owner_b_witness import EQUITY as B_EQUITY
    from sextant.exits import policy
    from sextant.exits.owner_b import adopt
    from sextant.exits.owner_b_sim import BManager, BManagerConfig

    b_params = dc.replace(B_FIXTURE, claim_max_latency_s=D(10))
    manager = BManager(
        BManagerConfig(
            instrument_id=B_EQUITY.id,
            params=FIXTURE,
            round_trip_cost=D("0.01"),
            session="rth",
            b_params=b_params,
            owner_order_ids=("owner-entry",),
        )
    )

    class Owner(Strategy):
        def __init__(self, config: StrategyConfig) -> None:
            super().__init__(config)
            self.entry: D | None = None
            self.filled_ns = 0

        def on_start(self) -> None:
            self.subscribe_trades(B_EQUITY.id)

        def on_trade(self, trade: TradeTick) -> None:
            if not self.cache.orders():
                self.submit_order(
                    self.order_factory.limit(
                        B_EQUITY.id,
                        OrderSide.BUY,
                        Quantity.from_str("10"),
                        Price.from_str("100.02"),
                        time_in_force=TimeInForce.DAY,
                        client_order_id=ClientOrderId("owner-entry"),
                    )
                )
            elif self.entry is not None and manager.protection is None:
                buffer = policy.buffer(D("0.01"), D("0.02"), self.entry, None, FIXTURE)
                assert buffer is not None
                adoption = adopt(
                    entry=self.entry,
                    mark=trade.price.as_decimal(),
                    quantity=D(10),
                    owner_reserved=D(0),
                    buffer=buffer,
                    filled_ns=self.filled_ns,
                    now_ns=trade.ts_event,
                    reconciled=True,
                    claim_max_latency_s=b_params.claim_max_latency_s,
                )
                manager.adopt_position(adoption, total_quantity=D(10))

        def on_order_filled(self, event: OrderFilled) -> None:
            self.entry, self.filled_ns = event.last_px.as_decimal(), event.ts_event

    size = Quantity.from_str("100")
    bids = [(0, "100.00"), (NS, "100.00"), (2 * NS, "102.00")]
    bids += [(8 * NS, "100.70"), (9 * NS, "100.70")]
    data: list = [
        QuoteTick(B_EQUITY.id, Price.from_str(bid), Price.from_str(f"{D(bid) + D('0.02'):.2f}"),
                  size, size, BASE + t, BASE + t)
        for t, bid in bids
    ]  # fmt: skip
    data += [
        TradeTick(B_EQUITY.id, Price.from_str(px), size, AggressorSide.BUY, TradeId(str(t)), t, t)
        for px, t in (("100.00", BASE + 1), ("101.00", BASE + 7 * NS + NS // 2))
    ]  # fmt: skip
    engine = BacktestEngine(BacktestEngineConfig(logging=LoggerConfig(bypass_logging=True)))
    engine.add_venue(
        Venue("SIM"),
        OmsType.NETTING,
        AccountType.MARGIN,
        [Money(1_000_000, USD)],
        base_currency=USD,
        fee_model=MakerTakerFeeModel(maker_rate=D(0), taker_rate=D(0)),
        latency_model=StaticLatencyModel(base_latency_nanos=200_000_000),
        use_reduce_only=False,
        liquidity_consumption=True,
    )
    engine.add_instrument(B_EQUITY)
    engine.add_data(sorted(data, key=lambda d: d.ts_init))
    owner = Owner(StrategyConfig())
    engine.add_strategy(owner)
    engine.add_strategy(manager)
    try:
        engine.run()
        assert owner.entry is not None and manager.protection is not None
        return manager
    finally:
        engine.dispose()


def test_a_b_adoption_on_a_stale_quote_never_anchors_the_raise() -> None:
    """#264's B case: B's adoption takes H's bid only from a quote that passes `_quote_ok`
    (ADR-0005:27; northstar's `quote_fresh`), as the engine's fill does. B adopts at 101.00 while
    its last bid, 102.00, is stale, so H's bid is unknown and the raise is judged against the fresh
    100.70 bid. H minus the trail, 100.79996, is above that bid, so B's trigger stays below it.
    With the stale bid as H's bid, `cap = max(100.70, 102.00)` raised the trigger into the bid."""
    manager = _b_adopted_on_a_stale_quote()
    assert manager.protection.high_bid is None  # type: ignore[attr-defined]
    assert manager.protection.trigger < D("100.70")  # type: ignore[attr-defined]


def test_a_handover_joins_the_freezes_pending_cancel_so_the_owner_add_is_never_sold() -> None:
    """D1, custody (ADR-0007:17; AGENTS.md custody line): the hand-off at 42 joins the cancel the
    freeze already sent at 40 instead of requesting again, as northstar's throttle refuses a
    second request before it records one (strategies/base.py:1744-1749) and rc8 sends nothing
    for an order already pending cancel (crates/trading/src/strategy/mod.rs:818-828). So the
    re-send stays 5 s after the real request, at 45, and lands; the owner's 1 fills at 47 and the
    bid at 49 finds no house sell. A request time moved to 42 once sent it at 47, too late, and
    the house sold all 11, the owner's add included."""
    t = _freeze_then_handover(40, 7, owner_price="100.02", wake_at=49, cancel_ns=3 * NS)
    sells = [s for s, n, e in t.timeline if n == "engine-SELL" and e == "OrderPendingCancel"]
    assert sells == [40, 45] and t.status["engine-SELL"] == "CANCELED"
    assert _sold(t) == 0 and t.net == 11


def test_a_handover_after_a_freeze_never_spends_a_fifth_cancel() -> None:
    """D1, the bound (ADR-0007:27, K+1 = 4 cancels per order): with the freeze's cancel rejected
    before the hand-off, a second request at 42 once opened a second re-send chain, so cancels
    went out at 40, 42, 45, 47 and 50, one past the bound. Joined, there is one chain: 40, 45, 50
    and 55, and the last cancels the sell once it rests at 53."""
    t = _freeze_then_handover(40, 14)
    sells = [s for s, n, e in t.timeline if n == "engine-SELL" and e == "OrderPendingCancel"]
    assert sells == [40, 45, 50, 55] and t.status["engine-SELL"] == "CANCELED"
