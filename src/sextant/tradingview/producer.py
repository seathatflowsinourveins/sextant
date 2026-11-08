"""Offline RankingGeneration -> one complete display unit; never orders or OAuth.

Adapted from northstar-trading@8256c16c:scanner/top100.py:3853-3930,
4000-4121; top100_focus.py:650-734,794-909 (immutable unit + latest swap).
Field provenance and deliberately unavailable inputs: docs/tradingview.md.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import mkdtemp
from typing import Any
from uuid import uuid4

from sextant.ranking.generation import (
    CoverageState,
    GenerationStatus,
    RankingGeneration,
    RankingRow,
    generation_digest,
)
from sextant.ranking.publisher import universe_digest
from sextant.tradingview.display_lists import (
    ArmedSet,
    build_display_lists,
    validate_display_contract,
)
from sextant.tradingview.display_support import (
    FLAG_NAMES,
    calendar_time,
    phase,
    qualify_tradingview_symbol,
    timestamp_iso,
    timestamp_ns,
)
from sextant.tradingview.inputs import (
    QUALIFIED,
    TICKER,
    InputError,
    _envelope,
    _session,
    read_research_inputs,
)

METHODS = {"potential/2", "MOVER-v2@00203275944a22655b3e14b221cfde9a265d549a"}
BOUNDARY = (
    "Offline display only; no entry signal, sizing, ticket, orders, broker, OAuth or network."
)


def _json_bytes(doc: Any) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _validation_clock(generated_at: str) -> datetime:
    # The existing consumer accepts datetime (microseconds), not integer clocks.
    # Validate at the first representable instant AT OR AFTER publication; never
    # round a written clock or make the exact source/freshness checks more lenient.
    return calendar_time(timestamp_ns(generated_at) + 999)


def _reason(row: RankingRow, code: str, *, required: bool = False) -> dict[str, Any]:
    values = [reason.detail for reason in row.reasons if reason.code == code]
    if not values and not required:
        return {}
    if len(values) != 1 or values[0] is None:
        raise ValueError(f"{row.symbol}: missing/duplicate {code} provenance")
    value = json.loads(values[0], parse_float=Decimal)
    if not isinstance(value, dict):
        raise ValueError(f"{row.symbol}: malformed {code} provenance")
    return value


def _validate(record: RankingGeneration, generated_at: str) -> dict[str, Any]:
    now = timestamp_ns(generated_at)
    coverage = record.coverage
    count = len(record.rows)
    if (
        record.method_version not in METHODS
        or record.status not in {GenerationStatus.PROVISIONAL, GenerationStatus.SETTLED}
        or coverage.state is not CoverageState.READY
        or not coverage.complete
        or coverage.expected_symbols != count
        or coverage.observed_symbols != count
        or coverage.missing_symbols != 0
        or coverage.invalid_symbols != 0
        or coverage.late_symbols != 0
        or not count
        or not record.ts_event <= record.input_cutoff <= record.known_at <= record.ts_init <= now
        or not 0 <= now - record.input_cutoff < 600_000_000_000
    ):
        raise ValueError("Need a fresh, complete, explicitly sourced ranking generation")
    session, overnight = _session(calendar_time(now))
    if record.session_date.isoformat() != session:
        raise ValueError("Ranking belongs to a different Eastern trading session")
    sources = []
    ranked = []
    for row in record.rows:
        if row.partial or not row.completed or not TICKER.fullmatch(row.symbol):
            raise ValueError("Partial or malformed ranking row")
        if (row.rank is None) != (row.score is None):
            raise ValueError("Ranking rank/score disagree")
        if row.rank is not None:
            ranked.append(row.rank)
        for feature in row.features:
            if (
                feature.partial
                or not feature.completed
                or feature.ts_event is None
                or feature.known_at is None
                or not feature.ts_event <= feature.known_at <= record.input_cutoff
            ):
                raise ValueError("Ranking feature unavailable at the input cutoff")
        source = _reason(row, "SOURCE", required=True)
        if any(
            not source.get(key)
            for key in (
                "session_source",
                "universe_source",
                "baseline_source",
                "params_hash",
                "universe_hash",
                "baseline_hash",
            )
        ):
            raise ValueError("Ranking source identity is incomplete")
        if any(type(source.get(key)) is not int for key in ("start_ns", "end_ns")) or not (
            source["start_ns"] <= record.ts_event <= record.input_cutoff and now < source["end_ns"]
        ):
            raise ValueError("Ranking outside its sourced segment")
        if (
            source.get("feed") != ("boats" if overnight else "sip")
            or source.get("segment") != phase(calendar_time(now)).upper()
        ):
            raise ValueError("Ranking feed/segment differs from the display session")
        sources.append(source)
    if not ranked or ranked != list(range(1, len(ranked) + 1)):
        raise ValueError("Ranking is empty or ranks are not unique/contiguous")
    if any(source != sources[0] for source in sources):
        raise ValueError("Ranking rows mix source generations")
    if sources[0]["universe_hash"] != universe_digest(tuple(row.symbol for row in record.rows)):
        raise ValueError("Ranking rows do not match the sourced full universe")
    return sources[0]


def _symbol_map(mapping: Mapping[str, str]) -> None:
    reverse = set()
    for symbol, qualified in mapping.items():
        if (
            not isinstance(symbol, str)
            or not TICKER.fullmatch(symbol)
            or not isinstance(qualified, str)
            or not QUALIFIED.fullmatch(qualified)
            or qualified.split(":", 1)[0] in {"SMART", "IB", "IBKR", "ALPACA"}
            or qualified in reverse
        ):
            raise ValueError("Need exact, unique, verified TradingView symbol mappings")
        reverse.add(qualified)


def _snapshot_row(row: RankingRow, record: RankingGeneration, mapping: Mapping[str, str]):
    features = {
        feature.name: None if feature.value is None else str(feature.value)
        for feature in row.features
    }
    asset = _reason(row, "ASSET")
    kind = None
    if (
        asset.get("source")
        and type(asset.get("known_at")) is int
        and type(asset.get("expires_at")) is int
        and asset["known_at"] <= record.input_cutoff <= record.ts_init < asset["expires_at"]
    ):
        kind = asset.get("security_type")
    qualified, authority = qualify_tradingview_symbol(row.symbol, None, mapping)
    return {
        "symbol": row.symbol,
        "rank": row.rank,
        "score": str(row.score),
        "weights_version": record.method_version,
        "exchange": None,  # An instrument/routing venue is not a primary listing exchange.
        "tradingview_symbol": qualified,
        "tradingview_symbol_source": authority,
        "coverage": {"security_type": "common_stock" if kind == "common" else kind},
        "inputs": {key: features.get(key) for key in ("price", "previous_close", "rvol")},
        "ranking_features": features,
        "sell_pressure_flags": [
            {"flag": flag, "status": "UNVERIFIED", "source": None} for flag in FLAG_NAMES
        ],
    }


def _candidate(row: dict[str, Any], record: RankingGeneration) -> dict[str, Any]:
    return {
        **{
            key: row[key]
            for key in (
                "symbol",
                "rank",
                "score",
                "tradingview_symbol",
                "tradingview_symbol_source",
                "sell_pressure_flags",
            )
        },
        "adjusted_rank": row["rank"],
        "adjusted_score": row["score"],
        "potential2_rank": row["rank"] if record.method_version == "potential/2" else None,
        "potential2_score": row["score"] if record.method_version == "potential/2" else None,
        "rank_status": "as-of snapshot; incomplete evidence",
        "price": row["inputs"]["price"],
        "price_status": "observed" if row["inputs"]["price"] is not None else "UNVERIFIED",
        "signals": {"rvol": row["inputs"]["rvol"], "gap_pct": None},
        "adjustment_terms": [
            {"term": name, "status": "UNVERIFIED", "points": None}
            for name in ("qualifying_incentive_overlap", *FLAG_NAMES)
        ],
        "catalyst_refs": [],
        "score_breakdown": None,
        "daily_metrics": {"status": "UNVERIFIED", "atr22": None, "high60": None},
        "b_account_notes": [],
        "ticket": None,
        "ticket_unavailable_reason": "display only; no sizing or execution authority",
    }


def build_unit(
    record: RankingGeneration,
    *,
    generated_at: str,
    ranking_path: str = "inputs/ranking.json",
    symbol_map: Mapping[str, str] | None = None,
    armed_sets: Sequence[ArmedSet] = (),
) -> dict[str, dict[str, Any]]:
    """Pure adapter. Unknown close/RVOL/listing/pressure inputs never acquire values."""
    from hashlib import sha256

    source = _validate(record, generated_at)
    mapping = {} if symbol_map is None else symbol_map
    _symbol_map(mapping)
    as_of_snapshot = timestamp_iso(record.input_cutoff)
    rows = [_snapshot_row(row, record, mapping) for row in record.rows if row.rank is not None]
    snapshot = {
        "schema_version": "potential-snapshot/1",
        "weights_version": record.method_version,
        "session_date": record.session_date.isoformat(),
        "session": phase(calendar_time(generated_at)),
        "as_of": as_of_snapshot,
        "generated_at": timestamp_iso(record.ts_init),
        "ranking_generation_sha256": generation_digest(record),
        "symbols": rows,
        "ranking_source": source,
    }
    generation = {"as_of": as_of_snapshot, "sha256": sha256(_json_bytes(snapshot)).hexdigest()}
    common = {
        "session_date": record.session_date.isoformat(),
        "as_of_snapshot": as_of_snapshot,
        "as_of": generated_at,
        "generated_at": generated_at,
        "snapshot_status": "observed",
        "status": "fresh",
        "generation": generation,
        "ranking_context": {
            "session": phase(calendar_time(generated_at)),
            "session_date": record.session_date.isoformat(),
            "intraday_feed": source["feed"],
            "daily_history_feed": "sip",
            "daily_history_scope": "prior completed XNYS sessions; not BOATS intraday evidence",
        },
        "research_inputs": {
            "ranking": {"path": ranking_path, "sha256": generation_digest(record), **source},
            "daily_history": {"feed": "sip", "status": "UNVERIFIED", "path": None},
            "symbol_map": dict(mapping),
        },
    }
    candidates = [_candidate(row, record) for row in rows[:100]]
    policy = {
        "method_version": record.method_version,
        "profile_version": record.profile_version,
        "ranker_version": record.ranker_version,
        "adjustments": "none; preserve source scores/ranks",
    }
    top = {
        "schema": "morning-pack.candidates/1",
        **common,
        "ranking_policy": policy,
        "boundary": BOUNDARY,
        "sizing": {"risk_usd": "OWNER INPUT"},
        "empty_top100": not candidates,
        "candidates": candidates,
    }
    focus = {
        "schema": "top100.focus/1",
        **common,
        "ranking_policy": policy,
        "rule": {"n": 100, "allow_unverified_flags": False, "floors": {}, "exclusions": []},
        "candidates": [],  # top100_focus.py:356-361: all pressure flags remain unknown.
        "excluded": [
            {"symbol": row["symbol"], "reason": "unverified_sell_pressure"} for row in candidates
        ],
        "tradingview_watchlist": {"qualified_symbols": [], "watchlist_txt": ""},
        "warning": BOUNDARY,
    }
    _envelope(top, "morning-pack.candidates/1", _validation_clock(generated_at), 600)
    display = build_display_lists(
        snapshot,
        focus,
        snapshot_path="inputs/display-snapshot.json",
        snapshot_sha256=generation["sha256"],
        generated_at=generated_at,
        armed_sets=armed_sets,
    )
    validate_display_contract(display)
    return {
        "top100.json": top,
        "focus.json": focus,
        "display-lists.json": display,
        "inputs/display-snapshot.json": snapshot,
        "inputs/ranking.json": record.to_dict(),
    }


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(_json_bytes(doc))
        output.flush()
        os.fsync(output.fileno())


def publish_unit(
    record: RankingGeneration,
    root: Path,
    *,
    generated_at: str,
    symbol_map: Mapping[str, str] | None = None,
    armed_sets: Sequence[ArmedSet] = (),
) -> Path:
    """Only advertise after all files pass the existing consumer; old units are immutable."""
    docs = build_unit(
        record, generated_at=generated_at, symbol_map=symbol_map, armed_sets=armed_sets
    )
    root = root.resolve()
    generations = root / ".generations"
    generations.mkdir(parents=True, exist_ok=True)
    directory = Path(mkdtemp(prefix=record.session_date.isoformat() + "-", dir=generations))
    for name, doc in docs.items():
        _write_json(directory / name, doc)
    read_research_inputs(directory, now=_validation_clock(generated_at), max_age=600)
    latest = root / "latest"
    if latest.is_symlink():
        previous = json.loads((latest / "top100.json").read_bytes())
        if timestamp_ns(previous["as_of_snapshot"]) > record.input_cutoff:
            raise ValueError("Refusing to replace newer complete latest with older replay")
    for folder in (directory / "inputs", directory, generations):
        fd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    link = root / (".latest-" + uuid4().hex)
    try:
        link.symlink_to(directory.relative_to(root), target_is_directory=True)
        os.replace(link, latest)
    finally:
        link.unlink(missing_ok=True)
    return directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=BOUNDARY)
    parser.add_argument(
        "--ranking",
        required=True,
        type=Path,
        help="full RankingGeneration canonical JSON, not top-N",
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--symbol-map",
        type=Path,
        help="verified {symbol: EXCHANGE:SYMBOL} JSON; never routing venues",
    )
    parser.add_argument("--generated-at", help="explicit aware replay clock; otherwise current UTC")
    args = parser.parse_args(argv)
    try:
        record = RankingGeneration.from_json(args.ranking.read_bytes())
        mapping = json.loads(args.symbol_map.read_bytes()) if args.symbol_map else None
        if mapping is not None and not isinstance(mapping, dict):
            raise ValueError("Symbol map must be a JSON object")
        directory = publish_unit(
            record,
            args.out,
            generated_at=args.generated_at or datetime.now(UTC).isoformat(),
            symbol_map=mapping,
        )
        display = json.loads((directory / "display-lists.json").read_bytes())
        print(
            json.dumps(
                {
                    "status": "published",
                    "unit": str(directory),
                    "generation": display["generation"],
                    "lists": {
                        name: {
                            "count": display["counts"][key],
                            "as_of": display["as_of"],
                            "generated_at": display["generated_at"],
                        }
                        for name, key in (("NS movers", "ns_movers"), ("NS focus", "ns_focus"))
                    },
                }
            )
        )
        return 0
    except (OSError, ValueError, TypeError, KeyError, InputError) as exc:
        print(
            json.dumps({"status": "unavailable", "reason": str(exc), "ranking": str(args.ranking)})
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
