"""Exit-engine witness: one Nautilus sim run on the engine's own test quotes, against holding.

Data: nautilus_trader.testkit TestDataProvider.audusd_quotes (v2.0.0rc7 55c0e820), a generated,
deterministic sine-wave of AUD/USD quotes with no trades. With no eligible trades, H stays at entry
and the gain lock cannot arm (ADR-0005 X3), so this run exercises the initial trigger, the persisted
bid breach and the managed LIMIT. The pure witnesses in tests/proofs/test_exit_engine.py cover the
rest. This is a mechanism witness, not merit: the data are synthetic.

The control is ADR-0025's: the same entry held to the end of the data, marked at the last bid
(modeled).
Both arms are appended to the run's ledger (ADR-0018). The entry here is a witness entry only; the
entry engine is design row 6 (ADR-0004).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, RiskEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType,
    Currency,
    Money,
    OmsType,
    OrderSide,
    Quantity,
    QuoteTick,
    TraderId,
    Venue,
)
from nautilus_trader.testkit.providers import TestDataProvider, TestInstrumentProvider

from sextant.exits.engine import ExitEngine, ExitEngineConfig
from sextant.exits.policy import ExitParams

AUDUSD = TestInstrumentProvider.default_fx_ccy("AUD/USD")
QTY = Decimal(100_000)
DATA = "nautilus_trader@v2.0.0rc7 55c0e820: testkit TestDataProvider.audusd_quotes(3000)"

# Fixture values for the witness, not starting values and not calibrated (AGENTS.md Rule 2).
FIXTURE = ExitParams(
    prearm_buffer_fraction=Decimal("0.002"),
    prearm_range_multiple=Decimal(0),
    prearm_range_window_s=Decimal(60),
    gain_lock_giveback_fraction=Decimal("0.25"),
    breach_persist_count=3,
    breach_persist_span_s=Decimal(2),
    chase_cap_fraction=Decimal("0.001"),
    chase_min_interval_s=Decimal(1),
    take_profit_above_h_fraction=Decimal("0.10"),
    take_profit_step_fraction=Decimal("0.02"),
    backstop_min_separation_fraction=Decimal("0.02"),
    quote_max_age_s=Decimal(5),
)


class WitnessEntry(ExitEngine):
    """Buys once at the first quote, then the exit engine owns the position."""

    entered = False

    def on_quote(self, quote: QuoteTick) -> None:
        if not self.entered:
            self.entered = True
            order = self.order_factory.market(
                self.instrument_id, OrderSide.BUY, Quantity.from_str(str(QTY))
            )
            self.submit_order(order)
        super().on_quote(quote)


@dataclass(frozen=True)
class Arm:
    arm: str
    tier: str
    data: str
    params_hash: str
    entry: str
    exit: str
    exit_label: str
    gross_pnl_usd: str


def params_hash(params: ExitParams) -> str:
    text = json.dumps({k: str(v) for k, v in asdict(params).items()}, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def run(out: Path, params: ExitParams = FIXTURE) -> tuple[Arm, Arm, list[dict[str, str]]]:
    quotes = TestDataProvider.audusd_quotes()
    engine = BacktestEngine(
        BacktestEngineConfig(
            trader_id=TraderId.from_str("BACKTESTER-001"),
            risk_engine=RiskEngineConfig(bypass=True),
        )
    )
    engine.add_venue(
        venue=Venue("SIM"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=Currency.from_str("USD"),
        starting_balances=[Money(1_000_000, Currency.from_str("USD"))],
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
    )
    engine.add_instrument(AUDUSD)
    engine.add_data(quotes)
    strategy = WitnessEntry(
        ExitEngineConfig(
            instrument_id=AUDUSD.id,
            params=params,
            round_trip_cost=AUDUSD.price_increment.as_decimal(),
            session="rth",
        )
    )
    engine.add_strategy(strategy)
    engine.run()
    events = list(strategy.events)
    engine.dispose()

    entry = Decimal(next(e["entry"] for e in events if e["event"] == "protected_from_fill"))
    sells = [e for e in events if e["event"] == "sell_fill"]
    sold = sum((Decimal(e["qty"]) for e in sells), start=Decimal(0))
    value = sum((Decimal(e["price"]) * Decimal(e["qty"]) for e in sells), start=Decimal(0))
    last_bid = quotes[-1].bid_price.as_decimal()
    exit_px = value / sold if sold else last_bid
    label = "managed_sell" if sold == QTY else "open_at_end"
    digest = params_hash(params)
    managed = Arm(
        "exit-engine-x2-x5",
        "SIMULATED",
        DATA,
        digest,
        str(entry),
        str(exit_px),
        label,
        str((exit_px - entry) * QTY),
    )
    control = Arm(
        "hold-to-end",
        "MODELED",
        DATA,
        digest,
        str(entry),
        str(last_bid),
        "last_bid",
        str((last_bid - entry) * QTY),
    )
    out.mkdir(parents=True, exist_ok=True)
    with (out / "ledger.jsonl").open("a") as ledger:
        for arm in (managed, control):
            ledger.write(json.dumps(asdict(arm)) + "\n")
    (out / "exit-events.json").write_text(json.dumps(events, indent=1))
    return managed, control, events


if __name__ == "__main__":
    for row in run(Path("reports/exit-witness"))[:2]:
        print(row)
