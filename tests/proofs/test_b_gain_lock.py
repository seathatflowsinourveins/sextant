import json
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from sextant.exits.policy import REGISTRY, ExitParams


def advance(**overrides: Any) -> tuple[D, bool]:
    from sextant.paper.b_gain_lock import advance_gain_lock

    inputs: dict[str, Any] = {
        "entry": D("10"),
        "high": D("12"),
        "previous_trigger": D("9"),
        "setup_gap": D("1"),
        "one_tick": D("0.01"),
        "eligible_spread": D("0.10"),
        "range_w": D("0.50"),
        "round_trip_cost": D("0.15"),
        "confirmation_price": D("10.25"),
        "confirmation_noise_floor": D("0.10"),
        "executable": D("11.90"),
        "custody_resolved": True,
        "armed": False,
        "params": ExitParams.starts(),
    }
    return advance_gain_lock(**(inputs | overrides))


def test_arms_at_inclusive_confirmation_and_locks_fractional_gain():
    assert advance() == (D("11.80"), True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confirmation_price", D("10.249")),
        ("confirmation_price", None),
        ("confirmation_noise_floor", None),
        ("executable", D("11.80")),
        ("executable", None),
        ("custody_resolved", False),
        ("round_trip_cost", None),
    ],
)
def test_unconfirmed_or_unexecutable_lock_keeps_setup_gap(field, value):
    assert advance(**{field: value}) == (D("11"), False)


def test_no_arming_at_the_previous_trigger_even_if_the_lock_is_lower():
    assert advance(previous_trigger=D("11.90")) == (D("11.90"), False)


def test_arm_checks_the_post_arm_buffer_before_releasing_the_setup_gap():
    assert advance(range_w=D("0.10")) == (D("11"), False)
    assert advance(range_w=D("0.10"), executable=D("11.91")) == (D("11.90"), True)


def test_eligible_spread_can_bind_the_lock():
    assert advance(eligible_spread=D("0.35")) == (D("11.65"), True)


def test_narrower_current_spread_does_not_retroactively_confirm_a_close():
    assert advance(confirmation_noise_floor=D("0.11")) == (D("11"), False)


def test_one_tick_can_bind_the_lock_with_a_locked_quote():
    assert advance(
        one_tick=D("0.30"),
        eligible_spread=D("0"),
        confirmation_price=D("10.45"),
        confirmation_noise_floor=D("0.30"),
    ) == (
        D("11.70"),
        True,
    )


def test_expected_round_trip_cost_can_bind_the_lock():
    params = replace(ExitParams.starts(), gain_lock_giveback_fraction=D("0.5"))
    assert advance(high=D("10.25"), executable=D("10.16"), params=params) == (D("10.15"), True)


def test_an_armed_lock_stays_armed_and_never_loosens_on_a_rebound_in_noise():
    assert advance(
        armed=True,
        previous_trigger=D("11.80"),
        eligible_spread=D("0.40"),
        confirmation_price=D("10.20"),
        executable=D("11.60"),
    ) == (D("11.80"), True)


def test_an_armed_lock_keeps_following_eligible_highs():
    assert advance(armed=True, previous_trigger=D("11.80"), high=D("13")) == (D("12.70"), True)


@pytest.mark.parametrize("field", ["entry", "eligible_spread", "range_w"])
def test_missing_policy_input_preserves_the_previous_trigger(field):
    assert advance(**{field: None}) == (D("9"), False)


def test_range_is_unneeded_when_its_configured_multiple_is_zero():
    params = replace(ExitParams.starts(), prearm_range_multiple=D("0"))
    assert advance(range_w=None, executable=D("11.91"), params=params) == (D("11.90"), True)


def test_a_decimal_string_is_not_an_observed_decimal():
    with pytest.raises(ValueError, match="finite Decimal"):
        advance(high="12")


def test_a_nonfinite_decimal_is_rejected():
    with pytest.raises(ValueError, match="finite Decimal"):
        advance(confirmation_price=D("NaN"))


def test_gain_lock_registry_carries_shared_starts_and_b_one_tick_cost():
    root = Path(__file__).resolve().parents[2]
    rows = json.loads((root / "lanes/paper/b-gain-lock.params.json").read_text())
    starts = {row.name: row.start for row in REGISTRY}
    shared = {
        "gain_lock_giveback_fraction",
        "prearm_buffer_fraction",
        "prearm_range_multiple",
        "prearm_range_window_s",
    }
    assert {row["name"] for row in rows} == shared | {"round_trip_cost"}
    assert len(rows) == len(shared) + 1
    for row in rows:
        assert row["calibration_state"] == "UNCALIBRATED"
        assert row["source"] and row["last_change"]
        name = row["name"]
        if name == "round_trip_cost":
            # B's arming threshold needs a cost: ADR-0019 fixes its slippage term at one tick.
            assert D(row["value"]) == D("0.01")
            assert "0019-managed-exits-and-ranked-reentry.md:94" in row["source"]
            assert "0019-managed-exits-and-ranked-reentry.md:310" in row["source"]
        else:
            assert D(row["value"]) == starts[name]
