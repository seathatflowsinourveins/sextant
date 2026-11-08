"""Offline producer proofs: real publisher -> immutable unit -> existing reader."""

import copy
import importlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from nautilus_trader.common import MessageBus
from nautilus_trader.model import (
    AggressorSide,
    InstrumentId,
    Price,
    Quantity,
    TradeId,
    TraderId,
    TradeTick,
)
from test_ranking import DAY, NS, START, registry

from sextant.ranking.baseline import BaselineSample, BaselineTable
from sextant.ranking.engine import ReferencePrices, Segment
from sextant.ranking.generation import Coverage, CoverageState, RankingFeature, RankingGeneration
from sextant.ranking.publisher import AssetState, RankingPublisher
from sextant.tradingview.inputs import InputError, read_research_inputs


def ready(count):
    return Coverage(CoverageState.READY, True, count, count, 0, 0, 0)


NOW = datetime(2026, 10, 27, 8, 0, 3, tzinfo=UTC)
METHOD = "MOVER-v2@00203275944a22655b3e14b221cfde9a265d549a"


def api():
    try:
        return importlib.import_module("sextant.tradingview.producer")
    except ModuleNotFoundError:
        pytest.fail("The offline TradingView display producer is not implemented")


def generation(symbols=("AAA", "BBB"), *, start=START, day=DAY, feed="sip", segment="PRE"):
    times = Segment(segment, day, start - 400 * NS, start + 100 * NS, "fixture:official-session")
    samples = BaselineTable(
        tuple(
            BaselineSample(symbol, segment, "2026-10-26", offset, Decimal(amount), Decimal(amount))
            for symbol in symbols
            for offset, amount in ((0, 0), (600, 100))
        ),
        "fixture:complete-curves",
        start - 500 * NS,
        feed,
    )
    publisher = RankingPublisher(
        bus=MessageBus(trader_id=TraderId("TVP-001")),
        epoch="fixture-display",
        feed=feed,
        segment=times,
        registry=registry(),
        universe=symbols,
        universe_source="fixture:universe",
        baseline=samples,
    )
    publisher.set_coverage(ready(len(symbols)))
    for symbol in symbols:
        publisher.set_symbol(
            symbol,
            references=ReferencePrices(Decimal(10), start - 500 * NS, "fixture:official-close"),
            asset=AssetState(
                start - 500 * NS, start + 100 * NS, False, "common", "fixture:security-master"
            ),
        )
        for second in (-400, -300, -200, -100, 0, 1, 2):
            at = start + second * NS
            publisher.on_trade(
                TradeTick(
                    InstrumentId.from_str(symbol + ".NASDAQ"),
                    Price.from_str("12.000000000"),
                    Quantity.from_int(100),
                    AggressorSide.BUY,
                    TradeId(str(at)),
                    at,
                    at,
                )
            )
    result = publisher.publish(now=start + 3 * NS)
    assert result is not None
    return result


def mapping(record):
    return {row.symbol: f"NASDAQ:{row.symbol}" for row in record.rows}


def documents(record=None, **kwargs):
    record = generation() if record is None else record
    return api().build_unit(
        record,
        generated_at=kwargs.pop("generated_at", NOW.isoformat()),
        ranking_path="inputs/ranking.json",
        symbol_map=kwargs.pop("symbol_map", mapping(record)),
        **kwargs,
    )


def test_real_generation_maps_truthfully_without_making_unknowns_clean(tmp_path):
    record = generation()
    before = record.to_json()
    docs = documents(record)
    top, focus, display = (
        docs[name] for name in ("top100.json", "focus.json", "display-lists.json")
    )
    assert top["schema"] == "morning-pack.candidates/1"
    assert focus["schema"] == "top100.focus/1"
    assert top["as_of_snapshot"] == "2026-10-27T08:00:02+00:00"
    assert top["as_of"] == top["generated_at"] == "2026-10-27T08:00:03+00:00"
    assert docs["inputs/display-snapshot.json"]["weights_version"] == METHOD
    assert top["ranking_policy"]["method_version"] == METHOD
    assert display["counts"] == {"ns_movers": 2, "ns_focus": 0}
    assert display["excluded_unknown"] == 2
    assert display["armed"] == "UNVERIFIED"
    assert focus["candidates"] == []  # focus_eligible is not proof of absent sell pressure.
    assert {item["reason"] for item in focus["excluded"]} == {"unverified_sell_pressure"}
    first = top["candidates"][0]
    assert first["score"] == str(record.rows[0].score)
    assert first["potential2_score"] is None
    assert first["signals"]["rvol"] is None
    assert first["price"] == "12.000000000"
    assert {flag["status"] for flag in first["sell_pressure_flags"]} == {"UNVERIFIED"}
    assert first["ticket"] is None
    assert first["daily_metrics"]["atr22"] is None
    assert docs["inputs/display-snapshot.json"]["symbols"][0]["inputs"]["previous_close"] is None
    assert record.to_json() == before
    unit = api().publish_unit(
        record, tmp_path / "published", generated_at=NOW.isoformat(), symbol_map=mapping(record)
    )
    loaded = read_research_inputs(unit, now=NOW)
    assert loaded.memberships == {
        "NS movers": frozenset({"NASDAQ:AAA", "NASDAQ:BBB"}),
        "NS focus": frozenset(),
    }
    assert loaded.generation == top["generation"]
    assert (tmp_path / "published/latest").resolve() == unit


