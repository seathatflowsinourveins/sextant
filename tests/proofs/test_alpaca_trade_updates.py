"""Corrections/cancels reach the native bus; malformed rows cannot kill peers."""

import asyncio
import re
import threading
from decimal import Decimal
from importlib import import_module

import msgpack
import pytest
from nautilus_trader.common import logging_sync_to_disk
from nautilus_trader.model import CustomData, DataType
from test_alpaca_data import (
    INSTRUMENT_ID,
    START,
    StandInSocket,
    Witness,
    _WireTimestamp,
    run_shell,
)

CORRECTION = {
    "T": "c",
    "S": "AAPL",
    "x": "D",
    "t": msgpack.Timestamp(1_794_236_400),
    "oi": 123,
    "op": "10.020000000000000001",
    "os": 7,
    "oc": ["@"],
    "ci": 456,
    "cp": "10.030000000000000002",
    "cs": 9,
    "cc": ["@"],
    "z": "C",
}
CANCEL = {
    "T": "x",
    "S": "AAPL",
    "x": "D",
    "t": msgpack.Timestamp(1_794_236_400),
    "i": 123,
    "p": "10.020000000000000001",
    "s": 7,
    "a": "C",
    "z": "C",
}


@pytest.mark.parametrize(("raw", "kind"), [(CORRECTION, "Correction"), (CANCEL, "Cancel")])
def test_update_keeps_original_identity_and_lossless_decimal_values(raw, kind):
    convert = getattr(import_module("sextant.alpaca.data"), "_trade_update", None)
    assert callable(convert), "Trade correction/cancel conversion is missing"
    envelope = convert(raw, INSTRUMENT_ID.venue, "sip", 1_794_236_400_000_000_123)
    assert isinstance(envelope, CustomData)
    assert envelope.data_type == DataType(f"AlpacaTrade{kind}", metadata={"feed": "sip"})
    event = envelope.data
    assert event.instrument_id == INSTRUMENT_ID
    assert event.symbol == "AAPL" and event.exchange == "D"
    assert event.original_id == 123
    assert event.original_price == Decimal("10.020000000000000001")
    assert event.original_size == Decimal(7)
    assert isinstance(event.original_price, Decimal) and isinstance(event.original_size, Decimal)
    assert envelope.ts_event == 1_794_236_400_000_000_000
    assert envelope.ts_init == 1_794_236_400_000_000_123
    assert event.tape == "C"
    if kind == "Correction":
        assert event.corrected_id == 456
        assert event.corrected_price == Decimal("10.030000000000000002")
        assert event.corrected_size == Decimal(9)
        assert event.original_conditions == event.corrected_conditions == ("@",)
    else:
        assert event.action == "C"


@pytest.mark.parametrize("action", ["C", "E"])
def test_cancel_keeps_vendor_action_and_large_trade_id(action):
    convert = getattr(import_module("sextant.alpaca.data"), "_trade_update", None)
    assert callable(convert), "Trade correction/cancel conversion is missing"
    envelope = convert(
        {**CANCEL, "a": action, "i": 12345678901234567890},
        INSTRUMENT_ID.venue,
        "iex",
        1_794_236_400_000_000_123,
    )
    assert isinstance(envelope, CustomData)
    event = envelope.data
    assert event.original_id == 12345678901234567890 and event.action == action


@pytest.mark.parametrize("raw", [CORRECTION, CANCEL])
@pytest.mark.parametrize(
    "change",
    [
        {"S": []},
        {"S": ""},
        {"x": ""},
        {"t": "invalid"},
        {"t": _WireTimestamp(START.replace(tzinfo=None))},
        {"z": None},
    ],
)
def test_malformed_identity_is_rejected_inside_conversion(raw, change):
    convert = getattr(import_module("sextant.alpaca.data"), "_trade_update", None)
    assert callable(convert), "Trade correction/cancel conversion is missing"
    with pytest.raises((ValueError, TypeError, KeyError, AttributeError)):
        convert({**raw, **change}, INSTRUMENT_ID.venue, "sip", 1_794_236_400_000_000_123)


