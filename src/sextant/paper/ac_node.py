"""A/C auto-entry node: slot 3 only, B's protection level, the registry's entry facts.

Sources are the Rule 1 rows in ``docs/manifest.md``: the paper-node shell and
its offline order gate, B's owner-fill protector on alpaca-py ``v0.44.0``, the
N1 first-leg rows (northstar-trading ``8256c16c``), ADR-0002's account shape,
ADR-0011's ``FixedRiskSizer`` and ADR-0024's mover slots. The node refuses
slots 1 and 2 in code (slot 1 is the owner's external Peregrine account; A has
no paper account and runs replay/sim only), so the only writable slot is C's
slot 3, sharing its one REST allocation with TV-HOST through a single pacer.
C's registry row carries the owner's 2026-11-09 ruling: 1.0% of current equity,
re-read before each entry, with A's leverage row, UNCALIBRATED, the optimizer
proposing and adoption happening between sessions (ADR-0015/0018).
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
from sextant.paper.b_protector import (
    BParameters,
    Protector,
    TradingClientLike,
    load_b_parameters,
)
from sextant.paper.config import PaperAccount

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
    """A slot or account shape the node will not write."""


class NodeDisabled(RuntimeError):
    """The node ships disabled and no deployment opened it."""


class SizingRefusal(RuntimeError):
    """The profile's sizing authority is not a deployment authority."""


@dataclass(frozen=True)
class Slot:
    number: int
    lane: str
    writable: bool
    reason: str


SLOTS = {
    number: Slot(number, lane, number == 3, REFUSED_SLOTS.get(number, ""))
    for number, lane in SLOT_LANES.items()
}


def require_writable_slot(slot: int | None) -> Slot:
    """Refuse slots 1 and 2 and every slot other than C's slot 3."""
    if slot is None:
        raise SlotRefusal("A has no paper account: replay and sim only")
    if slot in REFUSED_SLOTS:
        raise SlotRefusal(REFUSED_SLOTS[slot])
    if slot != 3:
        raise SlotRefusal(f"slot {slot} is not one of the paper lane's slots")
    return SLOTS[slot]


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
    if not isinstance(row, dict):
        raise ValueError(f"{name}: missing profile row")
    for key in ("value", "unit", "scope", "calibration", "source", "last_change"):
        if row.get(key) in (None, ""):
            raise ValueError(f"{name}: missing {key}")
    if row["scope"] not in {"REVIEWED", "FIXTURE_ONLY"}:
        raise ValueError(f"{name}: unreviewed authority")
    if row["calibration"] not in {"UNCALIBRATED", "CALIBRATED"}:
        raise ValueError(f"{name}: invalid calibration")
    return row


def _number(rows: dict[str, dict[str, object]], name: str) -> Decimal:
    return number(_row(rows, name)["value"], name)


def _count(rows: dict[str, dict[str, object]], name: str) -> int:
    value = _number(rows, name)
    if value != value.to_integral_value() or value < 1:
        raise ValueError(f"{name}: not a positive count")
    return int(value)


