"""Pure, display-only projection of one scanner generation; never an entry gate.

Contract: northstar-trading@d957d8e9a791f470b6085861a10726dd939bdea1:
docs/research/2026-11-02-ns-display-lists-contract.md:19-55.
Reuse northstar-trading@d94292fba914c9c19df7582e7b42575bb9da5522:
scanner/top100.py:2483-2510 (mapping), scanner/engine.py:69-73 (phase),
strategies/premarket_gap/scanner.py:470-483 (refresh journal), :212-213 (RVOL).
The pinned producer emits coverage.security_type as a string (potential2.py:1092);
the contract's nested .type spelling is also accepted, never inferred from names.
No upstream SDK supplies this house projection; existing SDK/network paths are unchanged.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sextant.tradingview.display_support import (
    FLAG_NAMES,
    calendar_time,
    dec,
    phase,
    qualify_tradingview_symbol,
    timestamp_iso,
    timestamp_ns,
)

SCHEMA = "ns-display-lists/1"
GAP_BOUND = Decimal("0.05")
RVOL_BOUND = Decimal(2)
MAX_AGE_S = 600


@dataclass(frozen=True)
class ArmedSet:
    """Captured journal bytes decoded once by the I/O boundary; None means unavailable."""

    arm_id: str
    path: str
    text: str | None


def validate_bounds(gap_bound: Decimal, rvol_bound: Decimal, max_age_s: int) -> None:
    if any(dec(value) is None or Decimal(str(value)) <= 0 for value in (gap_bound, rvol_bound)):
        raise ValueError("display bounds must be positive finite decimals")
    if type(max_age_s) is not int or max_age_s <= 0:
        raise ValueError("display armed-set max age must be a positive integer")


def _rows(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = snapshot.get("symbols")
    if isinstance(raw, Mapping):
        rows = [dict(value, symbol=name) for name, value in raw.items()]
    elif isinstance(raw, list):
        rows = [dict(value) for value in raw]
    else:
        raise ValueError("display snapshot requires symbol rows")
    if any(
        not isinstance(row.get("symbol"), str)
        or type(row.get("rank")) is not int
        or row["rank"] < 1
        or row.get("weights_version", "potential/2") not in {
            "potential/2", "MOVER-v2@00203275944a22655b3e14b221cfde9a265d549a"
        }
        for row in rows
    ):
        raise ValueError("display requires potential/2 ranked rows")
    # Explicit ranks, not a top100 candidate limit or incidental JSON key order.
    return sorted(rows, key=lambda row: (row["rank"], row["symbol"]))


def _eligible(row: Mapping[str, Any]) -> bool:
    kind = row.get("coverage", {}).get("security_type")
    kind = kind.get("type") if isinstance(kind, Mapping) else kind
    return kind in {"common_stock", "adr"}


def _pressure_unknown(row: Mapping[str, Any]) -> bool:
    flags = row.get("sell_pressure_flags")
    if not isinstance(flags, list):
        return True
    statuses = {flag.get("flag"): flag.get("status") for flag in flags if isinstance(flag, Mapping)}
    return any(statuses.get(name) not in {"absent", "present"} for name in FLAG_NAMES)


def _member(row: Mapping[str, Any], labels: list[str]) -> dict[str, Any]:
    symbol = row["symbol"]
    qualified = row.get("tradingview_symbol")
    if qualified is None:
        qualified, _ = qualify_tradingview_symbol(symbol, row)
    return {"symbol": symbol, "tradingview_symbol": qualified, "labels": list(labels)}


def _append(members: dict[str, dict[str, Any]], row: Mapping[str, Any], labels: list[str]) -> None:
    item = members.setdefault(row["symbol"], _member(row, []))
    for label in labels:
        if label not in item["labels"]:
            item["labels"].append(label)


def _armed(
    source: ArmedSet, generation: Mapping[str, Any], now_ns: int, max_age_s: int
) -> tuple[dict, list[str]]:
    provenance: dict[str, Any] = {
        "arm_id": source.arm_id,
        "path": source.path,
        "as_of": None,
        "status": "UNVERIFIED",
    }
    try:
        if source.text is None:
            return provenance, []
        latest = None
        for line in source.text.splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("invalid journal record")
            if record.get("kind") == "premarket_gap_scanner_refresh":
                latest = record
        if latest is None or latest.get("version") != 1 or type(latest.get("ts_event")) is not int:
            return provenance, []
        at = latest["ts_event"]
        at_dt = calendar_time(at)
        provenance["as_of"] = timestamp_iso(at)
        if (
            not 0 <= now_ns - at <= max_age_s * 1_000_000_000
            or latest.get("snapshot_reason") != "fresh"
            or not isinstance(latest.get("snapshot_as_of"), str)
            or timestamp_ns(latest["snapshot_as_of"]) != timestamp_ns(generation["as_of"])
        ):
            return provenance, []
        armed = latest.get("armed")
        if not isinstance(armed, list) or any(
            not isinstance(iid, str) or not iid.endswith(".ALPACA") or not iid.removesuffix(".ALPACA")
            for iid in armed
        ):
            return provenance, []
        provenance.update(status="observed", phase=phase(at_dt))
        return provenance, list(dict.fromkeys(iid.removesuffix(".ALPACA") for iid in armed))
    except (ValueError, TypeError, OverflowError):
        return provenance, []


def build_display_lists(
    snapshot: Mapping[str, Any] | None,
    focus: Mapping[str, Any],
    *,
    snapshot_path: str,
    snapshot_sha256: str | None,
    generated_at: str,
    gap_bound: Decimal = GAP_BOUND,
    rvol_bound: Decimal = RVOL_BOUND,
    max_age_s: int = MAX_AGE_S,
    armed_sets: Sequence[ArmedSet] = (),
) -> dict[str, Any]:
    """No filesystem/clock access or input mutation; both lists use all snapshot rows.

    A missing/stale/mixed arm invalidates the entire armed portion, not the focus
    fallback. A stale unit is explicitly empty/stale, never populated from last_valid.
    """
    validate_bounds(gap_bound, rvol_bound, max_age_s)
    gap_bound, rvol_bound = Decimal(str(gap_bound)), Decimal(str(rvol_bound))
    now_ns = timestamp_ns(generated_at)
    stale = focus.get("status") == "stale"
    generation = {"as_of": focus.get("as_of_snapshot"), "sha256": snapshot_sha256}
    if not stale and (
        snapshot is None
        or snapshot.get("weights_version") not in {
            "potential/2", "MOVER-v2@00203275944a22655b3e14b221cfde9a265d549a"
        }
        or snapshot.get("session_date") != focus.get("session_date")
        or not isinstance(snapshot.get("as_of"), str)
        or timestamp_ns(snapshot["as_of"]) != timestamp_ns(generation["as_of"])
        or timestamp_ns(focus["generated_at"]) != now_ns
        or not isinstance(snapshot_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", snapshot_sha256) is None
    ):
        raise ValueError("display snapshot/focus generation differs")
    rows = [] if stale or snapshot is None else _rows(snapshot)
    by_symbol = {row["symbol"]: row for row in rows}
    movers: dict[str, dict[str, Any]] = {}
    eligible = [row for row in rows if _eligible(row)]
    for row in eligible:
        if row["symbol"] not in movers:
            _append(movers, row, [f"early:{row['rank']}"])
        if len(movers) == 50:
            break
    extremes = []
    unknown = 0
    for row in eligible:
        inputs = row.get("inputs", {})
        price, previous, rvol = (dec(inputs.get(key)) for key in ("price", "previous_close", "rvol"))
        if price is None or previous is None or rvol is None:
            unknown += 1
            continue
        if min(price, previous) <= 0 or rvol < rvol_bound:
            continue
        move = price / previous - 1
        activity = row.get("coverage", {}).get("session_relative") or {}
        session_return = dec(activity.get("session_return"))
        if session_return is not None:
            move = max(move, session_return)
        if move >= gap_bound:
            extremes.append((move, row))
    extremes.sort(key=lambda item: (-item[0], item[1]["symbol"]))
    for move, row in extremes[:50]:
        threshold = next((n for n in (20, 10, 5) if move >= Decimal(n) / 100), gap_bound * 100)
        _append(movers, row, [f"extreme:≥{threshold}%"])
    sources_and_names = [_armed(source, generation, now_ns, max_age_s) for source in armed_sets]
    armed_ok = (
        not stale
        and bool(armed_sets)
        and all(source["status"] == "observed" for source, _ in sources_and_names)
    )
    focused: dict[str, dict[str, Any]] = {}
    focus_rows = [] if stale else focus["candidates"]
    focus_by_symbol = {row["symbol"]: row for row in focus_rows}
    if armed_ok:
        for source, names in sources_and_names:
            for symbol in names:
                row = focus_by_symbol.get(symbol, by_symbol.get(symbol, {"symbol": symbol}))
                labels = [f"arm:{source['arm_id']}", f"phase:{source['phase']}"]
                if _pressure_unknown(row):
                    labels.append("sell_pressure:UNVERIFIED")
                _append(focused, row, labels)
    for row in focus_rows:
        labels = [f"phase:{phase(datetime.fromisoformat(generated_at))}"]
        if _pressure_unknown(row):
            labels.append("sell_pressure:UNVERIFIED")
        _append(focused, row, labels)
    return {
        "schema": SCHEMA,
        **{key: focus.get(key) for key in ("session_date", "as_of", "as_of_snapshot", "snapshot_status")},
        **(
            {key: copy.deepcopy(focus[key]) for key in ("ranking_context", "research_inputs")}
            if "ranking_context" in focus and "research_inputs" in focus
            else {}
        ),
        "status": "stale" if stale else "fresh",
        "generation": generation,
        "generated_at": generated_at,
        "bounds": {"gap_bound": str(gap_bound), "rvol_bound": str(rvol_bound), "max_age_s": max_age_s},
        "counts": {"ns_movers": len(movers), "ns_focus": len(focused)},
        "excluded_unknown": unknown,
        "armed": "observed" if armed_ok else "UNVERIFIED",
        "sources": {
            "snapshot": {"path": snapshot_path, **generation},
            "armed_sets": [source for source, _ in sources_and_names],
        },
        "ns_movers": list(movers.values()),
        "ns_focus": list(focused.values()),
    }


def validate_display_contract(doc: Mapping[str, Any]) -> None:
    """Validate display shape; the consumer additionally binds it to the selected unit."""
    if doc.get("schema") != SCHEMA or doc.get("status") not in {"fresh", "stale"}:
        raise ValueError("invalid display schema/status")
    bounds = doc["bounds"]
    validate_bounds(bounds["gap_bound"], bounds["rvol_bound"], bounds["max_age_s"])
    generation = doc["generation"]
    if (
        not isinstance(generation, Mapping)
        or set(generation) != {"as_of", "sha256"}
        or not isinstance(generation["sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", generation["sha256"]) is None
        or timestamp_ns(generation["as_of"]) != timestamp_ns(doc["as_of_snapshot"])
        or any(doc["sources"]["snapshot"].get(key) != value for key, value in generation.items())
    ):
        raise ValueError("invalid display snapshot generation")
    if (
        doc.get("armed") not in {"observed", "UNVERIFIED"}
        or type(doc.get("excluded_unknown")) is not int
        or doc["excluded_unknown"] < 0
    ):
        raise ValueError("invalid display coverage")
    for name in ("ns_movers", "ns_focus"):
        rows = doc[name]
        if not isinstance(rows, list) or (name == "ns_movers" and len(rows) > 100):
            raise ValueError("invalid display list size")
        if type(doc["counts"].get(name)) is not int or doc["counts"][name] != len(rows):
            raise ValueError("display counts differ")
        if any(
            not isinstance(row, Mapping)
            or not isinstance(row.get("labels"), list)
            or not row["labels"]
            or any(not isinstance(label, str) or not label for label in row["labels"])
            for row in rows
        ):
            raise ValueError("display members require labels")