@pytest.mark.parametrize(
    ("raw", "change"),
    [
        (CORRECTION, {"oi": None}),
        (CORRECTION, {"ci": None}),
        (CORRECTION, {"op": "NaN"}),
        (CORRECTION, {"cp": "Infinity"}),
        (CORRECTION, {"os": -1}),
        (CORRECTION, {"cs": "1.5"}),
        (CANCEL, {"i": None}),
        (CANCEL, {"p": 0}),
        (CANCEL, {"s": -1}),
        (CANCEL, {"a": "unknown"}),
        (CORRECTION, {"oc": None}),
    ],
)
def test_unconvertible_update_fields_are_rejected(raw, change):
    convert = getattr(import_module("sextant.alpaca.data"), "_trade_update", None)
    assert callable(convert), "Trade correction/cancel conversion is missing"
    with pytest.raises((ValueError, TypeError, KeyError, AttributeError)):
        convert({**raw, **change}, INSTRUMENT_ID.venue, "sip", 1_794_236_400_000_000_123)


def test_bad_updates_do_not_stop_bus_delivery_or_later_channel_subscriptions(monkeypatch, capfd):
    frames = []

    class UpdateSocket(StandInSocket):
        async def send(self, data):
            data = data if isinstance(data, bytes) else b"".join(data)
            payload = msgpack.unpackb(data)
            frames.append(payload)
            if payload["action"] == "subscribe" and payload.get("trades") == ["AAPL"]:
                if "updates" not in self.stream.delivered:
                    self.stream.delivered.add("updates")
                    for valid, price in ((CORRECTION, "op"), (CANCEL, "p")):
                        for row in (
                            {**valid, price: "NaN"},
                            {**valid, "S": []},
                            {k: v for k, v in valid.items() if k != "t"},
                            {**valid, "t": _WireTimestamp(START.replace(tzinfo=None))},
                            valid,
                        ):
                            await self.stream._dispatch(row)
            await super().send(data)

    monkeypatch.setattr("test_alpaca_data.StandInSocket", UpdateSocket)

    class UpdateWitness(Witness):
        def __init__(self):
            super().__init__()
            self.updates = []

        def on_start(self):
            for kind in ("Correction", "Cancel"):
                self.subscribe_data(DataType(f"AlpacaTrade{kind}", metadata={"feed": "sip"}))
            self.subscribe_trades(INSTRUMENT_ID)

        def on_data(self, data):
            self.updates.append((data, threading.get_ident()))
            if len(self.updates) == 2:
                # These real native commands run after all bad rows.
                super().on_start()

    owner = threading.get_ident()
    strategy, stream, history, client = asyncio.run(run_shell(strategy=UpdateWitness()))
    assert isinstance(strategy, UpdateWitness)
    assert len(strategy.updates) == 2
    assert [e.data_type.type_name for e, _ in strategy.updates] == [
        "AlpacaTradeCorrection",
        "AlpacaTradeCancel",
    ]
    assert all(thread == owner for _, thread in strategy.updates)
    assert len(strategy.events) == 3 and all(thread == owner for _, thread in strategy.events)
    assert client.trade_correction_count == client.trade_cancel_count == 1
    assert client.dropped_correction_count == client.dropped_cancel_count == 4
    assert client._stream_state.failure is None
    assert stream.closed.is_set() and not history.calls
    assert all(not handlers for handlers in stream._handlers.values())
    assert all(not frame.get("corrections") and not frame.get("cancelErrors") for frame in frames)
    assert all("*" not in frame.get("trades", ()) for frame in frames)
    logging_sync_to_disk()
    captured = capfd.readouterr()
    logs = re.sub(r"\x1b\[[0-9;]*m", "", captured.out + captured.err)
    assert sum("Dropped Alpaca corrections row" in line for line in logs.splitlines()) == 4
    assert sum("Dropped Alpaca cancelErrors row" in line for line in logs.splitlines()) == 4


def test_wire_timestamp_keeps_nanoseconds_in_the_original_trade_identity():
    convert = getattr(import_module("sextant.alpaca.data"), "_trade_update", None)
    assert callable(convert), "Trade correction/cancel conversion is missing"
    envelope = convert(
        {**CORRECTION, "t": msgpack.Timestamp(1_794_236_400, 123_456_789)},
        INSTRUMENT_ID.venue,
        "sip",
        1_794_236_400_987_654_321,
    )
    assert isinstance(envelope, CustomData)
    assert envelope.ts_event == 1_794_236_400_123_456_789
    assert envelope.ts_init == 1_794_236_400_987_654_321


