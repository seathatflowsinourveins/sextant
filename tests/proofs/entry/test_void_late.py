"""Late prints only refuse: VWAP stays untrusted, an in-span run restarts, nothing re-forms."""

from decimal import Decimal as D

import pytest
from nautilus_trader.model import InstrumentId

from sextant.entry.signals import Extension

from .conftest import SEC, START, quote, trade
from .test_delta_gate import receipt, reclaim_tape
from .test_late_controls import native, tape
from .test_replay import replay
from .test_signals import arm, extended_state, feed, state

LATCH, RESTART = "late print: VWAP untrusted", "late print: VWAP untrusted; run restarted"


@pytest.mark.parametrize("price", ["9.95", "10.01", "11.00"])
@pytest.mark.parametrize(
    ("at", "delayed"), [("0", True), ("0.5", True), ("0", False), ("0.5", False)]
)
def test_late_print_in_first_leg_span_restarts_the_run_without_ingestion(price, at, delayed):
    s = state()
    arm(s)
    feed(s, 0, "10.01")
    feed(s, 1, "10.01")
    before = s.dollars, s.volume, s.last
    lag = int((D("1.5") - D(at)) * SEC) if delayed else 0
    tick = trade(at, price, lag=lag, identity="late")
    assert not s.on_trade(tick, now=START + 1_500_000_000)
    assert s.void_reason == RESTART
    assert (s.dollars, s.volume, s.last) == before
    assert s.surge is not None and not s.run and s.vwap is None
    feed(s, 2, "10.02")
    feed(s, 3, "10.02")
    # Uncredited: (t0, t1, t2) was ready before the restart; only fresh prints count now.
    assert not s.first_leg_ready(D("10.02"), START + 3 * SEC)
    feed(s, 4, "10.02")
    assert s.first_leg_ready(D("10.02"), START + 4 * SEC)
    assert s.run[0].ts_event == START + 2 * SEC and s.vwap is None and not s.failure


@pytest.mark.parametrize(("price", "kept"), [("9.95", False), ("11.00", True)])
def test_same_timestamp_sibling_with_latency_is_ingested_like_upstream(price, kept):
    s = state()
    arm(s)
    feed(s, 0, "10.01")
    feed(s, 1, "10.01")
    sibling = trade(1, price, lag=30_000_000, identity="sweep-b")
    assert s.on_trade(sibling, now=sibling.ts_init)
    assert s.void_reason is None and s.last == sibling and s.volume == 300
    assert bool(s.run) is kept  # N1 alone decides: 9.95 is lower and under the quiet price
    again = trade(1, price, lag=60_000_000, identity="sweep-b")
    assert not s.on_trade(again, now=again.ts_init)  # exact redelivery of the current group
    assert s.void_reason is None and s.volume == 300 and s.vwap is not None


@pytest.mark.parametrize("lag", [0, 30_000_000], ids=["zero-lag", "ordinary-latency"])
def test_native_same_timestamp_sweeps_keep_first_leg_and_reclaim(instrument, tmp_path, lag):
    sweep = [trade(1, "10.02", size=10000, identity=f"sweep-{i}", lag=lag) for i in "ab"]
    data = [quote(0, "10.00", "10.02"), trade(0, "10.01", size=10000, lag=lag), *sweep]
    data += [trade(2, "10.03", size=10000, lag=lag), quote(3, "10.00", "10.02")]
    first = replay(instrument, tmp_path / "first", sorted(data, key=lambda t: t.ts_init))
    held = tape([(0, "10.00"), (1, "11.00"), (2, "9.99"), (3, "10.03"), (4, "10.04")])
    held += [trade(at, price, lag=lag) for at, price in ((5, "10.05"), (6, "10.02"))]
    held += [trade(7, "10.02", identity=f"hold-{i}", lag=lag) for i in "ab"]
    held += [trade(8, "10.03", lag=lag), quote("7.9", "10.02", "10.03")]
    reclaim = native(instrument, tmp_path / "reclaim", held, D(8) + D(lag) / SEC)
    for result in (first, reclaim):
        assert not any(e["action"] == "VOID" for e in result.events), result.events
        assert [o["status"] for o in result.orders] == ["FILLED"], result.events


