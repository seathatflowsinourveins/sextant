"""Reconcile ADR-0027's selected seed, without inventing PIT stocks or onset labels.

Audit adapted from docs/research/2026-11-06-extreme-gainer-package.md; CSV/ZIP/hash
I/O follows Python 3.13's documented APIs. Immutable publication follows
northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:
src/northstar_trading/data/alpaca_history.py:publish_once.
This is a metadata audit, not a backtest, TrialLog writer or predictive cohort.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import tempfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any
from zipfile import ZipFile

SEED_SHA256 = "f581ca7f771bf20ef05e212ce88aaaacda7325c640500d63926b23a0516d0577"
RELEASE = "https://github.com/seathatflowsinourveins/sextant/releases/tag/seed-research-2026-10-09"
PACKAGE = "extreme-gainer-research-package/"
DATASETS = PACKAGE + "datasets/"
CALENDAR = PACKAGE + "harness/research/regime-gate-backtest/lane-A-supplement-spx.csv"
GAINERS = tuple(f"extreme-gainers-{year}.csv" for year in (2021, 2022, 2023, 2024, "2025-2026"))
LOSERS = "extreme-losers-2021-2026.csv"
OVERLAYS = (
    "forward-returns-2021-2026.csv",
    "alias-map.csv",
    "forward-returns-recovered-supplement.csv",
)
CORRECTIONS = "discrepancy-resolution.csv"
BLOCKERS = {
    "pit_membership": "Dated share-class master, actions, scope and rights receipts unavailable",
    "delisting_acceptance": "10-exit, independent sample and recycled-ticker receipts unavailable",
    "ordinary_controls": "All-stock PIT stock-days and a frozen control protocol unavailable",
    "pre_ignition_labels": "Causal onset receipts and a source-backed frozen protocol unavailable",
    "availability_clocks": "Historical receipt/publication/first-print clocks unavailable in seed",
    "scanner_archive": "October 27-November 6 archive unavailable in clean checkout",
    "trial_ledger": "Cumulative TrialLog/custody unavailable; no replacement ledger created",
}


def _json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _key(row: dict[str, str]) -> tuple[str, str]:
    day, symbol = row["Date"], row["Ticker"]
    if date.fromisoformat(day).isoformat() != day or not symbol.strip():
        raise ValueError("Invalid seed event identity")
    return day, symbol


def _index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    indexed = {_key(row): row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError("Duplicate seed event key; refusing silent deduplication")
    return indexed


def _selection(cohort: str, day: str) -> str:
    if day < "2024-01-01":
        return "weekly_leader"
    return "daily_leader_collection" if cohort == "selected_gainer" else "selected_collapse"


def _inspect(archive: ZipFile) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Pure metadata recount. The public entry point verifies the release hash first."""
    if len(archive.namelist()) != len(set(archive.namelist())):
        raise ValueError("Duplicate ZIP member; ambiguous source bytes")
    inputs: dict[str, Any] = {}

    def read_csv(name: str, delimiter: str = ",") -> list[dict[str, str]]:
        raw = archive.read(name)
        reader = csv.DictReader(
            io.StringIO(raw.decode("utf-8-sig"), newline=""), delimiter=delimiter
        )
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"Missing or duplicate columns: {name}")
        rows = list(reader)
        if any(None in row or None in row.values() for row in rows):
            raise ValueError(f"Ragged CSV row: {name}")
        inputs[name] = {
            "sha256": _sha(raw),
            "bytes": len(raw),
            "rows": len(rows),
            "delimiter": delimiter,
            "date_range": (
                [min(r["Date"] for r in rows), max(r["Date"] for r in rows)]
                if rows and "Date" in reader.fieldnames
                else None
            ),
            "blank_fields": {
                field: sum(r[field] == "" for r in rows) for field in reader.fieldnames
            },
        }
        return rows

    calendar = sorted(
        {r["Date"] for r in read_csv(CALENDAR) if "2021-01-01" <= r["Date"] <= "2026-09-22"}
    )
    if not calendar or any(date.fromisoformat(day).isoformat() != day for day in calendar):
        raise ValueError("Missing or invalid observed SPX calendar")
    overlays = {name: _index(read_csv(DATASETS + name)) for name in OVERLAYS}
    corrections = read_csv(DATASETS + CORRECTIONS)
    events: list[dict[str, Any]] = []
    for name in (*GAINERS, LOSERS):
        cohort = "selected_loser" if name == LOSERS else "selected_gainer"
        rows = read_csv(DATASETS + name, "," if name.endswith("2025-2026.csv") else "|")
        _index(rows)
        for ordinal, row in enumerate(rows, start=2):
            day, symbol = _key(row)
            if day not in calendar:
                raise ValueError(f"Seed date absent from observed calendar: {day}")
            events.append(
                {
                    "cohort": cohort,
                    "session_date": day,
                    "symbol": symbol,
                    "selection": _selection(cohort, day),
                    "source_member": DATASETS + name,
                    "source_csv_record": ordinal,
                    "raw_fields": row,
                    "overlays": {
                        overlay: index.get((day, symbol)) for overlay, index in overlays.items()
                    }
                    if cohort == "selected_gainer"
                    else {},
                    "security_id": None,
                    "known_at": None,
                    "first_print_ts": None,
                    "flag_ts": None,
                    "pre_ignition_label": None,
                }
            )
    gainer_keys = {
        (e["session_date"], e["symbol"]) for e in events if e["cohort"] == "selected_gainer"
    }
    if len(gainer_keys) != sum(e["cohort"] == "selected_gainer" for e in events):
        raise ValueError("Duplicate gainer key across files")
    if set(overlays[OVERLAYS[0]]) != gainer_keys:
        raise ValueError("Forward overlay must retain every gainer, including missing returns")
    if any(set(index) - gainer_keys for index in overlays.values()):
        raise ValueError("Unmatched overlay keys; refusing an inferred alias/date correction")
    events.sort(key=lambda e: (e["session_date"], e["cohort"], e["symbol"]))
    coverage = []
    for year in sorted({day[:4] for day in calendar}):
        observed = {day for day in calendar if day.startswith(year)}
        counts: dict[str, Any] = {"year": year, "observed_spx_sessions": len(observed)}
        for cohort in ("selected_gainer", "selected_loser"):
            selected = [
                e for e in events if e["cohort"] == cohort and e["session_date"] in observed
            ]
            dates = {e["session_date"] for e in selected}
            counts[cohort] = {
                "events": len(selected),
                "dates": len(dates),
                "selection": _selection(cohort, year + "-01-01"),
                "unrepresented_dates": sorted(observed - dates),
            }
        coverage.append(counts)
    forward = list(overlays[OVERLAYS[0]].values())
    analysis = [
        r for r in forward if r["Status"] == "OK" and "EXCLUDE" not in r["Discrepancy_Flag"]
    ]
    summary = {
        "scope": "selected_seed_metadata_only",
        "source": RELEASE,
        "survivor_only": True,
        "pit_verified": False,
        "biases": ["retrospective_selection", "weekly_daily_mixed", "survivorship_unresolved"],
        "calendar": {
            "source_member": CALENDAR,
            "exchange_verified": False,
            "sessions": len(calendar),
        },
        "events": dict(Counter(e["cohort"] for e in events)),
        "distinct_gainer_dates": len({day for day, _ in gainer_keys}),
        "recent_gainer_dates": len({day for day, _ in gainer_keys if day >= "2025-01-01"}),
        "readme_recent_dates": 416,
        "coverage": coverage,
        "forward_status": dict(Counter(r["Status"] for r in forward)),
        "forward_exclude_flags": sum("EXCLUDE" in r["Discrepancy_Flag"] for r in forward),
        "forward_analysis_rows": len(analysis),
        "forward_observed_returns": {
            field: sum(r[field] != "" for r in analysis)
            for field in ("Ret_T1_Pct", "Ret_T5_Pct", "Ret_T20_Pct")
        },
        "alias_outcomes": dict(Counter(r["Outcome_Type"] for r in overlays[OVERLAYS[1]].values())),
        "correction_rows": len(corrections),
        "inputs": inputs,
        "blockers": BLOCKERS,
        "ordinary_control_count": None,
        "pre_ignition_label_count": None,
        "trial_accounting": {
            "new_strategy_trials": 0,
            "historical_seed_trials": None,
            "cumulative_n": None,
            "effective_n": None,
            "ledger_binding": None,
            "inference_eligible": False,
        },
    }
    return summary, events, calendar


