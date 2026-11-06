"""#141: the pre-arm noise surface, a registered grid over ADR-0019's documented starts.

The grid is exactly trading ADR-0019's documented grids (northstar-trading@7c5f852a, amendment 1):
`prearm_buffer_fraction` {0.005, 0.01, 0.02} (:251), `prearm_range_multiple` {0.5, 1, 2} (:252) and
`gain_lock_giveback_fraction` {0, 0.1, 0.25} (:140). Every other row stays at `ExitParams.starts()`;
the chase is off (#98 rulings). The tape, entries, costs and controls are #98's
(sextant.research.exit_econ_98), unchanged.

Order, per #141 and the ledger inbox (#102): `register` writes the grid and prints its SHA-256,
posted on #141 before any run; `reserve` writes the inbox batch, one RUNNING attempt per cell;
`run` refuses unless HEAD is the reserved implementation commit with a clean tree. It reports the
whole surface and selects nothing (ADR-0018, ADR-0019).

On minute bars, R_w is not estimable (#98, B3): the run drops the range term, so the three
`prearm_range_multiple` values are expected identical. The run checks that, not assumes it.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import subprocess
from collections import defaultdict
from decimal import Decimal
from itertools import product
from pathlib import Path
from typing import Any

from sextant.exits.policy import ExitParams
from sextant.research import exit_econ_98 as x98
from sextant.research import exit_study_41 as x41

ISSUE = 141
LANE = "exit"
VERSION = "exit-grid-141/1"
INBOX = Path.home() / "sextant-data" / f"{LANE}-{ISSUE}"
T19 = "northstar-trading@7c5f852a2816bbaa5896241a93bab9de7cf7bb4f"
AXES: dict[str, tuple[Decimal, ...]] = {
    "prearm_buffer_fraction": (Decimal("0.005"), Decimal("0.01"), Decimal("0.02")),
    "prearm_range_multiple": (Decimal("0.5"), Decimal(1), Decimal(2)),
    "gain_lock_giveback_fraction": (Decimal(0), Decimal("0.1"), Decimal("0.25")),
}
AXIS_SOURCES = {
    "prearm_buffer_fraction": f"{T19}:docs/adr/0019-managed-exits-and-ranked-reentry.md:251",
    "prearm_range_multiple": f"{T19}:docs/adr/0019-managed-exits-and-ranked-reentry.md:252",
    "gain_lock_giveback_fraction": f"{T19}:docs/adr/0019-managed-exits-and-ranked-reentry.md:140",
}
STUDY = (
    "Sextant exit engine (#45) on #98's minute-bar proxy, a grid over ADR-0019's documented "
    f"starts ({T19}); inputs and controls as #67 and #98"
)


def snapshot_hash(value: Any) -> str:
    """sextant.validation.trials.snapshot_hash at #110 head 735bca38: canonical finite JSON."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def cell_id(values: dict[str, Decimal]) -> str:
    b, m, g = (values[k] for k in AXES)
    return f"b{b}-m{m}-g{g}"


def cells() -> list[tuple[str, ExitParams]]:
    """Every cell of the registered grid, in a fixed order."""
    base = ExitParams.starts()
    out = []
    for combo in product(*AXES.values()):
        values = dict(zip(AXES, combo, strict=True))
        out.append((cell_id(values), dataclasses.replace(base, **values)))
    return out


def _params(p: ExitParams) -> dict[str, str | None]:
    return {k: (None if v is None else str(v)) for k, v in dataclasses.asdict(p).items()}


SANDBOX = {
    "engine": "sextant.exits.engine:ExitEngine (#45), one NautilusTrader BacktestEngine per entry",
    "nautilus": "v2.0.0rc7 55c0e82053142bce3a5cba4de4221d3929c2d3bc",
    "tape": (
        "northstar-trading@8256c16c b_gain_protection.py:856-905 minute-bar proxy; bid/ask = "
        "low x (1 -/+ h) on the broker tick (:411-415); recorded-entry anchor :705-735"
    ),
    "execution_model": x98.MODEL,
    "costs_bps_per_side": ["3", "6"],
    "chase": "chase not estimable on minute bars (off; sells at the bid proxy)",
    "range_term": "R_w not estimable on minute bars (dropped)",
    "arming": "bar_1m (ADR-0019:98 default); its quote-run alternatives are sub-minute",
    "flat": "15:55 ET open, the study's own exit and costs",
}