def load_profiles(path: Path = AC_PARAMETERS) -> dict[str, Profile]:
    """Read the two profile rows; validate every field and scope."""
    document = json.loads(path.read_text())
    profiles = document.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != {"a", "c"}:
        raise ValueError("profiles must hold exactly a and c")
    a_rows = profiles["a"]
    c_rows = profiles["c"]
    for name, rows in (("a", a_rows), ("c", c_rows)):
        if not isinstance(rows, dict):
            raise ValueError(f"{name}: profile rows must be an object")
    ceilings = (
        _number(a_rows, "a_rank_ceiling_top"),
        _number(a_rows, "a_rank_ceiling_mid"),
        _number(a_rows, "a_rank_ceiling_rest"),
    )
    mode = _row(a_rows, "a_equity_mode")["value"]
    if mode != "fixed":
        raise ValueError("a_equity_mode: A sizes on the frozen segment basis")
    c_mode = _row(c_rows, "c_equity_mode")["value"]
    if c_mode != "current":
        raise ValueError("c_equity_mode: C sizes on current equity")
    a_slot, c_slot = profiles["a"].get("slot"), profiles["c"].get("slot")
    if a_slot is not None:
        raise ValueError("A has no paper slot")
    if c_slot != 3:
        raise ValueError("C writes slot 3 only")
    a_risk = _row(a_rows, "a_risk_per_trade")
    c_risk = _row(c_rows, "c_risk_per_trade")
    if a_risk["scope"] != "REVIEWED":
        raise ValueError("a_risk_per_trade: ADR-0002 is reviewed")
    if c_risk["scope"] != "REVIEWED":
        raise ValueError("c_risk_per_trade: the owner's current-equity ruling is reviewed")
    return {
        "a": Profile(
            "a",
            "alpaca-paper-a",
            None,
            _number(a_rows, "a_risk_per_trade"),
            str(a_risk["scope"]),
            str(a_risk["source"]),
            _count(a_rows, "a_target_names"),
            _count(a_rows, "a_mover_slots"),
            ceilings,
            "fixed",
        ),
        "c": Profile(
            "c",
            C_LANE,
            3,
            _number(c_rows, "c_risk_per_trade"),
            str(c_risk["scope"]),
            str(c_risk["source"]),
            _count(c_rows, "c_target_names"),
            _count(c_rows, "c_mover_slots"),
            ceilings,
            "current",
        ),
    }


def rank_multiple(profile: Profile, rank: int | None) -> Decimal:
    """ADR-0002's rank ceiling for a mover rank: 1-5, 6-10, rest."""
    if rank is None:
        return Decimal(1)
    if not 1 <= rank <= 10:
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
    trail_fraction: Decimal = TRAIL_FRACTION
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
    return EntryPlan(
        profile.key,
        profile.lane,
        symbol,
        ts_ns,
        setup,
        rank=rank,
        refusal=reason,
    )


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
    """Size one plain-LIMIT buy from the row's risk and B's protection distance.

    The stop distance is B's protection level: ``ask * (1 - native_trail_fraction)``.
    The node never sizes a market order; the exit and protection orders stay with
    B's protector, which the node wires rather than re-implements.
    """

    def refuse(reason: str) -> EntryPlan:
        return refused_plan(
            profile, symbol=symbol, ts_ns=ts_ns, setup=setup, rank=rank, reason=reason
        )

    if profile.risk_scope == "FIXTURE_ONLY" and not fixture:
        return refuse(
            f"{profile.key}_risk_per_trade: FIXTURE_ONLY authority cannot size a non-fixture entry"
        )
    if not ask.is_finite() or ask <= 0:
        return refuse("invalid ask")
    # ADR-0002 sizes every trade at the profile's risk fraction; the rank ceiling is
    # an exposure cap on the position, never a multiplier of the planned loss.
    risk = profile.risk_per_trade
    if not regular_hours:
        risk *= HALF_RISK
    ceiling = rank_multiple(profile, rank)
    if risk <= 0 or ceiling <= 0:
        return refuse("invalid risk")
    tick = instrument.price_increment.as_decimal()
    stop_value = _floor(ask * (1 - TRAIL_FRACTION), tick)
    if not 0 < stop_value < ask:
        return refuse("invalid stop")
    try:
        entry = Price.from_str(f"{ask:.{instrument.price_precision}f}")
        stop = Price.from_str(f"{stop_value:.{instrument.price_precision}f}")
    except (ValueError, ArithmeticError):
        return refuse("price precision")
    if entry.as_decimal() != ask or stop.as_decimal() != stop_value:
        return refuse("price_increment")
    exposure = equity.as_decimal() * ceiling
    cap = _floor(exposure / ask, instrument.size_increment.as_decimal())
    planned = equity.as_decimal() * risk
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
        minimum = instrument.min_quantity
        if minimum is None:
            minimum = instrument.lot_size
        if minimum is None:
            minimum = Quantity.from_int(1)
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
        trail_fraction=TRAIL_FRACTION,
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
    """One symbol's entry state: a K2 first leg or a scheduled catalyst."""

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
        self.segment_start_ns = start_ns
        self.equity = equity
        self.fixture = fixture
        self._equity_source = equity_source
        self.armed_rank: int | None = None
        self.catalyst: Catalyst | None = None
        self._sequence = 0

    def _sizing_equity(self) -> Money:
        """Read the live basis at the decision point; C compounds on this value."""
        if self._equity_source is not None:
            return self._equity_source()
        return self.equity

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
        surge = Surge(
            self.instrument.id,
            self.state.segment,
            first_print_ts,
            ts_ns,
            ts_ns,
            ts_ns + self.state.params.ns("first_leg_window_s"),
            quiet_price,
            source,
        )
        self.state.arm(surge)
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
        usable = ask is not None and ask_ts_ns is not None
        fresh = False
        if ask is not None and ask_ts_ns is not None:
            fresh = 0 <= ts_ns - ask_ts_ns <= max_age
        if self.catalyst is not None and ts_ns >= self.catalyst.knowable_at_ns:
            self.catalyst = None
            if not fresh:
                return self._refuse(
                    ts_ns=ts_ns,
                    setup="CATALYST",
                    rank=None,
                    reason="no fresh ask at the catalyst print",
                )
            assert ask is not None
            return plan_entry(
                self.profile,
                instrument=self.instrument,
                symbol=str(self.instrument.id.symbol),
                ts_ns=ts_ns,
                ask=ask,
                equity=self._sizing_equity(),
                setup="CATALYST",
                rank=None,
                regular_hours=regular_hours,
                fixture=self.fixture,
            )
        if not usable:
            return None
        assert ask is not None
        if not fresh:
            return self._refuse(
                ts_ns=ts_ns,
                setup="FIRST_LEG",
                rank=self.armed_rank,
                reason="no fresh ask at the run completion",
            )
        if self.state.first_leg_ready(ask, ts_ns):
            return plan_entry(
                self.profile,
                instrument=self.instrument,
                symbol=str(self.instrument.id.symbol),
                ts_ns=ts_ns,
                ask=ask,
                equity=self._sizing_equity(),
                setup="FIRST_LEG",
                rank=self.armed_rank,
                regular_hours=regular_hours,
                fixture=self.fixture,
            )
        return None


