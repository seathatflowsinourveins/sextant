"""A rejected future-stamped quote cannot poison later valid quotes."""

from nautilus_trader.model import QuoteTick

from .conftest import quote, trade
from .test_replay import replay


def test_future_quote_does_not_suppress_later_valid_entry(instrument, tmp_path):
    future, early = quote(100, "10.00", "10.02"), quote(0, "10.00", "10.02")
    malformed = QuoteTick(
        future.instrument_id,
        future.bid_price,
        future.ask_price,
        future.bid_size,
        future.ask_size,
        future.ts_event,
        early.ts_init,
    )
    result = replay(
        instrument,
        tmp_path,
        [malformed, quote(1, "10.00", "10.02")]
        + [trade(at, "10.01", size=10000) for at in (1, 2, 3)],
    )
    assert len(result.orders) == 1 and not result.failed, result.events
