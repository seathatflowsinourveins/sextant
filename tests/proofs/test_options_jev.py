"""Row 13's offline software witness; fixtures are not model or trading evidence."""

import json
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path

import pytest
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.common import DataActor
from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.execution import FillModel, MakerTakerFeeModel, StaticLatencyModel
from nautilus_trader.model import (
    AccountType,
    ActorId,
    Currency,
    Equity,
    InstrumentId,
    Money,
    OmsType,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    Venue,
)

from sextant.judgments.catalyst import Capture, Request, effect, questions
from sextant.judgments.policy import Policy, digest, load_policy
from sextant.research.options import OptionsFactor
from sextant.research.options_jev import ResearchObserver, ResearchObserverConfig, simulation_status

ROOT = Path(__file__).parents[2]
ID = InstrumentId.from_str("AAPL.SIM")
NS = 1_000_000_000


@pytest.fixture
def policy() -> Policy:
    return load_policy(ROOT / "lanes/options/parameters.json")


@pytest.fixture
def source_request() -> Request:
    return Request(ID, "news-1", 1, "a" * 64, NS, "AAPL reports a product recall", "fixture")


def response(*, model: str = "jev-1.14.0", choice: str = "negative") -> str:
    # Numeric wire values stay textual until the consumer parses them with Decimal.
    return (
        '{"model":' + json.dumps(model) + ',"usage":{"input_tokens":123},"answers":{'
        '"relevance":{"type":"noul","noul":0.95},'
        '"polarity":{"type":"choice","choice":' + json.dumps(choice) + ","
        '"confidence":0.01,"probabilities":{"negative":0.85,"positive":0.10,"neutral":0.05}}}}'
    )


def capture(source_request: Request, raw: str | None = None, **kwargs) -> Capture:
    return Capture.from_response(
        source_request,
        response() if raw is None else raw,
        policy=load_policy(ROOT / "lanes/options/parameters.json"),
        requested_ns=NS,
        answered_ns=NS + 100_000_000,
        available_ns=NS + 110_000_000,
        **kwargs,
    )


def factor(value: Decimal | None = Decimal("4.2")) -> OptionsFactor:
    return OptionsFactor(ID, "OPRA", "rev-1", "b" * 64, NS, "activity", value)


