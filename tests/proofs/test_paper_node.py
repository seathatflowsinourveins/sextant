"""Shared gate proofs; contract fixtures are not a second custody implementation."""

from decimal import Decimal as D
from types import SimpleNamespace as NS
from typing import Any

import pytest
from test_paper_config import ROOT, account, ns

from sextant.paper.config import load_budget
from sextant.paper.runtime import (
    NativeRefusal,
    PaperIntent,
    PaperRuntime,
    PaperServices,
    PendingCancel,
)


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
        if book.registrations.get(cid, {}).get("unsent"):
            raise RuntimeError("a released unsent registration is closed; use a new client ID")
        book.registrations[cid] = dict(
            instrument=instrument, side=side, quantity=str(quantity), source=source
        )

    book.register = register

    def release_unsent(cid, *, reason):
        assert reason
        book.registrations[cid]["unsent"] = reason

    book.release_unsent = release_unsent

    book.refresh = lambda: False  # this contract stub has no file to reload
    book.cancel_sends = lambda cid: book.registrations.get(cid, {}).get("cancel_sends", 0)

    def record_cancel(cid):
        book.registrations[cid]["cancel_sends"] = book.cancel_sends(cid) + 1

    book.record_cancel = record_cancel
    book.record_unanswered = lambda cid: book.registrations[cid].update(cancel_unanswered=True)
    queued, sent = [], []
    budget = load_budget(ROOT / "lanes/limits.yaml", cfg.lane)

    class Values(dict):  # row 8's Controls: seconds stored, nanoseconds read
        def ns(self, name):
            return int(self[name] * 1_000_000_000)

    values = Values(request_budget=180, broker_limit=200, window_s=D("60"), max_cancel_retries=3)
    values.update(cancel_timeout_s=D("10"))
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
        prepare=lambda intent: lambda: sent.append(intent),
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
    assert boundary.book.registrations["A001-1"]["unsent"]  # never sent: custody closes it


def test_unknown_or_future_custody_never_opens_entry(boundary):
    boundary.book.snapshot.complete = False
    assert not boundary.runtime.request(intent())
    boundary.book.snapshot.complete = True
    boundary.book.snapshot.known_at = boundary.clock[0] + 1
    assert not boundary.runtime.request(intent())


def test_registration_precedes_native_dispatch_and_duplicate_id_is_refused(boundary):
    def prepare(value):
        assert value.client_order_id not in boundary.book.registrations  # validation first

        def command():
            assert value.client_order_id in boundary.book.registrations  # durable before submit
            boundary.sent.append(value)

        return command

    boundary.runtime.prepare = prepare
    assert boundary.runtime.request(intent())
    flush(boundary)
    assert len(boundary.sent) == 1
    assert not boundary.runtime.request(intent())


def test_the_runtime_runs_its_own_hook_before_the_native_command(boundary):
    """#163 gate P0: the native layer only prepares; it never receives the hook, so a command
    runs only after the runtime has registered and counted it (upstream RestCaller.call)."""
    calls: list[str] = []

    def prepare(value):
        calls.append("prepare")
        return lambda: calls.append(f"command:{'A001-1' in boundary.book.registrations}")

    boundary.runtime.prepare = prepare
    assert boundary.runtime.request(intent("EXIT"))
    _kind, send, options = boundary.queued.pop()
    assert options["admission"]()
    send(lambda: calls.append("counted"))
    assert calls == ["prepare", "counted", "command:True"]
    assert boundary.runtime.request(intent("EXIT", cid="A001-2"))
    _kind, send, options = boundary.queued.pop()
    assert options["admission"]()

    def refusing_pacer():
        raise ValueError("one admitted paced action permits one wire request")

    send(refusing_pacer)
    assert calls[-1] == "prepare" and boundary.guard.active  # the command never ran
    assert boundary.book.registrations["A001-2"]["unsent"]


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
    assert boundary.book.registrations["A001-1"]["unsent"]  # lineage kept, closed as unsent
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
    assert boundary.book.registrations["A001-1"]["unsent"]


