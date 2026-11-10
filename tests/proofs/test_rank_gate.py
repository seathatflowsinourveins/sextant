"""Offline proofs for the runner-independent rank veto."""

from importlib import import_module
from importlib.util import find_spec
from types import ModuleType

import pytest
from nautilus_trader.model import CustomData
from test_ranking import NS, START, publisher
from test_ranking_consumer import consumer, published

from sextant.ranking.publisher import ranking_data_type


def rank_gate() -> ModuleType:
    module = "sextant.ranking.rank_gate"
    assert find_spec(module) is not None, "rank gate decision function is missing"
    return import_module(module)


def test_rank_gate_defaults_to_disabled() -> None:
    gate = rank_gate()
    default = gate.decide_rank_gate()
    explicit = gate.decide_rank_gate(enabled=False, rank=None, consumer_reason="heartbeat_stale")
    assert (default.status.value, default.reason) == ("disabled", "rank_gate_disabled")
    assert explicit == default


@pytest.mark.parametrize(
    ("have_generation", "have_heartbeat", "generation_age", "heartbeat_age", "reason"),
    [
        (False, True, 2, 2, "generation_missing"),
        (True, False, 2, 2, "heartbeat_missing"),
        (True, True, 1, 2, "entry_generation_stale"),
        (True, True, 2, 1, "entry_heartbeat_stale"),
    ],
    ids=("missing-generation", "missing-heartbeat", "stale-generation", "stale-heartbeat"),
)
def test_enabled_gate_refuses_missing_or_stale_evidence(
    have_generation: bool,
    have_heartbeat: bool,
    generation_age: int,
    heartbeat_age: int,
    reason: str,
) -> None:
    pub = publisher()
    at = START + 360 * NS
    generation = published(pub, at=at)
    candidate = next(row.symbol for row in generation.rows if row.focus_eligible is True)
    entry = consumer(pub, heartbeat=heartbeat_age, generation=generation_age)
    if have_generation:
        assert entry.handle(CustomData(ranking_data_type(pub.feed), generation), now=at)
    if have_heartbeat:
        assert entry.accept_heartbeat(at=at, received_ns=at)

    rank = entry.entry_rank(candidate, now=at + NS + 1)
    assert rank is None and entry.reason == reason
    decision = rank_gate().decide_rank_gate(enabled=True, rank=rank, consumer_reason=entry.reason)
    assert (decision.status.value, decision.reason) == ("refuse", reason)
