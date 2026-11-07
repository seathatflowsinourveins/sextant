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
from nautilus_trader.execution import MakerTakerFeeModel, StaticLatencyModel
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


@dataclass(frozen=True)
class Tape:
    events: list[dict[str, str]]
    pages: list[str]
    paused: bool
    fills: list[tuple[int, str, str, str, bool]]  # (second, side, qty, price, owner)
    status: dict[str, str]  # each order's final status, keyed "house-1", "owner-1", ...
    net: D
    timeline: list[tuple[int, str, str]]  # (second, order, native event), each order's in order


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

    def on_quote(self, quote: QuoteTick) -> None:
        for o in (o for o in self.script if o.at == self.seen):
            ref = quote.ask_price if o.side == OrderSide.BUY else quote.bid_price
            price = ref if o.price is None else Price.from_str(o.price)
            qty = Quantity.from_str(o.qty)
            trigger = TriggerType.BID_ASK if o.emulated else None
            order = self.order_factory.limit(
                EQUITY.id,
                o.side,
                qty,
                price,
                time_in_force=TimeInForce.GTC,
                emulation_trigger=trigger,
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


def _tick(start: int, i: int, item: Quote | Trade) -> QuoteTick | TradeTick:
    ts = start + i * NS
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
    latency: StaticLatencyModel | None = None,
    start: int = START,
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
        engine.add_data([_tick(start, i, item) for i, item in enumerate(items)])
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
        )
    finally:
        engine.dispose()


NO_CHASE = dataclasses.replace(FIXTURE, chase_cap_fraction=None, chase_min_interval_s=None)
STARTS = ExitParams.starts()
PRE = START - 3600 * NS  # 08:30 ET, pre-market (sextant.paper.sessions)


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


def test_outside_rth_the_terminal_cancel_sends_the_exit_without_waiting_for_a_print() -> None:
    """Outside RTH only a print steps the engine, and prints can be minutes apart. The remainder's
    terminal cancel itself sends the retained exit (a #169 review finding)."""
    thin, wide = Quote("100.00", "100.02", ask_size="6"), Quote("99.40", "100.55")
    items: list[Quote | Trade] = [thin, Trade("100.02"), wide] + [Trade("99.50")] * 3
    items += [wide] * 30  # quotes only: no print after the crossing
    t = tape_run(items, [Order(0, "10", price="100.50")], session="outside")
    crossed = next(e for e in t.events if e["event"] == "crossed")
    (sell,) = [e for e in t.events if e["event"].startswith("breach_sell")]
    assert sell["ts"] == crossed["ts"]


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
    assert t.pages == ["owner_add"]  # two adds, one page
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
    assert t.paused and t.pages == ["chase_unavailable", "owner_add"]
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
    persisted trade breach then pages once, awaiting a quote, and nothing sells until one comes."""
    items: list[Quote | Trade] = [Quote("100.00", "100.02"), Trade("100.02")]
    items += [Quote("0.00", "100.02", bid_size="0")]
    items += [Trade(p) for p in ("100.30", "100.50", "99.70", "99.60", "99.50", "99.45")]
    items += [Quote("99.40", "99.42"), Trade("99.40"), Quote("99.40", "99.42")]
    t = tape_run(items, [Order(0, "10")], session="outside", start=PRE)
    (first,) = [e for e in t.events if e["event"] == "initial_trigger"]
    (sell,) = [e for e in t.events if e["event"].startswith("breach_sell")]
    assert sell["trigger"] == first["trigger"]  # never raised by the prints at 100.30-100.50
    assert int(sell["ts"]) == PRE + 10 * NS and t.pages == ["awaiting_quote"]


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
    """#211: the chase reprices only from a quote within quote_max_age_s (5 s here). The last quote
    is at second 2; the sell rests above it from second 5 and follows the prints until second 7.
    From second 8 the quote is stale, so the sell keeps its price and a person is paged."""
    items: list[Quote | Trade] = [Quote("100.00", "100.02"), Trade("100.02")]
    items += [Quote("99.40", "99.42")] + [Trade(p) for p in ("99.70", "99.65", "99.60", "99.55")]
    items += [Trade(p) for p in ("99.50", "99.45", "99.40", "99.35")]
    t = tape_run(items, [Order(0, "10")], session="outside", start=PRE)
    chases = [int(e["ts"]) for e in t.events if e["event"] == "chase"]
    assert chases and max(chases) == PRE + 7 * NS and t.pages == ["awaiting_quote"]


def _handover(items: list[Quote | Trade], session: str, start: int) -> Tape:
    return tape_run(items, [Order(0, "10")], session=session, start=start)


def test_an_outside_exit_hands_over_at_0930_by_a_terminal_cancel() -> None:
    """ADR-0005 venue limits, "terminal cancel precedes handover", on sextant.paper.sessions' XNYS
    clock: a pre-market exit rests and chases on prints from 09:29:45. At 09:30:00 the engine
    switches to bids, cancels that sell and waits until it is terminal; only then does the RTH exit
    go out. The pre-market sell is never repriced after 09:30."""
    items: list[Quote | Trade] = [Quote("100.00", "100.02")]
    for i in range(1, 40):
        px = D("99.80") - D("0.01") * i
        items.append(Trade(f"{px}") if i % 2 else Quote(f"{px - D('0.40')}", f"{px + D('0.20')}"))
    t = _handover(items, "outside", START - 20 * NS)  # 09:29:40; second 20 is 09:30:00
    pre = [(s, e) for s, n, e in t.timeline if n == "engine-SELL"]
    rth = [(s, e) for s, n, e in t.timeline if n == "engine-SELL-2"]
    assert max(s for s, e in pre if e == "OrderUpdated") < 20 and (20, "OrderCanceled") in pre
    assert min(s for s, e in rth if e == "OrderSubmitted") >= 20 and t.net == 0
