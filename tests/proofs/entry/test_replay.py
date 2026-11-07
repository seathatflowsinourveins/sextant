"""Exercise our entry boundary through real native matching, risk and clock events."""

from decimal import Decimal as D
from typing import Any

import pytest
from nautilus_trader.execution import (
    LimitOrderPartialFillModel,
    MakerTakerFeeModel,
    StaticLatencyModel,
)

from sextant.entry.orders import limit_price
from sextant.entry.replay import run_replay
from sextant.entry.signals import Surge, TradeCoverage

from .conftest import IID, SEC, START, bar, params, quote, trade


def replay(instrument, tmp_path, data, **overrides):
    arguments: dict[str, Any] = dict(
        instrument=instrument,
        params=params(),
        data=data,
        basis_path=tmp_path / "basis.json",
        segment="fixture-segment",
        segment_start_ns=START - 3600 * SEC,
        surge=Surge(IID, "fixture-segment", START, START, START + 120 * SEC, D("10"), "TEST"),
        buffer=D("0.10"),
        starting_cash=D("10000"),
        regular_hours=True,
        confidence=None,
        fee_model=MakerTakerFeeModel(maker_rate=D(0), taker_rate=D(0)),
        commission_rate=D(0),
    )
    if "fee_model" in overrides and "commission_rate" not in overrides:
        arguments["commission_rate"] = None
    return run_replay(**(arguments | overrides))


@pytest.mark.parametrize(("ask", "expected_orders"), [("9.99", 0), ("10.00", 1)])
def test_first_leg_native_ask_respects_quiet_bound(
    instrument, tmp_path, ask, expected_orders
) -> None:
    result = replay(
        instrument,
        tmp_path,
        [
            quote(0, "9.98", ask),
            trade(0, "10.01", size=10000),
            trade(1, "10.02", size=10000),
            trade(2, "10.03", size=10000),
        ],
    )
    assert len(result.orders) == expected_orders, result.events


def test_zero_cash_start_and_frozen_zero_restart_refuse_entry(instrument, tmp_path) -> None:
    data = [quote(0, "10.00", "10.01")] + [trade(at, "10.01", size=10000) for at in (0, 1, 2)]
    empty = replay(instrument, tmp_path, data, starting_cash=D(0))
    assert not empty.orders
    assert any(event["action"] == "REFUSE" for event in empty.events), empty.events
    # The node-start zero stays frozen even when a restart has cash available.
    restarted = replay(instrument, tmp_path, data)
    assert not restarted.orders
    assert any(
        event["action"] == "REFUSE" and "basis" in event["reason"] for event in restarted.events
    ), restarted.events


def test_lower_trade_restart_is_witnessed_in_native_replay(instrument, tmp_path) -> None:
    result = replay(
        instrument,
        tmp_path,
        [
            quote(0, "10.00", "10.01"),
            trade(0, "10.01", size=10000),
            trade(1, "10.03", size=10000),
            trade(2, "10.02", size=10000),
            trade(3, "10.02", size=10000),
            quote("3.5", "10.02", "10.03"),
            trade(4, "10.03", size=10000),
            trade(5, "10.04", size=10000),
        ],
    )
    submitted = [event for event in result.events if event["action"] == "SUBMIT"]
    assert len(submitted) == 1, result.events
    assert submitted[0]["ts"] == START + 4 * SEC
    assert submitted[0]["order_type"] == "LIMIT"
    assert submitted[0]["extension"] == "UNKNOWN"
    assert submitted[0]["confidence"] is None
    assert result.orders[0]["status"] == "FILLED"
    assert result.orders[0]["filled_qty"] != "0"
    assert result.tier == "MODELED"
    assert result.fixture_only


