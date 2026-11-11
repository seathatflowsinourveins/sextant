"""Paper B's sourced starting rows for entry, exit chase, re-entry and node cycles (D-45, R1).

Written before the rows existed: every test here failed while a listed row was absent or
carried no source. It now locks three things - the row shape, the sourced start values, and
the rows that stay MISSING because no pin records a value (a row without a source is never
guessed). Northstar pins are cited as `repo@sha:path:line`; a source must name one.
"""

import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from sextant.exits.policy import REGISTRY

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "lanes/paper"

FILES = {
    "entry": PAPER / "b-entry-parameters.json",
    "exit": PAPER / "b-exit-parameters.json",
    "reentry": PAPER / "b-reentry-parameters.json",
    "node": PAPER / "b-node-parameters.json",
}

ROW_KEYS = {"name", "unit", "value", "source", "calibration_state", "last_change"}

ENTRY_ROWS = {
    "first_leg_window_s",
    "first_leg_trades_count",
    "first_leg_span_s",
    "first_leg_max_move",
    "entry_max_vwap_extension_atr",
    "entry_chase_bps",
    "entry_ttl_s",
}
EXIT_ROWS = {"chase_cap_fraction", "chase_min_interval_s"}
REENTRY_ROWS = {
    "cooldown_seconds",
    "retry_rank_band",
    "rotation_rank_band",
    "reentry_min_confidence",
    "confidence_size_floor",
    "rotation_lift_margin_bps",
    "rotation_score_ratio",
    "whipsaw_stopouts_max",
    "reclaim_lookback_s",
    "reclaim_trades_count",
    "reclaim_trades_span_s",
    "reclaim_max_above_buffers",
    "reclaim_hold_s",
    "reentry_max",
    "flush_min_depth",
    "flush_window_s",
    "climax_window_s",
    "climax_ratio",
    "oversell_hold_s",
    "buy_flow_ratio",
    "flow_window_s",
    "oversell_max_above_buffers",
    "chase_cap_fraction",
    "catalyst_live_window_s",
    "climax_scale",
    "flow_scale",
    "climax_baseline_min",
}
NODE_ROWS = {
    "open_check_interval_secs",
    "position_check_interval_secs",
    "max_single_order_queries_per_cycle",
    "modify_rejection_page_count",
}
LISTED = {**{"entry": ENTRY_ROWS, "exit": EXIT_ROWS}, "reentry": REENTRY_ROWS, "node": NODE_ROWS}

# The row's start, and nothing more: each value is the one its source records (ADR-0004 N1-N4,
# ADR-0005 X5, ADR-0006 R1/R3/R3a/R3b, ADR-0019:296/299/300, lanes ADR-0006:95, lanes ADR-0007:135,
# northstar-trading@8256c16c profiles.yaml:50/55/114/126/138/162/174, northstar-lanes
# docs/m2b-classified-flow.md:113, src/northstar_lanes/registry.py:48, parameters.py:73,
# the s4-sizing-replay observations, and nautilus rc8 crates/live/src/node/config.rs:484-485).
VALUES = {
    "first_leg_window_s": "120",
    "first_leg_trades_count": "5",
    "first_leg_span_s": "2",
    "first_leg_max_move": "0.03",
    "entry_max_vwap_extension_atr": "2",
    "entry_chase_bps": "0",
    "entry_ttl_s": "1",
    "chase_cap_fraction": "0.01",
    "cooldown_seconds": "600",
    "whipsaw_stopouts_max": "2",
    "reclaim_lookback_s": "300",
    "reclaim_trades_count": "3",
    "reclaim_trades_span_s": "1",
    "reentry_max": "1",
    "flush_min_depth": "0.03",
    "flow_window_s": "10",
    "climax_window_s": "60",
    "climax_baseline_min": "30",
    "open_check_interval_secs": "10",
    "position_check_interval_secs": "10",
    "max_single_order_queries_per_cycle": "10",
    "modify_rejection_page_count": "3",
}

# No start exists at either pin. Each of these says MISSING and where it looked, and is never
# filled with a number that no source records.
MISSING = {
    "chase_min_interval_s",
    "retry_rank_band",
    "rotation_rank_band",
    "reentry_min_confidence",
    "confidence_size_floor",
    "rotation_lift_margin_bps",
    "rotation_score_ratio",
    "reclaim_max_above_buffers",
    "reclaim_hold_s",
    "flush_window_s",
    "climax_ratio",
    "oversell_hold_s",
    "buy_flow_ratio",
    "oversell_max_above_buffers",
    "catalyst_live_window_s",
    "climax_scale",
    "flow_scale",
}

# A source names a pinned upstream file and line, an ADR line, a research doc line or a vendor
# page with its read date. Prose alone is not a source.
SOURCE_MARKERS = (
    "@00203275944a:",
    "@8256c16c31dc:",
    "@7c5f852a2816:",
    "@00203275944a22655b3e14b221cfde9a265d549a:",
    "@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:",
    "@7c5f852a2816bbaa5896241a93bab9de7cf7bb4f:",
    "@d53849b216e20f2c122ca01b4dd0da377638b186:",
    "docs/adr/",
    "docs/research/",
    "docs/design.md:",
    "docs/handbook/",
    "read 2026-",
)


