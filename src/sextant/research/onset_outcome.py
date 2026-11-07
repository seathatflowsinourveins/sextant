"""#130 Part 1 outcome: close every frozen reserve row from the study's own files.

This is the builder that lived out of the repo at `~/sextant-data/onset-130/part1/
build_outcome.py` (`56f43fa3…`, 203 lines) before the move. It reads the frozen cohort's
hashes, the study summaries and the reserve rows; it writes one `sextant.ledger.handoff/1`
outcome batch and nothing else — no pull, price or order path is reachable.

`runner_sha` records the code that built the batch. It defaults to the running checkout's
HEAD prefix and can be given explicitly: the ledgered rows record `387521f14bd4`, which the
old builder hardcoded, so a byte-for-byte rebuild passes that value.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from sextant.research.onset_common import git, read_jsonl, sha256_file
from sextant.validation.handoff import write_batch

ISSUE = 130
LANE = "onset"
STUDY = "https://github.com/seathatflowsinourveins/sextant/issues/130"
FALLBACK_PULL_SHA = "5770e0bbead3"
ARM = "stocks-in-play"
FROZEN_FILES = ("events.jsonl", "controls.jsonl", "manifest.json", "rule.md", "windows.json")
STUDY_FILES = (
    "pull-summary.json",
    "pull-receipts.jsonl",
    "thresholds-summary.json",
    "sip.json",
    "fallback.json",
    "fallback-receipts.jsonl",
)
NOT_RUN = {
    "page-hinkley": (
        "NOT_RUN: River 0.26.1 PageHinkley has five parameters and none is admitted; "
        "constructor defaults grant no authority"
    ),
    "bocpd": (
        "NOT_RUN: hazard, observation model, boundary condition and alarm rule are unavailable"
    ),
    "e0-house-incumbent": (
        "NOT_RUN: the K2/K3 registry requires twelve caller values and none is published"
    ),
    "ranking-66": (
        "NOT_RUN: the move x dvol_ratio score has no admitted gate or publication policy"
    ),
    "adwin": "NOT_RUN: frozen follow-on; no admitted implementation",
    "lee-mykland": "NOT_RUN: frozen follow-on; no admitted implementation",
    "cusum": "NOT_RUN: frozen follow-on; no admitted implementation",
    "ofi": "NOT_RUN: frozen follow-on; no admitted implementation",
    "vpin": "NOT_RUN: frozen follow-on; no admitted implementation",
}
RUNNER_SHA = re.compile(r"[0-9a-f]{12}")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float):
        return format(Decimal(str(value)).quantize(Decimal("0.000001")), "f")
    return str(value)


def _inputs(freeze: Path, study: Path) -> dict[str, str]:
    """Every input is the SHA-256 of the file at the given root; the names are the record."""
    paths = [freeze / name for name in FROZEN_FILES] + [study / name for name in STUDY_FILES]
    return {path.name: sha256_file(path) for path in paths}


def _screen_result(
    sip: dict[str, Any], thresholds: dict[str, Any], inputs: dict[str, str], runner_sha: str
) -> dict[str, Any]:
    return {
        "arm": ARM,
        "cohort": (
            "814 price-observed selected gainers; 806 primary controls "
            "(2,418 frozen rows include two backups per event), with 14 zero-bar "
            "primaries replaced by their frozen backup_1"
        ),
        "inputs": inputs,
        "kind": "screen",
        "n": sip["evaluated_role"].get("event", 0),
        "selected": False,
        "study": STUDY,
        "tier": "MODELED",
        "version": "stocks-in-play/1",
        "atr_method": "mean of the 14 prior true ranges (Wilder seed, no extra warm-up)",
        "adv_definition": "mean of 14 prior session volumes over all SIP minutes 04:00-20:00 ET",
        "opening_definition": (
            "09:30-09:35 ET composite over every SIP 1-minute bar printed in the window; "
            "no-print minutes are no trades, never filled"
        ),
        "censoring_rule": (
            "a window with no printed bar, or a prior day with no printed opening window, "
            "is censored and counted; nothing is imputed"
        ),
        "screen_scope": (
            "frozen 814 events and 806 selected controls (primaries, or backup_1 for "
            "14 zero-bar primaries); not the market cross-section"
        ),
        "fallback_used": sip["fallback_used"],
        "fallback_note": (
            "14 primaries had no bars; each was replaced by its frozen backup_1. "
            "No backup_2 was needed and no control was re-ranked."
        ),
        "returns_note": (
            "the screen has no order model; zero daily returns are ledger bookkeeping, not P&L"
        ),
        "runner_sha": runner_sha,
        "fallback_pull_sha": FALLBACK_PULL_SHA,
        "events_evaluated": sip["evaluated_role"].get("event", 0),
        "events_censored": sip["censored_role"].get("event", 0),
        "controls_evaluated": sip["evaluated_role"].get("control", 0),
        "controls_censored": sip["censored_role"].get("control", 0),
        "controls_replaced": sip["fallback_used"],
        "censored": sip["censored"],
        "censored_by_role_reason": sip["censored_by_role_reason"],
        "censored_total": sip["censored_total"],
        "passers": sip["passers"],
        "top30": sip["top30"],
        "top100": sip["top100"],
        "recall": {
            label: {
                session: {
                    "events": counts["events"],
                    "top30": counts["top30"],
                    "top100": counts["top100"],
                    "recall30": _text(counts["recall30"]),
                    "recall100": _text(counts["recall100"]),
                }
                for session, counts in sessions.items()
            }
            for label, sessions in sip["recall"].items()
        },
        "time_to_flag": {
            label: {
                session: {
                    "n": stats["n"],
                    "median": _text(stats["median"]),
                    "min": _text(stats["min"]),
                    "max": _text(stats["max"]),
                }
                for session, stats in sessions.items()
            }
            for label, sessions in sip["time_to_flag"].items()
        },
        "control_days": sip["control_days"],
        "control_flags": sip["control_flags"],
        "control_top30": sip["control_top30"],
        "control_top100": sip["control_top100"],
        "false_flags_per_day": _text(sip["false_flags_per_day"]),
        "threshold_anchors": {
            "events": thresholds["events"],
            "measured": thresholds["measured"],
            "five": thresholds["five"],
            "ten": thresholds["ten"],
            "five_sessions": thresholds["five_sessions"],
            "ten_sessions": thresholds["ten_sessions"],
        },
    }


def _pruned_result(slug: str, inputs: dict[str, str]) -> dict[str, Any]:
    return {
        "arm": slug,
        "cohort": "814 price-observed selected gainers; 806 primary controls",
        "inputs": inputs,
        "kind": "mechanism",
        "n": 0,
        "selected": False,
        "study": STUDY,
        "tier": "MODELED",
        "version": "part1",
    }


def resolve_runner_sha(override: str | None) -> tuple[str, str]:
    """Return the recorded SHA and which source supplied it: the caller or the checkout's HEAD."""
    if override is not None:
        if RUNNER_SHA.fullmatch(override) is None:
            raise ValueError("runner_sha must be 12 lowercase hex characters")
        return override, "override"
    root = Path(__file__).resolve().parents[3]
    head = git(root, "rev-parse", "HEAD").decode().strip()
    return head[:12], f"git HEAD ({root})"


