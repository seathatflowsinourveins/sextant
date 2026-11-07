"""Real row-8 integration drills; explicitly pending until #51's modules land.

The same tests can run against a separately identified row-8 source fixture by
extending sextant.__path__ in the invoking Python process. Nothing is vendored.
"""

import importlib
from decimal import Decimal as D
from types import SimpleNamespace as NS

import pytest
from test_paper_config import ROOT, account, ns

from sextant.paper.config import load_budget
from sextant.paper.runtime import PaperIntent, PaperRuntime, PaperServices


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

    def send(intent, before_wire):
        before_wire()
        sent.append(intent)

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
        send=send,
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
