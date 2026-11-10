"""Generic entry reserve primitives remain without a B production caller."""

import ast
import json
from pathlib import Path

import pytest
from test_b_protector import NOW_NS

from sextant.execution.pacer import AccountPacer, ActionKind
from sextant.risk.controls import Controls

ROOT = Path(__file__).parents[2]


def b_entry_callers(source):
    """B has no submit(kind=...) or direct SUBMIT pacer request outside its facade."""
    return [
        call
        for call in ast.walk(ast.parse(source))
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and (
            (call.func.attr == "submit_order" and any(k.arg == "kind" for k in call.keywords))
            or (
                call.func.attr == "request"
                and any(
                    isinstance(arg, ast.Attribute) and arg.attr == "SUBMIT" for arg in call.args
                )
            )
        )
    ]


def test_no_b_production_caller_reaches_entry_admission_and_a_new_caller_fails_the_proof():
    sources = list((ROOT / "src/sextant/paper").glob("b_*.py"))
    assert sources
    for path in sources:
        assert b_entry_callers(path.read_text()) == [], path
    # Mutation witness: adding the most direct B caller makes this exact predicate fail.
    candidate = "client.submit_order(order, kind=ActionKind.SUBMIT)"
    with pytest.raises(AssertionError):
        assert b_entry_callers(candidate) == []
    with pytest.raises(AssertionError):
        assert b_entry_callers("pacer.request(ActionKind.SUBMIT, send)") == []


def test_generic_entry_reserve_includes_each_requested_snapshot_pair():
    controls = Controls.from_rows(json.loads((ROOT / "lanes/custody-parameters.json").read_text()))
    pacer = AccountPacer(controls, lambda: NOW_NS)
    pacer.bucket.tokens = 3
    sent = []
    active = [True]
    pacer.request(
        ActionKind.SUBMIT,
        lambda before: (before(), sent.append("entry")),
        admission=lambda: active[0],
        snapshot_reads=2,
        position_counts=lambda: (0, 0),
    )
    assert sent == [] and pacer.wire_requests == 0
    active[0] = False
    pacer.drain()
    pacer.request(ActionKind.REDUCE, lambda before: (before(), sent.append("protection")))
    assert sent == ["protection"] and pacer.wire_actions[ActionKind.SUBMIT] == 0
    assert pacer.wire_actions[ActionKind.REDUCE] == 1 and pacer.queue == []
