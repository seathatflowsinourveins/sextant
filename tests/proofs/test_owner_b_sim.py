"""Native sim custody/handover witnesses. No live-node external fill claim is exercised."""

import json
from dataclasses import replace
from decimal import Decimal as D
from typing import Any, cast

import pytest


def run_case(tmp_path, **case):
    from sextant.backtest.owner_b_witness import run_case as run

    return run(tmp_path, **case)


@pytest.mark.parametrize("missing", ["chase_cap_fraction", "chase_min_interval_s"])
@pytest.mark.parametrize("session", ["rth", "outside"])
def test_missing_chase_parameters_refuse_before_adoption(missing, session):
    from sextant.backtest.exit_witness import FIXTURE
    from sextant.backtest.owner_b_witness import B_FIXTURE, EQUITY
    from sextant.exits.owner_b_sim import BManager, BManagerConfig

    params = replace(FIXTURE, **{missing: None})
    with pytest.raises(ValueError, match="explicit chase parameters"):
        BManager(
            BManagerConfig(
                instrument_id=EQUITY.id,
                params=params,
                round_trip_cost=D(0),
                session=session,
                b_params=B_FIXTURE,
                owner_order_ids=(),
            )
        )


def test_option_b_waits_for_terminal_cancel_and_measures_both_gaps(tmp_path):
    r = run_case(tmp_path, scenario="normal")
    assert r["sold"] == "8" and r["residual"] == "2"
    assert r["max_house_exits"] == 1 and r["reservation_violations"] == []
    assert r["cancel_ack_ns"] < r["limit_accepted_ns"] < r["first_fill_ns"]
    # The pinned engine services latency at the next data event on this one-second grid.
    assert r["gap1_ns"] == 1_000_000_000
    assert r["gap2_ns"] > 0
    assert not any(o["reduce_only"] for o in r["house_orders"])
    assert all(o["quantity"] == "2" and o["status"] == "ACCEPTED" for o in r["owner_exits"])
    assert r["owner_mutations"] == []


@pytest.mark.parametrize(
    "point, sold, residual",
    [
        ("after_cancel_ack", "0", "8"),
        ("after_limit_accept", "3", "5"),
    ],
)
def test_engine_stop_and_start_in_sim_not_a_process_death_and_not_broker_reconciliation(
    tmp_path,
    point,
    sold,
    residual,
):
    """engine stop and start in sim; not a process death and not broker reconciliation."""
    r = run_case(tmp_path, scenario=point)
    assert r["stops"] == 1 and r["restarts"] == 1
    assert r["sold"] == sold
    assert len(r["resting_trails"]) == 1
    assert r["resting_trails"][0]["leaves"] == residual
    assert r["max_house_exits"] == 1 and r["reservation_violations"] == []
    assert r["limit_submissions"] == (0 if point == "after_cancel_ack" else 1)
    assert r["owner_mutations"] == []
    assert r["recovery_label"] == (
        "engine stop and start in sim; not a process death and not broker reconciliation"
    )


def test_unfilled_chase_ends_by_cancel_then_rearming_the_fresh_residual(tmp_path):
    r = run_case(tmp_path, scenario="unfilled")
    assert r["sold"] == "0" and r["gap2_ns"] is None
    assert r["limit_submissions"] == 1 and len(r["resting_trails"]) == 1
    assert r["resting_trails"][0]["leaves"] == "8"
    assert r["reservation_violations"] == []


def test_owner_add_pauses_the_manager_and_pages_without_touching_owner_orders(tmp_path):
    r = run_case(tmp_path, scenario="owner_add")
    assert r["paused"] and r["pages"] == ["owner_add"]
    assert r["limit_submissions"] == 0 and r["owner_mutations"] == []


def test_adopted_below_trigger_sells_on_the_first_persisted_breach(tmp_path):
    r = run_case(tmp_path, scenario="adopted_below")
    adoption = next(e for e in r["events"] if e["event"] == "adoption")
    assert D(adoption["entry"]) == D("100.02")
    assert D(adoption["high"]) == D(98)
    assert D(adoption["trigger"]) == D("99.81996")
    assert r["exit_reason"] == "adopted-below-trigger" and r["sold"] == "8"


