"""Exercise our entry boundary through real native matching, risk and clock events."""

from decimal import Decimal as D
from typing import Any

import pytest
from nautilus_trader.execution import MakerTakerFeeModel, StaticLatencyModel

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
        surge=Surge(IID, "fixture-segment", START, START, START + 120 * SEC, D("10"), "TEST"),
        buffer=D("0.10"),
        starting_cash=D("10000"),
        regular_hours=True,
        confidence=None,
        fee_model=MakerTakerFeeModel(maker_rate=D(0), taker_rate=D(0)),
    )
    return run_replay(**(arguments | overrides))


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
