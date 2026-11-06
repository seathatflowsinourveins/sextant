"""Shared gate proofs; contract fixtures are not a second custody implementation."""

from decimal import Decimal as D
from types import SimpleNamespace as NS
from typing import Any

import pytest
from test_paper_config import ROOT, account, ns

from sextant.paper.config import load_budget
from sextant.paper.runtime import PaperIntent, PaperRuntime, PaperServices


@pytest.fixture
def boundary():
    cfg = account()
    clock = [ns("2026-11-06T10:00:00")]
    scope = NS(key=cfg.scope_key)
    lease = NS(scope=scope, held=False, token=None)
    lease.acquire = lambda: (setattr(lease, "held", True), setattr(lease, "token", object()))
    lease.close = lambda: (setattr(lease, "held", False), setattr(lease, "token", None))
    guard = NS(scope=scope, loaded=True, active=True, gates=NS(mode="paper"))
    guard.entry_allowed = lambda: guard.active
    guard.kill = lambda _reason, **_kwargs: setattr(guard, "active", False)
    guard.step = lambda *_args, **_kwargs: []
    book = NS(scope=scope, loaded=True, frozen={}, registrations={})
    book.snapshot = NS(complete=True, known_at=clock[0], positions={}, orders=())
    book.may_cancel = lambda cid: cid in book.registrations
    book.may_replace = book.may_cancel
    book.submission_ready = lambda _iid, *, exclude_client_id=None: True
    book.available_exit = lambda _iid, *, exclude_client_id=None: D("10")

    def register(cid, instrument, side, quantity, *, source):
        book.registrations[cid] = dict(
            instrument=instrument, side=side, quantity=str(quantity), source=source
        )

    book.register = register
    queued, sent = [], []
    budget = load_budget(ROOT / "lanes/limits.yaml", cfg.lane)
    values = dict(request_budget=180, broker_limit=200, window_s=D("60"))
    pacer = NS(controls=values)
    pacer.request = lambda kind, send, **kwargs: queued.append((kind, send, kwargs))
    pacer.drain = lambda: None
    services = PaperServices(
        lease,
        book,
        pacer,
        guard,
        dict(CANCEL=0, REDUCE=1, MODIFY=2, QUERY=3, SUBMIT=4),
        submit_allowed=lambda *_args: True,
        eligible=lambda *_args: True,
        exit_price=lambda *_args: D("10.00"),
    )
    runtime = PaperRuntime(
        cfg,
        budget,
        services,
        now_ns=lambda: clock[0],
        send=lambda intent, before_wire: (before_wire(), sent.append(intent)),
    )
    runtime.open()
    return NS(
        config=cfg,
        clock=clock,
        lease=lease,
        guard=guard,
        book=book,
        pacer=pacer,
        services=services,
        runtime=runtime,
        queued=queued,
        sent=sent,
    )


def intent(action="ENTRY", cid="A001-1", **changes):
    values: dict[str, Any] = dict(
        action=action,
        client_order_id=cid,
        instrument="AAPL.XNAS",
        quantity=None if action in {"CANCEL", "MODIFY"} else D("1"),
        price=D("10.00"),
    )
    return PaperIntent(**(values | changes))


def flush(boundary):
    for _kind, send, options in list(boundary.queued):
        if options["admission"]():
            send(lambda: None)
    boundary.queued.clear()


def test_queue_wait_is_rechecked_after_owner_halt(boundary):
    assert boundary.runtime.request(intent())
    boundary.runtime.halt("owner")
    flush(boundary)
    assert boundary.sent == []
    assert boundary.book.registrations == {}


def test_callback_rechecks_halt_even_if_pacer_precheck_was_true(boundary):
    assert boundary.runtime.request(intent())
    _kind, send, options = boundary.queued[0]
    assert options["admission"]()
    boundary.guard.active = False
    send(lambda: pytest.fail("denied native command must not consume wire accounting"))
    assert boundary.sent == []


def test_queued_entry_is_refused_after_actual_xnys_early_close(boundary):
    boundary.clock[0] = ns("2026-11-27T12:59:59")
    assert boundary.runtime.request(intent())
    boundary.clock[0] = ns("2026-11-27T13:00:00")
    flush(boundary)
    assert boundary.sent == []


def test_halted_guard_allows_only_known_residual_protection(boundary):
    boundary.guard.active = False
    assert not boundary.runtime.request(intent())
    assert boundary.runtime.request(intent("PROTECT"))
    flush(boundary)
    assert [i.action for i in boundary.sent] == ["PROTECT"]


