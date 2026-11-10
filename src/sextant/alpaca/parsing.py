"""Parse an alpaca-py ``Asset`` into a Nautilus ``Equity``.

alpaca-py 0.44.0 ``alpaca/trading/models.py:32`` exposes ``price_increment`` as
a float or ``None``; the paper runners already observed ``None`` for US equities.
The Equity shape (zero size precision, multiplier and size increment one, USD
quote currency) follows nautilus_trader@d53849b216e20f2c122ca01b4dd0da377638b186
``docs/concepts/instruments/equity.md``. The fallback tick (0.0001 below $1)
follows the N4 ladder the paper runners apply in
``src/sextant/paper/c_live_main.py:273-295`` so a sub-dollar name is not rounded
up to a penny; a limit at or above $1 still lands on the penny branch when the
order is written.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from alpaca.trading.models import Asset
from nautilus_trader.model import Currency, Equity, InstrumentId, Price, Symbol

from .constants import VENUE

_USD = Currency.from_str("USD")
_N4_SUB_DOLLAR_TICK = "0.0001"
_N4_SUB_DOLLAR_PRECISION = 4


def _price_increment(asset: Asset) -> tuple[int, Price]:
    """Return the vendor tick, or the N4 sub-dollar tick when it is absent."""
    raw = getattr(asset, "price_increment", None)
    if raw is not None:
        try:
            increment = Decimal(str(raw)).normalize()
        except (InvalidOperation, ValueError):
            increment = Decimal(0)
        if increment.is_finite() and increment > 0:
            exponent = increment.as_tuple().exponent
            if isinstance(exponent, int):
                return max(0, -exponent), Price.from_str(format(increment, "f"))
    return _N4_SUB_DOLLAR_PRECISION, Price.from_str(_N4_SUB_DOLLAR_TICK)


def parse_equity(asset: Asset, *, ts_init: int) -> Equity:
    """Build an ALPACA-venue Equity from an Alpaca assets response row."""
    price_precision, price_increment = _price_increment(asset)
    symbol = Symbol(asset.symbol)
    return Equity(
        instrument_id=InstrumentId(symbol, VENUE),
        raw_symbol=symbol,
        currency=_USD,
        price_precision=price_precision,
        price_increment=price_increment,
        ts_event=ts_init,
        ts_init=ts_init,
    )
