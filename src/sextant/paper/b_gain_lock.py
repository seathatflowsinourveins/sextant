"""Pure long-side trigger and arming from ADR-0025 and ADR-0005 X2-X3."""

from decimal import Decimal

from sextant.exits import policy


def advance_gain_lock(
    *,
    entry: Decimal | None,
    high: Decimal,
    previous_trigger: Decimal,
    setup_gap: Decimal,
    one_tick: Decimal,
    eligible_spread: Decimal | None,
    range_w: Decimal | None,
    round_trip_cost: Decimal | None,
    confirmation_price: Decimal | None,
    confirmation_noise_floor: Decimal | None,
    executable: Decimal | None,
    custody_resolved: bool,
    armed: bool,
    params: policy.ExitParams,
) -> tuple[Decimal, bool]:
    """Return (trigger, armed) for one evaluation of already eligible inputs.

    Supply the latest completed close and its noise floor, or the least qualifying
    margin's price and floor from a completed trade run. Pass None without confirmation
    evidence. Executable is the current eligible RTH bid or outside-RTH trade.
    """
    required = (high, previous_trigger, setup_gap, one_tick)
    market = (entry, eligible_spread, range_w, executable)
    confirmation = (round_trip_cost, confirmation_price, confirmation_noise_floor)
    optional = (*market, *confirmation)
    values = (*required, *(value for value in optional if value is not None))
    if any(not isinstance(value, Decimal) or not value.is_finite() for value in values):
        raise ValueError("gain lock inputs must be finite Decimals")
    prices = (high, one_tick, entry, executable, confirmation_price)
    if any(value is not None and value <= 0 for value in prices):
        raise ValueError("gain lock needs positive observed prices and tick")
    distances = (setup_gap, eligible_spread, range_w, round_trip_cost)
    if any(value is not None and value < 0 for value in distances):
        raise ValueError("gain lock needs nonnegative distances and costs")
    if confirmation_noise_floor is not None and confirmation_noise_floor < one_tick:
        raise ValueError("confirmation noise floor must include at least one tick")
    if entry is None or eligible_spread is None:
        return previous_trigger, armed
    buffer = policy.buffer(one_tick, eligible_spread, entry, range_w, params)
    if buffer is None:
        return previous_trigger, armed

    lock = None
    if round_trip_cost is not None:
        floor = policy.noise_floor(one_tick, eligible_spread)
        lock = policy.gain_lock(entry, round_trip_cost, high, floor, params)
    armed_trigger = policy.next_trigger(previous_trigger, high, buffer, lock)
    if armed or (
        custody_resolved
        and round_trip_cost is not None
        and confirmation_price is not None
        and confirmation_noise_floor is not None
        and confirmation_price >= entry + round_trip_cost + confirmation_noise_floor
        and executable is not None
        and executable > armed_trigger
    ):
        return armed_trigger, True
    return policy.next_trigger(previous_trigger, high, max(buffer, setup_gap), None), False