@dataclass
class AcLedger:
    """The account's realized path: A freezes the basis, C compounds."""

    start_equity: Money
    mode: str
    realized: Decimal = Decimal(0)
    fills: int = 0

    def sizing_equity(self) -> Money:
        equity = self.start_equity.as_decimal()
        if self.mode == "current":
            equity += self.realized
        return Money.from_str(f"{equity} {self.start_equity.currency}")

    def record(self, *, entry: Decimal, exit_price: Decimal, quantity: Decimal) -> Decimal:
        change = (exit_price - entry) * quantity
        self.realized += change
        self.fills += 1
        return change

    def end_equity(self) -> Money:
        equity = self.start_equity.as_decimal() + self.realized
        return Money.from_str(f"{equity} {self.start_equity.currency}")


class GuardLike(Protocol):
    """The row-8 guard seam; the node never implements a second guard."""

    def entry_allowed(self) -> bool: ...


class WriterLike(Protocol):
    """The one-writer lease seam; C shares slot 3's single pacer through it."""

    @property
    def held(self) -> bool: ...

    def acquire(self) -> None: ...

    def bind_pacer(self, pacer: object) -> None: ...


@dataclass
class Deployment:
    """The one live wiring: slot 3's writer lease, its single pacer and B's protector."""

    writer: WriterLike
    pacer: object
    guard: GuardLike
    protector: Protector


class AcNode:
    """Ships disabled; opens only C's slot 3 with the shared writer wiring."""

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
        writer = self.deployment.writer
        writer.acquire()
        writer.bind_pacer(self.deployment.pacer)
        self._opened = True

    def protector_for(self, client: TradingClientLike, account: PaperAccount) -> Protector:
        """B's merged protector, admitted for slot 3's lane by its lane seam."""
        require_writable_slot(self.profile.slot)
        return Protector(
            client,
            account,
            load_b_parameters(B_PARAMETERS),
            lane=C_LANE,
        )

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
    """The nine reviewed N1 first-leg rows; the 18 sizing rows stay unread."""
    rows = json.loads(ENTRY_PARAMETERS.read_text())
    return EntryParameters.from_rows(rows, fixture=fixture, first_leg_only=True)


def b_parameters() -> BParameters:
    return load_b_parameters(B_PARAMETERS)