def test_possible_send_failure_retains_lineage_and_halts(boundary):
    def command():
        raise TimeoutError("fixture unknown native outcome")

    boundary.runtime.prepare = lambda _value: command
    assert boundary.runtime.request(intent())
    with pytest.raises(TimeoutError):
        flush(boundary)
    assert "unsent" not in boundary.book.registrations["A001-1"]  # the hook counted it: unknown
    assert not boundary.guard.active


def test_native_validation_before_wire_refuses_without_halting(boundary):
    def prepare(_value):
        raise NativeRefusal("fixture native validation refused")

    boundary.runtime.prepare = prepare
    assert boundary.runtime.request(intent())
    flush(boundary)
    assert boundary.guard.active
    assert boundary.runtime.last_refusal is not None
    assert boundary.sent == []
    assert boundary.book.registrations == {}  # native validation precedes durable registration


def test_only_a_read_cancel_timeout_s_after_the_pending_stamp_records_the_cancel(boundary):
    """#195: the age is the read's, not the clock's. A pending cancel stays a quiet refusal
    until a read taken cancel_timeout_s (10 s) after rc8's stamp still shows the order open."""
    stamp = boundary.clock[0]
    boundary.book.registrations["A001-1"] = dict(
        instrument="AAPL.XNAS", side="BUY", quantity="1", source="FIXTURE resting entry"
    )

    def prepare(_value):
        raise PendingCancel(stamp)

    def cancel(read_after_stamp):
        boundary.clock[0] = stamp + 600 * 1_000_000_000  # the clock is long past the stamp
        boundary.book.snapshot.known_at = stamp + read_after_stamp
        assert boundary.runtime.request(intent("CANCEL"))
        flush(boundary)
        return boundary.runtime.last_refusal, boundary.guard.active

    boundary.runtime.prepare = prepare
    pending = "native validation refused: native order is already pending cancel"
    assert cancel(10 * 1_000_000_000 - 1) == (pending, True)
    assert "cancel_unanswered" not in boundary.book.registrations["A001-1"]
    assert cancel(10 * 1_000_000_000) == ("cancel unanswered for A001-1", False)
    assert boundary.book.registrations["A001-1"]["cancel_unanswered"] is True  # durable mark
    assert boundary.sent == [] and "cancel_sends" not in boundary.book.registrations["A001-1"]

    def unwritable(_cid):
        raise OSError("custody disk full")

    boundary.book.record_unanswered = unwritable  # admission stays total: it halts, never raises
    boundary.guard.active = True
    assert cancel(10 * 1_000_000_000) == (
        "admission error halts: OSError: custody disk full",
        False,
    )


@pytest.mark.parametrize("error", [TimeoutError("t"), RuntimeError("r"), ValueError("v")])
def test_an_unexpected_prepare_error_registers_nothing_and_halts(boundary, error):
    """Only NativeRefusal is a quiet refusal. Any other error while preparing halts, and the
    runtime has registered and sent nothing (#163 gate P1-C)."""

    def prepare(_value):
        raise error

    boundary.runtime.prepare = prepare
    assert boundary.runtime.request(intent("EXIT"))
    flush(boundary)  # an admission error before the token halts and pops (#163 P1-2)
    assert not boundary.guard.active and type(error).__name__ in boundary.runtime.last_error
    assert boundary.book.registrations == {} and boundary.sent == []


def test_a_refusal_at_the_pacer_hook_is_released_without_a_halt(boundary):
    def pacer_hook():
        raise ValueError("one admitted paced action permits one wire request")

    assert boundary.runtime.request(intent("EXIT"))
    _kind, send, options = boundary.queued[0]
    assert options["admission"]()
    send(pacer_hook)
    assert boundary.sent == [] and boundary.guard.active
    assert boundary.book.registrations["A001-1"]["unsent"]
    assert boundary.runtime.last_refusal.startswith("refused at the wire hook")


