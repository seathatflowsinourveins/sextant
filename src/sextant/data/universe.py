# Carried from seathatflowsinourveins/northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:
# src/northstar_trading/data/universe.py, the dated-membership core only (ADR-0013).
# Its EDGAR-partial, Sharadar and asset-snapshot providers need northstar's catalysts
# store and are not carried. One change: ADR-0013 keeps `survivor_only: true` until
# acceptance, so no source lifts it here (upstream lifted it for Sharadar). Row 4 (#42)
# supplies member manifests; this module loads one only by its sha256.
"""Dated membership, separate from Alpaca's price/ticker mapping.

Upstream checked: alpaca-py@0.44.0:trading/client.py:get_all_assets (raw_data);
NautilusTrader@2.0.0rc7:persistence/__init__.pyi:309-315,491-498.
None exists: these price/catalog APIs do not reconstruct historical membership.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from .alpaca_history import NY, nanos, symbol_name

# "sharadar_coverage" is row 4's coverage manifest name (#107, research/sharadar_coverage.py).
SOURCES = frozenset({"pit-edgar-partial", "survivor_only", "sharadar", "sharadar_coverage"})


def _known_source(source: str) -> str:
    if source not in SOURCES:
        raise ValueError(f"Unsupported universe source: {source}")
    return source


def report_provenance(metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Every source stays survivor_only and unverified until ADR-0013's acceptance."""
    source = (metadata or {}).get("universe_source") or "survivor_only"
    return {"universe_source": str(source), "survivor_only": True, "pit_verified": False}


@dataclass(frozen=True)
class UniverseMember:
    """Inclusive interval for one dated exchange symbol and one share class.

    A rename is two nonoverlapping rows with the same security_id. Recycled
    tickers have different security_ids; CIK alone is not a share-class id.
    """

    symbol: str
    first_date: date
    last_date: date | None = None
    exit_reason: str | None = None
    source: str = "pit-edgar-partial"
    security_id: str = ""
    security_class: str = ""

    def __post_init__(self) -> None:
        symbol_name(self.symbol)
        _known_source(self.source)
        if not self.security_id:
            raise ValueError("A dated share-class security_id is required")
        if self.last_date is not None and self.last_date < self.first_date:
            raise ValueError("Membership last_date precedes first_date")


@dataclass(frozen=True)
class UniverseProvenance:
    source: str
    coverage_start: date
    coverage_end: date
    survivor_only: bool = True

    def __post_init__(self) -> None:
        _known_source(self.source)
        if self.coverage_start > self.coverage_end:
            raise ValueError("Universe coverage must be valid")
        if not self.survivor_only:
            raise ValueError("No accepted dated master: the universe must stay survivor_only")

    def report_fields(self) -> dict[str, Any]:
        return {
            **report_provenance({"universe_source": self.source}),
            "universe_coverage_start": self.coverage_start.isoformat(),
            "universe_coverage_end": self.coverage_end.isoformat(),
        }


@dataclass(frozen=True)
class UniverseSelection:
    day: date
    members: tuple[UniverseMember, ...]
    provenance: UniverseProvenance

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(row.symbol for row in self.members)

    @property
    def asof(self) -> dict[str, str]:
        return dict.fromkeys(self.symbols, self.day.isoformat())


def _session_cutoff(day: date, cutoff: datetime | None) -> int:
    """Default to the regular open; callers replaying another session supply its cutoff."""
    cutoff = cutoff if cutoff is not None else datetime.combine(day, time(9, 30), NY)
    if cutoff.tzinfo is None or cutoff.astimezone(NY).date() != day:
        raise ValueError(
            "Universe cutoff must be timezone-aware and on the requested New York date"
        )
    return nanos(cutoff)


class DatedUniverse:
    """Query explicit dated evidence; never infer membership from observed prices."""

    def __init__(
        self, members: Sequence[UniverseMember], *, source: str, start: date, end: date
    ) -> None:
        _known_source(source)
        if start > end:
            raise ValueError("Invalid universe coverage window")
        self.provenance = UniverseProvenance(source, start, end)
        self.members = tuple(sorted(members, key=lambda row: (row.symbol, row.first_date)))
        # Check both symbol collisions and share-class overlap, without quadratic
        # comparison over the whole market. Adjacent intervals suffice per key.
        for attribute in ("symbol", "security_id"):
            previous: dict[str, UniverseMember] = {}
            for row in sorted(self.members, key=lambda item: item.first_date):
                if row.source != source:
                    raise ValueError("Membership source differs from provider")
                key = getattr(row, attribute)
                before = previous.get(key)
                if before and (before.last_date is None or before.last_date >= row.first_date):
                    raise ValueError(f"Membership overlap for {attribute} {key}")
                previous[key] = row

    def universe_for_date(self, day: date, *, cutoff: datetime | None = None) -> UniverseSelection:
        _session_cutoff(day, cutoff)
        if not self.provenance.coverage_start <= day <= self.provenance.coverage_end:
            raise ValueError(f"Date {day} outside universe coverage")
        members = tuple(
            row
            for row in self.members
            if row.first_date <= day and (row.last_date is None or day <= row.last_date)
        )
        return UniverseSelection(day, members, self.provenance)


class SurvivorUniverse(DatedUniverse):
    """Explicitly biased fallback: today's supplied list projected backward."""

    def __init__(self, symbols: Sequence[str], *, observed_on: date) -> None:
        rows = [
            UniverseMember(
                symbol,
                date.min,
                observed_on,
                source="survivor_only",
                security_id=f"unverified:{symbol}",
            )
            for symbol in sorted(set(symbols))
        ]
        super().__init__(rows, source="survivor_only", start=date.min, end=observed_on)


def manifest_universe(path: Path, *, sha256: str, start: date, end: date) -> DatedUniverse:
    """Row 4's member manifest, admitted only at the hash its receipt names (#42)."""
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != sha256:
        raise ValueError(f"Member manifest does not match its recorded sha256: {path}")
    manifest = json.loads(body)
    rows = [
        UniverseMember(
            row["symbol"],
            date.fromisoformat(row["first_date"]),
            None if row["last_date"] is None else date.fromisoformat(row["last_date"]),
            row["exit_reason"],
            row["source"],
            row["security_id"],
            row["security_class"],
        )
        for row in manifest["members"]
    ]
    return DatedUniverse(rows, source=manifest["source"], start=start, end=end)