def registration() -> dict[str, Any]:
    return {
        "issue": ISSUE,
        "version": VERSION,
        "axes": {k: [str(v) for v in vs] for k, vs in AXES.items()},
        "axis_sources": AXIS_SOURCES,
        "fixed": {k: v for k, v in _params(ExitParams.starts()).items() if k not in AXES},
        "cells": [{"cell": c, "params": _params(p)} for c, p in cells()],
        "inputs": x41.INPUTS,
        "cohort": "primary complete-horizon entries, 2026-10-26..28 (n = 1,025)",
        "sandbox": SANDBOX,
        "controls": ["hold_flat", f"{x98.C5}-study", f"{x98.C5}-tape"],
        "report": "every cell: mean/median/win/pnl at 3 and 6 bps, attribution by exit label",
        "selection": "none; no cell becomes a start or registry value (ADR-0018, ADR-0019)",
        "expected": "prearm_range_multiple cells identical while R_w is not estimable",
    }


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def reserve_rows(attempt_dir: Path, implementation_sha: str) -> list[dict[str, Any]]:
    block = f"exit-study-41:{snapshot_hash(x41.INPUTS)}"
    rows = []
    for cid, p in cells():
        params = _params(p)
        rows.append(
            {
                "strategy": "exit-engine-prearm-grid",
                "params": params,
                "seed": None,
                "config": {
                    "arm_id": f"exit-grid-141:{cid}",
                    "arm_run_id": f"{attempt_dir}#{cid}",
                    "implementation_sha": implementation_sha,
                    "factor_mask": ["x2-trigger", "x3-arming", "x4-breach", "x5-bid-sell"],
                    "sandbox_config": SANDBOX,
                    "sandbox_config_hash": snapshot_hash(SANDBOX),
                    "evidence_weights": {},
                    "evidence_weights_hash": snapshot_hash({}),
                    "params_hash": snapshot_hash(params),
                    "tier": "MODELED",
                    "block_set_id": block,
                    "funding_divergent_session_count": None,
                    "funding_unverified_session_count": None,
                    "condition_returns": {},
                },
            }
        )
    return rows


def write_batch(directory: Path, kind: str, rows: list[dict[str, Any]]) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=False)
    raw = "".join(json.dumps(r, sort_keys=True, allow_nan=False) + "\n" for r in rows).encode()
    (directory / "rows.jsonl").write_bytes(raw)
    manifest = {
        "format": "sextant.ledger.handoff/1",
        "lane": LANE,
        "issue": ISSUE,
        "kind": kind,
        "count": len(rows),
        "rows_sha256": hashlib.sha256(raw).hexdigest(),
        "tier": "MODELED",
    }
    data = json.dumps(manifest, sort_keys=True).encode() + b"\n"
    (directory / "manifest.json").write_bytes(data)
    return {
        "rows_sha256": manifest["rows_sha256"],
        "manifest_sha256": hashlib.sha256(data).hexdigest(),
    }


def _day_means(per_entry: list[dict[str, Any]], cost: str) -> tuple[list[str], list[float]]:
    by_day: dict[str, list[Decimal]] = defaultdict(list)
    for row in per_entry:
        by_day[row["day"]].append(Decimal(row[cost]["managed"]))
    days = sorted(by_day)
    # The ledger's daily_net_returns are float64 (TrialLog schema); the values are Decimal means.
    return days, [float(sum(by_day[d], Decimal(0)) / len(by_day[d])) for d in days]