def test_entry_ttl_cancels_only_entry_and_chase_never_exceeds_first_limit(instrument, tmp_path):
    result = replay(
        instrument,
        tmp_path,
        [
            quote(0, "10.00", "10.02"),
            trade(0, "10.01", size=10000),
            trade(1, "10.01", size=10000),
            trade(2, "10.02", size=10000),
            quote("2.1", "10.02", "10.03"),
            quote(3, "10.02", "10.03"),
            quote("3.1", "10.03", "10.04"),
            quote(4, "10.03", "10.04"),
            quote(10, "10.03", "10.04"),
        ],
        latency_model=StaticLatencyModel(
            insert_latency_nanos=500_000_000, update_latency_nanos=500_000_000
        ),
    )
    assert len(result.orders) == 1
    assert result.orders[0]["status"] == "CANCELED"
    assert result.orders[0]["filled_qty"] == "0"
    modifications = [e for e in result.events if e["action"] == "MODIFY"]
    assert len(modifications) == 1
    assert modifications[0]["limit"] == "10.03"
    cancellations = [e for e in result.events if e["action"] == "CANCEL"]
    assert len(cancellations) == 1
    assert cancellations[0]["ts"] == START + 7 * SEC


@pytest.mark.parametrize(
    ("initial_ask", "next_ask", "cash", "flow_size", "can_reprice", "quantity"),
    [
        ("10.02", "10.03", "1000", 1850, False, "95"),
        ("10.02", "10.03", "1000", 2000, True, "95"),
        ("10.00", "10.01", "1001", 2000, False, "100"),
    ],
    ids=["whole-position-flow-cap", "affordable-leaves", "whole-position-risk-cap"],
)
def test_partial_fill_reprice_respects_full_position_caps(
    instrument, tmp_path, initial_ask, next_ask, cash, flow_size, can_reprice, quantity
):
    trade_price = initial_ask
    result = replay(
        instrument,
        tmp_path,
        [
            quote(0, "9.99", initial_ask),
            trade(0, trade_price, size=10000),
            trade(1, trade_price, size=10000),
            trade(2, trade_price, size=10000),
            trade(3, trade_price, size=flow_size),
            quote("3.1", "10.00", next_ask),
            quote(10, "10.00", next_ask),
        ],
        starting_cash=D(cash),
        surge=Surge(IID, "fixture-segment", START, START, START + 120 * SEC, D("9.90"), "TEST"),
        params=params(stop_ref_fraction="0.1", flow_share_window_s="1"),
        latency_model=StaticLatencyModel(insert_latency_nanos=500_000_000),
        fill_model=LimitOrderPartialFillModel(prob_fill_on_limit=1.0, prob_slippage=0.0),
    )
    assert len(result.orders) == 1
    assert result.orders[0]["quantity"] == quantity
    modifications = [e for e in result.events if e["action"] == "MODIFY"]
    if can_reprice:
        assert len(modifications) == 1
        assert result.orders[0]["price"] == next_ask
    else:
        assert modifications == []
        assert result.orders[0]["price"] == initial_ask
    assert D(0) < D(result.orders[0]["filled_qty"]) < D(quantity)
    assert result.orders[0]["status"] == "CANCELED"


@pytest.mark.parametrize("fee_bound", [None, D("0.01")])
def test_nonzero_commission_never_overdraws_cash(instrument, tmp_path, fee_bound):
    overrides = dict(
        starting_cash=D("1000"),
        params=params(stop_ref_fraction="1", portfolio_slots=1),
        fee_model=MakerTakerFeeModel(maker_rate=D("0.01"), taker_rate=D("0.01")),
    )
    if fee_bound is not None:
        overrides["commission_rate"] = fee_bound
    result = replay(
        instrument,
        tmp_path,
        [
            quote(0, "10.00", "10.01"),
            trade(0, "10.01", size=10000),
            trade(1, "10.01", size=10000),
            trade(2, "10.01", size=10000),
        ],
        **overrides,
    )
    if fee_bound is None:
        assert result.orders == []
        assert any("commission_rate" in e.get("reason", "") for e in result.events)
    else:
        assert len(result.orders) == 1 and result.orders[0]["status"] == "FILLED"
        assert D(result.orders[0]["filled_qty"]) <= D("98")


