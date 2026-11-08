# Carried from seathatflowsinourveins/northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:
# src/northstar_trading/data/catalog.py; force-verify variable renamed (ADR-0013).
# rc8 adaptation: nautilus_trader@d53849b216e20f2c122ca01b4dd0da377638b186,
# docs/concepts/backtesting/apis-and-runs.md (DataCatalogConfig); metadata names the pinned engine.
"""Decode against the engine's exported Arrow schema and use its typed catalog API."""

import hashlib
import json
import os
from bisect import bisect_right, insort
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.model import (
    Bar,
    BarType,
    Currency,
    Equity,
    InstrumentId,
    NautilusDataType,
    Price,
    Quantity,
    Symbol,
)
from nautilus_trader.persistence import BarDataWrangler, ParquetDataCatalog
from nautilus_trader.serialization import bars_to_arrow_record_batch_bytes, get_arrow_schema_bytes

from .alpaca_history import (
    NY,
    RawBar,
    day_start,
    decimal_value,
    nanos,
    publish_once,
    read_raw,
    symbol_name,
    timestamp,
)

PRICE_PRECISION = 9
SIZE_PRECISION = 0
DAY_NANOS = 86400 * 1_000_000_000
CATALOG_METADATA = {
    "source": "alpaca_sip",
    "feed": "sip",
    "adjustment": "raw",
    "currency": "USD",
    "nautilus_trader": "2.0.0rc8",
    "alpaca_py": "0.44.0",
    "minute_known_at": "source timestamp + 1 minute",
    "daily_known_at": "next America/New_York midnight (conservative full-source-day close)",
    "price_precision": PRICE_PRECISION,
    "size_precision": SIZE_PRECISION,
    "instrument": "synthetic ALPACA data venue, not an execution/security-master definition",
    "asof_policy": "per-partition-raw-proof-v1",
    "provenance": {"version": 1, "path": "provenance/", "unproven_asof": None},
}


def bar_type(symbol: str, bar: str) -> BarType:
    if bar not in ("1min", "1day"):
        raise ValueError(f"Unsupported bar interval: {bar}")
    spec = "1-MINUTE" if bar == "1min" else "1-DAY"
    return BarType.from_str(f"{symbol_name(symbol)}.ALPACA-{spec}-LAST-EXTERNAL")


def equity(symbol: str) -> Equity:
    return Equity(
        instrument_id=InstrumentId.from_str(f"{symbol_name(symbol)}.ALPACA"),
        raw_symbol=Symbol(symbol),
        currency=Currency.from_str("USD"),
        price_precision=PRICE_PRECISION,
        price_increment=Price.from_str("0.000000001"),
        lot_size=Quantity.from_int(1),
        ts_event=0,
        ts_init=0,
        info={"source": "alpaca_sip", "synthetic_data_definition": True},
    )


def close_bounds(day: date, bar: str) -> tuple[int, int]:
    following = nanos(day_start(day + timedelta(days=1)))
    if bar == "1day":
        return following, following
    return nanos(day_start(day)) + 60 * 1_000_000_000, following


def decode_bars(rows: Sequence[RawBar], symbol: str, bar: str) -> list[Bar]:
    """Map vendor columns into the *upstream* Decimal128 Arrow schema.

    Raw response numbers are decoded as Decimal, never through pandas/f64.
    Daily bars are held until the full New York source date ends; using the
    regular-session close could leak extended-hours trades from that response.
    """
    if not rows:
        return []
    kind = bar_type(symbol, bar)
    records = []
    for row in rows:
        start = timestamp(row["t"])
        known = (
            start + timedelta(minutes=1)
            if bar == "1min"
            else day_start(start.astimezone(NY).date() + timedelta(days=1))
        )
        record = {
            key: decimal_value(row[vendor])
            for key, vendor in (
                ("open", "o"),
                ("high", "h"),
                ("low", "l"),
                ("close", "c"),
                ("volume", "v"),
            )
        }
        for key, value in record.items():
            precision = SIZE_PRECISION if key == "volume" else PRICE_PRECISION
            if not value.is_finite() or value != value.quantize(Decimal(1).scaleb(-precision)):
                raise ValueError(f"{symbol} {row['t']}: {key} is not losslessly representable")
        records.append(
            {**record, "ts_event": nanos(known), "ts_init": nanos(known), "identifier": str(kind)}
        )
    schema = pa.ipc.read_schema(pa.BufferReader(get_arrow_schema_bytes(Bar)))
    table = pa.Table.from_pylist(records, schema=schema)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return BarDataWrangler(str(kind), PRICE_PRECISION, SIZE_PRECISION).process_record_batch_bytes(
        sink.getvalue().to_pybytes()
    )


def bar_bytes(bars: Sequence[Bar]) -> bytes:
    """Canonical upstream Arrow encoding, including fixed-point and timestamps."""
    return bars_to_arrow_record_batch_bytes(bars) if bars else b""