@pytest.mark.parametrize("price", ["9.97", "10.02", "10.04", "11.00"])
def test_late_print_inside_touch_or_hold_voids_the_whole_candidate(price):
    s = extended_state()
    for at, value in ((3, "10.03"), (4, "10.04"), (5, "10.05"), (6, "10.02"), (7, "10.02")):
        feed(s, at, value)
    before = s.dollars, s.volume
    late = trade("6.5", price, lag=800_000_000)
    assert not s.on_trade(late, now=late.ts_init)
    assert s.void_reason == LATCH
    assert (s.dollars, s.volume) == before and s.vwap is None
    assert not s.reclaim_ready(D("10.03"), D("0.10"), late.ts_init, covered_flow=True)
    for at in (8, 9, 10):
        feed(s, at, "10.03")
        assert s.extension is Extension.UNKNOWN and s.touch is None and not s.confirmed
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
    voids = [(e["reason"], e["ts"]) for e in result.events if e["action"] == "VOID"]
    if kind == "in-span":
        assert not result.orders, result.events
        assert voids == [(RESTART, START + 1_500_000_000)]
    else:
        # N1: the first leg is exempt from N2, so a pre-span old print untrusts VWAP only.
        assert len(result.orders) == 1 and result.orders[0]["status"] == "FILLED"
        assert voids == ([(LATCH, START + 1_500_000_000)] if kind == "old" else [])


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
def test_old_redelivery_cannot_be_told_from_a_missing_print_so_it_latches(
    instrument, tmp_path, duplicate
):
    data = [trade(-200, "10.00", size=10000), *reclaim_tape(), quote("7.9", "10.02", "10.03")]
    if duplicate:
        data.append(trade(-200, "10.00", size=10000, lag=207_300_000_000))
    result = native(instrument, tmp_path, data, 8)
    assert not result.failed and len(result.orders) == (0 if duplicate else 1), result.events
    assert [e["reason"] for e in result.events if e["action"] == "VOID"] == [LATCH] * duplicate


@pytest.mark.parametrize("resent", ["0", "1"])
def test_a_resent_admitted_print_drops_like_upstream_without_restart(instrument, tmp_path, resent):
    data = [quote(0, "10.00", "10.02")] + [trade(at, "10.01", size=10000) for at in (0, 1, 2)]
    data += [trade(resent, "10.01", size=10000, lag=(2 - int(resent)) * SEC + 50_000_000)]
    data += [quote("2.1", "10.00", "10.02")]
    result = replay(instrument, tmp_path, sorted(data, key=lambda t: t.ts_init))
    assert not any(e["action"] == "VOID" for e in result.events), result.events
    assert [o["status"] for o in result.orders] == ["FILLED"], result.events


@pytest.mark.parametrize("skew", [None, 1, 2_000_000], ids=["ordered", "skew-1ns", "skew-2ms"])
@pytest.mark.parametrize("setup", ["reclaim-hold-veto", "first-leg-lower"])
def test_a_clock_skewed_veto_drops_and_refuses_instead_of_vanishing(
    instrument, tmp_path, setup, skew
):
    # ts_init >= ts_event is not guaranteed; a skewed print is dropped like a late one.
    lag = 0 if skew is None else -skew
    if setup == "reclaim-hold-veto":
        data = [*reclaim_tape(), trade("6.5", "9.97", lag=lag), quote("7.9", "10.02", "10.03")]
        result = native(instrument, tmp_path, data, 8)
    else:
        data = [quote(0, "10.00", "10.02")] + [
            trade(at, p, size=10000) for at, p in ((0, "10.01"), (1, "10.02"), (2, "10.03"))
        ]
        data += [trade("1.5", "9.95", lag=lag), quote("2.1", "10.00", "10.02")]
        result = replay(instrument, tmp_path, sorted(data, key=lambda t: t.ts_init))
    assert result.orders == [], result.events
    assert any(e["action"] == "VOID" for e in result.events) is (skew is not None)