def test_outside_rth_is_plain_limit_with_extended_hours_intent(instrument, tmp_path) -> None:
    result = replay(
        instrument,
        tmp_path,
        [
            quote(0, "10.00", "10.01"),
            trade(0, "10.01", size=10000),
            trade(1, "10.01", size=10000),
            trade(2, "10.02", size=10000),
            quote(3, "10.01", "10.02"),
        ],
        regular_hours=False,
    )
    submits = [e for e in result.events if e["action"] == "SUBMIT"]
    assert len(submits) == 1
    assert submits[0]["extended_hours"] is True
    assert submits[0]["order_type"] == "LIMIT"
    assert submits[0]["contingency_type"] is None


@pytest.mark.parametrize(
    ("ask", "tick", "expected"),
    [
        ("0.12345", "0.0001", "0.1235"),
        ("0.99999", "0.0001", "1.00"),
        ("1.001", "0.01", "1.01"),
        ("10.020", "0.01", "10.02"),
    ],
)
def test_limit_precision_rounds_to_executable_ask(ask, tick, expected):
    assert limit_price(D(ask), D(tick)) == D(expected)


def test_stale_or_crossed_quote_never_submits(instrument, tmp_path) -> None:
    result = replay(
        instrument,
        tmp_path,
        [
            quote(0, "10.00", "10.01"),
            trade(10, "10.01", size=10000),
            trade(11, "10.01", size=10000),
            trade(12, "10.02", size=10000),
            quote(13, "10.03", "10.02"),
        ],
    )
    assert result.orders == []


@pytest.mark.parametrize("covered", [True, False])
def test_held_reclaim_reaches_native_limit_only_with_covered_flow(instrument, tmp_path, covered):
    coverage = TradeCoverage(
        IID,
        "fixture-segment",
        START - 60 * SEC,
        START + 8 * SEC,
        START + 8 * SEC,
        "TEST complete eligible tape",
        {60 * SEC: 9, 2 * SEC: 2},
    )
    result = replay(
        instrument,
        tmp_path,
        [
            bar(-180),
            bar(-120),
            bar(-60),
            quote(0, "9.99", "10.00"),
            trade(0, "10.00", size=10000),
            trade(1, "11.00"),
            trade(2, "9.99"),
            trade(3, "10.03"),
            trade(4, "10.04"),
            trade(5, "10.05"),
            trade(6, "10.02"),
            trade(7, "10.02"),
            quote("7.9", "10.02", "10.03"),
            trade(8, "10.03"),
        ],
        surge=None,
        confidence=D("0.5"),
        coverage=coverage if covered else None,
    )
    submits = [e for e in result.events if e["action"] == "SUBMIT"]
    if covered:
        assert len(submits) == 1
        assert submits[0]["ts"] == START + 8 * SEC
        assert submits[0]["setup"] == "RECLAIM"
        assert submits[0]["confidence"] == "0.5"
        assert result.orders[0]["status"] == "FILLED"
    else:
        assert submits == []
        assert result.orders == []


def test_missed_reclaim_never_submits_at_a_later_fresh_high(instrument, tmp_path):
    result = replay(
        instrument,
        tmp_path,
        [
            bar(-180),
            bar(-120),
            bar(-60),
            quote(0, "9.99", "10.00"),
            trade(0, "10.00", size=10000),
            trade(1, "11.00"),
            trade(2, "9.99"),
            trade(3, "10.03"),
            trade(4, "10.04"),
            trade(5, "10.05"),
            trade(6, "10.02"),
            trade(7, "10.02"),
            quote("7.9", "10.19", "10.20"),
            trade(8, "10.03"),
            trade(9, "10.06"),
            trade(10, "10.08"),
            quote("11.9", "10.09", "10.10"),
            trade(12, "10.10"),
        ],
        surge=None,
        confidence=D("0.5"),
        coverage=TradeCoverage(
            IID,
            "fixture-segment",
            START - 60 * SEC,
            START + 12 * SEC,
            START + 12 * SEC,
            "TEST complete eligible tape",
            {60 * SEC: 12, 2 * SEC: 1},
        ),
    )
    assert not any(e["action"] == "SUBMIT" for e in result.events), result.events
    assert result.orders == []


