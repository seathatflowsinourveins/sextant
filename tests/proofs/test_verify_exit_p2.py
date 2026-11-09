"""Independent reproductions of the unrefuted review findings on PR #2 (09e579f).

Each test asserts a rule the repository already states -- docs/manifest.md's exit rows, ADR-0005
(the 60-second cancel deadline, the terminal cancel before a hand-off), ADR-0007 (custody and one
writer) and ADR-0018's committed surfaces -- against the tape harness in
``tests/proofs/test_exit_position.py``. They are expected to FAIL on 09e579f: that is the point.
Nothing here changes the engine or fits the test to the code; the table in VERIFY-TABLE.md maps
each test to its finding (O*, C*, M*).
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.config import RiskEngineConfig
from nautilus_trader.execution import StaticLatencyModel
from nautilus_trader.model import (
    AggressorSide,
    OrderSide,
    Price,
    Quantity,
    QuoteTick,
    TradeId,
    TradeTick,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_exit_position as tp

from sextant.exits.policy import ExitParams

NS = tp.NS
START = tp.START
PRE = tp.PRE
CLOSE = START + 23_400 * NS  # 2026-11-06 16:00:00 ET


def _breach_sell_seconds(t: tp.Tape, start: int) -> list[int]:
    return sorted(
        {(int(e["ts"]) - start) // NS for e in t.events if e["event"].startswith("breach_sell")}
    )


def _submitted(t: tp.Tape, name: str) -> list[int]:
    return [s for s, order, event in t.timeline if order == name and event == "OrderSubmitted"]


def _cancelled(t: tp.Tape, name: str) -> list[int]:
    return [s for s, order, event in t.timeline if order == name and event == "OrderCanceled"]


# --------------------------------------------------------------------------------------------
# O1: a 16:00 quote-first hand-off cancels the resting RTH sell and never re-sends it.
# --------------------------------------------------------------------------------------------
def test_o1_a_1600_quote_handover_leaves_no_working_sell() -> None:
    """ADR-0005's hand-off keeps the crossing: ``_handover`` cancels the resting sell, and its
    terminal cancel must send the exit again (the same rule the existing 09:30 hand-off test
    asserts). At 16:00 a quote alone switches the session; 30 quotes follow with no print. The
    bid shows no size, so the sell rests whatever its collar (X5, PR 3)."""
    low = tp.Quote("99.50", "99.52", bid_size="0")
    items = [tp.FLAT, tp.Trade("100.02")] + [low] * 18 + [low] + [low] * 30
    t = tp.tape_run(items, [tp.Order(0, "10")], session="rth", start=CLOSE - 20 * NS)
    # Second 4 crosses; second 20 is 16:00:00. The cancel has to go out as engine-SELL-2.
    assert _breach_sell_seconds(t, CLOSE - 20 * NS) == [4, 20]
    assert t.status.get("engine-SELL-2") is not None
    assert t.pages == []


# --------------------------------------------------------------------------------------------
# O2: the foreign-order freeze returns before the house's own orders are canceled.
# --------------------------------------------------------------------------------------------
def _freeze_tape() -> tuple[list[tp.Quote | tp.Trade], list[tp.Order]]:
    thin = tp.Quote("100.00", "100.02", ask_size="6")
    wide = tp.Quote("99.50", "100.55")
    back = tp.Quote("100.48", "100.50")
    items: list[tp.Quote | tp.Trade] = [thin, *[wide] * 4, *[back] * 6]
    script = [tp.Order(0, "10", price="100.50"), tp.Order(1, "5", price="99.00", owner=True)]
    return items, script


def test_o2_the_foreign_freeze_still_cancels_the_house_entry_remainder() -> None:
    """ADR-0007's freeze does not suspend ADR-0005's cancel of a partial entry: the house's BUY
    fills 6, the owner's resting BUY pages ``foreign_order``, and the remaining 4 must not keep
    buying the same rising tape after the pause (they do: net 10 instead of 6)."""
    items, script = _freeze_tape()
    t = tp.tape_run(items, script)
    assert t.pages == ["foreign_order"] and t.paused
    assert t.status["house-1"] == "CANCELED"
    assert sum(D(q) for _s, side, q, _p, _o in t.fills if side == "BUY") == D(6)


# --------------------------------------------------------------------------------------------
# O3: pages are deduped by reason for the engine's lifetime, so a later refusal is silent.
# --------------------------------------------------------------------------------------------
def test_o3_every_sell_refusal_pages_even_in_a_later_cycle() -> None:
    """``test_each_page_reaches_a_person_once_as_an_error_line`` means one line per event, not one
    per reason forever. Two denied managed sells -- one per cycle, after a verified flat cleared
    the first pause -- are two events and need two ERROR lines and two page events."""
    low = tp.Quote("99.50", "99.52")
    items = [tp.FLAT] * 3 + [low] * 13 + [tp.FLAT] * 11 + [tp.FLAT] * 3 + [low] * 11
    script = [
        tp.Order(0, "10"),
        tp.Order(16, "10", side=OrderSide.SELL, owner=True),
        tp.Order(27, "10"),
    ]
    risk = RiskEngineConfig(bypass=False, max_order_submit_rate="1/00:00:10")
    tp.Scripted.paged = tp.Paged()
    t = tp.tape_run(items, script, risk=risk)
    refusals = [e for e in t.events if e.get("reason") == "sell_refused"]
    assert len(refusals) == 2
    assert len(tp.Scripted.paged.errors) == 2


# --------------------------------------------------------------------------------------------
# O4: the 60-second deadline is measured from the crossing, not from the hand-off's own cancel.
# --------------------------------------------------------------------------------------------
def test_o4_a_routine_handover_does_not_page_the_old_cancel_deadline() -> None:
    """The pre-market crossing happened at 09:28:35; at 09:30:00 ``_handover`` cancels the resting
    sell. Measuring ADR-0005:36's 60 seconds from the old crossing makes a routine hand-off page
    ``partial_entry_cancel_timeout`` on the same tick, before the cancel is even terminal."""
    items: list[tp.Quote | tp.Trade] = [tp.Quote("100.00", "100.02")]
    for i in range(1, 90 + 20):
        px = D("99.80") - D("0.01") * i
        items.append(
            tp.Trade(f"{px:.2f}")
            if i % 2
            else tp.Quote(f"{px - D('0.40'):.2f}", f"{px + D('0.20'):.2f}")
        )
    t = tp.tape_run(items, [tp.Order(0, "100")], session="outside", start=START - 90 * NS)
    assert "partial_entry_cancel_timeout" not in t.pages


# --------------------------------------------------------------------------------------------
# O5: outside RTH the awaiting_quote hold is released only by a print, not by a fresh quote.
# --------------------------------------------------------------------------------------------
def test_o5_a_fresh_quote_releases_the_outside_awaiting_quote_hold() -> None:
    """The crossing persists at second 6 while the quote is stale, so the exit waits
    (``awaiting_quote``). Fresh quotes arrive from second 16 and keep arriving for 30 s with no
    print. ADR-0005's quote gate is about the quote being fresh, not about a trade printing."""
    items: list[tp.Quote | tp.Trade] = [tp.Quote("100.00", "100.02")] + [tp.Trade("100.02")] * 3
    items += [tp.Trade(f"{D('99.70') - D('0.10') * i}") for i in range(12)]
    items += [tp.Quote("98.40", "98.42")] * 30
    t = tp.tape_run(items, [tp.Order(0, "10")], session="outside", start=PRE)
    sells = _breach_sell_seconds(t, PRE)
    assert sells and sells[0] <= 17


