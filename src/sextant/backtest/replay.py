"""Recorded-bar mechanism replay, never continuous delivery or merit.

Sources: NautilusTrader's pinned BacktestNode API/tests; the merged #41 catalog
writer and #45 ExitEngine; northstar-trading@8256c16c sim_lanes/process.py and
runner.py for immutable publication and byte manifests (docs/manifest.md).
Each CLI invocation runs one fresh node under one host lease. No TrialLog is
created: #72 owns that binding. Missing execution data remains NOT ESTIMABLE.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import asdict
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from typing import Any

from nautilus_trader.backtest import BacktestNode
from nautilus_trader.config import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
)
from nautilus_trader.execution import DefaultFillModel, MakerTakerFeeModel, StaticLatencyModel
from nautilus_trader.model import AccountType, InstrumentId, NautilusDataType, OmsType

from sextant.backtest.exit_witness import FIXTURE, params_hash
from sextant.exits.engine import ExitEngine, ExitEngineConfig
from sextant.research.exit_study_41 import DEFAULT_INPUTS, verify_inputs, write_catalog

REPOSITORY = Path(__file__).resolve().parents[3]
ROOT = Path.home() / "sextant-data" / "replay-82"
BINDING = "NOT_RUN: #72 has not landed"


def _json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n"
    ).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value)).hexdigest()


def _files(root: Path, pattern: str) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob(pattern))
        if p.is_file()
    }


def _publish(path: Path, value: Any) -> None:
    """Carry process.publish's fsync + no-replace link, not a second journal."""
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)


def prepare_catalog(inputs: Path, root: Path) -> dict[str, Any]:
    """Use #41's existing writer only. No study run or overlapping acquisition."""
    hashes = verify_inputs(inputs)
    root.mkdir(parents=True, exist_ok=False)
    catalog = write_catalog(inputs / "minute-bars-2026-10-26_29.jsonl", root)
    instruments = sorted(str(i.id) for i in catalog.instruments())
    receipt = {
        "input_hashes": hashes,
        "catalog_hashes": _files(root, "*.parquet"),
        "instruments": instruments,
        "temporary": True,
        "origin": "#41 research Equity construction; not original node-native exports",
        "clocks": "ts_event = ts_init = minute open + 1 minute; acquisition time unknown",
        "source": "exit-study-41-inputs-2026-10-29",
    }
    if not instruments or not receipt["catalog_hashes"]:
        raise ValueError("empty catalog cannot supply replay evidence")
    _publish(root / "replay-catalog.json", receipt)
    return receipt


def _profile(seed: int) -> dict[str, Any]:
    """Explicit #45 fixture, never a fallback for missing calibrated parameters."""
    return {
        "strategy": "sextant.exits.engine:ExitEngine",
        "purpose": "MECHANISM_WITNESS_ONLY",
        "venue": "ALPACA",
        "oms_type": "NETTING",
        "account_type": "CASH",
        "book_type": "L1_MBP",
        "data_type": "Bar",
        "bar_spec": "1-MINUTE-LAST-EXTERNAL",
        "window": "all catalog data",
        "run_analysis": False,
        "bypass_logging": True,
        "params": {key: str(value) for key, value in asdict(FIXTURE).items()},
        "params_hash": params_hash(FIXTURE),
        "parameter_source": "merged #45 src/sextant/backtest/exit_witness.py:FIXTURE",
        "session": "rth",
        "starting_balance": "1000000 USD",
        "maker_rate": "0",
        "taker_rate": "0",
        "model_authority": "frictionless, zero-latency native fixture; not calibrated costs",
        "fill_model": "DefaultFillModel",
        "prob_fill_on_limit": "1.0",
        "prob_slippage": "0.0",
        "seed": seed,
        "latency_ns": {"base": 0, "insert": 0, "update": 0, "cancel": 0},
        "use_random_ids": False,
        "bar_execution": True,
        "bar_adaptive_high_low_ordering": False,
        "round_trip_cost": "instrument.price_increment; fixture only",
    }


