"""Tests for the bar-only factor screen: frozen spec, causal signals, native fills.

The study protocol is `docs/research/2026-11-10-factor-screen-study.md`; these
tests pin its frozen values, the causal signal clock, the catalog volume-quantum
repair, the native fill path, and the all-arm TrialLog/table visibility.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
import pytest
from nautilus_trader.model import (
    AggregationSource,
    Bar,
    BarAggregation,
    BarSpecification,
    BarType,
    Currency,
    Equity,
    InstrumentId,
    OrderSide,
    Price,
    PriceType,
    Quantity,
    Symbol,
)

from sextant.backtest import factor_screen as fs
from sextant.validation.trials import TrialLog

ET = ZoneInfo("America/New_York")


def ts(day: int, minute: int) -> int:
    """A bar-close timestamp on 2026-10-day at 09:30 ET + minute."""
    dt = datetime(2026, 10, day, 9, 30, tzinfo=ET) + timedelta(minutes=minute)
    return int(dt.timestamp()) * 1_000_000_000


def equity(symbol: str) -> Equity:
    return Equity(
        InstrumentId.from_str(f"{symbol}.ALPACA"),
        Symbol(symbol),
        Currency.from_str("USD"),
        4,
        Price.from_str("0.0001"),
        0,
        0,
    )


def bar(symbol: str, close_ts: int, o: str, h: str, low: str, c: str, v: int) -> Bar:
    iid = InstrumentId.from_str(f"{symbol}.ALPACA")
    spec = BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST)
    return Bar(
        BarType(iid, spec, AggregationSource.EXTERNAL),
        Price.from_str(f"{Decimal(o):.4f}"),
        Price.from_str(f"{Decimal(h):.4f}"),
        Price.from_str(f"{Decimal(low):.4f}"),
        Price.from_str(f"{Decimal(c):.4f}"),
        Quantity.from_int(v),
        close_ts,
        close_ts,
    )


def test_clv_signals_use_only_the_completed_bar() -> None:
    bars = [bar("AAA", ts(26, i), "10", "11", "9", "10.5", 100) for i in range(4)]
    full = fs.clv_entries(bars)
    assert full, "the fixture must produce at least one CLV signal"
    prefix = fs.clv_entries(bars[: len(bars) // 2])
    cutoff = bars[len(bars) // 2 - 1].ts_event
    assert [entry for entry in full if entry[0] <= cutoff] == prefix


def test_k2_never_uses_the_same_session_as_baseline() -> None:
    rows: dict[InstrumentId, list[Bar]] = {}
    for symbol, step in (("AAA", "0.10"), ("BBB", "0.05")):
        series = []
        for day in (26, 27, 28):
            price = Decimal("10.00")
            for i in range(20):
                price = price + Decimal(step)
                series.append(
                    bar(
                        symbol,
                        ts(day, i),
                        str(price),
                        str(price + Decimal("0.1")),
                        str(price - Decimal("0.1")),
                        str(price),
                        100 + i,
                    )
                )
        rows[InstrumentId.from_str(f"{symbol}.ALPACA")] = series

    entries = fs.k2_entries(rows)
    assert entries, "the fixture must produce K2 candidates"
    assert all(fs.session_of(entry[0]) != "2026-10-26" for entry in entries)

    first_session_cut = max(
        b.ts_event
        for b in rows[InstrumentId.from_str("AAA.ALPACA")]
        if fs.session_of(b.ts_event) == "2026-10-26"
    )
    prefix_rows = {
        iid: [b for b in series if b.ts_event <= first_session_cut] for iid, series in rows.items()
    }
    assert fs.k2_entries(prefix_rows) == [
        entry for entry in entries if entry[0] <= first_session_cut
    ]


def verbose_bar(symbol: str, close_ts: int, volume: str) -> Bar:
    base = bar(symbol, close_ts, "10", "11", "9", "10.5", 300)
    return Bar(
        base.bar_type,
        base.open,
        base.high,
        base.low,
        base.close,
        Quantity.from_str(volume),
        base.ts_event,
        base.ts_init,
    )


def test_bar_volume_quantum_is_repaired_and_integral() -> None:
    verbose = verbose_bar("AAA", ts(26, 0), "300.0")
    assert verbose.volume.precision == 1
    repaired = fs.rebar(verbose)
    assert repaired.volume.precision == 0
    assert repaired.volume == Quantity.from_int(300)
    assert repaired.close == verbose.close and repaired.ts_event == verbose.ts_event

    with pytest.raises(ValueError, match="integral"):
        fs.rebar(verbose_bar("AAA", ts(26, 0), "300.5"))


def test_plan_respects_one_position_and_forced_session_exit() -> None:
    bars = [bar("AAA", ts(26, i), "10", "10.2", "9.8", "10", 100) for i in range(10)]
    rows = {InstrumentId.from_str("AAA.ALPACA"): bars}
    entries = [(bars[2].ts_event, bars[2].bar_type.instrument_id, Decimal("1"))]
    plan = fs.build_plan(entries, rows, horizon=3, top_k=None)
    actions = [side for actions in plan.values() for _, side in actions]
    assert actions.count(OrderSide.BUY) == 1
    assert actions.count(OrderSide.SELL) == 1
    sell_ts = next(
        t for t, actions in plan.items() if any(side is OrderSide.SELL for _, side in actions)
    )
    assert sell_ts == bars[5].ts_event


def test_native_run_fills_at_the_planned_bar_closes() -> None:
    symbol = "AAA"
    bars = [
        bar(symbol, ts(26, i), "10", "10.2", "9.8", str(Decimal("10") + Decimal(i) / 100), 100)
        for i in range(8)
    ]
    iid = InstrumentId.from_str("AAA.ALPACA")
    plan = {
        bars[2].ts_event: ((iid, OrderSide.BUY),),
        bars[5].ts_event: ((iid, OrderSide.SELL),),
    }
    result = fs.run_plan(bars, {iid: equity(symbol)}, plan, cost_bps=3, seed=7)
    trips = fs.round_trips(result["fills"])
    assert len(trips) == 1
    trip = trips[0]
    assert trip["buy_px"] == bars[2].close.as_decimal()
    assert trip["sell_px"] == bars[5].close.as_decimal()
    expected = (trip["sell_px"] - trip["buy_px"]) - (trip["buy_fee"] + trip["sell_fee"])
    assert trip["net_usd"] == expected
    assert result["metrics"]["n_trades"] == 1
    assert result["metrics"]["mean_net_bps"] == pytest.approx(
        float(expected / trip["buy_px"] * 10_000)
    )


def test_table_is_stamped_and_shows_every_arm() -> None:
    results = []
    for arm, spec in fs.ARMS.items():
        state = "COMPLETE" if spec["state"] == "RUNNABLE" else "FAIL"
        results.append(
            {
                "arm": arm,
                "state": state,
                "kind": spec["kind"],
                "source": spec["source"],
                "error": spec.get("missing", ""),
                "sample_state": "INSUFFICIENT_N",
                "costs": {
                    "1x": {
                        "n_trades": 0,
                        "mean_net_bps": 0.0,
                        "total_net_usd": 0.0,
                        "win_rate": 0.0,
                        "max_drawdown_usd": 0.0,
                    },
                    "2x": {
                        "n_trades": 0,
                        "mean_net_bps": 0.0,
                        "total_net_usd": 0.0,
                        "win_rate": 0.0,
                        "max_drawdown_usd": 0.0,
                    },
                },
                "days": ["2026-10-26"],
                "daily_net_returns": [0.0],
            }
        )
    text = fs.render_table(results, {"catalog_receipt_sha256": "x", "generated": "2026-11-10"})
    assert "SCREENING ONLY — NOT AN ADOPTED WINNER" in text
    for arm in fs.ARMS:
        assert arm in text
    for _arm, spec in fs.ARMS.items():
        if spec["state"] != "RUNNABLE":
            assert spec["missing"][:20] in text


def test_trial_rows_keep_every_arm_and_both_cost_conditions(tmp_path: Path) -> None:
    results = []
    for arm, spec in fs.ARMS.items():
        complete = spec["state"] == "RUNNABLE"
        results.append(
            {
                "arm": arm,
                "state": "COMPLETE" if complete else "FAIL",
                "kind": spec["kind"],
                "source": spec["source"],
                "error": spec.get("missing", ""),
                "sample_state": "INSUFFICIENT_N",
                "costs": {
                    "1x": {
                        "n_trades": 1,
                        "mean_net_bps": 1.0,
                        "total_net_usd": 5.0,
                        "win_rate": 1.0,
                        "max_drawdown_usd": 0.0,
                    },
                    "2x": {
                        "n_trades": 1,
                        "mean_net_bps": 0.5,
                        "total_net_usd": 4.0,
                        "win_rate": 1.0,
                        "max_drawdown_usd": 0.0,
                    },
                },
                "days": ["2026-10-26", "2026-10-27"],
                "daily_net_returns": [0.0, 5e-6],
                "condition_returns": {"cost_1x": [0.0, 5e-6], "cost_2x": [0.0, 4e-6]},
            }
        )
    path = tmp_path / "trials.parquet"
    fs.append_trials(
        TrialLog(path), results, {"implementation_sha": "0" * 40, "run_id": "test-run"}
    )
    table = pq.read_table(path)
    assert table.num_rows == len(fs.ARMS)
    assert table.column_names == [
        "trial_id",
        "strategy",
        "config",
        "params",
        "seed",
        "state",
        "error",
        "days",
        "daily_net_returns",
        "fold_scores",
        "objective",
        "n_trials",
        "effective_n",
    ]
    states = dict(
        zip(table.column("strategy").to_pylist(), table.column("state").to_pylist(), strict=True)
    )
    assert states["cash"] == "COMPLETE"
    assert states["k2_exact"] == "FAIL"
    assert set(table.column("effective_n").to_pylist()) == {None}
    config = json.loads(table.column("config").to_pylist()[0])
    assert config["tier"] == "MODELED"
    assert set(config["condition_returns"]) == {"cost_1x", "cost_2x"}


def test_study_constants_are_frozen() -> None:
    assert fs.STUDY["seed"] == 20261110
    assert fs.STUDY["horizon_bars"] == 30
    assert fs.STUDY["top_k"] == 3
    assert fs.STUDY["clv_threshold"] == "0.5"
    assert fs.STUDY["cost_bps"] == {"1x": 3, "2x": 6}
    assert fs.STUDY["quantity"] == 1
    assert fs.STUDY["start_balance"] == "1000000"
    runnable = {arm for arm, spec in fs.ARMS.items() if spec["state"] == "RUNNABLE"}
    assert runnable == {"cash", "buy_and_hold", "k2_bar_proxy", "h4_clv"}
    for arm, spec in fs.ARMS.items():
        assert spec["source"], arm
        if spec["state"] != "RUNNABLE":
            assert spec["missing"], arm


def test_buy_and_hold_is_a_benchmark_never_a_control() -> None:
    assert fs.ARMS["buy_and_hold"]["kind"] == "benchmark"
    assert fs.ARMS["cash"]["kind"] == "control"
    costs = {
        "1x": {"n_trades": 2, "mean_net_bps": 1.0, "total_net_usd": 2.0, "win_rate": 1.0},
        "2x": {"n_trades": 2, "mean_net_bps": 0.0, "total_net_usd": 0.0, "win_rate": 0.5},
    }
    results = [
        {
            "arm": arm,
            "state": "COMPLETE",
            "kind": kind,
            "source": "test",
            "sample_state": "INSUFFICIENT_N",
            "costs": costs,
        }
        for arm, kind in (("cash", "control"), ("buy_and_hold", "benchmark"))
    ]
    text = fs.render_table(results, {"catalog_receipt_sha256": "x", "generated": "2026-11-10"})
    controls = text.split("## Controls", 1)[1].split("\n## ", 1)[0]
    assert "buy_and_hold" not in controls
    assert "## Buy-and-hold benchmark" in text
    assert "buy_and_hold" in text.split("## Buy-and-hold benchmark", 1)[1]


def test_gains_accumulate_in_decimal_before_the_return_boundary() -> None:
    fills = []
    for index in range(3):
        at = ts(26, index * 2)
        fills += [
            {
                "instrument_id": "AAA.ALPACA",
                "side": "BUY",
                "ts_event": at,
                "px": Decimal("10.0000"),
                "qty": Decimal("1"),
                "fee": Decimal(0),
            },
            {
                "instrument_id": "AAA.ALPACA",
                "side": "SELL",
                "ts_event": at + 1,
                "px": Decimal("10.1000"),
                "qty": Decimal("1"),
                "fee": Decimal(0),
            },
        ]
    result = fs.metrics(fills)
    assert result["total_net_usd"] == float(Decimal("0.30"))
    day = fs.session_of(fills[0]["ts_event"])
    assert result["session_returns"][day] == float(Decimal("0.30") / Decimal(1_000_000))


def test_native_money_is_the_session_pnl_boundary() -> None:
    closes = ("10.0000", "10.0000", "10.0049", "10.0049")
    bars = [
        bar("AAA", ts(26, index), "10", "11", "9", close, 100) for index, close in enumerate(closes)
    ]
    iid = InstrumentId.from_str("AAA.ALPACA")
    plan = {
        bars[1].ts_event: ((iid, OrderSide.BUY),),
        bars[2].ts_event: ((iid, OrderSide.SELL),),
    }
    result = fs.run_plan(bars, {iid: equity("AAA")}, plan, cost_bps=3, seed=7)
    day = fs.session_of(bars[0].ts_event)
    assert result["metrics"]["session_returns"][day] == 0.0
    assert result["metrics"]["total_net_usd"] == 0.0


def test_insufficient_factor_rows_are_never_ranked() -> None:
    costs = {
        "1x": {"n_trades": 3, "mean_net_bps": 1.0, "total_net_usd": 1.0, "win_rate": 0.5},
        "2x": {"n_trades": 3, "mean_net_bps": 0.5, "total_net_usd": 0.5, "win_rate": 0.5},
    }
    results = [
        {
            "arm": arm,
            "state": "COMPLETE",
            "kind": "factor",
            "error": "",
            "sample_state": "INSUFFICIENT_N",
            "costs": costs,
        }
        for arm in ("k2_bar_proxy", "h4_clv")
    ]
    meta = {
        "study": "s",
        "generated": "g",
        "catalog_receipt_sha256": "x",
        "implementation_sha": "y",
    }
    text = fs.render_table(results, meta)
    assert re.search(r"^\| \d+ \|", text, re.MULTILINE) is None
    assert "INSUFFICIENT_N" in text