@pytest.mark.parametrize("error", [ValueError("after the hook"), TimeoutError("after the hook")])
def test_an_error_once_the_wire_is_counted_is_never_released(boundary, error):
    def command():
        raise error

    boundary.runtime.prepare = lambda _value: command
    assert boundary.runtime.request(intent("EXIT"))
    with pytest.raises(type(error)):
        flush(boundary)
    assert "unsent" not in boundary.book.registrations["A001-1"]
    assert not boundary.guard.active


def test_final_admission_error_is_not_native_validation(boundary):
    def submit_allowed(_iid, _side, _qty, own_id):
        if own_id is not None:
            raise ValueError("fixture invalid custody admission state")
        return True

    boundary.services.submit_allowed = submit_allowed
    assert boundary.runtime.request(intent())
    flush(boundary)  # the error halts inside admission, which returns False (#163 P1-2)
    assert not boundary.guard.active
    assert boundary.sent == []
    assert boundary.book.registrations["A001-1"]["unsent"]  # halted, and never sent
    assert "admission error halts" in boundary.runtime.last_refusal


def test_validation_error_once_wire_hook_returns_still_halts(boundary):
    """A raise inside row 8's hook is a refusal before counting (pacer.py; #151 review)."""

    def command():
        raise ValueError("fixture native failure after accounting")

    boundary.runtime.prepare = lambda _value: command
    assert boundary.runtime.request(intent())
    _kind, send, _options = boundary.queued[0]
    with pytest.raises(ValueError):
        send(lambda: None)
    assert not boundary.guard.active
    assert "unsent" not in boundary.book.registrations["A001-1"]


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


def test_an_admission_error_at_the_drain_halts_and_pops_instead_of_wedging(boundary):
    """#163 #88 review P1-2: the pacer pops a False; a raise would stay at the queue head."""

    def submit_allowed(_iid, _side, _qty, _own_id):
        raise ValueError("fixture admission error at drain")

    assert boundary.runtime.request(intent("EXIT"))
    boundary.services.submit_allowed = submit_allowed
    _kind, _send, options = boundary.queued[0]
    assert options["admission"]() is False
    assert not boundary.guard.active and boundary.book.registrations == {}


def test_a_late_denial_releases_only_this_writers_live_registration(boundary):
    """A denial after the lease closed, or for another writer's row, rewrites nothing."""
    assert boundary.runtime.request(intent("EXIT"))
    flush(boundary)
    boundary.book.register("A001-other", "AAPL.XNAS", "SELL", D("1"), source="another writer")
    boundary.runtime.denied("A001-other", "fixture denial")
    assert "unsent" not in boundary.book.registrations["A001-other"]
    boundary.runtime.close()
    boundary.runtime.denied("A001-1", "fixture late denial")
    assert "unsent" not in boundary.book.registrations["A001-1"]


def test_a_cancel_refused_at_the_pacer_hook_keeps_the_real_reason(boundary):
    boundary.book.register("A001-1", "AAPL.XNAS", "BUY", D("1"), source="fixture")
    assert boundary.runtime.request(intent("CANCEL"))
    _kind, send, options = boundary.queued[0]
    assert options["admission"]()

    def pacer_hook():
        boundary.runtime._refuse("fixture refusal inside the pacer's recheck")
        raise ValueError("one admitted paced action permits one wire request")

    send(pacer_hook)
    assert boundary.runtime.last_refusal == (
        "refused at the wire hook: fixture refusal inside the pacer's recheck"
    )
    assert boundary.guard.active


def test_close_clears_the_runtime_bookkeeping(boundary):
    assert boundary.runtime.request(intent("EXIT"))
    flush(boundary)
    assert boundary.runtime._registrars
    boundary.runtime.close()
    assert boundary.runtime._registrars == {} and boundary.runtime._kill_prices == {}
