"""LEAD-1452 part 4a: B-scoped ExitParams mapping; fixtures confer no authority."""

import importlib
import json
from dataclasses import fields
from decimal import Decimal as D

import pytest

from sextant.exits.policy import ExitParams, buffer

from .test_b_order_node import ROOT


def dependencies():
    return importlib.import_module("sextant.paper.b_entry_dependencies")


def exit_rows():
    return json.loads((ROOT / "lanes/paper/b-gain-lock.params.json").read_text())


def test_b_maps_its_own_exit_rows_and_never_turns_on_chase():
    params = dependencies().load_exit_params(exit_rows())
    assert isinstance(params, ExitParams)
    assert params.prearm_buffer_fraction == D("0.01")
    assert params.prearm_range_multiple == D("1")
    assert params.prearm_range_window_s == D("10")
    assert params.breach_persist_count == 3
    assert params.quote_max_age_s == D("1")
    assert params.chase_cap_fraction is None and params.chase_min_interval_s is None
    assert params.chase_on is False
    assert all(
        type(getattr(params, f.name)) is D
        for f in fields(params)
        if f.name not in {"breach_persist_count", "chase_cap_fraction", "chase_min_interval_s"}
    )
    changed = [
        r | {"value": "0.02"} if r["name"] == "prearm_buffer_fraction" else r for r in exit_rows()
    ]
    assert dependencies().load_exit_params(changed).prearm_buffer_fraction == D("0.02")


@pytest.mark.parametrize(
    "name", [f.name for f in fields(ExitParams) if not f.name.startswith("chase_")]
)
@pytest.mark.parametrize("damage", ["absent", "source", "scope", "value"])
def test_each_required_exit_input_names_itself_and_refuses(name, damage):
    rows = exit_rows()
    if damage == "absent":
        rows = [r for r in rows if r["name"] != name]
    else:
        value = None if damage == "value" else ""
        rows = [r | {damage: value} if r["name"] == name else r for r in rows]
    with pytest.raises(ValueError, match=name):
        dependencies().load_exit_params(rows)


@pytest.mark.parametrize("name", ["round_trip_cost", "chase_min_interval_s"])
def test_unavailable_cost_and_exit_interval_cannot_be_silently_enabled(name):
    rows = [
        r | {"value": "0.002", "calibration_state": "UNCALIBRATED"} if r["name"] == name else r
        for r in exit_rows()
    ]
    with pytest.raises(ValueError, match=name):
        dependencies().load_exit_params(rows)


@pytest.mark.parametrize("damage", ["duplicate", "float", "bool", "nonfinite", "extra"])
def test_exit_loader_refuses_malformed_authority(damage):
    rows = exit_rows()
    name = "prearm_buffer_fraction"
    if damage == "duplicate":
        rows.append(rows[0])
    elif damage == "extra":
        rows.append(rows[0] | {"name": "chase_cap_fraction", "value": "0.0020"})
        name = "chase_cap_fraction"
    else:
        value = {"float": 0.01, "bool": True, "nonfinite": "NaN"}[damage]
        rows[0] = rows[0] | {"value": value}
    with pytest.raises((ValueError, TypeError), match=name):
        dependencies().load_exit_params(rows)


def test_missing_exit_range_refuses_the_buffer():
    params = dependencies().load_exit_params(exit_rows())
    assert buffer(D("0.01"), D("0.02"), D("10"), None, params) is None
