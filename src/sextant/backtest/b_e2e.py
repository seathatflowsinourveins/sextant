"""PR-3: a historical end-to-end replay of the owner's entry and B's protection.

Template: NautilusTrader's official trailing-stop example strategy
(``nautechsystems/nautilus_trader@v1.231.0:
nautilus_trader/examples/strategies/ema_cross_trailing_stop.py``) and its
BacktestEngine examples, with entry changed to the owner's fill at time T. The
broker-held protection is the same ``trailing_stop_market`` the live owner-B
protector submits for the owner's PARA fill (``tests/fixtures/b-trades.jsonl``,
trail_percent 2.5). This module is a research replay: it writes MODELED
TrialLog rows and a per-case report, and it changes no live code path.

Two entry arms, per ``b-clean/BRIEF.md``'s 12:19 and 10:4x addenda:

- ``reference``: buy at the owner's fill (or the case's labelled stand-in).
- ``catalyst``: buy the first print at or after the EDGAR ``knowable_at``.
- ``first_leg``: arm on the recorded K2 rank path and buy the first
  non-decreasing run of ``first_leg_trades_count`` prints inside
  ``first_leg_window_s`` and within ``first_leg_max_move`` of the quiet price.

The 2.5% trailing stop is B's protection level. Outside regular hours BManager
releases an emulated BID_ASK trail with a ``limit_offset``; that offset's
``chase_cap_fraction`` row is UNAVAILABLE, so this replay models the same 2.5%
level with the in-hours LAST_PRICE trail and records that substitution in the
report. The persistent-breach fast exit is likewise recorded as the trail's
own trigger path, not re-ordered; its chase rows are UNAVAILABLE.

Every run appends rows to the one cumulative ledger
(``reports/research/trials.parquet``) through ``src/sextant/validation/trials.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, RiskEngineConfig, StrategyConfig
from nautilus_trader.execution import DefaultFillModel, MakerTakerFeeModel, StaticLatencyModel
from nautilus_trader.model import (
    AccountType,
    AggressorSide,
    InstrumentId,
    Money,
    OmsType,
    OrderSide,
    Price,
    Quantity,
    TimeInForce,
    TradeId,
    TraderId,
    TradeTick,
    TrailingOffsetType,
    TriggerType,
    Venue,
)
from nautilus_trader.trading import Strategy

from sextant.data.catalog import equity
from sextant.validation.trials import TrialLog, snapshot_hash

NS = 1_000_000_000
EASTERN = ZoneInfo("America/New_York")
TRAIL_FRACTION = Decimal("0.025")
QUANTITY = Decimal("50")
ARMS = ("reference", "catalyst", "first_leg")
_RULE_PATH = Path(__file__).resolve().parents[3] / "lanes/sim/entry-parameters.json"


@dataclass(frozen=True)
class EntryRule:
    window_s: int
    trades: int
    span_s: int
    max_move: Decimal
    source: str = "lanes/sim/entry-parameters.json"


@dataclass(frozen=True)
class Print:
    ts_ns: int
    price: Decimal
    size: int = 100


@dataclass(frozen=True)
class RankRow:
    known_at_ns: int
    rank: int
    quiet_price: Decimal
    first_print_ns: int


@dataclass(frozen=True)
class CaseSpec:
    case: str
    symbol: str
    session: str
    prior_close: Decimal
    last_price: Decimal
    prints: tuple[Print, ...]
    owner_fill: Print | None = None
    reference_label: str = ""
    catalyst_ns: int | None = None
    catalyst_label: str = ""
    rank: tuple[RankRow, ...] = ()
    trail_fraction: Decimal = TRAIL_FRACTION
    quantity: Decimal = QUANTITY
    rule: EntryRule = field(default_factory=lambda: reviewed_rule())
    source: str = ""
    hashes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Trigger:
    ts_ns: int
    price: Decimal
    arm: str
    label: str


@dataclass(frozen=True)
class Pick:
    trigger: Trigger | None
    reason: str = ""


@dataclass(frozen=True)
class ArmResult:
    arm: str
    state: str
    reason: str = ""
    note: str = ""
    trigger: Trigger | None = None
    entry_price: Decimal | None = None
    entry_ts_ns: int | None = None
    high: Decimal | None = None
    trail_level: Decimal | None = None
    exit_price: Decimal | None = None
    exit_ts_ns: int | None = None
    protected: float | None = None
    hold_flat: float | None = None
    path: tuple[tuple[int, Decimal, Decimal, Decimal], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "arm": self.arm,
            "state": self.state,
            "reason": self.reason,
            "note": self.note,
            "trigger": _trigger_dict(self.trigger),
            "entry_price": _str(self.entry_price),
            "entry_ts": _iso(self.entry_ts_ns),
            "high": _str(self.high),
            "trail_level": _str(self.trail_level),
            "exit_price": _str(self.exit_price),
            "exit_ts": _iso(self.exit_ts_ns),
            "protected": self.protected,
            "hold_flat": self.hold_flat,
            "path": [
                {"ts": _iso(ts), "price": _str(px), "high": _str(hi), "level": _str(level)}
                for ts, px, hi, level in self.path
            ],
        }


def _str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _iso(ts_ns: int | None) -> str | None:
    if ts_ns is None:
        return None
    dt = datetime.fromtimestamp(ts_ns / NS, tz=UTC)
    return dt.isoformat().replace("+00:00", "Z")


def _trigger_dict(trigger: Trigger | None) -> dict[str, object] | None:
    if trigger is None:
        return None
    return {
        "ts": _iso(trigger.ts_ns),
        "price": str(trigger.price),
        "arm": trigger.arm,
        "label": trigger.label,
    }


def _ns_from_datetime(stamp: datetime) -> int:
    utc = stamp.astimezone(UTC) if stamp.tzinfo else stamp.replace(tzinfo=UTC)
    delta = utc - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * NS + delta.microseconds * 1_000


def _ns(text: str) -> int:
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = dt.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * NS + delta.microseconds * 1_000


def _is_rth(ts_ns: int) -> bool:
    local = datetime.fromtimestamp(ts_ns / NS, tz=EASTERN)
    if local.weekday() >= 5:
        return False
    return time(9, 30) <= local.time() < time(16, 0)


def reviewed_rule(path: Path | None = None) -> EntryRule:
    """Read the four reviewed N1 rows from the one entry-parameter registry."""
    rows = {row["name"]: row for row in json.loads((path or _RULE_PATH).read_text())}
    picked: dict[str, Decimal] = {}
    for name in (
        "first_leg_window_s",
        "first_leg_trades_count",
        "first_leg_span_s",
        "first_leg_max_move",
    ):
        row = rows[name]
        if row["scope"] != "REVIEWED" or row["value"] is None:
            raise ValueError(f"{name} is not a REVIEWED value: {row['scope']}")
        picked[name] = Decimal(str(row["value"]))
    return EntryRule(
        window_s=int(picked["first_leg_window_s"]),
        trades=int(picked["first_leg_trades_count"]),
        span_s=int(picked["first_leg_span_s"]),
        max_move=picked["first_leg_max_move"],
        source="lanes/sim/entry-parameters.json: REVIEWED, UNCALIBRATED",
    )


def load_spec(path: Path) -> CaseSpec:
    data = json.loads(Path(path).read_text())
    prints = tuple(
        Print(_ns(p["ts"]), Decimal(p["price"]), int(p.get("size", 100))) for p in data["prints"]
    )
    owner = data.get("owner_fill")
    owner_fill = (
        Print(_ns(owner["ts"]), Decimal(owner["price"]), int(owner.get("size", 50)))
        if owner
        else None
    )
    catalyst = data.get("catalyst")
    rank = tuple(
        RankRow(
            _ns(r["known_at"]), int(r["rank"]), Decimal(r["quiet_price"]), _ns(r["first_print"])
        )
        for r in data.get("rank", [])
    )
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return CaseSpec(
        case=data["case"],
        symbol=data["symbol"],
        session=data["session"],
        prior_close=Decimal(data["prior_close"]),
        last_price=Decimal(data["last_price"]),
        prints=prints,
        owner_fill=owner_fill,
        reference_label=data.get("reference_label", ""),
        catalyst_ns=_ns(catalyst["knowable_at"]) if catalyst else None,
        catalyst_label=catalyst.get("label", "") if catalyst else "",
        rank=rank,
        trail_fraction=Decimal(data.get("trail_fraction", "0.025")),
        quantity=Decimal(data.get("quantity", "50")),
        rule=reviewed_rule(),
        source=data.get("source", f"fixture {Path(path).name}"),
        hashes=(("fixture", digest),),
    )


def reference_pick(spec: CaseSpec) -> Pick:
    if spec.owner_fill is not None:
        label = spec.reference_label or "owner fill at T"
        return Pick(Trigger(spec.owner_fill.ts_ns, spec.owner_fill.price, "reference", label))
    if not spec.prints:
        return Pick(None, "no prints in the case tape")
    first = min(spec.prints, key=lambda p: p.ts_ns)
    label = spec.reference_label or "no owner fill recorded; the move's first print"
    return Pick(Trigger(first.ts_ns, first.price, "reference", label))


def catalyst_pick(spec: CaseSpec) -> Pick:
    if spec.catalyst_ns is None:
        return Pick(None, "no scheduled catalyst (EDGAR knowable_at) is recorded for this case")
    for item in sorted(spec.prints, key=lambda p: p.ts_ns):
        if item.ts_ns >= spec.catalyst_ns:
            label = spec.catalyst_label or "first print at or after knowable_at"
            return Pick(Trigger(item.ts_ns, item.price, "catalyst", label))
    return Pick(None, "no print at or after the EDGAR knowable_at")


def first_leg_pick(spec: CaseSpec) -> Pick:
    if not spec.rank:
        return Pick(None, "no recorded K2 rank path for this case")
    rule = spec.rule
    prints = sorted(spec.prints, key=lambda p: p.ts_ns)
    first_reason = ""
    for row in sorted(spec.rank, key=lambda r: r.known_at_ns):
        if row.rank < 1 or row.rank > 2:
            continue
        horizon = row.known_at_ns + rule.window_s * NS
        run: list[Print] = []
        for item in prints:
            if item.ts_ns < row.known_at_ns:
                continue
            if item.ts_ns > horizon:
                break
            if item.price <= row.quiet_price:
                run = []
                continue
            if item.price > row.quiet_price * (1 + rule.max_move):
                if not first_reason:
                    move = (item.price / row.quiet_price - 1) * 100
                    first_reason = (
                        f"first print {item.price} is +{move:.1f}% above the "
                        f"{row.quiet_price} quiet price, beyond first_leg_max_move "
                        f"{rule.max_move * 100:.1f}%"
                    )
                run = []
                break
            if run and item.price < run[-1].price:
                run = [item]
            else:
                run.append(item)
            if len(run) >= rule.trades and run[-1].ts_ns - run[0].ts_ns >= rule.span_s * NS:
                label = (
                    f"{len(run)} non-decreasing prints from {run[0].price} to "
                    f"{item.price} within {rule.max_move * 100:.1f}% of {row.quiet_price}"
                )
                return Pick(Trigger(item.ts_ns, item.price, "first_leg", label))
    return Pick(None, first_reason or "no five-print non-decreasing run within the 120s window")


class _ProtectConfig(StrategyConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        trigger_ns: int,
        trigger_price: Decimal,
        quantity: Decimal,
        trail_fraction: Decimal,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.trigger_ns = trigger_ns
        self.trigger_price = trigger_price
        self.quantity = quantity
        self.trail_fraction = trail_fraction


class _Protect(Strategy):
    """The official example's shape: enter at T, then hold a reduce-only trail."""

    def __init__(self, config: _ProtectConfig) -> None:
        super().__init__(config)
        self.instrument: Any = None
        self.entered = False
        self.entry_cid = None
        self.trail_cid = None
        self.entry_price: Decimal | None = None
        self.entry_ts_ns: int | None = None
        self.exit_price: Decimal | None = None
        self.exit_ts_ns: int | None = None
        self.exit_qty = Decimal(0)
        self.exit_notional = Decimal(0)
        self.exited = False
        self.position_id = None
        self.high: Decimal | None = None
        self.level: Decimal | None = None
        self.path: list[tuple[int, Decimal, Decimal, Decimal]] = []
        self.rejected = ""

    @property
    def cfg(self) -> _ProtectConfig:
        config = self.config
        assert isinstance(config, _ProtectConfig)
        return config

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.cfg.instrument_id)
        if self.instrument is None:
            raise RuntimeError(f"instrument {self.cfg.instrument_id} is not in the cache")
        self.subscribe_trades(self.cfg.instrument_id)

    def on_trade(self, trade: TradeTick) -> None:
        assert self.instrument is not None
        price = trade.price.as_decimal()
        if not self.entered and trade.ts_event >= self.cfg.trigger_ns:
            self.entered = True
            order = self.order_factory.limit(
                instrument_id=self.cfg.instrument_id,
                order_side=OrderSide.BUY,
                quantity=self.instrument.make_qty(self.cfg.quantity),
                price=_price(self.instrument, self.cfg.trigger_price),
                time_in_force=TimeInForce.GTC,
            )
            self.entry_cid = order.client_order_id
            self.submit_order(order)
        if self.entry_price is None or self.exited:
            return
        if self.high is None or price > self.high:
            self.high = price
        level = self.high * (1 - self.cfg.trail_fraction)
        self.level = level
        if not self.path or self.path[-1][2] != self.high:
            self.path.append((trade.ts_event, price, self.high, level))

    def on_position_opened(self, event) -> None:
        assert self.instrument is not None
        position = self.cache.position(event.position_id)
        if position is None:
            raise RuntimeError(f"position {event.position_id} is not in the cache")
        self.position_id = event.position_id
        entry = position.avg_px_open
        self.entry_price = entry
        self.high = entry
        self.level = entry * (1 - self.cfg.trail_fraction)
        order = self.order_factory.trailing_stop_market(
            instrument_id=self.cfg.instrument_id,
            order_side=OrderSide.SELL,
            quantity=self.instrument.make_qty(self.cfg.quantity),
            time_in_force=TimeInForce.DAY,
            trailing_offset=self.cfg.trail_fraction * 10_000,
            trailing_offset_type=TrailingOffsetType.BASIS_POINTS,
            trigger_type=TriggerType.LAST_PRICE,
            reduce_only=True,
        )
        self.trail_cid = order.client_order_id
        self.submit_order(order, position_id=self.position_id)

    def on_order_rejected(self, event) -> None:
        self.rejected = str(event.reason)

    def on_order_denied(self, event) -> None:
        self.rejected = str(event.reason)

    def on_order_filled(self, event) -> None:
        if event.order_side == OrderSide.BUY and self.entry_ts_ns is None:
            self.entry_ts_ns = event.ts_event
            self.entry_price = event.last_px.as_decimal()
        elif event.order_side == OrderSide.SELL and event.client_order_id == self.trail_cid:
            quantity = event.last_qty.as_decimal()
            self.exit_qty += quantity
            self.exit_notional += event.last_px.as_decimal() * quantity
            if self.exit_qty >= self.cfg.quantity:
                self.exit_ts_ns = event.ts_event
                self.exit_price = self.exit_notional / self.exit_qty
                self.exited = True