def test_snapshot_hash_binds_the_entire_generation_not_just_top100(tmp_path):
    from hashlib import sha256

    record = generation(tuple(f"SYM{i:04}" for i in range(101)))
    rows = list(record.rows)
    # Explicit independently clocked inputs, not dvol_ratio masquerading as RVOL.
    rows[-1] = replace(
        rows[-1],
        features=(
            *rows[-1].features,
            RankingFeature("previous_close", Decimal(1), START, START),
            RankingFeature("rvol", Decimal(2), START + 2 * NS, START + 2 * NS),
        ),
    )
    record = replace(record, rows=tuple(rows))
    unit = api().publish_unit(
        record, tmp_path, generated_at=NOW.isoformat(), symbol_map=mapping(record)
    )
    top = json.loads((unit / "top100.json").read_text())
    display = json.loads((unit / "display-lists.json").read_text())
    source = unit / display["sources"]["snapshot"]["path"]
    assert len(top["candidates"]) == 100
    assert len(json.loads(source.read_text())["symbols"]) == 101
    assert display["ns_movers"][-1] == {
        "symbol": "SYM0100",
        "tradingview_symbol": "NASDAQ:SYM0100",
        "labels": ["extreme:≥20%"],
    }
    assert display["generation"]["sha256"] == sha256(source.read_bytes()).hexdigest()
    frozen = RankingGeneration.from_json((unit / "inputs/ranking.json").read_bytes())
    assert frozen == record


@pytest.mark.parametrize(
    "fault",
    [
        "partial",
        "missing",
        "unknown-coverage",
        "top-only",
        "truncated-universe",
        "stale",
        "future",
        "method",
        "rank",
        "rank-score",
        "feature-future",
        "feature-partial",
        "feature-no-clock",
        "source",
        "mixed-source",
        "empty",
        "session",
    ],
)
def test_unavailable_generations_cannot_publish_or_replace_latest(tmp_path, fault):
    record = generation()
    producer = api()
    original = producer.publish_unit(
        record, tmp_path, generated_at=NOW.isoformat(), symbol_map=mapping(record)
    )
    before = {p.relative_to(original): p.read_bytes() for p in original.rglob("*") if p.is_file()}
    rows = list(record.rows)
    if fault == "partial":
        rows[0] = replace(rows[0], partial=True)
    elif fault == "missing":
        record = replace(record, coverage=replace(record.coverage, missing_symbols=1))
    elif fault == "unknown-coverage":
        record = replace(record, coverage=Coverage(CoverageState.UNKNOWN, False))
    elif fault == "top-only":
        record = replace(record, coverage=replace(record.coverage, complete=False))
    elif fault == "truncated-universe":
        rows = rows[:1]
        record = replace(record, coverage=ready(1))
    elif fault == "stale":
        record = replace(record, input_cutoff=START - 601 * NS)
    elif fault == "future":
        record = replace(record, known_at=START + 3 * NS + 1)
    elif fault == "method":
        record = replace(record, method_version=METHOD + "-new")
    elif fault == "rank":
        rows[1] = replace(rows[1], rank=rows[0].rank)
    elif fault == "rank-score":
        rows[1] = replace(rows[1], score=None)
    elif fault.startswith("feature-"):
        changes = {
            "feature-future": {"known_at": START + 3 * NS},
            "feature-partial": {"partial": True},
            "feature-no-clock": {"known_at": None},
        }[fault]
        rows[0] = replace(
            rows[0], features=(replace(rows[0].features[0], **changes), *rows[0].features[1:])
        )
    elif fault in {"source", "mixed-source"}:
        reasons = tuple(r for r in rows[0].reasons if r.code != "SOURCE")
        if fault == "mixed-source":
            source = next(r for r in rows[0].reasons if r.code == "SOURCE")
            reasons += (replace(source, detail=(source.detail or "").replace('"sip"', '"boats"')),)
        rows[0] = replace(rows[0], reasons=reasons)
    elif fault == "empty":
        rows = []
        record = replace(record, coverage=ready(0))
    elif fault == "session":
        record = replace(record, session_date=DAY.replace(day=26))
    record = replace(record, rows=tuple(rows))
    with pytest.raises((ValueError, InputError)):
        producer.publish_unit(
            record, tmp_path, generated_at=NOW.isoformat(), symbol_map=mapping(record)
        )
    assert (tmp_path / "latest").resolve() == original
    assert {
        p.relative_to(original): p.read_bytes() for p in original.rglob("*") if p.is_file()
    } == before


