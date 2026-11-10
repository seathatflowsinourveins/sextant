"""C-lane decision-core witnesses: a synthetic flag, one LIMIT BUY, one RTH trail.

These receipts exercise the pure session slice only. There is no stream, broker
client, account or network here; the event clock, baseline and order sink are
injected so the same state machine can later sit behind the paper runner.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from nautilus_trader.model import (
    AggressorSide,
    Currency,
    Equity,
    InstrumentId,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    TradeId,
    TradeTick,
)

from sextant.entry.orders import limit_price
from sextant.entry.parameters import EntryParameters
from sextant.execution.alpaca import OrderCommand
from sextant.execution.custody import OrderFact
from sextant.paper.c_session import CConfig, CSession
from sextant.ranking.baseline import BaselineSample, BaselineTable
from sextant.ranking.engine import Segment

ROOT = Path(__file__).parents[2]
NS = 1_000_000_000
SEC = NS
START = 1_793_088_000 * SEC
DAY = date(2026, 10, 27)
AAA = InstrumentId.from_str("AAA.ALPACA")
BBB = InstrumentId.from_str("BBB.ALPACA")


def equity(iid: InstrumentId) -> Equity:
    return Equity(
        iid,
        Symbol(str(iid.symbol)),
        Currency.from_str("USD"),
        2,
        Price.from_str("0.01"),
        0,
        0,
        lot_size=Quantity.from_int(1),
    )


def segment(name: str) -> Segment:
    return Segment(name, DAY, START, START + 600 * SEC, "fixture XNYS boundary")


def baseline(*symbols: str, session: str = "RTH") -> BaselineTable:
    samples: list[BaselineSample] = []
    for symbol in symbols:
        samples.append(BaselineSample(symbol, session, "2026-10-26", 0, D(0), D(0)))
        samples.append(BaselineSample(symbol, session, "2026-10-26", 600, D(600), D(60)))
    return BaselineTable(
        tuple(samples),
        "fixture explicit complete curve; linear within minute",
        START - SEC,
        "sip",
    )


def registry_rows() -> list[dict]:
    return json.loads((ROOT / "lanes/sim/entry-parameters.json").read_text())


def reviewed_params() -> EntryParameters:
    return EntryParameters.from_rows(registry_rows(), first_leg_only=True)


FIXTURE_VALUES: dict[str, object] = {
    "first_leg_window_s": "120",
    "first_leg_trades_count": 3,
    "first_leg_span_s": "1",
    "first_leg_max_move": "0.10",
    "entry_max_vwap_extension_atr": "2",
    "entry_chase_bps": "10",
    "entry_ttl_s": "5",
    "reclaim_lookback_s": "30",
    "reclaim_trades_count": 3,
    "reclaim_trades_span_s": "1",
    "reclaim_hold_s": "2",
    "reclaim_max_above_buffers": "1",
    "atr_period": 3,
    "atr_bar_minutes": 1,
    "max_data_age_s": "5",
    "max_armed_symbols": 5,
    "bp_target_fraction": "1",
    "stop_ref_fraction": "0.01",
    "portfolio_slots": 5,
    "stopout_size_decay": "0.5",
    "stopout_size_floor": "0.25",
    "confidence_size_floor": "0.5",
    "chase_cap_fraction": "0.01",
    "flow_share_cap": "0.05",
    "flow_share_window_s": "60",
    "covered_flow_window_s": "2",
    "covered_flow_baseline_min": "1",
    "covered_flow_ratio": "1",
}


def fixture_params() -> EntryParameters:
    rows = [
        {
            "name": name,
            "unit": "count" if type(value) is int else "fixture unit",
            "value": value,
            "source": "ADR-0004; TEST ONLY, no deployment authority",
            "calibration": "UNCALIBRATED",
            "last_change": "2026-11-06",
            "scope": "FIXTURE_ONLY",
        }
        for name, value in FIXTURE_VALUES.items()
    ]
    return EntryParameters.from_rows(rows, fixture=True)


class Clock:
    def __init__(self) -> None:
        self.value = START

    def __call__(self) -> int:
        return self.value

    def at(self, seconds: int | str) -> None:
        self.value = START + int(D(str(seconds)) * SEC)


@dataclass
class Harness:
    session: CSession
    clock: Clock
    submitted: list[OrderCommand] = field(default_factory=list)
    config: CConfig | None = None


def make_harness(
    *iids: InstrumentId,
    segment_name: str = "RTH",
    slot_count: int = 2,
    params: EntryParameters | None = None,
    chase: str = "0.03",
) -> Harness:
    subscribed = iids or (AAA,)
    instruments: dict[str, Equity] = {str(iid): equity(iid) for iid in subscribed}
    config = CConfig(
        symbols=tuple(str(iid) for iid in subscribed),
        chase_cap_fraction=D(chase),
        trail_fraction=D("0.025"),
        slot_count=slot_count,
        segment=segment(segment_name),
        params=params if params is not None else reviewed_params(),
    )
    submitted: list[OrderCommand] = []
    clock = Clock()
    session = CSession(
        config,
        baseline(*(str(iid.symbol) for iid in subscribed), session=segment_name),
        clock,
        submitted.append,
        instruments=instruments,
    )
    return Harness(session=session, clock=clock, submitted=submitted, config=config)


def trade(seconds: int | str, price: str, *, iid: InstrumentId = AAA, size: int = 100) -> TradeTick:
    ts = START + int(D(str(seconds)) * SEC)
    return TradeTick(
        iid,
        Price.from_str(price),
        Quantity.from_int(size),
        AggressorSide.NO_AGGRESSOR,
        TradeId(f"{iid.symbol}-{ts}"),
        ts,
        ts,
    )


def quote(
    seconds: int | str,
    bid: str,
    ask: str,
    *,
    iid: InstrumentId = AAA,
) -> QuoteTick:
    ts = START + int(D(str(seconds)) * SEC)
    return QuoteTick(
        iid,
        Price.from_str(bid),
        Price.from_str(ask),
        Quantity.from_int(100),
        Quantity.from_int(100),
        ts,
        ts,
    )


def warm_to_quote(h: Harness, iids: tuple[InstrumentId, ...] = (AAA,)) -> None:
    """Feed the surge30 warm-up through the 32 s quote, but not the flag print."""
    for seconds, price, size in (
        (0, "1.0000", 100),
        (25, "1.0100", 100),
        (26, "1.0100", 100),
        (30, "1.0000", 100),
        (31, "1.0300", 500),
        (32, "1.0400", 500),
    ):
        h.clock.at(seconds)
        for iid in iids:
            h.session.on_trade(trade(seconds, price, iid=iid, size=size))
    h.clock.at(32)
    for iid in iids:
        h.session.on_quote(quote(32, "1.0400", "1.0600", iid=iid))


def flag(h: Harness, iids: tuple[InstrumentId, ...] = (AAA,)) -> None:
    """The 33 s print that completes the qualifying surge30 flag."""
    h.clock.at(33)
    for iid in iids:
        h.session.on_trade(trade(33, "1.0500", iid=iid, size=500))


def warm(h: Harness, iids: tuple[InstrumentId, ...] = (AAA,)) -> None:
    warm_to_quote(h, iids)
    flag(h, iids)


def first_leg_run(
    h: Harness,
    iids: tuple[InstrumentId, ...] = (AAA,),
    *,
    last: int = 38,
    price: str = "1.0200",
) -> None:
    for seconds in range(34, last + 1):
        h.clock.at(seconds)
        for iid in iids:
            h.session.on_trade(trade(seconds, price, iid=iid, size=100))


def ask_quote(
    h: Harness,
    seconds: int | str,
    iids: tuple[InstrumentId, ...] = (AAA,),
    *,
    bid: str = "1.0200",
    ask: str = "1.0300",
) -> None:
    h.clock.at(seconds)
    for iid in iids:
        h.session.on_quote(quote(seconds, bid, ask, iid=iid))


def entered(h: Harness, iids: tuple[InstrumentId, ...] = (AAA,)) -> None:
    warm(h, iids)
    first_leg_run(h, iids)
    ask_quote(h, 38, iids)


def test_no_order_before_a_qualifying_surge_and_the_flag_arms_the_entry() -> None:
    h = make_harness(AAA)
    warm_to_quote(h)
    symbol = str(AAA)

    assert h.submitted == []
    before = h.session.snapshot()
    assert before[symbol] == {
        "armed": False,
        "flag_ts": None,
        "pending_cid": None,
        "filled_qty": D("0"),
        "protection": None,
    }

    flag(h)

    after = h.session.snapshot()
    assert h.submitted == []
    assert after[symbol]["armed"] is True
    assert after[symbol]["flag_ts"] == START + 33 * SEC
    assert after[symbol]["pending_cid"] is None


def test_the_first_leg_sends_one_limit_buy_at_the_ask_on_the_increment() -> None:
    h = make_harness(AAA)
    entered(h)

    assert len(h.submitted) == 1
    command = h.submitted[0]
    assert command.side == "BUY"
    assert command.instrument == str(AAA)
    assert command.quantity == D("1")
    assert command.order_type == "LIMIT"
    assert command.time_in_force == "DAY"
    assert command.limit_price == limit_price(D("1.0300"), D("0.01"))
    assert command.limit_price == D("1.03")
    assert command.limit_price is not None
    assert command.limit_price % D("0.01") == 0
    assert command.client_order_id
    assert h.session.snapshot()[str(AAA)]["pending_cid"] == command.client_order_id


def test_the_same_flag_never_submits_twice() -> None:
    h = make_harness(AAA)
    entered(h)
    assert len(h.submitted) == 1
    cid = h.submitted[0].client_order_id

    ask_quote(h, 38)
    ask_quote(h, 39)

    assert len(h.submitted) == 1
    assert h.session.snapshot()[str(AAA)]["pending_cid"] == cid


def test_the_chase_cap_refuses_an_ask_above_quiet_times_one_plus_the_cap() -> None:
    h = make_harness(AAA, params=fixture_params(), chase="0.03")
    warm(h)
    first_leg_run(h)

    ask_quote(h, 38, ask="1.0400")
    assert h.submitted == []

    ask_quote(h, 39, ask="1.0300")
    assert len(h.submitted) == 1
    assert h.submitted[0].limit_price == D("1.03")


def test_a_second_symbol_can_fill_the_second_slot() -> None:
    h = make_harness(AAA, BBB, slot_count=2)
    warm(h, (AAA, BBB))
    first_leg_run(h, (AAA, BBB))

    ask_quote(h, 38, (AAA,))
    assert len(h.submitted) == 1
    ask_quote(h, 38, (BBB,))
    assert len(h.submitted) == 2
    assert {command.instrument for command in h.submitted} == {str(AAA), str(BBB)}


def test_an_rth_fill_emits_one_native_trailing_sell() -> None:
    h = make_harness(AAA)
    entered(h)
    cid = h.submitted[0].client_order_id

    h.session.on_fill(OrderFact(cid, str(AAA), "BUY", D("1"), D("1"), "FILLED", "venue-1"))

    assert len(h.submitted) == 2
    trail = h.submitted[1]
    assert trail.client_order_id == f"{cid}-trail"
    assert trail.instrument == str(AAA)
    assert trail.side == "SELL"
    assert trail.quantity == D("1")
    assert trail.order_type == "TRAILING_STOP"
    assert trail.time_in_force == "GTC"
    assert trail.limit_price is None
    assert trail.trail_price == D("2.5")
    snapshot = h.session.snapshot()[str(AAA)]
    assert snapshot["filled_qty"] == D("1")
    assert snapshot["protection"] == trail.client_order_id

    h.session.on_fill(OrderFact(cid, str(AAA), "BUY", D("1"), D("1"), "FILLED", "venue-1"))
    assert len(h.submitted) == 2


def test_an_outside_rth_fill_records_pending_protection_and_emits_nothing() -> None:
    h = make_harness(AAA, segment_name="PRE")
    entered(h)
    cid = h.submitted[0].client_order_id

    h.session.on_fill(OrderFact(cid, str(AAA), "BUY", D("1"), D("1"), "FILLED", "venue-2"))

    assert len(h.submitted) == 1
    snapshot = h.session.snapshot()[str(AAA)]
    assert snapshot["filled_qty"] == D("1")
    assert snapshot["protection"] == "outside RTH"


def test_expiry_refuses_the_order_at_the_window_edge() -> None:
    h = make_harness(AAA)
    warm(h)
    first_leg_run(h)

    for seconds in range(149, 154):
        h.clock.at(seconds)
        h.session.on_trade(trade(seconds, "1.0200", size=100))
    ask_quote(h, 153)

    assert h.submitted == []
    assert h.session.snapshot()[str(AAA)]["pending_cid"] is None