def _head_sha() -> str:
    root = Path(__file__).resolve().parents[3]
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _price(instrument: Any, value: Decimal) -> Price:
    return Price.from_str(f"{value:.{instrument.price_precision}f}")


def _ticks(spec: CaseSpec, trigger: Trigger) -> list[TradeTick]:
    instrument = equity(spec.symbol)
    items = [p for p in spec.prints if p.ts_ns >= trigger.ts_ns]
    if not items or items[0].ts_ns != trigger.ts_ns or items[0].price != trigger.price:
        items.insert(0, Print(trigger.ts_ns, trigger.price, max(int(spec.quantity), 1)))
    elif items[0].size < int(spec.quantity):
        # The owner's fill substitution: T carries the owner's quantity, so the
        # model fills the whole order on its print even when the SIP print was small.
        items[0] = Print(items[0].ts_ns, items[0].price, int(spec.quantity))
    return [
        TradeTick(
            instrument_id=instrument.id,
            price=_price(instrument, item.price),
            size=Quantity.from_int(item.size),
            aggressor_side=AggressorSide.NO_AGGRESSOR,
            trade_id=TradeId(f"{spec.symbol}-{index}"),
            ts_event=item.ts_ns,
            ts_init=item.ts_ns,
        )
        for index, item in enumerate(items)
    ]


