"""Row 11 (#73): the replayable catalog, its clocks and the dated universe (ADR-0013).

Most cases are carried from
seathatflowsinourveins/northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:
tests/data/fixtures.py, tests/data/test_catalog.py, tests/data/test_universe.py and
tests/catalysts/test_pit.py. The `asof` replay, revision and determinism witnesses are row 11's own.
Offline: no key, network, stream or order.
"""

import hashlib
import json
from datetime import date, datetime, time, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.models import BarSet
from requests import PreparedRequest, Response
from requests.adapters import HTTPAdapter

from sextant.data.alpaca_history import AlpacaHistory, Pacer, land_raw, nanos, raw_path, read_raw
from sextant.data.catalog import CatalogStore, bar_bytes, bar_type, close_bounds, decode_bars
from sextant.data.pit import alpaca_news_backfill, finra_si_ts, fred_vintage_ts_init, regsho_ts
from sextant.data.universe import (
    DatedUniverse,
    SurvivorUniverse,
    UniverseMember,
    UniverseProvenance,
    manifest_universe,
    report_provenance,
)

NY = ZoneInfo("America/New_York")
HALF_DAY = date(2024, 11, 29)


def payload(day: date = HALF_DAY, *, daily: bool = False) -> dict[str, Any]:
    """Upstream tests/data/fixtures.py, validated by the pinned Alpaca response model."""
    count = 210 if day == HALF_DAY else 390
    start = datetime.combine(day, datetime.min.time(), NY)
    if not daily:
        start += timedelta(hours=9, minutes=30)
    rows = [
        {
            "t": (start + timedelta(minutes=i)).isoformat(),
            "o": 100.125,
            "h": 101.5,
            "l": 99.5,
            "c": 100.25,
            "v": 10 * count if daily else 10,
            "n": count if daily else 1,
            "vw": 100.1875,
        }
        for i in range(1 if daily else count)
    ]
    if not daily:
        rows.append(dict(rows[-1], t=(start + timedelta(minutes=count)).isoformat(), o=100.25))
    result = {"bars": {"AAPL": rows}, "next_page_token": None}
    BarSet(result["bars"])
    return result


def _ingest(root: Path, raw_root: Path, bar: str = "1min") -> tuple[CatalogStore, Path]:
    raw = raw_path(raw_root, bar, "AAPL", HALF_DAY)
    land_raw(raw, (json.dumps(payload(daily=bar == "1day")),), symbol="AAPL", day=HALF_DAY, bar=bar)
    store = CatalogStore(root)
    store.write("AAPL", decode_bars(read_raw(raw), "AAPL", bar), raw_partition=raw)
    return store, raw


def _replay(store: CatalogStore, decision: datetime, bar: str = "1min") -> bytes:
    """An asof=D replay: the session's bars whose known-at time is at or before the decision."""
    start, _ = close_bounds(HALF_DAY, bar)
    bars = store.catalog.query_bars(
        identifiers=[str(bar_type("AAPL", bar))], start=start, end=nanos(decision)
    )
    return bar_bytes(bars)


# --- Clocks -----------------------------------------------------------------------------------


def test_minute_bars_are_known_one_minute_after_they_open_and_daily_at_next_midnight() -> None:
    minute = decode_bars(payload()["bars"]["AAPL"][:1], "AAPL", "1min")[0]
    opened = datetime.combine(HALF_DAY, time(9, 30), NY)
    assert minute.ts_event == minute.ts_init == nanos(opened + timedelta(minutes=1))
    daily = decode_bars(payload(daily=True)["bars"]["AAPL"], "AAPL", "1day")[0]
    midnight = datetime.combine(HALF_DAY + timedelta(days=1), time(0), NY)
    assert daily.ts_event == daily.ts_init == nanos(midnight)


def _utc(text: str) -> int:
    return nanos(datetime.fromisoformat(text.replace("Z", "+00:00")))


def _et(text: str) -> int:
    return nanos(datetime.fromisoformat(text).replace(tzinfo=NY))


