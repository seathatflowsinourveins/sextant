"""A nonempty native replay is reproducible; missing execution evidence stays missing."""

import hashlib
import json
from pathlib import Path

import pytest

from sextant.backtest import replay
from sextant.research import exit_study_41


@pytest.fixture
def recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Explicit tiny source fixture, never an authority for a real #41 input."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    rows = [
        {
            "symbol": symbol,
            "t": f"2026-10-26T13:{minute:02d}:00+00:00",
            "o": "10.0000",
            "h": "10.2000",
            "l": "9.9000",
            "c": "10.1000",
            "v": "1000.0",
        }
        for symbol in ("AAPL", "MSFT")
        for minute in (30, 31, 32)
    ]
    for name in exit_study_41.INPUTS:
        content = "\n".join(json.dumps(row) for row in rows) if name == exit_study_41.BARS else "[]"
        (inputs / name).write_text(content)
    # Isolated test evidence replaces only the pin expectations, not the checksum implementation.
    monkeypatch.setattr(
        exit_study_41,
        "INPUTS",
        {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()},
    )
    catalog = tmp_path / "catalog"
    replay.prepare_catalog(inputs, catalog)
    return inputs, catalog


def test_two_native_nodes_replay_every_bar_identically_with_missing_returns_kept_null(
    recorded: tuple[Path, Path], tmp_path: Path
) -> None:
    inputs, catalog = recorded
    manifests = [
        replay.run_once(inputs, catalog, tmp_path / name, seed=42, mechanism_witness=True)
        for name in ("first", "second")
    ]
    results = [
        json.loads((tmp_path / name / "result.json").read_text()) for name in ("first", "second")
    ]
    assert results[0] == results[1]
    assert results[0]["iterations"] == 6
    assert results[0]["strategies"] == ["AAPL.ALPACA", "MSFT.ALPACA"]
    assert results[0]["total_orders"] == 0
    assert results[0]["daily_net_returns"] is None
    assert results[0]["realized_pnl"] is None
    assert results[0]["exit_execution"] == "NOT_ESTIMABLE: no recorded quotes, trades or entries"
    assert manifests[0]["result_sha256"] == manifests[1]["result_sha256"]
    assert manifests[0]["config_sha256"] == manifests[1]["config_sha256"]
    for manifest in manifests:
        assert manifest["state"] == "COMPLETED"
        assert manifest["tier"] == "MODELED"
        assert manifest["trial_log_binding"] == "NOT_RUN: #72 has not landed"
        assert manifest["n_trials"] is None and manifest["effective_n"] is None
        assert manifest["catalog_temporary"] is True
        assert manifest["parameter_authority"] == "NONE: explicitly selected fixture values"
        assert len(manifest["implementation_sha"]) == 40
        assert len(manifest["source_tree_sha256"]) == 64
        assert manifest["input_hashes"] == exit_study_41.INPUTS


@pytest.mark.parametrize("target", ["raw", "parquet"])
def test_changed_input_is_refused_and_the_attempt_manifest_survives(
    recorded: tuple[Path, Path], tmp_path: Path, target: str
) -> None:
    inputs, catalog = recorded
    path = inputs / exit_study_41.BARS if target == "raw" else next(catalog.rglob("*.parquet"))
    path.write_bytes(path.read_bytes() + b"corruption")
    out = tmp_path / "failed"
    with pytest.raises(ValueError, match=r"hash|inputs differ"):
        replay.run_once(inputs, catalog, out, seed=42, mechanism_witness=True)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["state"] == "FAILED"
    assert manifest["result_sha256"] is None
    assert manifest["daily_net_returns"] is None
    assert (out / "request.json").is_file()


def test_source_and_run_artifacts_are_never_overwritten(
    recorded: tuple[Path, Path], tmp_path: Path
) -> None:
    inputs, catalog = recorded
    before = (catalog / "replay-catalog.json").read_bytes()
    with pytest.raises(FileExistsError):
        replay.prepare_catalog(inputs, catalog)
    assert (catalog / "replay-catalog.json").read_bytes() == before
    out = tmp_path / "run"
    replay.run_once(inputs, catalog, out, seed=42, mechanism_witness=True)
    before_run = {p.name: p.read_bytes() for p in out.iterdir()}
    with pytest.raises(FileExistsError):
        replay.run_once(inputs, catalog, out, seed=43, mechanism_witness=True)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before_run


def test_a_fixture_is_never_silently_a_parameter_default(
    recorded: tuple[Path, Path], tmp_path: Path
) -> None:
    inputs, catalog = recorded
    with pytest.raises(ValueError, match=r"explicit.*mechanism"):
        replay.run_once(inputs, catalog, tmp_path / "no-authority", seed=42)
    assert not (tmp_path / "no-authority").exists()


def test_seed_and_catalog_configuration_are_bound_to_each_attempt(
    recorded: tuple[Path, Path], tmp_path: Path
) -> None:
    inputs, catalog = recorded
    first = replay.run_once(inputs, catalog, tmp_path / "seed42", seed=42, mechanism_witness=True)
    second = replay.run_once(inputs, catalog, tmp_path / "seed43", seed=43, mechanism_witness=True)
    assert first["seed"] != second["seed"]
    assert first["config_sha256"] != second["config_sha256"]
    assert first["catalog_hashes"] == second["catalog_hashes"]


def test_the_runner_never_creates_a_second_ledger(
    recorded: tuple[Path, Path], tmp_path: Path
) -> None:
    inputs, catalog = recorded
    replay.run_once(inputs, catalog, tmp_path / "run", seed=42, mechanism_witness=True)
    assert not list(tmp_path.rglob("*ledger*"))


def test_recorded_full_data_pair_has_identical_results_from_distinct_processes() -> None:
    evidence = Path(__file__).parents[2] / "docs/research/2026-11-06-replay-82"
    manifests = [json.loads((evidence / f"run-{n}-manifest.json").read_text()) for n in (1, 2)]
    results = [(evidence / f"run-{n}-result.json").read_bytes() for n in (1, 2)]
    assert results[0] == results[1]
    assert json.loads(results[0])["iterations"] == 117486
    assert len(json.loads(results[0])["strategies"]) == 54
    assert manifests[0]["pid"] != manifests[1]["pid"]
    assert manifests[0]["implementation_sha"] == manifests[1]["implementation_sha"]
    assert manifests[0]["source_tree_sha256"] == manifests[1]["source_tree_sha256"]
    assert manifests[0]["config_sha256"] == manifests[1]["config_sha256"]
    for manifest, result in zip(manifests, results, strict=True):
        assert manifest["state"] == "COMPLETED"
        assert manifest["result_sha256"] == hashlib.sha256(result).hexdigest()
        assert manifest["input_hashes"] == exit_study_41.INPUTS
        assert manifest["daily_net_returns"] is None and manifest["n_trials"] is None
        assert manifest["trial_log_binding"] == "NOT_RUN: #72 has not landed"
