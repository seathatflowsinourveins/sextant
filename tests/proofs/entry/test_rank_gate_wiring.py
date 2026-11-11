"""Native entry seam proofs; synthetic fixtures grant no deployment authority."""

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from nautilus_trader.common import MessageBus
from nautilus_trader.execution import StaticLatencyModel
from nautilus_trader.model import CustomData, TraderId
from test_ranking import baseline, registry

from sextant.ranking import registry as gate_registry
from sextant.ranking.consumer import RankingConsumer
from sextant.ranking.engine import ReferencePrices, Segment
from sextant.ranking.generation import Coverage, CoverageState
from sextant.ranking.publisher import AssetState, RankingPublisher, ranking_data_type

from .conftest import SEC, START, quote, trade
from .test_delta_gate import receipt, reclaim_tape
from .test_replay import replay


def episode(instrument, tmp_path, *, setup="FIRST_LEG", **kwargs):
    if setup == "RECLAIM":
        data = sorted(
            [*reclaim_tape(), quote("7.9", "10.02", "10.03")], key=lambda row: row.ts_init
        )
        kwargs = (
            dict(surge=None, confidence=D("0.5"), coverage=receipt({60 * SEC: 9, 2 * SEC: 2}))
            | kwargs
        )
    else:
        data = [quote(0, "10.00", "10.02")]
        data += [trade(at, "10.01", size=10000) for at in (0, 1, 2)]
        data += [
            quote("2.1", "10.49", "10.50"),
            quote(3, "10.02", "10.03"),
            quote(10, "10.49", "10.50"),
        ]
        kwargs = dict(latency_model=StaticLatencyModel(insert_latency_nanos=500_000_000)) | kwargs
    return replay(instrument, tmp_path, data, **kwargs)


def ranked(*, missing=None, heartbeat=20, generation=20, inputs=20, focus=True):
    """A real publisher and consumer, with explicit test-only freshness ages."""
    reg = registry()
    reg = replace(
        reg,
        rows=tuple(
            replace(row, value=20)
            if row.name in {"generation_max_age_s", "heartbeat_max_age_s", "input_max_age_s"}
            else row
            for row in reg.rows
        ),
    )
    segment = Segment("PRE", date(2026, 11, 1), START - 360 * SEC, START + 600 * SEC, "TEST")
    table = baseline()
    table = replace(
        table,
        samples=tuple(replace(row, symbol="AAA") for row in table.samples if row.symbol == "PENNY"),
    )
    pub = RankingPublisher(
        bus=MessageBus(TraderId.from_str("RANK-TEST")),
        epoch="TEST",
        feed="sip",
        segment=segment,
        registry=reg,
        universe=("AAA",),
        universe_source="TEST",
        baseline=table,
    )
    pub.set_coverage(Coverage(CoverageState.READY, True, 1, 1, 0, 0, 0))
    pub.set_symbol(
        "AAA",
        references=ReferencePrices(D("0.50"), segment.start_ns - SEC, "TEST"),
        asset=AssetState(segment.start_ns - SEC, segment.end_ns, False, "common", "TEST"),
    )
    for second in (0, 60, 120, 180, 240, 300, 310, 320, 330, 340, 350, 360):
        tick = trade(second - 360, "0.55" if focus and second > 300 else "0.50")
        pub.on_trade(tick)
    batch = pub.publish(now=START)
    assert batch is not None
    consumer = RankingConsumer(
        registry=reg,
        feed="sip",
        segment=segment,
        universe_hash=pub.universe_hash,
        baseline_hash=table.identity,
        entry_heartbeat_max_age_s=heartbeat,
        entry_generation_max_age_s=generation,
        entry_input_max_age_s=inputs,
    )
    if missing != "generation":
        assert consumer.handle(CustomData(ranking_data_type("sip"), batch), now=START)
    if missing != "heartbeat":
        assert consumer.accept_heartbeat(at=START, received_ns=START)
    return consumer


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(
        gate_registry, "RANK_GATE_ENABLED", replace(gate_registry.RANK_GATE_ENABLED, value=True)
    )