def test_owner_client_id_never_reaches_cancel_or_modify_sink(boundary):
    for action in ("CANCEL", "MODIFY"):
        assert not boundary.runtime.request(intent(action, cid="owner-1"))
    assert boundary.queued == [] and boundary.sent == []


def test_prefix_alone_grants_no_house_custody(boundary):
    assert not boundary.runtime.request(intent("CANCEL"))
    assert not boundary.runtime.request(intent("MODIFY"))


def test_registered_house_lineage_is_used_for_cancel(boundary):
    boundary.book.register("A001-1", "AAPL.XNAS", "BUY", D("1"), source="fixture")
    assert boundary.runtime.request(intent("CANCEL"))
    assert boundary.queued[0][0] == 0
    flush(boundary)
    assert [i.action for i in boundary.sent] == ["CANCEL"]


def test_custody_pending_submission_refusal_is_consumed(boundary):
    boundary.services.submit_allowed = lambda *_args: False
    assert not boundary.runtime.request(intent("EXIT"))
    assert boundary.sent == []


@pytest.mark.parametrize("action", ["EXIT", "PROTECT"])
def test_sell_requires_row8_residual_readiness(boundary, action):
    del boundary.book.submission_ready
    assert not boundary.runtime.request(intent(action))
    assert boundary.queued == [] and boundary.sent == []


@pytest.mark.parametrize("action", ["EXIT", "PROTECT"])
def test_permissive_callback_cannot_override_custody_refusal(boundary, action):
    boundary.book.submission_ready = lambda _iid, *, exclude_client_id=None: False
    assert not boundary.runtime.request(intent(action))
    assert boundary.queued == [] and boundary.sent == []


@pytest.mark.parametrize("action", ["EXIT", "PROTECT"])
def test_final_sell_residual_check_excludes_its_own_registration(boundary, action):
    exclusions = []

    def available_exit(_iid, *, exclude_client_id=None):
        exclusions.append(exclude_client_id)
        return D("10")

    boundary.book.available_exit = available_exit
    order = intent(action)
    assert boundary.runtime.request(order)
    flush(boundary)
    assert boundary.sent == [order]
    assert exclusions[0] is None
    assert exclusions[-1] == "A001-1"


@pytest.mark.parametrize("action", ["EXIT", "PROTECT"])
def test_sell_residual_is_rechecked_after_registration(boundary, action):
    boundary.book.available_exit = lambda _iid, *, exclude_client_id=None: (
        D("0") if boundary.book.registrations else D("10")
    )
    assert boundary.runtime.request(intent(action))
    flush(boundary)
    assert boundary.sent == []
    assert "A001-1" in boundary.book.registrations


def test_unknown_or_future_custody_never_opens_entry(boundary):
    boundary.book.snapshot.complete = False
    assert not boundary.runtime.request(intent())
    boundary.book.snapshot.complete = True
    boundary.book.snapshot.known_at = boundary.clock[0] + 1
    assert not boundary.runtime.request(intent())


def test_registration_precedes_native_dispatch_and_duplicate_id_is_refused(boundary):
    def send(value, before_wire):
        assert value.client_order_id in boundary.book.registrations
        before_wire()
        boundary.sent.append(value)

    boundary.runtime.send = send
    assert boundary.runtime.request(intent())
    flush(boundary)
    assert len(boundary.sent) == 1
    assert not boundary.runtime.request(intent())


@pytest.mark.parametrize("action,side", [("ENTRY", "BUY"), ("EXIT", "SELL"), ("PROTECT", "SELL")])
def test_final_submission_admission_excludes_its_registered_reservation(boundary, action, side):
    admissions = []

    def submit_allowed(instrument, order_side, quantity, exclude_client_id):
        admissions.append(
            (instrument, order_side, quantity, exclude_client_id, bool(boundary.book.registrations))
        )
        return True

    boundary.services.submit_allowed = submit_allowed
    order = intent(action)
    assert boundary.runtime.request(order)
    flush(boundary)
    assert boundary.sent == [order]
    assert admissions[0] == ("AAPL.XNAS", side, D("1"), None, False)
    assert admissions[-1] == ("AAPL.XNAS", side, D("1"), "A001-1", True)


