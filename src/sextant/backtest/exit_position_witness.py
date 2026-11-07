"""R86 witnesses (#129): the exit engine protects the native position, not its first fill.

One offline NautilusTrader BacktestEngine run (nautechsystems/nautilus_trader@v2.0.0rc7
55c0e82053142bce3a5cba4de4221d3929c2d3bc) per scripted equity quote path. The venue sets
`liquidity_consumption=True`, so each fill is bounded by a quote's displayed size:
docs/concepts/backtesting/fill-prices-and-matching.md:9 and :153-170. A resting LIMIT entry for
10 against asks of size 6 therefore fills 6, then 4 on the next quote, at its limit price. A
MARKET entry fills its residual one tick worse (the same file, "L1 books"), which gives one order
two fill prices. The path shape is the rc7 probe that #129's reconciliation cites (§4 item 1,
U6), rerun here.

The script submits house BUY orders at given quotes, and `sextant.exits.engine.ExitEngine` does
the rest. There is no network, broker or key. These are mechanism witnesses, not merit: the data
are synthetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggerConfig, RiskEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType,
    Currency,
    Equity,
    InstrumentId,
    Money,
    OmsType,
    OrderFilled,
    OrderSide,
    PositionChanged,
    PositionClosed,
    PositionOpened,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    TimeInForce,
    Venue,
)

from sextant.backtest.exit_witness import FIXTURE
from sextant.exits.engine import ExitEngine, ExitEngineConfig
from sextant.exits.policy import ExitParams

NS = 1_000_000_000
START = 1_793_975_400 * NS
USD = Currency.from_str("USD")
EQUITY = Equity(
    instrument_id=InstrumentId.from_str("PTEST.SIM"),
    raw_symbol=Symbol("PTEST"),
    currency=USD,
    price_precision=2,
    price_increment=Price.from_str("0.01"),
    lot_size=Quantity.from_str("1"),
    ts_event=0,
    ts_init=0,
)


@dataclass(frozen=True)
class Quote:
    bid: str
    ask: str
    bid_size: str = "100"
    ask_size: str = "100"


@dataclass(frozen=True)
class Buy:
    """A house BUY submitted on quote `at`: a LIMIT at that quote's ask, or a MARKET order."""

    at: int
    qty: str
    market: bool = False


@dataclass(frozen=True)
class Result:
    events: list[dict[str, str]]
    pages: list[str]
    paused: bool
    calls: list[str]
    buy_fills: list[tuple[str, str, str]]
    sells: list[tuple[str, str, str]]
    buy_avg_px: dict[str, Decimal]
    position: Decimal
    max_working_sells: int


class ScriptedEntry(ExitEngine):
    """House entries from a script; every fill after that belongs to the exit engine.

    rc7's native `Strategy.__new__` takes only the config, so the script is set after construction.
    """

    def __init__(self, config: ExitEngineConfig) -> None:
        super().__init__(config)
        self.buys: tuple[Buy, ...] = ()
        self.seen = 0
        self.calls: list[str] = []
        self.max_working_sells = 0

    def on_quote(self, quote: QuoteTick) -> None:
        for buy in (b for b in self.buys if b.at == self.seen):
            qty = Quantity.from_str(buy.qty)
            if buy.market:
                order = self.order_factory.market(EQUITY.id, OrderSide.BUY, qty)
            else:
                order = self.order_factory.limit(
                    EQUITY.id, OrderSide.BUY, qty, quote.ask_price, time_in_force=TimeInForce.DAY
                )
            self.submit_order(order)
        self.seen += 1
        super().on_quote(quote)
        self._count_sells()

    def on_order_filled(self, event: OrderFilled) -> None:
        self.calls.append("filled_buy" if event.order_side == OrderSide.BUY else "filled_sell")
        super().on_order_filled(event)
        self._count_sells()

    def on_position_opened(self, event: PositionOpened) -> None:
        self.calls.append("position_opened")
        super().on_position_opened(event)
        self._count_sells()

    def on_position_changed(self, event: PositionChanged) -> None:
        self.calls.append("position_changed")
        super().on_position_changed(event)
        self._count_sells()

    def on_position_closed(self, event: PositionClosed) -> None:
        self.calls.append("position_closed")
        super().on_position_closed(event)
        self._count_sells()

    def _count_sells(self) -> None:
        working = [
            o for o in self.cache.orders_open(instrument_id=EQUITY.id) if o.side == OrderSide.SELL
        ]
        self.max_working_sells = max(self.max_working_sells, len(working))


def tape(quotes: list[Quote]) -> list[QuoteTick]:
    return [
        QuoteTick(
            EQUITY.id,
            Price.from_str(q.bid),
            Price.from_str(q.ask),
            Quantity.from_str(q.bid_size),
            Quantity.from_str(q.ask_size),
            START + i * NS,
            START + i * NS,
        )
        for i, q in enumerate(quotes)
    ]


def run(quotes: list[Quote], buys: list[Buy], params: ExitParams = FIXTURE) -> Result:
    """The venue enforces reduce-only, so a fill resizes a resting reduce-only order to the
    position (docs/concepts/orders/advanced.md:228-231)."""
    engine = BacktestEngine(
        BacktestEngineConfig(
            logging=LoggerConfig(bypass_logging=True),
            risk_engine=RiskEngineConfig(bypass=False),
        )
    )
    try:
        engine.add_venue(
            venue=Venue("SIM"),
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            starting_balances=[Money(1_000_000, USD)],
            base_currency=USD,
            fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
            use_reduce_only=True,
            liquidity_consumption=True,
        )
        engine.add_instrument(EQUITY)
        engine.add_data(tape(quotes))
        strategy = ScriptedEntry(
            ExitEngineConfig(
                instrument_id=EQUITY.id,
                params=params,
                round_trip_cost=Decimal("0.01"),
                session="rth",
            )
        )
        strategy.buys = tuple(buys)
        engine.add_strategy(strategy)
        engine.run()
        orders = engine.cache.orders(instrument_id=EQUITY.id)
        timed = [
            (e.ts_event, str(e.client_order_id), e.order_side, e.last_qty, e.last_px)
            for o in orders
            for e in o.events()
            if isinstance(e, OrderFilled)
        ]
        timed.sort(key=lambda f: f[0])  # stable: one order's fills keep their own order
        fills = [(c, s, q.as_decimal(), p.as_decimal()) for _t, c, s, q, p in timed]
        bought = sum((q for _c, s, q, _p in fills if s == OrderSide.BUY), Decimal(0))
        sold = sum((q for _c, s, q, _p in fills if s == OrderSide.SELL), Decimal(0))
        return Result(
            events=list(strategy.events),
            pages=list(getattr(strategy, "pages", [])),
            paused=strategy.paused,
            calls=list(strategy.calls),
            buy_fills=[(c, str(q), str(p)) for c, s, q, p in fills if s == OrderSide.BUY],
            sells=[
                (str(o.client_order_id), str(o.quantity), str(o.filled_qty))
                for o in orders
                if o.side == OrderSide.SELL
            ],
            buy_avg_px={
                str(o.client_order_id): o.avg_px
                for o in orders
                if o.side == OrderSide.BUY and o.avg_px is not None
            },
            position=bought - sold,
            max_working_sells=strategy.max_working_sells,
        )
    finally:
        engine.dispose()
