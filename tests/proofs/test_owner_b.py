"""B's supplied-custody intents; these do not witness real external-fill claiming (#49)."""

from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path

import pytest


def adoption(**overrides):
    from sextant.exits.owner_b import adopt

    facts: dict = dict(
        entry=D("100"),
        mark=D("90"),
        quantity=D(10),
        owner_reserved=D(2),
        buffer=D(1),
        filled_ns=0,
        now_ns=1_000_000_000,
        reconciled=True,
        claim_max_latency_s=D(2),
    )
    return adopt(**(facts | overrides))


def test_adoption_keeps_the_basis_and_starts_h_at_the_mark():
    a = adoption()
    assert (a.entry, a.high, a.trigger, a.quantity) == (D(100), D(90), D(99), D(8))
    assert a.reason == "adopted-below-trigger"


@pytest.mark.parametrize(
    "facts, reason",
    [
        ({"reconciled": False}, "custody_unresolved"),
        ({"claim_max_latency_s": None}, "claim_latency_unavailable"),
        ({"now_ns": 2_000_000_001}, "claim_too_late"),
        ({"now_ns": -1}, "invalid_claim_clock"),
        ({"owner_reserved": D(11)}, "quantity_mismatch"),
        ({"quantity": D("10.5")}, "fractional_custody_unverified"),
    ],
)
def test_adoption_never_infers_missing_or_stale_custody(facts, reason):
    a = adoption(**facts)
    assert a.reason == reason
    assert a.quantity == 0


def test_latency_boundary_is_inclusive_and_full_owner_reservation_is_an_alert():
    assert adoption(now_ns=2_000_000_000, mark=D(105)).quantity == 8
    a = adoption(owner_reserved=D(10))
    assert a.quantity == 0 and a.reason == "owner_reserved_unprotected"


def test_missing_or_invalid_authority_has_no_fixture_default():
    from sextant.exits.owner_b import REGISTRY, BParams

    assert all(row.start is None and row.state == "UNCALIBRATED" for row in REGISTRY)
    with pytest.raises(TypeError):
        BParams()  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        BParams(D("0.03"), D(5), D(2))
    with pytest.raises(ValueError):
        adoption(buffer=D("NaN"))


def test_a_live_or_pending_exit_reserves_its_quantity_until_terminal():
    from sextant.exits.owner_b import OwnedExit, decide

    trail = OwnedExit("house-trail", "trail", D(8))
    a = decide(D(10), D(2), (trail,), mode="breach")
    assert (a.action, a.order_id) == ("cancel", "house-trail")
    waiting = replace(trail, pending_cancel=True)
    assert decide(D(10), D(2), (waiting,), mode="breach").action == "wait"
    # Terminal trail is omitted from a fresh snapshot, so only now may LIMIT be submitted.
    a = decide(D(9), D(2), (), mode="breach")
    assert (a.action, a.quantity) == ("limit", D(7))
    pending_limit = OwnedExit("house-limit", "limit", D(7), pending=True)
    assert decide(D(9), D(2), (pending_limit,), mode="recover").action == "wait"
    accepted = replace(pending_limit, pending=False)
    assert decide(D(9), D(2), (accepted,), mode="recover").order_id == "house-limit"
    assert decide(D(6), D(2), (), mode="recover").quantity == D(4)


def test_duplicate_exits_mismatch_and_owner_add_pause_and_page():
    from sextant.exits.owner_b import OwnedExit, decide

    exits = (OwnedExit("a", "trail", D(8)), OwnedExit("b", "limit", D(8)))
    assert decide(D(10), D(2), exits, mode="protect").action == "pause_and_page"
    a = decide(D(10), D(2), (), mode="protect", owner_add=True)
    assert a.action == "pause_and_page" and a.reason == "owner_add"
    assert a.order_id is None
    assert decide(D(10), D(11), (), mode="protect").action == "pause_and_page"


def test_b_export_reproduces_the_harvested_descriptive_fifo_and_lifo():
    from sextant.research.b_export import summarize

    path = Path(__file__).parents[1] / "fixtures" / "b-trades.jsonl"
    r = summarize(path)
    assert (r["orders"], r["symbols"], r["fifo_lots"]) == (162, 31, 97)
    assert r["sources"] == {"owner": 118, "node": 35, "coordinator-autoprotect": 9}
    assert D(r["fifo_gross_usd"]) == D("-15372.014069821952")
    assert D(r["lifo_gross_usd"]) == D("-14810.944196821952")
    assert r["first_fill"] == "2026-10-29T02:36:48.401546Z"
    assert r["last_fill"] == "2026-11-03T15:48:12.528314Z"
    assert r["unmatched_sells"] and r["open_lots"]
    assert r["paired"] is False and r["tier"] == "OBSERVED_ORDER_SUMMARIES"


def test_export_refuses_changed_bytes_before_describing_them(tmp_path):
    from sextant.research.b_export import summarize

    path = tmp_path / "changed.jsonl"
    path.write_text("{}\n")
    with pytest.raises(ValueError, match="SHA-256"):
        summarize(path)
