"""Review F7: the node's four windows come from registry rows; a flag is only a recorded override.

A sourced row is UNCALIBRATED; a window with no source is UNAVAILABLE (null), and the node then
refuses (the capacity bucket window) or runs without the feature (the snapshot recorder).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sextant.ranking import node_parameters

ROOT = Path(__file__).parents[2]


def test_the_rows_are_sourced_or_unavailable_never_invented() -> None:
    rows = node_parameters.load()
    assert set(rows) == {
        "page_window_s",
        "receipt_interval_s",
        "bucket_window_s",
        "status_snapshot_window_s",
    }
    assert (rows["page_window_s"].value, rows["page_window_s"].status) == (14400, "UNCALIBRATED")
    assert (rows["receipt_interval_s"].value, rows["receipt_interval_s"].status) == (
        60,
        "UNCALIBRATED",
    )
    for name in ("bucket_window_s", "status_snapshot_window_s"):
        assert (rows[name].value, rows[name].status) == (None, "UNAVAILABLE")
    assert all(row.source.strip() for row in rows.values())


def test_a_flag_overrides_and_says_so_and_an_unavailable_row_stays_none() -> None:
    rows = node_parameters.load()
    assert node_parameters.resolve(rows, "page_window_s", None) == (14400, "registry")
    assert node_parameters.resolve(rows, "page_window_s", 60) == (60, "override")
    assert node_parameters.resolve(rows, "bucket_window_s", None) == (None, "unavailable")
    assert node_parameters.resolve(rows, "bucket_window_s", 600) == (600, "override")


def test_a_malformed_registry_is_refused(tmp_path) -> None:
    bad = json.loads((ROOT / "deploy/ranking-node/parameters.json").read_text())
    bad["rows"]["page_window_s"]["value"] = "14400"  # a string is not a window
    path = tmp_path / "parameters.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="page_window_s"):
        node_parameters.load(path)
    bad["rows"]["page_window_s"]["value"] = 14400
    bad["rows"]["bucket_window_s"]["status"] = "UNCALIBRATED"  # null with a sourced status
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="bucket_window_s"):
        node_parameters.load(path)


def test_the_resolution_is_written_as_a_receipt(tmp_path) -> None:
    rows = node_parameters.load()
    resolved = {
        "page_window_s": node_parameters.resolve(rows, "page_window_s", None),
        "bucket_window_s": node_parameters.resolve(rows, "bucket_window_s", 600),
    }
    path = node_parameters.write_receipt(tmp_path, resolved)
    body = json.loads(path.read_text())
    assert body["page_window_s"] == {"value": 14400, "origin": "registry"}
    assert body["bucket_window_s"] == {"value": 600, "origin": "override"}
