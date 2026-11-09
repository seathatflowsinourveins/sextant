"""Read-only direct Sharadar coverage; no universe or historical knowledge is inferred.

Transport, bulk/CSV handling, bounded slices and receipt-only visibility follow
northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:data/sharadar.py.
Sharadar's own docs (read 2026-11-06) identify its account key with the direct API.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zipfile import ZipFile, is_zipfile
from zoneinfo import ZoneInfo

from sextant.research import candidate_history as seed
from sextant.research import sharadar_client
from sextant.research.sharadar_client import (
    PIN,
    SOURCE,
    Fetch,
    direct_client,
    parse_response,
)

PROBE_PIN = "80535ddb8a0906dcdb9a98af196de1e8a8aea1ea"
PROBED_EXITS = ("LNKD", "YHOO", "CELG", "LK", "TWTR", "SIVB", "BBBY", "FRC", "ATVI", "XLNX")
TABLES = ("TICKERS", "ACTIONS", "SEP", "SFP", "SF1", "DAILY", "METRICS")
Clock = Callable[[], datetime]
PAGE_LIMIT = 10000  # Pinned direct transport's max_pages; truncation stays incomplete.
PAGE_SIZE = 10000  # Official slice limit; full tables use bulk, never skip/limit.


def _query(
    table: str,
    filters: dict[str, Any],
    output: Path,
    fetch: Fetch,
    clock: Clock,
    ordinal: int,
    *,
    schema_only: bool = False,
) -> dict[str, Any]:
    query: dict[str, Any] = {
        "table": table,
        "filters": filters,
        "status": "error",
        "pages": [],
        "schema_only": schema_only,
    }
    params = dict(filters)
    seen: set[str] = set()
    try:
        for page_number in range(PAGE_LIMIT):
            requested_at = clock().astimezone(UTC).isoformat()
            body = fetch(table, params)
            received_at = clock().astimezone(UTC).isoformat()
            columns, rows = parse_response(body)
            required = {
                "TICKERS": {"table", "permaticker", "ticker", "isdelisted"},
                "ACTIONS": {"date", "action", "ticker", "contraticker"},
                "SEP": {"ticker", "date", "closeunadj"},
                "SFP": {"ticker", "date", "closeunadj"},
            }.get(table, set())
            if not required.issubset(columns):
                raise ValueError("Missing required vendor columns")
            extension = "zip" if is_zipfile(io.BytesIO(body)) else "csv"
            relative = f"raw/{ordinal:06d}-{page_number:05d}.{extension}"
            seed._publish_once(output / relative, body)
            query["pages"].append(
                {
                    "path": relative,
                    "sha256": seed._sha(body),
                    "columns": columns,
                    "requested_at": requested_at,
                    "received_at": received_at,
                }
            )
            if schema_only or "years" in filters or len(rows) < filters["limit"]:
                query["status"] = "schema_only" if schema_only else "complete"
                break
            digest = seed._sha(body)
            if digest in seen or len(rows) > filters["limit"]:
                raise ValueError("Repeated or oversized slice page")
            seen.add(digest)
            params["skip"] = (page_number + 1) * filters["limit"]
        else:
            query["status"] = "page_limit"
    except Exception as exc:
        # Vendor/transport messages can contain a key or URL. Never persist/print them.
        status = getattr(exc, "http_status", None)
        query["error"] = {
            "http_status": status if type(status) is int else None,
            "kind": type(exc).__name__
            if type(exc).__name__
            in {"AuthenticationError", "ForbiddenError", "NotFoundError", "LimitExceededError"}
            else "RequestFailed",
        }
    return query


def capture(
    events: list[dict[str, Any]],
    output: Path,
    *,
    asof: datetime,
    seed_sha256: str,
    implementation_sha: str,
    fetch: Fetch | None = None,
    clock: Clock = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Reserve a fresh capture directory; one serial writer, no persisted download URLs."""
    if asof.tzinfo is None:
        raise ValueError("A timezone-aware asof cutoff is required")
    asof = asof.astimezone(UTC)
    day = asof.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    if not events or any(date.fromisoformat(e["session_date"]).isoformat() > day for e in events):
        raise ValueError("Seed events must be at or before the requested asof date")
    if not re.fullmatch(r"[0-9a-f]{40}", implementation_sha):
        raise ValueError("A full implementation SHA is required")
    if output.exists():
        raise ValueError("Refusing an existing immutable capture; use offline report")
    mode = "offline_fixture" if fetch is not None else "authenticated"
    fetch = fetch or direct_client()
    output.mkdir(parents=True, exist_ok=False)
    queries: list[dict[str, Any]] = []

    def run(table: str, filters: dict[str, Any], *, schema_only: bool = False) -> dict[str, Any]:
        result = _query(table, filters, output, fetch, clock, len(queries), schema_only=schema_only)
        queries.append(result)
        return result

    run("TICKERS", {"years": "full"})
    run("ACTIONS", {"years": "10"})
    for table in ("SEP", "SFP", "SF1", "DAILY", "METRICS"):
        probe = run(table, {"ticker": "TWO", "format": "csv", "limit": 1}, schema_only=True)
        if table not in {"SEP", "SFP"} or probe["status"] != "schema_only":
            continue
        for session in sorted({e["session_date"] for e in events}):
            symbols = sorted({e["symbol"] for e in events if e["session_date"] == session})
            result = run(
                table,
                {
                    "from": session,
                    "to": session,
                    "ticker": ",".join(symbols),
                    "format": "csv",
                    "limit": PAGE_SIZE,
                    "sort": "date.asc",
                },
            )
            if result["status"] != "complete":
                break  # Preserve earlier receipts; subsequent coverage is unknown.
    result = {
        "schema_version": 1,
        "mode": mode,
        "asof": asof.isoformat(),
        "seed_sha256": seed_sha256,
        "seed_events_sha256": seed._sha(seed._json(events)),
        "client": SOURCE,
        "implementation_sha": implementation_sha,
        "implementation_source_sha256": seed._sha(Path(__file__).read_bytes()),
        "transport_source_sha256": seed._sha(Path(sharadar_client.__file__).read_bytes()),
        "queries": queries,
    }
    seed._publish_once(output / "capture.json", seed._json(result))
    return result