class CatalogStore:
    def __init__(self, root: Path, *, cache_intervals: bool = False) -> None:
        root.mkdir(parents=True, exist_ok=True)
        metadata_path = root / "metadata.json"
        if not metadata_path.exists() and any((root / "data").rglob("*.parquet")):
            raise ValueError(
                "Cannot label an existing catalog with unknown adjustment/source or asof proof; "
                "re-ingest into a fresh root"
            )
        body = json.dumps(CATALOG_METADATA, indent=2, sort_keys=True).encode()
        publish_once(metadata_path, lambda target: target.write_bytes(body))
        if json.loads(metadata_path.read_text()) != CATALOG_METADATA:
            raise ValueError(
                "Catalog metadata conflicts or lacks asof proof; re-ingest into a fresh root"
            )
        self.root = root
        self.catalog = ParquetDataCatalog(str(root.resolve()))
        # Only ingest owns a run-scoped snapshot; other callers read live metadata.
        self._interval_cache: dict[str, tuple[list[tuple[int, int]], bool]] | None = (
            {} if cache_intervals else None
        )

    def _intervals(self, kind: str) -> tuple[list[tuple[int, int]], bool]:
        if self._interval_cache is not None and kind in self._interval_cache:
            return self._interval_cache[kind]
        intervals = self.catalog.get_intervals(NautilusDataType.Bar, kind)
        # rc7 returns sorted closed intervals; interrupted consolidation can overlap.
        snapshot = intervals, all(left[1] < right[0] for left, right in pairwise(intervals))
        if self._interval_cache is not None:
            self._interval_cache[kind] = snapshot
        return snapshot

    @staticmethod
    def _covers(intervals: list[tuple[int, int]], start: int, end: int) -> bool:
        index = bisect_right(intervals, (start, 1 << 64)) - 1
        return index >= 0 and end <= intervals[index][1]

    def _can_resume(
        self, symbol: str, bars: Sequence[Bar], raw: Path | None, intervals: list[tuple[int, int]]
    ) -> bool:
        if raw is None or os.environ.get("SEXTANT_CATALOG_FORCE_FULL_VERIFY") == "1":
            return False
        if not self._covers(intervals, bars[0].ts_init, bars[-1].ts_init):
            return False
        try:
            meta = pq.read_metadata(raw).metadata or {}
            day = date.fromisoformat(meta[b"date"].decode())
            bar = meta[b"bar"].decode()
            if (
                meta.get(b"source") != b"alpaca_sip"
                or meta.get(b"symbol") != symbol.encode()
                or meta.get(b"feed") != b"sip"
                or meta.get(b"adjustment") != b"raw"
                or bars[0].bar_type != bar_type(symbol, bar)
            ):
                return False
            path = self.root / "provenance" / bar / symbol / f"{day.isoformat()}.json"
            proof = json.loads(path.read_text())
            with raw.open("rb") as handle:
                raw_hash = hashlib.file_digest(handle, "sha256").hexdigest()
            return proof == {
                "version": 1,
                "symbol": symbol,
                "bar": bar,
                "source_day": day.isoformat(),
                "asof": meta[b"asof"].decode(),
                "raw_identity": f"alpaca_sip/{bar}/{symbol}/{day.isoformat()}.parquet",
                "raw_sha256": raw_hash,
                "verified": True,
                "count": len(bars),
                "start_ns": bars[0].ts_init,
                "end_ns": bars[-1].ts_init,
                "bars_sha256": hashlib.sha256(bar_bytes(bars)).hexdigest(),
                "catalog_verified": True,
            }
        except (OSError, ValueError, KeyError, UnicodeError, pa.ArrowException):
            return False  # Fall back to every original raw/source-day/catalog check.

    def _partition_proof(
        self,
        symbol: str,
        bars: Sequence[Bar],
        raw_partition: Path | None,
    ) -> tuple[Path, dict[str, Any]]:
        """Tie the asof to the immutable raw envelope and the exact typed bars.

        No upstream catalog API supplies request provenance. Reuse the house
        raw envelope and publish_once, leaving typed data to rc7.
        """
        proof: dict[str, Any] = {
            "version": 1,
            "symbol": symbol_name(symbol),
            "asof": None,
            "source_day": None,
            "raw_identity": None,
            "raw_sha256": None,
            "verified": False,
            "count": len(bars),
            "start_ns": bars[0].ts_init if bars else None,
            "end_ns": bars[-1].ts_init if bars else None,
            "bars_sha256": hashlib.sha256(bar_bytes(bars)).hexdigest(),
        }
        if raw_partition is None:
            # Compatibility for synthetic callers is explicit, never a claim
            # that their bars used a session-dated historical request.
            name = f"{proof['start_ns']}-{proof['end_ns']}-{proof['bars_sha256']}.json"
            return self.root / "provenance" / "unverified" / symbol / name, proof
        meta = pq.read_metadata(raw_partition).metadata or {}
        if meta.get(b"source") != b"alpaca_sip" or meta.get(b"symbol") != symbol.encode():
            raise ValueError("Raw proof source/symbol does not match catalog partition")
        day = date.fromisoformat(meta[b"date"].decode())
        bar = meta[b"bar"].decode()
        kind = bar_type(symbol, bar)
        decoded = sorted(
            decode_bars(read_raw(raw_partition), symbol, bar), key=lambda item: item.ts_init
        )
        if any(item.bar_type != kind for item in bars) or bar_bytes(decoded) != bar_bytes(bars):
            raise ValueError("Typed bars differ from the raw partition proof")
        with raw_partition.open("rb") as handle:
            raw_hash = hashlib.file_digest(handle, "sha256").hexdigest()
        proof.update(
            {
                "source_day": day.isoformat(),
                "bar": bar,
                "asof": meta[b"asof"].decode(),
                "raw_identity": f"alpaca_sip/{bar}/{symbol}/{day.isoformat()}.parquet",
                "raw_sha256": raw_hash,
                "verified": True,
            }
        )
        return self.root / "provenance" / bar / symbol / f"{day.isoformat()}.json", proof

    def _publish_proof(self, path: Path, proof: dict[str, Any]) -> None:
        body = json.dumps(proof, indent=2, sort_keys=True).encode()
        publish_once(path, lambda target: target.write_bytes(body))
        if path.read_bytes() == body:
            return
        existing = json.loads(path.read_text())
        if "catalog_verified" not in proof and existing == {**proof, "catalog_verified": True}:
            return
        legacy = {key: value for key, value in proof.items() if key != "catalog_verified"}
        if existing != legacy:
            raise ValueError("Catalog partition provenance conflicts; re-ingest into a fresh root")
        # Old proofs were reserved before write_bars. Upgrade only after a full
        # successful comparison/write, preserving every immutable provenance field.
        with TemporaryDirectory(dir=path.parent, prefix=".proof-upgrade-") as directory:
            completed = Path(directory) / "proof.json"
            publish_once(completed, lambda target: target.write_bytes(body))
            completed.replace(path)

    def _check_proven_partition(self, proof: dict[str, Any], bars: Sequence[Bar]) -> None:
        if proof["verified"]:
            start, end = close_bounds(date.fromisoformat(proof["source_day"]), proof["bar"])
            existing = self.catalog.query_bars(
                identifiers=[str(bar_type(proof["symbol"], proof["bar"]))],
                start=start,
                end=end,
            )
            if existing and bar_bytes(existing) != bar_bytes(bars):
                raise ValueError("Overlapping source-day bars conflict with raw partition proof")

    def write(self, symbol: str, bars: Sequence[Bar], *, raw_partition: Path | None = None) -> str:
        if not bars:
            if raw_partition is not None:
                path, proof = self._partition_proof(symbol, [], raw_partition)
                self._check_proven_partition(proof, [])
                self._publish_proof(path, proof)
            return "empty"
        ordered = sorted(bars, key=lambda item: item.ts_init)
        kind = str(ordered[0].bar_type)
        instrument = equity(symbol)
        if any(
            str(item.bar_type) != kind or item.bar_type.instrument_id != instrument.id
            for item in ordered
        ):
            raise ValueError("One instrument and bar type per typed writer call")
        if len({item.ts_init for item in ordered}) != len(ordered):
            raise ValueError("Duplicate bar timestamps; inspect the completeness report")
        intervals, disjoint = self._intervals(kind)
        if disjoint and self._can_resume(symbol, ordered, raw_partition, intervals):
            return "unchanged"
        proof_path, proof = self._partition_proof(symbol, ordered, raw_partition)
        self._check_proven_partition(proof, ordered)
        start, end = ordered[0].ts_init, ordered[-1].ts_init
        overlaps = any(left <= end and start <= right for left, right in intervals)
        if overlaps:
            existing = self.catalog.query_bars(identifiers=[kind], start=start, end=end)
            if bar_bytes(existing) == bar_bytes(ordered):
                proof["catalog_verified"] = True
                self._publish_proof(proof_path, proof)
                return "unchanged"
            raise ValueError(f"Overlapping catalog write refused: {kind} [{start}, {end}]")
        if raw_partition is None:
            for interval in ("1min", "1day"):
                if kind != str(bar_type(symbol, interval)):
                    continue
                days = {
                    datetime.fromtimestamp((item.ts_init - 1) // 1_000_000_000, NY).date()
                    for item in ordered
                }
                if any(
                    (
                        self.root / "provenance" / interval / symbol / f"{day.isoformat()}.json"
                    ).exists()
                    for day in days
                ):
                    raise ValueError(
                        "Rawless append would invalidate existing source-day provenance proof"
                    )
        if not self.catalog.instruments(instrument_ids=[str(instrument.id)]):
            self.catalog.write_instruments([instrument])
        # Keep the original pre-write provenance reservation, but it is not a
        # resume witness until the post-write catalog_verified upgrade below.
        self._publish_proof(proof_path, proof)
        self.catalog.write_bars(ordered)  # Leave rc7's disjoint-write guard enabled.
        if self._interval_cache is not None:
            insort(intervals, (start, end))
        proof["catalog_verified"] = True
        self._publish_proof(proof_path, proof)
        return "written"