def test_options_factor_preserves_missingness_and_cannot_change_weight() -> None:
    assert factor().value_at(NS - 1) is None
    assert factor().value_at(NS) == Decimal("4.2")
    assert factor(None).value_at(NS) is None
    assert factor().weight == factor(None).weight == Decimal(0)
    for value in (4.2, Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(ValueError, match="Decimal"):
            factor(value)  # type: ignore[arg-type]


def test_policy_requires_six_sourced_uncalibrated_rows_and_hashes_authority(
    policy, tmp_path
) -> None:
    path = ROOT / "lanes/options/parameters.json"
    rows = json.loads(path.read_text())
    assert len(rows) == 6
    assert {row["calibration_state"] for row in rows} == {"UNCALIBRATED"}
    assert policy.relevance_min == Decimal("0.7")
    assert policy.negative_min == Decimal("0.8")
    assert policy.priority_max == Decimal("1.25")
    changed = tmp_path / "parameters.json"
    for key in ("value", "source", "unit", "calibration_state", "last_change"):
        damaged = [dict(row) for row in rows]
        del damaged[0][key]
        changed.write_text(json.dumps(damaged))
        with pytest.raises(ValueError):
            load_policy(changed)
    changed.write_text(json.dumps(rows[:-1]))
    with pytest.raises(ValueError):
        load_policy(changed)
    rows[0]["source"] += " additional authority"
    changed.write_text(json.dumps(rows))
    assert load_policy(changed).params_hash != policy.params_hash


def test_request_uses_pinned_sdk_questions_and_revision_identity(source_request) -> None:
    assert version("typesafe-sdk") == "0.7.5"
    # Extracted from the exact Noul/Choice literals in the pinned catalyst_screen.py.
    assert digest(questions()) == "9510971fb404689e361a5c775e568a891a7b6ed50ed0460ea9904a11ff06cacb"
    body = source_request.body
    assert body["model"] == "jev-1.14.0"
    assert {q["type"] for q in body["questions"].values()} == {"noul", "choice"}
    assert set(body["questions"]["polarity"]["criteria"]) == {"positive", "negative", "neutral"}
    assert body["state"]["catalyst"]["received_ns"] == NS
    body["state"]["catalyst"]["headline"] = "mutated"
    assert source_request.body["state"]["catalyst"]["headline"] == source_request.headline
    assert replace(source_request, revision_ns=2).request_hash != source_request.request_hash
    assert replace(source_request, received_ns=NS + 1).request_hash != source_request.request_hash
    assert (
        replace(source_request, content_sha256="c" * 64).source_version
        != source_request.source_version
    )


def test_recorded_response_round_trip_preserves_wire_identity_and_availability(
    source_request, policy
) -> None:
    recorded = capture(source_request)
    restored = Capture.from_json(recorded.to_json())
    assert restored == recorded
    assert restored.response_json == response()
    assert restored.model_served == "jev-1.14.0"
    assert restored.input_tokens == 123
    assert restored.latency_ns == 100_000_000
    assert restored.answer_label == "jev: live-ledgered"
    assert restored.request.request_hash == source_request.request_hash
    assert effect(restored, NS + 109_999_999, policy).reason == "not_yet_available"
    decided = effect(restored, NS + 110_000_000, policy)
    assert decided.reason == "negative" and decided.allowed is False
    assert decided.priority_multiplier == Decimal(1)


@pytest.mark.parametrize("failure", ["LATE", "ERROR", "SKIPPED"])
def test_failures_replay_as_unchanged_incumbent_without_a_neutral_answer(
    source_request, policy, failure
) -> None:
    recorded = Capture.unavailable(source_request, failure, "fixture failure", requested_ns=NS)
    restored = Capture.from_json(recorded.to_json())
    assert restored.response_json is None
    decided = effect(restored, NS + 1, policy)
    assert decided.reason == failure.lower()
    assert decided.allowed and decided.priority_multiplier == Decimal(1)
    assert effect(None, NS, policy).reason == "missing"


def test_response_metadata_mismatches_and_bad_answers_are_unavailable(
    source_request, policy
) -> None:
    bad_responses = [
        response(model="jev-latest"),
        response().replace('"negative":0.85', '"negative":1.85'),
        response().replace('"negative":0.85', '"negative":NaN'),
        response().replace('"type":"noul"', '"type":"choice"'),
        response().replace('"input_tokens":123', '"input_tokens":true'),
        response().replace('"neutral":0.05', '"other":0.05'),
        "{}",
    ]
    for raw in bad_responses:
        recorded = capture(source_request, raw)
        decided = effect(recorded, NS + 200_000_000, policy)
        assert recorded.status == "ERROR"
        assert decided.allowed and decided.priority_multiplier == Decimal(1)
        assert decided.reason == "error"


def test_late_and_future_sources_never_become_usable(source_request, policy) -> None:
    assert effect(capture(source_request), NS - 1, policy).reason == "future_source"
    recorded = Capture.from_response(
        source_request,
        response(),
        policy=policy,
        requested_ns=NS,
        answered_ns=NS + 200_000_000,
        available_ns=NS + 201_000_000,
    )
    assert effect(recorded, NS + 300_000_000, policy).reason == "late"
    assert recorded.status == "LATE"
    wider_budget = replace(policy, request_budget_ms=Decimal("300"), params_hash="d" * 64)
    assert effect(recorded, NS + 300_000_000, wider_budget).reason == "late"
    assert effect(capture(source_request), NS + 86_400 * NS + 1, policy).reason == "expired"
    assert effect(capture(source_request), NS + 120_000_000, policy, enabled=False).reason == "off"


def test_positive_is_bounded_priority_and_confidence_never_the_probability_gate(
    source_request, policy
) -> None:
    raw = response(choice="positive").replace(
        '"negative":0.85,"positive":0.10', '"negative":0.10,"positive":0.85'
    )
    decided = effect(capture(source_request, raw), NS + 120_000_000, policy)
    assert decided.reason == "positive"
    assert Decimal(1) < decided.priority_multiplier <= policy.priority_max
    assert decided.allowed
    irrelevant = response().replace('"noul":0.95', '"noul":0.69')
    assert (
        effect(capture(source_request, irrelevant), NS + 120_000_000, policy).reason == "irrelevant"
    )


def test_recording_rejects_reversed_clocks_and_unknown_answer_labels(
    source_request, policy
) -> None:
    with pytest.raises(ValueError):
        Capture.from_response(
            source_request,
            response(),
            policy=policy,
            requested_ns=NS,
            answered_ns=NS - 1,
            available_ns=NS + 1,
        )
    with pytest.raises(ValueError):
        capture(source_request, answer_label="invented")


def test_recalled_answers_keep_their_label_and_actual_availability(source_request, policy) -> None:
    recalled = capture(source_request, answer_label="jev: recalled")
    assert Capture.from_json(recalled.to_json()).answer_label == "jev: recalled"
    assert effect(recalled, NS + 100_000_000, policy).reason == "not_yet_available"


def test_optional_sdk_usage_remains_unknown_and_durable_readiness_controls_deadline(
    source_request, policy
) -> None:
    recorded = capture(source_request, response().replace('"input_tokens":123', ""))
    assert recorded.status == "ANSWERED" and recorded.input_tokens is None
    late = Capture.from_response(
        source_request,
        response(),
        policy=policy,
        requested_ns=NS,
        answered_ns=NS + 100_000_000,
        available_ns=NS + 200_000_000,
    )
    assert effect(late, NS + 201_000_000, policy).reason == "late"


def test_replay_refuses_tampered_source_question_and_sdk_identity(source_request) -> None:
    row = json.loads(capture(source_request).to_json())
    for key in ("request_hash", "question_hash", "sdk_version"):
        with pytest.raises(ValueError):
            Capture.from_json(json.dumps(row | {key: "changed"}))
    row["request"]["headline"] = "later correction"
    with pytest.raises(ValueError, match="identity"):
        Capture.from_json(json.dumps(row))


@pytest.mark.parametrize("boundary", ["2026-07-04T20:00:00-04:00", "2026-11-01T20:00:00-05:00"])
def test_calendar_accounting_day_roll_expires_answers_at_exact_eastern_boundary(
    source_request, policy, boundary
) -> None:
    roll = int(datetime.fromisoformat(boundary).timestamp()) * NS
    source = replace(source_request, received_ns=roll - NS)
    recorded = Capture.from_response(
        source,
        response(),
        policy=policy,
        requested_ns=roll - NS,
        answered_ns=roll - NS + 100_000_000,
        available_ns=roll - NS + 110_000_000,
    )
    assert effect(recorded, roll - 1, policy).reason == "negative"
    assert effect(recorded, roll, policy).reason == "expired"


def test_observer_refuses_mixed_answer_labels_and_duplicate_source_revisions(
    source_request, policy
):
    recorded = capture(source_request)
    for recordings in (
        (recorded, recorded),
        (recorded, replace(recorded, answer_label="jev: recalled")),
    ):
        with pytest.raises(ValueError):
            ResearchObserverConfig(instrument_id=ID, options=(), captures=recordings, policy=policy)


def test_policy_rejects_a_mislabelled_time_unit(tmp_path) -> None:
    rows = json.loads((ROOT / "lanes/options/parameters.json").read_text())
    rows[-1]["unit"] = "milliseconds"
    path = tmp_path / "params.json"
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError, match="unit"):
        load_policy(path)