def rows_of(kind: str) -> list[dict[str, Any]]:
    return json.loads(FILES[kind].read_text())


def all_rows() -> list[dict[str, Any]]:
    return [row for kind in FILES for row in rows_of(kind)]


@pytest.mark.parametrize("kind", sorted(FILES))
def test_each_file_registers_exactly_the_listed_rows(kind: str) -> None:
    rows = rows_of(kind)
    names = [row["name"] for row in rows]
    assert len(names) == len(set(names))
    assert set(names) == LISTED[kind]


def test_every_row_keeps_the_registry_shape() -> None:
    for row in all_rows():
        assert set(row) == ROW_KEYS, row["name"]
        assert row["calibration_state"] == "UNCALIBRATED", row["name"]
        for key in ("unit", "source", "last_change"):
            assert isinstance(row[key], str) and row[key].strip(), (row["name"], key)
        assert date.fromisoformat(row["last_change"]) <= date(2026, 11, 10)


def test_every_row_names_a_source() -> None:
    for row in all_rows():
        source = row["source"]
        assert any(marker in source for marker in SOURCE_MARKERS), (row["name"], source)


def test_only_the_unrecorded_rows_stay_missing() -> None:
    missing = {row["name"] for row in all_rows() if row["value"] is None}
    assert missing == MISSING


def test_a_row_without_a_value_says_missing_and_where_it_looked() -> None:
    for row in all_rows():
        if row["value"] is not None:
            continue
        assert row["source"].startswith("MISSING:"), row["name"]
        assert "looked:" in row["source"], row["name"]


@pytest.mark.parametrize(("name", "value"), sorted(VALUES.items()))
def test_a_sourced_row_keeps_its_recorded_start(name: str, value: str) -> None:
    row = next(row for row in all_rows() if row["name"] == name)
    assert isinstance(row["value"], str)
    assert D(row["value"]) == D(value)
    assert row["value"] == value


def test_node_rows_keep_the_reconcile_once_per_interval_rate() -> None:
    rows = {row["name"]: row["value"] for row in rows_of("node")}
    b_parameters = json.loads((PAPER / "b-parameters.json").read_text())
    reconcile = next(row["value"] for row in b_parameters if row["name"] == "reconcile_interval_s")
    assert rows["open_check_interval_secs"] == reconcile
    assert rows["position_check_interval_secs"] == reconcile
    # 12 GETs a minute at 10 s each: one order GET plus one position GET per interval.
    assert int(rows["max_single_order_queries_per_cycle"]) <= 10
    assert int(rows["modify_rejection_page_count"]) == 3


def test_round_trip_cost_carries_the_one_tick_start() -> None:
    rows = json.loads((PAPER / "b-gain-lock.params.json").read_text())
    cost = next(row for row in rows if row["name"] == "round_trip_cost")
    assert D(cost["value"]) == D("0.01")
    assert "docs/adr/0019-managed-exits-and-ranked-reentry.md:94" in cost["source"]
    assert "docs/adr/0019-managed-exits-and-ranked-reentry.md:310" in cost["source"]
    assert "docs/adr/0005-exit-engine.md:28" in cost["source"]
    starts = {row.name: row.start for row in REGISTRY}
    for row in rows:
        if row["name"] != "round_trip_cost":
            assert D(row["value"]) == starts[row["name"]]


def test_the_aggressive_arm_is_registered_as_a_paired_arm() -> None:
    arms = json.loads((PAPER / "b-arms.json").read_text())
    by_id = {arm["arm_id"]: arm for arm in arms}
    assert len(by_id) == len(arms) == 2
    base = by_id["b-house-start-v1"]
    aggressive = by_id["b-aggressive-early-entry-tight-trail-v1"]
    assert base["overrides"] == {}
    assert aggressive["overrides"] == {
        "first_leg_max_move": "0.02",
        "prearm_buffer_fraction": "0.005",
    }
    for arm in arms:
        assert arm["state"] == "REGISTERED"
        assert arm["calibration_state"] == "UNCALIBRATED"
        assert arm["lane"] == "paper-b"
        assert arm["tier"] == base["tier"]
        assert arm["stack"] == base["stack"]
        assert arm["trial_ledger"] == "one cumulative ledger, ADR-0018"
        assert "runs" not in arm and "result" not in arm


def test_an_arm_override_names_a_registered_row_and_moves_it() -> None:
    gain_lock = json.loads((PAPER / "b-gain-lock.params.json").read_text())
    registered = {row["name"]: row["value"] for row in [*all_rows(), *gain_lock]}
    arms = json.loads((PAPER / "b-arms.json").read_text())
    aggressive = next(arm for arm in arms if arm["overrides"])
    for name, value in aggressive["overrides"].items():
        assert name in registered, name
        assert registered[name] is not None, name
        assert D(value) < D(registered[name]), name