def _publish_once(path: Path, body: bytes) -> None:
    """Upstream's hard-link publication: no partial receipt and no overwrite."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(body)
    try:
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != body:
                raise ValueError(f"Conflicting immutable receipt: {path}") from None
    finally:
        temporary.unlink()


def reconcile_seed(archive_path: Path, output: Path, *, implementation_sha: str) -> dict[str, Any]:
    """Verify the exact owner archive, then publish research receipts outside the catalog."""
    if len(implementation_sha) != 40 or any(
        c not in "0123456789abcdef" for c in implementation_sha
    ):
        raise ValueError("A full implementation commit SHA is required")
    archive_bytes = archive_path.read_bytes()
    if _sha(archive_bytes) != SEED_SHA256:
        raise ValueError("Seed archive SHA-256 differs from ADR-0027; refusing reconciliation")
    with ZipFile(io.BytesIO(archive_bytes)) as archive:
        summary, events, calendar = _inspect(archive)
        correction_bytes = archive.read(DATASETS + CORRECTIONS)
    summary["archive_sha256"] = SEED_SHA256
    summary["implementation_sha"] = implementation_sha
    summary["implementation_source_sha256"] = _sha(Path(__file__).read_bytes())
    lines = [json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n" for e in events]
    by_date: dict[str, list[str]] = defaultdict(list)
    for event, line in zip(events, lines, strict=True):
        by_date[event["session_date"]].append(line)
    files = {"events.jsonl": "".join(lines).encode(), CORRECTIONS: correction_bytes}
    for day in calendar:
        session_events = [e for e in events if e["session_date"] == day]
        files[f"sessions/{day}.json"] = _json(
            {
                "session_date": day,
                "archive_sha256": SEED_SHA256,
                "implementation_sha": implementation_sha,
                "implementation_source_sha256": summary["implementation_source_sha256"],
                "survivor_only": True,
                "pit_verified": False,
                "events": dict(Counter(e["cohort"] for e in session_events)),
                "selections": sorted({e["selection"] for e in session_events}),
                "event_rows_sha256": _sha("".join(by_date[day]).encode()),
                "input_members": sorted(
                    {e["source_member"] for e in session_events}
                    | {CALENDAR}
                    | {DATASETS + name for e in session_events for name in e["overlays"]}
                ),
                "known_at": None,
                "ordinary_control_count": None,
                "pre_ignition_label_count": None,
                "absence_semantics": "not_selected_or_unobserved; never no_movers",
                "trial_accounting": summary["trial_accounting"],
                "biases": summary["biases"],
                "blockers": BLOCKERS,
            }
        )
    summary["artifacts"] = {name: _sha(body) for name, body in sorted(files.items())}
    # One root digest binds the complete per-session tree without committing market data.
    summary["artifacts_sha256"] = _sha(_json(summary["artifacts"]))
    files["summary.json"] = _json(summary)
    for name, body in files.items():
        path = output / name
        if path.exists() and path.read_bytes() != body:
            raise ValueError(f"Conflicting immutable receipt: {path}")
    for name, body in files.items():
        _publish_once(output / name, body)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    implementation = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    if subprocess.check_output(
        ["git", "status", "--porcelain", "--", "src/sextant/research"], cwd=root
    ):
        parser.error("Commit the research implementation before binding its receipt")
    result = reconcile_seed(args.archive, args.output, implementation_sha=implementation)
    print(
        json.dumps(
            {
                "events": result["events"],
                "sessions": result["calendar"]["sessions"],
                "scope": result["scope"],
                "survivor_only": result["survivor_only"],
            }
        )
    )


if __name__ == "__main__":
    main()
