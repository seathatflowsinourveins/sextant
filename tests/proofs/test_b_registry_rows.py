"""Paper B's registry rows, each loaded through the reader that consumes it (D-45; LEAD-0115).

entry: ``EntryParameters.from_rows``, the load B's Strategy needs (FIRST_LEG | SIZING);
re-entry: ``reentry.policy.Params``; gain lock: ``ExitParams`` and ``advance_gain_lock``'s
``round_trip_cost``; arms: their overrides through the same readers. A row no reader reads is
not kept. A row without value or authority stays UNAVAILABLE and its step stays off.
"""

from __future__ import annotations

import json
from dataclasses import fields, replace
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest
from test_b_gain_lock import advance
from test_b_lifecycle_entry import house, run_entry

from sextant.entry.parameters import COUNTS, FIRST_LEG, NAMES, SIZING, EntryParameters
from sextant.entry.surge import DEFAULT_CONFIG
from sextant.exits.policy import CHASE, REGISTRY, ExitParams
from sextant.reentry.policy import Params

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "lanes/paper"
RULING = (
    "extended to Paper B as an uncalibrated starting value by lead ruling LEAD-0115 "
    "(2026-11-11) under owner direction D-45: paper is never held back; each account's rows "
    "are its own arm"
)
ENTRY_KEYS = {"name", "unit", "value", "source", "calibration", "last_change", "scope"}
OTHER_KEYS = {"name", "unit", "value", "source", "calibration_state", "last_change"}
REENTRY_INTS = {"retry_rank_band", "rotation_rank_band", "whipsaw_stopouts_max"}
GAIN_SHARED = {
    "prearm_buffer_fraction",
    "prearm_range_multiple",
    "prearm_range_window_s",
    "gain_lock_giveback_fraction",
}
EXIT_FIELDS = {f.name for f in fields(ExitParams)}
# B's own exit file (LEAD-0310 ruling 6): every ExitParams row except chase_cap_fraction, whose one
# home is the entry file, plus the gain lock's cost.
GAIN_FILE = (EXIT_FIELDS - {"chase_cap_fraction"}) | {"round_trip_cost"}
SHARED_PREFIX = "Shared src/sextant/exits/policy.py REGISTRY; "


def _no_float(text: str) -> float:
    raise AssertionError(f"float in a registry file: {text}")  # Decimal strings or ints only


def load(name: str) -> list[dict[str, Any]]:
    return json.loads((PAPER / name).read_text(), parse_float=_no_float)


def entry_rows() -> list[dict[str, Any]]:
    return load("b-entry-parameters.json")


def exit_params(rows: list[dict[str, Any]]) -> ExitParams:
    """B's exit load from its own file only; an absent or UNAVAILABLE row is no authority.

    LEAD-0310 ruling 6: a row absent there is unavailable, with no fall-through to another file.
    Only the chase rows may stay unavailable (ExitParams: the chase is then off).
    """
    values: dict[str, Any] = {}
    for row in rows:
        name, value = row["name"], row["value"]
        if name not in EXIT_FIELDS:
            continue
        if row["calibration_state"] == "UNAVAILABLE":
            if value is not None:
                raise ValueError(f"{name}: an UNAVAILABLE row is no authority for its value")
            values[name] = None
        elif row["calibration_state"] != "UNCALIBRATED" or not row["source"]:
            raise ValueError(f"{name}: no sourced starting value")
        elif name == "breach_persist_count":
            values[name] = value if type(value) is int else None
        else:
            values[name] = D(value) if type(value) is str else None
    for name in CHASE:
        values.setdefault(name, None)
    missing = sorted(EXIT_FIELDS - set(values))
    if missing:
        raise ValueError(f"no authority in B's exit file: {missing}")
    return ExitParams(**values)  # a None in a required row raises here


def reentry(rows: list[dict[str, Any]]) -> Params:
    """Params from rows: ints stay ints, Decimal strings become Decimal, nothing else passes."""
    values: dict[str, Any] = {}
    for row in rows:
        value = row["value"]
        if row["name"] in REENTRY_INTS:
            values[row["name"]] = value if type(value) is int else None
        else:
            values[row["name"]] = D(value) if type(value) is str else None
    return Params(**values)


# -- entry: EntryParameters.from_rows ---------------------------------------------------


def test_entry_file_loads_its_first_leg_rows_through_the_reader() -> None:
    params = EntryParameters.from_rows(entry_rows(), first_leg_only=True)
    assert not params.fixture and set(params.values) == FIRST_LEG
    assert all(type(params[name]) is int for name in FIRST_LEG & COUNTS)


