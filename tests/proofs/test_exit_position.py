"""R86 (#129 §4 item 1): the exit engine protects the native position, not its first fill.

Offline BacktestEngine witnesses on scripted quotes (sextant.backtest.exit_position_witness). The
fixture's 100.02 entry has an initial trigger of 99.81996 (buffer 0.002 x entry), so bids of 99.50
breach it, and three of them over 2 s persist (ADR-0005 X4).
"""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal as D

from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggerConfig, RiskEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType,
    AggressorSide,
    Money,
    OmsType,
    OrderFilled,
    OrderSide,
    Price,
    Quantity,
    QuoteTick,
    TimeInForce,
    TradeId,
    TradeTick,
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
    """ADR-0007:17: an owner add to a strategy-held symbol pauses it and pages."""
    r = run([FLAT] * 5 + [LOW] * 6, [Buy(0, "10"), Buy(2, "5")])
    assert len({c for c, _q, _p in r.buy_fills}) == 2
    assert r.paused and r.pages == ["owner_add"]
    assert _kinds(r).count("add_paused") == 1
    assert r.sells == [] and r.position == 15  # paused: the later breach sells nothing


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


@dataclass(frozen=True)
class Tape:
    events: list[dict[str, str]]
    pages: list[str]
    paused: bool
    fills: list[tuple[int, str, str, str, bool]]  # (second, side, qty, price, owner)
    status: dict[str, str]  # each order's final status, keyed "house-1", "owner-1", ...
    net: D
    timeline: list[tuple[int, str, str]]  # (second, order, native event), each order's in order


class Scripted(ExitEngine):
    script: tuple[Order, ...] = ()

    def on_start(self) -> None:
        super().on_start()
        self.seen = 0
        self.owner_ids: set[str] = set()
        self.names: dict[str, str] = {}

    def on_quote(self, quote: QuoteTick) -> None:
        for o in (o for o in self.script if o.at == self.seen):
            ref = quote.ask_price if o.side == OrderSide.BUY else quote.bid_price
            price = ref if o.price is None else Price.from_str(o.price)
            qty = Quantity.from_str(o.qty)
            order = self.order_factory.limit(
                EQUITY.id, o.side, qty, price, time_in_force=TimeInForce.GTC
            )
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


def _tick(i: int, item: Quote | Trade) -> QuoteTick | TradeTick:
    ts = START + i * NS
    if isinstance(item, Trade):
        price, size = Price.from_str(item.price), Quantity.from_str("1")
        return TradeTick(EQUITY.id, price, size, AggressorSide.BUY, TradeId(str(i)), ts, ts)
    bid, ask = Price.from_str(item.bid), Price.from_str(item.ask)
    sizes = Quantity.from_str(item.bid_size), Quantity.from_str(item.ask_size)
    return QuoteTick(EQUITY.id, bid, ask, *sizes, ts, ts)


def tape_run(
    items: Sequence[Quote | Trade],
    script: Sequence[Order],
    params: ExitParams = FIXTURE,
    *,
    session: str = "rth",
    risk: RiskEngineConfig | None = None,
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
        )
        engine.add_instrument(EQUITY)
        engine.add_data([_tick(i, item) for i, item in enumerate(items)])
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
        )
    finally:
        engine.dispose()


STARTS = ExitParams.starts()


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
    # The breach persisted at second 3; the remainder's cancel was terminal there, and the sell went
    # out on the next bid (ADR-0005:36: the crossing is retained exit intent, not permission).
    assert (3, "house-1", "OrderCanceled") in t.timeline
    assert next(x for x in t.timeline if x[1] == "engine-SELL")[0] == 4
    assert [e["ts"] for e in t.events if e["event"] == "breach_sell_prearm"] == [
        str(START + 4 * NS)
    ]


def test_a_crossing_is_retained_through_a_rebound_while_the_remainder_cancels() -> None:
    """ADR-0005:36: a price rebound cannot clear the crossing's exit intent. The breach persists at
    second 3 and the remainder's cancel goes out; the bid rebounds above the trigger at second 4,
    and the house still sells its 6 there, once the remainder is terminal."""
    thin = Quote("100.00", "100.02", ask_size="6")
    wide, rebound = Quote("99.50", "100.55"), Quote("100.00", "100.55")
    t = tape_run([thin] + [wide] * 3 + [rebound] * 3, [Order(0, "10", price="100.50")])
    assert [(s, q, p) for _t, s, q, p, _o in t.fills] == [
        ("BUY", "6", "100.02"),
        ("SELL", "6", "100.00"),
    ]
    assert t.status == {"house-1": "CANCELED", "engine-SELL": "FILLED"} and t.net == 0


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
