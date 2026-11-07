"""Uncertain setup state refuses entry; rejected prints never rebuild or arm it."""

from decimal import Decimal as D

import pytest
from nautilus_trader.model import InstrumentId

from .conftest import SEC, START, quote, trade
from .test_delta_gate import receipt, reclaim_tape
from .test_late_controls import native
from .test_replay import replay
from .test_signals import arm, extended_state, feed, state


@pytest.mark.parametrize("price", ["9.95", "10.01", "11.00"])
@pytest.mark.parametrize(
    ("at", "delayed"), [("0", True), ("0.5", True), ("1", True), ("0", False), ("0.5", False)]
)
def test_late_print_in_first_leg_span_voids_without_ingestion(price, at, delayed):
    s = state()
    arm(s)
    feed(s, 0, "10.01")
    feed(s, 1, "10.01")
    before = s.dollars, s.volume, s.last
    tick = trade(at, price, lag=int((D("1.5") - D(at)) * SEC) if delayed else 0)
    assert not s.on_trade(tick, now=START + 1_500_000_000)
    assert s.void_reason == "late print within setup span"
    assert (s.dollars, s.volume, s.last) == before
    assert s.surge is None and not s.run and s.touch is None
    for when in (2, 3, 4):
        feed(s, when, "10.02")
    assert not s.first_leg_ready(D("10.02"), START + 4 * SEC)
    assert not s.failure


@pytest.mark.parametrize("price", ["9.97", "10.02", "10.04", "11.00"])
def test_late_print_inside_touch_or_hold_voids_the_whole_candidate(price):
    s = extended_state()
    for at, value in ((3, "10.03"), (4, "10.04"), (5, "10.05"), (6, "10.02"), (7, "10.02")):
        feed(s, at, value)
    before = s.dollars, s.volume
    late = trade("6.5", price, lag=800_000_000)
    assert not s.on_trade(late, now=late.ts_init)
    assert s.void_reason == "late print within setup span"
    assert (s.dollars, s.volume) == before
    assert s.touch is None and s.hold_started is None and not s.confirmed
    for at in (8, 9, 10):
        feed(s, at, "10.03")
    assert not s.reclaim_ready(D("10.03"), D("0.10"), START + 10 * SEC, covered_flow=True)


@pytest.mark.parametrize("kind", ["clean", "delivery-delay", "old", "wrong-symbol", "in-span"])
def test_native_first_leg_void_is_journaled_and_clean_controls_enter(instrument, tmp_path, kind):
    lag = 30_000_000 if kind == "delivery-delay" else 0
    data = [
        quote(0, "10.00", "10.02"),
        trade(0, "10.01", size=10000, lag=lag),
        trade(1, "10.01", size=10000, lag=lag),
    ]
    if kind == "old":
        data += [trade(-200, "9.95", lag=201_500_000_000)]
    elif kind == "wrong-symbol":
        data += [trade("0.5", "9.95", iid=InstrumentId.from_str("OTHER.SIM"), lag=SEC)]
    elif kind == "in-span":
        data += [trade("0.5", "10.01", lag=SEC)]
    data += [trade(2, "10.01", size=10000, lag=lag), quote(3, "10.00", "10.02")]
    if kind == "wrong-symbol":
        # Native replay requires registered instruments; validate this malformed-context arm below.
        s = state()
        arm(s)
        feed(s, 0, "10.01")
        feed(s, 1, "10.01")
        assert not s.on_trade(data[3], now=data[3].ts_init)
        assert s.void_reason is None
        data.pop(3)
    result = replay(instrument, tmp_path, data)
    assert not result.failed
    voids = [e for e in result.events if e["action"] == "VOID"]
    if kind == "in-span":
        assert not result.orders, result.events
        assert len(voids) == 1 and voids[0]["reason"] == "late print within setup span"
        assert voids[0]["ts"] == START + 1_500_000_000
    else:
        assert len(result.orders) == 1 and result.orders[0]["status"] == "FILLED"
        assert not voids


@pytest.mark.parametrize("late", [False, True], ids=["clean-positive", "round4-hidden-veto"])
def test_dropping_a_benign_late_print_must_still_void_reclaim(instrument, tmp_path, late):
    data = [*reclaim_tape(), quote("7.9", "10.02", "10.03")]
    if late:
        data.append(trade("6.5", "10.04", lag=800_000_000))
    result = replay(
        instrument,
        tmp_path,
        sorted(data, key=lambda t: t.ts_init),
        surge=None,
        confidence=D("0.5"),
        coverage=receipt({60 * SEC: 10 if late else 9, 2 * SEC: 3 if late else 2}),
    )
    assert not result.failed
    assert len(result.orders) == (0 if late else 1), result.events
    assert any(e["action"] == "VOID" for e in result.events) is late


def test_fresh_in_order_delivery_delay_preserves_native_reclaim(instrument, tmp_path):
    data = [item for item in reclaim_tape() if not hasattr(item, "trade_id")]
    data += [
        trade(at, price, size=10000 if at == 0 else 100, lag=30_000_000)
        for at, price in [
            (0, "10.00"),
            (1, "11.00"),
            (2, "9.99"),
            (3, "10.03"),
            (4, "10.04"),
            (5, "10.05"),
            (6, "10.02"),
            (7, "10.02"),
            (8, "10.03"),
        ]
    ]
    result = native(instrument, tmp_path, [*data, quote("7.9", "10.02", "10.03")], "8.03")
    assert not result.failed and len(result.orders) == 1, result.events
    assert result.orders[0]["status"] == "FILLED"
    assert not any(e["action"] == "VOID" for e in result.events)


@pytest.mark.parametrize("duplicate", [False, True], ids=["clean", "old-redelivery"])
def test_old_duplicate_outside_the_reclaim_span_does_not_latch(instrument, tmp_path, duplicate):
    data = [trade(-200, "10.00", size=10000), *reclaim_tape(), quote("7.9", "10.02", "10.03")]
    if duplicate:
        data.append(trade(-200, "10.00", size=10000, lag=207_300_000_000))
    result = native(instrument, tmp_path, data, 8)
    assert not result.failed and len(result.orders) == 1, result.events
    assert result.orders[0]["status"] == "FILLED"
    assert not any(e["action"] == "VOID" for e in result.events)
