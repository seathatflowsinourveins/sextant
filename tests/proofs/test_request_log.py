"""C's request rate must be readable from C's own log, not from the vendor."""

import json
from pathlib import Path

from sextant.execution.pacer import AccountPacer, ActionKind
from sextant.paper.request_counter import (
    REQUEST_LOG_INTERVAL_S,
    CountingMarketData,
    RequestLog,
)
from sextant.risk.controls import Controls

ROOT = Path(__file__).resolve().parents[2]
CONTROLS = Controls.from_rows(json.loads((ROOT / "lanes/custody-parameters.json").read_text()))


class FakeData:
    """Stands in for StockHistoricalDataClient on C's universe path."""

    def __init__(self):
        self.calls = 0
        self.bars = {"AAA": ["bar"]}

    def get_stock_bars(self, request_params):
        self.calls += 1
        return self.bars


def test_one_interval_line_reports_the_pacers_wire_count_and_the_data_calls():
    clock = [0.0]
    pacer = AccountPacer(CONTROLS, lambda: int(clock[0] * 1_000_000_000))
    pacer.request(ActionKind.QUERY, lambda mark: mark())
    pacer.request(ActionKind.QUERY, lambda mark: mark())
    assert pacer.wire_requests == 2

    data = FakeData()
    lines = []
    log = RequestLog(lambda: pacer.wire_requests, lambda: clock[0], out=lines.append)
    counted = CountingMarketData(data, log.count_data_request)
    for _ in range(3):
        assert counted.get_stock_bars(object()) is data.bars
    assert data.calls == 3

    log.maybe_log()  # First call arms the interval; no line yet.
    assert lines == []
    clock[0] = 60.0
    log.maybe_log()
    assert lines == ["c-requests wire=2 data=3"]
    clock[0] = 119.9
    log.maybe_log()
    assert lines == ["c-requests wire=2 data=3"]


def test_a_raising_counter_never_blocks_the_data_call():
    data = FakeData()

    def broken():
        raise RuntimeError("counter down")

    counted = CountingMarketData(data, broken)
    assert counted.get_stock_bars("request") is data.bars
    assert data.calls == 1


def test_a_failing_counter_read_logs_one_line_and_never_raises():
    clock = [0.0]
    lines = []

    def broken():
        raise RuntimeError("counter down")

    log = RequestLog(broken, lambda: clock[0], out=lines.append)
    log.maybe_log()
    clock[0] = 60.0
    log.maybe_log()
    clock[0] = 120.0
    log.maybe_log()
    assert lines == ["c-requests unavailable"]


def test_the_log_interval_is_an_uncalibrated_row_at_its_source():
    rows = json.loads((ROOT / "lanes/paper/shared-node.params.json").read_text())
    row = next(row for row in rows if row["name"] == "request_log_interval_s")
    assert float(row["value"]) == REQUEST_LOG_INTERVAL_S
    assert row["calibration_state"] == "UNCALIBRATED"
