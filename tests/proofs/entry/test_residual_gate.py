"""Minimal admission: stale setup vetoes, complete flow and native funding credits."""

from decimal import Decimal as D

import pytest
from nautilus_trader.execution import (
    LimitOrderPartialFillModel,
    MakerTakerFeeModel,
    StaticLatencyModel,
)

from sextant.entry.signals import Surge, TradeCoverage

from .conftest import IID, SEC, START, bar, params, quote, trade
from .test_delta_gate import reclaim_tape
from .test_replay import replay
from .test_signals import arm, feed, state


def coverage(end, baseline, recent):
    return TradeCoverage(
        IID,
        "fixture-segment",
        START - 60 * SEC,
        START + end * SEC,
        START + end * SEC,
        "TEST full tape",
        {60 * SEC: baseline, 2 * SEC: recent},
    )


@pytest.mark.parametrize("price", ["9.95", "10.01"])
@pytest.mark.parametrize("lag", [0, 5_100_000_000], ids=["ordered", "stale-late"])
def test_native_stale_print_inside_first_leg_still_vetoes(instrument, tmp_path, price, lag):
    data = [
        trade(0, "10.01", size=10000),
        trade(1, "10.02", size=10000),
        trade(2, "10.03", size=10000),
        trade("1.5", price, lag=lag),
        quote("6.7", "10.02", "10.03"),
        quote("6.8", "10.02", "10.03"),
    ]
    result = replay(
        instrument,
        tmp_path,
        sorted(data, key=lambda item: item.ts_init),
        surge=Surge(
            IID, "fixture-segment", START, START + 6_650_000_000, START + 120 * SEC, D("10"), "TEST"
        ),
    )
    assert result.orders == [], result.events


@pytest.mark.parametrize("price", ["9.97", "11.10"])
@pytest.mark.parametrize("lag", [0, 5_100_000_000], ids=["ordered", "stale-late"])
def test_native_stale_print_inside_reclaim_still_vetoes(instrument, tmp_path, price, lag):
    data = [item for item in reclaim_tape() if item.ts_event != START + 8 * SEC]
    data += [
        trade("6.5", price, lag=lag),
        quote("11.9", "10.02", "10.03"),
        trade(12, "10.03"),
    ]
    result = replay(
        instrument,
        tmp_path,
        sorted(data, key=lambda item: item.ts_init),
        surge=None,
        confidence=D("0.5"),
        coverage=coverage(12, 10, 1),
    )
    assert result.orders == [], result.events


def test_a_stale_print_before_the_run_does_not_veto_it():
    s = state()
    arm(s)
    for at, price in ((0, "10.01"), (1, "10.02"), (2, "10.03")):
        feed(s, at, price)
    old = trade(-1, "9.95", lag=7_600_000_000)
    assert not s.on_trade(old, now=old.ts_init)
    assert s.first_leg_ready(D("10.03"), START + 6_700_000_000)


def test_old_duplicate_cannot_double_count_and_untrusts_vwap_until_the_next_segment():
    s = state(first_leg_window_s="10", flow_share_window_s="10", covered_flow_baseline_min="0.1")
    first = trade(0, "10.00")
    assert s.on_trade(first, now=first.ts_init)
    feed(s, 20, "20.00")
    assert not s.on_trade(first, now=START + 21 * SEC)
    assert s.volume == 200 and s.vwap is None and s.void_reason == "late print: VWAP untrusted"
    assert feed(s, 22, "20.00") and s.vwap is None
    s.reset_segment("next-segment", start_ns=START + 30 * SEC)
    assert feed(s, 31, "20.00") and s.vwap == 20


@pytest.mark.parametrize("lag", [700_000_000, 5_100_000_000], ids=["late", "stale-late"])
def test_a_dropped_print_leaves_no_usable_biased_vwap(lag):
    # Round 8 deleted this property's proof with its mechanism; it is kept, restated for the latch.
    ordered, arrived = state(), state()
    first, last = trade(0, "10.00", size=10000), trade(1, "10.01", size=100)
    for tick in (first, trade("0.5", "9.60", size=10000), last):
        ordered.on_trade(tick, now=tick.ts_init)
    for tick in (first, last):
        arrived.on_trade(tick, now=tick.ts_init)
    late = trade("0.5", "9.60", size=10000, lag=lag)
    for _ in range(2):
        assert not arrived.on_trade(late, now=late.ts_init)
        assert arrived.volume == 10100 and arrived.last == last and arrived.vwap is None
    assert ordered.vwap == D("197001") / D("20100")
    assert not arrived.reclaim_ready(D("10.03"), D("0.10"), late.ts_init, covered_flow=True)


@pytest.mark.parametrize("lag", [0, 700_000_000], ids=["ordered", "late-block"])
def test_native_late_block_cannot_bias_the_reclaim_level(instrument, tmp_path, lag):
    data = [bar(-180), bar(-120), bar(-60)] + [
        trade(at, price, size=size)
        for at, price, size in (
            (0, "10.00", 10000),
            (1, "10.01", 100),
            (2, "11.00", 100),
            (3, "9.99", 100),
            (4, "10.03", 100),
            (5, "10.04", 100),
            (6, "10.05", 100),
            (7, "10.02", 100),
            (8, "10.02", 100),
            (9, "10.03", 100),
        )
    ]
    data += [trade("0.5", "9.60", size=10000, lag=lag), quote("8.9", "10.02", "10.03")]
    result = replay(
        instrument,
        tmp_path,
        sorted(data, key=lambda item: item.ts_init),
        surge=None,
        confidence=D("0.5"),
        coverage=coverage(9, 11, 2),
    )
    assert result.orders == [], result.events