@pytest.mark.parametrize(
    ("raw", "channel"), [(CORRECTION, "corrections"), (CANCEL, "cancelErrors")]
)
def test_updates_follow_current_trade_membership_and_shutdown(monkeypatch, raw, channel):
    from test_alpaca_data import offline_client

    adapter = import_module("sextant.alpaca.data")
    client = offline_client()
    published = []
    monkeypatch.setattr(client, "_handle_data", published.append)
    event = adapter._trade_update(raw, INSTRUMENT_ID.venue, "sip", 1_794_236_400_000_000_123)
    client._publish(channel, "AAPL", INSTRUMENT_ID, event)
    assert not published  # No trade membership.
    client._active["trades"]["AAPL"] = INSTRUMENT_ID
    client._publish(channel, "AAPL", INSTRUMENT_ID, event)
    assert published == [event]
    client._publish(channel, "MSFT", INSTRUMENT_ID, event)
    del client._active["trades"]["AAPL"]
    client._publish(channel, "AAPL", INSTRUMENT_ID, event)
    client._active["trades"]["AAPL"] = INSTRUMENT_ID
    client._stream_state.closing = True
    client._publish(channel, "AAPL", INSTRUMENT_ID, event)
    assert published == [event]
    assert client.trade_correction_count + client.trade_cancel_count == 1
    assert client.dropped_correction_count + client.dropped_cancel_count == 0


def test_later_trade_membership_keeps_both_global_update_handlers(monkeypatch):
    from nautilus_trader.model import Currency, Equity, Price, Quantity, Symbol
    from test_alpaca_data import ProofProvider

    other = type(INSTRUMENT_ID).from_str("MSFT.ALPACA")
    original_load = ProofProvider.load_all_async

    async def load_all(self, filters=None):
        await original_load(self, filters)
        self.add(
            Equity(
                other,
                Symbol("MSFT"),
                Currency.from_str("USD"),
                2,
                Price.from_str("0.01"),
                0,
                0,
                lot_size=Quantity.from_int(1),
            )
        )

    monkeypatch.setattr(ProofProvider, "load_all_async", load_all)

    class UpdateSocket(StandInSocket):
        async def send(self, data):
            data = data if isinstance(data, bytes) else b"".join(data)
            payload = msgpack.unpackb(data)
            if payload["action"] == "subscribe" and "AAPL" in payload.get("trades", ()):
                if "first-update" not in self.stream.delivered:
                    self.stream.delivered.add("first-update")
                    await self.stream._dispatch(CORRECTION)
                if "MSFT" in payload["trades"] and "second-update" not in self.stream.delivered:
                    self.stream.delivered.add("second-update")
                    await self.stream._dispatch(CANCEL)  # Earlier symbol still works.
                    await self.stream._dispatch({**CORRECTION, "S": "MSFT", "oi": 999})
            await super().send(data)

    monkeypatch.setattr("test_alpaca_data.StandInSocket", UpdateSocket)

    class UpdateWitness(Witness):
        def __init__(self):
            super().__init__()
            self.updates = []

        def on_start(self):
            for kind in ("Correction", "Cancel"):
                self.subscribe_data(DataType(f"AlpacaTrade{kind}", metadata={"feed": "sip"}))
            super().on_start()
            self.subscribe_trades(other)

        def on_data(self, data):
            self.updates.append(data)
            self.finish_if_complete()

        def receive(self, event):
            self.events.append((event, threading.get_ident()))
            self.finish_if_complete()

        def finish_if_complete(self):
            if len(self.updates) == len(self.events) == 3:
                self.unsubscribe_quotes(INSTRUMENT_ID)
                self.finished.set()

    strategy, stream, history, client = asyncio.run(run_shell(strategy=UpdateWitness()))
    assert isinstance(strategy, UpdateWitness)
    assert [(event.data.symbol, event.data.original_id) for event in strategy.updates] == [
        ("AAPL", 123),
        ("AAPL", 123),
        ("MSFT", 999),
    ]
    assert client.trade_correction_count == 2 and client.trade_cancel_count == 1
    assert client._stream_state.failure is None
    assert len(stream.thread_ids) == 1 and stream.closed.is_set() and not history.calls
