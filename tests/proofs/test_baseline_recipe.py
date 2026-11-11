"""Witnesses for the one tracked C baseline recipe.

Hand-built minute bars only: no vendor call, no network, no clock.
"""

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from alpaca.data.enums import DataFeed
from nautilus_trader.model import AggressorSide, InstrumentId, Price, Quantity, TradeId, TradeTick
from test_ranking import registry  # the mechanism-only fixture registry

from sextant.data import baseline_recipe as recipe
from sextant.data.baseline_bars import prior_xnys_sessions
from sextant.data.baseline_recipe import (
    RECIPE_SEGMENTS,
    SEGMENT_FILES,
    build,
    main,
    publish,
    render,
    run,
    verify,
)
from sextant.ranking.baseline import BaselineTable, load_baseline
from sextant.ranking.baseline_coverage import coverage_receipt, partition_covered
from sextant.ranking.engine import MoverState, ReferencePrices, Segment, advance_mover, rank_movers

D = Decimal
NS = 1_000_000_000
ET = ZoneInfo("America/New_York")
AS_OF = date(2026, 11, 9)
SESSIONS = (date(2026, 11, 5), date(2026, 11, 6))
SYMBOLS = ("AAPL", "MF")
COMMAND = ["python", "-m", "sextant.data.baseline_recipe"]


def moment(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=ET)


def nanos(value: datetime) -> int:
    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * NS + delta.microseconds * 1_000


KNOWN_AT = nanos(moment(date(2026, 11, 9), 12))


def overnight_rows() -> dict[str, list[dict[str, object]]]:
    rows: dict[str, list[dict[str, object]]] = {}
    for symbol in SYMBOLS:
        bars: list[dict[str, object]] = []
        for day in SESSIONS:
            previous = day - timedelta(days=1)
            for hour, minute in ((20, 0), (20, 30), (23, 59)):
                bars.append({"t": moment(previous, hour, minute), "v": 10, "vw": "2", "n": 1})
            bars.append({"t": moment(day, 3, 59), "v": 10, "vw": "2", "n": 1})
        rows[symbol] = bars
    return rows


def daytime_rows() -> dict[str, list[dict[str, object]]]:
    rows: dict[str, list[dict[str, object]]] = {}
    for symbol in SYMBOLS:
        bars: list[dict[str, object]] = []
        for day in SESSIONS:
            for hour, minute in ((4, 0), (9, 30), (9, 31), (15, 59), (16, 1), (17, 0)):
                bars.append({"t": moment(day, hour, minute), "v": 10, "vw": "2", "n": 1})
        rows[symbol] = bars
    return rows


OVERNIGHT_BARS = overnight_rows()
DAYTIME_BARS = daytime_rows()


class FakeBars:
    """A fake data client: one window of bars per feed, filtered by the request."""

    def __init__(
        self, *, omit: str | None = None, empty: bool = False, fail: DataFeed | None = None
    ) -> None:
        self.omit = omit
        self.empty = empty
        self.fail = fail
        self.requests: list[Any] = []

    def get_stock_bars(self, request: Any) -> dict[str, list[dict[str, object]]]:
        self.requests.append(request)
        if request.feed == self.fail:
            raise RuntimeError("offline batch failed before its last page")
        if self.empty:
            return {}
        requested = request.symbol_or_symbols
        if isinstance(requested, str):
            requested = [requested]
        source = OVERNIGHT_BARS if request.feed == DataFeed.BOATS else DAYTIME_BARS
        rows = {symbol: list(source[symbol]) for symbol in requested}
        if self.omit is not None and request.feed == DataFeed.BOATS:
            rows.pop(self.omit, None)
        return rows


def build_tables() -> dict[str, BaselineTable]:
    return build(FakeBars(), SYMBOLS, as_of=AS_OF, known_at=KNOWN_AT, prior_sessions=2)


