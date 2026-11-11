"""Bar-only factor screening on the verified #41 catalog: MODELED, screening only.
Protocol: docs/research/2026-11-06-replay-82.md, frozen before selection. Catalog bars carry
volume 1 vs Equity 0; the rc8 matcher drops them (#5461), so the screen re-stamps the quantum.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.execution import DefaultFillModel, MakerTakerFeeModel, StaticLatencyModel
from nautilus_trader.model import (
    AccountType,
    Bar,
    Currency,
    Equity,
    InstrumentId,
    Money,
    OmsType,
    OrderSide,
    Quantity,
    Venue,
)
from nautilus_trader.trading import Strategy

from sextant.validation.trials import TrialLog, snapshot_hash

ET = ZoneInfo("America/New_York")
USD = Currency.from_str("USD")
STAMP = "SCREENING ONLY — NOT AN ADOPTED WINNER"
CLV_SOURCE = "ADR-0014 H4 completed-bar CLV; docs/adr/0014-features-and-regime-models.md"
K2_SOURCE = "ADR-0024 K2 move x dvol_ratio; docs/adr/0024-extreme-mover-ranking-and-early-entry.md"
Plan = dict[int, tuple[tuple[InstrumentId, OrderSide], ...]]
Rows = dict[InstrumentId, list[Bar]]
# fmt: off
STUDY = {"name": "bar-only-factor-screen-1", "seed": 20261110,
         "horizon_bars": 30, "top_k": 3, "clv_threshold": "0.5", "quantity": 1,
         "start_balance": "1000000", "cost_bps": {"1x": 3, "2x": 6}}
_ARMS = (
    ("cash", "RUNNABLE", "control", "ADR-0019 paired control", ""),
    ("buy_and_hold", "RUNNABLE", "benchmark", "lanes/sim/README.md benchmark", ""),
    ("k2_bar_proxy", "RUNNABLE", "factor", K2_SOURCE + " (bar proxy)", ""),
    ("h4_clv", "RUNNABLE", "factor", CLV_SOURCE, ""),
    ("k2_exact", "NOT_READY", "factor", K2_SOURCE, "TradeTick tape: no trades in the catalog"),
    ("h1_ofi", "NOT_READY", "factor", "ADR-0014 H1", "L1 NBBO quotes and SIP trades: absent"),
    ("h2_arrival_intensity", "NOT_READY", "factor", "ADR-0014 H2", "trade timestamps: absent"),
    ("h3_microprice", "NOT_READY", "factor", "ADR-0014 H3", "quote book: absent"),
    ("h5_ffd", "NOT_READY", "factor", "ADR-0014 H5", "RiskLabAI dependency: outside the brief"),
    ("n1_first_leg", "NOT_READY", "factor", "ADR-0024 N1", "trade/event tape, early-second clock"),
    ("h4_range", "STOPPED_NO_FROZEN_SIGN", "factor", "ADR-0014 H4 range", "no frozen sign"),
    ("h4_volume", "STOPPED_NO_FROZEN_SIGN", "factor", "ADR-0014 H4 volume", "no frozen sign"),
)
ARMS = {a: {"state": s, "kind": k, "source": u, "missing": m} for a, s, k, u, m in _ARMS}
_EMPTY = {"n_trades": 0, "mean_net_bps": 0.0, "total_net_usd": 0.0, "win_rate": 0.0, "max_drawdown_usd": 0.0, "session_returns": {}}  # noqa: E501
# fmt: on


def session_of(ts_event: int) -> str:
    return datetime.fromtimestamp(ts_event / 1_000_000_000, ET).date().isoformat()


def rebar(bar: Bar) -> Bar:
    volume = bar.volume.as_decimal()
    if volume != volume.to_integral_value():
        raise ValueError(f"bar volume {volume} is not integral; #5461 needs an integer quantum")
    return Bar(
        bar.bar_type,
        bar.open,
        bar.high,
        bar.low,
        bar.close,
        Quantity.from_int(int(volume)),
        bar.ts_event,
        bar.ts_init,
    )


def clv(bar: Bar) -> Decimal | None:
    high, low, close = bar.high.as_decimal(), bar.low.as_decimal(), bar.close.as_decimal()
    return None if high - low <= 0 else (2 * close - high - low) / (high - low)


def clv_entries(bars: Any) -> list[tuple[int, Decimal]]:
    threshold = Decimal(STUDY["clv_threshold"])
    entries = [(bar.ts_event, value) for bar in bars if (value := clv(bar)) is not None]
    return sorted((ts, value) for ts, value in entries if value >= threshold)


def _sessions(bars: Any) -> dict[str, list[Bar]]:
    sessions: dict[str, list[Bar]] = defaultdict(list)
    for bar in sorted(bars, key=lambda item: item.ts_event):
        sessions[session_of(bar.ts_event)].append(bar)
    return dict(sessions)


def k2_entries(rows: dict[InstrumentId, list[Bar]]) -> list[tuple[int, InstrumentId, Decimal]]:
    entries: list[tuple[int, InstrumentId, Decimal]] = []
    for iid, bars in rows.items():
        prior_close: Decimal | None = None
        baselines: dict[int, list[Decimal]] = defaultdict(list)
        for series in _sessions(bars).values():
            cumulative: list[Decimal] = []
            running = Decimal(0)
            for bar in series:
                running += bar.close.as_decimal() * bar.volume.as_decimal()
                cumulative.append(running)
            if prior_close is not None:
                for index, dv in enumerate(cumulative):
                    prior = baselines.get(index)
                    if prior:
                        base = Decimal(sum(prior)) / Decimal(len(prior))
                        close = series[index].close.as_decimal()
                        entries.append(
                            (series[index].ts_event, iid, (close / prior_close - 1) * (dv / base))
                        )
            for index, dv in enumerate(cumulative):
                baselines[index].append(dv)
            prior_close = series[-1].close.as_decimal()
    return sorted(entries, key=lambda entry: (entry[0], str(entry[1])))


def build_plan(entries: Any, rows: Rows, *, horizon: int = 30, top_k: int | None = None) -> Plan:
    exits: dict[tuple[InstrumentId, int], int] = {}
    for iid, bars in rows.items():
        for series in _sessions(bars).values():
            for index, bar in enumerate(series):
                target = min(index + horizon, len(series) - 1)
                if target > index:
                    exits[(iid, bar.ts_event)] = series[target].ts_event
    plan: dict[int, list[tuple[InstrumentId, OrderSide]]] = defaultdict(list)
    held: dict[InstrumentId, int] = {}
    by_ts: dict[int, list[tuple[int, InstrumentId, Decimal]]] = defaultdict(list)
    for entry in entries:
        by_ts[entry[0]].append(entry)
    for ts_event in sorted(by_ts):
        held = {iid: until for iid, until in held.items() if until >= ts_event}
        taken = 0
        for _, iid, _ in sorted(by_ts[ts_event], key=lambda entry: (-entry[2], str(entry[1]))):
            if (top_k is not None and taken >= top_k) or iid in held:
                continue
            if (iid, ts_event) not in exits:
                continue
            plan[ts_event].append((iid, OrderSide.BUY))
            plan[exits[(iid, ts_event)]].append((iid, OrderSide.SELL))
            held[iid] = exits[(iid, ts_event)]
            taken += 1
    return {ts_event: tuple(actions) for ts_event, actions in plan.items()}


def buy_and_hold_plan(rows: dict[InstrumentId, list[Bar]]) -> Plan:
    plan: dict[int, list[tuple[InstrumentId, OrderSide]]] = defaultdict(list)
    for iid, bars in rows.items():
        for series in _sessions(bars).values():
            if len(series) > 1:
                plan[series[0].ts_event].append((iid, OrderSide.BUY))
                plan[series[-1].ts_event].append((iid, OrderSide.SELL))
    return {ts_event: tuple(actions) for ts_event, actions in plan.items()}


class _PlanStrategy(Strategy):
    def __new__(cls, *args: Any, **kwargs: Any) -> _PlanStrategy:
        return super().__new__(cls)

    def __init__(self, plan: Plan, bar_types: Any) -> None:
        super().__init__()
        self.plan, self.bar_types, self.fills = plan, tuple(bar_types), []
        self.realized: dict[str, Decimal] = defaultdict(Decimal)
        self._last = Decimal(0)

    def on_start(self) -> None:
        for bar_type in self.bar_types:
            self.subscribe_bars(bar_type)

    def on_bar(self, bar: Bar) -> None:
        quantity = Quantity.from_int(int(STUDY["quantity"]))
        iid = bar.bar_type.instrument_id
        flat = self.portfolio.is_net_flat
        for instrument_id, side in self.plan.get(bar.ts_event, ()):
            if instrument_id == iid and (side is OrderSide.BUY) == flat(iid):
                self.submit_order(self.order_factory.market(instrument_id, side, quantity))

    def on_position_closed(self, event: Any) -> None:
        money = self.portfolio.realized_pnls(Venue("ALPACA"), target_currency=USD).get(USD)
        total = money.as_decimal() if money else Decimal(0)
        self.realized[session_of(event.ts_event)] += total - self._last
        self._last = total

    def on_order_filled(self, event: Any) -> None:
        self.fills.append(
            {
                "instrument_id": str(event.instrument_id),
                "side": "BUY" if event.order_side is OrderSide.BUY else "SELL",
                "ts_event": int(event.ts_event),
                "px": event.last_px.as_decimal(),
                "qty": event.last_qty.as_decimal(),
                "fee": event.commission.as_decimal()
                if event.commission is not None
                else Decimal(0),
            }
        )


def run_plan(
    bars: Any, instruments: dict[InstrumentId, Equity], plan: Plan, *, cost_bps: int, seed: int
) -> dict[str, Any]:
    prepared = sorted((rebar(bar) for bar in bars), key=lambda bar: bar.ts_event)
    strategy = _PlanStrategy(plan, {bar.bar_type for bar in prepared})
    engine = BacktestEngine(config=BacktestEngineConfig(bypass_logging=True))
    try:
        engine.add_venue(
            venue=Venue("ALPACA"),
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            starting_balances=[Money(int(STUDY["start_balance"]), Currency.from_str("USD"))],
            fee_model=MakerTakerFeeModel(Decimal(0), Decimal(cost_bps) / Decimal(10000)),
            fill_model=DefaultFillModel(
                prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=seed
            ),
            latency_model=StaticLatencyModel(),
            bar_execution=True,
        )
        for instrument in instruments.values():
            engine.add_instrument(instrument)
        engine.add_data(prepared)
        engine.add_strategy(strategy)
        engine.run()
    finally:
        engine.dispose()
    return {"fills": strategy.fills, "metrics": metrics(strategy.fills, strategy.realized)}


def round_trips(fills: Any) -> list[dict[str, Any]]:
    buys: dict[str, list[dict[str, Any]]] = defaultdict(list)
    trips: list[dict[str, Any]] = []
    for fill in sorted(fills, key=lambda item: item["ts_event"]):
        if fill["side"] == "BUY":
            buys[fill["instrument_id"]].append(fill)
        elif buys[fill["instrument_id"]]:
            buy = buys[fill["instrument_id"]].pop(0)
            net = (fill["px"] - buy["px"]) * fill["qty"] - buy["fee"] - fill["fee"]
            trips.append(
                {
                    "instrument_id": fill["instrument_id"],
                    "buy_ts": buy["ts_event"],
                    "sell_ts": fill["ts_event"],
                    "buy_px": buy["px"],
                    "sell_px": fill["px"],
                    "qty": fill["qty"],
                    "buy_fee": buy["fee"],
                    "sell_fee": fill["fee"],
                    "net_usd": net,
                    "session": session_of(fill["ts_event"]),
                }
            )
    return trips


def metrics(fills: Any, session_pnl: dict[str, Decimal] | None = None) -> dict[str, Any]:
    trips = round_trips(fills)
    if not trips:
        return dict(_EMPTY)
    returns = [float((t["net_usd"] / (t["buy_px"] * t["qty"])) * 10_000) for t in trips]
    equity = peak = drawdown = Decimal(0)
    session_returns: dict[str, Decimal] = defaultdict(Decimal)
    for trip in sorted(trips, key=lambda item: item["sell_ts"]):
        equity += trip["net_usd"]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        session_returns[trip["session"]] += trip["net_usd"]
    pnl = session_pnl or session_returns
    return {
        "n_trades": len(trips),
        "mean_net_bps": sum(returns) / len(returns),
        "total_net_usd": float(sum(pnl.values(), Decimal(0))),
        "win_rate": sum(1 for value in returns if value > 0) / len(returns),
        "max_drawdown_usd": float(drawdown),
        "session_returns": {
            day: float(value / Decimal(STUDY["start_balance"])) for day, value in pnl.items()
        },
    }


def render_table(results: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    factors = sorted(
        (r for r in results if r["state"] == "COMPLETE" and r["kind"] == "factor"),
        key=lambda r: (-r["costs"]["1x"]["mean_net_bps"], r["arm"]),
    )
    controls = [result for result in results if result["kind"] == "control"]
    stopped = [result for result in results if result["state"] != "COMPLETE"]
    lines = [
        "# First ranked factor table — bar-only screening",
        "",
        f"**{STAMP}**",
        "",
        f"Study `{meta.get('study')}` on the verified #41 catalog, tier MODELED, "
        f"generated {meta.get('generated')}. Receipt SHA-256 "
        f"`{meta.get('catalog_receipt_sha256')}`; implementation "
        f"`{meta.get('implementation_sha')}`.",
        "",
        "Costs: assumed 3 bps (1x) and 6 bps (2x) per side, uncalibrated study conventions, "
        "not measured costs. Rank is by mean net return at 1x; INSUFFICIENT_N rows are unranked; "
        "cash is the only zero control; the buy-and-hold benchmark is shown apart.",
        "",
        "## Ranked factor arms",
        "| Rank | Arm | n | mean net bps 1x | mean net bps 2x | net USD 1x | "
        "net USD 2x | win rate | sample |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    rank = 0
    for result in factors:
        eligible = result["sample_state"] != "INSUFFICIENT_N"
        rank += eligible
        one, two = result["costs"]["1x"], result["costs"]["2x"]
        lines.append(
            f"| {rank if eligible else '—'} | {result['arm']} | {one['n_trades']} | "
            f"{one['mean_net_bps']:.2f} | "
            f"{two['mean_net_bps']:.2f} | {one['total_net_usd']:.2f} | "
            f"{two['total_net_usd']:.2f} | {one['win_rate']:.2f} | {result['sample_state']} |"
        )
    lines += [
        "",
        "## Controls",
        "| Arm | n | mean net bps 1x | mean net bps 2x | sample |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {r['arm']} | {r['costs']['1x']['n_trades']} | "
        f"{r['costs']['1x']['mean_net_bps']:.2f} | "
        f"{r['costs']['2x']['mean_net_bps']:.2f} | {r['sample_state']} |"
        for r in controls
    ]
    lines += ["", "## Buy-and-hold benchmark (not a control)", ""]
    lines += [
        f"`{r['arm']}`: {r['costs']['1x']['n_trades']} trips, mean net "
        f"{r['costs']['1x']['mean_net_bps']:.2f} bps at 1x, "
        f"{r['costs']['2x']['mean_net_bps']:.2f} bps at 2x."
        for r in results
        if r["kind"] == "benchmark"
    ]
    lines += [
        "",
        "## Not ready or stopped, kept in the ledger",
        "| Arm | State | Reason |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {r['arm']} | {r['state']} | {r['error']} |" for r in stopped]
    lines += [
        "",
        f"**{STAMP}**",
        "",
        "INSUFFICIENT_N: fewer than 30 round trips or fewer than five sessions; the "
        "four catalog sessions cannot clear that bar. This table orders a screening "
        "run only; it adopts no factor and states no after-cost edge.",
    ]
    return "\n".join(lines) + "\n"


def append_trials(log: TrialLog, results: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    params = {key: STUDY[key] for key in ("horizon_bars", "top_k", "clv_threshold", "quantity")}
    sandbox = {"study": STUDY["name"], "seed": STUDY["seed"], "cost_bps": STUDY["cost_bps"]}
    weights = {arm: 1 for arm, spec in ARMS.items() if spec["kind"] == "factor"}
    with log.writer():
        for result in results:
            complete = result["state"] == "COMPLETE"
            config = {
                "arm_id": result["arm"],
                "arm_run_id": f"{meta['run_id']}-{result['arm']}",
                "implementation_sha": meta["implementation_sha"],
                "factor_mask": [result["arm"]] if result["kind"] == "factor" else [],
                "sandbox_config": sandbox,
                "sandbox_config_hash": snapshot_hash(sandbox),
                "evidence_weights": weights,
                "evidence_weights_hash": snapshot_hash(weights),
                "params_hash": snapshot_hash(params),
                "tier": "MODELED",
                "block_set_id": "|".join(result["days"] or meta.get("days", [])),
                "funding_divergent_session_count": 0,
                "funding_unverified_session_count": 0,
                "condition_returns": result["condition_returns"],
                "sample_state": result["sample_state"],
            }
            log.append(
                result["arm"],
                params,
                config,
                int(STUDY["seed"]),
                state="COMPLETE" if complete else "FAIL",
                error="" if complete else result["error"],
                days=result["days"],
                daily_net_returns=result["daily_net_returns"],
                objective=float(result["costs"]["1x"]["mean_net_bps"]) if complete else None,
            )
