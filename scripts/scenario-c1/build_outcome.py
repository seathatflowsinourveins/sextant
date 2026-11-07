"""Builds the C1 outcome batch for #102 from local run receipts; no network, no broker."""

from __future__ import annotations

import json
from datetime import date, datetime, time as daytime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader.persistence import ParquetDataCatalog

import sys

sys.path.insert(0, str(Path(__file__).parent / "lib"))
from handoff import write_batch  # noqa: E402

from sextant.data.alpaca_history import NY  # noqa: E402

ROOT = Path.home() / "sextant-data" / "c1-scenario"
STUDY = "https://github.com/seathatflowsinourveins/sextant/issues/130"
COHORT = (
    "3 hindsight-selected extreme-mover cases (PARA 2026-11-03, PARA 2026-10-27 split day, "
    "SPCX 2026-10-21), one session per arm; survivor_only"
)


def keys(arm: str, version: str) -> dict[str, Any]:
    """#67's result row: the six keys the ledger needs on every COMPLETE arm."""
    return {
        "arm": arm,
        "cohort": COHORT,
        "n": 1,
        "selected": False,
        "study": STUDY,
        "version": version,
    }
SCEN = Path.home() / "sextant-data" / "scenario-130" / "c1"
CATALOG = ROOT / "catalog"
NS = 1_000_000_000

CASES = {
    "a": {"symbol": "PARA", "day": date(2026, 11, 3), "prior": date(2026, 11, 2), "split": 1},
    "b": {"symbol": "PARA", "day": date(2026, 10, 27), "prior": date(2026, 10, 26), "split": 10},
    "c": {"symbol": "SPCX", "day": date(2026, 10, 21), "prior": date(2026, 10, 20), "split": 1},
}


