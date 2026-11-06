"""The trading path, end to end, on NautilusTrader's own example and test data."""

import hashlib
import json
import re
from pathlib import Path

from sextant.backtest.thin_slice import run_window

ROOT = Path(__file__).parents[2]
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _fills(folder: Path) -> str:
    # The engine gives each event a random UUID. Prices, sizes and times must match exactly.
    return UUID.sub("", (folder / "fills-replay.csv").read_text())


def test_strategy_is_verbatim_upstream() -> None:
    source = (ROOT / "src" / "sextant" / "strategies" / "ema_cross.py").read_bytes()
    assert hashlib.sha256(source).hexdigest() == (
        "0ce09c22bfbdffbad8c78f8578c220205219a594fe7ab10a2ca383eb2b57c541"
    )


def test_backtest_then_replay_reaches_ledger_and_merit_page(tmp_path: Path) -> None:
    backtest = run_window("backtest", tmp_path)
    replay = run_window("replay", tmp_path)
    assert backtest.backtest_end and replay.backtest_start
    assert backtest.backtest_end < replay.backtest_start
    assert [row["window"] for row in _rows(tmp_path / "ledger.jsonl")] == ["backtest", "replay"]
    for window in ("backtest", "replay"):
        assert (tmp_path / f"fills-{window}.csv").stat().st_size > 0
        assert (tmp_path / f"merit-{window}.html").stat().st_size > 0


def test_hold_flat_control_never_trades(tmp_path: Path) -> None:
    run = run_window("backtest", tmp_path)
    assert run.hold_flat_orders == 0
    assert run.hold_flat_pnl_usdt == "0"


def test_a_rerun_reproduces_its_numbers(tmp_path: Path) -> None:
    first = run_window("replay", tmp_path / "first")
    second = run_window("replay", tmp_path / "second")
    assert first == second
    assert _fills(tmp_path / "first") == _fills(tmp_path / "second")
