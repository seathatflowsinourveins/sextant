"""#98: Sextant's exit engine (#45) against hold-to-15:55 on #41's exact inputs, with attribution.

Sources, each pinned:
- Inputs, cohort and both controls: the pinned b-exit-replay study and #41's hash-checked inputs,
  through sextant.research.exit_study_41 (#67): its catalog, `opening_entries`, `prepare`, `replay`.
- Tape: northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:
  src/northstar_trading/research_e2e/backtests/b_gain_protection.py:856-905 (`replay_minute_bars`),
  per the lead's ruling B2 on #98: at each completed minute, a quote at the bar low, then a trade at
  the bar high, then the bar. Its equal bid/ask becomes low x (1 -/+ h), h = the study's own cost
  per side, on the broker tick (bid floored, ask ceiled; ticks from :411-415).
  Labelled `minute-bar-approximate`.
- Entry: the same file :705-735: an equal bid/ask anchor at the recorded entry time, a market buy
  on a time alert, and a check that the fill equals the recorded price and quantity.
- Engine: sextant.exits (#45) at `ExitParams.starts()`; chase off (`chase_min_interval_s`
  unavailable, ruling B1); R_w per ruling B3.

Costs: the exit's fill at the proxy bid already embeds h, so it is not charged again (11-03 note
:126); the entry and a 15:55 flat pay the study's cost per side, exactly as its own `net_return`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from statistics import median
from typing import Any

from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggerConfig, RiskEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType,
    AggressorSide,
    Bar,
    BarType,
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
    TradeId,
    TradeTick,
    Venue,
)

from sextant.exits import policy
from sextant.exits.engine import ExitEngine, ExitEngineConfig
from sextant.exits.policy import ExitParams
from sextant.research import exit_study_41 as x41

BPS = Decimal(10_000)
COSTS = (Decimal(3), Decimal(6))  # bps per side, the study's own assumption and its stress
C5 = "C5-n22-k3-R-OFF"
# Ruling B3 on #98 pending: (a) R_w not estimable on minute bars, dropped; (b) R_w kept strict.
ARMS = ((False, "exit-engine-starts-rw-dropped"), (True, "exit-engine-starts-rw-strict"))
SEC = 1_000_000_000
MATCH_PRECISION = 9
MODEL = "minute-bar-approximate"


def broker_tick(price: Decimal) -> Decimal:
    return Decimal("0.0001") if price < 1 else Decimal("0.01")


def _on_tick(value: Decimal, tick: Decimal, rounding: str) -> Decimal:
    return (value / tick).to_integral_value(rounding=rounding) * tick


def _px(value: Decimal) -> Price:
    return Price.from_str(f"{value:.{MATCH_PRECISION}f}")


@dataclass(frozen=True)
class Minute:
    close_ns: int
    o: Decimal
    h: Decimal
    low: Decimal
    c: Decimal


def to_ns(at: Any) -> int:
    return int(at.timestamp()) * SEC + at.microsecond * 1_000


def held_minutes(minutes: list[Minute], entry_ns: int, flat_ns: int) -> list[Minute]:
    """Fully held minutes only (the straddling minute is omitted), completed before the flat."""
    return [m for m in minutes if m.close_ns - 60 * SEC >= entry_ns and m.close_ns + 2 <= flat_ns]


def proxy_bid(m: Minute, h_bps: Decimal, tick: Decimal) -> Decimal:
    return _on_tick(m.low * (1 - h_bps / BPS), tick, ROUND_FLOOR)


class WitnessEntry(ExitEngine):
    """Buys the recorded fill on a time alert, then the exit engine owns the position."""

    entry_ns = 0
    entry_qty = Decimal(0)

    def on_start(self) -> None:
        super().on_start()
        self.clock.set_time_alert_ns("recorded-entry", self.entry_ns, self._enter)

    def _enter(self, _event: object) -> None:
        order = self.order_factory.market(
            self.instrument_id, OrderSide.BUY, Quantity.from_str(str(self.entry_qty))
        )
        self.submit_order(order)


def _instrument(symbol: str) -> Equity:
    return Equity(
        InstrumentId.from_str(f"{symbol}.{x41.VENUE}"),
        Symbol(symbol),
        Currency.from_str("USD"),
        MATCH_PRECISION,
        Price.from_str("0.000000001"),
        0,
        0,
        lot_size=Quantity.from_int(1),
    )


def run_entry(
    entry: Any,
    minutes: list[Minute],
    flat_ns: int,
    h_bps: Decimal,
    params: ExitParams,
    *,
    range_estimable: bool,
) -> dict[str, Any]:
    """One BacktestEngine run for one recorded entry at one cost. Returns its fills and events."""
    entry_ns = to_ns(entry.at)
    tick = broker_tick(entry.price)
    instrument = _instrument(entry.symbol)
    iid = instrument.id
    bar_type = BarType.from_str(f"{iid}-1-MINUTE-LAST-EXTERNAL")
    size = Quantity.from_int(1_000_000)
    anchor_px = _px(entry.price)
    tape: list[Any] = [
        QuoteTick(iid, anchor_px, anchor_px, size, size, entry_ns - 1, entry_ns - 1),
        QuoteTick(iid, anchor_px, anchor_px, size, size, entry_ns, entry_ns),
    ]
    held = held_minutes(minutes, entry_ns, flat_ns)
    for m in held:
        bid = proxy_bid(m, h_bps, tick)
        ask = _on_tick(m.low * (1 + h_bps / BPS), tick, ROUND_CEILING)
        at = m.close_ns
        tape.append(QuoteTick(iid, _px(bid), _px(ask), size, size, at, at))
        tape.append(
            TradeTick(
                iid,
                _px(m.h),
                Quantity.from_int(1),
                AggressorSide.NO_AGGRESSOR,
                TradeId(f"BAR-HIGH-{at}"),
                at + 1,
                at + 1,
            )
        )
        tape.append(Bar(bar_type, _px(m.o), _px(m.h), _px(m.low), _px(m.c), size, at, at + 2))
    engine = BacktestEngine(
        BacktestEngineConfig(
            bypass_logging=True,
            logging=LoggerConfig(bypass_logging=True),
            run_analysis=False,
            risk_engine=RiskEngineConfig(bypass=True),
        )
    )
    try:
        engine.add_venue(
            venue=Venue(x41.VENUE),
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            base_currency=Currency.from_str("USD"),
            starting_balances=[Money(1_000_000_000, Currency.from_str("USD"))],
            fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
            bar_execution=False,
            trade_execution=False,
        )
        engine.add_instrument(instrument)
        strategy = WitnessEntry(
            ExitEngineConfig(
                instrument_id=iid,
                params=params,
                round_trip_cost=2 * h_bps / BPS * entry.price,
                session="rth",
                one_tick=tick,
                arm_bar_type=str(bar_type),
                range_estimable=range_estimable,
            )
        )
        strategy.entry_ns, strategy.entry_qty = entry_ns, entry.qty
        engine.add_strategy(strategy)
        engine.add_data(sorted(tape, key=lambda x: x.ts_init))
        engine.run(end=flat_ns)
        events = list(strategy.events)
    finally:
        engine.dispose()
    buys = [e for e in events if e["event"] == "protected_from_fill"]
    if len(buys) != 1 or Decimal(buys[0]["entry"]) != entry.price:
        raise ArithmeticError(f"native entry differs from the recorded fill: {entry.key} {buys}")
    return {"events": events, "held_minutes": len(held), "tick": tick}


def _net(q: Decimal, c: Decimal, *, exit_paid: bool) -> Decimal:
    """Net per unit notional: entry pays c; a proxy-bid exit already paid h = c."""
    return q - (1 + c) if exit_paid else q * (1 - c) - (1 + c)


def take_profit_touch(entry: Any, held: list[Minute], until_ns: int, p: ExitParams) -> bool:
    """Would the desired take-profit (X5, rolling with H) have been reached before the exit?"""
    tp = anchor = None
    high = entry.price
    for m in held:
        if m.close_ns > until_ns:
            break
        tp, anchor = policy.take_profit(tp, anchor, high, p)
        if m.h >= tp:
            return True
        high = max(high, m.h)
    return False


def _summary(values: list[Decimal]) -> dict[str, Any]:
    n = len(values)
    return {
        "n": n,
        "mean_bps": str(sum(values, Decimal(0)) / n * BPS) if n else None,
        "median_bps": str(median(values) * BPS) if n else None,
        "win_rate": str(Decimal(sum(v > 0 for v in values)) / n) if n else None,
        "pnl_units": str(sum(values, Decimal(0))),
    }


def implementation_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


METRICS = ("n", "mean_bps", "median_bps", "win_rate", "pnl_units")
CONTROLS = ("hold_flat", f"{C5}-tape", f"{C5}-study")


def prepare(inputs: Path, catalog_dir: Path, *, limit: int | None = None) -> dict[str, Any]:
    """Inputs, catalog, cohort and the controls' marks, once; any number of arms reuse them."""
    hashes = x41.verify_inputs(inputs)
    study: Any = x41.load_study()
    bars_path = inputs / x41.BARS
    catalog = x41.write_catalog(bars_path, catalog_dir)
    bars = x41.catalog_bars(catalog, bars_path, study)
    if bars != study.load_bars(bars_path):
        raise ValueError("catalog bars differ from the study's own loader")
    fills = study.read_jsonl(inputs / x41.FILLS)
    mu = study.owner_fill(inputs / x41.OWNER)
    if not any(r["order_id"] == mu["order_id"] and r["side"] == "buy" for r in fills):
        fills.append(mu)
    entries, _audit = study.opening_entries(fills, set(bars))
    data = study.prepare(bars)
    c5 = next(v for v in study.variants() if v.name == C5)
    hold = {e.key: study.replay(e, data[e.symbol], None) for e in entries}
    primary = [e for e in entries if e.day < "2026-10-29" and hold[e.key].price is not None]
    if limit is not None:
        primary = primary[:limit]
    minutes: dict[str, list[Minute]] = defaultdict(list)
    for symbol, bar_rows in bars.items():
        for b in bar_rows:
            minutes[symbol].append(Minute(to_ns(b.at) + 60 * SEC, b.o, b.h, b.l, b.c))
    return {
        "hashes": hashes,
        "study": study,
        "primary": primary,
        "cohort": len(primary),
        "hold": hold,
        "c5_marks": {e.key: study.replay(e, data[e.symbol], c5) for e in primary},
        "minutes": minutes,
    }


