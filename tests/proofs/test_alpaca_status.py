"""Status commands use the existing stream; unknown never retains trading state."""

import asyncio
import re
import threading
from importlib import import_module

import msgpack
import pytest
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import InstrumentStatus, MarketStatusAction
from test_alpaca_data import (
    INSTRUMENT_ID,
    START,
    StandInSocket,
    Witness,
    _WireTimestamp,
    run_shell,
)

STATUS = {"T": "s", "sc": "T", "sm": "Trading Resumption", "rc": "", "rm": "", "z": "C"}


@pytest.mark.parametrize(
    ("tape", "code", "action", "trading", "quoting"),
    [
        ("A", "2", "HALT", False, None),
        ("B", "2", "HALT", False, None),
        ("A", "3", "TRADING", True, None),
        ("B", "3", "TRADING", True, None),
        ("A", "5", "NEW_PRICE_INDICATION", None, None),
        ("B", "E", "SHORT_SELL_RESTRICTION_CHANGE", None, None),
        ("C", "H", "HALT", False, None),
        ("O", "H", "HALT", False, None),
        ("C", "T", "TRADING", True, None),
        ("O", "T", "TRADING", True, None),
        ("C", "Q", "QUOTING", False, True),
        ("O", "P", "PAUSE", False, None),
        ("C", "P", "PAUSE", False, None),
        ("C", "NEW_VENDOR_CODE", "NONE", None, None),
        ("A", "T", "NONE", None, None),
        ("C", "3", "NONE", None, None),
        ("UNKNOWN_TAPE", "T", "NONE", None, None),
        ("A", "7", "NONE", None, None),  # Imbalance has no native action.
        ("A", "F", "NONE", None, None),  # Bands alone do not mean halted/trading.
    ],
)
def test_status_codes_are_tape_scoped_and_never_infer_trading_from_text(
    tape, code, action, trading, quoting
):
    adapter = import_module("sextant.alpaca.data")
    convert = getattr(adapter, "_instrument_status", None)
    assert callable(convert), "Native instrument-status conversion is missing"
    stock = adapter._Stock(INSTRUMENT_ID, str(INSTRUMENT_ID.symbol), 2, 0)
    receipt = dt_to_unix_nanos(START) + 123
    event = convert(
        {**STATUS, "S": stock.symbol, "z": tape, "sc": code, "t": _WireTimestamp()},
        stock,
        receipt,
    )
    assert isinstance(event, InstrumentStatus)
    assert event.action == getattr(MarketStatusAction, action)
    assert event.is_trading is trading
    assert event.is_quoting is quoting
    assert event.is_short_sell_restricted is None
    assert event.instrument_id == INSTRUMENT_ID
    assert event.ts_event == dt_to_unix_nanos(START)
    assert event.ts_init == receipt
    if action == "NONE":
        assert event.trading_event == "unknown"


def test_bad_status_rows_do_not_stop_later_statuses_or_later_tick_subscriptions(monkeypatch, capfd):
    symbol = str(INSTRUMENT_ID.symbol)
    frames = []

    class StatusSocket(StandInSocket):
        async def send(self, data):
            data = data if isinstance(data, bytes) else b"".join(data)
            payload = msgpack.unpackb(data)
            frames.append(payload)
            if payload["action"] == "subscribe" and payload.get("statuses") == [symbol]:
                if "statuses" not in self.stream.delivered:
                    self.stream.delivered.add("statuses")
                    valid = {**STATUS, "S": symbol, "t": _WireTimestamp()}
                    # Known trading, invalid rows, halt, then unknown: the latest
                    # status must no longer leave the previous trading state current.
                    for row in (
                        valid,
                        {**valid, "t": "invalid timestamp"},
                        {**valid, "t": _WireTimestamp(START.replace(tzinfo=None))},
                        {**valid, "S": []},
                        {key: value for key, value in valid.items() if key != "S"},
                        {key: value for key, value in valid.items() if key != "sc"},
                        {**valid, "sc": "H", "sm": "Trading Halt"},
                        {**valid, "sm": "unknown"},  # Text does not determine normalized state.
                        {**valid, "sc": "NEW_VENDOR_CODE"},
                    ):
                        await self.stream._dispatch(row)
            await super().send(data)

    monkeypatch.setattr("test_alpaca_data.StandInSocket", StatusSocket)

    class StatusWitness(Witness):
        def __init__(self):
            super().__init__()
            self.statuses = []

        def on_start(self):
            self.subscribe_instrument_status(INSTRUMENT_ID)
            self.subscribe_instrument_status(INSTRUMENT_ID)  # No second wire membership.

        def on_instrument_status(self, status):
            self.statuses.append((status, threading.get_ident()))
            if len(self.statuses) == 4:
                self.unsubscribe_instrument_status(INSTRUMENT_ID)
                super().on_start()  # Actual native later subscriptions, after bad rows.

    owner = threading.get_ident()
    strategy, stream, history, client = asyncio.run(run_shell(strategy=StatusWitness()))
    assert isinstance(strategy, StatusWitness)
    statuses = [event for event, thread in strategy.statuses if thread == owner]
    assert [event.action for event in statuses] == [
        MarketStatusAction.TRADING,
        MarketStatusAction.HALT,
        MarketStatusAction.TRADING,
        MarketStatusAction.NONE,
    ]
    assert [event.is_trading for event in statuses] == [True, False, True, None]
    assert statuses[-1].trading_event == "unknown"
    assert all(event.ts_event == dt_to_unix_nanos(START) for event in statuses)
    assert all(event.ts_init >= event.ts_event for event in statuses)
    assert len(strategy.events) == 3
    assert all(thread == owner for _, thread in strategy.events)
    assert client.dropped_status_count == 5
    assert client.unknown_status_count == 1
    assert client._stream_state.failure is None
    assert stream.closed.is_set() and not history.calls
    assert all(not handlers for handlers in stream._handlers.values())
    assert not client._active["statuses"]
    status_frames = [frame for frame in frames if frame.get("statuses")]
    assert [(frame["action"], frame["statuses"]) for frame in status_frames] == [
        ("subscribe", [symbol]),
        ("unsubscribe", [symbol]),
    ]
    assert all("*" not in frame.get("statuses", ()) for frame in frames)
    client._log.flush()
    captured = capfd.readouterr()
    logs = re.sub(r"\x1b\[[0-9;]*m", "", captured.out + captured.err)
    dropped = [line for line in logs.splitlines() if "Dropped Alpaca statuses row" in line]
    unknown = [line for line in logs.splitlines() if "Unknown Alpaca status code" in line]
    assert len(dropped) == 5 and all("[ERROR]" in line for line in dropped)
    assert len(unknown) == 1
    assert all(symbol not in line for line in dropped + unknown)
