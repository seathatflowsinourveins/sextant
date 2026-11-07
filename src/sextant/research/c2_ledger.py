"""C2 ledger hand-offs: reservation before the run, outcome after it.

Format `sextant.ledger.handoff/1`, lane `scenario`, issue 130, attempt `c2`. Every row is
Decimal-string/int/bool/None only: the ledger refused C1's first outcome hand-off for floats
(#102 comments 6712315034, 6712385409), so `c2` never emits one. The batch writer is C1's
(`/home/sextant/sextant-data/c1-scenario/lib/handoff.py`), copied here so the study code lives
in the branch (BRIEF-C2.md, last bullet).

Subcommands:
  reserve --protocol-sha <sha> --code-sha <sha>   writes ~/sextant-data/scenario-130/c2/reserve
  outcome --protocol-sha <sha> --code-sha <sha>   writes ~/sextant-data/scenario-130/c2/outcome
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from sextant.exits.policy import ExitParams

ROOT = Path.home() / "sextant-data" / "c2-scenario"
HANDOFF = Path.home() / "sextant-data" / "scenario-130" / "c2"
STUDY = "https://github.com/seathatflowsinourveins/sextant/issues/130"
EXIT_COMPONENT = "09e579fa27b4af5ae458e5b6e899196fd681d430"  # exit PR 2 head (C1 row)
BASE = "fc50653ee62006385f6f92765f4151a38b64af40"  # c1-integration head / c2 base

ARMS = (
    "exit-engine-p2",
    "trail-0.5",
    "trail-2.5",
    "trail-0.25",
    "trail-0.1",
    "atr-trail-3",
    "hold-1555",
    "hold-flat",
)
CASES = ("a", "b", "c")
LETTER = {"a": "A", "b": "B", "c": "C"}

FACTS: dict[str, dict[str, Any]] = {
    "a": {
        "symbol": "PARA",
        "cusip": "06682J803",
        "entry_session": "2026-11-03",
        "sessions": ["2026-11-03", "2026-11-04"],
        "marks": {
            "prior_close_adjusted": "1.68",
            "open": "3.73",
            "high": "8.93",
            "low": "2.69",
            "close": "2.7101",
            "next_close": "0.319",
            "next_pct": "-0.882",
            "volume": "101700000",
        },
        "note": (
            "overnight extension: witness entry 2026-11-03 held through the 11-04 RTH "
            "collapse for the hold control"
        ),
    },
    "b": {
        "symbol": "PARA",
        "cusip": "06682J803",
        "entry_session": "2026-10-27",
        "sessions": ["2026-10-27"],
        "marks": {
            "prior_close_adjusted": "4.139",
            "open": "4.46",
            "high": "6.43",
            "low": "3.2101",
            "close": "4.29",
            "split": "1:10 reverse effective 2026-10-27",
        },
        "note": (
            "conditional case runs: C1 #130 named the -32.7% exit a modeled fill artifact "
            "(quote bid at a wide LULD quote, trades 4.01-4.40), not a corporate-action "
            "adjustment bug in the lookback ATR"
        ),
    },
    "c": {
        "symbol": "SPCX",
        "cusip": None,
        "entry_session": "2026-10-21",
        "sessions": ["2026-10-21", "2026-10-22"],
        "marks": {
            "prior_close": "147.95",
            "open": "160.555",
            "high": "166.18",
            "low": "146.165",
            "close": "159.27",
            "next_close": "144.745",
            "next_pct": "-0.0912",
            "event": "Q3 8-K after 2026-10-20 close",
        },
        "note": "large-cap contrast for the small fixed trails (ADDENDUM-C2-1)",
    },
}

LABELS = {
    "cohort": "hindsight_selected",
    "entry": "NOT_RUN (entry_parameters_unavailable)",
    "merit": False,
    "n": 3,
    "ranking_66": "NOT_RUN",
    "re_entry": "NOT_RUN (R1-R6 incomplete)",
    "survivor_only": True,
    "tier": "MODELED",
    "x5": "PENDING",
}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_batch(
    directory: Path,
    kind: str,
    rows: list[dict],
    *,
    lane: str,
    issue: int,
    indent: int | None = None,
) -> dict[str, Any]:
    """C1's writer (`c1-scenario/lib/handoff.py`): rows.jsonl + manifest.json, no overwrite."""
    text = "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n"
    encoded = text.encode()
    rows_sha = hashlib.sha256(encoded).hexdigest()
    manifest = {
        "format": "sextant.ledger.handoff/1",
        "lane": lane,
        "issue": issue,
        "kind": kind,
        "count": len(rows),
        "rows_sha256": rows_sha,
        "tier": "MODELED",
    }
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "rows.jsonl").write_bytes(encoded)
    body = json.dumps(manifest, indent=indent, sort_keys=True) + "\n"
    (directory / "manifest.json").write_text(body)
    return {
        "directory": str(directory),
        "count": len(rows),
        "rows_sha256": rows_sha,
        "manifest_sha256": hashlib.sha256(body.encode()).hexdigest(),
    }