# --------------------------------------------------------------------------------------------
# O6: `_session` has no monotonic guard, so one backward-stamped print flips the session back.
# --------------------------------------------------------------------------------------------
def _straddle_tape() -> list[tp.Quote | tp.Trade]:
    items: list[tp.Quote | tp.Trade] = [tp.Quote("100.00", "100.02")]
    for i in range(1, 40):
        px = D("99.80") - D("0.01") * i
        items.append(
            tp.Trade(f"{px}")
            if i % 2
            else tp.Quote(f"{px - D('0.40')}", f"{px + D('0.20')}", bid_size="0")
        )
    return items


def test_o6_a_backward_stamped_print_never_resends_the_cancelled_exit() -> None:
    """Feeds are ordered by ts_init; a print received at 09:30:01 can carry a ts_event at
    09:29:59.9. The engine must not treat that skew as another session boundary and cancel/resend
    the exit again: the outcome has to match the same tape with monotonic timestamps."""
    orig = tp._tick

    def skewed(start: int, i: int, item: tp.Quote | tp.Trade) -> object:
        tick = orig(start, i, item)
        if i == 21 and isinstance(item, tp.Trade):
            ts_event = start + 20 * NS - 100_000_000  # 09:29:59.9, received at second 21
            ts_init = start + 21 * NS
            return TradeTick(
                tp.EQUITY.id,
                Price.from_str(item.price),
                Quantity.from_str("1"),
                AggressorSide.BUY,
                TradeId(str(i)),
                ts_event,
                ts_init,
            )
        return tick

    mono = tp.tape_run(
        _straddle_tape(), [tp.Order(0, "100")], session="outside", start=START - 20 * NS
    )
    tp._tick = skewed
    try:
        skew = tp.tape_run(
            _straddle_tape(), [tp.Order(0, "100")], session="outside", start=START - 20 * NS
        )
    finally:
        tp._tick = orig

    def names(t: tp.Tape) -> list[str]:
        return sorted({n for _s, n, _e in t.timeline if n.startswith("engine-SELL")})

    assert names(skew) == names(mono)
    assert [_cancelled(skew, n) for n in names(skew)] == [_cancelled(mono, n) for n in names(mono)]
    # The engine's own decisions match. The fills can't: rc8's venue never fills an order
    # accepted at 09:30:00 against a print stamped 09:29:59.9, so that one share stays unsold.
    assert _breach_sell_seconds(skew, START - 20 * NS) == _breach_sell_seconds(
        mono, START - 20 * NS
    )
    assert skew.net - mono.net == 1


