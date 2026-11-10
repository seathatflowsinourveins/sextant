"""First-leg-only mode: N1's own rows (Northstar FirstLegParams.from_row), no reclaim, and a
one-increment measurement-only witness that is refused outside MODELED replay."""

from decimal import Decimal as D

import pytest

from sextant.entry.parameters import FIRST_LEG, NAMES, EntryParameters
from sextant.entry.signals import EntryState, Extension

from .conftest import IID, SEC, START, quote, registry_rows, rows, trade
from .test_delta_gate import receipt, reclaim_tape
from .test_replay import replay
from .test_signals import feed


def first_leg_rows(missing=None):
    out = []
    for row in rows():
        if row["name"] not in FIRST_LEG or row["name"] == missing:
            row = dict(row, value=None, scope="UNAVAILABLE", calibration="UNCALIBRATED")
        out.append(row)
    return out


def first_leg_params():
    return EntryParameters.from_rows(first_leg_rows(), fixture=True, first_leg_only=True)


def test_the_mode_loads_first_leg_and_capacity_rows_and_the_full_mode_still_refuses():
    params = first_leg_params()
    assert (
        params.first_leg_only and set(params.values) == FIRST_LEG and len(NAMES - FIRST_LEG) == 18
    )
    with pytest.raises(KeyError):
        params["reclaim_hold_s"]  # reclaim, sizing and flow rows stay unread
    with pytest.raises(ValueError, match="unavailable or unreviewed authority"):
        EntryParameters.from_rows(first_leg_rows(), fixture=True)
    assert params.params_hash != EntryParameters.from_rows(rows(), fixture=True).params_hash


@pytest.mark.parametrize("missing", sorted(FIRST_LEG))
def test_the_mode_refuses_any_missing_first_leg_row(missing):
    with pytest.raises(ValueError, match=f"{missing}: unavailable or unreviewed authority"):
        EntryParameters.from_rows(first_leg_rows(missing), fixture=True, first_leg_only=True)


def test_the_production_registry_loads_reviewed_first_leg_and_capacity_rows_in_the_mode():
    params = EntryParameters.from_rows(registry_rows(), first_leg_only=True)
    assert params.first_leg_only and set(params.values) == FIRST_LEG
    assert params.values["first_leg_window_s"] == 120
    assert params.values["max_armed_symbols"] == 5
    with pytest.raises(ValueError, match="unavailable or unreviewed authority"):
        EntryParameters.from_rows(registry_rows())


@pytest.mark.parametrize("value", [None, 0, -1, True, "5", "5.5"])
def test_the_mode_refuses_an_unavailable_or_noninteger_arming_capacity(value):
    rows = registry_rows()
    for row in rows:
        if row["name"] == "max_armed_symbols":
            row["value"] = value
    with pytest.raises(ValueError, match="max_armed_symbols"):
        EntryParameters.from_rows(rows, first_leg_only=True)


def test_reclaim_cannot_fire_and_nothing_reads_extension_or_flow(instrument, tmp_path):
    s = EntryState(IID, first_leg_params(), "fixture-segment", start_ns=START - 3600 * SEC)
    for at in range(5):
        feed(s, at, "10.01")
    assert s.windows == {} and s.extension is Extension.UNKNOWN and s.reclaim_event_ns is None
    data = [*reclaim_tape(), quote("7.9", "10.02", "10.03")]
    result = replay(
        instrument,
        tmp_path,
        sorted(data, key=lambda item: item.ts_init),
        params=first_leg_params(),
        surge=None,
        confidence=D("0.5"),
        coverage=receipt({60 * SEC: 9, 2 * SEC: 2}),
    )
    assert not result.failed and result.orders == [], result.events


def test_covered_flow_is_false_in_first_leg_only_mode():
    # dsh P3: the public method must not raise KeyError just because the flow rows are absent.
    s = EntryState(IID, first_leg_params(), "fixture-segment", start_ns=START - 3600 * SEC)
    assert s.covered_flow(START, None) is False


@pytest.mark.parametrize(("tier", "fills"), [("MODELED", True), ("BROKER-PAPER", False)])
def test_witness_sizing_is_one_increment_and_refused_outside_modeled_replay(
    instrument, tmp_path, tier, fills
):
    data = [quote(0, "10.00", "10.02")] + [trade(at, "10.01", size=10000) for at in (0, 1, 2)]
    result = replay(instrument, tmp_path, data, params=first_leg_params(), tier=tier)
    assert result.tier == tier and not result.failed
    rows_ = [e for e in result.events if e["action"] in {"SUBMIT", "REFUSE"}]
    assert [e["binding_term"] for e in rows_] == ["measurement-only witness"], result.events
    if fills:
        assert rows_[0]["action"] == "SUBMIT" and rows_[0]["quantity"] == "1"
        assert [(o["status"], o["filled_qty"]) for o in result.orders] == [("FILLED", "1")]
    else:
        assert rows_[0]["reason"] == "witness sizing is measurement-only"
        assert result.orders == []