def build_outcome(
    freeze: Path,
    study: Path,
    reserve: Path,
    output: Path,
    *,
    runner_sha: str | None = None,
) -> dict[str, Any]:
    """Build the outcome batch; return its receipts, size and the runner SHA's source."""
    recorded, source = resolve_runner_sha(runner_sha)
    inputs = _inputs(freeze, study)
    sip = json.loads((study / "sip.json").read_text())
    thresholds = json.loads((study / "thresholds-summary.json").read_text())
    days = sorted({row["day"] for row in sip["rows"] if row["role"] == "event"})
    result = _screen_result(sip, thresholds, inputs, recorded)
    rows: list[dict[str, Any]] = []
    for item in read_jsonl(reserve / "rows.jsonl"):
        config = item["config"]
        arm_id = config["arm_id"]
        base = {"arm_run_id": config["arm_run_id"]}
        if arm_id == f"onset-{ISSUE}:{ARM}":
            rows.append(
                {
                    **base,
                    "state": "COMPLETE",
                    "error": "",
                    "days": days,
                    "daily_net_returns": [0.0] * len(days),
                    "condition_returns": {"1x": [0.0] * len(days), "2x": [0.0] * len(days)},
                    "result": result,
                }
            )
            continue
        slug = arm_id.split(":", 1)[1]
        rows.append(
            {
                **base,
                "state": "PRUNED",
                "error": NOT_RUN[slug],
                "result": _pruned_result(slug, inputs),
            }
        )
    receipt = write_batch(output, "outcome", rows, lane=LANE, issue=ISSUE, indent=2)
    return {
        "outcome": str(output),
        "rows": len(rows),
        "days": len(days),
        "runner_sha": recorded,
        "runner_sha_source": source,
        **receipt,
    }
