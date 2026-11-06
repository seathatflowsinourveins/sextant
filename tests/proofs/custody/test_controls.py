"""Registry authority and unavailable protection reserves have runtime consequences."""

import json
from pathlib import Path

import pytest

from sextant.execution.pacer import AccountPacer, ActionKind
from sextant.risk.controls import Controls

from .conftest import control_rows

ROOT = Path(__file__).parents[3]


def test_fixture_rows_cannot_be_loaded_as_deployment_authority():
    with pytest.raises(ValueError, match="fixture"):
        Controls.from_rows(control_rows())
    rows = control_rows()
    rows[0]["source"] = ""
    with pytest.raises(ValueError, match="metadata"):
        Controls.from_rows(rows, fixture=True)


def test_sourced_registry_keeps_missing_reserves_unavailable_without_blocking_protection():
    rows = json.loads((ROOT / "lanes/custody-parameters.json").read_text())
    controls = Controls.from_rows(rows)
    assert controls["reserve_per_open_position"] is None
    assert controls["reserve_per_exiting_position"] is None
    pacer = AccountPacer(controls, lambda: 0)
    sends = []
    pacer.request(ActionKind.SUBMIT, lambda mark: (mark(), sends.append("entry")))
    pacer.request(ActionKind.REDUCE, lambda mark: (mark(), sends.append("protection")))
    assert sends == ["protection"]