def test_observer_keeps_each_source_event_and_never_reuses_an_older_revision(
    source_request, policy
):
    negative = capture(source_request)
    positive_source = replace(source_request, event_key="news-2", received_ns=NS + 1)
    positive_raw = response(choice="positive").replace(
        '"negative":0.85,"positive":0.10', '"negative":0.10,"positive":0.85'
    )
    positive = Capture.from_response(
        positive_source,
        positive_raw,
        policy=policy,
        requested_ns=NS + 1,
        answered_ns=NS + 100_000_000,
        available_ns=NS + 110_000_000,
    )
    newer_source = replace(source_request, revision_ns=2, received_ns=NS + 2)
    newer = Capture.unavailable(newer_source, "ERROR", "fixture", requested_ns=NS + 2)
    quote = QuoteTick(
        ID,
        Price.from_str("100.00"),
        Price.from_str("100.01"),
        Quantity.from_int(1),
        Quantity.from_int(1),
        NS + 120_000_000,
        NS + 120_000_000,
    )
    for records, reason in (((negative, positive), "negative"), ((negative, newer), "error")):
        observer = ResearchObserver(
            ResearchObserverConfig(
                instrument_id=ID,
                options=(factor(),),
                captures=records,
                policy=policy,
                enabled=True,
            )
        )
        observer.on_quote(quote)
        row = observer.observations[-1]
        assert row["jev_reason"] == reason
        assert row["options_factors"][0]["evidence_sha256"] == "b" * 64
        assert len(row["jev_records"]) == (2 if reason == "negative" else 1)


