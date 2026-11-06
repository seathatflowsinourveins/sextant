"""Read-only scanner BBO facts, preserving absent size and receipt authority.

Shape: pinned northstar_trading/scanner snapshots and b_exit_replay.load_spreads;
hash/Decimal shape: Sextant exit_study_41.py. Native rc7 model constructors.
These facts do not reconstruct the original trade stream or ranking generation.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model import InstrumentId, Price, Quantity, QuoteTick


def timestamp(value: str) -> int:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("recorded clock requires an explicit offset")
    return dt_to_unix_nanos(parsed)


def positive(value) -> Decimal:
    if type(value) not in (str, Decimal, int):
        raise ValueError("recorded price requires exact Decimal text")
    result = Decimal(value)
    if not result.is_finite() or result <= 0:
        raise ValueError("recorded price must be finite and positive")
    return result


@dataclass(frozen=True)
class RecordedQuote:
    instrument_id: InstrumentId
    bid_price: Price
    ask_price: Price
    ts_event: int
    ts_init: int
    bid_size: Quantity | None
    ask_size: Quantity | None

    def to_native(self) -> QuoteTick:
        if self.bid_size is None or self.ask_size is None:
            raise ValueError("quote sizes unavailable; cannot invent executable liquidity")
        return QuoteTick(
            self.instrument_id,
            self.bid_price,
            self.ask_price,
            self.bid_size,
            self.ask_size,
            self.ts_event,
            self.ts_init,
        )


@dataclass(frozen=True)
class RecordedSnapshot:
    path: str
    sha256: str
    as_of_ns: int
    generated_ns: int
    quotes: tuple[RecordedQuote, ...]
    missing_quotes: tuple[str, ...]
    capture_completed_ns: int | None
    received_ns: int | None
    ranking_authority: str = "UNAVAILABLE"
    tier: str = "MODELED"


def read_snapshot(path: Path, *, expected_sha256: str, symbols: frozenset[str]) -> RecordedSnapshot:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise ValueError("scanner snapshot hash mismatch")
    document = json.loads(raw, parse_float=Decimal)
    as_of, generated = timestamp(document["as_of"]), timestamp(document["generated_at"])
    if generated < as_of:
        raise ValueError("scanner generation precedes as_of")
    quotes, missing, seen = [], set(symbols), set()
    for row in document["symbols"]:
        symbol = row["symbol"]
        if symbol not in symbols:
            continue
        if symbol in seen:
            raise ValueError("duplicate snapshot symbol")
        seen.add(symbol)
        quote = row.get("coverage", {}).get("tradeability", {})
        if any(quote.get(field) is None for field in ("bid", "ask", "quote_at")):
            continue
        at = timestamp(quote["quote_at"])
        if at > as_of:
            raise ValueError("quote event is after the snapshot cutoff")
        bid, ask = positive(quote["bid"]), positive(quote["ask"])
        if bid > ask:
            raise ValueError("crossed recorded quote")
        sizes = [
            None
            if quote.get(field) is None
            else Quantity.from_str(format(positive(quote[field]), "f"))
            for field in ("bid_size", "ask_size")
        ]
        quotes.append(
            RecordedQuote(
                InstrumentId.from_str(f"{symbol}.ALPACA"),
                Price.from_str(format(bid, "f")),
                Price.from_str(format(ask, "f")),
                at,
                generated,
                *sizes,
            )
        )
        missing.discard(symbol)
    return RecordedSnapshot(
        str(path),
        digest,
        as_of,
        generated,
        tuple(quotes),
        tuple(sorted(missing)),
        None
        if document.get("capture_completed_at") is None
        else timestamp(document["capture_completed_at"]),
        None if document.get("received_at") is None else timestamp(document["received_at"]),
    )
