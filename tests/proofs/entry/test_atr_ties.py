"""Review 5812691955: equal timestamps must not make ATR depend on dispatch or lag."""

from decimal import Decimal as D

import pytest
from nautilus_trader.model import Bar, Price

from .conftest import SEC, START, bar, quote, trade
from .test_asof_atr import grid_bar
from .test_late_controls import native
from .test_signals import feed, state


@pytest.mark.parametrize("wide", [True, False], ids=["widening", "narrowing"])
@pytest.mark.parametrize(
    ("lag", "bar_first"),
    [(0, False), (0, True), (1, False), (150_000_000, False)],
    ids=["print-first", "bar-first", "lag-1ns", "lag-150ms"],
)
def test_equal_bar_knowledge_time_keeps_the_same_native_reclaim(
    instrument, tmp_path, wide, lag, bar_first
):
    template = bar(0)
    high, low = ("10.10", "9.90") if wide else ("10.13", "9.87")
    data: list = [
        Bar(
            template.bar_type,
            template.open,
            Price.from_str(high),
            Price.from_str(low),
            template.close,
            template.volume,
            START + at * SEC,
            START + at * SEC,
        )
        for at in (-180, -120, -60, 0)
    ]
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
    data += [trade(str(D(at) + 53), price, size=10000 if at == 0 else 100) for at, price in prices]
    tied_bar = (
        grid_bar(60, "11.00", "9.99", "10.50", arrival_ms=50)
        if wide
        else grid_bar(60, "10.01", "9.99", "10.00", arrival_ms=50)
    )
    spike = trade("60.05", "10.50", lag=lag)
    data += [tied_bar, spike] if bar_first else [spike, tied_bar]
    data += [quote("61.1", "10.03", "10.04"), quote("62.1", "10.03", "10.04")]
    result = native(instrument, tmp_path, data, "62.2")
    assert not result.failed, result.failure_reason
    submitted = [event for event in result.events if event["action"] == "SUBMIT"]
    assert len(submitted) == (0 if wide or lag == 150_000_000 else 1), result.events
    assert any(e["action"] == "VOID" for e in result.events) is (lag == 150_000_000)
    if not wide and lag != 150_000_000:
        assert submitted[0]["setup"] == "RECLAIM"
        assert submitted[0]["ts"] == START + 62_200_000_000
        assert result.orders[0]["status"] == "FILLED"


def test_batched_bars_known_at_the_print_timestamp_do_not_supply_atr():
    s = state()
    for at in (-180, -120, -60):
        assert s.on_bar(bar(at), now=START)
    assert feed(s, 0, "10.00")
    assert s.last_atr is None
    assert feed(s, "0.000000001", "10.01")
    assert s.last_atr == D("0.20")