@pytest.mark.parametrize("action", ["ENTRY", "EXIT", "PROTECT"])
def test_final_submission_refusal_preserves_lineage_without_dispatch(boundary, action):
    boundary.services.submit_allowed = lambda _iid, _side, _qty, own_id: own_id is None
    order = intent(action)
    assert boundary.runtime.request(order)
    _kind, send, options = boundary.queued[0]
    assert options["admission"]()
    wire = []
    send(lambda: wire.append("accounted"))
    assert boundary.sent == []
    assert wire == []
    assert "A001-1" in boundary.book.registrations
    assert not boundary.runtime.request(order)


def test_owner_halt_during_registration_prevents_native_dispatch(boundary):
    register = boundary.book.register

    def register_and_halt(*args, **kwargs):
        register(*args, **kwargs)
        boundary.guard.active = False

    boundary.book.register = register_and_halt
    assert boundary.runtime.request(intent())
    flush(boundary)
    assert boundary.sent == []
    assert "A001-1" in boundary.book.registrations


def test_possible_send_failure_retains_lineage_and_halts(boundary):
    def failed_send(_value, before_wire):
        before_wire()
        raise TimeoutError("fixture unknown native outcome")

    boundary.runtime.send = failed_send
    assert boundary.runtime.request(intent())
    with pytest.raises(TimeoutError):
        flush(boundary)
    assert "A001-1" in boundary.book.registrations
    assert not boundary.guard.active


def test_native_validation_before_wire_refuses_without_halting(boundary):
    def invalid_send(_value, _before_wire):
        raise ValueError("fixture native validation refused")

    boundary.runtime.send = invalid_send
    assert boundary.runtime.request(intent())
    flush(boundary)
    assert boundary.guard.active
    assert boundary.runtime.last_refusal is not None
    assert boundary.sent == []
    assert "A001-1" in boundary.book.registrations


def test_unexpected_error_before_wire_still_halts(boundary):
    def failed_send(_value, _before_wire):
        raise RuntimeError("fixture unexpected native failure")

    boundary.runtime.send = failed_send
    assert boundary.runtime.request(intent())
    with pytest.raises(RuntimeError):
        flush(boundary)
    assert not boundary.guard.active


def test_final_admission_error_is_not_native_validation(boundary):
    def submit_allowed(_iid, _side, _qty, own_id):
        if own_id is not None:
            raise ValueError("fixture invalid custody admission state")
        return True

    boundary.services.submit_allowed = submit_allowed
    assert boundary.runtime.request(intent())
    with pytest.raises(ValueError):
        flush(boundary)
    assert not boundary.guard.active
    assert boundary.sent == []


@pytest.mark.parametrize("inside_hook", [False, True])
def test_validation_error_once_wire_hook_starts_still_halts(boundary, inside_hook):
    def failed_send(_value, before_wire):
        before_wire()
        raise ValueError("fixture native failure after accounting")

    def before_wire():
        if inside_hook:
            raise ValueError("fixture accounting hook failure")

    boundary.runtime.send = failed_send
    assert boundary.runtime.request(intent())
    _kind, send, _options = boundary.queued[0]
    with pytest.raises(ValueError):
        send(before_wire)
    assert not boundary.guard.active
    assert "A001-1" in boundary.book.registrations


def test_close_fences_already_queued_commands(boundary):
    assert boundary.runtime.request(intent())
    boundary.runtime.close()
    flush(boundary)
    assert boundary.sent == []


def test_reacquiring_the_writer_does_not_revive_its_old_queued_commands(boundary):
    assert boundary.runtime.request(intent())
    boundary.runtime.close()
    boundary.runtime.open()
    flush(boundary)
    assert boundary.sent == []


def test_reduction_does_not_use_entry_session_opt_ins(boundary):
    boundary.clock[0] = ns("2026-11-06T17:00:00")
    assert not boundary.runtime.request(intent())
    assert boundary.runtime.request(intent("EXIT"))
    flush(boundary)
    assert [i.action for i in boundary.sent] == ["EXIT"]


def test_nonlimit_cannot_leave_in_extended_hours(boundary):
    boundary.clock[0] = ns("2026-11-06T17:00:00")
    assert not boundary.runtime.request(
        intent("PROTECT", order_type="STOP_MARKET", trigger_price=D("9.50"))
    )


def test_native_eligibility_is_required_for_protective_send_too(boundary):
    boundary.services.eligible = lambda *_args: False
    assert not boundary.runtime.request(intent("PROTECT"))


@pytest.mark.parametrize(
    "field,value", [("quantity", 1.0), ("price", 10.0), ("price", D("NaN")), ("quantity", D("0"))]
)
def test_intents_reject_nondecimal_or_invalid_money(field, value):
    with pytest.raises(ValueError):
        intent(**{field: value})
