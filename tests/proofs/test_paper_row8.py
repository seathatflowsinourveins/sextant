"""Real row-8 integration drills; explicitly pending until #51's modules land.

The same tests can run against a separately identified row-8 source fixture by
extending sextant.__path__ in the invoking Python process. Nothing is vendored.
"""

import importlib
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace as NS

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
def row8(tmp_path):
    try:
        custody = importlib.import_module("sextant.execution.custody")
        pacing = importlib.import_module("sextant.execution.pacer")
        risk = importlib.import_module("sextant.risk.guard")
        controls = importlib.import_module("sextant.risk.controls")
    except ModuleNotFoundError as error:
        if error.name not in {
            "sextant.execution",
            "sextant.execution.custody",
            "sextant.execution.pacer",
            "sextant.risk",
            "sextant.risk.guard",
            "sextant.risk.controls",
        }:
            raise
        pytest.skip(f"row-8 dependency has not landed: {error.name}")
    values = dict(
        request_budget=180,
        broker_limit=200,
        window_s="60",
        burst_fraction="0.1",
        cancel_timeout_s="10",
        cancel_retry_s="5",
        flatten_tick_s="2",
        backoff_base_s="1",
        backoff_max_s="30",
        reserve_per_open_position=1,
        reserve_per_exiting_position=1,
        observation_reminder_s="300",
        observation_money_step_fraction="0.01",
        observation_leverage_step="0.01",
        observation_max_edges=500,
        max_cancel_retries=3,
    )
    rows = [
        dict(
            name=k,
            value=v,
            source="FIXTURE ONLY: ADR-0007/0009/0010; no deployment authority",
            unit="fixture",
            calibration="UNCALIBRATED",
            last_change="2026-11-06",
            scope="FIXTURE_ONLY",
        )
        for k, v in values.items()
    ]
    params = controls.Controls.from_rows(rows, fixture=True)
    cfg = account()
    clock = [ns("2026-11-06T10:00:00")]
    scope = custody.AccountScope(cfg.broker, cfg.account_id)
    book = custody.Custody(scope, tmp_path / "custody.json", create=True)
    snapshot = custody.AccountSnapshot(scope, 1, {}, {}, (), True, clock[0], "TEST positive flat")
    assert book.observe(snapshot, now=clock[0])
    guard = risk.Guard(scope, tmp_path / "guard.json", tmp_path / "kill", params, mode="paper")
    guard.initialize(book.flat_receipt())
    lease = custody.WriterLease(scope, tmp_path / "locks", "shared-paper-test")
    pacer = pacing.AccountPacer(params, lambda: clock[0])
    sent = []

    def prepare(intent):
        return lambda: sent.append(intent)

    services = PaperServices(
        lease,
        book,
        pacer,
        guard,
        pacing.ActionKind.__members__,
        # Flat fixture entries only; residual admission is a separate #51 seam.
        submit_allowed=lambda *_args: True,
        eligible=lambda *_args: True,
        exit_price=lambda *_args: None,
    )
    runtime = PaperRuntime(
        cfg,
        load_budget(ROOT / "lanes/limits.yaml", cfg.lane),
        services,
        now_ns=lambda: clock[0],
        prepare=prepare,
    )
    return NS(
        cfg=cfg,
        clock=clock,
        scope=scope,
        book=book,
        guard=guard,
        lease=lease,
        pacer=pacer,
        services=services,
        runtime=runtime,
        sent=sent,
        custody_module=custody,
        params=params,
        risk_module=risk,
    )


def test_one_writer_is_refused_twice_across_different_lane_labels(row8, tmp_path):
    row8.runtime.open()
    second = row8.custody_module.WriterLease(row8.scope, tmp_path / "locks", "other-lane")
    try:
        for _attempt in range(2):
            with pytest.raises(row8.custody_module.CustodyError):
                second.acquire()
        assert not second.held and row8.lease.held
    finally:
        row8.runtime.close()
        second.close()


def test_shared_path_keeps_real_pacer_below_the_limit_sheet(row8):
    row8.runtime.open()
    try:
        for number in range(240):
            row8.clock[0] += 250_000_000
            row8.runtime.request(
                PaperIntent("ENTRY", f"A001-{number}", "AAPL.XNAS", D("1"), D("10"))
            )
            row8.pacer.drain()
        assert 0 < len(row8.sent) <= 180
        assert row8.pacer.wire_requests == len(row8.sent)
        row8.runtime.halt("owner")
        before = len(row8.sent)
        row8.clock[0] += 60_000_000_000
        row8.pacer.drain()
        assert len(row8.sent) == before
    finally:
        row8.runtime.close()


