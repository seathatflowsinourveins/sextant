"""Exact-head delta witnesses: late vetoes, attested counts, TTL and Decimal prices."""

from decimal import Decimal as D

import pytest
from nautilus_trader.execution import StaticLatencyModel

from sextant.entry.signals import TradeCoverage

from .conftest import IID, SEC, START, bar, params, quote, trade
from .test_replay import replay
from .test_signals import arm, extended_state, feed, state


def receipt(counts=None):
    return TradeCoverage(
        IID, "fixture-segment", START - 60 * SEC, START + 8 * SEC, START + 8 * SEC, "TEST", counts
    )


def reclaim_tape(trough="10.02", last="10.03"):
    return [bar(-180), bar(-120), bar(-60)] + [
        trade(at, price, size=10000 if at == 0 else 100)
        for at, price in (
            (0, "10.00"),
            (1, "11.00"),
            (2, "9.99"),
            (3, "10.03"),
            (4, "10.04"),
            (5, "10.05"),
            (6, trough),
            (7, trough),
            (8, last),
        )
    ]


@pytest.mark.parametrize("price", ["9.95", "10.01", "11.00"])
def test_out_of_order_print_clears_first_leg_without_extending_it(price):
    s = state()
    for offset in (-180, -120, -60):
        s.on_bar(bar(offset), now=START)
    arm(s)
    for at, value in ((0, "10.01"), (1, "10.02"), (2, "10.03")):
        feed(s, at, value)
    assert s.first_leg_ready(D("10.03"), START + 2 * SEC)
    previous = s.last
    late = trade("1.5", price, lag=600_000_000)
    assert not s.on_trade(late, now=late.ts_init)
    assert not s.first_leg_ready(D("10.03"), late.ts_init)
    assert s.last == previous
    assert s.dollars == D("3006")
    assert s.volume == 300
    for at in (3, 4):
        feed(s, at, "10.03")
    assert not s.first_leg_ready(D("10.03"), START + 4 * SEC)
    feed(s, 5, "10.03")  # N1's restart: only fresh prints re-form the run
    assert s.first_leg_ready(D("10.03"), START + 5 * SEC)
    assert s.run[0].ts_event == START + 3 * SEC


@pytest.mark.parametrize("price", ["9.97", "10.02", "11.00"])
def test_out_of_order_print_cannot_preserve_a_held_reclaim(price):
    s = extended_state()
    for at, value in ((3, "10.03"), (4, "10.04"), (5, "10.05"), (6, "10.03"), (7, "10.03")):
        feed(s, at, value)
    late = trade("6.5", price, lag=800_000_000)
    assert not s.on_trade(late, now=late.ts_init)
    feed(s, 8, "10.04")
    assert not s.reclaim_ready(D("10.04"), D("0.10"), START + 8 * SEC, covered_flow=True)


@pytest.mark.parametrize("price", ["9.95", "10.01"])
@pytest.mark.parametrize("lag", [0, 600_000_000], ids=["ordered-control", "late-veto"])
def test_native_out_of_order_first_leg_veto_is_not_ignored(instrument, tmp_path, price, lag):
    data = [
        trade(0, "10.01", size=10000),
        trade(1, "10.02", size=10000),
        trade(2, "10.03", size=10000),
        trade("1.5", price, lag=lag),
        quote("2.2", "10.02", "10.03"),
        quote("2.3", "10.02", "10.03"),
    ]
    result = replay(instrument, tmp_path, sorted(data, key=lambda item: item.ts_init))
    assert result.orders == [], result.events


@pytest.mark.parametrize(
    ("price", "trough", "last"), [("9.97", "10.02", "10.03"), ("10.02", "10.03", "10.04")]
)
@pytest.mark.parametrize("lag", [0, 800_000_000], ids=["ordered-control", "late-veto"])
def test_native_out_of_order_reclaim_veto_is_not_ignored(
    instrument, tmp_path, price, trough, last, lag
):
    data = [
        *reclaim_tape(trough, last),
        trade("6.5", price, lag=lag),
        quote("7.9", trough, last),
    ]
    result = replay(
        instrument,
        tmp_path,
        sorted(data, key=lambda item: item.ts_init),
        surge=None,
        confidence=D("0.5"),
        coverage=receipt({60 * SEC: 10, 2 * SEC: 3}),
    )
    assert result.orders == [], result.events


