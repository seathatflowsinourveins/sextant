"""#130 Part 1: frozen-cohort minute pull and detector study over one catalog.

The pull is historical SIP minute bars only, through the carried Alpaca REST
client, at most 200 requests a minute, before an explicit stop time. Bars land
in row 11's raw envelope and native ParquetDataCatalog; no stream, broker
endpoint or order path is reachable. Study flags are computed after the pull.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sextant.data.alpaca_history import (
    Pacer,
    calendar_cache,
    day_start,
    land_raw,
    raw_path,
    read_raw,
    symbol_name,
)
from sextant.data.catalog import CatalogStore, decode_bars
from sextant.research.onset_capture import (
    BoundedCalendar,
    BoundedHistory,
    CaptureBudget,
    CaptureStopped,
)
from sextant.research.onset_common import read_jsonl, sha256_file


def _json(path: Path) -> Any:
    return json.loads(path.read_text())


def load_freeze(directory: Path) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    events = read_jsonl(directory / "events.jsonl")
    controls: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(directory / "controls.jsonl"):
        controls[row["event_id"]].append(row)
    for rows in controls.values():
        rows.sort(key=lambda row: row["role"])
    return events, controls


def market_sessions(cache: Path, budget: CaptureBudget) -> list[date]:
    calendar = BoundedCalendar(budget)
    try:
        sessions = calendar_cache(
            cache,
            date(2020, 1, 1),
            date(2026, 12, 31),
            calendar,
        )
    finally:
        calendar.close()
    return [item.date for item in sessions]


def study_budget(
    *, max_requests: int, max_bytes: int, deadline: datetime, per_minute: Decimal
) -> CaptureBudget:
    """Widen the frozen pilot object's bounds without changing its endpoint refusals."""
    budget = CaptureBudget(
        max_requests=160,
        max_bytes=128 * 1024**2,
        deadline=datetime(2026, 11, 6, 19, 0, tzinfo=UTC),
        requests_per_minute=Decimal(60),
    )
    if max_requests > 4000 or max_bytes > 8 * 1024**3 or per_minute > 200:
        raise CaptureStopped("study_budget_exceeds_contract")
    budget.max_requests = max_requests
    budget.max_bytes = max_bytes
    budget.deadline = deadline
    budget.rate = per_minute
    budget.wait = Pacer(per_minute).wait
    return budget


def pull_targets(
    events: Sequence[dict[str, Any]],
    controls: dict[str, list[dict[str, Any]]],
) -> list[dict[str, str]]:
    """Event days and their primary control; backups are pulled only on an empty primary."""
    targets: list[dict[str, str]] = []
    for event in events:
        if event["cohort"] != "selected_gainer" or not event["control_ids"]:
            continue
        targets.append(
            dict(
                role="event",
                event_id=event["event_id"],
                control_id="",
                symbol=symbol_name(event["symbol"]),
                day=event["day"],
            )
        )
        primary = next(row for row in controls[event["event_id"]] if row["role"] == "primary")
        targets.append(
            dict(
                role="control",
                event_id=event["event_id"],
                control_id=primary["control_id"],
                symbol=symbol_name(primary["ticker"]),
                day=primary["day"],
            )
        )
    return targets


def needed_days(
    targets: Sequence[dict[str, str]], sessions: Sequence[date], lookback: int
) -> dict[date, list[str]]:
    """One symbol-day pull set serves every target window that contains it."""
    by_day: dict[date, set[str]] = defaultdict(set)
    index = {day: i for i, day in enumerate(sessions)}
    for target in targets:
        end = date.fromisoformat(target["day"])
        if end not in index:
            raise CaptureStopped("target_day_not_a_session")
        first = index[end] - lookback
        if first < 0:
            raise CaptureStopped("insufficient_calendar")
        for day in sessions[first : index[end] + 1]:
            by_day[day].add(target["symbol"])
    return {day: sorted(symbols) for day, symbols in by_day.items()}


def _split_pages(pages: Sequence[str], symbols: Sequence[str]) -> dict[str, list[str]]:
    """Keep source bar arrays unchanged; only the response envelope is per-symbol."""
    merged: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for text in pages:
        body = json.loads(text)
        for symbol, rows in (body.get("bars") or {}).items():
            merged[symbol].extend(rows)
    result: dict[str, list[str]] = {}
    for symbol in symbols:
        rows = merged.get(symbol, [])
        if rows:
            result[symbol] = [json.dumps({"bars": {symbol: rows}})]
    return result


