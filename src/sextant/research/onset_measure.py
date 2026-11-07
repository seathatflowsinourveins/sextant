"""#130 Part 1: measured threshold minutes from the frozen windows.

Reads the pulled SIP raw partitions, never a vendor model. A threshold is the
first event-day minute whose close reaches +5% or +10% over the latest completed
official RTH close before it. The output is the denominator the report needs;
it does not claim a detector flag.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sextant.data.alpaca_history import raw_path, read_raw, symbol_name, timestamp

NY = ZoneInfo("America/New_York")
RTH_CLOSE = time(16, 0)
OPEN = time(9, 30)
PRE = time(4, 0)
POST = time(20, 0)
FIVE = Decimal("1.05")
TEN = Decimal("1.10")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _sessions(path: Path) -> list[date]:
    body = json.loads(path.read_text())
    return [date.fromisoformat(item["date"]) for item in body]


def _bars(raw_root: Path, symbol: str, day: date) -> list[dict[str, Any]]:
    path = raw_path(raw_root, "1min", symbol_name(symbol), day)
    if not path.exists():
        return []
    return read_raw(path)


def _close(row: dict[str, Any]) -> Decimal:
    return Decimal(str(row["c"]))


def _official_close(rows: list[dict[str, Any]]) -> Decimal | None:
    last = None
    for row in rows:
        local = timestamp(row["t"]).astimezone(NY)
        if local.time() <= RTH_CLOSE:
            if last is None or timestamp(row["t"]) > timestamp(last["t"]):
                last = row
    return None if last is None else _close(last)


def _event_series(raw_root: Path, symbol: str, day: date, prior: date) -> list[dict[str, Any]]:
    rows = []
    for row in _bars(raw_root, symbol, prior):
        if timestamp(row["t"]).astimezone(NY).time() >= POST:
            rows.append(row)
    rows.extend(_bars(raw_root, symbol, day))
    return sorted(rows, key=lambda row: timestamp(row["t"]))


def _session(local: datetime) -> str:
    clock = local.time()
    if clock >= POST or clock < PRE:
        return "overnight"
    if clock < OPEN:
        return "pre"
    if clock < RTH_CLOSE:
        return "rth"
    return "post"


def _first(rows: list[dict[str, Any]], prior_close: Decimal, multiple: Decimal) -> datetime | None:
    target = prior_close * multiple
    for row in rows:
        if _close(row) >= target:
            return timestamp(row["t"]).astimezone(NY)
    return None


def measure(freeze: Path, raw_root: Path, output: Path) -> dict[str, Any]:
    events = [row for row in _jsonl(freeze / "events.jsonl") if row["cohort"] == "selected_gainer"]
    sessions = _sessions(output / "calendar" / "alpaca_calendar" / "2020-01-01_2026-12-31.json")
    index = {day: i for i, day in enumerate(sessions)}
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for event in events:
        day = date.fromisoformat(event["day"])
        if day not in index or index[day] == 0:
            missing.append(event["event_id"])
            continue
        prior = sessions[index[day] - 1]
        prior_rows = _bars(raw_root, event["symbol"], prior)
        prior_close = _official_close(prior_rows)
        if prior_close is None:
            missing.append(event["event_id"])
            continue
        series = _event_series(raw_root, event["symbol"], day, prior)
        five = _first(series, prior_close, FIVE)
        ten = _first(series, prior_close, TEN)
        rows.append(
            dict(
                event_id=event["event_id"],
                symbol=event["symbol"],
                day=day.isoformat(),
                prior_session=prior.isoformat(),
                prior_close=str(prior_close),
                first_5pct=five.isoformat() if five else None,
                first_5pct_session=_session(five) if five else None,
                first_10pct=ten.isoformat() if ten else None,
                first_10pct_session=_session(ten) if ten else None,
                bars=len(series),
            )
        )
    output.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    (output / "thresholds.jsonl").write_text(body)
    summary = dict(
        events=len(events),
        measured=len(rows),
        missing=len(missing),
        five=sum(1 for row in rows if row["first_5pct"]),
        ten=sum(1 for row in rows if row["first_10pct"]),
        five_sessions=dict(Counter(row["first_5pct_session"] for row in rows if row["first_5pct"])),
        ten_sessions=dict(
            Counter(row["first_10pct_session"] for row in rows if row["first_10pct"])
        ),
        missing_events=missing,
    )
    (output / "thresholds-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(measure(args.freeze, args.raw, args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
