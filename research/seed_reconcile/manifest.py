"""Reconcile the owner's selected extreme-gainer seed on a research branch.

Research-only metadata audit. It reproduces the design's event and coverage
counts, publishes one immutable manifest per observed SPX session, and binds
every input, output and clock it can actually verify. It adds no strategy,
feed, universe inference or TrialLog.

Sources:
- docs/research/2026-11-06-extreme-gainer-package.md: the recount this repeats.
- docs/handbook/candidate-history.md: selected events are not negatives.
- northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:
  src/northstar_trading/data/alpaca_history.py:publish_once, the temporary-file
  plus hard-link publication adopted here.
- Python 3.13's documented csv, zipfile, hashlib and json APIs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import ZipFile
from zoneinfo import ZoneInfo

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
GAINER_MEMBERS = tuple(DATASETS + name for name in GAINERS)
LOSER_MEMBER = DATASETS + LOSERS
OVERLAY_MEMBERS = tuple(DATASETS + name for name in OVERLAYS)
CORRECTIONS_MEMBER = DATASETS + CORRECTIONS
INPUT_MEMBERS = (CALENDAR, *GAINER_MEMBERS, LOSER_MEMBER, *OVERLAY_MEMBERS, CORRECTIONS_MEMBER)
README_MEMBER = PACKAGE + "README.md"
GRAND_MANIFEST_MEMBER = "GRAND-MANIFEST.md"

EXPECTED_SESSIONS = {"2021": 252, "2022": 251, "2023": 250, "2024": 252, "2025": 250, "2026": 181}
EXPECTED_GAINER_EVENTS = {"2021": 52, "2022": 52, "2023": 51, "2024": 279, "2025": 281, "2026": 242}
EXPECTED_GAINER_DATES = {"2021": 52, "2022": 52, "2023": 51, "2024": 235, "2025": 241, "2026": 176}
EXPECTED_LOSER_EVENTS = {"2021": 52, "2022": 52, "2023": 52, "2024": 24, "2025": 26, "2026": 9}
EXPECTED_LOSER_DATES = {"2021": 52, "2022": 52, "2023": 52, "2024": 23, "2025": 24, "2026": 9}
EXPECTED_TOTAL_GAINERS = 957
EXPECTED_TOTAL_LOSERS = 215
EXPECTED_DISTINCT_GAINER_DATES = 807
EXPECTED_RECENT_GAINER_DATES = 417
EXPECTED_README_RECENT_DATES = 416
EXPECTED_SESSIONS_WITH_ANY_SEED_EVENT = 940
EXPECTED_FORWARD_STATUS = {"OK": 686, "NO_DATA": 265, "EVENT_BAR_MISSING": 6}
EXPECTED_FORWARD_EXCLUDE_FLAGS = 8
EXPECTED_ANALYSIS_ROWS = 678
EXPECTED_OBSERVED_RETURNS = {"Ret_T1_Pct": 671, "Ret_T5_Pct": 662, "Ret_T20_Pct": 646}

BIAS = {
    "selected_event": True,
    "survivor_only": True,
    "retrospective_selection": True,
    "weekly_daily_mixed": True,
    "ordinary_non_mover_controls": False,
    "selected_loser_is_selected_collapse": True,
    "absence_is_not_no_mover": True,
    "ticker_identity_unresolved": True,
}
BLOCKERS = {
    "pit_membership": "Dated share-class master, actions, scope and rights receipts unavailable",
    "delisting_acceptance": "10-exit, independent sample and recycled-ticker receipts unavailable",
    "ordinary_controls": "All-stock PIT stock-days and a frozen control protocol unavailable",
    "pre_ignition_labels": "Causal onset receipts and a source-backed frozen protocol unavailable",
    "availability_clocks": "Historical receipt/publication/first-print clocks unavailable in seed",
    "scanner_archive": "Oct 27-Nov 6 scanner archive not mounted; attaching is the owner's step",
    "trial_ledger": "Cumulative TrialLog/custody unavailable; no replacement ledger created",
}
TRIAL_ACCOUNTING = {
    "new_strategy_trials": 0,
    "historical_seed_trials": None,
    "cumulative_n": None,
    "effective_n": None,
    "ledger_binding": None,
    "inference_eligible": False,
}


def _json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label}: expected {expected!r}, got {actual!r}")


def _key(row: dict[str, str]) -> tuple[str, str]:
    day, symbol = row["Date"], row["Ticker"]
    if datetime.fromisoformat(day).date().isoformat() != day or not symbol.strip():
        raise ValueError("Invalid seed event identity")
    return day, symbol


def _index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    indexed = {_key(row): row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError("Duplicate seed event key; refusing silent deduplication")
    return indexed


def _selection(cohort: str, day: str) -> str:
    weekly = day < "2024-01-01"
    if cohort == "selected_gainer":
        return "weekly_leader" if weekly else "daily_leader_collection"
    return "weekly_selected_collapse" if weekly else "selected_collapse"


def _read_csv(
    archive: ZipFile, member: str, delimiter: str
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    raw = archive.read(member)
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), delimiter=delimiter)
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError(f"Missing or duplicate columns: {member}")
    rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError(f"Ragged CSV row: {member}")
    meta = {
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
            field: sum(row[field] == "" for row in rows) for field in reader.fieldnames
        },
    }
    return rows, meta


def _documents(archive: ZipFile) -> tuple[dict[str, Any], dict[str, Any]]:
    readme_raw = archive.read(README_MEMBER)
    readme_text = readme_raw.decode("utf-8")
    claim = re.search(r"2025.26\s+covers\s+(\d+)\s+trading dates", readme_text)
    if claim is None:
        raise ValueError("README's recent-date claim is missing; refusing a silent substitute")
    readme_dates = int(claim.group(1))
    grand_raw = archive.read(GRAND_MANIFEST_MEMBER)
    grand_text = grand_raw.decode("utf-8")
    revision = re.search(r"\*\*Grand revision:\*\*\s*(\d+)", grand_text)
    built = re.search(r"\*\*Built:\*\*\s+(\d{4}-\d{2}-\d{2}) ~(\d{2}:\d{2}) ET", grand_text)
    if revision is None or built is None:
        raise ValueError("Grand manifest revision/build declaration is missing")
    declared_et = datetime.fromisoformat(f"{built.group(1)}T{built.group(2)}:00")
    declared_utc = _utc(declared_et.replace(tzinfo=ZoneInfo("America/New_York")))
    documents = {
        README_MEMBER: {
            "sha256": _sha(readme_raw),
            "bytes": len(readme_raw),
            "declared_recent_dates": readme_dates,
            "claim": claim.group(0),
        },
        GRAND_MANIFEST_MEMBER: {
            "sha256": _sha(grand_raw),
            "bytes": len(grand_raw),
            "grand_revision": int(revision.group(1)),
            "built_declared": f"{built.group(1)} ~{built.group(2)} ET",
            "built_declared_utc": declared_utc,
        },
    }
    return documents, documents[GRAND_MANIFEST_MEMBER]


def _inspect(
    archive: ZipFile, archive_bytes: int
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError("Duplicate ZIP member; ambiguous source bytes")
    infos = archive.infolist()
    latest = max(infos, key=lambda info: info.date_time)
    content_written_at = _utc(datetime(*latest.date_time, tzinfo=UTC))

    calendar_rows, calendar_meta = _read_csv(archive, CALENDAR, ",")
    calendar = sorted(
        {row["Date"] for row in calendar_rows if "2021-01-01" <= row["Date"] <= "2026-09-22"}
    )
    if not calendar or any(
        datetime.fromisoformat(day).date().isoformat() != day for day in calendar
    ):
        raise ValueError("Missing or invalid observed SPX calendar")
    _require(len(calendar), sum(EXPECTED_SESSIONS.values()), "calendar sessions")

    overlays = {name: _index(_read_csv(archive, DATASETS + name, ",")[0]) for name in OVERLAYS}
    corrections_rows, corrections_meta = _read_csv(archive, CORRECTIONS_MEMBER, ",")
    documents, grand = _documents(archive)

    events: list[dict[str, Any]] = []
    inputs: dict[str, Any] = {CALENDAR: calendar_meta, CORRECTIONS_MEMBER: corrections_meta}
    for name in (*GAINERS, LOSERS):
        cohort = "selected_loser" if name == LOSERS else "selected_gainer"
        member = DATASETS + name
        rows, meta = _read_csv(
            archive, member, "," if name == "extreme-gainers-2025-2026.csv" else "|"
        )
        inputs[member] = meta
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
                    "source_member": member,
                    "source_csv_record": ordinal,
                    "raw_fields": row,
                    "overlays": (
                        {overlay: index.get((day, symbol)) for overlay, index in overlays.items()}
                        if cohort == "selected_gainer"
                        else {}
                    ),
                    "security_id": None,
                    "known_at": None,
                    "first_print_ts": None,
                    "flag_ts": None,
                    "pre_ignition_label": None,
                    "bias": {"selected_event": True, "survivor_only": True},
                }
            )
    for name in OVERLAYS:
        inputs[DATASETS + name] = _read_csv(archive, DATASETS + name, ",")[1]
    gainer_keys = {
        (event["session_date"], event["symbol"])
        for event in events
        if event["cohort"] == "selected_gainer"
    }
    if len(gainer_keys) != sum(event["cohort"] == "selected_gainer" for event in events):
        raise ValueError("Duplicate gainer key across files")
    if set(overlays[OVERLAYS[0]]) != gainer_keys:
        raise ValueError("Forward overlay must retain every gainer, including missing returns")
    if any(set(index) - gainer_keys for index in overlays.values()):
        raise ValueError("Unmatched overlay keys; refusing an inferred alias/date correction")

    events.sort(key=lambda event: (event["session_date"], event["cohort"], event["symbol"]))
    counts = Counter(event["cohort"] for event in events)
    _require(counts["selected_gainer"], EXPECTED_TOTAL_GAINERS, "gainer events")
    _require(counts["selected_loser"], EXPECTED_TOTAL_LOSERS, "loser events")

    coverage: dict[str, list[dict[str, Any]]] = {"gainers": [], "losers": []}
    for year in sorted(EXPECTED_SESSIONS):
        observed = {day for day in calendar if day.startswith(year)}
        _require(len(observed), EXPECTED_SESSIONS[year], f"observed sessions {year}")
        for cohort, key, event_expect, date_expect in (
            ("selected_gainer", "gainers", EXPECTED_GAINER_EVENTS, EXPECTED_GAINER_DATES),
            ("selected_loser", "losers", EXPECTED_LOSER_EVENTS, EXPECTED_LOSER_DATES),
        ):
            selected = [
                event
                for event in events
                if event["cohort"] == cohort and event["session_date"] in observed
            ]
            dates = {event["session_date"] for event in selected}
            _require(len(selected), event_expect[year], f"{cohort} events {year}")
            _require(len(dates), date_expect[year], f"{cohort} dates {year}")
            coverage[key].append(
                {
                    "year": year,
                    "selection": _selection(cohort, year + "-01-01"),
                    "events": len(selected),
                    "dates": len(dates),
                    "observed_spx_sessions": len(observed),
                    "share": round(len(dates) / len(observed), 4),
                    "unrepresented_dates": sorted(observed - dates),
                }
            )

    distinct_gainer_dates = len({day for day, _ in gainer_keys})
    recent_gainer_dates = len({day for day, _ in gainer_keys if day >= "2025-01-01"})
    _require(distinct_gainer_dates, EXPECTED_DISTINCT_GAINER_DATES, "distinct gainer dates")
    _require(recent_gainer_dates, EXPECTED_RECENT_GAINER_DATES, "recent gainer dates")
    _require(
        documents[README_MEMBER]["declared_recent_dates"],
        EXPECTED_README_RECENT_DATES,
        "README recent dates",
    )

    forward = list(overlays[OVERLAYS[0]].values())
    forward_status = Counter(row["Status"] for row in forward)
    _require(dict(forward_status), EXPECTED_FORWARD_STATUS, "forward status")
    exclude_flags = sum("EXCLUDE" in row["Discrepancy_Flag"] for row in forward)
    _require(exclude_flags, EXPECTED_FORWARD_EXCLUDE_FLAGS, "forward exclude flags")
    analysis = [
        row for row in forward if row["Status"] == "OK" and "EXCLUDE" not in row["Discrepancy_Flag"]
    ]
    _require(len(analysis), EXPECTED_ANALYSIS_ROWS, "forward analysis rows")
    observed_returns = {
        field: sum(row[field] != "" for row in analysis)
        for field in ("Ret_T1_Pct", "Ret_T5_Pct", "Ret_T20_Pct")
    }
    _require(observed_returns, EXPECTED_OBSERVED_RETURNS, "observed forward returns")

    event_dates = {event["session_date"] for event in events}
    sessions_with_any_event = len(event_dates)
    _require(
        sessions_with_any_event,
        EXPECTED_SESSIONS_WITH_ANY_SEED_EVENT,
        "sessions with any seed event",
    )

    knowledge = {
        "knowable_at": grand["built_declared_utc"],
        "basis": (
            "GRAND-MANIFEST.md declares Built 2026-10-09 ~08:45 ET; latest ZIP member "
            f"mtime is {content_written_at}; release publication is unverified"
        ),
        "precision": "~15 minutes (declared ~08:45 ET)",
        "release_published_at": None,
        "exchange_verified": False,
        "content_written_at": content_written_at,
        "max_mtime_member": latest.filename,
        "decision_clock": None,
        "event_clocks": {
            "first_print_ts": None,
            "flag_ts": None,
            "publication_ts": None,
            "known_at": None,
        },
        "event_clock_blocker": (
            "The seed carries no event first-print, detector-flag, publication or receipt clock"
        ),
    }
    summary = {
        "scope": "selected_seed_metadata_only",
        "source_release": RELEASE,
        "survivor_only": True,
        "pit_verified": False,
        "inference_eligible": False,
        "bias": BIAS,
        "archive": {
            "sha256": SEED_SHA256,
            "bytes": archive_bytes,
            "zip_members": len(names),
            "regular_files": sum(not info.is_dir() for info in infos),
            "max_member_mtime_utc": content_written_at,
            "max_mtime_member": latest.filename,
            "grand_revision": grand["grand_revision"],
            "grand_built_declared": grand["built_declared"],
            "grand_built_declared_utc": grand["built_declared_utc"],
        },
        "documents": documents,
        "calendar": {
            "source_member": CALENDAR,
            "exchange_verified": False,
            "sessions": len(calendar),
            "first_session": calendar[0],
            "last_session": calendar[-1],
            "sessions_with_any_seed_event": sessions_with_any_event,
            "sessions_without_any_seed_event": len(calendar) - sessions_with_any_event,
        },
        "events": {
            "selected_gainer": counts["selected_gainer"],
            "selected_loser": counts["selected_loser"],
        },
        "distinct_gainer_dates": distinct_gainer_dates,
        "recent_gainer_dates": recent_gainer_dates,
        "readme_recent_dates": documents[README_MEMBER]["declared_recent_dates"],
        "recent_dates_disagreement": {
            "parsed_distinct_dates": recent_gainer_dates,
            "readme_declared_dates": documents[README_MEMBER]["declared_recent_dates"],
            "difference": recent_gainer_dates - documents[README_MEMBER]["declared_recent_dates"],
            "note": "Preserved; neither is verified all-stock coverage or pre-move recall",
        },
        "coverage": coverage,
        "forward_status": dict(sorted(forward_status.items())),
        "forward_exclude_flags": exclude_flags,
        "forward_analysis_rows": len(analysis),
        "forward_observed_returns": observed_returns,
        "alias_outcomes": dict(
            sorted(Counter(row["Outcome_Type"] for row in overlays[OVERLAYS[1]].values()).items())
        ),
        "recovered_supplement_rows": len(overlays[OVERLAYS[2]]),
        "correction_rows": len(corrections_rows),
        "inputs": {member: inputs[member] for member in sorted(inputs)},
        "knowledge": knowledge,
        "blockers": BLOCKERS,
        "ordinary_control_count": None,
        "pre_ignition_label_count": None,
        "trial_accounting": TRIAL_ACCOUNTING,
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


def reconcile_seed(archive_path: Path, output: Path) -> dict[str, Any]:
    """Verify the exact owner archive, then publish research receipts outside the catalog."""
    archive_bytes = archive_path.read_bytes()
    if _sha(archive_bytes) != SEED_SHA256:
        raise ValueError("Seed archive SHA-256 differs from ADR-0027; refusing reconciliation")
    with ZipFile(io.BytesIO(archive_bytes)) as archive:
        summary, events, calendar = _inspect(archive, len(archive_bytes))
    summary["implementation"] = {
        "script": "research/seed_reconcile/manifest.py",
        "script_sha256": _sha(Path(__file__).read_bytes()),
        "language": "CPython >=3.13,<3.14; standard library only",
    }
    lines = [
        json.dumps(
            {**event, "selection_knowable_at": summary["knowledge"]["knowable_at"]},
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
        for event in events
    ]
    by_date: dict[str, list[str]] = {day: [] for day in calendar}
    for event, line in zip(events, lines, strict=True):
        by_date[event["session_date"]].append(line)
    input_hashes = {name: meta["sha256"] for name, meta in summary["inputs"].items()}
    files = {"events.jsonl": "".join(lines).encode()}
    for day in calendar:
        session_events = [event for event in events if event["session_date"] == day]
        session_counts = Counter(event["cohort"] for event in session_events)
        files[f"sessions/{day}.json"] = _json(
            {
                "session_date": day,
                "archive_sha256": SEED_SHA256,
                "script_sha256": summary["implementation"]["script_sha256"],
                "survivor_only": True,
                "pit_verified": False,
                "inference_eligible": False,
                "bias": BIAS,
                "events": {
                    "selected_gainer": session_counts.get("selected_gainer", 0),
                    "selected_loser": session_counts.get("selected_loser", 0),
                },
                "selections": sorted({event["selection"] for event in session_events}),
                "event_rows_sha256": _sha("".join(by_date[day]).encode()),
                "input_members": input_hashes,
                "knowledge": summary["knowledge"],
                "absence_semantics": "not_selected_or_unobserved; never no_movers",
                "ordinary_control_count": None,
                "pre_ignition_label_count": None,
                "trial_accounting": TRIAL_ACCOUNTING,
                "blockers": BLOCKERS,
            }
        )
    artifacts = {name: _sha(body) for name, body in sorted(files.items())}
    summary["artifacts"] = artifacts
    summary["artifacts_sha256"] = _sha(_json(artifacts))
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
    result = reconcile_seed(args.archive, args.output)
    print(
        json.dumps(
            {
                "events": result["events"],
                "sessions": result["calendar"]["sessions"],
                "artifacts": len(result["artifacts"]) + 1,
                "artifacts_sha256": result["artifacts_sha256"],
                "survivor_only": result["survivor_only"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
