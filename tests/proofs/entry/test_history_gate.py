"""Review 5811398007: reclaim history and consumed holds in native replay."""

from decimal import Decimal as D

import pytest
from nautilus_trader.model import Bar, Price, TradeTick

from sextant.entry.signals import TradeCoverage

from .conftest import IID, SEC, START, bar, quote, trade
from .test_replay import replay
from .test_signals import extended_state, feed


def tape(prices):
    return [bar(-180), bar(-120), bar(-60)] + [
        trade(at, price, size=10000 if at == 0 else 100) for at, price in prices
    ]


BASE = [(0, "10.00"), (1, "11.00"), (2, "9.99"), (3, "10.03")]


def native(instrument, tmp_path, data, end):
    end_ns = START + int(D(end) * SEC)
    trades = [item for item in data if isinstance(item, TradeTick)]
    receipt = TradeCoverage(
        IID,
        "fixture-segment",
        START - 60 * SEC,
        end_ns,
        end_ns,
        "TEST complete native witness",
        {
            span: sum(end_ns - span < t.ts_event <= end_ns for t in trades)
            for span in (60 * SEC, 2 * SEC)
        },
    )
    return replay(
        instrument,
        tmp_path,
        sorted(data, key=lambda item: item.ts_init),
        surge=None,
        confidence=D("0.5"),
        coverage=receipt,
    )


@pytest.mark.parametrize("ordered", [True, False], ids=["ordered", "late"])
@pytest.mark.parametrize(
    ("at", "price", "size", "arrival"),
    [
        ("2.5", "10.10", 6700, "7.5"),
        ("2.5", "10.10", 6700, "7.7"),
        ("-70", "10.10", 6700, "7.5"),
        ("-125", "10.10", 6700, "7.5"),
        ("2.5", "10.06", 8000, "7.5"),
        ("2.5", "10.06", 8000, "6.5"),
    ],
    ids=["raise-level", "stale-level", "before-tape", "pruned-tape", "benign-5s", "benign-4s"],
)
def test_corrected_vwap_revalidates_the_reclaim_run(
    instrument, tmp_path, ordered, at, price, size, arrival
):
    data = tape([*BASE, (4, "10.06"), (5, "10.07"), (6, "10.05"), (7, "10.05"), (8, "10.06")])
    lag = 0 if ordered else int((D(arrival) - D(at)) * SEC)
    data += [trade(at, price, size=size, lag=lag), quote("7.9", "10.05", "10.06")]
    result = native(instrument, tmp_path, data, 8)
    assert result.orders == [], result.events


@pytest.mark.parametrize("lag", [0, 2_100_000_000, 4_900_000_000, 7_000_000_000])
def test_corrected_vwap_revalidates_the_episode_touch(instrument, tmp_path, lag):
    data = tape([*BASE, (4, "10.04"), (5, "10.05"), (6, "10.02"), (7, "10.02"), (8, "10.03")])
    data += [trade("0.5", "9.80", size=3000, lag=lag), quote("7.9", "10.02", "10.03")]
    result = native(instrument, tmp_path, data, 8)
    assert result.orders == [], result.events


@pytest.mark.parametrize("lag", [0, 2_500_000_000, 5_000_000_000])
def test_late_earlier_touch_cannot_preserve_a_later_invalid_touch(instrument, tmp_path, lag):
    data = tape([*BASE, (4, "10.04"), (5, "10.05"), (6, "10.02"), (7, "10.02"), (8, "10.03")])
    data += [trade("1.5", "9.98", lag=lag), quote("7.9", "10.02", "10.03")]
    result = native(instrument, tmp_path, data, 8)
    assert result.orders == [], result.events