@pytest.mark.parametrize(("middle", "last"), [("10.04", "10.05"), ("10.03", "10.04")])
def test_consumed_reclaim_cannot_rearm_on_rising_or_flat_tape(instrument, tmp_path, middle, last):
    result = replay(
        instrument,
        tmp_path,
        [
            bar(-180),
            bar(-120),
            bar(-60),
            quote(0, "9.99", "10.00"),
            trade(0, "10.00", size=10000),
            trade(1, "11.00"),
            trade(2, "9.99"),
            trade(3, "10.03"),
            trade(4, "10.04"),
            trade(5, "10.05"),
            trade(6, "10.02"),
            trade(7, "10.02"),
            quote("7.9", "10.19", "10.20"),
            trade(8, "10.03"),
            trade(9, middle),
            quote("10.9", middle, last),
            trade(11, last),
        ],
        surge=None,
        confidence=D("0.5"),
        coverage=TradeCoverage(
            IID,
            "fixture-segment",
            START - 60 * SEC,
            START + 11 * SEC,
            START + 11 * SEC,
            "TEST complete eligible tape",
            {60 * SEC: 11, 2 * SEC: 1},
        ),
    )
    assert result.orders == []
    assert not any(e["action"] == "SUBMIT" for e in result.events)


def test_refused_reclaim_cannot_enter_on_a_later_quote(instrument, tmp_path):
    result = replay(
        instrument,
        tmp_path,
        [
            bar(-180),
            bar(-120),
            bar(-60),
            quote(0, "9.99", "10.00"),
            trade(0, "10.00", size=10000),
            trade(1, "11.00"),
            trade(2, "9.99"),
            trade(3, "10.03"),
            trade(4, "10.04"),
            trade(5, "10.05"),
            trade(6, "10.02"),
            trade(7, "10.02"),
            quote("7.9", "10.19", "10.20"),
            trade(8, "10.03"),
            quote(9, "10.02", "10.03"),
        ],
        surge=None,
        confidence=D("0.5"),
        coverage=TradeCoverage(
            IID,
            "fixture-segment",
            START - 60 * SEC,
            START + 9 * SEC,
            START + 9 * SEC,
            "TEST complete eligible tape",
            {60 * SEC: 9, 2 * SEC: 1},
        ),
    )
    assert result.orders == []


def test_ttl_during_unacknowledged_submit_cancels_after_acceptance(instrument, tmp_path):
    result = replay(
        instrument,
        tmp_path,
        [
            quote(0, "10.00", "10.02"),
            trade(0, "10.01", size=10000),
            trade(1, "10.01", size=10000),
            trade(2, "10.02", size=10000),
            quote(3, "10.50", "10.51"),
            quote(12, "10.50", "10.51"),
        ],
        latency_model=StaticLatencyModel(insert_latency_nanos=10 * SEC),
    )
    assert len(result.orders) == 1
    assert result.orders[0]["status"] == "CANCELED"
    assert result.orders[0]["filled_qty"] == "0"
    assert [e["ts"] for e in result.events if e["action"] == "CANCEL"] == [START + 12 * SEC]
    assert not any(e["action"] == "MODIFY" for e in result.events)


def test_reprice_rechecks_first_leg_cap(instrument, tmp_path):
    result = replay(
        instrument,
        tmp_path,
        [
            quote(0, "10.00", "11.00"),
            trade(0, "10.01", size=10000),
            trade(1, "10.01", size=10000),
            trade(2, "10.02", size=10000),
            quote("2.1", "11.00", "11.01"),
            quote(3, "11.00", "11.01"),
            quote(10, "11.00", "11.01"),
        ],
        params=params(chase_cap_fraction="0"),
        latency_model=StaticLatencyModel(insert_latency_nanos=500_000_000),
    )
    assert result.orders[0]["status"] == "CANCELED"
    assert not any(e["action"] == "MODIFY" for e in result.events)
