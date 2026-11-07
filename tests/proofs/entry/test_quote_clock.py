"""Quote clocks and books: a bad newest quote never poisons, or falls back to, another."""

import pytest
from nautilus_trader.execution import StaticLatencyModel
from nautilus_trader.model import QuoteTick

from .conftest import SEC, START, quote, trade
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


def stamped(seconds, bid, ask, *, arrival):
    base, late = quote(seconds, bid, ask), quote(arrival, bid, ask)
    return QuoteTick(
        base.instrument_id,
        base.bid_price,
        base.ask_price,
        base.bid_size,
        base.ask_size,
        base.ts_event,
        late.ts_init,
    )


@pytest.mark.parametrize(
    ("bid", "ask", "submit_at"),
    [(None, None, 2), ("10.10", "10.05", 3), ("10.02", "10.02", 2), ("0.00", "10.50", 3)],
    ids=["clean", "crossed", "locked-admitted", "one-sided"],
)
def test_an_invalid_newest_book_is_unknown_and_never_falls_back(
    instrument, tmp_path, bid, ask, submit_at
):
    data = [quote(0, "10.00", "10.02"), *[trade(at, "10.01", size=10000) for at in (0, 1, 2)]]
    if bid:  # first_leg.py:550 refuses not 0 < bid <= ask; the older quote is never reused
        data += [quote("1.9", bid, ask), stamped("1.5", "10.00", "10.02", arrival="2.5")]
    data += [quote(3, "10.00", "10.02")]
    result = replay(instrument, tmp_path, sorted(data, key=lambda item: item.ts_init))
    submits = [e["ts"] for e in result.events if e["action"] == "SUBMIT"]
    assert submits == [START + submit_at * SEC], result.events


@pytest.mark.parametrize("book", ["valid", "crossed"])
def test_an_invalid_newest_book_never_reprices_from_an_older_quote(instrument, tmp_path, book):
    # The entry is in flight at t2.3; the acceptance at t2.5 would reprice from that quote.
    data = [quote(0, "10.00", "10.02"), *[trade(at, "10.01", size=10000) for at in (0, 1, 2)]]
    data += [quote("2.1", "10.49", "10.50"), quote("2.3", "10.02", "10.03")]
    if book == "crossed":
        data.append(quote("2.4", "10.10", "10.03"))
    data.append(trade(3, "10.01", size=10000))  # runs past the acceptance; no newer quote
    latency = StaticLatencyModel(insert_latency_nanos=500_000_000)
    result = replay(instrument, tmp_path, data, latency_model=latency)
    assert len(result.orders) == 1, result.events
    assert any(e["action"] == "MODIFY" for e in result.events) is (book == "valid"), result.events