def test_halt_leaves_owner_orders_untouched_and_releases_no_entries(row8):
    module = row8.custody_module
    row8.book.register("A001-entry", "AAPL.XNAS", "BUY", D("2"), source="TEST house entry")
    row8.book.link("A001-entry", "house-v")
    house = module.OrderFact("A001-entry", "AAPL.XNAS", "BUY", D("2"), D("0"), "NEW", "house-v")
    owner = module.OrderFact(
        "owner-buy", "AAPL.XNAS", "BUY", D("5"), D("0"), "NEW", "owner-v", True
    )
    snap = module.AccountSnapshot(
        row8.scope, 2, {}, {}, (owner, house), True, row8.clock[0], "TEST owner and house orders"
    )
    assert row8.book.observe(snap, now=row8.clock[0])
    row8.runtime.open()
    try:
        row8.runtime.halt("owner")
        assert [(i.action, i.client_order_id) for i in row8.sent] == [("CANCEL", "A001-entry")]
        assert row8.book.snapshot.orders == (owner, house)
        assert row8.guard.marker.exists()
        assert not row8.guard.entry_allowed()
    finally:
        row8.runtime.close()


def test_repeated_flatten_ticks_do_not_resell_without_a_new_snapshot(row8):
    module = row8.custody_module
    snapshot = module.AccountSnapshot(
        row8.scope,
        2,
        {"AAPL.XNAS": D("10")},
        {"AAPL.XNAS": module.PositionAuthority(D("10"), "FIXTURE reconciled long")},
        (),
        True,
        row8.clock[0],
        "FIXTURE authoritative long before exit",
    )
    assert row8.book.observe(snapshot, now=row8.clock[0])
    row8.services.exit_price = lambda *_args: D("10.00")
    row8.services.submit_allowed = lambda *_args: True
    row8.runtime.open()
    try:
        row8.runtime.halt("owner")
        assert not row8.runtime.request(
            PaperIntent("EXIT", "A001-retry", "AAPL.XNAS", D("10"), D("10.00"))
        )
        for _tick in range(4):
            row8.clock[0] += row8.params.ns("flatten_tick_s")
            row8.runtime.pulse()
        assert [(i.action, i.quantity) for i in row8.sent] == [("EXIT", D("10"))]
        assert row8.pacer.wire_requests == 1
        assert row8.book.snapshot is snapshot
        assert not row8.guard.entry_allowed()
    finally:
        row8.runtime.close()


def long_ten(row8, epoch):
    module = row8.custody_module
    snapshot = module.AccountSnapshot(
        row8.scope,
        epoch,
        {"AAPL.XNAS": D("10")},
        {"AAPL.XNAS": module.PositionAuthority(D("10"), "FIXTURE reconciled long")},
        (),
        True,
        row8.clock[0],
        "FIXTURE authoritative long, no house order reported",
    )
    assert row8.book.observe(snapshot, now=row8.clock[0])
    return snapshot


def in_flight(row8):
    """House SELL quantity registered and not released, but not yet in a broker report."""
    present = {o.client_order_id for o in row8.book.snapshot.orders}
    return sum(
        (
            D(row["quantity"])
            for cid, row in row8.book.registrations.items()
            if row["side"] == "SELL" and cid not in present and not row.get("unsent")
        ),
        D(0),
    )


def test_kill_to_flat_keeps_one_exit_quantity_in_flight_across_ticks_and_a_pause(row8):
    """#123: no new observation, ticks 2 s apart after halt, a paced pause between."""
    snapshot = long_ten(row8, 2)
    row8.services.exit_price = lambda *_args: D("10.00")
    row8.runtime.open()
    try:
        row8.pacer.on_rate_limited(30_000_000_000)  # the first EXIT waits at the pacer
        row8.runtime.halt("owner")
        for _tick in range(5):
            row8.clock[0] += row8.params.ns("flatten_tick_s")
            row8.runtime.pulse()
            assert row8.sent == [] and in_flight(row8) == 0
        row8.clock[0] += 30_000_000_000
        for _tick in range(5):
            row8.runtime.pulse()
            assert in_flight(row8) == D("10")
            row8.clock[0] += row8.params.ns("flatten_tick_s")
        assert [(i.action, i.quantity) for i in row8.sent] == [("EXIT", D("10"))]
        assert row8.pacer.wire_requests == 1
        assert row8.book.snapshot is snapshot and row8.book.available_exit("AAPL.XNAS") == 0
    finally:
        row8.runtime.close()


def protect():
    return PaperIntent(
        "PROTECT", "A001-stop", "AAPL.XNAS", D("10"), order_type="STOP_MARKET",
        trigger_price=D("9.00"),
    )  # fmt: skip


def flatten_after_halt(row8, ticks=4):
    row8.runtime.halt("owner")
    for _tick in range(ticks):
        row8.clock[0] += row8.params.ns("flatten_tick_s")
        row8.runtime.pulse()


