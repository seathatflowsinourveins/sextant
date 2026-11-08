"""Delayed-print/bar straddles refuse untrusted setups without historical repair."""

from decimal import Decimal as D

import pytest
from nautilus_trader.model import Bar, Price, QuoteTick, TradeTick

from sextant.entry.signals import Surge, classify

from .conftest import IID, SEC, START, bar, quote, trade
from .test_late_controls import BASE, native, tape
from .test_replay import replay
from .test_signals import extended_state, feed, state


def minute_bar_at(seconds):
    template = bar(0)
    ts = START + int(D(seconds) * SEC)
    return Bar(
        template.bar_type,
        Price.from_str("10.00"),
        Price.from_str("11.00"),
        Price.from_str("9.99"),
        Price.from_str("10.50"),
        template.volume,
        ts,
        ts,
    )


@pytest.mark.parametrize(
    ("s_lag_ms", "with_bar"),
    [(0, True), (200, True), (200, False), (1000, True), (6000, True)],
    ids=["S-on-time", "S-lag-0.2s-straddles-bar", "S-lag-0.2s-no-bar", "S-late-1s", "S-stale-6s"],
)
def test_probe_bar_inside_print_lag_hides_extended_print(instrument, tmp_path, s_lag_ms, with_bar):
    data: list[Bar | TradeTick | QuoteTick] = []
    data.extend(
        tape(
            [
                *BASE,
                (4, "10.04"),
                (5, "10.05"),
                (6, "10.02"),
                (7, "10.02"),
                (8, "10.03"),
                (9, "10.03"),
            ]
        )
    )
    data.append(trade("6.5", "10.50", lag=s_lag_ms * 1_000_000))
    if with_bar:
        data.append(minute_bar_at("6.6"))
    data.append(quote("8.9", "10.03", "10.04"))
    result = native(instrument, tmp_path, data, 9)
    submits = [
        (e["setup"], e["limit"], (e["ts"] - START) / SEC)
        for e in result.events
        if e["action"] == "SUBMIT"
    ]
    print(
        "PROBE",
        s_lag_ms,
        with_bar,
        submits,
        [(o["status"], str(o.get("filled_qty"))) for o in result.orders],
    )
    # Time-ordered tape: S (t6.5) precedes the bar (t6.6) and is EXTENDED -> no reclaim buy.
    assert result.orders == [], result.events


def test_probe_state_level_classification_of_s():
    s = extended_state()
    for at, price in [(3, "10.03"), (4, "10.04"), (5, "10.05"), (6, "10.02")]:
        feed(s, at, price)
    pre_bar, b = s.atr.value, minute_bar_at("6.6")
    assert s.on_bar(b, now=b.ts_init)
    volume, spike = s.volume, trade("6.5", "10.50", lag=200_000_000)
    # In print order and one bar group behind: the strict as-of ATR excludes that bar (#88 P2-1).
    assert s.on_trade(spike, now=spike.ts_init)
    assert s.void_reason is None and s.volume == volume + 100 and s.vwap is not None
    assert s.last_atr == pre_bar and pre_bar != s.atr.value
    assert s.extension is classify(
        D("10.50"), s.vwap, pre_bar, s.params["entry_max_vwap_extension_atr"]
    )


def grid_bar(seconds, high, low, close, arrival_ms=0):
    template = bar(0)
    ts = START + seconds * SEC
    return Bar(
        template.bar_type,
        Price.from_str("10.00"),
        Price.from_str(high),
        Price.from_str(low),
        Price.from_str(close),
        template.volume,
        ts,
        ts + arrival_ms * 1_000_000,
    )


@pytest.mark.parametrize(
    "s_lag_ms",
    [0, 30, 150, 1200],
    ids=["S-0ms", "S-30ms", "S-150ms-straddles-bar", "S-1200ms-late"],
)
def test_probe_minute_grid_bar_hides_its_own_spike(instrument, tmp_path, s_lag_ms):
    """Minute-aligned: bars close on the grid; the bar closing at t60 arrives 50 ms later and
    contains S (10.50 @ t59.95). Its own bar widens ATR and hides S when S lags past it."""
    shift = 53
    prices = [
        (0, "10.00"),
        (1, "11.00"),
        (2, "9.99"),
        (3, "10.03"),
        (4, "10.04"),
        (5, "10.05"),
        (6, "10.02"),
        ("7.2", "10.02"),
        ("8.2", "10.03"),
        ("9.2", "10.03"),
    ]
    data: list[Bar | TradeTick | QuoteTick] = [
        bar(-180),
        bar(-120),
        bar(-60),
        grid_bar(0, "10.10", "9.90", "10.00"),
    ]
    data += [
        trade(str(D(at) + shift), price, size=10000 if at == 0 else 100) for at, price in prices
    ]
    data.append(trade("59.95", "10.50", lag=s_lag_ms * 1_000_000))
    data.append(grid_bar(60, "11.00", "9.99", "10.50", arrival_ms=50))
    data.append(quote("62.1", "10.03", "10.04"))
    result = native(instrument, tmp_path, data, "62.2")
    submits = [
        (e["setup"], e["limit"], (e["ts"] - START) / SEC)
        for e in result.events
        if e["action"] == "SUBMIT"
    ]
    print(
        "PROBE grid",
        s_lag_ms,
        submits,
        [(o["status"], str(o.get("filled_qty"))) for o in result.orders],
    )
    assert result.orders == [], result.events