# --------------------------------------------------------------------------------------------
# O7: `_session` calls the XNYS calendar on every quote and trade.
# --------------------------------------------------------------------------------------------
def test_o7_the_session_is_not_recomputed_on_every_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    """A quote is already session-stamped by its own ts_event; recomputing the calendar per tick
    costs ~78 us and is 11x the rest of the tape loop. One computation per boundary (or per
    second) is enough."""
    import sextant.exits.engine as engine

    calls: list[int] = []
    orig = engine.session_at

    def counted(ts: int):
        calls.append(ts)
        return orig(ts)

    monkeypatch.setattr(engine, "session_at", counted)
    tp.tape_run([tp.FLAT] * 200, [tp.Order(0, "10")])
    assert len(calls) <= 5, f"session_at called {len(calls)} times for 200 quotes"


# --------------------------------------------------------------------------------------------
# C1: a foreign SELL is only checked on the first sell, so a resting house sell keeps selling.
# --------------------------------------------------------------------------------------------
def test_c1_an_owner_sell_while_the_house_sell_rests_never_goes_short() -> None:
    """ADR-0007's one writer and the manifest's fail-closed row: an order the house did not send
    freezes the symbol. An owner SELL LIMIT for 8 arrives while the house sell rests; the house
    must stop selling, not chase 8 more and leave the account short when the owner also fills."""
    wide = tp.Quote("99.50", "100.05", bid_size="2")  # the house sell fills 2 and rests 8
    under = tp.Quote("99.40", "100.05", bid_size="2")
    rising = [tp.Quote(f"{D('99.52') + D('0.02') * i}", "100.05", bid_size="2") for i in range(5)]
    up = tp.Quote("100.50", "100.55")
    owner_exit = tp.Order(4, "8", side=OrderSide.SELL, price="100.50", owner=True)
    items = [tp.FLAT] + [wide] * 3 + [under] + rising + [up] * 3
    t = tp.tape_run(items, [tp.Order(0, "10"), owner_exit], tp.NO_CHASE)
    assert t.net == 0, t.fills  # 10 entered, 2 + 8 sold: never a short
    assert "foreign_order" in t.pages


