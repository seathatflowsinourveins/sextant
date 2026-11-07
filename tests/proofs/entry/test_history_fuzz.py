"""#88's known-prefix differential: an arrival event must exist in event order."""

from decimal import Decimal as D
from random import Random

import pytest

from .conftest import bar, trade
from .test_signals import state


def initialized():
    s = state()
    for at in (-180, -120, -60):
        s.on_bar(bar(at), now=bar(0).ts_init)
    return s


def random_tape(rng, max_lag):
    trough = rng.choice(["10.02", "10.03", "10.05"])
    base = [
        (0, "10.00", 10000),
        (1000, "11.00", 100),
        (2000, "9.99", 100),
        (3000, rng.choice(["10.03", "10.04"]), 100),
        (4000, rng.choice(["10.04", "10.06"]), 100),
        (5000, rng.choice(["10.05", "10.07", "10.10"]), 100),
    ]
    at = 5000
    for _ in range(rng.randrange(4, 8)):
        at += rng.choice([500, 1000, 1000, 1500])
        base.append((at, rng.choice([trough, trough, "10.03", "10.04", "10.05", "10.06"]), 100))
    prints = [(at, price, size, 0, f"base-{i}", i) for i, (at, price, size) in enumerate(base)]
    for i in range(rng.randrange(1, 4)):
        prints.append(
            (
                rng.randrange(-10000, at),
                str(D(rng.randrange(980, 1021)) / 100),
                rng.choice([50, 100, 300, 1000, 3000, 8000]),
                rng.randrange(500, max_lag),
                f"late-{i}",
                100 + i,
            )
        )
    return prints


def tick(row, *, ordered=False):
    at, price, size, lag, identity, _ = row
    return trade(
        str(D(at) / 1000),
        price,
        size=size,
        lag=0 if ordered else lag * 1_000_000,
        identity=identity,
    )


@pytest.mark.parametrize(
    ("seed", "max_lag"), [(5, 5000), (9, 9000)], ids=["late-only", "late-and-stale"]
)
def test_arrival_reclaim_events_match_a_known_event_ordered_prefix(seed, max_lag, record_property):
    rng = Random(seed)  # noqa: S311 - deterministic differential fixture.
    events = 0
    for case in range(1500):
        arrived, known = initialized(), []
        for row in sorted(random_tape(rng, max_lag), key=lambda p: (p[0] + p[3], p[5])):
            item = tick(row)
            accepted = arrived.on_trade(item, now=item.ts_init)
            known.append(row)
            if accepted and arrived.reclaim_event_ns == item.ts_event:
                events += 1
                ordered = initialized()
                # Stable tie order is the arrival order already known at this decision.
                for prior in sorted(known, key=lambda p: p[0]):
                    control_tick = tick(prior, ordered=True)
                    ordered.on_trade(control_tick, now=control_tick.ts_init)
                assert ordered.reclaim_event_ns == item.ts_event, (case, row, known)
    record_property("arrival_events", events)
    record_property("cases", 1500)
    assert events > 0  # A reducer which refuses every reclaim cannot pass this proof.