def test_missing_listing_identity_is_null_not_synthetic_alpaca_venue(tmp_path):
    record = generation()
    docs = documents(record, symbol_map={})
    assert [row["tradingview_symbol"] for row in docs["top100.json"]["candidates"]] == [None, None]
    assert [row["exchange"] for row in docs["inputs/display-snapshot.json"]["symbols"]] == [
        None,
        None,
    ]
    with pytest.raises(InputError, match=r"unmapped|empty"):
        api().publish_unit(record, tmp_path, generated_at=NOW.isoformat())
    assert not (tmp_path / "latest").exists()


@pytest.mark.parametrize(
    "bad",
    [
        {"AAA": "ALPACA:AAA"},
        {"AAA": "SMART:AAA"},
        {"AAA": "AAA"},
        {"AAA": "NASDAQ:BBB", "BBB": "NASDAQ:BBB"},
    ],
)
def test_bad_explicit_symbol_map_cannot_publish(tmp_path, bad):
    with pytest.raises(ValueError):
        api().publish_unit(generation(), tmp_path, generated_at=NOW.isoformat(), symbol_map=bad)
    assert not (tmp_path / "latest").exists()


@pytest.mark.parametrize(
    "name",
    [
        "top100.json",
        "focus.json",
        "display-lists.json",
        "inputs/display-snapshot.json",
        "inputs/ranking.json",
    ],
)
def test_each_publication_write_failure_keeps_previous_complete_unit(tmp_path, monkeypatch, name):
    producer = api()
    record = generation()
    original = producer.publish_unit(
        record, tmp_path, generated_at=NOW.isoformat(), symbol_map=mapping(record)
    )
    previous = (original / "display-lists.json").read_bytes()
    write = producer._write_json

    def fail(path, doc):
        write(path, doc)
        if str(path).endswith("/" + name):
            raise OSError("fixture: disk full after write")

    monkeypatch.setattr(producer, "_write_json", fail)
    with pytest.raises(OSError):
        producer.publish_unit(
            record, tmp_path, generated_at=NOW.isoformat(), symbol_map=mapping(record)
        )
    assert (tmp_path / "latest").resolve() == original
    assert (original / "display-lists.json").read_bytes() == previous
    assert read_research_inputs(tmp_path / "latest", now=NOW).memberships["NS movers"]


def test_nanosecond_cutoff_is_exact_and_generation_digest_changes(tmp_path):
    producer = api()
    record = generation()
    left = documents(replace(record, input_cutoff=START + 2 * NS + 1))
    right = documents(replace(record, input_cutoff=START + 2 * NS + 2))
    assert left["top100.json"]["as_of_snapshot"] == "2026-10-27T08:00:02.000000001+00:00"
    assert left["top100.json"]["generation"] != right["top100.json"]["generation"]
    with pytest.raises(ValueError):
        producer.publish_unit(
            record,
            tmp_path,
            generated_at="2026-10-27T08:00:02.999999999+00:00",
            symbol_map=mapping(record),
        )


def test_sunday_overnight_keeps_explicit_boats_and_sip_separate(tmp_path):
    from datetime import date

    from sextant.tradingview.display_support import timestamp_ns

    now = datetime(2026, 11, 9, 1, 0, 3, tzinfo=UTC)
    record = generation(
        start=timestamp_ns("2026-11-09T01:00:00+00:00"),
        day=date(2026, 11, 9),
        feed="boats",
        segment="OVERNIGHT",
    )
    unit = api().publish_unit(
        record, tmp_path, generated_at=now.isoformat(), symbol_map=mapping(record)
    )
    expected = {
        "session": "overnight",
        "session_date": "2026-11-09",
        "intraday_feed": "boats",
        "daily_history_feed": "sip",
        "daily_history_scope": "prior completed XNYS sessions; not BOATS intraday evidence",
    }
    for name in ("top100.json", "focus.json", "display-lists.json"):
        doc = json.loads((unit / name).read_text())
        assert doc["ranking_context"] == expected
        assert doc["research_inputs"]["ranking"]["feed"] == "boats"
    assert read_research_inputs(unit, now=now).memberships["NS movers"]
    # The publisher itself refuses this feed/segment pairing; alter its wire receipt
    # to witness the independent display boundary's refusal of a forged source.
    rows = tuple(
        replace(
            row,
            reasons=tuple(
                replace(reason, detail=(reason.detail or "").replace('"boats"', '"sip"'))
                if reason.code == "SOURCE"
                else reason
                for reason in row.reasons
            ),
        )
        for row in record.rows
    )
    with pytest.raises(ValueError):
        documents(replace(record, rows=rows), generated_at=now.isoformat())


