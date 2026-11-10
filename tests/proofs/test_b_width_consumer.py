"""B arms and re-arms its trail at the stored per-symbol width (D-30, consumer); fixture prices."""

import random
from decimal import Decimal

from test_b_dynamic_width import (
    INTERVAL_NS,
    RTH_NS,
    SEC,
    FakeBars,
    FakeQuotes,
    calm,
    held,
    make,
    quote,
    reasons,
    steady_bars,
)
from test_b_protector import api_position

from sextant.paper.b_width import MAX_TRAIL_FRACTION, trail_percent

FLOOR = Decimal("0.001")  # WIDTH_ROWS' alpaca_min_trail_fraction
NATIVE = "dynamic_width_native_fallback"


def sent_percent(request) -> Decimal:
    """The one float the broker request carries, read back exactly as Decimal."""

    assert isinstance(request.trail_percent, float)
    return Decimal(str(request.trail_percent))


def rearm(p, client) -> None:
    client.orders = []  # the broker lost the trail: the existing code re-arms it
    p.reconcile()


def test_the_sent_percent_stays_inside_floor_and_cap_and_within_one_rounding_step():
    rng = random.Random(20261110)  # noqa: S311 - a seeded fixture sweep, not a secret
    for _ in range(300):
        close = Decimal(rng.randint(100, 50_000)) / 100
        bar_range = (close * Decimal(rng.randint(0, 2_000)) / 100_000).quantize(Decimal("0.01"))
        spread = Decimal(rng.randint(1, 50)) / 100
        clock = [RTH_NS]
        bars = FakeBars({"AAPL": steady_bars(RTH_NS, bar_range=str(bar_range), close=str(close))})
        quotes = FakeQuotes([quote(str(close), str(close + spread), RTH_NS)])
        client = held("AAPL")
        p = make(client, bars, quotes, clock)
        p.reconcile()
        assert p.refresh_widths_when_due() is True
        stored = p.trail_width("AAPL")
        assert isinstance(stored, Decimal) and "AAPL" in p._width
        rearm(p, client)

        sent = sent_percent(client.submitted[-1])
        assert FLOOR * 100 <= sent <= MAX_TRAIL_FRACTION * 100
        assert Decimal(0) <= sent - stored * 100 < Decimal("0.01")
        assert sent == trail_percent(stored)
        assert client.cancelled == [] and client.replaced == []


def test_with_no_width_stored_b_arms_at_native_and_pages_once_per_symbol_per_episode():
    clock = [RTH_NS]
    bars, quotes = calm(RTH_NS)
    client = held("AAPL")
    p = make(client, bars, quotes, clock)
    p.reconcile()
    rearm(p, client)
    assert [sent_percent(r) for r in client.submitted] == [Decimal("2.5")] * 2
    assert reasons(p) == [NATIVE]  # one page for two native arms

    p.refresh_widths_when_due()  # a stored width ends the episode
    rearm(p, client)
    assert sent_percent(client.submitted[-1]) == Decimal("0.18")
    assert reasons(p) == [NATIVE]

    client.positions = []  # flat: the stored width goes with the position
    p.reconcile()
    client.positions = [api_position("10")]
    client.orders = []
    p.reconcile()  # held again with no width: a new episode, one new page
    rearm(p, client)
    assert sent_percent(client.submitted[-1]) == Decimal("2.5")
    assert reasons(p) == [NATIVE, NATIVE]


def test_a_changed_stored_width_with_a_working_trail_cancels_and_replaces_nothing():
    clock = [RTH_NS]
    bars, quotes = calm(RTH_NS)
    client = held("AAPL")
    p = make(client, bars, quotes, clock)
    p.reconcile()
    working = list(client.orders)
    for bar_range in ("0.12", "0.30", "0.06"):
        clock[0] += INTERVAL_NS
        bars.rows["AAPL"] = steady_bars(clock[0], bar_range=bar_range)
        quotes.quotes = [quote("200.00", "200.01", clock[0])]
        p.refresh_widths_when_due()
        p.reconcile()
        p.watch(clock[0])
    assert p.trail_width("AAPL") == FLOOR  # 3 x 0.06 / 200 is under the floor
    assert client.orders == working and len(client.submitted) == 1
    assert client.cancelled == [] and client.replaced == []
    assert "cancel_order_by_id" not in client.calls


def test_the_state_line_prints_the_width_and_its_source_and_reprints_when_it_changes():
    clock = [RTH_NS]
    bars, quotes = calm(RTH_NS)
    client = held("AAPL")
    p = make(client, bars, quotes, clock)
    p.reconcile()
    p.watch(clock[0])
    assert "width=2.50 width_src=native" in p.states[-1]
    seen = len(p.states)
    p.watch(clock[0] + SEC)
    assert len(p.states) == seen  # unchanged: no reprint

    p.refresh_widths_when_due()
    p.watch(clock[0] + 2 * SEC)
    assert "width=0.18 width_src=computed" in p.states[-1]
    seen = len(p.states)

    clock[0] += INTERVAL_NS
    bars.rows["AAPL"] = steady_bars(clock[0], bar_range="0.30")
    quotes.quotes = [quote("200.00", "200.01", clock[0])]
    p.refresh_widths_when_due()
    p.watch(clock[0])
    assert len(p.states) == seen + 1
    assert "width=0.45 width_src=computed" in p.states[-1]