def engine_params() -> dict[str, Any]:
    starts = ExitParams.starts()
    out: dict[str, Any] = {
        "source": "src/sextant/exits/policy.py:106",
        "x5_label": "PENDING",
    }
    for field in fields(starts):
        value = getattr(starts, field.name)
        if value is None:
            continue
        out[field.name] = str(value)
    return out


def arm_params(arm: str) -> dict[str, Any]:
    if arm == "exit-engine-p2":
        return engine_params()
    if arm.startswith("trail-"):
        pct = arm.split("-", 1)[1]
        return {
            "trail_percent": pct,
            "source": "docs.alpaca.markets/docs/orders-at-alpaca, read 2026-11-07 (trail_percent)",
            "outside_rth": "owner_b_sim.py:195 emulated BID_ASK trailing stop-limit",
        }
    if arm == "atr-trail-3":
        return {
            "atr_period": 22,
            "atr_bar_minutes": 5,
            "atr_multiple": "3",
            "source": (
                "docs/adr/0005-exit-engine.md:38 HH22-3xATR22; StockCharts Chandelier "
                "read 2026-11-01"
            ),
        }
    if arm == "hold-1555":
        return {"exit_time": "15:55 America/New_York", "source": "BRIEF-C2.md arm 5"}
    return {"position": "none", "source": "BRIEF-C2.md arm 6"}


def arm_factor_mask(arm: str) -> list[str]:
    if arm == "exit-engine-p2":
        return ["x2-trigger", "x3-arming", "x4-breach", "x5-bid-sell"]
    if arm.startswith("trail-"):
        return ["trail-high-water-mark", "rth-trade-trigger"]
    if arm == "atr-trail-3":
        return ["atr22-5m", "chandelier-k3"]
    if arm == "hold-1555":
        return ["time-exit"]
    return ["no-position"]


def arm_strategy(arm: str) -> str:
    if arm == "exit-engine-p2":
        return "exit-engine-p2"
    if arm.startswith("trail-"):
        return "fixed-trail"
    if arm == "atr-trail-3":
        return "atr-trail"
    return "hold" if arm == "hold-1555" else "hold-flat"


def arm_run_id(case: str, arm: str) -> str:
    return str(ROOT / "run" / "arms" / f"case-{case}" / arm)


def block_set(protocol_sha: str) -> str:
    return "scenario-130:" + digest(
        {"protocol_sha256": protocol_sha, "cases": {c: FACTS[c]["sessions"] for c in CASES}}
    )


def reserve(protocol_sha: str, code_sha: str) -> dict[str, Any]:
    block = block_set(protocol_sha)
    rows: list[dict[str, Any]] = []
    for case in CASES:
        for arm in ARMS:
            params = arm_params(arm)
            sandbox = {
                "case": LETTER[case],
                "symbol": FACTS[case]["symbol"],
                "cusip": FACTS[case]["cusip"],
                "entry_session": FACTS[case]["entry_session"],
                "sessions": FACTS[case]["sessions"],
                "marks": FACTS[case]["marks"],
                "note": FACTS[case]["note"],
                "witness_entry": "first SIP trade print at/after 09:30:00 ET on entry_session",
                "labels": LABELS,
                "costs_bps_per_side": ["3", "6"],
                "protocol_sha256": protocol_sha,
                "purpose": "MEASUREMENT_ONLY",
                "c2_commit": code_sha,
                "arm_semantics": arm_params(arm),
                "fill_model": (
                    "nautilus BacktestEngine 2.0.0rc8 SIMULATED, market orders, one share"
                ),
            }
            implementation = EXIT_COMPONENT if arm == "exit-engine-p2" else code_sha
            rows.append(
                {
                    "strategy": arm_strategy(arm),
                    "params": params,
                    "seed": 7,
                    "config": {
                        "arm_id": f"scenario-130:c2:{arm}:{case}",
                        "arm_run_id": arm_run_id(case, arm),
                        "block_set_id": block,
                        "condition_returns": {},
                        "evidence_weights": {},
                        "evidence_weights_hash": digest({}),
                        "factor_mask": arm_factor_mask(arm),
                        "funding_divergent_session_count": None,
                        "funding_unverified_session_count": None,
                        "implementation_sha": implementation,
                        "parameter_state": (
                            "RECORDED_START" if arm == "exit-engine-p2" else "FROZEN"
                        ),
                        "params_hash": digest(params),
                        "protocol_sha256": protocol_sha,
                        "purpose": "MEASUREMENT_ONLY",
                        "sandbox_config": sandbox,
                        "sandbox_config_hash": digest(sandbox),
                        "tier": "MODELED",
                    },
                }
            )
    return write_batch(
        HANDOFF / "reserve", "reserve", rows, lane="scenario", issue=130, indent=None
    )