def _read_capture(root: Path) -> tuple[dict[str, Any], list[tuple[dict[str, Any], list[dict]]]]:
    capture = json.loads((root / "capture.json").read_bytes())
    if capture["client"] != SOURCE or capture["client"]["commit"] != PIN:
        raise ValueError("Unexpected direct transport source SHA")
    queries = []
    for query in capture["queries"]:
        rows = []
        for page in query["pages"]:
            if not re.fullmatch(r"raw/\d{6}-\d{5}\.(?:csv|zip)", page["path"]):
                raise ValueError("Invalid raw receipt path")
            body = (root / page["path"]).read_bytes()
            if seed._sha(body) != page["sha256"]:
                raise ValueError("Raw response SHA-256 differs from capture hash")
            columns, values = parse_response(body)
            if columns != page["columns"]:
                raise ValueError("Raw schema differs from capture hash receipt")
            rows.extend(values)
        queries.append((query, rows))
    return capture, queries


def _candidates(symbol: str, master: list[dict]) -> list[dict]:
    return [
        row
        for row in master
        if row.get("ticker") == symbol or symbol in (row.get("relatedtickers") or "").split()
    ]


def _price(event: dict, queries: list[tuple[dict, list[dict]]], table: str) -> dict[str, Any]:
    relevant = [
        (query, rows)
        for query, rows in queries
        if query["table"] == table
        and not query["schema_only"]
        and query["filters"].get("from") == event["session_date"]
        and query["filters"].get("to") == event["session_date"]
        and event["symbol"] in query["filters"].get("ticker", "").split(",")
    ]
    rows = [
        row
        for _, values in relevant
        for row in values
        if row.get("ticker") == event["symbol"] and row.get("date") == event["session_date"]
    ]
    status = "unknown"
    if len(relevant) == 1 and relevant[0][0]["status"] == "complete":
        status = "absent" if not rows else "ambiguous" if len(rows) > 1 else "missing_price"
        if len(rows) == 1 and rows[0].get("closeunadj") not in (None, ""):
            status = "observed"
    return {"status": status, "rows": rows}