def test_outside_rth_uses_native_bid_ask_emulation_and_one_limit_release(tmp_path):
    r = run_case(tmp_path, scenario="outside")
    assert r["emulations"] == 1 and r["releases"] == 1
    assert r["sold"] == "8" and r["owner_mutations"] == []
    assert r["max_house_exits"] == 1 and r["reservation_violations"] == []


def test_run_ledger_appends_every_arm_and_keeps_tiers_separate(tmp_path):
    from sextant.backtest.owner_b_witness import run

    run(tmp_path)
    run(tmp_path)
    rows = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert len(rows) == 6
    assert [r["arm"] for r in rows] == ["option-b", "native-trail-o0", "hold"] * 2
    assert [r["tier"] for r in rows] == ["SIMULATED", "SIMULATED", "MODELED"] * 2
    assert all(r["params_hash"] and r["data_hash"] and r["run_id"] for r in rows)
    assert len({r["run_id"] for r in rows}) == 2


def test_each_individual_attempt_is_ledgered_with_its_actual_latency(tmp_path):
    run_case(tmp_path, scenario="normal", latency_ns=1_200_000_000)
    rows = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["latency_ns"] == 1_200_000_000
    assert rows[0]["gap1_ns"] == 2_000_000_000
    assert rows[0]["gap2_ns"] is None and rows[0]["status"] == "completed"
    assert rows[0]["code_hash"] and rows[0]["arm_run_id"]


def test_full_owner_reservation_alerts_then_freed_quantity_gets_one_trail(tmp_path):
    r = run_case(tmp_path, scenario="owner_reserved")
    assert not r["paused"] and "owner_reserved_unprotected" in r["pages"]
    assert len(r["resting_trails"]) == 1
    assert r["resting_trails"][0]["leaves"] == "10"
    assert r["max_house_exits"] == 1 and r["reservation_violations"] == []
    assert r["gross_pnl_usd"] is None  # Custody drills are not matched economic arms.


def test_unknown_scenario_is_refused_and_the_failed_attempt_is_not_erased(tmp_path):
    with pytest.raises(ValueError, match="unknown scenario"):
        run_case(tmp_path, scenario="misspelled-scenario")
    rows = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["status"] == "failed"


def test_the_in_hours_native_trail_is_broker_held_on_the_last_trade(tmp_path):
    """Alpaca elects stop and trailing-stop orders on the consolidated print (docs read
    2026-11-06), so the RTH native trail triggers on LAST_PRICE (rc8 TriggerType.LastPrice) and
    is held by the broker, not emulated. The trigger is read when the order is submitted."""
    for scenario in ("normal", "adopted_below"):
        r = run_case(tmp_path / scenario, scenario=scenario)
        trails = [a for a in r["actions"] if a["action"] == "trail"]
        assert trails and all(a["trigger"] == "LAST_PRICE" for a in trails)
        assert all(a["emulation"] in {None, "NO_TRIGGER"} for a in trails)
        accepted = {e.get("order_id") for e in r["events"] if e["event"] == "accepted"}
        assert all(a["order_id"] in accepted for a in trails) and r["emulations"] == 0
        types = {o["id"]: o["type"] for o in r["house_orders"]}  # Alpaca has no trailing stop-limit
        assert all(types[a["order_id"]] == "TRAILING_STOP_MARKET" for a in trails)


def test_on_quotes_only_b_waits_for_a_print_and_never_pauses(tmp_path):
    """#191 reviews: B submits no in-hours trail that rc8 would deny for want of a cached print.
    It waits and alerts without pausing, so the X2-X5 exit still sells in hours."""
    r = run_case(tmp_path, scenario="quotes_only")
    assert r["paused"] is False and "protection_denied" not in r["pages"]
    assert "awaiting_trade" in r["pages"]  # the unarmed broker trail is not silent
    assert any(e["event"] == "awaiting_trade" for e in r["events"])
    assert not [a for a in r["actions"] if a["action"] == "trail"]
    assert r["sold"] == "8" and r["residual"] == "2"