def test_native_sim_observers_share_inputs_and_models_without_order_authority(
    source_request, policy
) -> None:
    # Engine fixture only. There is no trial, inference, financial return or merit claim.
    # The research-run entry point remains NOT_RUN until #72 lands the TrialLog.
    instrument = Equity(
        ID,
        Symbol("AAPL"),
        Currency.from_str("USD"),
        2,
        Price.from_str("0.01"),
        0,
        0,
        lot_size=Quantity.from_int(1),
    )
    quotes = [
        QuoteTick(
            ID,
            Price.from_str("100.00"),
            Price.from_str("100.01"),
            Quantity.from_int(1),
            Quantity.from_int(1),
            at,
            at,
        )
        for at in (NS, NS + 120_000_000)
    ]
    engine = BacktestEngine(BacktestEngineConfig(bypass_logging=True))
    engine.add_venue(
        Venue("SIM"),
        OmsType.NETTING,
        AccountType.CASH,
        [Money(10_000, Currency.from_str("USD"))],
        fill_model=FillModel(random_seed=42),
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
        latency_model=StaticLatencyModel(base_latency_nanos=10),
    )
    engine.add_instrument(instrument)
    pair = [
        ResearchObserver(
            ResearchObserverConfig(
                actor_id=ActorId(f"JEV-{label}"),
                instrument_id=ID,
                options=(factor(),),
                captures=(capture(source_request),),
                policy=policy,
                enabled=enabled,
            )
        )
        for label, enabled in (("OFF", False), ("ON", True))
    ]
    for observer in pair:
        assert isinstance(observer, DataActor)
        assert not hasattr(observer, "submit_order")
        engine.add_actor(observer)
    try:
        engine.add_data(quotes)
        engine.run()
        off, on = pair
        assert len(off.observations) == len(on.observations) == 2
        assert [row["ts_init"] for row in off.observations] == [q.ts_init for q in quotes]
        assert on.observations[-1]["jev_reason"] == "negative"
        assert on.observations[-1]["shadow_allowed"] is False
        assert off.observations[-1]["shadow_allowed"] is True
        assert all(row["options_weight"] == "0" for row in on.observations)
        assert all(row["order_authority"] is False for row in on.observations)
        assert engine.get_result().total_orders == 0
    finally:
        engine.dispose()


def test_canonical_triallog_binding_is_not_run_and_creates_no_alternative_ledger() -> None:
    status = simulation_status()
    assert status["ledger_binding"] == status["simulation"] == "NOT_RUN"
    assert status["order_authority"] is False
    assert "#72" in status["reason"]