def _attribution(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row[key]["label"]].append(row[key])
    total = len(rows)
    return {
        label: {
            "n": len(g),
            "managed_mean_bps": str(
                sum((Decimal(r["managed"]) for r in g), Decimal(0)) / len(g) * BPS
            ),
            "hold_mean_bps": str(sum((Decimal(r["hold"]) for r in g), Decimal(0)) / len(g) * BPS),
            "gap_contribution_bps": str(
                sum((Decimal(r["managed"]) - Decimal(r["hold"]) for r in g), Decimal(0))
                / total
                * BPS
            ),
            "tp_touched": sum(r["tp_touched"] for r in g),
        }
        for label, g in sorted(groups.items())
    }


def evaluate(
    ctx: dict[str, Any], params: ExitParams, *, range_estimable: bool, arm: str
) -> dict[str, Any]:
    """One arm over the whole cohort at both costs, with its attribution and the controls."""
    study, hold, c5_marks, minutes = ctx["study"], ctx["hold"], ctx["c5_marks"], ctx["minutes"]
    values: dict[str, list[Decimal]] = defaultdict(list)
    per_entry: list[dict[str, Any]] = []
    for e in ctx["primary"]:
        flat_ns = to_ns(study.boundary(e.day, 15, 55))
        by_close = {m.close_ns: m for m in minutes[e.symbol]}
        held = held_minutes(minutes[e.symbol], to_ns(e.at), flat_ns)
        row: dict[str, Any] = {"key": e.key, "symbol": e.symbol, "day": e.day, "arm": arm}
        for c_bps in COSTS:
            c = c_bps / BPS
            result = run_entry(
                e, minutes[e.symbol], flat_ns, c_bps, params, range_estimable=range_estimable
            )
            sells = [x for x in result["events"] if x["event"] == "sell_fill"]
            kinds = [x["event"] for x in result["events"] if x["event"].startswith("breach")]
            sold = sum((Decimal(x["qty"]) for x in sells), Decimal(0))
            if sold == e.qty:
                price = sum(Decimal(x["price"]) * Decimal(x["qty"]) for x in sells) / sold
                label = kinds[0].removeprefix("breach_sell_")
                exit_ns = max(int(x["ts"]) for x in sells)
                managed = _net(price / e.price, c, exit_paid=True)
            elif sold == 0:
                price, label, exit_ns = hold[e.key].price, "flat_1555", flat_ns
                managed = _net(price / e.price, c, exit_paid=False)
            else:
                raise ArithmeticError(f"partial managed exit: {e.key}")
            held_ = study.net_return(e, hold[e.key].price, c_bps)
            if label == "flat_1555" and managed != held_:
                raise ArithmeticError(f"a 15:55 flat must equal hold: {e.key}")
            mark = c5_marks[e.key]
            if mark.reason == "flat":
                c5_tape = study.net_return(e, mark.price, c_bps)
            else:  # the signal bar's proxy bid at the study's exit time
                signal = by_close[to_ns(mark.at)]
                c5_tape = _net(
                    proxy_bid(signal, c_bps, broker_tick(e.price)) / e.price, c, exit_paid=True
                )
            c5_study = study.net_return(e, mark.price, c_bps)
            row[str(c_bps)] = {
                "label": label,
                "exit": str(price),
                "managed": str(managed),
                "hold": str(held_),
                "c5_tape": str(c5_tape),
                "c5_study": str(c5_study),
                "tp_touched": take_profit_touch(e, held, exit_ns, params),
            }
            values[f"arm/{c_bps}"].append(managed)
            values[f"hold_flat/{c_bps}"].append(held_)
            values[f"{C5}-tape/{c_bps}"].append(c5_tape)
            values[f"{C5}-study/{c_bps}"].append(c5_study)
        per_entry.append(row)
    costs = [str(c) for c in COSTS]
    return {
        "per_entry": per_entry,
        "arm": {
            **{c: _summary(values[f"arm/{c}"]) for c in costs},
            "attribution": {c: _attribution(per_entry, c) for c in costs},
        },
        "controls": {
            name: {c: _summary(values[f"{name}/{c}"]) for c in costs} for name in CONTROLS
        },
    }


