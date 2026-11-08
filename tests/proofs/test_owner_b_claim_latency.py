"""#78 B drill B5: claim latency, house-side component measured in native sim.

Measures owner fill -> B's adoption -> first protection ACCEPTED on #95's native witness
(nautilus_trader v2.0.0rc8 BacktestEngine, StaticLatencyModel, one-second quote grid).
It is a sim mechanism measurement: the TradingView -> Alpaca -> trade_updates leg needs an
Alpaca execution client and a broker fill, so claim_max_latency_s stays UNCALIBRATED.
"""

import json

import pytest

NS = 1_000_000_000


def _measure(tmp_path, latency_ns):
    from sextant.backtest import owner_b_witness as w

    fills: list[int] = []
    original = w.OwnerFixture.on_order_filled

    def spy(self, event):
        if str(event.client_order_id) == "owner-entry":
            fills.append(event.ts_event)
        original(self, event)

    w.OwnerFixture.on_order_filled = spy
    try:
        r = w._simulate_case(tmp_path / str(latency_ns), latency_ns=latency_ns)
    finally:
        w.OwnerFixture.on_order_filled = original
    adoption = next(int(e["ts"]) for e in r["events"] if e["event"] == "adoption")
    trail = next(a["order_id"] for a in r["actions"] if a["action"] == "trail")
    accepted = next(  # the protection's own acceptance, not any later house order's (#191 P2-1)
        int(e["ts"]) for e in r["events"] if e["event"] == "accepted" and e["order_id"] == trail
    )
    assert len(fills) == 1
    return {
        "latency_ms": latency_ns // 1_000_000,
        "fill_to_adoption_ns": adoption - fills[0],
        "adoption_to_protection_accepted_ns": accepted - adoption,
        "fill_to_protection_accepted_ns": accepted - fills[0],
    }


@pytest.mark.parametrize(
    "latency_ns, protected_ns",
    [(100_000_000, 2 * NS), (200_000_000, 2 * NS), (1_200_000_000, 3 * NS)],
)  # #78's published B5 values, on the one-second witness grid
def test_house_side_claim_latency_is_measured_and_within_the_fixture_bound(
    tmp_path, latency_ns, protected_ns
):
    from sextant.exits.owner_b import REGISTRY

    m = _measure(tmp_path, latency_ns)
    print("B5", json.dumps(m))
    assert 0 <= m["fill_to_adoption_ns"] <= 2 * NS  # B_FIXTURE claim_max_latency_s = 2
    assert m["fill_to_protection_accepted_ns"] == protected_ns
    row = next(r for r in REGISTRY if r.name == "claim_max_latency_s")
    assert row.start is None and row.state == "UNCALIBRATED"