@pytest.mark.parametrize("lag", [0, 7_000_000_000])
def test_corrected_vwap_revalidates_an_extended_reclaim_high(instrument, tmp_path, lag):
    data = tape([*BASE, (4, "10.10"), (5, "10.40"), (6, "10.06"), (7, "10.06"), (8, "10.07")])
    data += [trade("0.5", "9.98", size=10000, lag=lag), quote("7.9", "10.06", "10.07")]
    result = native(instrument, tmp_path, data, 8)
    assert result.orders == [], result.events


@pytest.mark.parametrize("lag", [None, 0, 3_000_000_000], ids=["no-late-print", "ordered", "late"])
def test_corrected_hold_consumes_the_already_processed_first_chance(instrument, tmp_path, lag):
    data = tape(BASE + [(4, "10.04"), (5, "10.05")] + [(at, "10.03") for at in range(6, 11)])
    if lag is not None:
        data.append(trade("6.5", "10.02", lag=lag))
    data += [quote("8.95", "10.19", "10.20"), quote("9.8", "10.02", "10.03")]
    result = native(instrument, tmp_path, data, 10)
    assert result.orders == [], result.events


@pytest.mark.parametrize("lag", [0, 2_800_000_000], ids=["ordered", "late"])
def test_pre_hold_late_low_cannot_reopen_a_consumed_first_chance(instrument, tmp_path, lag):
    data = tape(
        [
            *BASE,
            (4, "10.04"),
            (5, "10.05"),
            ("6.5", "10.03"),
            ("7.5", "10.03"),
            ("8.6", "10.03"),
            ("9.5", "10.04"),
        ]
    )
    data += [
        trade(6, "10.02", lag=lag),
        quote("8.55", "10.19", "10.20"),
        quote("9.2", "10.03", "10.04"),
    ]
    result = native(instrument, tmp_path, data, "9.5")
    assert result.orders == [], result.events


def test_clean_held_reclaim_still_fills(instrument, tmp_path):
    data = tape([*BASE, (4, "10.04"), (5, "10.05"), (6, "10.02"), (7, "10.02"), (8, "10.03")])
    result = native(instrument, tmp_path, [*data, quote("7.9", "10.02", "10.03")], 8)
    assert len(result.orders) == 1, result.events
    assert result.orders[0]["status"] == "FILLED"


def test_rebuild_uses_the_atr_known_when_each_historical_print_was_processed():
    s = extended_state()
    for at, price in [(3, "10.03"), (4, "10.04"), (5, "10.05"), (6, "10.02"), (7, "10.02")]:
        feed(s, at, price)
    template = bar(7)
    wider = Bar(
        template.bar_type,
        Price.from_str("10.00"),
        Price.from_str("11.00"),
        Price.from_str("9.00"),
        Price.from_str("10.00"),
        template.volume,
        template.ts_event,
        template.ts_init,
    )
    assert s.on_bar(wider, now=wider.ts_init)
    assert s.atr.value == D("0.8")
    late = trade("6.5", "10.04", lag=800_000_000)
    assert not s.on_trade(late, now=late.ts_init)
    feed(s, 8, "10.03")
    assert s.reclaim_ready(D("10.03"), D("0.10"), START + 8 * SEC, covered_flow=True)


@pytest.mark.parametrize("lag", [0, 800_000_000], ids=["ordered", "late"])
def test_late_print_uses_the_atr_available_at_its_event_time(instrument, tmp_path, lag):
    data = tape(
        [*BASE, (4, "10.04"), (5, "10.05"), (6, "10.02"), (7, "10.02"), (8, "10.02"), (9, "10.03")]
    )
    template = bar(7)
    wider = Bar(
        template.bar_type,
        Price.from_str("10.00"),
        Price.from_str("11.00"),
        Price.from_str("9.00"),
        Price.from_str("10.00"),
        template.volume,
        template.ts_event,
        template.ts_init,
    )
    data += [wider, trade("6.5", "10.60", lag=lag), quote("8.9", "10.02", "10.03")]
    result = native(instrument, tmp_path, data, 9)
    assert result.orders == [], result.events
