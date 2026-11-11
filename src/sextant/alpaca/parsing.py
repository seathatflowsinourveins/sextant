"""Parse an alpaca-py ``Asset`` into a Nautilus ``Equity`` on Alpaca's tick ladder.

alpaca-py 0.44.0 ``alpaca/trading/models.py:32`` exposes ``price_increment`` as
a float or ``None``; the paper runners already observed ``None`` for US equities.
The Equity shape (zero size precision, multiplier and size increment one, USD
quote currency) follows nautilus_trader@d53849b216e20f2c122ca01b4dd0da377638b186
``docs/concepts/instruments/equity.md``. The instrument uses the engine's own
tiered tick scheme mechanism (``register_tick_scheme``; the Rust precedent is
``crates/model/src/instruments/tick_scheme.rs:150-217``): Alpaca accepts at most
two decimals for a limit or stop price at or above $1.00 and at most four below
$1.00, rejecting an excess increment with error 42210000 (Alpaca "Orders at
Alpaca", sub-penny increments, https://docs.alpaca.markets/us/docs/orders-at-alpaca,
page updated 2026-10-13, read 2026-11-10). Every equity therefore carries
``price_precision`` 4 and the 0.0001 unit increment, and the
``ALPACA_US_EQUITY`` scheme supplies the 0.01 penny at and above $1.00. The
scheme's open tier expands to its last bounded tick (1,000,000 ticks, ending at
$10,000.99); the engine reports no farther tick from the scheme.
"""

from __future__ import annotations

from alpaca.trading.models import Asset
from nautilus_trader.model import (
    Currency,
    Equity,
    InstrumentId,
    Price,
    Symbol,
    TieredTickScheme,
    list_tick_schemes,
    register_tick_scheme,
)

from .constants import VENUE

_USD = Currency.from_str("USD")
_SUB_PENNY = "0.0001"
_PRICE_PRECISION = 4

ALPACA_TICK_SCHEME = "ALPACA_US_EQUITY"
_PRICE_TIERS = ((0.0, 1.0, 0.0001), (1.0, float("inf"), 0.01))
_MAX_TICKS_PER_TIER = 1_000_000

_VENDOR_FLAGS = ("tradable", "shortable", "easy_to_borrow", "marginable", "fractionable")


def register_alpaca_equity_tick_scheme() -> str:
    """Register the Alpaca equity tick ladder once, and return its name."""
    if ALPACA_TICK_SCHEME not in list_tick_schemes():
        register_tick_scheme(
            TieredTickScheme(
                ALPACA_TICK_SCHEME,
                _PRICE_TIERS,
                _PRICE_PRECISION,
                _MAX_TICKS_PER_TIER,
            ),
        )
    return ALPACA_TICK_SCHEME


def parse_equity(asset: Asset, *, ts_init: int) -> Equity:
    """Build an ALPACA-venue Equity from an Alpaca assets response row."""
    symbol = Symbol(asset.symbol)
    return Equity(
        instrument_id=InstrumentId(symbol, VENUE),
        raw_symbol=symbol,
        currency=_USD,
        price_precision=_PRICE_PRECISION,
        price_increment=Price.from_str(_SUB_PENNY),
        ts_event=ts_init,
        ts_init=ts_init,
        tick_scheme=register_alpaca_equity_tick_scheme(),
        info={name: bool(getattr(asset, name, False)) for name in _VENDOR_FLAGS},
    )