def test_the_recipe_writes_one_file_per_segment_with_the_same_schema(tmp_path) -> None:
    out = tmp_path / "baselines"

    run(
        FakeBars(),
        SYMBOLS,
        out,
        command=[*COMMAND, "--out", str(out)],
        as_of=AS_OF,
        known_at=KNOWN_AT,
        prior_sessions=2,
    )

    assert sorted(path.name for path in out.iterdir()) == [
        "manifest.json",
        "overnight.json",
        "post.json",
        "pre.json",
        "rth.json",
    ]
    for name in RECIPE_SEGMENTS:
        payload = json.loads((out / SEGMENT_FILES[name]).read_text())
        assert set(payload) == {"samples", "provenance", "known_at", "feed"}
        loaded = load_baseline((out / SEGMENT_FILES[name]).read_text())
        assert {sample.segment for sample in loaded.samples} == {name}
        assert {sample.symbol for sample in loaded.samples} == set(SYMBOLS)
        assert loaded.known_at == KNOWN_AT
        assert loaded.feed == ("boats" if name == "OVERNIGHT" else "sip")


def test_the_manifest_records_the_run_next_to_the_published_bytes(tmp_path) -> None:
    out = tmp_path / "baselines"

    run(
        FakeBars(),
        SYMBOLS,
        out,
        command=[*COMMAND, "--out", str(out)],
        as_of=AS_OF,
        known_at=KNOWN_AT,
        prior_sessions=2,
    )

    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["command"] == [*COMMAND, "--out", str(out)]
    assert manifest["as_of"] == "2026-11-09"
    assert manifest["known_at"] == KNOWN_AT
    assert manifest["symbols"] == ["AAPL", "MF"]
    assert manifest["window"] == {
        "prior_sessions": 2,
        "first_session": "2026-11-05",
        "last_session": "2026-11-06",
    }
    assert manifest["source"] == "symbols"
    assert manifest["universe"] is None
    for name in RECIPE_SEGMENTS:
        filename = SEGMENT_FILES[name]
        entry = manifest["files"][filename]
        assert entry["segment"] == name
        assert entry["feed"] == ("boats" if name == "OVERNIGHT" else "sip")
        assert entry["sha256"] == hashlib.sha256((out / filename).read_bytes()).hexdigest()
        assert entry["samples"] == len(load_baseline((out / filename).read_text()).samples)
        assert entry["symbols"] == ["AAPL", "MF"]


def test_the_two_fetchers_receive_boats_then_sip(tmp_path) -> None:
    fake = FakeBars()

    run(
        fake,
        SYMBOLS,
        tmp_path / "baselines",
        command=[*COMMAND],
        as_of=AS_OF,
        known_at=KNOWN_AT,
        prior_sessions=2,
    )

    assert [request.feed for request in fake.requests] == [DataFeed.BOATS, DataFeed.SIP]


def test_every_segment_round_trips_through_the_baseline_schema() -> None:
    tables = build_tables()

    texts = render(tables)

    for name in RECIPE_SEGMENTS:
        assert load_baseline(texts[SEGMENT_FILES[name]]).identity == tables[name].identity


def test_verify_refuses_a_segment_file_that_is_missing_a_symbol() -> None:
    tables = build_tables()
    broken = BaselineTable(
        tuple(sample for sample in tables["PRE"].samples if sample.symbol != "MF"),
        tables["PRE"].provenance,
        tables["PRE"].known_at,
        tables["PRE"].feed,
    )

    with pytest.raises(ValueError, match="does not cover"):
        verify({**tables, "PRE": broken}, SYMBOLS)


def test_verify_refuses_a_segment_file_that_holds_two_segments() -> None:
    tables = build_tables()
    mixed = BaselineTable(
        tuple(tables["PRE"].samples + tables["RTH"].samples),
        tables["PRE"].provenance,
        tables["PRE"].known_at,
        tables["PRE"].feed,
    )

    with pytest.raises(ValueError, match="one segment"):
        verify({**tables, "PRE": mixed}, SYMBOLS)


def published(out: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in out.iterdir()}


def publish_fixture(client: Any, out: Path, symbols: Sequence[str], known_at: int = KNOWN_AT):
    return run(
        client, symbols, out, command=COMMAND, as_of=AS_OF, known_at=known_at, prior_sessions=2
    )