@pytest.mark.parametrize(
    ("updated", "visible"),
    [
        ("2026-10-22T13:00:01Z", "2026-10-22T13:06:00Z"),
        ("2026-10-22T13:01:00Z", "2026-10-22T13:06:00Z"),
        ("2026-10-22T13:04:59Z", "2026-10-22T13:07:59Z"),
        ("2026-10-22T13:05:00Z", "2026-10-22T13:08:00Z"),
    ],
)
def test_news_backfill_waits_for_the_next_batch_mark_and_the_minimum_lag(
    updated: str, visible: str
) -> None:
    assert alpaca_news_backfill(_utc(updated)) == _utc(visible)


@pytest.mark.parametrize(
    ("vintage", "visible"),
    [
        (date(2026, 10, 21), "2026-10-22T23:59:59"),
        (date(2026, 11, 25), "2026-11-27T23:59:59"),
        (date(2025, 12, 23), "2025-12-29T23:59:59"),
        (date(2026, 10, 30), "2026-11-02T23:59:59"),
    ],
)
def test_fred_vintage_is_next_business_day_at_235959(vintage: date, visible: str) -> None:
    assert fred_vintage_ts_init(vintage) == _et(visible)


def test_finra_short_interest_is_known_at_publication_and_regsho_at_its_file_time() -> None:
    day = date(2026, 1, 15)
    assert finra_si_ts(day) == _et(f"{day}T16:40:00")
    assert regsho_ts(day) == _et(f"{day}T18:00:00")


# --- Catalog provenance (upstream test_r1_pit03_*) -------------------------------------------


def test_catalog_metadata_records_the_engine_that_writes_it(tmp_path: Path) -> None:
    CatalogStore(tmp_path)
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["nautilus_trader"] == version("nautilus-trader")


def test_a_catalog_from_rc7_requires_reingestion_and_is_not_relabelled(tmp_path: Path) -> None:
    CatalogStore(tmp_path)
    metadata_path = tmp_path / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["nautilus_trader"] = "2.0.0rc7"
    legacy = json.dumps(metadata, indent=2, sort_keys=True).encode()
    metadata_path.write_bytes(legacy)
    with pytest.raises(ValueError, match="re-ingest into a fresh root"):
        CatalogStore(tmp_path)
    assert metadata_path.read_bytes() == legacy