def test_the_first_print_arms_the_in_hours_trail(tmp_path):
    """The witness's first print comes at 6 s: B waits until then, then arms and is accepted."""
    r = run_case(tmp_path, scenario="late_print")
    trails = [a for a in r["actions"] if a["action"] == "trail"]
    accepted = {e.get("order_id") for e in r["events"] if e["event"] == "accepted"}
    waited = [e for e in r["events"] if e["event"] == "awaiting_trade"]
    assert trails and trails[0]["order_id"] in accepted
    assert waited and int(waited[0]["ts"]) < int(trails[0]["ts"])
    assert r["paused"] is False and r["pages"] == ["awaiting_trade"]
    assert trails[0]["trigger"] == "LAST_PRICE" and trails[0]["emulation"] in {None, "NO_TRIGGER"}
    assert r["emulations"] == 0
    from sextant.backtest.owner_b_witness import BASE, NS

    assert trails[0]["ts"] == BASE + 6 * NS + 1  # on the print itself, not the next quote


def test_rc8s_own_denial_of_an_unpriced_in_hours_trail_waits_and_the_print_re_arms(
    tmp_path, monkeypatch
):
    """#191 legs: B's first in-hours trail here skips the cached-print precondition, so rc8's
    RiskEngine itself denies it (crates/risk/src/engine/mod.rs:2364-2417). B drops the denied
    order, waits and alerts without pausing, and the first print arms an accepted trail."""
    from nautilus_trader.model import (
        OrderSide,
        Quantity,
        TimeInForce,
        TrailingOffsetType,
        TriggerType,
    )

    from sextant.backtest import owner_b_witness

    denials: list[str] = []

    class Unguarded(owner_b_witness.WitnessManager):
        def _submit(self, kind, quantity):
            if kind != "trail" or self.awaiting_trade or denials:
                return super()._submit(kind, quantity)
            order = self.order_factory.trailing_stop_market(
                instrument_id=self.instrument_id,
                order_side=OrderSide.SELL,
                quantity=Quantity.from_str(str(quantity)),
                time_in_force=TimeInForce.DAY,
                trailing_offset=self.b.native_trail_fraction * 10_000,
                trailing_offset_type=TrailingOffsetType.BASIS_POINTS,
                trigger_type=TriggerType.LAST_PRICE,
            )
            self.owned[str(order.client_order_id)] = "trail"
            self.submit_order(order)

        def on_order_denied(self, event):
            denials.append(str(event.reason))
            super().on_order_denied(event)

    monkeypatch.setattr(owner_b_witness, "WitnessManager", Unguarded)
    r = run_case(tmp_path, scenario="late_print")
    (denial,) = denials
    assert denial.startswith("MARKET_PRICE_UNAVAILABLE")
    (waited,) = [e for e in r["events"] if e["event"] == "awaiting_trade"]
    assert waited["order_id"] and waited["reason"] == denial  # the alert names its order
    assert r["paused"] is False and r["pages"] == ["awaiting_trade"]
    trails = [a for a in r["actions"] if a["action"] == "trail"]
    accepted = {e.get("order_id") for e in r["events"] if e["event"] == "accepted"}
    assert trails and trails[0]["order_id"] in accepted and trails[0]["trigger"] == "LAST_PRICE"