def test_a_refusal_after_registration_leaves_kill_to_flat_working(row8):
    """#151: a PROTECT registered, then refused before the wire, is released."""
    long_ten(row8, 2)
    row8.services.exit_price = lambda *_args: D("10.00")
    register = row8.book.register

    def register_then_close(*args, **kwargs):
        register(*args, **kwargs)
        row8.services.eligible = lambda *_args: False  # changes during registration

    row8.book.register = register_then_close
    row8.runtime.open()
    try:
        assert row8.runtime.request(protect())
        assert row8.book.registrations["A001-stop"]["unsent"]  # refused before the command ran
        assert row8.pacer.wire_requests == 0 and row8.guard.entry_allowed()
        row8.book.register, row8.services.eligible = register, lambda *_args: True
        row8.clock[0] += 1_000_000_000
        long_ten(row8, 3)
        assert row8.book.registrations["A001-stop"]["unsent"] and row8.book.frozen == {}
        flatten_after_halt(row8)
        assert [(i.action, i.quantity) for i in row8.sent] == [("EXIT", D("10"))]
        assert in_flight(row8) == D("10") and row8.pacer.wire_requests == 1
        assert "unknown_execution_state" not in row8.guard.reasons
    finally:
        row8.runtime.close()


def test_a_refusal_inside_the_pacer_hook_is_released(row8):
    """#151 review: row 8's pacer refuses inside its hook before counting anything."""
    long_ten(row8, 2)
    row8.services.exit_price = lambda *_args: D("10.00")
    own_checks = []

    def submit_allowed(_iid, _side, _qty, own_id):
        if own_id is None:
            return True
        own_checks.append(own_id)
        return len(own_checks) != 2  # only the pacer's own recheck, after the runtime's

    row8.services.submit_allowed = submit_allowed
    row8.runtime.open()
    try:
        assert row8.runtime.request(protect())
        assert row8.runtime.last_refusal.startswith("refused at the wire hook")
        assert row8.book.registrations["A001-stop"]["unsent"]
        assert row8.pacer.wire_requests == 0 and row8.guard.entry_allowed()
        row8.clock[0] += 1_000_000_000
        long_ten(row8, 3)
        assert row8.book.registrations["A001-stop"]["unsent"]
        flatten_after_halt(row8)
        assert [(i.action, i.quantity) for i in row8.sent] == [("EXIT", D("10"))]
    finally:
        row8.runtime.close()


def test_a_repeated_native_refusal_writes_no_custody_on_any_tick(row8):
    """#151 review: a deterministic refusal on the kill path must not grow custody."""
    long_ten(row8, 2)
    row8.services.exit_price = lambda *_args: D("10.00")

    def uncached(_intent):
        raise NativeRefusal("shared paper slice supports cached US equities only")

    row8.runtime.prepare = uncached
    row8.runtime.open()
    try:
        size = row8.book.path.stat().st_size
        flatten_after_halt(row8, ticks=20)
        assert row8.sent == [] and row8.book.registrations == {}
        assert row8.book.path.stat().st_size == size and row8.pacer.wire_requests == 0
        # Refused before the token, and the kill EXIT waits for a new observation (#88 review).
        assert row8.runtime._denied_epochs == {"AAPL.XNAS": 2}
        assert row8.runtime.last_refusal.startswith("kill exit denied at this observation")
    finally:
        row8.runtime.close()


def test_an_error_once_the_wire_is_counted_keeps_the_exit_reserved(row8):
    """A possibly live EXIT is never released: unknown stays halted and reserved."""
    long_ten(row8, 2)
    native = row8.runtime.prepare

    def counted_then_failed(intent):
        command = native(intent)

        def run():
            command()
            raise ValueError("fixture failure after the wire hook")

        return run

    row8.runtime.prepare = counted_then_failed
    row8.runtime.open()
    try:
        exit_ = PaperIntent("EXIT", "A001-exit", "AAPL.XNAS", D("10"), D("10.00"))
        with pytest.raises(ValueError, match="after the wire hook"):
            row8.runtime.request(exit_)
        assert "unsent" not in row8.book.registrations["A001-exit"]
        assert row8.book.available_exit("AAPL.XNAS") == 0 and in_flight(row8) == D("10")
        assert not row8.guard.entry_allowed()
    finally:
        row8.runtime.close()