def run(inputs: Path, out: Path, *, limit: int | None = None) -> dict[str, Any]:
    ctx = prepare(inputs, out / "catalog", limit=limit)
    params = ExitParams.starts()
    arms: dict[str, dict[str, Any]] = {}
    attribution: dict[str, Any] = {}
    per_entry: list[dict[str, Any]] = []
    for range_estimable, arm in ARMS:
        result = evaluate(ctx, params, range_estimable=range_estimable, arm=arm)
        per_entry += result["per_entry"]
        for c in (str(c) for c in COSTS):
            arms[f"{arm}/{c}"] = result["arm"][c]
            attribution[f"{arm}/{c}"] = result["arm"]["attribution"][c]
            if arm == ARMS[0][1]:  # the controls do not depend on the arm
                for name in CONTROLS:
                    arms[f"{name}/{c}"] = result["controls"][name][c]
    report = {
        "issue": 98,
        "execution_model": MODEL,
        "tier": "MODELED",
        "implementation": implementation_sha(),
        "params": {k: (str(v) if v is not None else None) for k, v in asdict(params).items()},
        "params_hash": hashlib.sha256(
            json.dumps({k: str(v) for k, v in asdict(params).items()}, sort_keys=True).encode()
        ).hexdigest(),
        "inputs": ctx["hashes"],
        "study": f"{x41.STUDY} sha256:{x41.STUDY_SHA256}",
        "cohort": ctx["cohort"],
        "arms": arms,
        "attribution": attribution,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / "entries.jsonl").write_text("".join(json.dumps(r) + "\n" for r in per_entry))
    trials = trial_rows(report)
    (out / "trials.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in trials))
    return report


LABELS = {
    "exit-engine-starts-rw-dropped": (
        "sextant.exits at ExitParams.starts(); chase not estimable on minute bars (off, sells "
        "at the bid proxy); R_w: not estimable on minute bars (dropped)"
    ),
    "exit-engine-starts-rw-strict": (
        "sextant.exits at ExitParams.starts(); chase not estimable on minute bars (off); "
        "R_w strict, so no trigger is ever set on this tape (never protected)"
    ),
    "hold_flat": "control: hold to the 15:55 ET open, the study's own exit and costs",
    f"{C5}-tape": "control: the study's selected variant, filled at the signal bar's proxy bid",
    f"{C5}-study": "control: the study's selected variant on its own fill model (next 1m open)",
}


def trial_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """One MODELED row per arm in #67's shape; nothing is selected."""
    rows = []
    for arm, label in LABELS.items():
        base, stress = report["arms"][f"{arm}/3"], report["arms"][f"{arm}/6"]
        rows.append(
            {
                "arm": arm,
                "kind": "control"
                if arm in ("hold_flat", f"{C5}-tape", f"{C5}-study")
                else "engine",
                "label": label,
                "tier": report["tier"],
                "execution_model": report["execution_model"],
                "study": report["study"],
                "implementation": report["implementation"],
                "params_hash": report["params_hash"],
                "inputs": report["inputs"],
                "cohort": "primary complete-horizon entries, 2026-10-26..28",
                "n": base["n"],
                "mean_bps_3": base["mean_bps"],
                "mean_bps_6": stress["mean_bps"],
                "median_bps_3": base["median_bps"],
                "median_bps_6": stress["median_bps"],
                "win_rate_3": base["win_rate"],
                "win_rate_6": stress["win_rate"],
                "pnl_units_3": base["pnl_units"],
                "pnl_units_6": stress["pnl_units"],
                "selected": False,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=x41.DEFAULT_INPUTS)
    parser.add_argument("--out", type=Path, default=Path("reports/exit-econ-98"))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    report = run(args.inputs, args.out, limit=args.limit)
    print(json.dumps({"arms": report["arms"], "attribution": report["attribution"]}, indent=1))


if __name__ == "__main__":
    main()