def test_submicrosecond_generated_at_survives_publication_without_rounding(tmp_path):
    record = generation()
    unit = api().publish_unit(
        record,
        tmp_path,
        generated_at="2026-10-27T08:00:03.000000001+00:00",
        symbol_map=mapping(record),
    )
    top = json.loads((unit / "top100.json").read_bytes())
    assert top["generated_at"] == "2026-10-27T08:00:03.000000001+00:00"
    read_research_inputs(unit, now=datetime(2026, 10, 27, 8, 0, 3, 1, tzinfo=UTC))


def test_missing_security_type_never_enters_movers_even_with_an_explicit_map(tmp_path):
    record = generation()
    rows = tuple(
        replace(row, reasons=tuple(r for r in row.reasons if r.code != "ASSET"))
        for row in record.rows
    )
    record = replace(record, rows=rows)
    doc = documents(record)
    assert doc["display-lists.json"]["ns_movers"] == []
    with pytest.raises(InputError):
        api().publish_unit(
            record, tmp_path, generated_at=NOW.isoformat(), symbol_map=mapping(record)
        )
    assert not (tmp_path / "latest").exists()


def test_newer_latest_refuses_older_generation_without_overwriting(tmp_path):
    record = generation()
    newest = replace(record, input_cutoff=START + 2 * NS + 1)
    original = api().publish_unit(
        newest, tmp_path, generated_at=NOW.isoformat(), symbol_map=mapping(record)
    )
    with pytest.raises(ValueError, match="older"):
        api().publish_unit(
            record, tmp_path, generated_at=NOW.isoformat(), symbol_map=mapping(record)
        )
    assert (tmp_path / "latest").resolve() == original


def test_armed_journal_is_captured_once_and_keeps_unknown_pressure_label(tmp_path):
    from sextant.tradingview.display_lists import ArmedSet

    record = generation()
    text = json.dumps(
        {
            "kind": "premarket_gap_scanner_refresh",
            "version": 1,
            "ts_event": START + 3 * NS,
            "snapshot_reason": "fresh",
            "snapshot_as_of": "2026-10-27T08:00:02+00:00",
            "armed": ["AAA.ALPACA"],
        }
    )
    unit = api().publish_unit(
        record,
        tmp_path,
        generated_at=NOW.isoformat(),
        symbol_map=mapping(record),
        armed_sets=(ArmedSet("fixture-arm", "captured.jsonl", text),),
    )
    doc = json.loads((unit / "display-lists.json").read_bytes())
    assert doc["ns_focus"] == [
        {
            "symbol": "AAA",
            "tradingview_symbol": "NASDAQ:AAA",
            "labels": ["arm:fixture-arm", "phase:pre", "sell_pressure:UNVERIFIED"],
        }
    ]
    assert doc["armed"] == "observed"
    assert read_research_inputs(unit, now=NOW).memberships["NS focus"] == frozenset({"NASDAQ:AAA"})


def test_cli_missing_input_is_explicit_and_does_not_create_a_unit(tmp_path, capsys):
    producer = api()
    missing = tmp_path / "missing-ranking.json"
    assert producer.main(["--ranking", str(missing), "--out", str(tmp_path / "out")]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "unavailable"
    assert str(missing) in output["reason"]
    assert not (tmp_path / "out").exists()


def test_cli_emits_counts_and_clocks_without_auth_or_network(tmp_path, capsys):
    producer = api()
    record = generation()
    source = tmp_path / "ranking.json"
    source.write_text(record.to_json())
    symbols = tmp_path / "symbols.json"
    symbols.write_text(json.dumps(mapping(record)))
    before = copy.deepcopy((source.read_bytes(), symbols.read_bytes()))
    assert (
        producer.main(
            [
                "--ranking",
                str(source),
                "--out",
                str(tmp_path / "out"),
                "--symbol-map",
                str(symbols),
                "--generated-at",
                NOW.isoformat(),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "published"
    assert report["lists"] == {
        "NS movers": {
            "count": 2,
            "as_of": "2026-10-27T08:00:03+00:00",
            "generated_at": "2026-10-27T08:00:03+00:00",
        },
        "NS focus": {
            "count": 0,
            "as_of": "2026-10-27T08:00:03+00:00",
            "generated_at": "2026-10-27T08:00:03+00:00",
        },
    }
    assert before == (source.read_bytes(), symbols.read_bytes())