@pytest.mark.parametrize("feed", [DataFeed.BOATS, DataFeed.SIP])
def test_a_failed_batch_is_refused_and_keeps_the_previous_files(tmp_path, feed) -> None:
    out = tmp_path / "baselines"
    publish_fixture(FakeBars(), out, SYMBOLS)
    before = published(out)

    with pytest.raises(RuntimeError, match="before its last page"):
        publish_fixture(FakeBars(fail=feed), out, SYMBOLS, KNOWN_AT + 1)

    assert published(out) == before


def test_a_dropped_session_is_refused_before_anything_is_published(tmp_path, monkeypatch) -> None:
    out = tmp_path / "baselines"
    dropped = {
        symbol: [bar for bar in bars if bar["t"].date() != SESSIONS[0]]  # type: ignore[attr-defined]
        for symbol, bars in DAYTIME_BARS.items()
    }
    monkeypatch.setitem(globals(), "DAYTIME_BARS", dropped)

    with pytest.raises(ValueError, match="for every requested symbol"):
        publish_fixture(FakeBars(), out, SYMBOLS)

    assert not out.exists()


BROAD = tuple(f"M{index:02d}" for index in range(100))
QUIET_OVERNIGHT = ("M07", "M42", "M99")


class BroadBars:
    """The 2026-11-11 shape: 100 movers, a few with no overnight-session bars."""

    def __init__(self, quiet: Sequence[str] = QUIET_OVERNIGHT) -> None:
        self.quiet = tuple(quiet)

    def get_stock_bars(self, request: Any) -> dict[str, list[dict[str, object]]]:
        overnight = request.feed == DataFeed.BOATS
        template = OVERNIGHT_BARS["AAPL"] if overnight else DAYTIME_BARS["AAPL"]
        return {
            symbol: list(template)
            for symbol in request.symbol_or_symbols
            if not (overnight and symbol in self.quiet)
        }


def test_a_broad_universe_with_quiet_overnight_names_publishes_and_records_them(tmp_path) -> None:
    out = tmp_path / "baselines"

    manifest = publish_fixture(BroadBars(), out, BROAD)

    written = json.loads((out / "manifest.json").read_text())
    assert written == manifest
    assert written["symbols"] == list(BROAD)
    overnight = written["coverage"]["OVERNIGHT"]
    assert overnight["without_baseline"] == list(QUIET_OVERNIGHT)
    assert overnight["with_baseline"] == 97
    assert "fully paged" in overnight["reason"]
    traded = sorted(set(BROAD) - set(QUIET_OVERNIGHT))
    assert written["files"]["overnight.json"]["symbols"] == traded
    for name in ("PRE", "RTH", "POST"):
        assert written["coverage"][name]["without_baseline"] == []
        assert written["coverage"][name]["with_baseline"] == 100
    loaded = load_baseline(recipe.verified_baseline_text(out / "overnight.json"))
    assert sorted({sample.symbol for sample in loaded.samples}) == traded


def test_a_change_in_the_quiet_names_changes_the_manifest_bytes(tmp_path) -> None:
    publish_fixture(BroadBars(), tmp_path / "a", BROAD)
    publish_fixture(BroadBars(("M07", "M42")), tmp_path / "b", BROAD)

    def digest(name: str) -> str:
        return hashlib.sha256((tmp_path / name / "manifest.json").read_bytes()).hexdigest()

    assert digest("a") != digest("b")


def test_a_segment_where_no_symbol_traded_refuses_and_keeps_the_previous_files(tmp_path) -> None:
    out = tmp_path / "baselines"
    publish_fixture(BroadBars(), out, BROAD)
    before = published(out)

    with pytest.raises(recipe.BaselineFlagged, match="empty_segment"):
        publish_fixture(BroadBars(BROAD), out, BROAD, KNOWN_AT + 1)

    assert published(out) == before


def trade(name: str, at: int, price: str) -> TradeTick:
    return TradeTick(
        InstrumentId.from_str(name + ".ALPACA"),
        Price.from_str(price),
        Quantity.from_str("10"),
        AggressorSide.BUY,
        TradeId(str(at)),
        at,
        at + 1,
    )


