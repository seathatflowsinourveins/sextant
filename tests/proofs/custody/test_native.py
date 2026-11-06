"""Native simulated house fills/kill; no external-order claim or broker recovery."""

from decimal import Decimal as D

from nautilus_trader.execution import MakerTakerFeeModel, StaticLatencyModel
from nautilus_trader.model import Currency, Equity, InstrumentId, Price, Quantity, QuoteTick, Symbol

from sextant.backtest.custody_witness import run

from .conftest import SEC, controls

START = 1_794_000_000 * SEC
IID = InstrumentId.from_str("AAA.SIM")


def native(tmp_path, *, owner_order=False):
    instrument = Equity(
        IID,
        Symbol("AAA"),
        Currency.from_str("USD"),
        2,
        Price.from_str("0.01"),
        0,
        0,
        lot_size=Quantity.from_int(1),
    )
    quotes = [
        QuoteTick(
            IID,
            Price.from_str("10.00"),
            Price.from_str("10.01"),
            Quantity.from_int(100),
            Quantity.from_int(100),
            START + i * SEC,
            START + i * SEC,
        )
        for i in range(16)
    ]
    return run(
        instrument=instrument,
        quotes=quotes,
        out=tmp_path,
        controls=controls(),
        starting_cash=D("10000"),
        quantity=D("20"),
        kill_after_ns=3 * SEC,
        owner_resting_order=owner_order,
        fee_model=MakerTakerFeeModel(maker_rate=D(0), taker_rate=D(0)),
        latency_model=StaticLatencyModel(
            insert_latency_nanos=SEC // 2, cancel_latency_nanos=SEC // 2
        ),
    )


def test_native_modeled_kill_to_flat_is_latched_and_never_flips_short(tmp_path):
    result = native(tmp_path)
    assert result.broker_net == D(0)
    assert result.minimum_net >= 0
    assert result.state == "HALTED"
    assert result.flat_receipt
    assert result.fills == 2
    assert result.order_types == {"LIMIT"}
    assert result.tier == "MODELED"
    assert result.fixture_only
    assert not result.entry_allowed
    assert result.errors == []


def test_native_guard_leaves_owner_fixture_order_open_and_never_cancels_it(tmp_path):
    result = native(tmp_path, owner_order=True)
    assert result.broker_net == 0
    assert result.owner_status == "ACCEPTED"
    assert result.owner_client_id not in result.cancelled_ids
    assert not result.flat_receipt  # An untouched owner entry still has possible-fill exposure.
    assert not result.entry_allowed
    assert result.errors == []
