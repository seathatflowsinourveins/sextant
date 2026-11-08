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
    over it. The chase is off (#98). Each later bid moves up through the resting limit, because an
    L1 maker fill needs a market move (fill-prices-and-matching.md, "L1 books"); each move fills the
    bid's displayed 2."""
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
    assert not r.paused and r.pages == []


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
        self.seen += 1
        super().on_trade(trade)

    def on_order_canceled(self, event) -> None:  # type: ignore[override]
        if event.client_order_id not in self.external:
            super().on_order_canceled(event)


def _tick(i: int, item: Quote | Trade, quote_delay_ns: int = 0) -> QuoteTick | TradeTick:
    """Item `i` is received at second i; a quote's event can precede its receipt by the delay."""
    ts = START + i * NS
    if isinstance(item, Trade):
        price, size = Price.from_str(item.price), Quantity.from_str("1")
        return TradeTick(EQUITY.id, price, size, AggressorSide.BUY, TradeId(str(i)), ts, ts)
    bid, ask = Price.from_str(item.bid), Price.from_str(item.ask)
    sizes = Quantity.from_str(item.bid_size), Quantity.from_str(item.ask_size)
    return QuoteTick(EQUITY.id, bid, ask, *sizes, ts - quote_delay_ns, ts)


def tape_run(
    items: Sequence[Quote | Trade],
    script: Sequence[Order],
    params: ExitParams = FIXTURE,
    *,
    session: str = "rth",
    risk: RiskEngineConfig | None = None,
    latency: StaticLatencyModel | None = None,
    quote_delay_ns: int = 0,
) -> Tape:
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
        engine.add_data([_tick(i, item, quote_delay_ns) for i, item in enumerate(items)])
        strategy = Scripted(
            ExitEngineConfig(
                instrument_id=EQUITY.id,
                params=params,
                round_trip_cost=D("0.01"),
                session=session,
            )
        )
        strategy.script = tuple(script)
        engine.add_strategy(strategy)
        engine.run()
        orders = engine.cache.orders(instrument_id=EQUITY.id)
        fills = sorted(
            (
                (e.ts_event - START) // NS,
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
        name = {
            o.client_order_id: strategy.names.get(str(o.client_order_id), f"engine-{o.side.name}")
            for o in orders
        }
        status = {name[o.client_order_id]: o.status.name for o in orders}
        timeline = sorted(
            (
                ((e.ts_event - START) // NS, name[o.client_order_id], type(e).__name__)
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


STARTS = ExitParams.starts()


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
    """ADR-0007:16-17: cancel acts only on house orders. An owner BUY LIMIT rests below the market
    while the breach persists; the house exit never cancels it."""
    owner_bid = Order(1, "5", price="99.00", owner=True)
    t = tape_run([FLAT] * 3 + [LOW] * 4, [Order(0, "10"), owner_bid])
    assert _sold(t, owner=False) == 10
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


@pytest.mark.parametrize("delay_ns", [0, 1, NS, 6 * NS])
def test_the_re_send_waits_5_s_of_engine_clock_however_late_the_quote(delay_ns: int) -> None:
    """The #214 GPT delta gate at c76c77b: a re-send waits 5 s from the cancel's actual request,
    on the engine's clock, as northstar's throttle reads `self._now()` (strategies/base.py:711,
    :1743), never from the quote's own event time. A quote that arrives `delay_ns` after its
    event once brought the re-send 5 s minus that delay after the request."""
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
    """The deadline escalates an exit the engine still owes and manages. An owner add pauses the
    symbol while the remainder's 10 s cancel is in flight; that pause has paged a person, so at
    60 s the deadline adds no page of its own."""
    thin, wide = Quote("100.00", "100.02", ask_size="6"), Quote("99.50", "100.55")
    late = StaticLatencyModel(cancel_latency_nanos=10_000_000_000)
    t = tape_run(
        [thin] + [wide] * 70,
        [Order(0, "10", price="100.50"), Order(4, "5", owner=True)],
        latency=late,
    )
    assert t.status["house-1"] == "CANCELED" and t.pages == ["owner_add"] and _sold(t) == 0


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
    unfinished. The owner sells the 6 that filled while the remainder's 100 s cancel is pending;
    the remainder's 4 then fill late and reopen the position. The crossing is still owed, so those
    4 are sold at once, never protected afresh with a new trigger."""
    thin, wide = Quote("100.00", "100.02", ask_size="6"), Quote("99.50", "100.55")
    back = Quote("100.40", "100.50")  # the ask touches the remainder's limit
    late = StaticLatencyModel(cancel_latency_nanos=100 * NS)
    owner_sells_6 = Order(4, "6", side=OrderSide.SELL, owner=True)
    t = tape_run(
        [thin] + [wide] * 4 + [back] * 75,
        [Order(0, "10", price="100.50"), owner_sells_6],
        latency=late,
    )
    protected = [e for e in t.events if e["event"] == "protected_from_fill"]
    (sell,) = [e for e in t.events if e["event"].startswith("breach_sell")]
    assert t.status["house-1"] == "FILLED" and sell["qty"] == "4" and t.net == 0
    assert (
        len(protected) == 2 and "initial_trigger" not in _kinds_of(t)[_kinds_of(t).index("flat") :]
    )


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
    flat; its 5 then fill and reopen the position. They are sold, never protected afresh."""
    wide, back = Quote("99.50", "100.55"), Quote("100.40", "100.50")
    late = StaticLatencyModel(cancel_latency_nanos=100 * NS)
    items = [FLAT] * 2 + [Quote("100.00", "100.55")] + [wide] * 4 + [back] * 75
    script = [
        Order(0, "10"),
        Order(2, "5", price="100.50"),
        Order(6, "10", side=OrderSide.SELL, owner=True),
    ]
    t = tape_run(items, script, latency=late)
    (sell,) = [e for e in t.events if e["event"].startswith("breach_sell")]
    assert t.status["house-2"] == "FILLED" and sell["qty"] == "5" and t.net == 0
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
    """D1's unpaused side: the owner sells the 6 flat while the remainder's cancel is pending; it
    ends at second 6 with nothing left owed, so the 60 s deadline never pages."""
    t = _kept_cycle(
        [Order(0, "10", price="100.50"), Order(4, "6", side=OrderSide.SELL, owner=True)]
    )
    assert t.status["house-1"] == "CANCELED" and t.net == 0 and t.pages == []


def test_a_reservation_whose_cancel_is_rejected_after_a_close_keeps_its_exit_owed() -> None:
    """The #214 GPT delta gate at 34bff6b: a rejected cancel must not erase a reservation's
    identity (northstar ADR-0002:354-366, a cancel rejection cannot clear that intent). The
    owner's SELL closes the position at second 10 while house-2's cancel, which reached the venue
    before house-2 did, is rejected; house-2 then lands and fills 5 at second 13. Those 5 belong to
    the crossing and are sold, never protected afresh with a new trigger."""
    t = _rejected_then_filled()
    rejected = [e for _s, n, e in t.timeline if n == "house-2"].count("OrderCancelRejected")
    (sell,) = [e for e in t.events if e["event"].startswith("breach_sell")]
    assert rejected >= 1 and t.status["house-2"] == "FILLED" and sell["qty"] == "5"
    assert "initial_trigger" not in _kinds_of(t)[_kinds_of(t).index("flat") :] and t.net == 0


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
    house-2 lands and fills at 13, before its re-send falls due at 14, so no cancel goes out again
    and the crossing still sells its 5."""
    t = _rejected_then_filled()
    (sell,) = [e for e in t.events if e["event"].startswith("breach_sell")]
    assert _cancels(t) == [9] and _retries(t) == [] and t.status["house-2"] == "FILLED"
    assert sell["qty"] == "5" and t.net == 0