def test_the_reader_treats_a_quiet_name_as_baseline_unknown(tmp_path) -> None:
    out = tmp_path / "baselines"
    publish_fixture(BroadBars(), out, BROAD)
    table = load_baseline(recipe.verified_baseline_text(out / "overnight.json"))
    names = ("M41.ALPACA", "M42.ALPACA")

    assert partition_covered(table, names, "OVERNIGHT") == (("M41.ALPACA",), ("M42.ALPACA",))
    assert coverage_receipt(table, names, "OVERNIGHT")["M42.ALPACA"]["state"] == "baseline_missing"
    start = nanos(moment(date(2026, 11, 9), 20))
    segment = Segment("OVERNIGHT", date(2026, 11, 10), start, start + 28_800 * NS, "fixture XNYS")
    rows = {}
    for name in ("M41", "M42"):
        state = MoverState()
        for second, price in ((0, "1.00"), (1500, "1.00"), (1860, "1.00"), (1920, "1.10")):
            state, row = advance_mover(
                state,
                trade(name, start + second * NS, price),
                ReferencePrices(D("1.00"), KNOWN_AT, "fixture official close"),
                table,
                segment=segment,
                feed="boats",
                registry=registry(),
            )
            rows[name] = row
    quiet, traded = rows["M42"], rows["M41"]
    assert quiet is not None and traded is not None
    assert "baseline_unknown" in quiet.observations["unknown_reasons"]
    assert quiet.score is None and quiet.dvol_ratio is None
    assert "baseline_unknown" not in traded.observations["unknown_reasons"]
    assert traded.dvol_ratio is not None and traded.score is not None
    assert [row.symbol for row in rank_movers([quiet, traded])] == ["M41"]


def test_publish_refuses_before_writing_when_a_table_is_wrong(tmp_path) -> None:
    tables = build_tables()
    broken = BaselineTable(
        tuple(sample for sample in tables["PRE"].samples if sample.symbol != "MF"),
        tables["PRE"].provenance,
        tables["PRE"].known_at,
        tables["PRE"].feed,
    )
    out = tmp_path / "baselines"

    with pytest.raises(ValueError, match="does not cover"):
        publish(
            out,
            {**tables, "PRE": broken},
            command=[*COMMAND],
            as_of=AS_OF,
            symbols=SYMBOLS,
            sessions=SESSIONS,
            known_at=KNOWN_AT,
            prior_sessions=2,
            source="symbols",
            universe=None,
        )

    assert not out.exists()


def test_main_reads_the_k2_universe_artifact_and_records_its_source(tmp_path) -> None:
    artifact = tmp_path / "universe.json"
    artifact.write_text(
        json.dumps(
            {
                "session": "overnight",
                "rows": [
                    {"symbol": "MF", "instrument_id": "MF.ALPACA"},
                    {"symbol": "AAPL", "instrument_id": "AAPL.ALPACA"},
                ],
            }
        )
    )
    out = tmp_path / "baselines"

    assert (
        main(
            [
                "--out",
                str(out),
                "--universe",
                str(artifact),
                "--as-of",
                "2026-11-09",
                "--prior-sessions",
                "2",
            ],
            client_factory=FakeBars,
            now_ns=lambda: KNOWN_AT,
        )
        == 0
    )

    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["symbols"] == ["MF", "AAPL"]
    assert manifest["source"] == "k2_universe"
    assert manifest["universe"] == {
        "path": str(artifact),
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    assert manifest["command"] == [
        "python",
        "-m",
        "sextant.data.baseline_recipe",
        "--out",
        str(out),
        "--universe",
        str(artifact),
        "--as-of",
        "2026-11-09",
        "--prior-sessions",
        "2",
    ]


def test_the_universe_artifact_is_read_once_and_hashed_from_those_bytes(
    tmp_path, monkeypatch
) -> None:
    artifact = tmp_path / "universe.json"
    artifact.write_text(json.dumps({"rows": [{"symbol": "MF"}, {"symbol": "AAPL"}]}))
    expected = hashlib.sha256(artifact.read_bytes()).hexdigest()
    reads: list[Path] = []
    original = Path.read_bytes

    def counting(path: Path) -> bytes:
        reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counting)

    symbols, record = recipe.load_universe(artifact)

    assert symbols == ("MF", "AAPL")
    assert reads == [artifact]
    assert record == {"path": str(artifact), "sha256": expected}


