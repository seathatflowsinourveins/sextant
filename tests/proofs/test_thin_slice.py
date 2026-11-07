"""The trading path, end to end, on NautilusTrader's own example and test data."""

import hashlib
import json
import re
from pathlib import Path

import pytest

from sextant.backtest.thin_slice import run_window
from sextant.validation.trials import WITNESS_PATH, TrialLog

ROOT = Path(__file__).parents[2]
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _fills(folder: Path) -> str:
    # The engine gives each event a random UUID. Prices, sizes and times must match exactly.
    return UUID.sub(
        "", next(folder.glob("reports/thin-slice/replay-*/fills-replay.csv")).read_text()
    )


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
    rows = TrialLog(tmp_path / WITNESS_PATH).records
    assert [row["strategy"] for row in rows] == ["hold_flat", "EMACross"] * 2
    assert all(row["state"] == "COMPLETE" for row in rows)
    assert backtest.round_trips == 8 and replay.round_trips == 6
    assert not list(tmp_path.rglob("ledger.jsonl"))
    for window in ("backtest", "replay"):
        assert (
            next(tmp_path.glob(f"reports/thin-slice/{window}-*/fills-{window}.csv")).stat().st_size
            > 0
        )
        assert (
            next(tmp_path.glob(f"reports/thin-slice/{window}-*/tearsheet-{window}.html"))
            .stat()
            .st_size
            > 0
        )


def test_hold_flat_control_never_trades(tmp_path: Path) -> None:
    run = run_window("backtest", tmp_path)
    assert run.hold_flat_orders == 0
    assert run.hold_flat_pnl_usdt == "0"


def test_a_rerun_reproduces_its_numbers(tmp_path: Path) -> None:
    first = run_window("replay", tmp_path / "first")
    second = run_window("replay", tmp_path / "second")
    assert first == second
    assert _fills(tmp_path / "first") == _fills(tmp_path / "second")


@pytest.mark.parametrize("argument", ["paper_measurements", "inference", "merit_id"])
def test_deferred_merit_inputs_cannot_publish_false_verification(
    tmp_path: Path, argument: str
) -> None:
    with pytest.raises(TypeError, match=argument):
        run_window("backtest", tmp_path, **{argument: {"value": True, "status": "PASS"}})
    assert not (tmp_path / WITNESS_PATH).exists()


def test_repeated_native_runs_keep_distinct_attempts_and_artifacts(tmp_path: Path) -> None:
    first = run_window("replay", tmp_path)
    second = run_window("replay", tmp_path)
    assert first == second
    rows = TrialLog(tmp_path / WITNESS_PATH).records
    assert len(rows) == 4 and len({r["trial_id"] for r in rows}) == 4
    assert len({json.loads(r["config"])["arm_run_id"] for r in rows}) == 4
    assert len(list(tmp_path.glob("reports/thin-slice/replay-*/tearsheet-replay.html"))) == 2


def test_failed_strategy_setup_is_retained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sextant.backtest.thin_slice as thin

    def fail():
        raise ValueError("fixture setup failed")

    monkeypatch.setattr(thin, "_strategy", fail)
    with pytest.raises(ValueError, match="fixture setup failed"):
        run_window("backtest", tmp_path)
    assert [row["state"] for row in TrialLog(tmp_path / WITNESS_PATH).records] == ["FAIL", "FAIL"]