def outcome(protocol_sha: str, code_sha: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in CASES:
        for arm in ARMS:
            path = ROOT / "run" / "arms" / f"case-{case}" / f"{arm}.json"
            facts = FACTS[case]
            if not path.exists():
                rows.append(
                    {
                        "arm_run_id": arm_run_id(case, arm),
                        "state": "PRUNED",
                        "error": f"no run output at {path}",
                    }
                )
                continue
            run = json.loads(path.read_text())
            net1x, net2x = run.get("net_1x"), run.get("net_2x")
            if net1x is None or net2x is None:
                rows.append(
                    {
                        "arm_run_id": arm_run_id(case, arm),
                        "state": "PRUNED",
                        "error": "no exit fill; arm left open at the tape end",
                    }
                )
                continue
            entry = run.get("entry_px")
            result: dict[str, Any] = {
                "arm": arm,
                "case": case,
                "cohort": (
                    "3 hindsight-selected extreme-mover cases (PARA 2026-11-03, PARA "
                    "2026-10-27 split day, SPCX 2026-10-21); one session per arm; "
                    "survivor_only; B runs because C1 named a modeled fill artifact, not an ATR bug"
                ),
                "component_commit": EXIT_COMPONENT if arm == "exit-engine-p2" else code_sha,
                "costs_bps_per_side": [3, 6],
                "entry_px": entry,
                "entry_ts_ns": run.get("entry_ts_ns"),
                "execution_model": "nautilus BacktestEngine 2.0.0rc8, SIMULATED",
                "exit_px": run.get("exit_px"),
                "exit_reason": run.get("exit_reason"),
                "exit_ts_ns": run.get("exit_ts_ns"),
                "facts": {
                    **facts["marks"],
                    "symbol": facts["symbol"],
                    "entry_session": facts["entry_session"],
                    "tier": "MODELED",
                },
                "held_seconds": run.get("held_seconds"),
                "inputs": {
                    "catalog": "/home/sextant/sextant-data/c1-scenario/catalog",
                    "protocol_sha256": protocol_sha,
                    "data_sha256": run.get("data_sha256"),
                    "code_sha256": code_sha,
                },
                "kind": "simulated-fill",
                "kind_detail": {
                    "exit-engine-p2": (
                        "production ExitEngine (09e579f) on one-share witness entry"
                    ),
                    "trail-0.5": (
                        "fixed trailing stop 0.5% (Alpaca trail_percent RTH; market sell on breach)"
                    ),
                    "trail-2.5": "fixed trailing stop 2.5% (B's current row)",
                    "trail-0.25": "fixed trailing stop 0.25% (test arm, not an adopted value)",
                    "trail-0.1": "fixed trailing stop 0.1% (test arm, not an adopted value)",
                    "atr-trail-3": "ATR22 on 5-minute RTH bars x3 chandelier (k=3, ADR-0005:38)",
                    "hold-1555": "hold to 15:55 ET of the final session",
                    "hold-flat": "no position; flat control",
                }[arm],
                "mae": run.get("mae"),
                "mfe": run.get("mfe"),
                "n": 1,
                "net_1x": net1x,
                "net_2x": net2x,
                "selected": False,
                "spread_at_entry": run.get("spread_at_entry"),
                "spread_at_entry_bps": run.get("spread_at_entry_bps"),
                "study": STUDY,
                "tier": "MODELED",
                "trigger_px": run.get("trigger_px"),
                "trigger_ts_ns": run.get("trigger_ts_ns"),
                "version": "c2/1",
            }
            rows.append(
                {
                    "arm_run_id": arm_run_id(case, arm),
                    "condition_returns": {"1x": [net1x], "2x": [net2x]},
                    "daily_net_returns": [net1x],
                    "days": [facts["entry_session"]],
                    "result": result,
                    "state": "COMPLETE",
                }
            )
    return write_batch(
        HANDOFF / "outcome", "outcome", rows, lane="scenario", issue=130, indent=None
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("reserve", "outcome"))
    parser.add_argument("--protocol-sha", required=True)
    parser.add_argument("--code-sha", required=True)
    args = parser.parse_args()
    if len(args.protocol_sha) != 64 or len(args.code_sha) != 40:
        raise SystemExit("protocol sha256 (64 hex) and code sha (40 hex) required")
    if args.kind == "reserve":
        print(json.dumps(reserve(args.protocol_sha, args.code_sha), indent=2))
    else:
        print(json.dumps(outcome(args.protocol_sha, args.code_sha), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