def test_main_defaults_as_of_to_the_current_segments_session_date(tmp_path) -> None:
    out = tmp_path / "baselines"

    assert (
        main(
            ["--out", str(out), "--symbols", "AAPL", "MF", "--prior-sessions", "2"],
            client_factory=FakeBars,
            now_ns=lambda: KNOWN_AT,
        )
        == 0
    )

    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["as_of"] == "2026-11-09"
    assert manifest["source"] == "symbols"


def test_prior_xnys_sessions_is_public_and_names_the_builder_window() -> None:
    assert prior_xnys_sessions(AS_OF, 2) == SESSIONS


def test_the_advertised_module_command_runs_main() -> None:
    root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [sys.executable, "-m", "sextant.data.baseline_recipe", "--help"],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage: python -m sextant.data.baseline_recipe" in result.stdout


def test_the_default_client_asks_its_vendor_for_raw_bars(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeHistoricalClient:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setenv("APCA_API_KEY_ID", "test-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "test-secret")
    monkeypatch.setattr("alpaca.data.historical.StockHistoricalDataClient", FakeHistoricalClient)

    client = recipe._default_client()

    assert isinstance(client, FakeHistoricalClient)
    assert calls == [{"api_key": "test-key", "secret_key": "test-secret", "raw_data": True}]


def test_a_venue_qualified_symbol_is_refused_before_the_vendor_call() -> None:
    client = FakeBars()

    with pytest.raises(ValueError, match="bare vendor ticker"):
        build(client, ["AAPL.ALPACA"], as_of=AS_OF, known_at=KNOWN_AT, prior_sessions=2)

    assert client.requests == []


def test_an_empty_refresh_leaves_the_active_set_untouched_and_exits_nonzero(
    tmp_path, capsys
) -> None:
    out = tmp_path / "baselines"
    arguments = [
        "--out",
        str(out),
        "--symbols",
        "AAPL",
        "--as-of",
        "2026-11-09",
        "--prior-sessions",
        "2",
    ]
    assert main(arguments, client_factory=FakeBars, now_ns=lambda: KNOWN_AT) == 0
    before = {path.name: path.read_bytes() for path in out.iterdir()}

    code = main(arguments, client_factory=lambda: FakeBars(empty=True), now_ns=lambda: KNOWN_AT)

    assert code == 1
    assert {path.name: path.read_bytes() for path in out.iterdir()} == before
    assert not [path for path in out.parent.iterdir() if path.name.startswith(f".{out.name}")]
    warning = capsys.readouterr().err
    assert "warning: baseline flags" in warning
    assert '"empty_segment"' in warning


def test_verified_text_proves_the_manifest_commits_to_the_bytes(tmp_path) -> None:
    out = tmp_path / "baselines"
    run(
        FakeBars(),
        SYMBOLS,
        out,
        command=[*COMMAND, "--out", str(out)],
        as_of=AS_OF,
        known_at=KNOWN_AT,
        prior_sessions=2,
    )
    path = out / "overnight.json"
    text = path.read_text()

    assert recipe.verified_baseline_text(path) == text

    path.write_text(text.replace('"feed":"boats"', '"feed":"sip"'))
    with pytest.raises(ValueError, match="manifest commit"):
        recipe.verified_baseline_text(path)


def test_verified_text_refuses_a_file_without_a_manifest(tmp_path) -> None:
    path = tmp_path / "overnight.json"
    path.write_text("{}")

    with pytest.raises(ValueError, match="manifest commit"):
        recipe.verified_baseline_text(path)


def test_a_table_missing_a_session_is_flagged_sparse() -> None:
    tables = build_tables()
    pre = [sample for sample in tables["PRE"].samples if sample.session != "2026-11-06"]
    thin = BaselineTable(
        tuple(pre), tables["PRE"].provenance, tables["PRE"].known_at, tables["PRE"].feed
    )

    flags = recipe.survey({**tables, "PRE": thin}, SYMBOLS, SESSIONS)

    assert flags["sparse"] == {"PRE": ["AAPL", "MF"]}
    assert flags["zero_filled"] == {}
