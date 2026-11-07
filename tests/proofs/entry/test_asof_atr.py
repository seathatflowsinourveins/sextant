"""n1n2ctl probe: a completed bar that arrives inside an in-order print's lag hides that
print's EXTENDED reading, so a held RECLAIM fills that the time-ordered tape never makes.

Tape = the fixture's clean held reclaim with a spike S (10.50 @ t6.5) during the hold.
The minute bar closing at t6.6 contains the t1 11.00 print (H 11.00 L 9.99 C 10.50), so
ATR moves 0.20 -> 0.47 when it arrives at t6.6.  In event order S precedes the bar:
10.50 - VWAP(10.0155) = 0.485 > 2 x 0.20, so S is EXTENDED, opens a new episode and voids
the setup; nothing buys.  The PR uses S's arrival-time ATR when S is in order and fresh.
"""

from decimal import Decimal as D

import pytest
from nautilus_trader.model import Bar, Price, QuoteTick, TradeTick

from .conftest import SEC, START, bar, quote, trade
from .test_history_gate import BASE, native, tape
from .test_signals import extended_state, feed


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
    b = minute_bar_at("6.6")
    assert s.on_bar(b, now=b.ts_init)
    spike = trade("6.5", "10.50", lag=200_000_000)
    assert s.on_trade(spike, now=spike.ts_init)  # in order, fresh: eligible
    print(
        "PROBE S extension with arrival ATR", s.atr.value, s.extension, "episode", s.episode_started
    )
    assert s.episode_started is not None, "S must open an extension episode in event order"


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
