"""C's request rate must be readable from C's own log, not from the vendor."""

import json
import os
import subprocess
import sys
import textwrap
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


PIPE_PROGRAM = textwrap.dedent(
    """
    import faulthandler
    import os
    import resource
    import sys
    import threading
    import time

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    from sextant.paper.request_counter import RequestLog

    descriptor = sys.stdout.fileno()
    os.set_blocking(descriptor, False)
    while True:
        try:
            os.write(descriptor, b"x" * 4096)
        except BlockingIOError:
            break
    os.set_blocking(descriptor, True)

    log = RequestLog(lambda: 0, time.monotonic, interval_s=0.01)
    if sys.argv[1] == "enabled":
        log.start()
    time.sleep(0.2)
    started = time.monotonic()
    log.stop()
    elapsed = time.monotonic() - started
    alive = any(thread.name == "c-request-log" for thread in threading.enumerate())
    os.write(2, f"stop_elapsed={elapsed:.6f}s alive={alive}\\n".encode())
    faulthandler.dump_traceback(file=sys.stderr)
    """
)


def _run_in_a_full_pipe(case: str) -> tuple[int, str]:
    """Runs the child interpreter with stdout a pipe nobody drains."""
    child = subprocess.Popen(
        [sys.executable, "-c", PIPE_PROGRAM, case],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
        return -1, "timed out with stdout still full"
    assert child.stdout is not None and child.stderr is not None
    stderr = child.stderr.read().decode()
    child.stdout.close()
    child.stderr.close()
    return child.returncode, stderr


def test_one_print_failure_still_tries_the_unavailable_line_once():
    clock = [0.0]
    attempts = []
    lines = []

    def transient(line):
        attempts.append(line)
        if len(attempts) == 1:
            raise OSError("stdout is gone")
        lines.append(line)

    log = RequestLog(lambda: 1, lambda: clock[0], out=transient)
    log.maybe_log()  # First call arms the interval.
    clock[0] = 60.0
    log.maybe_log()  # This print fails; exactly one guarded retry follows.
    clock[0] = 120.0
    log.maybe_log()  # Disabled: the sink is not touched again.
    assert lines == ["c-requests unavailable"]
    assert len(attempts) == 2


def test_a_full_pipe_does_not_change_the_exit_code_of_the_process_that_logs():
    control_exit, control_stderr = _run_in_a_full_pipe("disabled")
    assert control_exit == 0, control_stderr
    observer_exit, observer_stderr = _run_in_a_full_pipe("enabled")
    assert "alive=True" in observer_stderr, observer_stderr
    assert "in _default_out" in observer_stderr, observer_stderr
    assert observer_exit == 0, observer_stderr