# --------------------------------------------------------------------------------------------
# C2: B's custody snapshot is starved after 16:00 because it hangs off on_quote -> _session.
# --------------------------------------------------------------------------------------------
def test_c3_an_owner_add_never_has_its_shares_sold_by_the_house() -> None:
    """The breach sell is still SUBMITTED at the 16:00 hand-off, so ``_handover`` neither cancels
    it nor clears it from the venue's reduce-only quantity. An owner BUY of 5 then arrives; the
    orphan sell is resized 10 -> 15 and sells the owner's 5 too (net 0, house sold 15). The house
    may only ever sell its own 10."""
    start = START + 6 * 3600 * NS + 1800 * NS - 20 * NS  # 15:59:40; second 20 is 16:00:00
    wide = tp.Quote("99.50", "100.05", bid_size="2")
    under = tp.Quote("99.40", "100.05", bid_size="2")
    rising = [tp.Quote(f"{D('99.52') + D('0.02') * i}", "100.05", bid_size="2") for i in range(10)]
    items = [tp.FLAT] * 17 + [wide] * 3 + [under] * 4 + rising
    late = StaticLatencyModel(insert_latency_nanos=1_500_000_000)
    script = [tp.Order(0, "10"), tp.Order(21, "5", price="100.05", owner=True)]
    t = tp.tape_run(items, script, tp.NO_CHASE, start=start, latency=late)
    assert "owner_add" in t.pages
    assert tp._sold(t, owner=False) <= D(10), t.fills


# --------------------------------------------------------------------------------------------
# C4: the same freeze leaves the house's partial entry buying after the pause.
# --------------------------------------------------------------------------------------------
def test_c4_a_house_entry_remainder_never_buys_after_the_foreign_freeze() -> None:
    """The custody view of O2: the freeze pages, then the house BUY's own 4-share remainder fills
    at 100.50 and becomes unprotected inventory. ``entry_fill`` after ``pause_and_page`` is the
    signature of the skipped cancel loop."""
    items, script = _freeze_tape()
    t = tp.tape_run(items, script)
    kinds = [e["event"] for e in t.events]
    assert "entry_fill" not in kinds
    assert t.status["house-1"] == "CANCELED"


# --------------------------------------------------------------------------------------------
# C5: the 16:00 hand-off waits for the next print instead of sending the retained exit.
# --------------------------------------------------------------------------------------------
def test_c5_a_1600_quote_handover_resends_the_exit_without_a_print() -> None:
    """Starting 15:59:50, the breach sell fills 2 and rests 8. The 16:00:00 quote cancels it, but
    the cancel never re-drives ``_sell``; 30 quotes pass with no print and the next sell is only
    sent at 16:00:30 on a trade. The retained crossing must go out at the hand-off."""
    start = START + 6 * 3600 * NS + 1800 * NS - 10 * NS  # 15:59:50; second 10 is 16:00:00
    wide = tp.Quote("99.50", "100.05", bid_size="2")
    under = tp.Quote("99.40", "100.05", bid_size="2")
    items = [tp.FLAT] * 3 + [wide] * 3 + [under] * 4 + [under] * 30 + [tp.Trade("99.40")]
    t = tp.tape_run(items, [tp.Order(0, "10")], tp.NO_CHASE, start=start)
    assert _submitted(t, "engine-SELL-2") == [10], t.timeline