def pull(
    freeze: Path,
    raw_root: Path,
    catalog_root: Path,
    output: Path,
    *,
    deadline: datetime,
    max_requests: int = 3000,
    max_bytes: int = 6 * 1024**3,
    per_minute: Decimal = Decimal(200),
    lookback: int = 14,
    targets: Sequence[dict[str, str]] | None = None,
    force: bool = False,
    budget: CaptureBudget | None = None,
    sessions: Sequence[date] | None = None,
    receipts: list[dict[str, Any]] | None = None,
    study_outputs: bool = True,
) -> dict[str, Any]:
    """Land one 1min symbol-day pull in raw envelopes and the native catalog.

    The study call derives its targets from the freeze. The fallback call passes
    its backup symbol-days, the shared budget, sessions and receipt list, and
    ``study_outputs=False`` so it writes only its own summary files.
    """
    output.mkdir(parents=True, exist_ok=True)
    if budget is None:
        budget = study_budget(
            max_requests=max_requests,
            max_bytes=max_bytes,
            deadline=deadline,
            per_minute=per_minute,
        )
    if targets is None:
        events, controls = load_freeze(freeze)
        targets = pull_targets(events, controls)
    if sessions is None:
        sessions = market_sessions(output / "calendar", budget)
    needs = needed_days(targets, sessions, lookback)
    receipts = [] if receipts is None else receipts
    receipts_path = output / "pull-receipts.jsonl" if study_outputs else None
    known: dict[tuple[str, str], dict[str, Any]] = {}
    if receipts_path is not None and receipts_path.exists():
        for line in receipts_path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                known[(row["symbol"], row["day"])] = row
    history = BoundedHistory(budget)
    catalog = CatalogStore(catalog_root, cache_intervals=True)
    try:
        for day in sorted(needs):
            pending = []
            for symbol in needs[day]:
                raw = raw_path(raw_root, "1min", symbol, day)
                if force or not raw.exists():
                    pending.append(symbol)
                    continue
                key = (symbol, day.isoformat())
                receipt = known.get(key)
                if receipt is None:
                    bars = decode_bars(read_raw(raw), symbol, "1min")
                    receipt = dict(
                        symbol=symbol,
                        day=day.isoformat(),
                        bars=len(bars),
                        raw_sha256=sha256_file(raw),
                        source_pages_sha256=None,
                        resumed=True,
                    )
                receipts.append(receipt)
            for start in range(0, len(pending), 50):
                batch = pending[start : start + 50]
                if not batch:
                    continue
                pages = history.fetch_batch(
                    batch,
                    day_start(day),
                    day_start(day + timedelta(days=1)) - timedelta(microseconds=1),
                    "1min",
                )
                split = _split_pages(pages, batch)
                source_sha = hashlib.sha256("".join(pages).encode()).hexdigest()
                for symbol in batch:
                    raw = raw_path(raw_root, "1min", symbol, day)
                    symbol_pages = split.get(symbol)
                    if not symbol_pages:
                        receipts.append(
                            dict(symbol=symbol, day=day.isoformat(), bars=0, empty=True)
                        )
                        continue
                    land_raw(raw, symbol_pages, symbol=symbol, day=day, bar="1min")
                    bars = decode_bars(read_raw(raw), symbol, "1min")
                    if bars:
                        catalog.write(symbol, bars, raw_partition=raw)
                    receipts.append(
                        dict(
                            symbol=symbol,
                            day=day.isoformat(),
                            bars=len(bars),
                            raw_sha256=sha256_file(raw),
                            source_pages_sha256=source_sha,
                        )
                    )
            if receipts_path is not None:
                receipts_path.write_text(
                    "".join(json.dumps(row, sort_keys=True) + "\n" for row in receipts)
                )
    finally:
        history.close()
        if receipts_path is not None:
            receipts_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in receipts)
            )
    summary = dict(
        targets=len(targets),
        days=len(needs),
        requests=budget.requests,
        bytes=budget.bytes,
        receipts=len(receipts),
        receipts_sha256=sha256_file(receipts_path) if receipts_path is not None else None,
    )
    if study_outputs:
        (output / "pull-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def _deadline(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    freeze_parser = sub.add_parser("freeze", help="write the frozen cohort and controls")
    freeze_parser.add_argument("--events", type=Path, required=True)
    freeze_parser.add_argument("--tickers", type=Path, required=True)
    freeze_parser.add_argument("--out", type=Path, required=True)

    measure_parser = sub.add_parser("measure", help="measure threshold minutes")
    measure_parser.add_argument("--freeze", type=Path, required=True)
    measure_parser.add_argument("--raw", type=Path, required=True)
    measure_parser.add_argument("--output", type=Path, required=True)

    sip_parser = sub.add_parser("sip", help="evaluate the Stocks in Play detector")
    sip_parser.add_argument("--freeze", type=Path, required=True)
    sip_parser.add_argument("--raw", type=Path, required=True)
    sip_parser.add_argument("--calendar", type=Path, required=True)
    sip_parser.add_argument("--thresholds", type=Path, required=True)
    sip_parser.add_argument("--output", type=Path, required=True)
    sip_parser.add_argument("--fallback", type=Path)

    pull_parser = sub.add_parser("pull", help="pull the event and primary control days")
    pull_parser.add_argument("--freeze", type=Path, required=True)
    pull_parser.add_argument("--raw", type=Path, required=True)
    pull_parser.add_argument("--catalog", type=Path, required=True)
    pull_parser.add_argument("--output", type=Path, required=True)
    pull_parser.add_argument("--deadline", required=True)

    fallback_parser = sub.add_parser("fallback", help="pull the frozen backup controls")
    fallback_parser.add_argument("--freeze", type=Path, required=True)
    fallback_parser.add_argument("--raw", type=Path, required=True)
    fallback_parser.add_argument("--catalog", type=Path, required=True)
    fallback_parser.add_argument("--output", type=Path, required=True)
    fallback_parser.add_argument("--deadline", required=True)
    fallback_parser.add_argument("--force", action="store_true")

    outcome_parser = sub.add_parser("outcome", help="build the outcome handoff from the study")
    outcome_parser.add_argument("--freeze", type=Path, required=True)
    outcome_parser.add_argument("--study", type=Path, required=True)
    outcome_parser.add_argument("--reserve", type=Path, required=True)
    outcome_parser.add_argument("--output", type=Path, required=True)
    outcome_parser.add_argument("--runner-sha")

    args = parser.parse_args(argv)
    if args.command == "freeze":
        from sextant.research.onset_freeze import freeze

        manifest = freeze(args.events, args.tickers, args.out)
        print(json.dumps({"counts": manifest["counts"], "files": manifest["files"]}, indent=2))
    elif args.command == "measure":
        from sextant.research.onset_measure import measure

        print(json.dumps(measure(args.freeze, args.raw, args.output), indent=2, sort_keys=True))
    elif args.command == "sip":
        from sextant.research.detectors.stocks_in_play import PARAMETERS, StocksInPlaySpec
        from sextant.research.onset_sip import evaluate

        report = evaluate(
            args.freeze,
            args.raw,
            args.calendar,
            args.thresholds,
            StocksInPlaySpec(PARAMETERS),
            fallback=args.fallback,
        )
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "sip.json").write_text(json.dumps(report, indent=2, sort_keys=True))
        print(
            json.dumps(
                {k: v for k, v in report.items() if k not in {"rows", "event_rows"}},
                indent=2,
                sort_keys=True,
            )
        )
    elif args.command == "pull":
        summary = pull(
            args.freeze,
            args.raw,
            args.catalog,
            args.output,
            deadline=_deadline(args.deadline),
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
    elif args.command == "outcome":
        from sextant.research.onset_outcome import build_outcome

        summary = build_outcome(
            args.freeze,
            args.study,
            args.reserve,
            args.output,
            runner_sha=args.runner_sha,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        from sextant.research.onset_fallback import pull_fallbacks

        body = pull_fallbacks(
            args.freeze,
            args.raw,
            args.catalog,
            args.output,
            deadline=_deadline(args.deadline),
            force=args.force,
        )
        print(json.dumps(body, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