def run_once(
    inputs: Path, catalog: Path, out: Path, *, seed: int, mechanism_witness: bool = False
) -> dict[str, Any]:
    """One fresh BacktestNode; the CLI supplies process isolation and host custody.

    Bar-only inputs cannot exercise #45's quote/trade-driven protective exits.
    Their missing returns are null, even when the native engine reports no orders.
    """
    if not mechanism_witness:
        raise ValueError(
            "explicit --mechanism-witness required; fixture values confer no authority"
        )
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError("seed must be an explicit unsigned 64-bit integer")
    out.mkdir(parents=True, exist_ok=False)
    profile = _profile(seed)
    manifest: dict[str, Any] = {
        "implementation_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPOSITORY, text=True
        ).strip(),
        "source_tree_sha256": _digest(_files(REPOSITORY / "src", "*.py")),
        "nautilus_version": version("nautilus-trader"),
        "arm_run_id": str(out.resolve()),
        "pid": os.getpid(),
        "strategy": profile["strategy"],
        "tier": "MODELED",
        "config": profile,
        "config_sha256": _digest(profile),
        "params_hash": profile["params_hash"],
        "seed": seed,
        "factor_mask": None,
        "weights_identity": None,
        "funding_uncertainty": "UNKNOWN",
        "n_trials": None,
        "effective_n": None,
        "daily_net_returns": None,
        "trial_log_binding": BINDING,
        "parameter_authority": "NONE: explicitly selected fixture values",
        "catalog_temporary": True,
        "catalog_path": str(catalog.resolve()),
        "state": "STARTED",
        "result_sha256": None,
    }
    _publish(out / "request.json", manifest)
    node: BacktestNode | None = None
    try:
        manifest["input_hashes"] = verify_inputs(inputs)
        receipt_bytes = (catalog / "replay-catalog.json").read_bytes()
        receipt = json.loads(receipt_bytes)
        manifest["catalog_receipt_sha256"] = hashlib.sha256(receipt_bytes).hexdigest()
        manifest["catalog_hashes"] = _files(catalog, "*.parquet")
        if (
            not manifest["catalog_hashes"]
            or manifest["catalog_hashes"] != receipt["catalog_hashes"]
            or manifest["input_hashes"] != receipt["input_hashes"]
        ):
            raise ValueError("catalog or raw input hash mismatch")
        ids = [InstrumentId.from_str(value) for value in receipt["instruments"]]
        if not ids or len(set(ids)) != len(ids) or any(str(i.venue) != "ALPACA" for i in ids):
            raise ValueError("nonempty unique research ALPACA instruments required")
        config = BacktestRunConfig(
            venues=[
                BacktestVenueConfig(
                    name="ALPACA",
                    oms_type=OmsType.NETTING,
                    account_type=AccountType.CASH,
                    starting_balances=[profile["starting_balance"]],
                    fee_model=MakerTakerFeeModel(Decimal(0), Decimal(0)),
                    fill_model=DefaultFillModel(
                        prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=seed
                    ),
                    latency_model=StaticLatencyModel(),
                    use_random_ids=False,
                    bar_execution=True,
                    bar_adaptive_high_low_ordering=False,
                )
            ],
            data=[
                BacktestDataConfig(
                    data_type=NautilusDataType.Bar,
                    catalog_path=str(catalog.resolve()),
                    instrument_id=i,
                    bar_types=[f"{i}-1-MINUTE-LAST-EXTERNAL"],
                )
                for i in ids
            ],
            engine=BacktestEngineConfig(bypass_logging=True, run_analysis=False),
            raise_exception=True,
            dispose_on_completion=False,
        )
        node = BacktestNode([config])
        node.build()
        strategies = []
        for iid in ids:
            instrument = node.get_engine_cache(config.id).instrument(iid)
            if instrument is None:
                raise ValueError(f"catalog instrument missing: {iid}")
            strategy = ExitEngine(
                ExitEngineConfig(
                    instrument_id=iid,
                    params=FIXTURE,
                    round_trip_cost=instrument.price_increment.as_decimal(),
                    session="rth",
                )
            )
            node.add_strategy(config.id, strategy)
            strategies.append(strategy)
        native = node.run()[0]
        if native.iterations == 0:
            raise ValueError("empty replay cannot establish determinism")
        if _files(catalog, "*.parquet") != manifest["catalog_hashes"]:
            raise ValueError("catalog hash changed during replay")
        if verify_inputs(inputs) != manifest["input_hashes"]:
            raise ValueError("raw input hash changed during replay")
        result = {
            "backtest_start": native.backtest_start,
            "backtest_end": native.backtest_end,
            "iterations": native.iterations,
            "total_events": native.total_events,
            "total_orders": native.total_orders,
            "total_positions": native.total_positions,
            "strategies": [str(s.instrument_id) for s in strategies],
            "strategy_events": {str(s.instrument_id): s.events for s in strategies},
            "daily_net_returns": None,
            "realized_pnl": None,
            "exit_execution": "NOT_ESTIMABLE: no recorded quotes, trades or entries",
        }
        _publish(out / "result.json", result)
        manifest.update(state="COMPLETED", result_sha256=_digest(result))
    except Exception as exc:
        manifest.update(state="FAILED", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        try:
            if node is not None:
                node.dispose()
        except Exception as exc:
            manifest.update(state="FAILED", error=f"disposal failed: {type(exc).__name__}: {exc}")
            raise
        finally:
            _publish(out / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("catalog", "run"))
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--mechanism-witness", action="store_true")
    args = parser.parse_args()
    if args.command == "run" and (args.out is None or args.seed is None):
        parser.error("run requires --out and --seed")
    for path in (args.catalog, args.out):
        if path is not None and not path.resolve().is_relative_to(ROOT.resolve()):
            parser.error(f"temporary catalog and outputs must be under {ROOT}")
    memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    if int(memory["MemAvailable"].split()[0]) * 1024 < 20_000_000_000:
        raise RuntimeError("replay refused: less than 20 GB MemAvailable")
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / ".execution.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == "catalog":
            prepare_catalog(args.inputs, args.catalog)
            print("temporary catalog prepared; no study or strategy run")
        else:
            result = run_once(
                args.inputs,
                args.catalog,
                args.out,
                seed=args.seed,
                mechanism_witness=args.mechanism_witness,
            )
            print(f"{result['state']}: {result['result_sha256']}; {BINDING}")


if __name__ == "__main__":
    main()