def report(
    events: list[dict[str, Any]],
    capture_root: Path,
    output: Path,
    *,
    seed_sha256: str,
    calendar: list[str] | None = None,
) -> dict[str, Any]:
    """Offline reconstruction from hash-verified raw pages; no client/key initialization."""
    captured, queries = _read_capture(capture_root)
    if captured["seed_sha256"] != seed_sha256 or captured["seed_events_sha256"] != seed._sha(
        seed._json(events)
    ):
        raise ValueError("Seed/event hash differs from captured query population")
    capture_hash = seed._sha((capture_root / "capture.json").read_bytes())
    tables: dict[str, Any] = {}
    for table in TABLES:
        selected = [(q, rows) for q, rows in queries if q["table"] == table]
        data_queries = [q for q, _ in selected if not q["schema_only"]]
        complete = bool(data_queries) and all(q["status"] == "complete" for q in data_queries)
        if table in {"SEP", "SFP"}:
            complete = complete and {q["filters"]["from"] for q in data_queries} == {
                event["session_date"] for event in events
            }
        columns = sorted({name for q, _ in selected for p in q["pages"] for name in p["columns"]})
        tables[table] = {
            "columns": columns,
            "complete": complete,
            "query_statuses": dict(Counter(q["status"] for q, _ in selected)),
            "captured_rows": sum(len(rows) for q, rows in selected if not q["schema_only"]),
        }
    master = [r for q, rows in queries if q["table"] == "TICKERS" for r in rows]
    actions = [r for q, rows in queries if q["table"] == "ACTIONS" for r in rows]
    enriched = []
    counts: dict[str, Counter] = defaultdict(Counter)
    for event in events:
        prices = {table: _price(event, queries, table) for table in ("SEP", "SFP")}
        statuses = {p["status"] for p in prices.values()}
        outcome = (
            "price_observed"
            if "observed" in statuses
            else "ambiguous"
            if "ambiguous" in statuses
            else "unknown"
            if "unknown" in statuses
            else "absent"
        )
        counts[event["cohort"]].update(("events", outcome))
        enriched.append(
            {
                **event,
                "identity_verified": False,
                "prices": prices,
                "master_candidates": _candidates(event["symbol"], master),
            }
        )
    clocks = {
        "asof": captured["asof"],
        "capture_sha256": capture_hash,
        "historical_known_at": None,
        "survivor_only": True,
        "pit_verified": False,
    }
    probes = {
        symbol: {
            "master_candidates": _candidates(symbol, master),
            "action_candidates": [
                r for r in actions if symbol in {r.get("ticker"), r.get("contraticker")}
            ],
            "identity_verified": False,
        }
        for symbol in PROBED_EXITS
    }
    result: dict[str, Any] = {
        **clocks,
        "scope": "literal_symbol_daily_coverage_only",
        "capture_mode": captured["mode"],
        "seed_sha256": seed_sha256,
        "client": captured["client"],
        "implementation_sha": captured["implementation_sha"],
        "implementation_source_sha256": captured["implementation_source_sha256"],
        "transport_source_sha256": captured["transport_source_sha256"],
        "report_source_sha256": seed._sha(Path(__file__).read_bytes()),
        "tables": tables,
        "seed_coverage": {
            cohort: {
                key: values[key]
                for key in ("events", "price_observed", "absent", "unknown", "ambiguous")
            }
            for cohort, values in sorted(counts.items())
        },
        "dated_universe": {
            "status": "UNVERIFIED",
            "rows": len(master),
            "delisted_rows": sum(r.get("isdelisted") == "Y" for r in master),
            "table_rows": dict(Counter(str(r.get("table")) for r in master)),
            "first_price_is_listing_date": False,
            "known_at_semantics": "current receipt only; economic dates are not knowledge clocks",
        },
        "float_history": {
            "status": "UNVERIFIED",
            "shares_outstanding_is_float": False,
            "candidate_columns": {
                t: [c for c in tables[t]["columns"] if "float" in c.lower()] for t in TABLES
            },
            "reason": "Schemas do not establish PIT float definitions, coverage or clocks",
        },
        "ten_probed_exits": probes,
        "probe_source_commit": PROBE_PIN,
        "acceptance": {
            "ten_exit_identities": "NOT_RUN",
            "independent_delisted_sample": {
                "status": "NOT_RUN",
                "minimum_coverage": "0.95",
                "sample_sha256": None,
                "denominator": None,
                "covered": None,
            },
            "recycled_ticker_asof": "NOT_RUN",
            "replacement_backtest": "NOT_RUN",
            "rights": "API access does not establish transferred licence/scope",
        },
        "ordinary_control_count": None,
        "pre_ignition_label_count": None,
        "trial_accounting": {
            "new_strategy_trials": 0,
            "cumulative_n": None,
            "ledger_binding": None,
            "inference_eligible": False,
        },
    }
    files = {
        "universe_manifest.json": seed._json(
            {**clocks, "members": [], "source": "sharadar_coverage"}
        ),
    }
    lines = [json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n" for event in enriched]
    files["events.jsonl"] = "".join(lines).encode()
    for day in calendar if calendar is not None else sorted({e["session_date"] for e in events}):
        selected_lines = [
            line
            for event, line in zip(enriched, lines, strict=True)
            if event["session_date"] == day
        ]
        files[f"sessions/{day}.json"] = seed._json(
            {
                **clocks,
                "session_date": day,
                "event_rows_sha256": seed._sha("".join(selected_lines).encode()),
                "selected_events": len(selected_lines),
                "unselected_is_negative": False,
            }
        )
    result["artifacts"] = {name: seed._sha(body) for name, body in sorted(files.items())}
    files["report.json"] = seed._json(result)
    for name, body in files.items():
        if (output / name).exists() and (output / name).read_bytes() != body:
            raise ValueError("Conflicting immutable report")
    for name, body in files.items():
        seed._publish_once(output / name, body)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "report"))
    parser.add_argument("archive", type=Path)
    parser.add_argument("capture_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--asof", type=datetime.fromisoformat)
    args = parser.parse_args()
    try:
        raw = args.archive.read_bytes()
        if seed._sha(raw) != seed.SEED_SHA256:
            raise ValueError("Seed archive SHA-256 differs from ADR-0027")
        with ZipFile(io.BytesIO(raw)) as archive:
            _, events, calendar = seed._inspect(archive)
        if args.mode == "capture":
            if args.asof is None:
                raise ValueError("Capture requires an explicit timezone-aware --asof")
            root = Path(__file__).resolve().parents[3]
            if subprocess.check_output(
                [
                    "git",
                    "status",
                    "--porcelain",
                    "--",
                    "src/sextant/research",
                    "pyproject.toml",
                    "uv.lock",
                ],
                cwd=root,
            ):
                raise ValueError("Commit the implementation and dependency pins before capture")
            implementation = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip()
            capture(
                events,
                args.capture_root,
                asof=args.asof,
                seed_sha256=seed.SEED_SHA256,
                implementation_sha=implementation,
            )
        elif args.asof is not None:
            raise ValueError("Offline report uses the capture's asof clock")
        result = report(
            events, args.capture_root, args.output, seed_sha256=seed.SEED_SHA256, calendar=calendar
        )
    except Exception:
        parser.exit(2, "Coverage audit failed; no exception text or credential was emitted.\n")
    print(
        json.dumps(
            {
                "scope": result["scope"],
                "capture_mode": result["capture_mode"],
                "seed_coverage": result["seed_coverage"],
                "survivor_only": True,
            }
        )
    )


if __name__ == "__main__":
    main()
