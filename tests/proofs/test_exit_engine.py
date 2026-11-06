"""Exit-engine witnesses, ADR-0005 X2-X6, on hand sequences and Nautilus's own test quotes.

Mechanism only. The 96-variant rerun (design row 7) waits for its inputs (issue #41).
"""

import dataclasses
import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from sextant.backtest.exit_witness import FIXTURE, run
from sextant.exits import policy
from sextant.exits.policy import REGISTRY, Bar1mArming, BreachRun, ExitParams

ROOT = Path(__file__).parents[2]
S = 1_000_000_000


def test_every_parameter_is_an_uncalibrated_registry_row_with_no_default() -> None:
    names = [f.name for f in dataclasses.fields(ExitParams)]
    assert names == [row.name for row in REGISTRY]
    assert {row.state for row in REGISTRY} == {"UNCALIBRATED"}
    assert all(f.default is dataclasses.MISSING for f in dataclasses.fields(ExitParams))
    with pytest.raises(TypeError):
        ExitParams()  # type: ignore[call-arg]


def test_take_profit_above_h_must_exceed_its_step() -> None:
    with pytest.raises(ValueError, match="take_profit_above_h_fraction"):
        dataclasses.replace(FIXTURE, take_profit_step_fraction=D("0.10"))


def test_no_float_in_the_engine() -> None:
    for name in ("policy.py", "engine.py"):
        assert "float" not in (ROOT / "src" / "sextant" / "exits" / name).read_text()


def test_buffer_is_the_widest_term_and_unknown_range_is_unknown() -> None:
    p = dataclasses.replace(FIXTURE, prearm_range_multiple=D(2))
    assert policy.buffer(D("0.01"), D("0.02"), D(10), D("0.05"), p) == D("0.10")
    assert policy.buffer(D("0.01"), D("0.02"), D(100), D("0.05"), p) == D("0.200")
    assert policy.buffer(D("0.01"), D("0.02"), D(10), None, p) is None


def test_gain_lock_gives_back_the_larger_of_noise_and_its_fraction() -> None:
    # g=0.25: H-entry=2 gives back 0.5; noise 0.6 dominates it; never below entry + c_RT.
    assert policy.gain_lock(D(10), D("0.02"), D(12), D("0.01"), FIXTURE) == D("11.50")
    assert policy.gain_lock(D(10), D("0.02"), D(12), D("0.6"), FIXTURE) == D("11.4")
    assert policy.gain_lock(D(10), D("0.02"), D("10.01"), D("0.05"), FIXTURE) == D("10.02")


def test_round_trip_cost_caps_the_taf() -> None:
    c = policy.round_trip_cost(
        D(10), D(100_000), D("0.01"), D("0.0000278"), D("0.000166"), D("8.30")
    )
    assert c == D(10) * D("0.0000278") + D("8.30") / D(100_000) + D("0.01")


def test_trigger_never_loosens() -> None:
    trigger = D("9.90")
    for high, trail, lock in [
        (D(10), D("0.05"), None),
        (D(10), D("0.50"), None),
        (D(9), D(0), None),
    ]:
        new = policy.next_trigger(trigger, high, trail, lock)
        assert new >= trigger
        trigger = new
    assert trigger == D("9.95")
    assert policy.next_trigger(trigger, D(10), D(1), D("9.99")) == D("9.99")


def test_a_lone_breach_never_sells_and_a_rebound_resets_the_run() -> None:
    run_ = BreachRun()
    trigger = D(10)
    assert not run_.observe(D("9.99"), trigger, 0, FIXTURE)
    assert not run_.observe(D("10.01"), trigger, 1 * S, FIXTURE)  # rebound resets
    assert not run_.observe(D("9.99"), trigger, 2 * S, FIXTURE)
    assert not run_.observe(D("9.99"), trigger, 3 * S, FIXTURE)
    assert run_.observe(D(10), trigger, 4 * S, FIXTURE)  # third at/below, span 2 s


def test_persistence_needs_the_span_as_well_as_the_count() -> None:
    run_ = BreachRun()
    assert not any(run_.observe(D(9), D(10), i, FIXTURE) for i in range(5))
    assert run_.observe(D(9), D(10), 2 * S, FIXTURE)


def test_arming_needs_confirmation_and_a_price_above_the_armed_trigger() -> None:
    arming = Bar1mArming()
    assert not arming.try_arm(D(11), D(10))  # no completed close yet
    arming.on_bar_close(D("10.50"), D("10.10"))
    assert not arming.try_arm(D(10), D(10))  # arming cannot itself breach
    arming.on_bar_close(D("10.05"), D("10.10"))  # a later close below drops confirmation
    assert not arming.try_arm(D(11), D(10))
    arming.on_bar_close(D("10.10"), D("10.10"))
    assert arming.try_arm(D("10.01"), D(10))
    arming.on_bar_close(D(9), D("10.10"))
    assert arming.armed  # one-way


def test_the_fast_sell_never_goes_below_the_bid() -> None:
    assert policy.chase_limit(D("9.98"), D(10), FIXTURE) == D("9.990")
    assert policy.chase_limit(D("9.995"), D(10), FIXTURE) == D("9.995")
    assert policy.chase_limit(D("9.98"), None, FIXTURE) == D("9.98")


def test_take_profit_rolls_up_with_h_after_a_step_and_never_down() -> None:
    tp, anchor = policy.take_profit(None, None, D(10), FIXTURE)
    assert (tp, anchor) == (D("11.00"), D(10))
    assert policy.take_profit(tp, anchor, D("10.19"), FIXTURE) == (tp, anchor)
    tp, anchor = policy.take_profit(tp, anchor, D("10.20"), FIXTURE)
    assert tp == D("11.2200")
    assert policy.take_profit(tp, anchor, D(9), FIXTURE)[0] == tp
    clearance = (1 + FIXTURE.take_profit_above_h_fraction) / (
        1 + FIXTURE.take_profit_step_fraction
    ) - 1
    assert round(clearance, 4) == D("0.0784")  # ADR-0005: "about 7.8%"


def test_the_backstop_is_raised_never_lowered() -> None:
    level = policy.backstop(None, D(10), D("10.5"), FIXTURE)
    assert level == D("9.80")
    assert policy.backstop(level, D(10), D(9), FIXTURE) == level
    assert policy.backstop(level, D(11), D(12), FIXTURE) == D("10.78")


def test_sim_sells_on_the_first_persisted_bid_breach_and_logs_both_arms(tmp_path: Path) -> None:
    managed, control, events = run(tmp_path)
    kinds = [e["event"] for e in events]
    assert kinds[:2] == ["protected_from_fill", "initial_trigger"]
    assert events[0]["ts"] == events[1]["ts"]  # protected from the first fill
    assert "armed" not in kinds  # no eligible trades, so no gain lock (X3)
    sell = next(e for e in events if e["event"] == "breach_sell")
    assert D(sell["limit"]) <= D(sell["trigger"])
    assert managed.exit_label == "managed_sell"
    rows = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert [r["arm"] for r in rows] == ["exit-engine-x2-x5", "hold-to-end"]
    assert [r["tier"] for r in rows] == ["SIMULATED", "MODELED"]
    assert managed.entry == control.entry


def test_sim_rerun_reproduces_its_numbers(tmp_path: Path) -> None:
    first = run(tmp_path / "a")
    assert first == run(tmp_path / "b")
