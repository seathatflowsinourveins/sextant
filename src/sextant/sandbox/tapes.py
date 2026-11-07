"""Recorded bars/BBO facts and separately labelled native synthetic mechanisms.

Sources: #41 catalog loader; #134 recorded reader; native rc7 customdataclass;
owning entry/ranking/exit/custody proof event shapes. No OHLC-to-tick expansion.
"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model import (
    AggressorSide,
    Bar,
    BarType,
    Currency,
    CustomData,
    DataType,
    Equity,
    InstrumentId,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    TradeId,
    TradeTick,
    register_custom_data_class,
)
from nautilus_trader.model.custom import customdataclass
from nautilus_trader.persistence import ParquetDataCatalog

from sextant.research.exit_study_41 import BARS, verify_inputs, write_catalog
from sextant.sandbox.handoff import digest, wire
from sextant.sandbox.profile import values
from sextant.sandbox.recorded import read_snapshot

NS = 1_000_000_000


@customdataclass
class ScannerFacts:
    payload: str


def scanner_type():
    register_custom_data_class(ScannerFacts)
    return DataType("ScannerFacts")


def recorded(inputs: Path, catalog_root: Path, snapshot: Path, snapshot_hash: str):
    hashes = verify_inputs(inputs)
    catalog = (
        ParquetDataCatalog(str(catalog_root))
        if catalog_root.exists()
        else write_catalog(inputs / BARS, catalog_root)
    )
    instruments = list(catalog.instruments())
    bars = list(catalog.query_bars())
    symbols = frozenset(str(instrument.id.symbol) for instrument in instruments)
    facts = read_snapshot(snapshot, expected_sha256=snapshot_hash, symbols=symbols)
    payload = dict(
        path=facts.path,
        sha256=facts.sha256,
        ranking_authority=facts.ranking_authority,
        capture_completed_ns=facts.capture_completed_ns,
        received_ns=facts.received_ns,
        quotes=[
            dict(
                instrument=str(q.instrument_id),
                bid=str(q.bid_price),
                ask=str(q.ask_price),
                ts_event=q.ts_event,
                ts_init=q.ts_init,
                bid_size=None if q.bid_size is None else str(q.bid_size),
                ask_size=None if q.ask_size is None else str(q.ask_size),
            )
            for q in facts.quotes
        ],
        missing=list(facts.missing_quotes),
    )
    envelope = CustomData(
        scanner_type(),
        cast(Any, ScannerFacts)(facts.as_of_ns, facts.generated_ns, payload=wire(payload).decode()),
    )
    data = sorted([*bars, envelope], key=lambda item: (item.ts_init, isinstance(item, CustomData)))
    catalog_hashes = {
        str(path.relative_to(catalog_root)): digest(path.read_bytes())
        for path in sorted(catalog_root.rglob("*.parquet"))
    }
    return (
        instruments,
        data,
        hashes | {snapshot.name: snapshot_hash, "native_catalog": digest(catalog_hashes)},
    )


def fixture(profile: dict):
    spec = values(profile, "tape")
    start = dt_to_unix_nanos(datetime.fromisoformat(spec["start"]))
    iid = InstrumentId.from_str("AAA.ALPACA")
    instrument = Equity(
        iid,
        Symbol("AAA"),
        Currency.from_str("USD"),
        2,
        Price.from_str("0.01"),
        0,
        0,
        lot_size=Quantity.from_int(1),
    )
    data = []
    bar_type = BarType.from_str(f"{iid}-1-MINUTE-LAST-EXTERNAL")
    for second in range(spec["length_s"]):
        at = start + second * NS
        price = (
            "10.00"
            if second < 300
            else "10.20"
            if second < 360
            else (
                "10.31"
                if second == 360
                else "10.32"
                if second == 361
                else "10.33"
                if second < 370
                else "10.50"
                if second < 421
                else "10.46"
            )
        )
        bid = Decimal(price)
        ask = bid + Decimal("0.01")
        if second and second % 60 == 0:
            data.append(
                Bar(
                    bar_type,
                    Price.from_str(price),
                    Price.from_str(str(bid + Decimal("0.10"))),
                    Price.from_str(str(bid - Decimal("0.10"))),
                    Price.from_str(price),
                    Quantity.from_int(spec["trade_size"]),
                    at,
                    at,
                )
            )
        data.append(
            QuoteTick(
                iid,
                Price.from_str(price),
                Price.from_str(str(ask)),
                Quantity.from_int(spec["quote_size"]),
                Quantity.from_int(spec["quote_size"]),
                at,
                at,
            )
        )
        if second % 60 == 0 or second >= 300:
            data.append(
                TradeTick(
                    iid,
                    Price.from_str(price),
                    Quantity.from_int(spec["trade_size"]),
                    AggressorSide.BUY,
                    TradeId(str(at)),
                    at,
                    at,
                )
            )
    identity = [
        dict(type=type(event).__name__, event=event.ts_event, init=event.ts_init, value=str(event))
        for event in data
    ]
    return [instrument], data, {"synthetic-fixture": digest(identity)}