def test_one_unknown_exit_does_not_stop_the_other_instruments_flatten(row8):
    """#163 #88 review P2: AAPL's outcome is unknown; MSFT still flattens in the same pulse."""
    module = row8.custody_module
    authority = {
        iid: module.PositionAuthority(D(qty), "FIXTURE reconciled long")
        for iid, qty in (("AAPL.XNAS", "10"), ("MSFT.XNAS", "5"))
    }
    snapshot = module.AccountSnapshot(
        row8.scope, 2, {"AAPL.XNAS": D("10"), "MSFT.XNAS": D("5")}, authority, (), True,
        row8.clock[0], "FIXTURE two authoritative longs",
    )  # fmt: skip
    assert row8.book.observe(snapshot, now=row8.clock[0])
    row8.services.exit_price = lambda *_args: D("10.00")
    native = row8.runtime.prepare

    def ambiguous_aapl(intent):
        command = native(intent)

        def run():
            command()
            if intent.instrument == "AAPL.XNAS":
                raise TimeoutError("fixture ambiguous transport after the wire")

        return run

    row8.runtime.prepare = ambiguous_aapl
    row8.runtime.open()
    try:
        with pytest.raises(TimeoutError):
            row8.runtime.halt("owner")
        assert sorted((i.instrument, i.quantity) for i in row8.sent) == [
            ("AAPL.XNAS", D("10")), ("MSFT.XNAS", D("5")),
        ]  # fmt: skip
        assert "unsent" not in next(
            r for r in row8.book.registrations.values() if r["instrument"] == "AAPL.XNAS"
        )
    finally:
        row8.runtime.close()


def two_longs(row8, epoch=2):
    module = row8.custody_module
    held = {"AAPL.XNAS": D("10"), "MSFT.XNAS": D("5")}
    authority = {
        iid: module.PositionAuthority(q, "FIXTURE reconciled long") for iid, q in held.items()
    }
    snapshot = module.AccountSnapshot(row8.scope, epoch, held, authority, (), True, row8.clock[0],
                                      "FIXTURE two authoritative longs")  # fmt: skip
    assert row8.book.observe(snapshot, now=row8.clock[0])


def test_a_raising_admission_behind_a_pause_cannot_wedge_the_kill_queue(row8):
    """#163 #88 review P1-2: AAPL's queued EXIT errors at the drain head; MSFT still flattens."""
    two_longs(row8)
    row8.services.exit_price = lambda *_args: D("10.00")
    row8.runtime.open()
    try:
        row8.pacer.on_rate_limited(30_000_000_000)
        row8.runtime.halt("owner")  # both EXITs wait at the pacer
        assert row8.sent == [] and len(row8.pacer.queue) == 2

        def submit_allowed(iid, _side, _qty, _own_id):
            if iid == "AAPL.XNAS":
                raise ValueError("fixture admission error for AAPL")
            return True

        row8.services.submit_allowed = submit_allowed
        row8.clock[0] += 30_000_000_000
        row8.runtime.pulse()  # no exception escapes: the bad item is popped, not wedged
        assert [(i.instrument, i.quantity) for i in row8.sent] == [("MSFT.XNAS", D("5"))]
        assert row8.pacer.queue == []
        for _tick in range(3):  # later pulses keep running; nothing re-raises at the head
            row8.clock[0] += row8.params.ns("flatten_tick_s")
            row8.runtime.pulse()
        assert not row8.guard.entry_allowed()
    finally:
        row8.runtime.close()


def test_a_kill_exit_queued_behind_a_pause_goes_out_only_at_the_current_price(row8):
    long_ten(row8, 2)
    prices = [D("10.00")]
    row8.services.exit_price = lambda *_args: prices[-1]
    row8.runtime.open()
    try:
        row8.pacer.on_rate_limited(30_000_000_000)
        row8.runtime.halt("owner")
        prices.append(D("9.90"))  # the market moved while the first EXIT waited
        row8.clock[0] += row8.params.ns("flatten_tick_s")
        row8.runtime.pulse()
        row8.clock[0] += 30_000_000_000
        row8.runtime.pulse()
        assert [(i.action, i.quantity, i.price) for i in row8.sent] == [
            ("EXIT", D("10"), D("9.90"))
        ]
    finally:
        row8.runtime.close()


def test_a_kill_exit_denied_every_tick_retries_once_per_observation(row8):
    """#163 #88 review P3: an rc7 denial must not register a fresh EXIT on every tick."""
    long_ten(row8, 2)
    row8.services.exit_price = lambda *_args: D("10.00")
    native = row8.runtime.prepare

    def denied_after_submit(intent):
        command = native(intent)

        def run():
            command()
            row8.runtime.denied(intent.client_order_id, "fixture RiskEngine denial")

        return run

    row8.runtime.prepare = denied_after_submit
    row8.runtime.open()
    try:
        flatten_after_halt(row8, ticks=20)
        assert len(row8.book.registrations) == 1 and row8.pacer.wire_requests == 1
        assert row8.runtime.last_refusal.startswith("kill exit denied at this observation")
        row8.clock[0] += 1_000_000_000
        long_ten(row8, 3)  # a new observation earns one more attempt
        flatten_after_halt(row8, ticks=3)
        assert len(row8.book.registrations) == 2
    finally:
        row8.runtime.close()


