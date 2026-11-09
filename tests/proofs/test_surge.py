"""ADR-0024 surge30 witnesses: synthetic receipts, not a market cohort or strategy trial."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from nautilus_trader.model import (
    AggressorSide,
    InstrumentId,
    Price,
    Quantity,
    QuoteTick,
    TradeId,
    TradeTick,
)

from sextant.entry.signals import Surge
from sextant.entry.surge import (
    DEFAULT_CONFIG,
    SurgeConfig,
    SurgeState,
    active_flag,
    advance_surge,
    is_closing_print,
    two_sided,
)
from sextant.ranking.baseline import BaselineSample, BaselineTable
from sextant.ranking.engine import Segment
from sextant.ranking.window import NS

D = Decimal
DAY = date(2026, 10, 27)
START = 1_793_088_000 * NS  # 2026-10-27 04:00 ET, explicit fixture boundary.
RTH = Segment("RTH", DAY, START, START + 600 * NS, "fixture XNYS boundary")
PRE = Segment("PRE", DAY, START - 600 * NS, START, "fixture XNYS boundary")
IID = InstrumentId.from_str("SURGE.NASDAQ")


def baseline(*, known_at: int | None = None) -> BaselineTable:
    # A flat complete curve: 600 s of prior-session RTH flow gives a 30 s
    # normal of $30 and 3 trades.
    return BaselineTable(
        (
            BaselineSample("SURGE", "RTH", "2026-10-26", 0, D(0), D(0)),
            BaselineSample("SURGE", "RTH", "2026-10-26", 600, D(600), D(60)),
        ),
        "fixture explicit complete curve; linear within minute",
        START - NS if known_at is None else known_at,
        "sip",
    )


def tick(second: int, price: str = "1.00", size: str = "100", *, name: str = "SURGE") -> TradeTick:
    at = START + second * NS
    return TradeTick(
        InstrumentId.from_str(name + ".NASDAQ"),
        Price.from_str(price),
        Quantity.from_str(size),
        AggressorSide.BUY,
        TradeId(f"{name}-{at}"),
        at,
        at,  # same-timestamp receipt: the fixture's known_at equals its event time.
    )


def quote(second: int, bid: str = "1.04", ask: str = "1.06", bid_size: str = "500") -> QuoteTick:
    at = START + second * NS
    return QuoteTick(
        IID,
        Price.from_str(bid),
        Price.from_str(ask),
        Quantity.from_str(bid_size),
        Quantity.from_str("500"),
        at,
        at,
    )


def warm(quote_tick: QuoteTick | None = None) -> tuple[SurgeState, Surge | None]:
    """One quiet print, then a rising, unusually large run inside the 30 s window."""
    state: SurgeState = SurgeState()
    flag: Surge | None = None
    for second, price, size in (
        (0, "1.00", "100"),
        (25, "1.01", "100"),
        (26, "1.01", "100"),
        (30, "1.00", "100"),
        (31, "1.03", "500"),
        (32, "1.04", "500"),
    ):
        state, flag = advance_surge(state, tick(second, price, size), baseline(), segment=RTH)
    state, flag = advance_surge(
        state, tick(33, "1.05", "500"), baseline(), segment=RTH, quote=quote_tick or quote(32)
    )
    return state, flag


def test_qualifying_print_emits_the_first_leg_surge() -> None:
    state, flag = warm()
    assert flag is not None
    assert isinstance(flag, Surge)
    assert flag.instrument_id == IID
    assert flag.segment == RTH.name
    assert flag.first_print_ts == START + 31 * NS  # first print at/above quiet * 1.02
    assert flag.flag_ts == START + 33 * NS
    assert flag.known_at == flag.flag_ts
    assert flag.expires_ts == flag.flag_ts + 120 * NS
    assert flag.quiet_price == D("1.00")
    assert flag.source == "surge30"
    assert state.flag == flag
    assert state.segment_key == (RTH.name, RTH)
    assert state.metrics["dollar_volume"] == D(1862)
    assert state.metrics["trade_count"] == 6
    assert state.metrics["baseline_dollar_volume"] == D(30)
    assert state.metrics["move"] == D("0.05")
    assert state.metrics["rising"] is True
    assert state.metrics["latency_ns"] == 2 * NS
    assert state.metrics["window_start_ts"] == START + 3 * NS
    assert state.metrics["quiet_ts"] == START
    assert state.metrics["quote_ts"] == START + 32 * NS
    assert state.metrics["uncalibrated"] is True


@pytest.mark.parametrize(
    "quote_tick",
    [
        quote(30),  # 3 s old, beyond the 1 s RTH start
        quote(32, "1.06", "1.06"),  # locked, not two-sided
        quote(32, "1.04", "1.06", bid_size="0"),  # one-sided size
    ],
)
def test_stale_or_one_sided_quote_emits_no_flag(quote_tick: QuoteTick) -> None:
    state, flag = warm(quote_tick)
    assert flag is None
    assert state.flag is None
    assert two_sided(quote_tick, START + 33 * NS, RTH, DEFAULT_CONFIG) is False


def test_episode_latch_suppresses_a_second_flag_past_expiry() -> None:
    state, first = warm()
    assert first is not None
    assert state.latched is True
    # Keep the same unusual-volume/move episode alive for 143 s, well past the 120 s expiry.
    for second in range(34, 177):
        price = str(D("1.05") + D(second - 33) / 1000)
        state, flag = advance_surge(
            state,
            tick(second, price, "500"),
            baseline(),
            segment=RTH,
            quote=quote(second - 1),
        )
        assert flag is None
    assert state.flag == first
    assert state.latched is True
    assert active_flag(state, START + 176 * NS) is None  # expired, so the latch is what refused


@pytest.mark.parametrize("condition", ["6", "M", "9"])
def test_closing_print_is_ignored(condition: str) -> None:
    state, _ = advance_surge(SurgeState(), tick(0), baseline(), segment=RTH)
    assert is_closing_print((condition,)) is True
    assert is_closing_print(("F",)) is False
    returned, flag = advance_surge(
        state, tick(33, "1.05", "500"), baseline(), segment=RTH, conditions=(condition,)
    )
    assert flag is None
    assert returned is state  # neither history nor clocks moved
    assert returned.history == state.history


def test_segment_change_resets_state() -> None:
    state, first = warm()
    assert first is not None
    assert state.latched is True
    new_tick = tick(-1)
    returned, flag = advance_surge(state, new_tick, baseline(), segment=PRE)
    assert flag is None
    assert returned.segment_key == (PRE.name, PRE)
    assert returned.symbol == "SURGE"
    assert len(returned.history.buckets) == 1
    assert returned.history.buckets[0].ticks == (new_tick,)
    assert returned.volume_history.buckets[0].ticks == (new_tick,)
    assert returned.flag is None
    assert returned.latched is False
    assert returned.metrics == {}
    assert returned.known_at == START - NS


def test_params_hash_mismatch_raises() -> None:
    state, _ = advance_surge(SurgeState(), tick(0), baseline(), segment=RTH)
    changed = replace(DEFAULT_CONFIG, surge_move_min=D("0.03"))
    assert changed.params_hash != DEFAULT_CONFIG.params_hash
    with pytest.raises(ValueError, match="parameters changed"):
        advance_surge(state, tick(1), baseline(), segment=RTH, config=changed)


def test_surge_config_rejects_floats_and_uncalibrated_status() -> None:
    assert DEFAULT_CONFIG.status == "UNCALIBRATED"
    float_move: Any = 0.02
    calibrated: Any = "CALIBRATED"
    with pytest.raises(TypeError, match="never float"):
        SurgeConfig(surge_move_min=float_move)
    with pytest.raises(ValueError, match="UNCALIBRATED"):
        SurgeConfig(status=calibrated)
