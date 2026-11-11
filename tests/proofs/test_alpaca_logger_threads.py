"""An engine Logger must not cross threads: build it where it logs.

nautechsystems/nautilus_trader@d53849b crates/common/src/python/logging.rs:434-438 declares
the Python ``Logger`` an ``unsendable`` pyclass; PyO3 aborts the whole process when such an
object is used from a thread other than the one that created it. A module-level Logger is
created on the importing thread, so a node whose loop runs on another thread aborts on its
first record. The crash is reproduced in a child process so the test run survives it.
"""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]

CHILD = """
import threading
from uuid import UUID
from alpaca.trading.models import Position
from nautilus_trader.model import AccountId, Currency, Equity, InstrumentId, Price, Symbol
from sextant.alpaca.reports import position_status_report

stock = Equity(InstrumentId.from_str("TEST.ALPACA"), Symbol("TEST"), Currency.from_str("USD"),
               2, Price.from_str("0.01"), 0, 0)
row = {"asset_id": str(UUID(int=3)), "symbol": "TEST", "exchange": "NASDAQ",
       "asset_class": "crypto", "avg_entry_price": "1", "qty": "5", "cost_basis": "5",
       "side": "long"}

def report():
    # An out-of-scope asset class logs one warning record, then returns None.
    print(position_status_report(Position.model_validate(row), account_id=AccountId("ALPACA-1"),
                                 instrument=stock, ts_init=0), flush=True)

thread = threading.Thread(target=report)
thread.start()
thread.join()
print("survived", flush=True)
"""


def test_report_logging_from_another_thread_does_not_abort_the_process():
    child = subprocess.run(
        [sys.executable, "-c", CHILD],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert child.returncode == 0, child.stderr[-2000:]
    assert child.stdout.splitlines()[-2:] == ["None", "survived"]


def test_no_alpaca_module_holds_a_module_level_engine_logger():
    for path in sorted((ROOT / "src" / "sextant" / "alpaca").glob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call):
                called = node.value.func
                name = called.id if isinstance(called, ast.Name) else getattr(called, "attr", "")
                assert name != "Logger", f"{path.name}:{node.lineno} module-level engine Logger"
