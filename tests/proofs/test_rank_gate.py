"""Offline proofs for the runner-independent rank veto."""

from importlib import import_module
from importlib.util import find_spec
from types import ModuleType


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
