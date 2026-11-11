"""Run the frozen bar-only factor screen on the verified #41 replay catalog.

Protocol: docs/research/2026-11-10-factor-screen-study.md. Writes screen.json,
the canonical TrialLog and, with --table, the stamped markdown table. Native
NautilusTrader engine only; no broker, no key, no network. The catalog receipt
is re-verified against the pinned raw inputs before any arm runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from nautilus_trader.persistence import ParquetDataCatalog

from sextant.backtest import factor_screen as fs
from sextant.backtest import replay
from sextant.backtest.exit_inputs import DEFAULT_INPUTS
from sextant.validation.trials import TrialLog

REPOSITORY = Path(__file__).resolve().parents[1]


def verify(inputs: Path, catalog: Path) -> dict:
    receipt = json.loads((catalog / "replay-catalog.json").read_text())
    hashes = {
        str(path.relative_to(catalog)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(catalog.rglob("*.parquet"))
    }
    if receipt.get("input_hashes") != replay.verify_inputs(inputs):
        raise ValueError("catalog receipt input hashes differ from the pinned inputs")
    if receipt.get("catalog_hashes") != hashes:
        raise ValueError("catalog bytes differ from the receipt")
    if not receipt.get("instruments"):
        raise ValueError("catalog receipt lists no instruments")
    return receipt


def load(catalog: Path) -> tuple[dict, dict]:
    store = ParquetDataCatalog(str(catalog))
    instruments = {instrument.id: instrument for instrument in store.instruments()}
    rows = {
        iid: sorted(
            (fs.rebar(bar) for bar in store.query_bars(identifiers=[str(iid)])),
            key=lambda bar: bar.ts_event,
        )
        for iid in instruments
    }
    return instruments, rows


def plan_for(arm: str, rows: dict) -> fs.Plan:
    if arm == "cash":
        return {}
    if arm == "buy_and_hold":
        return fs.buy_and_hold_plan(rows)
    horizon = int(fs.STUDY["horizon_bars"])
    if arm == "k2_bar_proxy":
        return fs.build_plan(
            fs.k2_entries(rows), rows, horizon=horizon, top_k=int(fs.STUDY["top_k"])
        )
    entries = [
        (ts_event, iid, score)
        for iid, series in rows.items()
        for ts_event, score in fs.clv_entries(series)
    ]
    return fs.build_plan(entries, rows, horizon=horizon)


def arm_result(arm: str, plan: fs.Plan, bars: list, instruments: dict, days: list[str]) -> dict:
    costs = {
        label: fs.run_plan(bars, instruments, plan, cost_bps=int(bps), seed=int(fs.STUDY["seed"]))[
            "metrics"
        ]
        for label, bps in fs.STUDY["cost_bps"].items()
    }
    n_trades = costs["1x"]["n_trades"]
    return {
        "arm": arm,
        "state": "COMPLETE",
        "kind": fs.ARMS[arm]["kind"],
        "source": fs.ARMS[arm]["source"],
        "error": "",
        "sample_state": "INSUFFICIENT_N" if n_trades < 30 or len(days) < 5 else "SCREEN_ONLY",
        "costs": costs,
        "days": days,
        "daily_net_returns": [costs["1x"]["session_returns"].get(day, 0.0) for day in days],
        "condition_returns": {
            f"cost_{label}": [costs[label]["session_returns"].get(day, 0.0) for day in days]
            for label in fs.STUDY["cost_bps"]
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bar-only factor screening (#41 catalog).")
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--table", type=Path)
    args = parser.parse_args(argv)
    receipt = verify(args.inputs, args.catalog)
    instruments, rows = load(args.catalog)
    bars = [bar for series in rows.values() for bar in series]
    days = sorted({fs.session_of(bar.ts_event) for bar in bars})
    results = []
    for arm, spec in fs.ARMS.items():
        if spec["state"] == "RUNNABLE":
            results.append(arm_result(arm, plan_for(arm, rows), bars, instruments, days))
        else:
            results.append(
                {
                    "arm": arm,
                    "state": "FAIL",
                    "kind": spec["kind"],
                    "source": spec["source"],
                    "error": f"{spec['state']}: {spec['missing']}",
                    "sample_state": "INSUFFICIENT_N",
                    "costs": {},
                    "days": [],
                    "daily_net_returns": [],
                    "condition_returns": {},
                }
            )
    meta = {
        "study": fs.STUDY["name"],
        "seed": int(fs.STUDY["seed"]),
        "tier": "MODELED",
        "catalog_receipt_sha256": hashlib.sha256(
            (args.catalog / "replay-catalog.json").read_bytes()
        ).hexdigest(),
        "catalog_path": str(args.catalog),
        "inputs_path": str(args.inputs),
        "instrument_count": len(instruments),
        "bar_count": len(bars),
        "days": days,
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "implementation_sha": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPOSITORY, capture_output=True, text=True, check=True
        ).stdout.strip(),
        "stamp": fs.STAMP,
        "catalog_receipt": receipt,
        "run_id": str(uuid4()),
    }
    args.out.mkdir(parents=True, exist_ok=False)
    payload = {"meta": meta, "results": results}
    (args.out / "screen.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    )
    fs.append_trials(TrialLog(args.out / "trials.parquet"), results, meta)
    if args.table is not None:
        args.table.write_text(fs.render_table(results, meta))
    print(
        f"wrote {args.out} ({len(results)} arms, {len(bars)} bars, {len(instruments)} instruments)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
