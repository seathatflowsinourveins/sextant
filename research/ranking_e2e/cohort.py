"""Sealed cohort and session-list identity.

The e2e cohort is the 2026-11-09 bar-close set: 159 movers, 249 controls and
the 4,647-candidate denominator recorded by the e2e-omh replay.  It carries
``survivor_only``, ``pit_verified`` and ``inference_eligible`` labels verbatim:
the candidate list is not a dated PIT membership, so a W1/K2 run remains
NOT_RUN until that receipt exists.  A candidate whose official prior-day close
is missing keeps ``prior_close: null`` and is excluded with a counted reason;
no fallback close is accepted (K2 section 2).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

SCHEMA = "ranking-e2e.cohort/1"


@dataclass(frozen=True, slots=True)
class Candidate:
    symbol: str
    move: Decimal
    premarket_dollar_volume: Decimal
    full_dollar_volume: Decimal
    prior_close: Decimal | None
    prior_close_source: str = "unspecified"


@dataclass(frozen=True, slots=True)
class Cohort:
    session: date
    prior_sessions: tuple[date, ...]
    candidates: tuple[Candidate, ...]
    truth: tuple[Candidate, ...]
    controls: tuple[Candidate, ...]
    by_symbol: dict[str, Candidate]
    cohort_hash: str
    labels: Mapping[str, object]
    excluded: tuple[Mapping[str, object], ...] = ()
    counts: Mapping[str, object] | None = None

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(candidate.symbol for candidate in self.candidates)


def _required_decimal(row: dict[str, Any], key: str) -> Decimal:
    value = _decimal(row, key)
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def _decimal(row: dict[str, Any], key: str, *, optional: bool = False) -> Decimal | None:
    value = row.get(key)
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a decimal string, never a float")
    parsed = Decimal(value)
    if not parsed.is_finite():
        raise ValueError(f"{key} must be finite")
    return parsed


def load_cohort(path: Path) -> Cohort:
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    if data.get("schema") != SCHEMA:
        raise ValueError(f"unsupported cohort schema: {data.get('schema')!r}")
    session = date.fromisoformat(data["session"])
    prior = tuple(sorted(date.fromisoformat(day) for day in data["prior_sessions"]))
    if not prior or prior[-1] >= session:
        raise ValueError("prior sessions must be complete and before the session")
    labels = data.get("labels")
    if not isinstance(labels, Mapping):
        raise ValueError(
            "cohort labels are required (survivor_only/pit_verified/inference_eligible)"
        )
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for row in data["candidates"]:
        symbol = row["symbol"]
        if not symbol or symbol in seen:
            raise ValueError(f"duplicate or empty symbol: {symbol!r}")
        seen.add(symbol)
        candidates.append(
            Candidate(
                symbol,
                _required_decimal(row, "move"),
                _required_decimal(row, "premarket_dollar_volume"),
                _required_decimal(row, "full_dollar_volume"),
                _decimal(row, "prior_close", optional=True),
                str(row.get("prior_close_source", "unspecified")),
            )
        )
    by_symbol = {candidate.symbol: candidate for candidate in candidates}

    def rows(name: str) -> tuple[Candidate, ...]:
        out = []
        for symbol in data[name]:
            if symbol not in by_symbol:
                raise ValueError(f"{name} symbol absent from candidates: {symbol}")
            out.append(by_symbol[symbol])
        if len({row.symbol for row in out}) != len(out):
            raise ValueError(f"duplicate {name} symbol")
        return tuple(out)

    truth, controls = rows("truth"), rows("controls")
    if {row.symbol for row in truth} & {row.symbol for row in controls}:
        raise ValueError("truth and controls must be disjoint")
    for row in (*truth, *controls):
        if row.prior_close is None:
            raise ValueError(f"{row.symbol}: sealed truth/control has no prior close")
    return Cohort(
        session,
        prior,
        tuple(candidates),
        truth,
        controls,
        by_symbol,
        hashlib.sha256(raw).hexdigest(),
        labels,
        tuple(data.get("excluded", ())),
        data.get("counts"),
    )


def session_list_hash(sessions: list[date] | tuple[date, ...]) -> str:
    payload = json.dumps(sorted(day.isoformat() for day in sessions), separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
