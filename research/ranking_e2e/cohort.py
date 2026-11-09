"""Sealed cohort and session-list identity.

The e2e cohort is the 2026-11-09 bar-close set: 159 movers, 249 controls and
the 4,647-candidate denominator recorded by the e2e-omh replay.  W1's
1,436-session package cannot supply this yet because its PIT universe is empty
(`sharadar-42/report/universe_manifest.json` has ``members: []``).
"""

from __future__ import annotations

import hashlib
import json
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


@dataclass(frozen=True, slots=True)
class Cohort:
    session: date
    prior_sessions: tuple[date, ...]
    candidates: tuple[Candidate, ...]
    truth: tuple[Candidate, ...]
    controls: tuple[Candidate, ...]
    by_symbol: dict[str, Candidate]
    cohort_hash: str

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(candidate.symbol for candidate in self.candidates)


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
                _decimal(row, "move"),
                _decimal(row, "premarket_dollar_volume"),
                _decimal(row, "full_dollar_volume"),
                _decimal(row, "prior_close", optional=True),
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
    return Cohort(
        session,
        prior,
        tuple(candidates),
        truth,
        controls,
        by_symbol,
        hashlib.sha256(raw).hexdigest(),
    )


def session_list_hash(sessions: list[date] | tuple[date, ...]) -> str:
    payload = json.dumps(sorted(day.isoformat() for day in sessions), separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
