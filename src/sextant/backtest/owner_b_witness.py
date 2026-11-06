"""B's native sim witnesses over an explicit synthetic equity path; no merit/claim proof.

The owner fixture supplies plain LIMIT fills and one untouched reserved owner LIMIT. It is
not an external live-node claimant. Native factories/cache, StaticLatencyModel and streaming
execution are the installed rc7 runtime at 55c0e82053142bce3a5cba4de4221d3929c2d3bc;
stop/start uses Strategy.stop/resume in one BacktestEngine and cache, never broker recovery.
House policy/kill points: northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa,
docs/adr/0015-owner-entry-paper-exit-manager.md:94-124. The run ledger follows #45's witness
and ADR-0018. Every number below is a fixture, with no parameter authority or calibration.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, StrategyConfig
from nautilus_trader.execution import MakerTakerFeeModel, StaticLatencyModel
from nautilus_trader.model import (
    AccountType,
    AggressorSide,
    ClientOrderId,
    Currency,
    Equity,
    InstrumentId,
    Money,
    OmsType,
    OrderSide,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    TimeInForce,
    TradeId,
    TradeTick,
    Venue,
)
from nautilus_trader.trading import Strategy

from sextant.backtest.exit_witness import FIXTURE
from sextant.exits import policy
from sextant.exits.engine import NS
from sextant.exits.owner_b import BParams, adopt
from sextant.exits.owner_b_sim import BManager, BManagerConfig

D = Decimal
BASE = 1_793_975_400_000_000_000
USD = Currency.from_str("USD")
EQUITY = Equity(
    instrument_id=InstrumentId.from_str("BTEST.SIM"),
    raw_symbol=Symbol("BTEST"),
    currency=USD,
    price_precision=2,
    price_increment=Price.from_str("0.01"),
    lot_size=Quantity.from_str("1"),
    ts_event=0,
    ts_init=0,
)
B_FIXTURE = BParams(D("0.025"), D(3), D(2))
RECOVERY_LABEL = "engine stop and start in sim; not a process death and not broker reconciliation"


def _data(scenario: str) -> list:
    bids = ["100", "100", "100", "102"] + ["101.70"] * 10
    if scenario not in {"unfilled", "owner_add"}:
        bids[9] = "102"
    if scenario == "after_limit_accept":
        bids[9] = "101.95"
    if scenario == "after_cancel_ack":
        bids[10:] = ["102"] * 4
    if scenario == "after_limit_accept":
        bids[13] = "102"
    if scenario == "unfilled":
        bids[11:] = ["101.80"] * 3
    if scenario == "owner_reserved":
        bids[3:] = ["102"] * 11
    if scenario == "adopted_below":
        bids[2:] = ["98"] * 12
    if scenario == "outside":
        bids[4:7] = ["99"] * 3
        bids[7:] = ["100"] * 7
    data = []
    for i, bid in enumerate(bids):
        ts, value = BASE + i * NS, D(bid)
        size = "3" if scenario == "after_limit_accept" and i == 9 else "100"
        data.append(
            QuoteTick(
                EQUITY.id,
                Price.from_str(bid + (".00" if "." not in bid else "")),
                Price.from_str(f"{value + D('0.02'):.2f}"),
                Quantity.from_str(size),
                Quantity.from_str("100"),
                ts,
                ts,
            )
        )
        if i in {0, 2, 3} or (scenario == "outside" and i == 6):
            data.append(
                TradeTick(
                    EQUITY.id,
                    Price.from_str(f"{value:.2f}"),
                    Quantity.from_str("1"),
                    AggressorSide.BUY,
                    TradeId(str(i)),
                    ts + 1,
                    ts + 1,
                )
            )
    return data


class WitnessConfig(BManagerConfig):
    def __init__(self, *, scenario, arm, **kwargs):
        super().__init__(**kwargs)
        self.scenario, self.arm = scenario, arm


class WitnessManager(BManager):
    """Fault scheduling belongs to the witness, not to the policy/runtime interface."""

    def __init__(self, config: WitnessConfig):
        super().__init__(config)
        self.scenario, self.arm = config.scenario, config.arm
        self.stops, self.restarts = 0, 0

    def _sell(self, ts, p):
        if self.arm == "option-b":
            super()._sell(ts, p)

    def on_order_canceled(self, event):
        if self.scenario == "after_cancel_ack" and not self.stops:
            self.stops += 1
            self.stop()
        super().on_order_canceled(event)

    def on_order_accepted(self, event):
        if (
            self.scenario == "after_limit_accept"
            and not self.stops
            and self.owned.get(str(event.client_order_id)) == "limit"
        ):
            self.stops += 1
            self.stop()
        super().on_order_accepted(event)


class OwnerFixtureConfig(StrategyConfig):
    def __init__(self, *, manager, scenario, arm):
        super().__init__()
        self.manager, self.scenario, self.arm = manager, scenario, arm


class OwnerFixture(Strategy):
    """Separate sim strategy, explicit fixture facts; not EXTERNAL order reconciliation."""

    def __init__(self, config: OwnerFixtureConfig):
        super().__init__(config)
        self.manager, self.scenario, self.arm = config.manager, config.scenario, config.arm
        self.entry = None
        self.filled_ns = 0
        self.entered, self.adopted, self.added = False, False, False
        self.owner_canceled = False

    def on_start(self):
        self.subscribe_quotes(EQUITY.id)

    def _buy(self, quote, quantity, cid):
        self.submit_order(
            self.order_factory.limit(
                EQUITY.id,
                OrderSide.BUY,
                Quantity.from_str(quantity),
                quote.ask_price,
                time_in_force=TimeInForce.DAY,
                client_order_id=ClientOrderId(cid),
            )
        )

    def on_quote(self, quote):
        elapsed = quote.ts_event - BASE
        if not self.entered:
            self.entered = True
            self._buy(quote, "10", "owner-entry")
        if self.entry is not None and not self.adopted:
            self.adopted = True
            self.submit_order(
                self.order_factory.limit(
                    EQUITY.id,
                    OrderSide.SELL,
                    Quantity.from_str("10" if self.scenario == "owner_reserved" else "2"),
                    Price.from_str("200.00"),
                    time_in_force=TimeInForce.DAY,
                    client_order_id=ClientOrderId("owner-reservation"),
                )
            )
            if self.arm != "hold":
                buf = policy.buffer(D("0.01"), D("0.02"), self.entry, None, FIXTURE)
                assert buf is not None
                a = adopt(
                    entry=self.entry,
                    mark=quote.bid_price.as_decimal(),
                    quantity=D(10),
                    owner_reserved=D(10) if self.scenario == "owner_reserved" else D(2),
                    buffer=buf,
                    filled_ns=self.filled_ns,
                    now_ns=quote.ts_event,
                    reconciled=True,
                    claim_max_latency_s=B_FIXTURE.claim_max_latency_s,
                )
                self.manager.adopt_position(a, total_quantity=D(10))
        if self.scenario == "owner_add" and elapsed >= 3 * NS and not self.added:
            self.added = True
            self._buy(quote, "1", "owner-add")
        if self.scenario == "owner_reserved" and elapsed >= 5 * NS and not self.owner_canceled:
            self.owner_canceled = True
            self.cancel_order(ClientOrderId("owner-reservation"))
        restart_s = 10 if self.scenario == "after_limit_accept" else 9
        if self.manager.stops and not self.manager.restarts and elapsed >= restart_s * NS:
            self.manager.restarts += 1
            # rc7's Component FSM resumes a stopped component (component.rs:403-404).
            self.manager.resume()

    def on_order_filled(self, event):
        if str(event.client_order_id) == "owner-entry":
            self.entry, self.filled_ns = event.last_px.as_decimal(), event.ts_event


def _order_row(order) -> dict:
    return {
        "id": str(order.client_order_id),
        "type": order.order_type.name,
        "status": order.status.name,
        "quantity": str(order.quantity.as_decimal()),
        "leaves": str(order.leaves_qty.as_decimal()),
        "reduce_only": order.is_reduce_only,
    }


def _simulate_case(
    out: Path, *, scenario: str = "normal", arm: str = "option-b", latency_ns: int = 200_000_000
) -> dict:
    data = _data(scenario)
    engine = BacktestEngine(BacktestEngineConfig())
    engine.add_venue(
        Venue("SIM"),
        OmsType.NETTING,
        AccountType.MARGIN,
        [Money(1_000_000, USD)],
        base_currency=USD,
        fee_model=MakerTakerFeeModel(maker_rate=D(0), taker_rate=D(0)),
        latency_model=StaticLatencyModel(base_latency_nanos=latency_ns),
        use_reduce_only=False,
        liquidity_consumption=True,
    )
    engine.add_instrument(EQUITY)
    engine.add_data(data)
    manager = WitnessManager(
        WitnessConfig(
            scenario=scenario,
            arm=arm,
            instrument_id=EQUITY.id,
            params=FIXTURE,
            round_trip_cost=D("0.01"),
            session="outside" if scenario == "outside" else "rth",
            b_params=B_FIXTURE,
            owner_order_ids=("owner-entry", "owner-reservation", "owner-add"),
        ),
    )
    owner = OwnerFixture(OwnerFixtureConfig(manager=manager, scenario=scenario, arm=arm))
    engine.add_strategy(owner)
    engine.add_strategy(manager)
    try:
        engine.run()
        orders = manager.cache.orders(instrument_id=EQUITY.id)
        house = [o for o in orders if str(o.client_order_id) in manager.owned]
        owner_exits = [o for o in orders if str(o.client_order_id) == "owner-reservation"]
        fills = [e for o in house for e in o.events() if type(e).__name__ == "OrderFilled"]
        canceled = [
            e.ts_event
            for o in house
            for e in o.events()
            if type(e).__name__ == "OrderCanceled"
            and manager.owned[str(o.client_order_id)] == "trail"
        ]
        accepted = [
            e.ts_event
            for o in house
            for e in o.events()
            if type(e).__name__ == "OrderAccepted"
            and manager.owned[str(o.client_order_id)] == "limit"
        ]
        cancel_ns = min(canceled) if canceled else None
        accept_ns = min(accepted) if accepted else None
        first_fill = min((e.ts_event for e in fills), default=None)
        sold = sum((e.last_qty.as_decimal() for e in fills), D(0))
        value = sum((e.last_qty.as_decimal() * e.last_px.as_decimal() for e in fills), D(0))
        last_bid = next(
            q.bid_price.as_decimal() for q in reversed(data) if isinstance(q, QuoteTick)
        )
        assert owner.entry is not None
        result = {
            "scenario": scenario,
            "arm": arm,
            "events": manager.events,
            "actions": manager.actions,
            "audits": manager.audits,
            "sold": str(sold),
            "residual": str(D(10) + (D(1) if owner.added else D(0)) - sold),
            "gross_pnl_usd": str(value + (D(8) - sold) * last_bid - D(8) * owner.entry)
            if scenario == "normal"
            else None,
            "max_house_exits": max((a["house_exits"] for a in manager.audits), default=0),
            "reservation_violations": [
                a
                for a in manager.audits
                if D(a["house_reserved"]) + D(a["owner_reserved"]) > D(a["position"])
            ],
            "owner_mutations": [a for a in manager.actions if a["order_id"].startswith("owner-")],
            "house_orders": [_order_row(o) for o in house],
            "owner_exits": [_order_row(o) for o in owner_exits],
            "resting_trails": [
                _order_row(o)
                for o in house
                if not o.is_closed and manager.owned[str(o.client_order_id)] == "trail"
            ],
            "cancel_ack_ns": cancel_ns,
            "limit_accepted_ns": accept_ns,
            "first_fill_ns": first_fill,
            "gap1_ns": accept_ns - cancel_ns
            if accept_ns is not None and cancel_ns is not None
            else None,
            "gap2_ns": first_fill - accept_ns
            if first_fill is not None and accept_ns is not None
            else None,
            "limit_submissions": sum(a["action"] == "limit" for a in manager.actions),
            "stops": manager.stops,
            "restarts": manager.restarts,
            "recovery_label": RECOVERY_LABEL,
            "recovery_operations": ["Strategy.stop", "Strategy.resume"],
            "paused": manager.paused,
            "pages": manager.pages,
            "exit_reason": manager.exit_reason,
            "emulations": sum(
                type(e).__name__ == "OrderEmulated" for o in house for e in o.events()
            ),
            "releases": sum(type(e).__name__ == "OrderReleased" for o in house for e in o.events()),
            "data_hash": _hash([str(d) for d in data]),
        }
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{arm}-{scenario}.json").write_text(json.dumps(result, indent=1))
        return result
    finally:
        engine.dispose()


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def run_case(
    out: Path,
    *,
    scenario: str = "normal",
    arm: str = "option-b",
    latency_ns: int = 200_000_000,
    run_id: str | None = None,
) -> dict:
    """Append every attempt, including failures, to the same ledger; artifacts never overwrite."""
    out.mkdir(parents=True, exist_ok=True)
    attempt = str(uuid4())
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    files = [Path(__file__), *sorted((Path(__file__).parents[1] / "exits").glob("*.py"))]
    row = {
        "run_id": run_id or str(uuid4()),
        "arm_run_id": attempt,
        "arm": arm,
        "tier": "MODELED" if arm == "hold" else "SIMULATED",
        "scenario": scenario,
        "implementation_sha": sha,
        "code_hash": _hash([p.read_text() for p in files]),
        "params_hash": _hash([asdict(FIXTURE), asdict(B_FIXTURE), latency_ns]),
        "data_hash": None,
        "latency_ns": latency_ns,
        "costs": "zero-fee synthetic mechanism witness; no TCA or merit",
        "artifact": f"runs/{attempt}/{arm}-{scenario}.json",
        "status": "failed",
    }
    try:
        if scenario not in {
            "normal",
            "after_cancel_ack",
            "after_limit_accept",
            "unfilled",
            "owner_add",
            "adopted_below",
            "outside",
            "owner_reserved",
        }:
            raise ValueError("unknown scenario")
        if arm not in {"option-b", "native-trail-o0", "hold"}:
            raise ValueError("unknown arm")
        if not isinstance(latency_ns, int) or latency_ns < 0:
            raise ValueError("latency_ns must be a nonnegative int")
        row["data_hash"] = _hash([str(d) for d in _data(scenario)])
        result = _simulate_case(
            out / "runs" / attempt, scenario=scenario, arm=arm, latency_ns=latency_ns
        )
        row.update({k: result[k] for k in ("gross_pnl_usd", "gap1_ns", "gap2_ns")})
        row["status"] = "completed"
        return result
    finally:
        with (out / "ledger.jsonl").open("a") as ledger:
            ledger.write(json.dumps(row) + "\n")


def run(out: Path, *, latency_ns: int = 200_000_000) -> list[dict]:
    run_id = str(uuid4())
    return [
        run_case(out, arm=arm, latency_ns=latency_ns, run_id=run_id)
        for arm in ("option-b", "native-trail-o0", "hold")
    ]


def run_suite(out: Path) -> dict:
    results = [
        r for delay in (100_000_000, 200_000_000, 1_200_000_000) for r in run(out, latency_ns=delay)
    ]
    for scenario in (
        "after_cancel_ack",
        "after_limit_accept",
        "unfilled",
        "owner_add",
        "adopted_below",
        "outside",
        "owner_reserved",
    ):
        results.append(run_case(out, scenario=scenario))
    measured = [r for r in results if r["arm"] == "option-b" and r["scenario"] == "normal"]
    distributions = {}
    for name in ("gap1_ns", "gap2_ns"):
        samples = sorted(r[name] for r in measured if r[name] is not None)
        distributions[name] = {
            "samples_ns": samples,
            "observed": len(samples),
            "censored": len(measured) - len(samples),
        }
    report = {
        "distributions": distributions,
        "attempts": len(results),
        "recovery_label": RECOVERY_LABEL,
        "limitation": "one-second synthetic quote grid; not a live latency bound",
    }
    (out / "summary.json").write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    print(json.dumps(run_suite(Path("reports/owner-b-witness")), indent=1))