def test_proof_checks_real_bars_and_replays_immutably(tmp_path: Path) -> None:
    store, raw = _ingest(tmp_path / "catalog", tmp_path / "raw")
    proofs = {p: p.read_bytes() for p in (tmp_path / "catalog" / "provenance").rglob("*.json")}
    assert len(proofs) == 1
    proof = json.loads(next(iter(proofs.values())))
    assert proof["source_day"] == proof["asof"] == "2024-11-29" and proof["verified"] is True
    assert proof["raw_sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()
    bars = decode_bars(read_raw(raw), "AAPL", "1min")
    assert store.write("AAPL", bars, raw_partition=raw) == "unchanged"
    assert all(p.read_bytes() == content for p, content in proofs.items())
    wrong = decode_bars([dict(read_raw(raw)[0], c="100.5")], "AAPL", "1min")
    with pytest.raises(ValueError, match=r"raw|proof"):
        CatalogStore(tmp_path / "other").write("AAPL", wrong, raw_partition=raw)


def test_unproven_writes_cannot_claim_asof(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path)
    store.write("AAPL", decode_bars(payload()["bars"]["AAPL"][:1], "AAPL", "1min"))
    proof = json.loads(next((tmp_path / "provenance").rglob("*.json")).read_text())
    assert proof["asof"] is None and proof["verified"] is False


def test_rawless_append_cannot_invalidate_a_proven_day(tmp_path: Path) -> None:
    raw = raw_path(tmp_path / "raw", "1min", "AAPL", HALF_DAY)
    rows = payload()["bars"]["AAPL"][:1]
    land_raw(raw, (json.dumps({"bars": {"AAPL": rows}}),), symbol="AAPL", day=HALF_DAY, bar="1min")
    store = CatalogStore(tmp_path / "catalog")
    store.write("AAPL", decode_bars(rows, "AAPL", "1min"), raw_partition=raw)
    with pytest.raises(ValueError, match=r"provenance|proof"):
        store.write("AAPL", decode_bars(payload()["bars"]["AAPL"][1:2], "AAPL", "1min"))


def test_raw_partitions_record_and_require_the_session_asof(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = raw_path(tmp_path, "1day", "META", date(2021, 12, 1))
    land_raw(path, ('{"bars":{"META":[]}}',), symbol="META", day=date(2021, 12, 1), bar="1day")
    assert pq.read_metadata(path).metadata[b"asof"] == b"2021-12-01"
    legacy = tmp_path / "legacy.parquet"
    table = pq.read_table(path)
    meta = dict(table.schema.metadata or {})
    meta.pop(b"asof")
    pq.write_table(
        pa.Table.from_arrays(table.columns, schema=table.schema.with_metadata(meta)), legacy
    )
    with pytest.raises(ValueError, match="asof"):
        read_raw(legacy)


# --- Row 11's asof witnesses ------------------------------------------------------------------


def test_asof_replay_reads_only_what_was_known_at_the_decision(tmp_path: Path) -> None:
    store, _ = _ingest(tmp_path / "catalog", tmp_path / "raw")
    decision = datetime.combine(HALF_DAY, time(10, 0), NY)
    bars = store.catalog.query_bars(
        identifiers=[str(bar_type("AAPL", "1min"))],
        start=close_bounds(HALF_DAY, "1min")[0],
        end=nanos(decision),
    )
    # 09:30 through 09:59 opened before 10:00, so they are known by 10:00; the 10:00 bar is not.
    assert len(bars) == 30
    assert all(bar.ts_init <= nanos(decision) for bar in bars)


def test_a_later_revision_cannot_change_the_asof_replay(tmp_path: Path) -> None:
    store, raw = _ingest(tmp_path / "catalog", tmp_path / "raw")
    decision = datetime.combine(HALF_DAY, time(13, 0), NY)
    before = _replay(store, decision)
    revised = json.dumps({"bars": {"AAPL": [dict(payload()["bars"]["AAPL"][0], c=200.0)]}})
    # The raw receipt is immutable: a backfill lands nowhere over it.
    assert land_raw(raw, (revised,), symbol="AAPL", day=HALF_DAY, bar="1min") is False
    changed = decode_bars([dict(read_raw(raw)[0], c="200")], "AAPL", "1min")
    with pytest.raises(ValueError, match=r"[Oo]verlap|proof"):
        store.write("AAPL", changed)
    assert _replay(CatalogStore(tmp_path / "catalog"), decision) == before


def test_replay_is_deterministic_across_fresh_catalogs(tmp_path: Path) -> None:
    decision = datetime.combine(HALF_DAY, time(13, 0), NY)
    first, _ = _ingest(tmp_path / "a", tmp_path / "raw")
    second, _ = _ingest(tmp_path / "b", tmp_path / "raw")
    assert _replay(first, decision) == _replay(second, decision) != b""
    proofs = [
        sorted(p.read_bytes() for p in (tmp_path / name / "provenance").rglob("*.json"))
        for name in ("a", "b")
    ]
    assert proofs[0] == proofs[1]


# --- The dated universe -----------------------------------------------------------------------


def test_membership_delisting_rename_and_recycled_symbol() -> None:
    """Upstream test_universe.py: one ticker, two issuers, each on its own dates."""
    rows = [
        UniverseMember(
            "FB", date(2012, 5, 18), date(2022, 6, 8), "rename", "pit-edgar-partial", "meta-common"
        ),
        UniverseMember("META", date(2022, 6, 9), None, None, "pit-edgar-partial", "meta-common"),
        UniverseMember(
            "META", date(2021, 6, 30), date(2022, 1, 30), "rename", "pit-edgar-partial", "roundhill"
        ),
        UniverseMember(
            "SIVB", date(2019, 1, 1), date(2023, 3, 9), "delist", "pit-edgar-partial", "svb-common"
        ),
    ]
    universe = DatedUniverse(
        rows, source="pit-edgar-partial", start=date(2019, 1, 1), end=date(2024, 1, 1)
    )
    selection = universe.universe_for_date(date(2021, 12, 1))
    assert selection.symbols == ("FB", "META", "SIVB")
    assert selection.asof == {"FB": "2021-12-01", "META": "2021-12-01", "SIVB": "2021-12-01"}
    assert next(row for row in selection.members if row.symbol == "META").security_id == "roundhill"
    later = universe.universe_for_date(date(2023, 1, 3))
    assert next(row for row in later.members if row.symbol == "META").security_id == "meta-common"
    assert universe.universe_for_date(date(2023, 3, 10)).symbols == ("META",)
    with pytest.raises(ValueError, match="coverage"):
        universe.universe_for_date(date(2018, 12, 31))
    with pytest.raises(ValueError, match="overlap"):
        DatedUniverse(
            [rows[1], rows[1]],
            source="pit-edgar-partial",
            start=date(2019, 1, 1),
            end=date(2024, 1, 1),
        )


def test_alpaca_asof_selects_the_recycled_tickers_issuer_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upstream test_sdk_asof_selects_recycled_ticker_without_credentials_or_network."""
    queries = []

    def send(adapter: HTTPAdapter, request: PreparedRequest, **kwargs: Any) -> Response:
        query = parse_qs(urlsplit(str(request.url)).query)
        queries.append(query)
        response = Response()
        response.status_code = 200
        response.request = request
        close = 15.47 if query.get("asof") == ["2021-12-01"] else 310.60
        bar = {"t": "2021-12-01T05:00:00Z", "o": close, "h": close, "l": close, "c": close, "v": 1}
        response._content = json.dumps({"bars": {"META": [bar]}, "next_page_token": None}).encode()
        return response

    monkeypatch.setattr(HTTPAdapter, "send", send)
    history = AlpacaHistory.__new__(AlpacaHistory)
    # Inert fixture strings passed straight to upstream; no key store or environment is read.
    StockHistoricalDataClient.__init__(
        history,
        api_key="offline",
        secret_key="offline",  # noqa: S106 - an inert fixture string, as upstream's test
        raw_data=True,
    )
    history.pacer = Pacer()
    history.pages = []
    history._session.hooks["response"].append(history._capture)
    try:
        pages = history.fetch("META", date(2021, 12, 1), "1day")
        assert queries[0]["asof"] == ["2021-12-01"]
        assert json.loads(pages[0])["bars"]["META"][0]["c"] == 15.47
    finally:
        history.close()


def test_every_universe_stays_survivor_only_until_acceptance(tmp_path: Path) -> None:
    for source in ("survivor_only", "sharadar", "pit-edgar-partial"):
        fields = report_provenance({"universe_source": source})
        assert fields["survivor_only"] is True and fields["pit_verified"] is False
    with pytest.raises(ValueError, match="survivor_only"):
        UniverseProvenance("sharadar", date(2016, 1, 1), date(2026, 1, 1), survivor_only=False)
    survivors = SurvivorUniverse(["AAPL"], observed_on=date(2026, 11, 6))
    assert survivors.provenance.report_fields()["survivor_only"] is True


def test_row_4_manifests_load_only_at_their_recorded_hash(tmp_path: Path) -> None:
    manifest = tmp_path / "members.json"
    manifest.write_text(json.dumps({"source": "sharadar", "members": []}))
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    universe = manifest_universe(
        manifest, sha256=digest, start=date(2016, 1, 4), end=date(2026, 1, 2)
    )
    assert universe.universe_for_date(date(2020, 3, 2)).symbols == ()
    assert universe.provenance.survivor_only is True
    with pytest.raises(ValueError, match="sha256"):
        manifest_universe(manifest, sha256="0" * 64, start=date(2016, 1, 4), end=date(2026, 1, 2))