# --------------------------------------------------------------------------------------------
# C6: the custody docs describe overrides and checks the code does not contain.
# --------------------------------------------------------------------------------------------
def test_m1_a_level_above_an_unmoved_bid_is_refused() -> None:
    """#210 cause 2: with the entry at the 2.03 ask and the bid unchanged at 2.00, the level is
    entry - buffer. A tick in the ask changes the buffer (spread term) to 0.0203, so the level
    becomes 2.0097 > 2.00 and the guard lets it through; the unchanged-ask control refuses.
    rc8 rejects a stop already in the market, so any level at or below the bid must refuse."""
    q, rest = tp.Quote("2.00", "2.03"), tp.Quote("2.00", "2.02")
    t = tp.tape_run([q, tp.Trade("2.03")] + [rest] * 10, [tp.Order(0, "10")], tp.STARTS)
    assert tp._sold(t) == 0, t.fills
    assert t.pages == ["trigger_in_market"]


# --------------------------------------------------------------------------------------------
# M2: outside RTH the freshness gate is only consulted on prints, so fresh quotes never sell.
# --------------------------------------------------------------------------------------------
def _timed_run(
    timed: list[tuple[float, tp.Quote | tp.Trade]],
    script: list[tp.Order],
    params: ExitParams | None = None,
    **kwargs: Any,
) -> tp.Tape:
    times = [seconds for seconds, _item in timed]

    def timed_tick(start: int, i: int, item: tp.Quote | tp.Trade) -> object:
        ts = start + int(times[i] * 1_000_000_000)
        if isinstance(item, tp.Trade):
            return TradeTick(
                tp.EQUITY.id,
                Price.from_str(item.price),
                Quantity.from_str("1"),
                AggressorSide.BUY,
                TradeId(str(i)),
                ts,
                ts,
            )
        return QuoteTick(
            tp.EQUITY.id,
            Price.from_str(item.bid),
            Price.from_str(item.ask),
            Quantity.from_str(item.bid_size),
            Quantity.from_str(item.ask_size),
            ts,
            ts,
        )

    orig = tp._tick
    tp._tick = timed_tick
    try:
        return tp.tape_run(
            [item for _seconds, item in timed], script, params or tp.FIXTURE, **kwargs
        )
    finally:
        tp._tick = orig


def test_m2_a_fresh_quote_prices_the_outside_exit_without_a_print() -> None:
    """Pre-market prints every 2 s, each followed 0.5 s later by a fresh two-sided quote at the
    print. The quote_max_age_s=1 gate (starts) is satisfied on every quote, but ``_step`` is only
    called from ``on_trade`` outside RTH, so after the crossing the engine waits for the next
    print while ~30 fresh quotes arrive and never sells (the base sold at second 19)."""
    timed: list[tuple[float, tp.Quote | tp.Trade]] = [
        (0.0, tp.Quote("100.00", "100.02")),
        (0.5, tp.Trade("100.02")),
    ]
    px = D("100.02")
    for k in range(40):
        at = float(D(1) + D(2) * k)
        if 3 <= k < 8:
            px -= D("0.25")
        timed.append((at, tp.Trade(f"{px}")))
        timed.append((at + 0.5, tp.Quote(f"{px - D('0.02')}", f"{px}")))
    t = _timed_run(timed, [tp.Order(0, "10")], tp.STARTS, session="outside", start=PRE)
    sells = _breach_sell_seconds(t, PRE)
    assert sells, "no sell while fresh quotes kept arriving"
    assert t.net == 0