def run(inputs: Path, attempt_dir: Path, out: Path) -> dict[str, Any]:
    reserved = [
        json.loads(x) for x in (attempt_dir / "reserve" / "rows.jsonl").read_text().splitlines()
    ]
    sha = _git("rev-parse", "HEAD").strip()
    if _git("status", "--porcelain", "--untracked-files=no").strip():
        raise RuntimeError("run only from a clean tree at the reserved implementation commit")
    if {r["config"]["implementation_sha"] for r in reserved} != {sha}:
        raise RuntimeError("HEAD is not the reserved implementation commit")
    if [r["config"]["arm_run_id"] for r in reserved] != [
        f"{attempt_dir / 'reserve'}#{c}" for c, _ in cells()
    ]:
        raise RuntimeError("the reserved attempts differ from the registered grid")
    ctx = x98.prepare(inputs, out / "catalog")
    surface: dict[str, Any] = {}
    outcome: list[dict[str, Any]] = []
    controls: dict[str, Any] | None = None
    for cid, params in cells():
        result = x98.evaluate(ctx, params, range_estimable=False, arm=cid)
        if controls is None:
            controls = result["controls"]
        surface[cid] = {"params": _params(params), **result["arm"]}
        days, daily = _day_means(result["per_entry"], "3")
        _same, stress = _day_means(result["per_entry"], "6")
        arm = result["arm"]
        outcome.append(
            {
                "arm_run_id": f"{attempt_dir / 'reserve'}#{cid}",
                "state": "COMPLETE",
                "days": days,
                "daily_net_returns": daily,
                "condition_returns": {"1x": daily, "2x": stress},
                "result": {
                    "arm": cid,
                    "cohort": "primary complete-horizon entries, 2026-10-26..28",
                    "inputs": ctx["hashes"],
                    "kind": "variant",
                    "n": arm["3"]["n"],
                    "selected": False,
                    "study": STUDY,
                    "tier": "MODELED",
                    "version": VERSION,
                    "execution_model": x98.MODEL,
                    "params_hash": snapshot_hash(_params(params)),
                    **{f"{k}_{c}": arm[c][k] for c in ("3", "6") for k in x98.METRICS},
                    "attribution": arm["attribution"],
                },
            }
        )
    report = {
        "issue": ISSUE,
        "version": VERSION,
        "tier": "MODELED",
        "execution_model": x98.MODEL,
        "implementation": sha,
        "registration_sha256": hashlib.sha256(
            (attempt_dir / "registration.json").read_bytes()
        ).hexdigest(),
        "inputs": ctx["hashes"],
        "cohort": ctx["cohort"],
        "controls": controls,
        "surface": surface,
        "selected": None,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    receipt = write_batch(attempt_dir / "outcome", "outcome", outcome)
    print(json.dumps({"outcome": str(attempt_dir / "outcome"), **receipt}))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    reg = sub.add_parser("register")
    reg.add_argument("--attempt", required=True)
    res = sub.add_parser("reserve")
    res.add_argument("--attempt", required=True)
    go = sub.add_parser("run")
    go.add_argument("--attempt", required=True)
    go.add_argument("--inputs", type=Path, default=x41.DEFAULT_INPUTS)
    go.add_argument("--out", type=Path, default=Path("reports/exit-grid-141"))
    args = parser.parse_args()
    attempt = INBOX / args.attempt
    if args.cmd == "register":
        attempt.mkdir(parents=True, exist_ok=False)
        data = (json.dumps(registration(), indent=2, sort_keys=True) + "\n").encode()
        (attempt / "registration.json").write_bytes(data)
        print(
            json.dumps(
                {
                    "registration": str(attempt / "registration.json"),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        )
    elif args.cmd == "reserve":
        sha = _git("rev-parse", "HEAD").strip()
        receipt = write_batch(
            attempt / "reserve", "reserve", reserve_rows(attempt / "reserve", sha)
        )
        print(
            json.dumps({"reserve": str(attempt / "reserve"), "implementation_sha": sha, **receipt})
        )
    else:
        run(args.inputs, attempt, args.out)


if __name__ == "__main__":
    main()
