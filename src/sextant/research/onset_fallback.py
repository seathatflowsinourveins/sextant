"""#130 Part 1: pull the frozen backup controls for zero-bar primary days.

The frozen rule (`frozen/rule.md:26-28`) pre-registers backup 1 and backup 2 as
the fallback for a primary control day with no bars. This module pulls only those
backup symbol-days, in role order, and records the first backup with a printed
bar as the selected control. It never re-ranks a control.

The pull uses the same bounded historical SIP client as the main study: GET only,
at most 200 requests a minute, before an explicit stop time. No order, stream or
live endpoint is reachable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sextant.data.alpaca_history import raw_path, read_raw, symbol_name
from sextant.research.onset_study import (
    load_freeze,
    market_sessions,
    pull,
    study_budget,
)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def zero_bar_primaries(freeze: Path, raw_root: Path) -> list[dict[str, Any]]:
    """One row per event whose frozen primary control has no printed bar on its day."""
    events, controls = load_freeze(freeze)
    rows: list[dict[str, Any]] = []
    for event in events:
        if event["cohort"] != "selected_gainer" or not event["control_ids"]:
            continue
        primary = next(row for row in controls[event["event_id"]] if row["role"] == "primary")
        path = raw_path(
            raw_root,
            "1min",
            symbol_name(primary["ticker"]),
            date.fromisoformat(primary["day"]),
        )
        if path.exists() and read_raw(path):
            continue
        backups = sorted(
            (row for row in controls[event["event_id"]] if row["role"] in {"backup_1", "backup_2"}),
            key=lambda row: row["role"],
        )
        rows.append(dict(event_id=event["event_id"], primary=primary, backups=backups))
    return rows


def pull_fallbacks(
    freeze: Path,
    raw_root: Path,
    catalog_root: Path,
    output: Path,
    *,
    deadline: datetime,
    max_requests: int = 600,
    max_bytes: int = 1 * 1024**3,
    per_minute: Decimal = Decimal(150),
    lookback: int = 14,
    force: bool = False,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    budget = study_budget(
        max_requests=max_requests,
        max_bytes=max_bytes,
        deadline=deadline,
        per_minute=per_minute,
    )
    sessions = market_sessions(output / "calendar", budget)
    primaries = zero_bar_primaries(freeze, raw_root)
    selected: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for role in ("backup_1", "backup_2"):
        pending = [row for row in primaries if row["event_id"] not in selected]
        stage_rows = [
            backup for row in pending for backup in row["backups"] if backup["role"] == role
        ]
        if not stage_rows:
            continue
        targets = [
            dict(
                symbol=symbol_name(row["ticker"]),
                day=row["day"],
                control_id=row["control_id"],
            )
            for row in stage_rows
        ]
        pull(
            freeze,
            raw_root,
            catalog_root,
            output,
            deadline=deadline,
            budget=budget,
            sessions=sessions,
            receipts=receipts,
            targets=targets,
            force=force,
            lookback=lookback,
            study_outputs=False,
        )
        for row in pending:
            for backup in row["backups"]:
                if backup["role"] != role:
                    continue
                path = raw_path(
                    raw_root,
                    "1min",
                    symbol_name(backup["ticker"]),
                    date.fromisoformat(backup["day"]),
                )
                if path.exists() and read_raw(path):
                    selected[row["event_id"]] = dict(
                        event_id=row["event_id"],
                        primary_control_id=row["primary"]["control_id"],
                        control_id=backup["control_id"],
                        role=role,
                        ticker=backup["ticker"],
                        day=backup["day"],
                        permaticker=backup["permaticker"],
                    )
                    break
    unresolved = [
        dict(event_id=row["event_id"], primary_control_id=row["primary"]["control_id"])
        for row in primaries
        if row["event_id"] not in selected
    ]
    (output / "fallback-receipts.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in receipts)
    )
    body = dict(
        primaries_without_bars=len(primaries),
        selected=len(selected),
        unresolved=len(unresolved),
        replacements=sorted(selected.values(), key=lambda item: item["event_id"]),
        unresolved_rows=unresolved,
        receipts=len(receipts),
        receipts_sha256=_sha(output / "fallback-receipts.jsonl"),
        requests=budget.requests,
        bytes=budget.bytes,
    )
    (output / "fallback.json").write_text(json.dumps(body, indent=2, sort_keys=True))
    return body


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deadline", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    body = pull_fallbacks(
        args.freeze,
        args.raw,
        args.catalog,
        args.output,
        deadline=datetime.fromisoformat(args.deadline.replace("Z", "+00:00")),
        force=args.force,
    )
    print(json.dumps(body, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
