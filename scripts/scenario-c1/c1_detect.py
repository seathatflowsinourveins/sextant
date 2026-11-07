"""C1 detection witness: native 5-minute composite opening windows, then `stocks_in_play.screen`.

The detector is used exactly as admitted on #130 (no parameter edits). ATR is not supplied:
#129 has not bound the native ATR warm-up, so `screen` reports `daily_facts_unavailable` with
the RVOL it could still compute. That is recorded, not patched.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time as daytime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
from nautilus_trader.data import DataEngineConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import AccountType, Bar, Currency, Money, OmsType, Venue
from nautilus_trader.persistence import ParquetDataCatalog
from nautilus_trader.trading import Strategy, StrategyConfig

from sextant.data.alpaca_history import NY, nanos
from sextant.research.detectors import stocks_in_play as sip

ROOT = Path.home() / "sextant-data" / "c1-scenario"
CATALOG = ROOT / "catalog"
RUN = ROOT / "run"

CASES: dict[str, dict[str, Any]] = {
    "a": {"symbol": "PARA", "entry": date(2026, 11, 3), "lookback": 14},
    "b": {"symbol": "PARA", "entry": date(2026, 10, 27), "lookback": 14},
    "c": {"symbol": "SPCX", "entry": date(2026, 10, 21), "lookback": 14},
}


def open_ns(day: date) -> int:
    return nanos(datetime.combine(day, daytime(9, 30), tzinfo=NY))


def composite_window(instrument, bars: list[Bar], composite) -> tuple[Bar, ...]:
    class Collector(Strategy):
        def __init__(self) -> None:
            super().__init__(StrategyConfig())
            self.bars: list[Bar] = []

        def on_start(self) -> None:
            self.subscribe_bars(composite)

        def on_bar(self, bar) -> None:
            self.bars.append(bar)

    engine = BacktestEngine(
        BacktestEngineConfig(
            bypass_logging=True,
            run_analysis=False,
            data_engine=DataEngineConfig(
                time_bars_interval_type="left-open",
                time_bars_timestamp_on_close=True,
                time_bars_build_with_no_updates=False,
            ),
        )
    )
    try:
        engine.add_venue(
            venue=Venue("ALPACA"),
            oms_type=OmsType.HEDGING,
            account_type=AccountType.MARGIN,
            base_currency=Currency.from_str("USD"),
            starting_balances=[Money.from_str("10000 USD")],
            fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
        )
        engine.add_instrument(instrument)
        engine.add_data(bars)
        collector = Collector()
        engine.add_strategy(collector)
        engine.run()
        return tuple(collector.bars)
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=sorted(CASES))
    args = parser.parse_args()
    case = CASES[args.case]
    symbol, entry = case["symbol"], case["entry"]
    active = sip.StocksInPlaySpec(sip.PARAMETERS)
    catalog = ParquetDataCatalog(str(CATALOG.resolve()))
    iid = f"{symbol}.ALPACA"
    instrument = catalog.instruments(instrument_ids=[iid])[0]
    composite = active.composite_type(instrument.id)
    bar_type = f"{iid}-1-MINUTE-LAST-EXTERNAL"

    start = nanos(datetime.combine(entry - timedelta(days=30), daytime(4, 0), tzinfo=NY))
    end = nanos(datetime.combine(entry, daytime(20, 0), tzinfo=NY))
    bars = catalog.query_bars(identifiers=[bar_type], start=start, end=end)
    bars.sort(key=lambda b: b.ts_init)
    by_day: dict[date, list[Bar]] = {}
    for bar in bars:
        day = datetime.fromtimestamp(bar.ts_event // 1_000_000_000, NY).date()
        by_day.setdefault(day, []).append(bar)

    # 14 completed sessions before the entry session, plus the entry session itself.
    sessions = sorted(d for d in by_day if d < entry)[-case["lookback"] :]
    wanted = sessions + [entry]
    raw: dict[date, tuple[Bar, bool] | None] = {}
    daily_volume: dict[str, Decimal] = {}
    for day in wanted:
        day_bars = by_day.get(day, [])
        opened = open_ns(day)
        # Feed through 09:40 so a bucket with a missing minute still closes at 09:35.
        fed = [b for b in day_bars if opened < b.ts_event <= opened + 600_000_000_000]
        minute_bars = [b for b in fed if b.ts_event <= opened + 300_000_000_000]
        coverage = len({b.ts_event for b in minute_bars}) == 5
        emitted = composite_window(instrument, fed, composite)
        completed = [b for b in emitted if b.ts_event == opened + 300_000_000_000]
        raw[day] = (completed[0], coverage) if completed else None
        daily_volume[day.isoformat()] = sum(
            (b.volume.as_decimal() for b in day_bars), Decimal(0)
        )

    windows: dict[str, Any] = {}
    objects: dict[date, sip.OpeningWindow] = {}
    for day in wanted:
        opened = open_ns(day)
        item = raw[day]
        if item is None:
            windows[day.isoformat()] = {"coverage_complete": False, "composite": None}
            continue
        bar, coverage = item
        windows[day.isoformat()] = {
            "open": str(bar.open),
            "close": str(bar.close),
            "volume": str(bar.volume),
            "ts_event": bar.ts_event,
            "ts_init": bar.ts_init,
            "coverage_complete": coverage,
        }
        window = sip.opening_window(
            (bar,),
            session_open_ns=opened,
            as_of_ns=opened + 300_000_000_000,
            coverage_complete=coverage,
            composite_type=composite,
            spec=active,
        )
        if window is not None:
            objects[day] = window

    # Facts: ADV is the measured mean of the same prior sessions; ATR stays None (#129).
    adv = sum((daily_volume[d.isoformat()] for d in sessions), Decimal(0)) / len(sessions)
    facts = sip.DailyFacts(
        instrument_id=instrument.id,
        sessions=tuple(sessions),
        adv=adv,
        atr=None,
        known_at_ns=open_ns(entry),
    )
    current = objects.get(entry)
    prior = tuple(objects[d] for d in sessions if d in objects)
    as_of = open_ns(entry) + 300_000_000_000
    strict = sip.screen(
        current,
        prior,
        expected_sessions=tuple(sessions),
        facts=facts,
        as_of_ns=as_of,
        spec=active,
    )
    # Sensitivity only: treat a partial opening window as if coverage were complete.
    loose_current = current
    item = raw.get(entry)
    if loose_current is None and item is not None:
        bar, _coverage = item
        loose_current = sip.OpeningWindow(
            instrument.id,
            entry,
            bar.open.as_decimal(),
            bar.close.as_decimal(),
            bar.volume.as_decimal(),
            bar.ts_init,
            coverage_complete=True,
            params_hash=active.params_hash,
            composite_type=composite,
        )
    loose = (
        sip.screen(
            loose_current,
            prior,
            expected_sessions=tuple(sessions),
            facts=facts,
            as_of_ns=as_of,
            spec=active,
        )
        if loose_current is not None
        else None
    )

    out = {
        "case": args.case,
        "symbol": symbol,
        "entry_session": entry.isoformat(),
        "prior_sessions": [d.isoformat() for d in sessions],
        "windows": windows,
        "daily_volume": {k: str(v) for k, v in daily_volume.items()},
        "adv": str(adv) if adv is not None else None,
        "strict": {
            "rvol": str(strict.rvol) if strict.rvol is not None else None,
            "passes": strict.passes_local_filters,
            "reason": strict.reason,
        },
        "loose": None
        if loose is None
        else {
            "rvol": str(loose.rvol) if loose.rvol is not None else None,
            "passes": loose.passes_local_filters,
            "reason": loose.reason,
        },
        "flag_at_ns": as_of,
    }
    path = RUN / args.case / "detect.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, sort_keys=True))
    print(json.dumps(out["strict"]), json.dumps(out["loose"]))
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
