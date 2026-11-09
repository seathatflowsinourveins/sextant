"""A/C auto-entry node: slot 3 only, B's protection level, the registry's entry facts.

Rule 1 rows: `docs/manifest.md`. Slots 1 and 2 are refused in code; C's row
carries the owner's 2026-11-09 ruling: 1.0% of current equity, re-read before
each entry, with A's leverage row, UNCALIBRATED (ADR-0015/0018).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Protocol

from nautilus_trader.model import (
    AggressorSide,
    Equity,
    Money,
    Price,
    Quantity,
    TradeId,
    TradeTick,
)
from nautilus_trader.risk import FixedRiskSizer

from sextant.entry.orders import limit_price
from sextant.entry.parameters import EntryParameters, number
from sextant.entry.signals import EntryState, Surge
from sextant.paper.b_protector import Protector

REPOSITORY = Path(__file__).resolve().parents[3]
AC_PARAMETERS = REPOSITORY / "lanes/paper/ac-parameters.json"
B_PARAMETERS = REPOSITORY / "lanes/paper/b-parameters.json"
ENTRY_PARAMETERS = REPOSITORY / "lanes/sim/entry-parameters.json"

TRAIL_FRACTION = Decimal("0.025")
HALF_RISK = Decimal("0.5")
MOVER_SLOT_RANKS = 2
ENABLED = False
C_LANE = "alpaca-paper-c"
SLOT_LANES = {1: "peregrine-external", 2: "alpaca-paper-b", 3: C_LANE}
REFUSED_SLOTS = {
    1: "slot 1 is the owner's external Peregrine account, not a Sextant writer",
    2: "slot 2 belongs to B's writer (the owner-fill protector)",
}


class SlotRefusal(RuntimeError):
    pass


class NodeDisabled(RuntimeError):
    pass


class SizingRefusal(RuntimeError):
    pass


def require_writable_slot(slot: int | None) -> str:
    if slot is None:
        raise SlotRefusal("A has no paper account: replay and sim only")
    if slot in REFUSED_SLOTS:
        raise SlotRefusal(REFUSED_SLOTS[slot])
    if slot != 3:
        raise SlotRefusal(f"slot {slot} is not one of the paper lane's slots")
    return C_LANE


@dataclass(frozen=True)
class Profile:
    key: str
    lane: str
    slot: int | None
    risk_per_trade: Decimal
    risk_scope: str
    risk_source: str
    target_names: int
    mover_slots: int
    rank_ceilings: tuple[Decimal, Decimal, Decimal]
    equity_mode: str


def _row(rows: dict[str, dict[str, object]], name: str) -> dict[str, object]:
    row = rows.get(name)
    if not isinstance(row, dict) or any(
        row.get(key) in (None, "") for key in ("value", "unit", "scope", "calibration", "source")
    ):
        raise ValueError(f"{name}: incomplete registry row")
    if row["scope"] not in {"REVIEWED", "FIXTURE_ONLY"}:
        raise ValueError(f"{name}: unknown scope")
    if row["calibration"] not in {"UNCALIBRATED", "CALIBRATED"}:
        raise ValueError(f"{name}: unknown calibration")
    return row


def _number(rows: dict[str, dict[str, object]], name: str) -> Decimal:
    return number(_row(rows, name)["value"], name)


def _count(rows: dict[str, dict[str, object]], name: str) -> int:
    value = _number(rows, name)
    if value != int(value) or value <= 0:
        raise ValueError(f"{name}: must be a positive integer")
    return int(value)


def load_profiles(path: Path = AC_PARAMETERS) -> dict[str, Profile]:
    profiles = json.loads(path.read_text()).get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != {"a", "c"}:
        raise ValueError("profiles must hold exactly a and c")
    a, c = profiles["a"], profiles["c"]
    if not isinstance(a, dict) or not isinstance(c, dict):
        raise ValueError("profiles must hold objects")
    ceilings = (
        _number(a, "a_rank_ceiling_top"),
        _number(a, "a_rank_ceiling_mid"),
        _number(a, "a_rank_ceiling_rest"),
    )
    if (
        _row(a, "a_equity_mode")["value"] != "fixed"
        or _row(c, "c_equity_mode")["value"] != "current"
    ):
        raise ValueError("equity modes must be fixed for A and current for C")
    if a.get("slot") is not None or c.get("slot") != 3:
        raise ValueError("A has no paper slot; C writes slot 3 only")

    def build(key: str, rows: dict[str, dict[str, object]], lane: str, slot: int | None) -> Profile:
        risk = _row(rows, f"{key}_risk_per_trade")
        if risk["scope"] != "REVIEWED":
            raise ValueError(f"{key}_risk_per_trade: the reviewed authority is required")
        return Profile(
            key,
            lane,
            slot,
            _number(rows, f"{key}_risk_per_trade"),
            str(risk["scope"]),
            str(risk["source"]),
            _count(rows, f"{key}_target_names"),
            _count(rows, f"{key}_mover_slots"),
            ceilings,
            str(_row(rows, f"{key}_equity_mode")["value"]),
        )

    return {"a": build("a", a, "alpaca-paper-a", None), "c": build("c", c, C_LANE, 3)}


def rank_multiple(profile: Profile, rank: int | None) -> Decimal:
    if rank is None or not 1 <= rank <= 10:
        return profile.rank_ceilings[2]
    return profile.rank_ceilings[0] if rank <= 5 else profile.rank_ceilings[1]


@dataclass(frozen=True)
class EntryPlan:
    profile: str
    lane: str
    symbol: str
    ts_ns: int
    setup: str
    rank: int | None = None
    limit: Price | None = None
    quantity: Quantity | None = None
    stop: Price | None = None
    planned_risk: Money | None = None
    notional: Money | None = None
    binding: str = ""
    refusal: str = ""

    @property
    def accepted(self) -> bool:
        return not self.refusal


def refused_plan(
    profile: Profile, *, symbol: str, ts_ns: int, setup: str, rank: int | None, reason: str
) -> EntryPlan:
    return EntryPlan(profile.key, profile.lane, symbol, ts_ns, setup, rank=rank, refusal=reason)


def _floor(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise ValueError("non-positive increment")
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def plan_entry(
    profile: Profile,
    *,
    instrument: Equity,
    symbol: str,
    ts_ns: int,
    ask: Decimal,
    equity: Money,
    setup: str,
    rank: int | None,
    regular_hours: bool,
    fixture: bool,
    commission_rate: Decimal = Decimal(0),
) -> EntryPlan:

    def refuse(reason: str) -> EntryPlan:
        return refused_plan(
            profile, symbol=symbol, ts_ns=ts_ns, setup=setup, rank=rank, reason=reason
        )

    if profile.risk_scope == "FIXTURE_ONLY" and not fixture:
        return refuse(f"{profile.key}_risk_per_trade: the registry row is not reviewed")
    tick = instrument.price_increment.as_decimal()
    stop_value = _floor(ask * (1 - TRAIL_FRACTION), tick)
    risk = profile.risk_per_trade * (Decimal(1) if regular_hours else HALF_RISK)
    ceiling = rank_multiple(profile, rank)
    if not ask.is_finite() or ask <= 0 or not 0 < stop_value < ask or risk <= 0 or ceiling <= 0:
        return refuse("invalid ask, stop or risk")
    try:
        entry = Price.from_str(f"{ask:.{instrument.price_precision}f}")
        stop = Price.from_str(f"{stop_value:.{instrument.price_precision}f}")
    except (ValueError, ArithmeticError):
        return refuse("price precision")
    if entry.as_decimal() != ask or stop.as_decimal() != stop_value:
        return refuse("price_increment")
    planned = equity.as_decimal() * risk
    cap = _floor(equity.as_decimal() * ceiling / ask, instrument.size_increment.as_decimal())
    try:
        quantity = FixedRiskSizer(instrument).calculate(
            entry=entry,
            stop_loss=stop,
            equity=equity,
            risk=risk,
            commission_rate=commission_rate,
            hard_limit=cap,
        )
        whole = _floor(quantity.as_decimal(), instrument.size_increment.as_decimal())
        minimum = instrument.min_quantity or instrument.lot_size or Quantity.from_int(1)
        if whole < minimum.as_decimal():
            raise ValueError("quantity below the instrument's minimum")
    except (ValueError, ArithmeticError, ZeroDivisionError) as error:
        return refuse(f"sizing refusal: {error}")
    limit = limit_price(ask, tick)
    return EntryPlan(
        profile.key,
        profile.lane,
        symbol,
        ts_ns,
        setup,
        rank=rank,
        limit=Price.from_str(f"{limit:.{instrument.price_precision}f}"),
        quantity=Quantity.from_int(int(whole)),
        stop=stop,
        planned_risk=Money.from_str(f"{planned} {instrument.quote_currency}"),
        notional=Money.from_str(f"{whole * ask} {instrument.quote_currency}"),
        binding="cap" if whole >= cap else "risk",
    )


@dataclass(frozen=True)
class Catalyst:
    knowable_at_ns: int
    quiet_price: Decimal
    source: str


class AcEntry:
    def __init__(
        self,
        *,
        instrument: Equity,
        params: EntryParameters,
        profile: Profile,
        start_ns: int,
        segment: str,
        equity: Money,
        fixture: bool = False,
        equity_source: Callable[[], Money] | None = None,
    ) -> None:
        self.instrument = instrument
        self.profile = profile
        self.state = EntryState(instrument.id, params, segment, start_ns=start_ns)
        self.start_ns = start_ns
        self.equity = equity
        self.fixture = fixture
        self._equity_source = equity_source
        self.armed_rank: int | None = None
        self.catalyst: Catalyst | None = None
        self._sequence = 0

    def _sizing_equity(self) -> Money:
        return self._equity_source() if self._equity_source is not None else self.equity

    def _plan(
        self, *, ts_ns: int, ask: Decimal, setup: str, rank: int | None, regular_hours: bool
    ) -> EntryPlan:
        return plan_entry(
            self.profile,
            instrument=self.instrument,
            symbol=str(self.instrument.id.symbol),
            ts_ns=ts_ns,
            ask=ask,
            equity=self._sizing_equity(),
            setup=setup,
            rank=rank,
            regular_hours=regular_hours,
            fixture=self.fixture,
        )

    def _refuse(self, *, ts_ns: int, setup: str, rank: int | None, reason: str) -> EntryPlan:
        return refused_plan(
            self.profile,
            symbol=str(self.instrument.id.symbol),
            ts_ns=ts_ns,
            setup=setup,
            rank=rank,
            reason=reason,
        )

    def observe_rank(
        self,
        *,
        ts_ns: int,
        rank: int,
        quiet_price: Decimal,
        first_print_ts: int,
        source: str = "recorded K2 generation",
    ) -> bool:
        if not 1 <= rank <= MOVER_SLOT_RANKS or self.armed_rank is not None:
            return False
        self.state.arm(
            Surge(
                self.instrument.id,
                self.state.segment,
                first_print_ts,
                ts_ns,
                ts_ns,
                ts_ns + self.state.params.ns("first_leg_window_s"),
                quiet_price,
                source,
            )
        )
        self.armed_rank = rank
        return True

    def observe_catalyst(self, *, knowable_at_ns: int, quiet_price: Decimal, source: str) -> bool:
        if self.catalyst is not None:
            return False
        self.catalyst = Catalyst(knowable_at_ns, quiet_price, source)
        return True

    def _tick(self, ts_ns: int, price: Decimal, size: int) -> TradeTick:
        self._sequence += 1
        return TradeTick(
            instrument_id=self.instrument.id,
            price=Price.from_str(f"{price:.{self.instrument.price_precision}f}"),
            size=Quantity.from_int(size),
            aggressor_side=AggressorSide.NO_AGGRESSOR,
            trade_id=TradeId(f"AC-{self.instrument.id.symbol}-{self._sequence}"),
            ts_event=ts_ns,
            ts_init=ts_ns,
        )

    def observe_print(
        self,
        *,
        ts_ns: int,
        price: Decimal,
        size: int,
        regular_hours: bool,
        ask: Decimal | None = None,
        ask_ts_ns: int | None = None,
    ) -> EntryPlan | None:
        """Feed one recorded print; return a plan only when the setup is ready."""
        self.state.on_trade(self._tick(ts_ns, price, size), now=ts_ns)
        max_age = self.state.params.ns("max_data_age_s")
        fresh = ask is not None and ask_ts_ns is not None and 0 <= ts_ns - ask_ts_ns <= max_age
        if self.catalyst is not None and ts_ns >= self.catalyst.knowable_at_ns:
            self.catalyst = None
            if not fresh or ask is None:
                return self._refuse(
                    ts_ns=ts_ns,
                    setup="CATALYST",
                    rank=None,
                    reason="no fresh ask at the catalyst print",
                )
            return self._plan(
                ts_ns=ts_ns, ask=ask, setup="CATALYST", rank=None, regular_hours=regular_hours
            )
        if ask is None or ask_ts_ns is None:
            return None
        if not fresh:
            return self._refuse(
                ts_ns=ts_ns,
                setup="FIRST_LEG",
                rank=self.armed_rank,
                reason="no fresh ask at the run completion",
            )
        if self.state.first_leg_ready(ask, ts_ns):
            return self._plan(
                ts_ns=ts_ns,
                ask=ask,
                setup="FIRST_LEG",
                rank=self.armed_rank,
                regular_hours=regular_hours,
            )
        return None


@dataclass
class AcLedger:
    start_equity: Money
    mode: str
    realized: Decimal = Decimal(0)

    def sizing_equity(self) -> Money:
        value = self.start_equity.as_decimal()
        value += self.realized if self.mode == "current" else Decimal(0)
        return Money.from_str(f"{value} {self.start_equity.currency}")

    def record(self, *, entry: Decimal, exit_price: Decimal, quantity: Decimal) -> Decimal:
        change = (exit_price - entry) * quantity
        self.realized += change
        return change

    def end_equity(self) -> Money:
        return Money.from_str(
            f"{self.start_equity.as_decimal() + self.realized} {self.start_equity.currency}"
        )


class GuardLike(Protocol):
    def entry_allowed(self) -> bool: ...


class WriterLike(Protocol):
    @property
    def held(self) -> bool: ...

    def acquire(self) -> None: ...

    def bind_pacer(self, pacer: object) -> None: ...


@dataclass
class Deployment:
    writer: WriterLike
    pacer: object
    guard: GuardLike
    protector: Protector


class AcNode:
    def __init__(
        self,
        *,
        profile: Profile,
        params: EntryParameters,
        start_equity: Money,
        enabled: bool = ENABLED,
        deployment: Deployment | None = None,
    ) -> None:
        self.profile = profile
        self.params = params
        self.ledger = AcLedger(start_equity, profile.equity_mode)
        self.enabled = enabled
        self.deployment = deployment
        self._opened = False

    def entry(self, *, instrument: Equity, start_ns: int, segment: str) -> AcEntry:
        return AcEntry(
            instrument=instrument,
            params=self.params,
            profile=self.profile,
            start_ns=start_ns,
            segment=segment,
            equity=self.ledger.sizing_equity(),
            equity_source=self.ledger.sizing_equity,
        )

    def open(self) -> None:
        if not self.enabled:
            raise NodeDisabled("the A/C node ships disabled (enabled=0)")
        require_writable_slot(self.profile.slot)
        if self.profile.risk_scope == "FIXTURE_ONLY":
            raise SizingRefusal(
                f"{self.profile.key}_risk_per_trade is FIXTURE_ONLY: fixture authority "
                "cannot open a writer lease"
            )
        if self.deployment is None:
            raise NodeDisabled("no writer lease, pacer, guard or protector wired")
        self.deployment.writer.acquire()
        self.deployment.writer.bind_pacer(self.deployment.pacer)
        self._opened = True

    def protect_account(self) -> None:
        if not self.enabled or self.deployment is None:
            raise NodeDisabled("the A/C node ships disabled (enabled=0)")
        if not self._opened:
            raise NodeDisabled("no writer lease is held: refusing broker protection")
        if not getattr(self.deployment.writer, "held", False):
            raise NodeDisabled("the writer lease is not held: refusing broker protection")
        protector = self.deployment.protector
        if protector.account.lane != self.profile.lane:
            raise NodeDisabled("the protector is not bound to this profile's lane")
        protector.bind()
        protector.reconcile()


def profiles() -> dict[str, Profile]:
    return load_profiles(AC_PARAMETERS)


def entry_parameters(fixture: bool = False) -> EntryParameters:
    rows = json.loads(ENTRY_PARAMETERS.read_text())
    return EntryParameters.from_rows(rows, fixture=fixture, first_leg_only=True)
