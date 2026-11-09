"""Witnesses for the A/C node's hard lines and its one entry path."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from alpaca.trading.models import Order, Position, TradeAccount

from sextant.data.catalog import equity
from sextant.execution.custody import AccountScope, WriterLease
from sextant.paper import ac_node
from sextant.paper.b_protector import (
    Protector,
    ProtectorRefusal,
    TradingClientLike,
    load_b_parameters,
)
from sextant.paper.config import PaperAccount
from sextant.paper.sessions import Session

NS = 1_000_000_000
START = 1_700_000_000 * NS
EQUITY = "1000000 USD"
ET = ZoneInfo("America/New_York")
NOW_NS = int(datetime(2026, 11, 9, 10, 0, tzinfo=ET).timestamp()) * NS


def profiles():
    return ac_node.load_profiles()


def test_slot_one_is_the_owners_peregrine_account():
    with pytest.raises(ac_node.SlotRefusal, match="Peregrine"):
        ac_node.require_writable_slot(1)


def test_slot_two_belongs_to_bs_writer():
    with pytest.raises(ac_node.SlotRefusal, match="B's writer"):
        ac_node.require_writable_slot(2)


def test_a_has_no_paper_account_and_no_writable_slot():
    with pytest.raises(ac_node.SlotRefusal, match="A has no paper account"):
        ac_node.require_writable_slot(None)
    with pytest.raises(ac_node.SlotRefusal, match="A has no paper account"):
        ac_node.require_writable_slot(profiles()["a"].slot)


def test_only_slot_three_is_writable():
    assert ac_node.require_writable_slot(3) == ac_node.C_LANE


def test_unknown_slot_is_refused():
    with pytest.raises(ac_node.SlotRefusal, match="not one of the paper lane's slots"):
        ac_node.require_writable_slot(4)


def test_the_node_ships_disabled():
    assert ac_node.ENABLED is False
    with pytest.raises(ac_node.NodeDisabled, match="enabled=0"):
        ac_node.AcNode(
            profile=profiles()["a"],
            params=ac_node.entry_parameters(),
            start_equity=ac_node.Money.from_str(EQUITY),
        ).open()


def test_a_profile_can_never_open_a_writer_even_when_enabled():
    with pytest.raises(ac_node.SlotRefusal, match="A has no paper account"):
        ac_node.AcNode(
            profile=profiles()["a"],
            params=ac_node.entry_parameters(),
            start_equity=ac_node.Money.from_str(EQUITY),
            enabled=True,
        ).open()


def test_c_sizes_on_current_equity_under_the_owners_compounding_ruling():
    a, c = profiles()["a"], profiles()["c"]

    def sized(equity_text: str) -> ac_node.EntryPlan:
        return ac_node.plan_entry(
            c,
            instrument=equity("TEST"),
            symbol="TEST",
            ts_ns=START,
            ask=Decimal("100"),
            equity=ac_node.Money.from_str(equity_text),
            setup="FIRST_LEG",
            rank=1,
            regular_hours=True,
            fixture=False,
        )

    base = sized(EQUITY)
    higher = sized("1040000 USD")
    assert base.accepted, base.refusal
    assert higher.accepted, higher.refusal
    assert base.quantity is not None and higher.quantity is not None
    assert base.quantity.as_decimal() == 4000
    assert higher.quantity.as_decimal() == 4160
    assert base.planned_risk is not None and base.planned_risk.as_decimal() == Decimal("10000")
    assert c.risk_scope == "REVIEWED"
    assert c.risk_per_trade == a.risk_per_trade == Decimal("0.01")
    assert c.rank_ceilings == a.rank_ceilings == (Decimal("2"), Decimal("1.5"), Decimal("1"))
    assert c.equity_mode == "current"
    assert "dynamic compounding" in c.risk_source
    for citation in (
        "docs/adr/0011-sizing-and-auto-leverage.md",
        "docs/adr/0002-philosophy-and-lanes.md",
        "lanes/paper/README.md",
        "No conservative profile",
        "docs/adr/0015-",
        "docs/adr/0018-",
    ):
        assert citation in c.risk_source, citation

    node = ac_node.AcNode(
        profile=c,
        params=ac_node.entry_parameters(),
        start_equity=ac_node.Money.from_str(EQUITY),
    )
    before = node.entry(instrument=equity("TEST"), start_ns=START, segment="PRE")
    node.ledger.record(entry=Decimal("100"), exit_price=Decimal("110"), quantity=Decimal("1000"))
    after = node.entry(instrument=equity("TEST"), start_ns=START, segment="PRE")
    assert before.equity.as_decimal() == Decimal("1000000")
    assert after.equity.as_decimal() == Decimal("1010000")


def test_c_open_reaches_the_writer_seam_without_a_fixture_gate():
    with pytest.raises(ac_node.NodeDisabled, match="no writer lease"):
        ac_node.AcNode(
            profile=profiles()["c"],
            params=ac_node.entry_parameters(),
            start_equity=ac_node.Money.from_str(EQUITY),
            enabled=True,
        ).open()


def test_first_leg_buys_the_fifth_print_at_the_ask_never_market():
    profile = profiles()["a"]
    params = ac_node.entry_parameters()
    entry = ac_node.AcEntry(
        instrument=equity("TEST"),
        params=params,
        profile=profile,
        start_ns=START,
        segment="PRE",
        equity=ac_node.Money.from_str(EQUITY),
    )
    assert entry.observe_rank(
        ts_ns=START + 10 * NS,
        rank=2,
        quiet_price=Decimal("100"),
        first_print_ts=START + NS,
    )
    plan = None
    for index in range(6):
        plan = entry.observe_print(
            ts_ns=START + (11 + index) * NS,
            price=Decimal("100.5") + Decimal(index) / 10,
            size=100,
            regular_hours=False,
            ask=Decimal("100.5") + Decimal(index) / 10,
            ask_ts_ns=START + (11 + index) * NS,
        )
        if plan is not None:
            break
    assert plan is not None and plan.accepted
    assert plan.quantity is not None and plan.limit is not None and plan.stop is not None
    assert plan.setup == "FIRST_LEG" and plan.rank == 2
    assert plan.quantity.as_decimal() == 1982
    assert plan.limit.as_decimal() == Decimal("100.9")
    assert plan.stop.as_decimal() == Decimal("98.3775")


def test_rank_ceiling_caps_exposure_while_risk_halves_outside_rth():
    profile = profiles()["a"]

    def sized(regular_hours: bool) -> ac_node.EntryPlan:
        return ac_node.plan_entry(
            profile,
            instrument=equity("TEST"),
            symbol="TEST",
            ts_ns=START,
            ask=Decimal("100"),
            equity=ac_node.Money.from_str(EQUITY),
            setup="FIRST_LEG",
            rank=1,
            regular_hours=regular_hours,
            fixture=True,
        )

    rth = sized(True)
    pre = sized(False)
    assert rth.quantity is not None and pre.quantity is not None
    assert rth.quantity.as_decimal() == 4000
    assert pre.quantity.as_decimal() == 2000
    assert rth.planned_risk is not None and rth.planned_risk.as_decimal() == Decimal("10000")
    assert pre.planned_risk is not None and pre.planned_risk.as_decimal() == Decimal("5000")
    assert rth.notional is not None and rth.notional.as_decimal() == Decimal("400000")
    assert pre.notional is not None and pre.notional.as_decimal() == Decimal("200000")


def test_stale_ask_refuses_instead_of_reaching_for_a_print():
    entry = ac_node.AcEntry(
        instrument=equity("TEST"),
        params=ac_node.entry_parameters(),
        profile=profiles()["a"],
        start_ns=START,
        segment="PRE",
        equity=ac_node.Money.from_str(EQUITY),
    )
    entry.observe_rank(
        ts_ns=START + 10 * NS,
        rank=1,
        quiet_price=Decimal("100"),
        first_print_ts=START + NS,
    )
    plan = entry.observe_print(
        ts_ns=START + 11 * NS,
        price=Decimal("101"),
        size=100,
        regular_hours=False,
        ask=Decimal("101"),
        ask_ts_ns=START + 2 * NS,
    )
    assert plan is not None and plan.refusal == "no fresh ask at the run completion"


def test_catalyst_enters_the_first_print_at_or_after_knowable_at():
    entry = ac_node.AcEntry(
        instrument=equity("TEST"),
        params=ac_node.entry_parameters(),
        profile=profiles()["c"],
        start_ns=START,
        segment="PRE",
        equity=ac_node.Money.from_str(EQUITY),
        fixture=True,
    )
    assert entry.observe_catalyst(
        knowable_at_ns=START + 5 * NS, quiet_price=Decimal("100"), source="recorded EDGAR 8-K"
    )
    early = entry.observe_print(
        ts_ns=START + 4 * NS, price=Decimal("99"), size=100, regular_hours=False
    )
    assert early is None
    plan = entry.observe_print(
        ts_ns=START + 6 * NS,
        price=Decimal("101.25"),
        size=100,
        regular_hours=False,
        ask=Decimal("101.25"),
        ask_ts_ns=START + 6 * NS,
    )
    assert plan is not None and plan.accepted and plan.setup == "CATALYST"
    assert plan.limit is not None
    assert plan.limit.as_decimal() == Decimal("101.25")


def test_c_stays_on_current_equity_while_a_freezes_the_segment_basis():
    a, c = profiles()["a"], profiles()["c"]
    a_ledger = ac_node.AcLedger(ac_node.Money.from_str(EQUITY), a.equity_mode)
    c_ledger = ac_node.AcLedger(ac_node.Money.from_str(EQUITY), c.equity_mode)
    a_ledger.record(entry=Decimal("100"), exit_price=Decimal("90"), quantity=Decimal("100"))
    c_ledger.record(entry=Decimal("100"), exit_price=Decimal("90"), quantity=Decimal("100"))
    assert a_ledger.sizing_equity().as_decimal() == Decimal("1000000")
    assert c_ledger.sizing_equity().as_decimal() == Decimal("999000")
    assert c_ledger.end_equity().as_decimal() == Decimal("999000")


def test_c_compounds_a_gain_into_the_next_size():
    c = profiles()["c"]
    plan = ac_node.plan_entry(
        c,
        instrument=equity("TEST"),
        symbol="TEST",
        ts_ns=START,
        ask=Decimal("100"),
        equity=ac_node.Money.from_str(EQUITY),
        setup="FIRST_LEG",
        rank=None,
        regular_hours=True,
        fixture=True,
    )
    assert plan.quantity is not None
    assert plan.quantity.as_decimal() == 4000
    c_ledger = ac_node.AcLedger(ac_node.Money.from_str(EQUITY), c.equity_mode)
    c_ledger.record(entry=Decimal("100"), exit_price=Decimal("110"), quantity=Decimal("4000"))
    larger = ac_node.plan_entry(
        c,
        instrument=equity("TEST"),
        symbol="TEST",
        ts_ns=START,
        ask=Decimal("100"),
        equity=c_ledger.sizing_equity(),
        setup="FIRST_LEG",
        rank=None,
        regular_hours=True,
        fixture=True,
    )
    assert larger.quantity is not None
    assert larger.quantity.as_decimal() == 4160


def test_the_protector_admits_only_its_asked_lane():
    account = PaperAccount(
        lane="alpaca-paper-c",
        account_id="PA3TEST",
        client_id="c3test",
        namespace="c3",
        sessions=(Session.PRE, Session.RTH),
    )
    parameters = load_b_parameters(ac_node.B_PARAMETERS)
    client = cast(TradingClientLike, object())
    with pytest.raises(ProtectorRefusal, match="alpaca-paper-b"):
        Protector(client, account, parameters)
    protector = Protector(client, account, parameters, lane="alpaca-paper-c")
    assert protector.account.lane == "alpaca-paper-c"


def test_the_writer_lease_is_one_per_slot_and_the_pacer_is_bound_once(tmp_path: Path):
    account = PaperAccount(
        lane="alpaca-paper-c",
        account_id="PA3TEST",
        client_id="c3test",
        namespace="c3",
        sessions=(Session.PRE, Session.RTH),
    )
    scope = AccountScope(account.broker, account.account_id)
    first = WriterLease(scope, tmp_path, "paper-ac-c")
    first.acquire()
    second = WriterLease(scope, tmp_path, "tv-host")
    with pytest.raises(Exception, match="already has a writer"):
        second.acquire()
    first.close()


def test_ac_parameters_are_a_registry_file_not_an_invented_number():
    rows = json.loads(ac_node.AC_PARAMETERS.read_text())
    assert rows["schema"] == 1
    for name in ("a_risk_per_trade", "c_risk_per_trade"):
        row = rows["profiles"][name[0]][name]
        assert row["scope"] in {"REVIEWED", "FIXTURE_ONLY"}
        assert row["calibration"] == "UNCALIBRATED"
        assert row["source"]


def _c_account() -> PaperAccount:
    return PaperAccount(
        lane="alpaca-paper-c",
        account_id="PA3TEST",
        client_id="c3test",
        namespace="c3",
        sessions=(Session.RTH,),
    )


class _HeldWriter:
    """The minimum writer seam: a held lease admits one pacer."""

    def __init__(self) -> None:
        self.held = False
        self.pacers: list[object] = []

    def acquire(self) -> None:
        self.held = True

    def bind_pacer(self, pacer: object) -> None:
        self.pacers.append(pacer)


class _Guard:
    def entry_allowed(self) -> bool:
        return True


class _RecordingProtector:
    def __init__(self) -> None:
        self.account = _c_account()
        self.bound = 0
        self.reconciled = 0

    def bind(self) -> None:
        self.bound += 1

    def reconcile(self) -> None:
        self.reconciled += 1


class _EntryClient:
    """Serves the partial-fill case: 500 of a 1,000-share entry filled."""

    def __init__(self) -> None:
        self.submitted: list[Any] = []
        self.cancelled: list[object] = []

    def get_account(self) -> TradeAccount:
        return TradeAccount.model_validate(
            {
                "id": str(uuid4()),
                "account_number": "PA3TEST",
                "status": "ACTIVE",
                "currency": "USD",
                "buying_power": "100000",
                "cash": "100000",
                "portfolio_value": "100000",
                "equity": "100000",
            }
        )

    def get_all_positions(self) -> list[Position]:
        return [
            Position.model_validate(
                {
                    "asset_id": str(uuid4()),
                    "symbol": "AAPL",
                    "exchange": "NASDAQ",
                    "asset_class": "us_equity",
                    "avg_entry_price": "100",
                    "qty": "500",
                    "side": "long",
                    "cost_basis": "50000",
                    "qty_available": "500",
                }
            )
        ]

    def get_orders(self, filter=None) -> list[Order]:
        return [
            Order.model_validate(
                {
                    "id": str(uuid4()),
                    "client_order_id": "c3-entry-AAPL-1",
                    "created_at": "2026-11-09T14:59:00Z",
                    "updated_at": "2026-11-09T14:59:00Z",
                    "submitted_at": "2026-11-09T14:59:00Z",
                    "order_class": "simple",
                    "time_in_force": "day",
                    "status": "partially_filled",
                    "extended_hours": False,
                    "symbol": "AAPL",
                    "qty": "1000",
                    "filled_qty": "500",
                    "side": "buy",
                    "type": "limit",
                }
            )
        ]

    def submit_order(self, order_data):
        self.submitted.append(order_data)
        return order_data

    def cancel_order_by_id(self, order_id) -> None:
        self.cancelled.append(order_id)


def test_protecting_needs_an_open_held_lease():
    protector = _RecordingProtector()
    deployment = ac_node.Deployment(
        writer=_HeldWriter(),
        pacer=object(),
        guard=_Guard(),
        protector=cast(Protector, protector),
    )
    node = ac_node.AcNode(
        profile=profiles()["c"],
        params=ac_node.entry_parameters(),
        start_equity=ac_node.Money.from_str(EQUITY),
        enabled=True,
        deployment=deployment,
    )
    with pytest.raises(ac_node.NodeDisabled, match="no writer lease is held"):
        node.protect_account()
    assert protector.bound == protector.reconciled == 0

    node.open()
    assert deployment.writer.held is True
    node.protect_account()
    assert protector.bound == 1
    assert protector.reconciled == 1


def test_a_house_entry_buy_is_not_mistaken_for_a_protective_exit():
    client = _EntryClient()
    protector = Protector(
        client,
        _c_account(),
        load_b_parameters(ac_node.B_PARAMETERS),
        lane=ac_node.C_LANE,
        now_ns=lambda: NOW_NS,
    )
    positions = protector.reconcile()
    assert positions["AAPL"].qty == "500"
    assert client.cancelled == []
    assert len(client.submitted) == 1
    submitted = client.submitted[0]
    assert submitted.side.value == "sell"
    assert Decimal(str(submitted.qty)) == Decimal("500")
    assert str(submitted.trail_percent) == "2.5"


def test_catalyst_refuses_a_stale_ask_before_sizing():
    entry = ac_node.AcEntry(
        instrument=equity("TEST"),
        params=ac_node.entry_parameters(),
        profile=profiles()["c"],
        start_ns=START,
        segment="PRE",
        equity=ac_node.Money.from_str(EQUITY),
        fixture=True,
    )
    assert entry.observe_catalyst(
        knowable_at_ns=START + 5 * NS, quiet_price=Decimal("100"), source="recorded EDGAR 8-K"
    )
    plan = entry.observe_print(
        ts_ns=START + 6 * NS,
        price=Decimal("101.25"),
        size=100,
        regular_hours=False,
        ask=Decimal("101.25"),
        ask_ts_ns=START - 4 * NS,
    )
    assert plan is not None and not plan.accepted
    assert plan.refusal == "no fresh ask at the catalyst print"


def test_catalyst_sizes_on_equity_re_read_at_the_decision():
    node = ac_node.AcNode(
        profile=profiles()["c"],
        params=ac_node.entry_parameters(),
        start_equity=ac_node.Money.from_str(EQUITY),
    )
    entry = node.entry(instrument=equity("TEST"), start_ns=START, segment="PRE")
    assert entry.observe_catalyst(
        knowable_at_ns=START + 5 * NS, quiet_price=Decimal("100"), source="recorded EDGAR 8-K"
    )
    node.ledger.record(entry=Decimal("100"), exit_price=Decimal("110"), quantity=Decimal("4000"))
    plan = entry.observe_print(
        ts_ns=START + 6 * NS,
        price=Decimal("101"),
        size=100,
        regular_hours=False,
        ask=Decimal("100"),
        ask_ts_ns=START + 6 * NS,
    )
    assert plan is not None, "the catalyst print produced no plan"
    assert plan.accepted, plan.refusal
    assert plan.quantity is not None
    assert plan.quantity.as_decimal() == 2080
    assert plan.planned_risk is not None
    assert plan.planned_risk.as_decimal() == Decimal("5200")