@pytest.mark.parametrize("setup", ["FIRST_LEG", "RECLAIM"])
def test_off_entry_decisions_match_unwired_head_bytes(instrument, tmp_path, monkeypatch, setup):
    # Removing the OFF branch or consulting ranking while disabled breaks this witness.
    assert gate_registry.RANK_GATE_ENABLED.value is False

    def unavailable(*_args, **_kwargs):
        raise AssertionError("OFF must not read ranking")

    monkeypatch.setattr(RankingConsumer, "entry_rank", unavailable)
    result = episode(instrument, tmp_path, setup=setup)
    expected = json.loads(Path(__file__).with_name("rank-gate-off.json").read_bytes())[setup]
    assert (
        json.dumps(result.events, sort_keys=True, separators=(",", ":")).encode()
        == expected.encode()
    )
    assert not result.failed and len(result.orders) == 1


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"missing": "consumer"}, "consumer_result_missing"),
        ({"missing": "generation"}, "generation_missing"),
        ({"missing": "heartbeat"}, "heartbeat_missing"),
        ({"generation": 1}, "entry_generation_stale"),
        ({"heartbeat": 1}, "entry_heartbeat_stale"),
        ({"inputs": 1}, "entry_input_stale"),
        ({"focus": False}, "candidate_unranked"),
        ({"missing": "invalid"}, "TEST invalid generation"),
    ],
)
def test_enabled_native_entry_refuses_current_ranking_evidence(
    instrument, tmp_path, enabled, arguments, reason
):
    consumer = None if arguments.get("missing") == "consumer" else ranked(**arguments)
    if arguments.get("missing") == "invalid":
        consumer.reader.invalidate(reason)
    result = episode(instrument, tmp_path, ranking_consumer=consumer)
    assert not result.failed, result.events
    assert result.orders == [], result.events
    assert any(e.get("stage") == "RANK" and e.get("reason") == reason for e in result.events)


@pytest.mark.parametrize("setup", ["FIRST_LEG", "RECLAIM"])
def test_enabled_native_entry_reads_raw_symbol_at_each_decision_clock(
    instrument, tmp_path, enabled, monkeypatch, setup
):
    consumer = ranked()
    calls = []
    real = consumer.entry_rank

    def observe(symbol, *, now):
        calls.append((symbol, now))
        return real(symbol, now=now)

    monkeypatch.setattr(consumer, "entry_rank", observe)
    result = episode(instrument, tmp_path, setup=setup, ranking_consumer=consumer)
    assert not result.failed and len(result.orders) == 1, result.events
    submits = [e for e in result.events if e["action"] == "SUBMIT"]
    assert len(submits) == 1 and submits[0]["setup"] == setup
    assert ("AAA", START + (8 if setup == "RECLAIM" else 2) * SEC) in calls
    assert {symbol for symbol, _now in calls} == {"AAA"}


def test_rank_pass_does_not_override_setup_or_sizing(instrument, tmp_path, enabled):
    consumer = ranked()
    sized = episode(instrument, tmp_path / "sizing", starting_cash=D(0), ranking_consumer=consumer)
    setup = replay(
        instrument,
        tmp_path / "setup",
        [quote(0, "10.00", "10.02"), trade(0, "10.01")],
        ranking_consumer=consumer,
    )
    assert not sized.failed and not setup.failed
    assert sized.orders == setup.orders == []
    assert any(e["action"] == "REFUSE" and e.get("stage") != "RANK" for e in sized.events)


def test_stale_rank_blocks_reprice_and_preserves_ttl(instrument, tmp_path, enabled):
    # Caching the rank at submission would incorrectly amend this still-owned order.
    consumer = ranked(generation=2)
    result = episode(instrument, tmp_path, ranking_consumer=consumer)
    assert not result.failed and len(result.orders) == 1, result.events
    assert not any(e["action"] == "MODIFY" for e in result.events)
    assert any(e.get("reason") == "entry_generation_stale" for e in result.events)
    assert [e["ts"] for e in result.events if e["action"] == "CANCEL"] == [START + 7 * SEC]
    assert result.orders[0]["status"] == "CANCELED"


def test_invalid_registry_switch_cannot_bypass_rank_gate(instrument, tmp_path, monkeypatch):
    monkeypatch.setattr(
        gate_registry, "RANK_GATE_ENABLED", replace(gate_registry.RANK_GATE_ENABLED, value=0)
    )
    result = episode(instrument, tmp_path)
    assert not result.failed and result.orders == []
    assert any(e.get("reason") == "rank_gate_setting_invalid" for e in result.events)