def test_the_strategy_load_refuses_on_chase_cap_fraction_alone() -> None:
    rows = entry_rows()
    with pytest.raises(ValueError, match=r"^chase_cap_fraction: unavailable"):
        EntryParameters.from_rows(rows, sizing_only=True)
    # the one gap: with only that row given a test value, the full B load passes
    patched = [
        row | {"value": "0.01", "scope": "FIXTURE_ONLY", "calibration": "UNCALIBRATED"}
        if row["name"] == "chase_cap_fraction"
        else row
        for row in rows
    ]
    loaded = EntryParameters.from_rows(patched, fixture=True, sizing_only=True)
    assert set(loaded.values) == FIRST_LEG | SIZING


def test_b_strategy_refuses_entry_with_the_files_rows(tmp_path) -> None:
    """The host cannot build the sizing load, so the Strategy names the rows and sends nothing."""
    narrow = EntryParameters.from_rows(entry_rows(), first_leg_only=True)
    journal, orders, strategy = run_entry(tmp_path, entry_params=narrow)
    (refusal,) = [row for row in journal if row["kind"] == "entry_refused"]
    assert set(refusal["missing"]) == SIZING - FIRST_LEG
    assert "chase_cap_fraction" in refusal["missing"]
    assert house(orders) == [] and strategy.sent == []


def test_entry_rows_are_the_sim_lanes_reviewed_rows_under_the_ruling() -> None:
    rows = entry_rows()
    sim = {r["name"]: r for r in json.loads((ROOT / "lanes/sim/entry-parameters.json").read_text())}
    assert [r["name"] for r in rows] == list(sim) and set(sim) == NAMES
    reviewed = set()
    for row in rows:
        assert set(row) == ENTRY_KEYS and row["source"] and row["unit"] and row["last_change"]
        if row["scope"] == "REVIEWED":
            reviewed.add(row["name"])
            base = sim[row["name"]]
            assert base["scope"] == "REVIEWED" and row["value"] == base["value"]
            assert type(row["value"]) is type(base["value"])
            assert base["source"].rstrip(";. ") in row["source"] and RULING in row["source"]
            assert row["calibration"] == "UNCALIBRATED"
        else:
            assert row["value"] is None
            assert row["scope"] == row["calibration"] == "UNAVAILABLE"
    assert reviewed == (FIRST_LEG | SIZING) - {"chase_cap_fraction"}


@pytest.mark.parametrize(
    ("name", "change", "error"),
    [
        ("first_leg_span_s", {"source": ""}, "missing source"),
        ("first_leg_max_move", {"value": 0.03}, "finite Decimal required"),
        ("first_leg_trades_count", {"value": "5"}, "positive integer required"),
        ("entry_ttl_s", {"scope": "UNAVAILABLE"}, "unavailable or unreviewed"),
        ("atr_period", {"calibration": None}, "missing calibration state"),
    ],
)
def test_a_damaged_entry_row_stops_the_load(name: str, change: dict, error: str) -> None:
    rows = [row | change if row["name"] == name else row for row in entry_rows()]
    with pytest.raises(ValueError, match=error):
        EntryParameters.from_rows(rows, first_leg_only=True)
    with pytest.raises(ValueError, match="missing, duplicate or unknown"):
        EntryParameters.from_rows([r for r in entry_rows() if r["name"] != name])


# -- re-entry: reentry.policy.Params -----------------------------------------------------


def test_reentry_file_holds_exactly_the_policy_params_and_stays_unavailable() -> None:
    rows = load("b-reentry-parameters.json")
    assert [r["name"] for r in rows] == [f.name for f in fields(Params)]
    for row in rows:
        assert set(row) == OTHER_KEYS and row["source"] and row["unit"] and row["last_change"]
        sourced = row["value"] is not None
        assert row["calibration_state"] == ("UNCALIBRATED" if sourced else "UNAVAILABLE")
        assert sourced or row["source"].startswith("UNAVAILABLE: no start at either pin")
    assert {r["name"] for r in rows if r["value"] is not None} == {"cooldown_seconds"}
    with pytest.raises(ValueError):
        reentry(rows)  # so B's Strategy is built with reentry_params=None: no re-entry
    test_values = {
        "retry_rank_band": 5,
        "rotation_rank_band": 10,
        "reentry_min_confidence": "0.6",
        "confidence_size_floor": "0.25",
        "rotation_lift_margin_bps": "10",
        "rotation_score_ratio": "1.2",
        "whipsaw_stopouts_max": 2,
    }
    filled = [r | {"value": test_values.get(r["name"], r["value"])} for r in rows]
    assert reentry(filled).cooldown_seconds == D("600")  # the sourced row loads as given


# -- gain lock: ExitParams and advance_gain_lock -----------------------------------------


def test_gain_lock_file_loads_into_the_exit_params_and_its_cost_keeps_arming_off() -> None:
    rows = {r["name"]: r for r in load("b-gain-lock.params.json")}
    assert set(rows) == GAIN_FILE
    params = exit_params(list(rows.values()))
    assert params == ExitParams.starts()  # the shared registry's starts, unchanged for B
    assert params.chase_on is False  # no chase authority in B's file
    cost = rows["round_trip_cost"]["value"]
    assert cost is None
    assert advance(params=params)[1] is True  # a cost would arm on these inputs
    trigger, armed = advance(params=params, round_trip_cost=cost)
    assert armed is False and trigger == advance(params=params, confirmation_price=None)[0]


