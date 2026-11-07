"""R86 (#129 §4 item 1): the exit engine protects the native position, not its first fill.

Offline BacktestEngine witnesses on scripted quotes (sextant.backtest.exit_position_witness). The
fixture's 100.02 entry has an initial trigger of 99.81996 (buffer 0.002 x entry), so bids of 99.50
breach it, and three of them over 2 s persist (ADR-0005 X4).
"""

import dataclasses
from decimal import Decimal as D

from sextant.backtest.exit_position_witness import Buy, Quote, Result, run
from sextant.backtest.exit_witness import FIXTURE

FLAT = Quote("100.00", "100.02")
LOW = Quote("99.50", "99.52")
THIN = Quote("100.00", "100.02", ask_size="6")


def _kinds(r: Result) -> list[str]:
    return [e["event"] for e in r.events]


def _breach_sells(r: Result) -> list[dict[str, str]]:
    return [e for e in r.events if e["event"].startswith("breach_sell")]


def test_one_fill_protects_the_position_and_sells_it_flat() -> None:
    r = run([FLAT] * 5 + [LOW] * 6, [Buy(0, "10")])
    assert [(q, p) for _c, q, p in r.buy_fills] == [("10", "100.02")]
    assert _kinds(r)[:2] == ["protected_from_fill", "initial_trigger"]
    assert D(r.events[0]["qty"]) == 10
    (sell,) = _breach_sells(r)
    assert D(sell["qty"]) == 10
    assert [(D(q), D(f)) for _c, q, f in r.sells] == [(D(10), D(10))]
    assert r.position == 0 and _kinds(r)[-1] == "flat"
    assert not r.paused and r.pages == []


def test_an_entry_filled_6_then_4_is_protected_as_10_and_the_breach_sell_covers_10() -> None:
    r = run([THIN, THIN] + [FLAT] * 3 + [LOW] * 6, [Buy(0, "10")])
    assert [(q, p) for _c, q, p in r.buy_fills] == [("6", "100.02"), ("4", "100.02")]
    assert len({c for c, _q, _p in r.buy_fills}) == 1  # one entry order, two fills
    assert "add_paused" not in _kinds(r) and r.pages == []
    grown = [
        D(e["qty"]) for e in r.events if e["event"] in ("protected_from_fill", "protected_qty")
    ]
    assert grown == [D(6), D(10)]
    (sell,) = _breach_sells(r)
    assert D(sell["qty"]) == 10
    assert [(D(q), D(f)) for _c, q, f in r.sells] == [(D(10), D(10))]
    assert r.position == 0


def test_a_buy_from_a_different_order_pauses_the_symbol_and_pages() -> None:
    """ADR-0007:17: an owner add to a strategy-held symbol pauses it and pages."""
    r = run([FLAT] * 5 + [LOW] * 6, [Buy(0, "10"), Buy(2, "5")])
    assert len({c for c, _q, _p in r.buy_fills}) == 2
    assert r.paused and r.pages == ["owner_add"]
    assert _kinds(r).count("add_paused") == 1
    assert r.sells == [] and r.position == 15  # paused: the later breach sells nothing


def test_a_close_then_a_re_entry_is_protected_again() -> None:
    again, lower = Quote("99.60", "99.62"), Quote("99.30", "99.32")
    r = run([FLAT] * 5 + [LOW] * 3 + [again] * 3 + [lower] * 6, [Buy(0, "10"), Buy(9, "10")])
    entries = [D(e["entry"]) for e in r.events if e["event"] == "protected_from_fill"]
    assert entries == [D("100.02"), D("99.62")]
    assert len(_breach_sells(r)) == 2 and _kinds(r).count("flat") == 2
    assert [(D(q), D(f)) for _c, q, f in r.sells] == [(D(10), D(10))] * 2
    assert r.position == 0 and not r.paused and r.pages == []


def test_the_decimal_basis_is_the_entry_orders_avg_px() -> None:
    """rc7's Position.avg_px_open is an f64, so the basis is Order.avg_px (MIGRATION_V2.md:480)."""
    r = run([THIN] + [FLAT] * 4 + [LOW] * 6, [Buy(0, "10", market=True)])
    assert [(q, p) for _c, q, p in r.buy_fills] == [("6", "100.02"), ("4", "100.03")]
    (avg,) = r.buy_avg_px.values()
    assert type(avg) is D and avg == D("100.024")
    bases = [e["entry"] for e in r.events if e["event"] in ("protected_from_fill", "protected_qty")]
    assert [D(b) for b in bases] == [D("100.02"), avg]
    (sell,) = _breach_sells(r)
    assert D(sell["qty"]) == 10 and r.position == 0


def test_a_same_order_fill_after_the_breach_sell_is_still_covered_until_flat() -> None:
    """The entry's remainder fills while the managed sell rests. The venue resizes that
    reduce-only sell to the position (orders/advanced.md:228-231), so the one exit covers all 10.

    The protected quantity follows the native position throughout, and one sell works at a time
    (ADR-0007:19). The chase is off (#98). Each later bid moves up through the resting limit,
    because an L1 maker fill needs a market move (fill-prices-and-matching.md, "L1 books").
    Each move fills the bid's displayed 2."""
    wide = Quote("99.50", "100.05", bid_size="2")  # breaches; the ask is above the entry limit
    through = Quote("99.60", "100.01", bid_size="2")  # fills the entry's remaining 4
    rising = [Quote(f"99.6{d}", "100.05", bid_size="2") for d in (2, 4, 6, 8)]
    no_chase = dataclasses.replace(FIXTURE, chase_cap_fraction=None, chase_min_interval_s=None)
    r = run([THIN] + [wide] * 3 + [through] + rising, [Buy(0, "10")], no_chase)
    assert [(q, p) for _c, q, p in r.buy_fills] == [("6", "100.02"), ("4", "100.02")]
    assert "add_paused" not in _kinds(r) and r.pages == []
    (sell,) = _breach_sells(r)
    assert D(sell["qty"]) == 6  # the position when the breach persisted
    # The late 4 joined the protected position: the record after its fill adds exactly 4.
    i = _kinds(r).index("entry_fill")
    before = [D(e["qty"]) for e in r.events[:i] if e["event"].startswith("protected_")][-1]
    assert r.events[i + 1]["event"] == "protected_qty"
    assert D(r.events[i + 1]["qty"]) == before + 4
    assert [(D(q), D(f)) for _c, q, f in r.sells] == [(D(10), D(10))]
    assert r.max_working_sells == 1 and r.position == 0 and _kinds(r)[-1] == "flat"


def test_every_position_event_follows_its_order_fill() -> None:
    """The order the engine relies on: rc7 docs/concepts/events/index.md:123-160."""
    r = run([THIN, THIN] + [FLAT] * 3 + [LOW] * 6, [Buy(0, "10")])
    assert r.calls == [
        "filled_buy",
        "position_opened",
        "filled_buy",
        "position_changed",
        "filled_sell",
        "position_closed",
    ]