def rth_bars(catalog, symbol: str, day: date):
    bars = catalog.query_bars(identifiers=[f"{symbol}.ALPACA-1-MINUTE-LAST-EXTERNAL"])
    out = []
    for b in bars:
        local = datetime.fromtimestamp(b.ts_event // NS, NY)
        if local.date() == day and daytime(9, 31) <= local.time() <= daytime(16, 0):
            out.append(b)
    return out


def closes(catalog, symbol: str, day: date) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    bars = rth_bars(catalog, symbol, day)
    return (
        bars[0].open.as_decimal(),
        bars[-1].close.as_decimal(),
        max(b.high.as_decimal() for b in bars),
        min(b.low.as_decimal() for b in bars),
    )


def net(entry: Decimal, exit_: Decimal, bps: int) -> float:
    c = Decimal(bps) / Decimal(10_000)
    return float((exit_ / entry) * (1 - c) - (1 + c))


def main() -> int:
    catalog = ParquetDataCatalog(str(CATALOG.resolve()))
    reserve = [
        json.loads(line) for line in (SCEN / "reserve" / "rows.jsonl").read_text().splitlines()
    ]
    marks = json.loads((ROOT / "run" / "marks.json").read_text())
    rows: list[dict[str, Any]] = []

    for case, info in CASES.items():
        symbol, day = info["symbol"], info["day"]
        open_, close, high, low = closes(catalog, symbol, day)
        prior_close = closes(catalog, symbol, info["prior"])[1] * info["split"]
        detect = json.loads((ROOT / "run" / case / "detect.json").read_text())
        strict = detect["strict"]
        exit_run = json.loads((ROOT / "run" / case / "exit.json").read_text())
        events = {e["event"]: e for e in exit_run.get("events", [])}
        entry_px = Decimal(events["entry_fill"]["price"])
        exit_px = Decimal(events["sell_fill"]["price"])
        entry_ns = int(events["entry_fill"]["ts"])
        exit_ns = int(events["sell_fill"]["ts"])
        held_s = (exit_ns - entry_ns) / NS
        mfe = (Decimal(marks[case]["held_high"]) / entry_px) - 1
        mae = (Decimal(marks[case]["held_low"]) / entry_px) - 1
        facts = {
            "symbol": symbol,
            "entry_session": day.isoformat(),
            "prior_close_adjusted": str(prior_close),
            "open": str(open_),
            "high": str(high),
            "low": str(low),
            "close": str(close),
            "gap": str(open_ / prior_close - 1),
            "tier": "MODELED",
        }
        by_arm = {
            r["config"]["arm_id"].split(":")[2]: r
            for r in reserve
            if r["config"]["arm_id"].endswith(f":{case}")
        }
        base_result = {
            "case": case,
            "tier": "MODELED",
            "inputs": {
                "catalog": str(CATALOG),
                "protocol_sha256": "904747d4b928cae4af890597ef2c403f8c90fb86dfbe189a1b36a09c104e2110",
            },
            "facts": facts,
        }

        det = {
            **base_result,
            "kind": "detection-screen",
            "screen_reason": strict["reason"],
            "rvol": strict["rvol"],
            "passes_local_filters": strict["passes"],
            "flag": False,
            "component_commit": "fc50653ee62006385f6f92765f4151a38b64af40",
            "note": "ATR unavailable (#129 unbound); opening coverage as measured",
        }
        rows.append(
            {
                "arm_run_id": by_arm["detection"]["config"]["arm_run_id"],
                "state": "PRUNED",
                "error": f"NOT_RUN: {strict['reason']}; the detector produced no flag on this case",
                "result": det,
            }
        )

        entry_row = by_arm["entry"]
        rows.append(
            {
                "arm_run_id": entry_row["config"]["arm_run_id"],
                "state": "PRUNED",
                "error": "NOT_RUN: entry parameters unavailable (27/27 null, calibration UNAVAILABLE); fixture values are synthetic-only and not admissible",
                "result": {
                    **base_result,
                    "kind": "entry-arm",
                    "parameters_state": "UNAVAILABLE",
                    "component_commit": "61174b829bd42da60ab719bae9c43bead807f0e5",
                },
            }
        )

        def complete(
            arm: str,
            version: str,
            entry: Decimal,
            exit_: Decimal,
            entry_ts: int,
            exit_ts: int,
            extra: dict,
        ) -> dict:
            n3 = net(entry, exit_, 3)
            n6 = net(entry, exit_, 6)
            return {
                "arm_run_id": by_arm[arm]["config"]["arm_run_id"],
                "state": "COMPLETE",
                "days": [day.isoformat()],
                "daily_net_returns": [n3],
                "condition_returns": {"1x": [n3], "2x": [n6]},
                "result": {
                    **base_result,
                    **keys(arm.replace("control-", ""), version),
                    "kind": "simulated-fill",
                    "entry_px": str(entry),
                    "exit_px": str(exit_),
                    "entry_ts_ns": entry_ts,
                    "exit_ts_ns": exit_ts,
                    "held_seconds": str(Decimal(repr((exit_ts - entry_ts) / NS))),
                    "net_1x": str(Decimal(repr(n3))),
                    "net_2x": str(Decimal(repr(n6))),
                    "costs_bps_per_side": [3, 6],
                    "execution_model": "nautilus BacktestEngine 2.0.0rc8, SIMULATED",
                    **extra,
                },
            }

        rows.append(
            complete(
                "exit",
                "exit-engine-p2/1",
                entry_px,
                exit_px,
                entry_ns,
                exit_ns,
                {
                    "kind_detail": "production ExitEngine (09e579f) on one-share witness entry",
                    "mfe": str(mfe),
                    "mae": str(mae),
                    "post_exit_30m_bid": marks[case]["post_exit_30m_bid"],
                    "pages": exit_run.get("pages", []),
                    "component_commit": "09e579fa27b4af5ae458e5b6e899196fd681d430",
                },
            )
        )

        flat = by_arm["control-hold-flat"]
        rows.append(
            {
                "arm_run_id": flat["config"]["arm_run_id"],
                "state": "COMPLETE",
                "days": [day.isoformat()],
                "daily_net_returns": [0.0],
                "condition_returns": {"1x": [0.0], "2x": [0.0]},
                "result": {
                    **base_result,
                    **keys("hold-flat", "hold-flat/1"),
                    "kind": "no-position",
                    "position": "none",
                    "net_1x": "0.0",
                    "net_2x": "0.0",
                    "costs_bps_per_side": [3, 6],
                    "kind_detail": "control per protocol section 3: no position, 0 return",
                    "component_commit": "fc50653ee62006385f6f92765f4151a38b64af40",
                },
            }
        )

        for arm, mode in (("control-hold-1555", "hold1555"),):
            if case in ("a", "b"):
                run = json.loads((ROOT / "run" / case / f"{mode}.json").read_text())
                c_entry = Decimal(run["entry_px"])
                c_exit = Decimal(run["exit_px"])
                c_entry_ts, c_exit_ts = int(run["entry_ts"]), int(run["exit_ts"])
                source = "simulated market sale in BacktestEngine"
            else:
                c_entry = entry_px
                c_exit = Decimal(
                    marks[case]["holdflat_bid" if mode == "holdflat" else "hold1555_bid"]
                )
                # Control buys at the witness entry time and sells at its documented exit time.
                c_entry_ts = marks[case]["entry_ns"]
                c_exit_ts = marks[case]["holdflat_ns" if mode == "holdflat" else "hold1555_ns"]
                source = "bid mark at the documented exit time"
            rows.append(
                complete(
                    arm,
                    "hold-to-1555/1",
                    c_entry,
                    c_exit,
                    c_entry_ts,
                    c_exit_ts,
                    {
                        "kind_detail": source,
                        "component_commit": "fc50653ee62006385f6f92765f4151a38b64af40",
                    },
                )
            )

        rows.append(
            {
                "arm_run_id": by_arm["harness-stack"]["config"]["arm_run_id"],
                "state": "PRUNED",
                "error": "NOT_RUN: #111 recorded tape needs #41 inputs and a ScannerFacts snapshot; the C1 catalog needs a new adapter, not authorized in this study",
                "result": {
                    **base_result,
                    "kind": "sandbox-full-stack",
                    "component_commit": "2bb696275ef2a057b2203abeb40f09b3b70de391",
                },
            }
        )

    assert len(rows) == 18 and len({r["arm_run_id"] for r in rows}) == 18
    out = SCEN / "outcome"
    if out.exists():
        if "--restage" not in sys.argv:
            raise SystemExit(f"{out} already exists; refusing to overwrite without --restage")
        for stale in out.iterdir():
            stale.unlink()
        out.rmdir()
    if "--dry" in sys.argv:
        for row in rows:
            print(row["arm_run_id"].rsplit("/", 2)[-2:], row["state"], row.get("error", ""))
            if row["state"] == "COMPLETE":
                print("   net", row["condition_returns"])
        return 0
    receipts = write_batch(out, "outcome", rows, lane="scenario", issue=130)
    print(json.dumps({"dir": str(out), "count": len(rows), **receipts}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
