"""ADR-0004 N5: native sizing terms and refusals remain visible to replay users."""

from decimal import Decimal as D

import pytest
from nautilus_trader.execution import LimitOrderPartialFillModel, StaticLatencyModel

from .conftest import params, quote, trade
from .test_replay import replay
from .test_sizing import sizing


def test_binding_term_uses_native_round_trip_commission_deduction(instrument):
    result = sizing(instrument, buying_power=D("905"), commission_rate=D("0.1"))
    assert result.quantity.as_decimal() == 80
    assert result.planned_risk == 20 and result.stop_distance == D("0.20")
    assert result.binding_term == "risk"


def test_submit_journals_the_sizing_terms_for_its_native_quantity(instrument, tmp_path):
    result = replay(
        instrument,
        tmp_path,
        [quote(0, "10.00", "10.02")]
        + [trade(at, "10.01" if at < 2 else "10.02", size=10000) for at in range(3)],
    )
    submit = next(event for event in result.events if event["action"] == "SUBMIT")
    assert submit["quantity"] == result.orders[0]["quantity"] == "95"
    assert D(submit["planned_risk"]) == 20
    assert D(submit["stop_distance"]) == D("0.21")
    assert submit["binding_term"] == "risk"


@pytest.mark.parametrize("ask", ["10.03", "10.50"], ids=["sizing", "chase-cap"])
def test_blocked_native_reprice_journals_its_failing_term(instrument, tmp_path, ask):
    result = replay(
        instrument,
        tmp_path,
        [quote(0, "10.00", "10.02")]
        + [trade(at, "10.02", size=10000 if at < 3 else 1850) for at in range(4)]
        + [quote("2.1", "10.49", "10.50"), quote("3.1", "10.02", ask), quote(10, "10.49", "10.50")],
        starting_cash=D("1000"),
        params=params(stop_ref_fraction="0.1", flow_share_window_s="1"),
        latency_model=StaticLatencyModel(insert_latency_nanos=500_000_000),
        fill_model=LimitOrderPartialFillModel(prob_fill_on_limit=1.0, prob_slippage=0.0),
    )
    assert result.orders[0]["status"] == "CANCELED"
    assert not any(event["action"] == "MODIFY" for event in result.events)
    refusals = [
        event
        for event in result.events
        if event["action"] == "REFUSE" and event.get("stage") == "MODIFY"
    ]
    assert refusals, result.events
    if ask == "10.03":
        assert any(
            event.get("binding_term") == "flow" and event.get("quantity") == "92"
            for event in refusals
        )
    else:
        assert any(event["reason"] == "entry_chase_bps" for event in refusals)