def outside_before_any_quote(manager_class):
    """Outside RTH: the owner's entry fills on prints (rc8 fills a resting LIMIT from trades)
    and B adopts on the next print, before any quote is cached. Quotes start at 4.5 s, no print
    follows them, and the bid drops 3% at 9 s."""
    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig, StrategyConfig
    from nautilus_trader.execution import MakerTakerFeeModel, StaticLatencyModel
    from nautilus_trader.model import (
        AccountType,
        AggressorSide,
        ClientOrderId,
        Money,
        OmsType,
        OrderSide,
        Price,
        Quantity,
        QuoteTick,
        TimeInForce,
        TradeId,
        TradeTick,
        Venue,
    )
    from nautilus_trader.trading import Strategy

    from sextant.backtest.exit_witness import FIXTURE
    from sextant.backtest.owner_b_witness import B_FIXTURE, BASE, EQUITY, USD
    from sextant.exits import policy
    from sextant.exits.engine import NS
    from sextant.exits.owner_b import adopt
    from sextant.exits.owner_b_sim import BManagerConfig

    manager = manager_class(
        BManagerConfig(
            instrument_id=EQUITY.id,
            params=FIXTURE,
            round_trip_cost=D("0.01"),
            session="outside",
            b_params=B_FIXTURE,
            owner_order_ids=("owner-entry",),
        )
    )

    class Owner(Strategy):
        def __init__(self, config):
            super().__init__(config)
            self.entry, self.filled_ns = None, 0

        def on_start(self):
            self.subscribe_trades(EQUITY.id)

        def on_trade(self, trade):
            if not self.cache.orders():
                self.submit_order(
                    self.order_factory.limit(
                        EQUITY.id,
                        OrderSide.BUY,
                        Quantity.from_str("10"),
                        Price.from_str("100.02"),
                        time_in_force=TimeInForce.DAY,
                        client_order_id=ClientOrderId("owner-entry"),
                    )
                )
            elif self.entry is not None and manager.protection is None:
                assert self.cache.quote(EQUITY.id) is None
                buffer = policy.buffer(D("0.01"), D("0.02"), self.entry, None, FIXTURE)
                assert buffer is not None
                adoption = adopt(
                    entry=self.entry,
                    mark=trade.price.as_decimal(),
                    quantity=D(10),
                    owner_reserved=D(0),
                    buffer=buffer,
                    filled_ns=self.filled_ns,
                    now_ns=trade.ts_event,
                    reconciled=True,
                    claim_max_latency_s=B_FIXTURE.claim_max_latency_s,
                )
                manager.adopt_position(adoption, total_quantity=D(10))

        def on_order_filled(self, event):
            self.entry, self.filled_ns = event.last_px.as_decimal(), event.ts_event

    data: list = [
        TradeTick(EQUITY.id, Price.from_str("100.00"), Quantity.from_str("100"),
                  AggressorSide.SELL, TradeId(str(i)), BASE + i * NS, BASE + i * NS)
        for i in range(3)
    ] + [
        QuoteTick(EQUITY.id, Price.from_str("99.99"), Price.from_str("100.01"),
                  Quantity.from_str("100"), Quantity.from_str("100"), at, at)
        for at in (BASE + i * NS + NS // 2 for i in range(4, 8))
    ] + [
        QuoteTick(EQUITY.id, Price.from_str(bid), Price.from_str(bid[:-2] + "02"),
                  Quantity.from_str("100"), Quantity.from_str("100"), BASE + s * NS, BASE + s * NS)
        for bid, s in (("97.00", 9), ("96.50", 10))
    ]  # fmt: skip
    engine = BacktestEngine(BacktestEngineConfig())
    engine.add_venue(
        Venue("SIM"),
        OmsType.NETTING,
        AccountType.MARGIN,
        [Money(1_000_000, USD)],
        base_currency=USD,
        fee_model=MakerTakerFeeModel(maker_rate=D(0), taker_rate=D(0)),
        latency_model=StaticLatencyModel(base_latency_nanos=200_000_000),
        use_reduce_only=False,
        liquidity_consumption=True,
    )
    engine.add_instrument(EQUITY)
    engine.add_data(data)
    owner = Owner(StrategyConfig())
    engine.add_strategy(owner)
    engine.add_strategy(manager)
    try:
        engine.run()
        assert owner.entry is not None
        orders = {str(o.client_order_id): o.status.name for o in manager.cache.orders()}
        return manager, orders
    finally:
        engine.dispose()


def test_outside_rth_a_trail_adopted_before_any_quote_is_held_by_the_emulator_and_armed():
    """#191 dsh leg P1, measured: outside RTH the trail is an emulated BID_ASK trailing stop. rc8
    sends it to the OrderEmulator, not to the RiskEngine, so it is never denied for want of a
    quote. The emulator holds it unactivated and arms it on the first quote, so the 3% drop at
    9 s releases it."""
    from sextant.exits.owner_b_sim import BManager

    manager, orders = outside_before_any_quote(BManager)
    adoption = next(e for e in manager.events if e["event"] == "adoption")
    (trail,) = [a for a in manager.actions if a["action"] == "trail"]
    assert trail["ts"] == int(adoption["ts"]) and trail["emulation"] == "BID_ASK"  # no quote yet
    assert manager.paused is False and manager.pages == ["awaiting_quote"]  # not silent (#194)
    assert "DENIED" not in orders.values()
    assert manager.owned[trail["order_id"]] == "limit" and orders[trail["order_id"]] == "ACCEPTED"


def test_outside_rth_a_denial_fails_closed():
    """#191 dsh leg P1: only the in-hours trail waits for a print. Outside RTH any denial pages
    and pauses. rc8 never denies the emulated outside trail for want of a quote (above), so this
    denial is synthetic."""
    from types import SimpleNamespace

    from sextant.exits.owner_b_sim import BManager

    class Denied(BManager):
        def _submit(self, kind, quantity):
            super()._submit(kind, quantity)
            if kind == "trail" and not self.paused:
                cid = self.actions[-1]["order_id"]
                reason = "MARKET_PRICE_UNAVAILABLE: synthetic"
                event = SimpleNamespace(client_order_id=cid, reason=reason, ts_event=0)
                self.on_order_denied(cast(Any, event))

    manager, _orders = outside_before_any_quote(Denied)
    assert manager.paused is True and manager.pages == ["awaiting_quote", "protection_denied"]
    assert manager.awaiting_trade is False


@pytest.mark.parametrize(
    "denied_kind, reason",
    [
        ("trail", "NOTIONAL_EXCEEDS_FREE_BALANCE: synthetic"),
        ("limit", "MARKET_PRICE_UNAVAILABLE: x"),
    ],
)
def test_in_hours_any_other_denial_pages_and_pauses(tmp_path, monkeypatch, denied_kind, reason):
    """#194 (#88 P2-2): only rc8's MARKET_PRICE_UNAVAILABLE denial of the in-hours trail waits.
    Another reason on the trail, or any denial of the LIMIT exit, pages and pauses. The denials
    are synthetic: the witness's orders are not denied by rc8."""
    from types import SimpleNamespace

    from sextant.backtest import owner_b_witness

    class Denied(owner_b_witness.WitnessManager):
        def _submit(self, kind, quantity):
            super()._submit(kind, quantity)
            if kind == denied_kind and not getattr(self, "denied", False) and self.actions:
                self.denied = True
                event = SimpleNamespace(
                    client_order_id=self.actions[-1]["order_id"], reason=reason, ts_event=0
                )
                self.on_order_denied(cast(Any, event))

    monkeypatch.setattr(owner_b_witness, "WitnessManager", Denied)
    r = run_case(tmp_path, scenario="normal")
    assert r["paused"] is True and "protection_denied" in r["pages"]
    assert "awaiting_trade" not in r["pages"]


def test_the_limit_handover_ends_the_wait_for_a_print(tmp_path, monkeypatch):
    """#194 (dsh P2-1): once the LIMIT exit replaces the trail B waited to arm, a later print
    drives nothing: no audit row at the print and no new trail."""
    from nautilus_trader.model import AggressorSide, Price, Quantity, TradeId, TradeTick

    from sextant.backtest import owner_b_witness as witness

    at, base = witness.BASE + 12 * witness.NS + 1, witness._data

    def with_a_late_print(scenario):
        late = TradeTick(witness.EQUITY.id, Price.from_str("90.00"), Quantity.from_str("1"),
                         AggressorSide.BUY, TradeId("late"), at, at)  # fmt: skip
        return [*base(scenario), late]

    monkeypatch.setattr(witness, "_data", with_a_late_print)
    r = run_case(tmp_path, scenario="quotes_only")
    assert [a["action"] for a in r["actions"]] == ["limit"]
    assert not [a for a in r["audits"] if a["ts"] == at]