def test_kill_to_flat_drains_every_symbol_under_429_pacing_with_a_moving_price(row8):
    """#163 gate P1-A: a stale-price refusal pops before the token, so no symbol starves."""
    module = row8.custody_module
    held = {f"S{n:02d}.XNAS": D("10") for n in range(8)}
    authority = {
        iid: module.PositionAuthority(q, "FIXTURE reconciled long") for iid, q in held.items()
    }
    snapshot = module.AccountSnapshot(row8.scope, 2, held, authority, (), True, row8.clock[0],
                                      "FIXTURE eight authoritative longs")  # fmt: skip
    assert row8.book.observe(snapshot, now=row8.clock[0])
    start, tick = row8.clock[0], row8.params.ns("flatten_tick_s")
    row8.services.exit_price = lambda _iid, now: D("10.00") - D("0.01") * ((now - start) // tick)
    row8.runtime.open()
    try:
        row8.pacer.on_rate_limited(30_000_000_000)  # one 429 just before the owner halt
        row8.runtime.halt("owner")
        for _tick in range(30):  # 60 s of ticks, the price falling a cent each tick
            row8.clock[0] += tick
            row8.runtime.pulse()
        flattened = {i.instrument for i in row8.sent if i.action == "EXIT"}
        assert flattened == set(held) and len(row8.sent) == len(held)
        assert len(row8.pacer.queue) <= len(held)  # one queued kill EXIT per symbol at most
    finally:
        row8.runtime.close()


def test_a_denied_protect_does_not_silence_that_symbols_kill(row8):
    """#163 gate P1-D: only a denied kill EXIT waits for a new observation."""
    long_ten(row8, 2)
    row8.services.exit_price = lambda *_args: D("10.00")
    native = row8.runtime.prepare

    def deny_the_protect(intent):
        command = native(intent)

        def run():
            command()
            if intent.action == "PROTECT":
                row8.runtime.denied(intent.client_order_id, "fixture RiskEngine denial")

        return run

    row8.runtime.prepare = deny_the_protect
    row8.runtime.open()
    try:
        assert row8.runtime.request(protect())
        assert row8.book.registrations["A001-stop"]["unsent"]  # an rc7 denial releases at once
        row8.clock[0] += 1_000_000_000
        flatten_after_halt(row8, ticks=1)  # no new observation, yet the halt flattens AAPL
        assert [(i.action, i.quantity) for i in row8.sent if i.action == "EXIT"] == [
            ("EXIT", D("10"))
        ]
    finally:
        row8.runtime.close()


def test_corrupt_guard_state_stays_unknown_and_halted(row8, tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{")
    row8.services.guard = row8.risk_module.Guard(
        row8.scope, path, tmp_path / "unknown-kill", row8.params, mode="paper"
    )
    row8.runtime.open()
    try:
        assert not row8.runtime.request(
            PaperIntent("ENTRY", "A001-unknown", "AAPL.XNAS", D("1"), D("10"))
        )
        row8.runtime.halt("owner")
        row8.runtime.pulse()
        assert not row8.services.guard.entry_allowed()
        assert not row8.services.guard.loaded
        assert row8.sent == []
        assert path.read_text() == "{"
    finally:
        row8.runtime.close()


def test_a_prepare_error_registers_nothing_and_the_next_tick_flattens_once(row8):
    """#163 gate P1-C: an unexpected error while preparing halts with no row; the next flatten
    tick sends exactly one EXIT, and no tick resells without a new observation."""
    long_ten(row8, 2)
    row8.services.exit_price = lambda *_args: D("10.00")
    native, calls = row8.runtime.prepare, []

    def fails_once(intent):
        calls.append(intent.client_order_id)
        if len(calls) == 1:
            raise RuntimeError("fixture bug while preparing")
        return native(intent)

    row8.runtime.prepare = fails_once
    row8.runtime.open()
    try:
        row8.runtime.halt("owner")  # the error halts in admission, before the token (P1-2)
        assert "RuntimeError" in row8.runtime.last_error
        assert row8.book.registrations == {} and row8.sent == []
        for _tick in range(5):
            row8.clock[0] += row8.params.ns("flatten_tick_s")
            row8.runtime.pulse()
        assert [(i.action, i.quantity) for i in row8.sent] == [("EXIT", D("10"))]
    finally:
        row8.runtime.close()


def test_a_reopened_writer_reloads_custody_and_never_resells_the_next_writers_exit(row8):
    """#163 author review: writer A stops, another writer registers its kill EXIT in the file,
    and A starts again. A reloads on acquire, so it neither erases that row nor sells the
    position a second time."""
    long_ten(row8, 2)
    row8.services.exit_price = lambda *_args: D("10.00")
    native, calls = row8.runtime.prepare, []

    def fails_once(intent):
        calls.append(intent.client_order_id)
        if len(calls) == 1:
            raise RuntimeError("fixture bug while preparing")
        return native(intent)

    row8.runtime.prepare = fails_once
    row8.runtime.open()
    row8.runtime.halt("owner")  # the error halts in admission, before the token (P1-2)
    row8.runtime.close()  # writer A stops
    module = row8.custody_module
    other = module.Custody(row8.scope, row8.book.path)  # the next writer, from the file
    other.register("A001-b-kill", "AAPL.XNAS", "SELL", D("10"), source="FIXTURE next writer")
    row8.runtime.open()  # writer A again: load-on-acquire
    try:
        assert "A001-b-kill" in row8.book.registrations and row8.book.snapshot is None
        row8.clock[0] += row8.params.ns("flatten_tick_s")
        long_ten(row8, 3)
        for _tick in range(4):
            row8.clock[0] += row8.params.ns("flatten_tick_s")
            row8.runtime.pulse()
        assert row8.sent == []  # the other writer's unreported EXIT still reserves the long
        assert "A001-b-kill" in module.Custody(row8.scope, row8.book.path).registrations
    finally:
        row8.runtime.close()


def test_a_native_refusal_on_the_kill_path_spends_no_token_and_waits_for_an_observation(row8):
    """#88 review of 512660b (the shipped send): a deterministic native refusal used to come
    after the pacer's token, and kill-to-flat re-queued it every tick. It is now refused before
    the token, and the refused kill EXIT waits for a new observation, so MSFT still flattens."""
    two_longs(row8, 2)
    start, tick = row8.clock[0], row8.params.ns("flatten_tick_s")
    row8.services.exit_price = lambda _iid, now: D("10.00") - D("0.01") * ((now - start) // tick)
    native, taken = row8.runtime.prepare, []
    take = row8.pacer.bucket.take
    row8.pacer.bucket.take = lambda now: taken.append(now) or take(now)

    def aapl_uncached(intent):
        if intent.instrument == "AAPL.XNAS":
            raise NativeRefusal("shared paper slice supports cached US equities only")
        return native(intent)

    row8.runtime.prepare = aapl_uncached
    row8.runtime.open()
    try:
        row8.pacer.on_rate_limited(30_000_000_000)  # one 429 just before the owner halt
        row8.runtime.halt("owner")
        for _tick in range(30):  # 60 s of ticks, the price falling a cent each tick
            row8.clock[0] += tick
            row8.runtime.pulse()
        assert [(i.instrument, i.quantity) for i in row8.sent] == [("MSFT.XNAS", D("5"))]
        assert len(taken) == 1 and row8.pacer.wire_requests == 1  # AAPL never spent a token
        assert row8.runtime._denied_epochs == {"AAPL.XNAS": 2}
    finally:
        row8.runtime.close()


def test_an_invalid_kill_exit_price_grows_no_bookkeeping_and_never_raises(row8):
    """#88 review of 512660b (low): the kill EXIT is validated before any bookkeeping."""
    long_ten(row8, 2)
    row8.services.exit_price = lambda *_args: D("0")
    row8.runtime.open()
    try:
        row8.runtime.halt("owner")
        for _tick in range(5):
            row8.clock[0] += row8.params.ns("flatten_tick_s")
            row8.runtime.pulse()
        assert row8.runtime._kill_prices == {} and row8.runtime._kill_cids == set()
        assert row8.sent == [] and "kill exit invalid" in (row8.runtime.last_error or "")
    finally:
        row8.runtime.close()


def read(row8, longs, entries):
    """A complete read of the longs and these entry facts, in which every house EXIT still
    rests, so custody freezes nothing."""
    module, book = row8.custody_module, row8.book
    exits = tuple(
        module.OrderFact(cid, row["instrument"], "SELL", D(row["quantity"]), D("0"), "NEW", None)
        for cid, row in book.registrations.items()
        if row["side"] == "SELL" and not row.get("unsent")
    )
    authority = {
        iid: module.PositionAuthority(q, "FIXTURE reconciled long") for iid, q in longs.items()
    }
    epoch, now = book.snapshot.epoch + 1, row8.clock[0]
    orders = (*entries, *exits)
    snapshot = module.AccountSnapshot(row8.scope, epoch, longs, authority, orders, True, now, "R")
    assert book.observe(snapshot, now=now)


def resting_entries(row8, k, longs):
    module, entries = row8.custody_module, []
    for n in range(k):
        cid, iid = f"A001-entry{n:02d}", f"E{n:02d}.XNAS"
        row8.book.register(cid, iid, "BUY", D("1"), source="FIXTURE resting house entry")
        row8.book.link(cid, f"v{n}")
        entries.append(module.OrderFact(cid, iid, "BUY", D("1"), D("0"), "NEW", f"v{n}"))
    read(row8, longs, entries)
    return entries


def lost_cancels(row8):
    """rc8's cancel state as the shipped _prepare reads it (test_paper_native proves it in
    rc8): a CANCEL that leaves marks the order PENDING_CANCEL at that time, and a later CANCEL
    raises PendingCancel before the token. Nothing ever answers, as when a cancel is lost."""
    stamps: dict[str, int] = {}
    prepare = row8.runtime.prepare

    def native(intent):
        cid = intent.client_order_id
        if intent.action == "CANCEL" and cid in stamps:
            raise PendingCancel(stamps[cid])
        command = prepare(intent)

        def run():
            if intent.action == "CANCEL":
                stamps[cid] = row8.clock[0]
            command()

        return run

    row8.runtime.prepare = native
    return stamps


@pytest.mark.parametrize("answer", ["lost", "rejected"])
def test_unacknowledged_entry_cancels_cannot_starve_the_kill_exits(row8, answer):
    """#187 and #195: during a halt the guard re-emits CANCEL_ENTRY every cancel_retry_s, and
    CANCEL outranks REDUCE; every read still shows the entries open. A lost cancel leaves rc8's
    order pending, so each entry sends one CANCEL and every re-emission is refused before the
    token; the first read taken cancel_timeout_s after an entry's stamp records the unknown
    outcome and marks that entry. A rejected cancel returns the order to its prior state, so
    every CANCEL leaves until the cap of max_cancel_retries + 1. With 24 entries every long
    flattens, and the first kill EXIT goes out within 20 s (lost) or 40 s (rejected)."""
    k, longs = 24, {"AAPL.XNAS": D("10"), "MSFT.XNAS": D("10")}
    entries = resting_entries(row8, k, longs)
    stamps = lost_cancels(row8) if answer == "lost" else {}
    row8.services.exit_price = lambda *_args: D("10.00")
    kills: list[tuple[str, int]] = []
    kill = row8.guard.kill
    row8.guard.kill = lambda reason, **kw: (
        kills.append((reason, row8.clock[0])) or kill(reason, **kw)
    )
    row8.runtime.open()
    try:
        row8.pacer.bucket.tokens = 0  # the burst is already spent
        start, first_exit, peak = row8.clock[0], None, 0
        row8.runtime.halt("owner")
        for _tick in range(150):  # 300 s of 2 s pulses; every read still shows all orders open
            row8.clock[0] += row8.params.ns("flatten_tick_s")
            read(row8, longs, entries)
            row8.runtime.pulse()
            peak = max(peak, len(row8.pacer.queue))
            if first_exit is None and any(i.action == "EXIT" for i in row8.sent):
                first_exit = row8.clock[0] - start
        exits = sorted((i.instrument, i.quantity) for i in row8.sent if i.action == "EXIT")
        assert exits == [("AAPL.XNAS", D("10")), ("MSFT.XNAS", D("10"))]
        bound = 20 if answer == "lost" else 40
        assert first_exit is not None and first_exit <= bound * 1_000_000_000
        sends = 1 if answer == "lost" else row8.pacer.controls["max_cancel_retries"] + 1
        cancels = [i.client_order_id for i in row8.sent if i.action == "CANCEL"]
        assert all(cancels.count(e.client_order_id) == sends for e in entries)
        assert all(row8.book.cancel_sends(e.client_order_id) == sends for e in entries)  # durable
        assert row8.pacer.wire_requests == len(row8.sent)  # no refusal spent a token
        assert peak <= k + 2  # one CANCEL per order queued, plus the kill EXITs
        (recorded,) = [at for reason, at in kills if reason == "unknown_execution_outcome"]
        if answer == "rejected":
            assert row8.runtime.last_error.startswith("cancel retries exhausted for")
            return
        timeout, retry = (row8.params.ns(n) for n in ("cancel_timeout_s", "cancel_retry_s"))
        first = min(stamps.values())
        assert first + timeout <= recorded <= first + timeout + retry + 2 * 1_000_000_000
        assert row8.runtime.last_error.startswith("cancel unanswered for A001-entry")
        marked = [
            cid for cid, row in row8.book.registrations.items() if row.get("cancel_unanswered")
        ]
        assert sorted(marked) == sorted(e.client_order_id for e in entries)  # each one, durably
    finally:
        row8.runtime.close()


def test_a_read_showing_the_order_closed_never_records_its_cancel(row8):
    """#195 author review: the venue took the cancel and the read says so, while rc8 still
    holds PENDING_CANCEL. That read refuses the CANCEL before the native layer, so nothing is
    recorded and the active account keeps trading."""
    longs = {"AAPL.XNAS": D("10")}
    (entry,) = resting_entries(row8, 1, longs)
    lost_cancels(row8)
    cid, iid = entry.client_order_id, entry.instrument
    row8.runtime.open()
    try:
        assert row8.runtime.request(PaperIntent("CANCEL", cid, iid))
        row8.runtime.pulse()  # the CANCEL leaves; rc8 stamps PENDING_CANCEL
        assert row8.book.cancel_sends(cid) == 1
        row8.clock[0] += 12 * 1_000_000_000  # past cancel_timeout_s
        read(row8, longs, [replace(entry, status="CANCELED")])
        assert not row8.runtime.request(PaperIntent("CANCEL", cid, iid))
        assert row8.runtime.last_refusal == "no current house lineage for this action"
        assert row8.guard.entry_allowed() and row8.runtime.last_error is None
        assert not row8.book.registrations[cid].get("cancel_unanswered")
    finally:
        row8.runtime.close()


def test_every_cancel_caller_shares_one_queued_cancel_and_the_durable_cap(row8):
    """#190 reviews: the dedupe and the cap hold per order for every caller, and the count
    lives in custody, so a reopen or a restart cannot buy an order more CANCELs. Every CANCEL
    here leaves, as when each is rejected and rc8 returns the order to its prior state, so the
    cap counts real sends."""
    (entry,) = resting_entries(row8, 1, {"AAPL.XNAS": D("10")})
    cid, iid = entry.client_order_id, entry.instrument
    row8.runtime.open()
    try:
        row8.pacer.bucket.tokens = 0  # nothing drains: the first CANCEL stays queued
        assert row8.runtime.request(PaperIntent("CANCEL", cid, iid))
        assert not row8.runtime.request(PaperIntent("CANCEL", cid, iid))  # already queued
        cap = row8.pacer.controls["max_cancel_retries"] + 1
        for _attempt in range(cap + 2):
            row8.clock[0] += 60_000_000_000  # a full refill each time
            row8.runtime.pulse()
            row8.runtime.request(PaperIntent("CANCEL", cid, iid))
        assert row8.book.cancel_sends(cid) == cap
        row8.runtime.close()
        row8.runtime.open()  # the reopened writer reloads custody: the count survives
        row8.runtime.last_error = "admission error halts: an earlier cause"
        assert not row8.runtime.request(PaperIntent("CANCEL", cid, iid))
        assert row8.runtime.last_error == "admission error halts: an earlier cause"  # kept
        assert row8.runtime.last_refusal == f"cancel retries exhausted for {cid}"
        assert [i.client_order_id for i in row8.sent].count(cid) == cap
    finally:
        row8.runtime.close()


def fail_one_write(row8, monkeypatch, field):
    """Make custody's next file write that carries `field` raise, as a full disk would."""
    write, failed = row8.custody_module.write_atomic, []

    def once(path, state):
        if not failed and any(row.get(field) for row in state["house"].values()):
            failed.append(field)
            raise OSError("custody disk full")
        return write(path, state)

    monkeypatch.setattr(row8.custody_module, "write_atomic", once)
    return failed


def halt_and_pulse(row8, longs, entries, ticks=30):
    row8.services.exit_price = lambda *_args: D("10.00")
    row8.runtime.halt("owner")
    for _tick in range(ticks):
        row8.clock[0] += row8.params.ns("flatten_tick_s")
        read(row8, longs, entries)
        row8.runtime.pulse()


def test_a_failed_audit_mark_never_stops_kill_to_flat(row8, monkeypatch):
    """#198 P2-1: a failed cancel_unanswered write keeps custody loaded; the unknown outcome is
    still recorded with the write's cause named, and the long still flattens."""
    longs = {"AAPL.XNAS": D("10")}
    entries = resting_entries(row8, 1, longs)
    lost_cancels(row8)
    failed = fail_one_write(row8, monkeypatch, "cancel_unanswered")
    row8.runtime.open()
    try:
        halt_and_pulse(row8, longs, entries)
        assert failed and row8.book.loaded and "unknown_execution_outcome" in row8.guard.reasons
        assert row8.runtime.last_error.startswith("unanswered mark not written: OSError")
        exits = [(i.instrument, i.quantity) for i in row8.sent if i.action == "EXIT"]
        assert exits == [("AAPL.XNAS", D("10"))]
    finally:
        row8.runtime.close()


def test_a_failed_cancel_count_sends_nothing_halts_named_and_keeps_flattening(row8, monkeypatch):
    """#198 P2-1: a CANCEL leaves only with a durable count. A failed count write keeps custody
    loaded, sends that CANCEL nowhere, halts with the cause named, and the long still flattens."""
    longs = {"AAPL.XNAS": D("10")}
    entries = resting_entries(row8, 1, longs)
    failed = fail_one_write(row8, monkeypatch, "cancel_sends")
    row8.runtime.open()
    try:
        halt_and_pulse(row8, longs, entries)
        assert failed and row8.book.loaded
        cancels = [i for i in row8.sent if i.action == "CANCEL"]
        assert row8.book.cancel_sends(entries[0].client_order_id) == len(cancels)  # all counted
        assert row8.runtime.last_error.startswith("cancel count not written: OSError")
        exits = [(i.instrument, i.quantity) for i in row8.sent if i.action == "EXIT"]
        assert exits == [("AAPL.XNAS", D("10"))]
    finally:
        row8.runtime.close()
