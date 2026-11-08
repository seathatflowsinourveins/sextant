"""The GPT r4 gate's own quote-audit witnesses at bbfc1da (#231 comment 6722007855), made
permanent by the lead's round-11 order. They are the reviewer's scratch test_quote_audit.py
(SHA-256 6d8d1854de1fc2c9...), with its audit wrappers and control arms removed and its harness
import pointed at this checkout's tape."""

from __future__ import annotations

import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.model import QuoteTick, TradeTick

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_exit_position as tp


def test_a_delayed_event_time_quote_cannot_breach(monkeypatch: pytest.MonkeyPatch) -> None:
    """R2: a quote's age is judged on the engine clock, as northstar's `quote_fresh` reads it,
    0 <= now - ts_event <= quote_max_age (exit_manager/strategy.py:2166-2169). Ten shares open on
    fresh quotes; from second 3 every quote arrives with its event 10 s behind the clock, past the
    fixture's 5 s limit. Judged on its own stamp, each was age 0: three established a crossing
    and the bid sold all ten. On the clock they are stale, so nothing sells."""
    late = tp._late

    def delay_only_after_entry(tick: QuoteTick | TradeTick, delay_ns: int) -> object:
        return late(tick, delay_ns if tick.ts_init >= tp.START + 3 * tp.NS else 0)

    monkeypatch.setattr(tp, "_late", delay_only_after_entry)
    t = tp.tape_run([tp.FLAT] * 3 + [tp.LOW] * 6, [tp.Order(0, "10")], quote_delay_ns=10 * tp.NS)
    assert tp._sold(t) == 0 and t.net == 10


def test_a_stale_bar_cannot_preserve_an_obsolete_arming_confirmation() -> None:
    """R1: X3 confirmation holds only until a later minute closes below, and an unavailable quote
    stays unarmed (ADR-0005:29). The minute at 60 s confirms on a 101.00 close over a fresh quote,
    but the bid is below the armed trigger. The minute at 120 s closes at 99.00, below the entry,
    with the last quote 61 s old, so it cannot be judged. Skipped, it kept the old confirmation,
    and the fresh quote at 122 s armed from it, so the 101.50 bids sold all ten. A minute that
    cannot be judged ends the pending confirmation, so nothing arms."""
    params = replace(
        tp.FIXTURE,
        prearm_buffer_fraction=Decimal("0.01"),
        gain_lock_giveback_fraction=Decimal("0.1"),
        quote_max_age_s=Decimal(1),
    )
    items: list[tp.Quote | tp.Trade] = [tp.FLAT, tp.Trade("102.00")]
    items += [tp.Trade("101.00")] * 57
    items += [tp.Quote("100.50", "100.52"), tp.Trade("101.00")]
    items += [tp.Trade("99.00")] * 61
    items += [tp.Quote("102.50", "102.52")]
    items += [tp.Quote("101.50", "101.52")] * 7
    t = tp.tape_run(items, [tp.Order(0, "10")], params)
    assert "armed" not in tp._kinds_of(t)
    assert tp._sold(t) == 0 and t.net == 10


def test_a_future_stamped_quote_cannot_breach(monkeypatch: pytest.MonkeyPatch) -> None:
    """R2's lower bound, from the same pin: `quote_fresh` needs 0 <= now - ts_event, so a quote
    stamped after the engine clock is never fresh (exit_manager/strategy.py:2169). The same tape
    as above, but from second 3 every quote's event is 10 s ahead of the clock. Judged on its own
    stamp, each was age 0 and the bid sold all ten. Ahead of the clock, it is not fresh, so
    nothing sells."""
    late = tp._late

    def ahead_after_entry(tick: QuoteTick | TradeTick, delay_ns: int) -> object:
        return late(tick, -delay_ns if tick.ts_init >= tp.START + 3 * tp.NS else 0)

    monkeypatch.setattr(tp, "_late", ahead_after_entry)
    t = tp.tape_run([tp.FLAT] * 3 + [tp.LOW] * 6, [tp.Order(0, "10")], quote_delay_ns=10 * tp.NS)
    assert tp._sold(t) == 0 and t.net == 10


def test_a_quote_newer_than_a_backdated_print_never_anchors_h(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dsh review at bbfc1da (5818051233, #266): an anchor made at an observation takes only
    a quote that existed then, quote_ns <= the observation's ts_event. northstar likewise compares
    quote and observation stamps before it judges, never executing a newly earned trigger against
    a preceding quote (exit_manager/strategy.py:1826-1827). The O6 skew: the 102.00 quote is
    stamped 2 s, and the 101.00 print that makes H is stamped 1.9 s but received at 3 s. H's bid
    is unknown, so the raise is judged against the fresh 100.70 bid, and H minus the trail,
    100.80, stays out. Anchored on the later 102.00 bid, the trigger rose into the bid and sold."""
    late = tp._late

    def backdate_the_high(tick: QuoteTick | TradeTick, delay_ns: int) -> object:
        if isinstance(tick, TradeTick) and tick.ts_init == tp.START + 3 * tp.NS:
            stamped = tick.ts_init - 1_100_000_000
            return TradeTick(
                tick.instrument_id,
                tick.price,
                tick.size,
                tick.aggressor_side,
                tick.trade_id,
                stamped,
                tick.ts_init,
            )
        return late(tick, delay_ns)

    monkeypatch.setattr(tp, "_late", backdate_the_high)
    items: list[tp.Quote | tp.Trade] = [tp.Trade("100.00"), tp.Quote("100.00", "100.02")]
    items += [tp.Quote("102.00", "102.02"), tp.Trade("101.00")]
    items += [tp.Quote("100.70", "100.72")] * 10
    t = tp.tape_run(items, [tp.Order(0, "1", price="100.02")])  # one share: each print fills one
    assert t.net == 1 and tp._sold(t) == 0
    assert not any(e["event"].startswith("breach_sell") for e in t.events)


def test_a_quote_newer_than_a_late_bar_never_sets_its_arming_level() -> None:
    """#266 at `on_bar`: the minute ending at 60 s arrives as an external bar at 61.5 s, after a
    quote stamped 61 s. The arming level's noise floor must come from a quote that existed at
    the bar's close, so that later quote cannot set it. The minute is not judged and confirms
    nothing, so nothing arms. Read from the 61 s quote, the minute confirmed and the engine
    armed at the next quote."""
    from nautilus_trader.model import Bar, BarType, Price, Quantity

    bar_type = f"{tp.EQUITY.id}-1-MINUTE-LAST-EXTERNAL"
    px = Price.from_str("5.06")
    late = Bar(
        BarType.from_str(bar_type),
        px,
        px,
        px,
        px,
        Quantity.from_str("100"),
        tp.START + 60 * tp.NS,
        tp.START + 61 * tp.NS + tp.NS // 2,
    )
    items: list[tp.Quote | tp.Trade] = [tp.Quote("5.00", "5.01")]
    items += [tp.Quote("5.06", "5.07"), tp.Trade("5.06")] * 45
    t = tp.tape_run(items, [tp.Order(0, "10")], tp.STARTS, bars=[late], bar_type=bar_type)
    assert "armed" not in tp._kinds_of(t) and tp._sold(t) == 0 and t.net == 10
