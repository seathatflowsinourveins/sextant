"""Raw Alpaca SIP 1-minute bars and the synthetic trade tick used by the replay.

The frozen K3 section reads SIP trades at 04:00-11:35 ET; the only bar cache
that exists for the sealed 2026-11-09 cohort is the e2e-omh raw JSON.  This
module keeps that fidelity explicit: one synthetic tick per non-zero-volume
minute at the bar close, zero-volume minutes skipped, and a named bar-close
flag for every tick.  There is no anchor or segment-start tick: coverage of a
segment prefix comes from the recording's receipt, never from a print.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

NS = 1_000_000_000
MINUTE_NS = 60 * NS


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    ts_ns: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    trades: int
    vwap: Decimal

    def __post_init__(self) -> None:
        if self.ts_ns < 0 or type(self.volume) is not int or self.volume < 0:
            raise ValueError("bar needs a nonnegative timestamp and integer volume")
        for name in ("open", "high", "low", "close", "vwap"):
            value = getattr(self, name)
            if type(value) is not Decimal or not value.is_finite() or value <= 0:
                raise ValueError(f"bar {self.symbol} needs positive finite Decimal {name}")

    @property
    def close_ns(self) -> int:
        return self.ts_ns + MINUTE_NS

    @property
    def dollar_volume(self) -> Decimal:
        return self.close * self.volume


class _DecimalView:
    """The two methods northstar-lanes' pure transitions read from a tick."""

    __slots__ = ("_value",)

    def __init__(self, value: Decimal) -> None:
        self._value = value

    def as_decimal(self) -> Decimal:
        return self._value


class _InstrumentId:
    __slots__ = ("symbol",)

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol


@dataclass(frozen=True, slots=True)
class Tick:
    instrument_id: _InstrumentId
    price: _DecimalView
    size: _DecimalView
    ts_event: int
    ts_init: int


def tick_from_bar(bar: Bar) -> Tick:
    at = bar.close_ns
    return Tick(
        _InstrumentId(bar.symbol),
        _DecimalView(bar.close),
        _DecimalView(Decimal(bar.volume)),
        at,
        at,
    )


def parse_utc_ns(text: str) -> int:
    """Raw bars carry second-resolution UTC ISO strings; reject anything else."""
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:  # pragma: no cover - malformed upstream data
        raise ValueError(f"unexpected bar timestamp {text!r}") from exc
    return int(parsed.timestamp()) * NS


def load_raw_day(
    root: Path,
    day: date,
    symbols: set[str] | None = None,
    *,
    requested_out: set[str] | None = None,
) -> dict[str, tuple[Bar, ...]]:
    """Read the 48 batch files of one day, keeping only requested symbols.

    Each batch file's outer ``symbols`` list is the recording's declared
    coverage for that day: every name it asked for, whether or not a bar
    printed.  ``requested_out`` collects the union across the day's files, so a
    caller can distinguish a covered silent symbol (a zero) from a session
    that never recorded the symbol at all (an unknown).  A day whose files
    declare no symbols leaves the set empty; absence is never imputed.
    """
    directory = Path(root) / "1min" / day.isoformat()
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    out: dict[str, list[Bar]] = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if requested_out is not None:
            requested_out.update(str(symbol) for symbol in payload.get("symbols", ()))
        for page in payload.get("pages", ()):
            bars = json.loads(page).get("bars", {})
            for symbol, rows in bars.items():
                if symbols is not None and symbol not in symbols:
                    continue
                bucket = out.setdefault(symbol, [])
                for row in rows:
                    close = Decimal(str(row["c"]))
                    if close <= 0 or int(row["v"]) <= 0:
                        continue
                    bucket.append(
                        Bar(
                            symbol,
                            parse_utc_ns(row["t"]),
                            Decimal(str(row["o"])),
                            Decimal(str(row["h"])),
                            Decimal(str(row["l"])),
                            close,
                            int(row["v"]),
                            int(row.get("n", 0)),
                            Decimal(str(row["vw"])),
                        )
                    )
    return {symbol: tuple(sorted(rows, key=lambda b: b.ts_ns)) for symbol, rows in out.items()}
