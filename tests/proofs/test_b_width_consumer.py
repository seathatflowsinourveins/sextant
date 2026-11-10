"""B arms and re-arms its trail at the stored per-symbol width (D-30, consumer); fixture prices."""

import contextlib
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
from test_b_protector import api_position, b_account

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


# --- Codex max on 0cc47b7, P1: a failing page sink never stops the protective submit ----------


def test_a_failing_page_sink_never_keeps_the_native_arm_from_being_sent(monkeypatch):
    from test_b_dynamic_width import width_params

    from sextant.paper import b_protector_main as entry
    from sextant.paper.b_protector import Protector

    def broken_print(*_args, **_kwargs):
        raise BrokenPipeError("closed fixture page sink")

    monkeypatch.setattr(entry, "print", broken_print, raising=False)
    client = held("AAPL")
    p = Protector(
        client, b_account(), width_params(), now_ns=lambda: RTH_NS, on_page=entry._print_page
    )
    with contextlib.suppress(BrokenPipeError):
        p.reconcile()
    assert [request.qty for request in client.submitted] == [10]  # 10 shares, one trail


def test_a_recovered_page_sink_neither_resubmits_nor_repeats_the_fallback_page():
    from test_b_dynamic_width import width_params

    from sextant.paper.b_protector import Protector

    failed = []

    def broken_page(page):
        failed.append(page.reason)
        raise BrokenPipeError("closed fixture page sink")

    client = held("AAPL")
    p = Protector(client, b_account(), width_params(), now_ns=lambda: RTH_NS, on_page=broken_page)
    p.reconcile()  # the sink's failure is counted, never raised into the arm path
    assert (len(client.submitted), p.page_sink_failures) == (1, 1)
    p._on_page = None
    p.reconcile()
    assert len(client.submitted) == 1
    assert failed == reasons(p) == [NATIVE]


def cover_run(held_count: int, stored: int, lose: bool, add: bool, sink) -> list:
    """Arms, a width refresh, a lost-trail re-arm and an owner add, with the given page sink."""

    from test_b_dynamic_width import width_params

    from sextant.paper.b_protector import Protector

    symbols = ("AAPL", "MSFT", "AMD")[:held_count]
    clock = [RTH_NS]
    bars = FakeBars({s: steady_bars(RTH_NS) for s in symbols[:stored]})
    quotes = FakeQuotes([quote("200.00", "200.01", RTH_NS, s) for s in symbols])
    client = held(*symbols)
    p = Protector(
        client,
        b_account(),
        width_params(),
        now_ns=lambda: clock[0],
        bars=bars,
        quotes=quotes,
        on_page=sink,
    )
    covers = []

    def step(action) -> None:
        with contextlib.suppress(BrokenPipeError):  # a page outside the arm path may still raise
            action()
        covers.append(sorted((o.symbol, str(o.qty)) for o in client.orders))

    step(p.reconcile)
    step(p.refresh_widths_when_due)
    if lose:
        client.orders = []
        step(p.reconcile)
    if add:
        client.positions = [api_position("15", s) for s in symbols]
        step(p.reconcile)
    return [*covers, [(r.symbol, r.qty) for r in client.submitted]]


def test_with_a_page_sink_that_always_raises_every_cover_equals_the_normal_runs():
    """The P1 rule as a property: no raising call between the chosen percent and the submit."""

    def always_raises(page):
        raise BrokenPipeError("closed fixture page sink")

    for held_count in (1, 2, 3):
        for stored in range(held_count + 1):
            for lose in (False, True):
                for add in (False, True):
                    case = (held_count, stored, lose, add)
                    normal = cover_run(*case, sink=None)
                    assert cover_run(*case, sink=always_raises) == normal, case
