"""Small dependencies of the display carry, not the upstream top100 ranker.

northstar-trading@8256c16c:scanner/top100.py:92-99,112-127,547-564,
2517-2543; tradingview/inputs.py:25,43-50; scanner/engine.py:69-73;
scanner/scoring.py:aware; scanner/timestamps.py:29-54,78-85.
Timestamp parsing reuses Sextant's exact rc8 bridge; calendar views never order.
"""

from collections.abc import Mapping
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sextant.tradingview.inputs import EPOCH, ET, QUALIFIED, InputError, _ns

FLAG_NAMES: tuple[str, ...] = (
    "dilution",
    "insider_sale_cluster",
    "lockup_expiry",
    "ownership_exit_13dg",
    "finra_short_volume",
    "overhead_supply",
)
TV_EXCHANGE_MAP = {
    "NASDAQ": "NASDAQ",
    "XNAS": "NASDAQ",
    "NYSE": "NYSE",
    "XNYS": "NYSE",
    "ARCA": "AMEX",
    "ARCX": "AMEX",
    "NYSEARCA": "AMEX",
    "AMEX": "AMEX",
    "XASE": "AMEX",
    "BATS": "CBOE",
    "CBOE": "CBOE",
}


def timestamp_ns(value: str | datetime | int) -> int:
    return value if type(value) is int else _ns(value)


def calendar_time(value: str | datetime | int) -> datetime:
    return EPOCH + timedelta(microseconds=timestamp_ns(value) // 1000)


def timestamp_iso(value: int) -> str:
    if value % 1000 == 0:
        return calendar_time(value).isoformat()
    seconds, fraction = divmod(value, 1_000_000_000)
    whole = (EPOCH + timedelta(seconds=seconds)).isoformat(timespec="seconds")
    return whole.replace("+00:00", f".{fraction:09d}+00:00")


def phase(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")
    at = now.astimezone(ET).time()
    if at >= time(20) or at < time(4):
        return "overnight"
    return "pre" if at < time(9, 30) else "rth" if at < time(16) else "post"


def dec(value: Any) -> Decimal | None:
    """Parse finite Decimal without binary float conversion; reject bool/float/NaN."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = Decimal(stripped)
        except InvalidOperation:
            return None
        return parsed if parsed.is_finite() else None
    raise TypeError(f"Binary float or unsupported numeric type refused: {type(value)!r}")


def qualify_tradingview_symbol(
    symbol: str,
    scanner_row: Mapping[str, Any] | None,
    mapping: Mapping[str, str] | None = None,
) -> tuple[str | None, str]:
    if not isinstance(symbol, str) or not symbol or symbol != symbol.strip():
        raise InputError("A deployment symbol must be nonempty text")
    name, sep, venue = symbol.rpartition(".")
    venues = {"SMART", "IB", "IBKR", "ALPACA", "XNAS", "XNYS", "NASDAQ", "NYSE", "ARCA", "XASE"}
    clean = name if sep and name and venue in venues else symbol
    if mapping and clean in mapping:
        candidate = mapping[clean]
        prefix, _, _ = candidate.partition(":")
        if QUALIFIED.fullmatch(candidate) and prefix not in {"SMART", "IB", "IBKR", "ALPACA"}:
            return candidate, "symbol_map"
    if isinstance(scanner_row, Mapping):
        raw_exch = scanner_row.get("exchange")
        if isinstance(raw_exch, str):
            tv_exch = TV_EXCHANGE_MAP.get(raw_exch.strip().upper())
            if tv_exch:
                candidate = f"{tv_exch}:{clean}"
                if QUALIFIED.fullmatch(candidate):
                    return candidate, "scanner_exchange"
    return None, "UNVERIFIED"