@pytest.mark.parametrize("full_tape", [True, False], ids=["complete-control", "late-start"])
@pytest.mark.parametrize(
    "counts", [None, {60 * SEC: 109, 2 * SEC: 2}], ids=["no-counts", "full-counts"]
)
def test_metadata_receipt_cannot_authorize_an_unobserved_baseline(
    instrument, tmp_path, full_tape, counts
):
    earlier = [trade(str(D(-50) + D("0.49") * i), "10.00") for i in range(100)]
    data = [*reclaim_tape(), quote("7.9", "10.02", "10.03")]
    if full_tape:
        data += earlier
    result = replay(
        instrument,
        tmp_path,
        sorted(data, key=lambda item: item.ts_init),
        surge=None,
        confidence=D("0.5"),
        coverage=receipt(counts),
    )
    assert result.orders == [], result.events


@pytest.mark.parametrize("drop", ["missing", "out-of-order", "stale"])
def test_attested_baseline_cannot_shrink_when_local_prints_are_missing(drop):
    s = state(covered_flow_ratio="6.5")
    for at in range(9):
        feed(s, at, "10.01")
    if drop != "missing":
        late = (
            trade("3.5", "10.01", lag=4_500_000_000)
            if drop == "out-of-order"
            else trade(-1, "10.01", lag=9 * SEC)
        )
        assert not s.on_trade(late, now=START + 8 * SEC)
    # Nine kept prints give 120 >= 117; the attested ten give 120 < 130.
    assert not s.covered_flow(START + 8 * SEC, receipt({60 * SEC: 10, 2 * SEC: 2}))


@pytest.mark.parametrize(
    ("counts", "allowed"),
    [
        ({60 * SEC: 9, 2 * SEC: 2}, True),
        (None, False),
        ({60 * SEC: 9}, False),
        ({60 * SEC: 9, SEC: 2}, False),
        ({60 * SEC: True, 2 * SEC: 2}, False),
        ({60 * SEC: 9.0, 2 * SEC: 2}, False),
        ({60 * SEC: 0, 2 * SEC: 0}, False),
        ({60 * SEC: 9, 2 * SEC: -1}, False),
        ({60 * SEC: 1, 2 * SEC: 2}, False),
    ],
)
def test_covered_flow_uses_valid_counts_bound_to_each_horizon(counts, allowed):
    s = state()
    for at in range(9):
        feed(s, at, "10.01")
    assert s.covered_flow(START + 8 * SEC, receipt(counts)) is allowed


def test_late_veto_stops_repricing_an_open_first_leg(instrument, tmp_path):
    result = replay(
        instrument,
        tmp_path,
        [
            quote(0, "10.00", "10.02"),
            trade(0, "10.01", size=10000),
            trade(1, "10.01", size=10000),
            trade(2, "10.02", size=10000),
            quote("2.1", "10.49", "10.50"),
            trade("1.5", "9.95", lag=1_300_000_000),
            quote(3, "10.02", "10.03"),
            quote(10, "10.49", "10.50"),
        ],
        params=params(chase_cap_fraction="0", entry_chase_bps="100"),
        latency_model=StaticLatencyModel(insert_latency_nanos=500_000_000),
    )
    assert len(result.orders) == 1
    assert not any(e["action"] == "MODIFY" for e in result.events), result.events


def pending_modify_tape():
    return [
        quote(0, "10.00", "10.02"),
        trade(0, "10.01", size=10000),
        trade(1, "10.01", size=10000),
        trade(2, "10.02", size=10000),
        quote("2.1", "10.49", "10.50"),
        quote(3, "10.02", "10.03"),
        quote("3.1", "10.03", "10.04"),
        quote(9, "10.02", "10.03"),
    ]


def test_native_ttl_cancels_during_pending_modify_before_late_fill(instrument, tmp_path):
    result = replay(
        instrument,
        tmp_path,
        pending_modify_tape(),
        latency_model=StaticLatencyModel(
            insert_latency_nanos=500_000_000, update_latency_nanos=5 * SEC
        ),
    )
    assert len(result.orders) == 1
    assert result.orders[0]["status"] == "CANCELED", result.events
    assert result.orders[0]["filled_qty"] == "0"
    assert [e["ts"] for e in result.events if e["action"] == "CANCEL"] == [START + 7 * SEC]


def test_native_submit_and_modify_never_enter_float_price_gateway(
    instrument, tmp_path, monkeypatch
):
    def forbid_float(*_args, **_kwargs):
        raise AssertionError("float-typed make_price gateway entered")

    monkeypatch.setattr(type(instrument), "make_price", forbid_float)
    result = replay(
        instrument,
        tmp_path,
        pending_modify_tape(),
        latency_model=StaticLatencyModel(insert_latency_nanos=500_000_000),
    )
    assert len(result.orders) == 1, result.events
    assert any(e["action"] == "MODIFY" for e in result.events)
    assert result.orders[0]["price"] == "10.03"