def test_every_copied_exit_row_is_the_shared_registrys_value_and_source() -> None:
    rows = {r["name"]: r for r in load("b-gain-lock.params.json")}
    registry = {row.name: row for row in REGISTRY}
    for name in GAIN_FILE - {"round_trip_cost"}:
        row, shared = rows[name], registry[name]
        assert set(row) == OTHER_KEYS | {"scope"} and row["unit"] and row["last_change"]
        assert row["scope"] == "alpaca-paper-b"
        if shared.start is None:
            assert row["value"] is None and row["calibration_state"] == "UNAVAILABLE"
            assert row["source"].startswith(f"UNAVAILABLE: {SHARED_PREFIX}{shared.source}")
            continue
        assert row["calibration_state"] == "UNCALIBRATED"
        assert row["source"] == SHARED_PREFIX + shared.source
        expected = int(shared.start) if name == "breach_persist_count" else shared.start
        value = row["value"] if name == "breach_persist_count" else D(row["value"])
        assert value == expected and type(value) is type(expected)


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"breach_persist_count": {"value": None, "calibration_state": "UNAVAILABLE"}}, "int"),
        ({"chase_min_interval_s": {"value": "1"}}, "no authority for its value"),
        ({"take_profit_step_fraction": {"calibration_state": "UNAVAILABLE"}}, "no authority"),
        ({"quote_max_age_s": {"source": ""}}, "no sourced starting value"),
        ({"breach_persist_span_s": {"value": "inf"}}, "finite nonnegative Decimal"),
    ],
)
def test_an_unavailable_or_unsourced_exit_row_is_refused_as_authority(change, error) -> None:
    rows = [row | change.get(row["name"], {}) for row in load("b-gain-lock.params.json")]
    with pytest.raises(ValueError, match=error):
        exit_params(rows)


def test_an_absent_exit_row_is_unavailable_with_no_fall_through() -> None:
    rows = load("b-gain-lock.params.json")
    with pytest.raises(ValueError, match="quote_max_age_s"):
        exit_params([row for row in rows if row["name"] != "quote_max_age_s"])
    # chase_cap_fraction lives in the entry file; B's exit never reads it from there
    assert "chase_cap_fraction" not in {row["name"] for row in rows}
    assert exit_params(rows).chase_cap_fraction is None


# -- arms: their overrides through the same readers --------------------------------------


def test_the_aggressive_arm_differs_in_a_supported_direction() -> None:
    house_arm, aggressive = load("b-arms.json")
    assert house_arm["overrides"] == {}
    over = aggressive["overrides"]
    assert set(over) == {"first_leg_max_move", "prearm_buffer_fraction"}
    rows = [
        row | {"value": over[row["name"]]} if row["name"] in over else row for row in entry_rows()
    ]
    base = EntryParameters.from_rows(entry_rows(), first_leg_only=True)
    arm = EntryParameters.from_rows(rows, first_leg_only=True)
    grid = {D(n) / 100 for n in range(2, 21)}  # profiles.yaml:141, 0.02..0.20 step 0.01
    move = arm["first_leg_max_move"]
    assert move in grid and move > base["first_leg_max_move"] > DEFAULT_CONFIG.surge_move_min
    # readiness needs max(ask, last) <= quiet x (1 + cap): a larger cap admits a superset
    assert move - DEFAULT_CONFIG.surge_move_min == 2 * (
        base["first_leg_max_move"] - DEFAULT_CONFIG.surge_move_min
    )
    house_exit = ExitParams.starts()
    arm_exit = replace(house_exit, prearm_buffer_fraction=D(over["prearm_buffer_fraction"]))
    assert arm_exit.prearm_buffer_fraction == min({D("0.005"), D("0.01"), D("0.02")})  # T19:251
    assert arm_exit.prearm_buffer_fraction < house_exit.prearm_buffer_fraction


# -- one row per name, every row read ----------------------------------------------------


def test_every_b_row_has_a_reader_and_chase_cap_fraction_lives_once() -> None:
    names = {path.name for path in PAPER.glob("b-*.json")}
    assert "b-exit-parameters.json" not in names and "b-node-parameters.json" not in names
    rows = {
        "b-entry-parameters.json": NAMES,
        "b-reentry-parameters.json": {f.name for f in fields(Params)},
        "b-gain-lock.params.json": GAIN_FILE,
    }
    homes = [n for n, want in rows.items() if "chase_cap_fraction" in {r["name"] for r in load(n)}]
    assert homes == ["b-entry-parameters.json"]
    for name, want in rows.items():
        assert {r["name"] for r in load(name)} == want
    chase = {row.name: row.start for row in REGISTRY}["chase_cap_fraction"]
    assert chase is None  # the exit engine's own row agrees: no authority