def _replay(spec: CaseSpec, trigger: Trigger, out: Path) -> ArmResult:
    instrument = equity(spec.symbol)
    engine = BacktestEngine(
        BacktestEngineConfig(
            trader_id=TraderId("B-E2E-001"),
            risk_engine=RiskEngineConfig(bypass=True),
            bypass_logging=True,
        )
    )
    engine.add_venue(
        venue=Venue("ALPACA"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        base_currency=None,
        starting_balances=[Money.from_str("1000000 USD")],
        fill_model=DefaultFillModel(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=0),
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
        latency_model=StaticLatencyModel(0, 0, 0),
    )
    engine.add_instrument(instrument)
    engine.add_data(_ticks(spec, trigger))
    strategy = _Protect(
        _ProtectConfig(
            instrument_id=instrument.id,
            trigger_ns=trigger.ts_ns,
            trigger_price=trigger.price,
            quantity=spec.quantity,
            trail_fraction=spec.trail_fraction,
        )
    )
    engine.add_strategy(strategy)
    try:
        engine.run()
        fills = engine.generate_order_fills_report()
        fills.to_csv(out / f"{spec.case}-{trigger.arm}-fills.csv", index=False)
        engine.generate_orders_report().to_csv(
            out / f"{spec.case}-{trigger.arm}-orders.csv", index=False
        )
    finally:
        engine.dispose()

    entry = strategy.entry_price
    exit_price = strategy.exit_price
    protected = (
        None if entry in (None, Decimal(0)) or exit_price is None else float(exit_price / entry - 1)
    )
    hold_flat = None if entry in (None, Decimal(0)) else float(spec.last_price / entry - 1)
    note = ""
    if not _is_rth(trigger.ts_ns):
        note = (
            "outside regular hours: BManager releases an emulated BID_ASK trail with a "
            "limit_offset; chase_cap_fraction is UNAVAILABLE, so this replay uses the same "
            "2.5% level as a LAST_PRICE trailing stop (MODELED substitution)"
        )
    state = "COMPLETE" if strategy.entry_ts_ns is not None and exit_price is not None else "FAIL"
    reason = "" if state == "COMPLETE" else "the replay did not open and protect the position"
    return ArmResult(
        arm=trigger.arm,
        state=state,
        reason=reason
        + (f"; last order rejected: {strategy.rejected}" if strategy.rejected else ""),
        note=note,
        trigger=trigger,
        entry_price=entry,
        entry_ts_ns=strategy.entry_ts_ns,
        high=strategy.high,
        trail_level=strategy.level,
        exit_price=exit_price,
        exit_ts_ns=strategy.exit_ts_ns,
        protected=protected,
        hold_flat=hold_flat,
        path=tuple(strategy.path),
    )


def _params(spec: CaseSpec, arm: str, result: ArmResult) -> dict[str, object]:
    return {
        "case": spec.case,
        "symbol": spec.symbol,
        "session": spec.session,
        "arm": arm,
        "entry": _str(result.entry_price),
        "trigger": _str(result.trigger.price) if result.trigger else None,
        "exit": _str(result.exit_price),
        "high": _str(result.high),
        "trail_level": _str(result.trail_level),
        "trail_fraction": str(spec.trail_fraction),
        "quantity": str(spec.quantity),
        "rule_window_s": str(spec.rule.window_s),
        "rule_trades": str(spec.rule.trades),
        "rule_span_s": str(spec.rule.span_s),
        "rule_max_move": str(spec.rule.max_move),
        "data": [f"{name}:{digest}" for name, digest in spec.hashes],
    }


def _append(
    trial: TrialLog | None,
    spec: CaseSpec,
    arm: str,
    result: ArmResult,
    *,
    strategy: str = "b_e2e",
    entry: Decimal | None = None,
    hold_flat: float | None = None,
) -> None:
    if trial is None:
        return
    sandbox = {
        "case": spec.case,
        "session": spec.session,
        "source": spec.source,
        "data": [f"{name}:{digest}" for name, digest in spec.hashes],
    }
    params = _params(spec, arm, result)
    if hold_flat is not None:
        params["hold_flat"] = repr(hold_flat)
    config = {
        "tier": "MODELED",
        "block_set_id": spec.session,
        "arm_id": arm,
        "arm_run_id": f"{spec.case}-{arm}-{uuid.uuid4().hex}",
        "implementation_sha": _head_sha(),
        "factor_mask": [],
        "sandbox_config": sandbox,
        "sandbox_config_hash": snapshot_hash(sandbox),
        "evidence_weights": {},
        "evidence_weights_hash": snapshot_hash({}),
        "params_hash": snapshot_hash(params),
        "funding_divergent_session_count": None,
        "funding_unverified_session_count": None,
        "condition_returns": {},
    }
    ret = result.protected if result.protected is not None else hold_flat
    if result.state == "COMPLETE" and ret is None:
        raise ValueError(f"arm {arm!r} completed without a return")
    trial.append(
        strategy,
        params,
        config,
        seed=None,
        state=result.state,
        days=[spec.session] if result.state == "COMPLETE" else [],
        daily_net_returns=[ret] if ret is not None else [],
        objective=ret,
        error=result.reason if result.state == "FAIL" else "",
    )


def run_case(
    spec: CaseSpec,
    out: Path,
    *,
    arms: Sequence[str] = ARMS,
    log: Path | None = None,
) -> dict[str, ArmResult]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    trial = TrialLog(log) if log is not None else None
    picks = {"reference": reference_pick, "catalyst": catalyst_pick, "first_leg": first_leg_pick}
    results: dict[str, ArmResult] = {}
    reference_entry: Decimal | None = None
    for arm in arms:
        if arm not in picks:
            raise ValueError(f"unknown arm {arm!r}; choose from {sorted(picks)}")
        pick = picks[arm](spec)
        if pick.trigger is None:
            result = ArmResult(arm=arm, state="FAIL", reason=pick.reason)
            results[arm] = result
            _append(trial, spec, arm, result)
            continue
        result = _replay(spec, pick.trigger, out)
        results[arm] = result
        _append(trial, spec, arm, result)
        if arm == "reference" and result.entry_price is not None:
            reference_entry = result.entry_price
    if reference_entry is not None:
        control = ArmResult(
            arm="hold_flat",
            state="COMPLETE",
            entry_price=reference_entry,
            protected=None,
            hold_flat=float(spec.last_price / reference_entry - 1),
        )
        _append(
            trial,
            spec,
            "hold_flat",
            control,
            strategy="b_e2e_hold_flat",
            entry=reference_entry,
            hold_flat=control.hold_flat,
        )
    return results


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_files(root: Path, kind: str, symbol: str, day: str) -> list[Path]:
    if kind in ("trades", "quotes"):
        folder = root / "data" / kind / f"{symbol}.ALPACA"
    else:
        folder = root / "data" / kind / f"{symbol}.ALPACA-1-MINUTE-LAST-EXTERNAL"
    return sorted(path for path in folder.glob("*.parquet") if day in path.name)


def _read_prints(root: Path, symbol: str, session: str, start_ns: int, end_ns: int) -> list[Print]:
    files = _dataset_files(root, "trades", symbol, session)
    if not files:
        raise FileNotFoundError(f"no trade parquet files under {root} for {symbol} {session}")
    dataset = ds.dataset([str(path) for path in files], format="parquet")
    stamps = pa.timestamp("ns", tz="UTC")
    table = dataset.to_table(
        columns=["price", "size", "ts_event"],
        filter=(pc.field("ts_event") >= pa.scalar(start_ns, type=stamps))
        & (pc.field("ts_event") <= pa.scalar(end_ns, type=stamps)),
    )
    return [
        Print(_ns_from_datetime(stamp), Decimal(str(price)), int(size))
        for price, size, stamp in zip(
            table["price"].to_pylist(),
            table["size"].to_pylist(),
            table["ts_event"].to_pylist(),
            strict=True,
        )
    ]


def _bars(root: Path, symbol: str, session: str) -> list[tuple[datetime, Decimal]]:
    files = _dataset_files(root, "bars", symbol, session)
    if not files:
        raise FileNotFoundError(f"no bar parquet files under {root} for {symbol} {session}")
    table = ds.dataset([str(path) for path in files], format="parquet").to_table(
        columns=["ts_event", "close"]
    )
    return sorted(
        (
            (stamp, Decimal(str(close)))
            for stamp, close in zip(
                table["ts_event"].to_pylist(), table["close"].to_pylist(), strict=True
            )
        ),
        key=lambda item: item[0],
    )


def _et(day: str, clock: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}:00").replace(tzinfo=EASTERN)


def _last_close(root: Path, symbol: str, day: str) -> Decimal:
    cutoff = _et(day, "16:00")
    closes = [close for stamp, close in _bars(root, symbol, day) if stamp <= cutoff]
    if not closes:
        raise ValueError(f"no regular-hours close for {symbol} {day}")
    return closes[-1]


def _prior_close(root: Path, symbol: str, session: str) -> Decimal:
    day = date.fromisoformat(session)
    for back in range(1, 15):
        prior = (day - timedelta(days=back)).isoformat()
        if _dataset_files(root, "bars", symbol, prior):
            return _last_close(root, symbol, prior)
    raise ValueError(f"no prior session close for {symbol} before {session}")


def catalog_case(case: str, root: Path) -> CaseSpec:
    """PARA's owner fill and SPCX's post-8-K first print, read from the C1 catalog."""
    if case == "para":
        session, symbol = "2026-11-03", "PARA"
        owner = Print(_ns("2026-11-03T14:50:46.382818Z"), Decimal("7.63"), 50)
        return CaseSpec(
            case="para",
            symbol=symbol,
            session=session,
            prior_close=_prior_close(root, symbol, session),
            last_price=_last_close(root, symbol, session),
            prints=tuple(
                _read_prints(
                    root,
                    symbol,
                    session,
                    _ns("2026-11-03T13:45:00Z"),
                    _ns("2026-11-03T15:00:00Z"),
                )
            ),
            owner_fill=owner,
            reference_label=(
                "owner fill 50 @ 7.63 (created 14:50:44.522950Z, filled 14:50:46.382818Z); "
                "the SIP tape has no print between 14:45:17.713547Z and 14:52:56.291709Z, "
                "so T's print is the owner's fill"
            ),
            source="C1 ParquetDataCatalog, source alpaca_sip, feed sip, adjustment raw",
            hashes=tuple(
                ("trades/" + path.name, _sha256(path))
                for path in _dataset_files(root, "trades", symbol, session)
            ),
        )
    if case == "spcx":
        session, symbol = "2026-10-21", "SPCX"
        return CaseSpec(
            case="spcx",
            symbol=symbol,
            session=session,
            prior_close=_prior_close(root, symbol, session),
            last_price=_last_close(root, symbol, session),
            prints=tuple(
                _read_prints(
                    root,
                    symbol,
                    session,
                    _ns("2026-10-21T08:00:00Z"),
                    _ns("2026-10-21T14:14:10Z"),
                )
            ),
            catalyst_ns=_ns("2026-10-20T20:00:51Z"),
            catalyst_label=(
                "8-K accession 0001628280-26-066482 accepted 2026-10-20T20:00:51Z; "
                "first observable SIP print after it"
            ),
            reference_label=(
                "hypothetical entry, owner's fill T unknown: the first observable SIP print, "
                "161.21 at 2026-10-21T08:00:00.014636Z; modeled as the owner's 50-share fill "
                "at T (the SIP print carried 1 share)"
            ),
            source="C1 ParquetDataCatalog, source alpaca_sip, feed sip, adjustment raw",
            hashes=tuple(
                ("trades/" + path.name, _sha256(path))
                for path in _dataset_files(root, "trades", symbol, session)
            ),
        )
    raise ValueError(f"unknown catalog case {case!r}")


def omh_case(work: Path) -> CaseSpec:
    import numpy as np

    summary = json.loads((work / "omh_trades.json").read_text())
    arrays = np.load(work / "arrays/2026-11-09.npz")
    symbols = [str(item) for item in arrays["symbols"]]
    index = symbols.index("OMH")
    closes = [int(item) for item in arrays["price"][index]]
    present = [int(item) for item in arrays["present"][index]]
    start = _ns("2026-11-09T04:00:00-05:00")
    first = Print(_ns(summary["first_trade"]["t"]), Decimal(summary["first_trade"]["price"]), 210)
    prints = [first]
    for minute in range(len(closes)):
        if not present[minute] or closes[minute] < 0:
            continue
        prints.append(
            Print(start + (minute + 1) * 60 * NS, Decimal(closes[minute]) / Decimal(10_000), 100)
        )
    ranks = []
    rows = json.loads((work / "omh_generations.json").read_text())
    for row in rows:
        if row.get("rank") in (1, 2) and row.get("score") is not None:
            ranks.append(
                RankRow(
                    known_at_ns=_ns(row["time"]),
                    rank=int(row["rank"]),
                    quiet_price=Decimal(summary["prev_close"]),
                    first_print_ns=first.ts_ns,
                )
            )
    return CaseSpec(
        case="omh",
        symbol="OMH",
        session="2026-11-09",
        prior_close=Decimal(summary["prev_close"]),
        last_price=next(Decimal(item) / Decimal(10_000) for item in reversed(closes) if item > 0),
        prints=tuple(prints),
        reference_label=(
            "observed onset print, no owner fill recorded: 14.89 at "
            "2026-11-09T04:00:00.055894-05:00"
        ),
        rank=tuple(ranks),
        rule=reviewed_rule(),
        source=(
            "e2e-omh replay arrays: 1-minute SIP bars 04:00-11:35 ET, "
            "K2 generations, first-trade summary"
        ),
        hashes=tuple(
            (name, _sha256(work / name))
            for name in (
                "omh_trades.json",
                "omh_generations.json",
                "arrays/2026-11-09.npz",
                "ranks.npz",
            )
        ),
    )


def build_case(name: str, *, catalog: Path, omh_work: Path) -> CaseSpec:
    if name == "omh":
        return omh_case(omh_work)
    return catalog_case(name, catalog)


def report(spec: CaseSpec, results: dict[str, ArmResult]) -> dict[str, object]:
    return {
        "case": spec.case,
        "symbol": spec.symbol,
        "session": spec.session,
        "prior_close": str(spec.prior_close),
        "last_price": str(spec.last_price),
        "source": spec.source,
        "hashes": dict(spec.hashes),
        "rule": {
            "window_s": spec.rule.window_s,
            "trades": spec.rule.trades,
            "span_s": spec.rule.span_s,
            "max_move": str(spec.rule.max_move),
        },
        "arms": {arm: result.as_dict() for arm, result in results.items()},
    }


def _markdown(reports: Sequence[dict[str, object]]) -> str:
    lines = [
        "| case | arm | state | trigger | entry | high | trail | exit | protected | hold-flat |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in reports:
        arms = item["arms"]
        for arm, result in arms.items():  # type: ignore[union-attr]
            trigger = result["trigger"]
            when = "—" if not trigger else str(trigger["ts"])[11:19]

            def pct(value: object) -> str:
                return "—" if value is None else f"{float(str(value)) * 100:+.2f}%"

            lines.append(
                (
                    "| {case} | {arm} | {state} | {when} | {entry} | {high} | {trail}"
                    " | {exit} | {prot} | {hold} |"
                ).format(
                    case=item["case"],
                    arm=arm,
                    state=result["state"],
                    when=when,
                    entry=result["entry_price"] or "—",
                    high=result["high"] or "—",
                    trail=result["trail_level"] or "—",
                    exit=result["exit_price"] or "—",
                    prot=pct(result["protected"]),
                    hold=pct(result["hold_flat"]),
                )
            )
    return "\n".join(lines) + "\n"


def run_all(
    *,
    catalog: Path,
    omh_work: Path,
    out: Path,
    log: Path,
    cases: Sequence[str],
) -> list[dict[str, object]]:
    out.mkdir(parents=True, exist_ok=True)
    reports = []
    for name in cases:
        spec = build_case(name, catalog=catalog, omh_work=omh_work)
        results = run_case(spec, out, log=log)
        payload = report(spec, results)
        reports.append(payload)
        (out / f"{name}.json").write_text(json.dumps(payload, indent=2) + "\n")
        print(f"{name}: {json.dumps({arm: result.state for arm, result in results.items()})}")
    (out / "summary.md").write_text(_markdown(reports))
    return reports


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", nargs="?", default="run")
    parser.add_argument(
        "--catalog", type=Path, default=Path.home() / "sextant-data/c1-scenario/catalog"
    )
    parser.add_argument(
        "--omh-work", type=Path, default=Path.home() / "sextant-data/handoffs/e2e-omh/work"
    )
    parser.add_argument("--out", type=Path, default=Path("reports/research/b-e2e"))
    parser.add_argument("--log", type=Path, default=Path("reports/research/trials.parquet"))
    parser.add_argument("--cases", nargs="+", default=["para", "spcx", "omh"])
    args = parser.parse_args(argv)
    run_all(
        catalog=args.catalog,
        omh_work=args.omh_work,
        out=args.out,
        log=args.log,
        cases=args.cases,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