# --------------------------------------------------------------------------------------------
# M3: an armed gain lock below the bid is refused because the unarmed H-trail is into the bid.
# --------------------------------------------------------------------------------------------
def test_m3_an_armed_gain_lock_below_the_bid_still_sells() -> None:
    """Once armed, the stop is the gain lock (12.00 - 0.198 = 11.802), which sits below the 11.85
    bid. The raise guard tests ``max(next_trigger(...), lock)``, and the H - trail leg
    (11.8998) is at/into the bid, so the whole raise is refused; the trigger stays at 10.902
    through a 7.6% fall and the position never exits."""
    items: list[tp.Quote | tp.Trade] = [tp.Quote("10.00", "10.02")]
    items += [tp.Quote("10.98", "11.00"), tp.Trade("11.00")] * 36
    items += [tp.Quote("10.98", "11.00")] * 12
    items += [tp.Quote("11.85", "12.00"), tp.Trade("12.00")]
    items += [tp.Quote("11.85", "11.87"), tp.Trade("11.85")] * 12
    px = D("11.85")
    while px > D("10.95"):
        px -= D("0.01")
        items += [tp.Quote(f"{px}", f"{px + D('0.02')}"), tp.Trade(f"{px}")]
    t = tp.tape_run(items, [tp.Order(0, "10")], tp.STARTS)
    assert tp._sold(t) == D(10), t.fills
    assert t.net == 0


# --------------------------------------------------------------------------------------------
# M4: the committed #98/#141 surface no longer reruns from its exact inputs.
# --------------------------------------------------------------------------------------------
RERUN = os.environ.get("SEXTANT_RERUN_141") == "1"
# Lead ruling (a), 2026-11-07: the committed surface stays as history and PR 2's engine run is
# recorded beside it, so the rerun is compared with that run (the verifier's own test retargeted).
EVIDENCE = (
    Path(__file__).parents[2] / "docs" / "research" / "2026-11-06-exit-grid-141" / "run-a8282a4"
)


@pytest.mark.skipif(not RERUN, reason="opt-in (SEXTANT_RERUN_141=1); needs #41's exact inputs")
def test_m4_the_committed_dropped_arm_surface_still_reruns(tmp_path: Path) -> None:
    """docs/research/2026-11-06-exit-grid-141.md:70 says "Reproduced: every cell ... equals the
    committed surface", and 2026-11-06-exit-econ-98.md:3 commits -49.71/-53.52 bps for the
    "Exit engine at starts, R_w dropped" arm. At 09e579f the same cell reruns at -46.24/-49.96:
    the minute-bar close quote (the LOW proxy) is stamped 1 ns before the bar's HIGH print, so
    ``high_bid`` is the low proxy and the raise is refused."""
    from sextant.research import exit_econ_98 as x98
    from sextant.research import exit_grid_141 as grid
    from sextant.research.exit_study_41 import DEFAULT_INPUTS

    inputs = Path(os.environ.get("SEXTANT_EXIT_STUDY_41", str(DEFAULT_INPUTS)))
    cid = "b0.01-m1-g0.1"
    ctx = x98.prepare(inputs, tmp_path / "catalog")
    result = x98.evaluate(ctx, dict(grid.cells())[cid], range_estimable=False, arm=cid)
    committed = json.loads((EVIDENCE / "report.json").read_text())["surface"][cid]
    for bps in ("3", "6"):
        assert result["arm"][bps]["mean_bps"] == committed[bps]["mean_bps"]


# --------------------------------------------------------------------------------------------
# M5: in RTH the quote_unavailable page is unreachable while the quote is one-sided.
# --------------------------------------------------------------------------------------------
def test_m5_a_one_sided_rth_quote_pages_quote_unavailable() -> None:
    """ADR-0005 X2/X3: a quote needs bid > 0 to price anything, and an unknown quote pages once.
    In RTH ``on_quote`` passes ``None`` for a one-sided quote, and ``_step`` returns before the
    page; the entry fills, the bid is 0.00 for 30 s, and no page is emitted."""
    one_sided = tp.Quote("0.00", "100.02", bid_size="0")
    items: list[tp.Quote | tp.Trade] = [tp.Quote("100.00", "100.02"), one_sided]
    items += [one_sided] * 30 + [tp.Quote("97.00", "97.02")] * 4
    t = tp.tape_run(items, [tp.Order(1, "10", price="100.02")], session="rth")
    assert "quote_unavailable" in t.pages