@pytest.mark.parametrize(
    "size", [None, 10000, 100], ids=["clean-control", "biasing-block", "benign-print"]
)
def test_a_void_also_refuses_later_reclaims_in_the_segment(instrument, tmp_path, size):
    first = [(0, "10.00"), (1, "11.00"), (2, "9.99"), (3, "10.03"), (4, "10.04")]
    later = [(20, "11.00"), (21, "9.99"), (22, "10.03"), (23, "10.04"), (24, "10.05")]
    later += [(25, "10.02"), (26, "10.02"), (27, "10.03")]
    data = [bar(-180), bar(-120), bar(-60), quote("26.9", "10.02", "10.03")]
    data += [trade(at, p, size=10000 if at == 0 else 100) for at, p in first + later]
    if size:  # stamped inside candidate 1's reclaim span, arriving after its t4 print
        data.append(trade("3.5", "9.60", size=size, lag=500_000_000))
    result = replay(
        instrument,
        tmp_path,
        sorted(data, key=lambda item: item.ts_init),
        surge=None,
        confidence=D("0.5"),
        coverage=coverage(27, 14, 2),
    )
    assert len(result.orders) == (0 if size else 1), result.events
    voids = [e["reason"] for e in result.events if e["action"] == "VOID"]
    assert voids == ["late print: VWAP untrusted"] * bool(size), result.events


@pytest.mark.parametrize("lag", [600_000_000, 5_100_000_000], ids=["late", "stale-late"])
def test_arming_cannot_credit_a_late_qualifying_print(lag):
    s = state()
    feed(s, 0, "10.01")
    feed(s, 2, "10.03")
    late = trade("1.5", "10.02", lag=lag)
    assert not s.on_trade(late, now=late.ts_init)
    known = late.ts_init + 50_000_000
    s.arm(Surge(IID, "fixture-segment", START, known, START + 120 * SEC, D("10"), "TEST"))
    assert not s.first_leg_ready(D("10.03"), known + 50_000_000)
    feed(s, 8, "10.04")
    assert not s.first_leg_ready(D("10.04"), START + 8 * SEC)
    feed(s, 9, "10.05")
    feed(s, 10, "10.06")
    assert s.first_leg_ready(D("10.06"), START + 10 * SEC)


def test_receipt_cannot_undercount_the_observed_tape(instrument, tmp_path):
    earlier = [trade(str(D(-50) + D("0.49") * i), "10.00") for i in range(100)]
    data = [*earlier, *reclaim_tape(), quote("7.9", "10.02", "10.03")]
    result = replay(
        instrument,
        tmp_path,
        sorted(data, key=lambda item: item.ts_init),
        surge=None,
        confidence=D("0.5"),
        coverage=coverage(8, 9, 2),
    )
    assert result.orders == [], result.events


def test_a_stale_higher_print_cannot_hide_the_next_lower_trade():
    s = state()
    arm(s)
    for at in (0, 1, 2):
        feed(s, at, "10.01")
    stale = trade(3, "10.05", lag=6 * SEC)
    assert not s.on_trade(stale, now=stale.ts_init)
    feed(s, 10, "10.03")
    assert not s.first_leg_ready(D("10.03"), START + 10 * SEC)


def test_local_flow_must_pass_even_when_a_superset_receipt_passes(instrument, tmp_path):
    earlier = [trade(str(D(-50) + D("0.49") * i), "10.00") for i in range(100)]
    data = [*earlier, *reclaim_tape(), quote("7.9", "10.02", "10.03")]
    result = replay(
        instrument,
        tmp_path,
        sorted(data, key=lambda item: item.ts_init),
        surge=None,
        confidence=D("0.5"),
        coverage=coverage(8, 117, 10),
    )
    assert result.orders == [], result.events


@pytest.mark.parametrize(
    ("cash", "flow_cap", "quantity", "can_reprice"),
    [("990.99", "0.05", "99", False), ("1002", "0.0032", "96", True)],
    ids=["cannot-fund-leaves", "affordable-leaves"],
)
def test_partial_fill_funding_credits_only_actual_leaves_and_fills(
    instrument, tmp_path, cash, flow_cap, quantity, can_reprice
):
    rate = D("0.001")
    result = replay(
        instrument,
        tmp_path,
        [quote(0, "9.99", "10.00")]
        + [trade(at, "10.00", size=10000) for at in (0, 1, 2, 3)]
        + [quote("3.1", "10.00", "10.01"), quote(10, "10.00", "10.01")],
        starting_cash=D(cash),
        surge=Surge(IID, "fixture-segment", START, START, START + 120 * SEC, D("9.90"), "TEST"),
        params=params(stop_ref_fraction="1", portfolio_slots=1, flow_share_cap=flow_cap),
        commission_rate=rate,
        fee_model=MakerTakerFeeModel(maker_rate=rate, taker_rate=rate),
        latency_model=StaticLatencyModel(insert_latency_nanos=500_000_000),
        fill_model=LimitOrderPartialFillModel(prob_fill_on_limit=1.0, prob_slippage=0.0),
    )
    assert len(result.orders) == 1
    order = result.orders[0]
    assert order["quantity"] == quantity
    assert 0 < D(order["filled_qty"]) < D(quantity)
    assert order["status"] == "CANCELED"
    assert any(e["action"] == "MODIFY" for e in result.events) is can_reprice, result.events
    assert order["price"] == ("10.01" if can_reprice else "10.00")