@pytest.mark.parametrize(
    "case", ["episode-shift", "straddling-touch"], ids=["same-ts-episode-shift", "straddling-touch"]
)
def test_a_print_behind_a_known_bar_never_lets_a_shifted_touch_buy(case):
    # In time order the t1.5 print is classified with the pre-bar ATR and no reclaim follows:
    # its touch (or the same-ts t2 sibling's) is voided by the t3 or t2 print below the level.
    s = state()
    for offset in (-180, -120, -60):
        s.on_bar(bar(offset), now=START)
    for tick in (trade(0, "10.00", size=100000), trade(1, "11.00")):
        assert s.on_trade(tick, now=tick.ts_init)
    template = bar(0)
    known = START + 1_600_000_000
    narrow = Bar(
        template.bar_type,
        template.open,
        template.high,
        template.low,
        template.close,
        template.volume,
        known,
        known,
    )
    assert s.on_bar(narrow, now=known)
    if case == "episode-shift":
        straddler = trade("1.5", "10.60", lag=200_000_000)
        rest = [trade(2, "10.80", identity="t2-a"), trade(2, "9.99", identity="t2-b", lag=1)]
        rest += [trade(3, "9.95")]
    else:
        straddler = trade("1.5", "9.99", lag=200_000_000)
        rest = [trade(2, "9.95")]
    assert s.on_trade(straddler, now=straddler.ts_init)  # its exact pre-bar ATR, not UNKNOWN
    assert s.void_reason is None and s.last_atr is not None
    for at, price in ((4, "10.03"), (5, "10.04"), (6, "10.05"), (7, "10.02"), (8, "10.02")):
        rest.append(trade(at, price))
    for tick in [*rest, trade(9, "10.03")]:
        s.on_trade(tick, now=tick.ts_init)
    assert s.vwap is not None  # trusted: refused as time order refuses, not by a latch
    assert not s.reclaim_ready(D("10.03"), D("0.10"), START + 9 * SEC, covered_flow=True)


@pytest.mark.parametrize("lag_ms", [0, 30], ids=["zero-lag", "constant-30ms"])
def test_an_in_order_print_across_a_bar_dispatch_keeps_the_first_leg(instrument, tmp_path, lag_ms):
    # #88 P2-1: every print 30 ms late, crossing the t0 bar dispatched at t0.05. N1 reads no ATR,
    # so the run must not restart: both arms submit at t0.4, as the zero-lag tape does.
    data = [bar(-180), bar(-120), bar(-60), grid_bar(0, "10.10", "9.90", "10.00", arrival_ms=50)]
    rows, price, at = [], D("10.01"), D("-0.6")
    while at < D("1.2"):
        rows.append((at, price))
        at += D("0.04")
        price += D("0.01") if len(rows) % 5 == 0 else 0
    lag = lag_ms * 1_000_000
    data += [
        trade(str(t), str(p), size=10000 if i == 0 else 100, lag=lag)
        for i, (t, p) in enumerate(rows)
    ]
    data += [quote(str(t + D("0.001")), str(p - D("0.01")), str(p)) for t, p in rows[::3]]
    early = START - 600_000_000
    surge = Surge(IID, "fixture-segment", early, early, early, START + 120 * SEC, D("10"), "TEST")
    result = replay(instrument, tmp_path, data, surge=surge)
    submits = [(e["setup"], e["limit"], e["ts"]) for e in result.events if e["action"] == "SUBMIT"]
    assert submits == [("FIRST_LEG", "10.05", START + 400_000_000 + lag)], result.events
    assert not any(e["action"] == "VOID" for e in result.events), result.events
