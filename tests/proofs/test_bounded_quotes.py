"""Proofs for the bounded SIP L1 quote frontier and arm-e OFI capture; no network."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from alpaca.data.enums import DataFeed
from alpaca.data.live import StockDataStream
from nautilus_trader.model import (
    Currency,
    Equity,
    InstrumentId,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    TradeTick,
)

from sextant.data.quotes import (
    INCOMPLETE_FRONTIER,
    MEMORY_CAP,
    OFI_WINDOW_NS,
    ONE_SESSION_CAP_BYTES,
    ArmEAdmission,
    BoundedQuoteCapture,
    FrontierMember,
    OfiWindow,
    QuoteFrontier,
    ReceiptTimeOfi,
    arm_e_admission,
    frontier_instruments,
    quote_event_imbalance,
    resident_bytes,
)
from sextant.paper.alpaca_feed import AlpacaTickFeed

_TEST_API_KEY = "test-key"
_TEST_API_CREDENTIAL = "test-credential"


def _frontier(**overrides: object) -> QuoteFrontier:
    values: dict[str, object] = {
        "top_n": ("AAPL", "MSFT"),
        "holdings": ("MSFT", "NVDA"),
        "catalysts": ("TSLA", "AAPL"),
        "max_symbols": 4,
    }
    values.update(overrides)
    return QuoteFrontier.build(**values)  # type: ignore[arg-type]


def test_frontier_names_the_union_and_keeps_every_role() -> None:
    frontier = _frontier()

    assert frontier.symbols == ("AAPL", "MSFT", "NVDA", "TSLA")
    assert frontier.complete is True
    assert frontier.missing_sources == ()
    assert frontier.max_symbols == 4
    assert frontier.members == (
        FrontierMember("AAPL", ("top_n", "catalyst")),
        FrontierMember("MSFT", ("top_n", "holding")),
        FrontierMember("NVDA", ("holding",)),
        FrontierMember("TSLA", ("catalyst",)),
    )
    assert frontier.roles_for("AAPL") == ("top_n", "catalyst")
    assert frontier.roles_for("MSFT") == ("top_n", "holding")
    assert frontier.roles_for("NVDA") == ("holding",)
    assert frontier.roles_for("TSLA") == ("catalyst",)


def test_frontier_marks_a_missing_source_incomplete_without_losing_names() -> None:
    frontier = _frontier(catalysts=None)

    assert frontier.complete is False
    assert frontier.missing_sources == ("catalyst",)
    assert frontier.symbols == ("AAPL", "MSFT", "NVDA")


def test_frontier_refuses_more_names_than_its_bound() -> None:
    with pytest.raises(ValueError, match="bound"):
        _frontier(max_symbols=3)


def test_frontier_refuses_a_nonpositive_or_boolean_bound() -> None:
    with pytest.raises(ValueError, match="positive int"):
        _frontier(max_symbols=0)
    with pytest.raises(ValueError, match="positive int"):
        _frontier(max_symbols=True)


def test_frontier_refuses_the_wildcard() -> None:
    with pytest.raises(ValueError, match="wildcard"):
        _frontier(top_n=("*",), holdings=(), catalysts=())


def test_frontier_refuses_an_empty_set() -> None:
    with pytest.raises(ValueError, match="empty"):
        QuoteFrontier.build(top_n=(), holdings=(), catalysts=(), max_symbols=4)


def test_frontier_refuses_an_invalid_symbol() -> None:
    with pytest.raises(ValueError, match="Invalid equity symbol"):
        _frontier(catalysts=("aapl",))


def test_frontier_refuses_a_bare_string_as_a_source() -> None:
    with pytest.raises(ValueError, match="iterable"):
        _frontier(top_n="AAPL")


class _FakeStream(StockDataStream):
    """A stream stand-in that records calls; it never opens a socket."""

    def __init__(self) -> None:
        self.credentials: tuple[str, str] | None = None
        self.feed: DataFeed | None = None
        self.trade_handler: Callable[..., Any] | None = None
        self.quote_handler: Callable[..., Any] | None = None
        self.trade_symbols: tuple[str, ...] = ()
        self.quote_symbols: tuple[str, ...] = ()
        self.run_calls = 0

    def subscribe_trades(self, handler: Callable[..., Any], *symbols: str) -> None:
        self.trade_handler = handler
        self.trade_symbols = symbols

    def subscribe_quotes(self, handler: Callable[..., Any], *symbols: str) -> None:
        self.quote_handler = handler
        self.quote_symbols = symbols

    def run(self) -> None:
        self.run_calls += 1


def _equity(symbol: str) -> Equity:
    return Equity(
        InstrumentId.from_str(f"{symbol}.ALPACA"),
        Symbol(symbol),
        Currency.from_str("USD"),
        4,
        Price.from_str("0.0001"),
        0,
        0,
        lot_size=Quantity.from_int(1),
    )


def _instruments() -> dict[str, Equity]:
    return {symbol: _equity(symbol) for symbol in ("AAPL", "MSFT", "TSLA")}


def test_frontier_instruments_selects_exactly_the_frontier_names() -> None:
    frontier = _frontier(top_n=("AAPL",), holdings=("MSFT",), catalysts=())

    selected = frontier_instruments(frontier, _instruments())

    assert set(selected) == {"AAPL.ALPACA", "MSFT.ALPACA"}
    assert selected["AAPL.ALPACA"] == _equity("AAPL")
    assert "*" not in selected


def test_frontier_instruments_refuses_a_missing_name() -> None:
    frontier = _frontier(top_n=("AAPL",), holdings=("NVDA",), catalysts=())

    with pytest.raises(ValueError, match="no instrument"):
        frontier_instruments(frontier, _instruments())


def test_frontier_instruments_refuses_a_symbol_mismatch() -> None:
    frontier = _frontier(top_n=("AAPL",), holdings=(), catalysts=())

    with pytest.raises(ValueError, match="id symbol"):
        frontier_instruments(frontier, {"AAPL": _equity("MSFT")})


def _ignore_trade(tick: TradeTick) -> None:
    pass


def _ignore_quote(tick: QuoteTick) -> None:
    pass


def test_alpaca_feed_subscribes_only_the_bounded_frontier() -> None:
    frontier = _frontier(top_n=("AAPL",), holdings=("MSFT",), catalysts=())
    selected = frontier_instruments(frontier, _instruments())
    fake = _FakeStream()

    def factory(api_key: str, secret_key: str, *, feed: DataFeed) -> StockDataStream:
        fake.credentials = (api_key, secret_key)
        fake.feed = feed
        return fake

    feed = AlpacaTickFeed(
        selected,
        on_trade=_ignore_trade,
        on_quote=_ignore_quote,
        api_key=_TEST_API_KEY,
        secret_key=_TEST_API_CREDENTIAL,
        stream_factory=factory,
    )

    feed.start()

    assert fake.feed is DataFeed.SIP
    assert fake.quote_symbols == ("AAPL", "MSFT")
    assert fake.trade_symbols == fake.quote_symbols
    assert "TSLA" not in fake.quote_symbols
    assert "*" not in fake.quote_symbols


_NS = 1_000_000_000
_IID = InstrumentId.from_str("AAPL.ALPACA")


def _quote(
    *,
    bid: str = "10.00",
    ask: str = "10.02",
    bid_size: str = "100",
    ask_size: str = "200",
    ts_event: int = 0,
    ts_init: int = 0,
    instrument_id: InstrumentId = _IID,
) -> QuoteTick:
    return QuoteTick(
        instrument_id,
        Price.from_str(bid),
        Price.from_str(ask),
        Quantity.from_str(bid_size),
        Quantity.from_str(ask_size),
        ts_event,
        ts_init,
    )


def _paper_imbalance(previous: QuoteTick, current: QuoteTick) -> Decimal:
    zero = Decimal(0)
    one = Decimal(1)
    pb0 = previous.bid_price.as_decimal()
    qb0 = previous.bid_size.as_decimal()
    pa0 = previous.ask_price.as_decimal()
    qa0 = previous.ask_size.as_decimal()
    pb1 = current.bid_price.as_decimal()
    qb1 = current.bid_size.as_decimal()
    pa1 = current.ask_price.as_decimal()
    qa1 = current.ask_size.as_decimal()
    return (
        (one if pb1 >= pb0 else zero) * qb1
        - (one if pb1 <= pb0 else zero) * qb0
        - (one if pa1 <= pa0 else zero) * qa1
        + (one if pa1 >= pa0 else zero) * qa0
    )


@pytest.mark.parametrize(
    ("previous", "current"),
    [
        pytest.param(
            _quote(bid_size="100", ask_size="200"),
            _quote(bid="10.01", bid_size="150", ask_size="200"),
            id="bid-up",
        ),
        pytest.param(
            _quote(bid="10.01", bid_size="150", ask_size="200"),
            _quote(bid="10.00", bid_size="120", ask_size="200"),
            id="bid-down",
        ),
        pytest.param(
            _quote(bid_size="100", ask_size="200"),
            _quote(bid_size="140", ask_size="200"),
            id="bid-size-up",
        ),
        pytest.param(
            _quote(bid_size="140", ask_size="200"),
            _quote(bid_size="90", ask_size="200"),
            id="bid-size-down",
        ),
        pytest.param(
            _quote(bid_size="100", ask_size="200"),
            _quote(bid_size="100", ask="10.03", ask_size="250"),
            id="ask-up",
        ),
        pytest.param(
            _quote(bid_size="100", ask_size="200"),
            _quote(bid_size="100", ask="10.01", ask_size="150"),
            id="ask-down",
        ),
        pytest.param(
            _quote(bid_size="100", ask_size="200"),
            _quote(bid_size="100", ask_size="260"),
            id="ask-size-up",
        ),
        pytest.param(
            _quote(bid_size="100", ask_size="260"),
            _quote(bid_size="100", ask_size="180"),
            id="ask-size-down",
        ),
        pytest.param(
            _quote(bid_size="100", ask_size="200"),
            _quote(bid_size="100", ask_size="200"),
            id="unchanged",
        ),
    ],
)
def test_quote_event_imbalance_matches_the_paper_indicator_equation(
    previous: QuoteTick, current: QuoteTick
) -> None:
    assert quote_event_imbalance(previous, current) == _paper_imbalance(previous, current)


def test_ofi_fixture_reproduces_expected_sign_on_a_controlled_path() -> None:
    buy0 = _quote(bid_size="100", ask_size="200")
    buy1 = _quote(bid_size="150", ask_size="150")
    buy2 = _quote(bid="10.01", bid_size="150", ask_size="150")

    assert quote_event_imbalance(buy0, buy1) == Decimal("100")
    assert quote_event_imbalance(buy1, buy2) == Decimal("150")

    sell0 = _quote(bid_size="150", ask_size="150")
    sell1 = _quote(bid_size="100", ask_size="150")
    sell2 = _quote(bid="9.99", bid_size="100", ask_size="150")

    assert quote_event_imbalance(sell0, sell1) == Decimal("-50")
    assert quote_event_imbalance(sell1, sell2) == Decimal("-100")


def test_ofi_windows_join_on_local_receipt_not_vendor_time() -> None:
    assert OFI_WINDOW_NS == 10 * _NS
    book = ReceiptTimeOfi("AAPL", window_ns=_NS)
    first = _quote(bid_size="100", ts_event=900_000_000, ts_init=100_000_000)
    second = _quote(bid_size="140", ts_event=100_000_000, ts_init=400_000_000)

    assert book.update(first) == ()
    assert book.update(second) == ()

    third = _quote(bid_size="150", ts_event=1_400_000_000, ts_init=1_500_000_000)
    windows = book.update(third)

    assert windows == (
        OfiWindow(
            symbol="AAPL",
            start_ns=0,
            end_ns=_NS,
            receipt_ts=400_000_000,
            updates=2,
            imbalance=Decimal("40"),
        ),
    )
    assert windows[0].receipt_ts != second.ts_event
    assert book.flush() == OfiWindow(
        symbol="AAPL",
        start_ns=_NS,
        end_ns=2 * _NS,
        receipt_ts=1_500_000_000,
        updates=1,
        imbalance=Decimal("10"),
    )
    assert book.flush() is None


def test_stale_receipt_is_ignored_even_with_a_newer_vendor_time() -> None:
    book = ReceiptTimeOfi("AAPL", window_ns=_NS)
    first = _quote(bid_size="100", ts_event=0, ts_init=2_000_000_000)
    stale = _quote(bid_size="999", ts_event=9_000_000_000, ts_init=1_000_000_000)
    third = _quote(bid_size="120", ts_event=0, ts_init=2_100_000_000)

    assert book.update(first) == ()
    assert book.update(stale) == ()
    assert book.update(third) == ()

    assert book.flush() == OfiWindow(
        symbol="AAPL",
        start_ns=2_000_000_000,
        end_ns=3_000_000_000,
        receipt_ts=2_100_000_000,
        updates=2,
        imbalance=Decimal("20"),
    )


def test_quote_event_imbalance_refuses_two_instruments() -> None:
    with pytest.raises(ValueError, match="instrument"):
        quote_event_imbalance(_quote(), _quote(instrument_id=InstrumentId.from_str("MSFT.ALPACA")))


def test_quote_event_imbalance_refuses_a_crossed_book() -> None:
    with pytest.raises(ValueError, match="crossed"):
        quote_event_imbalance(_quote(bid="10.03"), _quote())


def test_receipt_time_ofi_refuses_another_symbol_and_a_bad_window() -> None:
    with pytest.raises(ValueError, match="does not belong"):
        ReceiptTimeOfi("AAPL").update(_quote(instrument_id=InstrumentId.from_str("MSFT.ALPACA")))
    with pytest.raises(ValueError, match="window"):
        ReceiptTimeOfi("AAPL", window_ns=0)


def test_arm_e_admission_admits_a_complete_frontier_below_the_cap() -> None:
    assert arm_e_admission(_frontier(), resident_bytes=ONE_SESSION_CAP_BYTES - 1) == ArmEAdmission(
        admitted=True
    )


def test_arm_e_admission_refuses_an_incomplete_frontier() -> None:
    admission = arm_e_admission(_frontier(catalysts=None), resident_bytes=0)

    assert admission == ArmEAdmission(admitted=False, reasons=(INCOMPLETE_FRONTIER,))


def test_arm_e_admission_refuses_the_full_memory_cap() -> None:
    admission = arm_e_admission(_frontier(), resident_bytes=ONE_SESSION_CAP_BYTES)

    assert admission == ArmEAdmission(admitted=False, reasons=(MEMORY_CAP,))


def test_arm_e_admission_reports_every_refusal() -> None:
    admission = arm_e_admission(_frontier(catalysts=None), resident_bytes=ONE_SESSION_CAP_BYTES)

    assert admission.reasons == (INCOMPLETE_FRONTIER, MEMORY_CAP)


def test_arm_e_admission_refuses_to_raise_the_one_session_cap() -> None:
    with pytest.raises(ValueError, match="never raised"):
        arm_e_admission(
            _frontier(),
            resident_bytes=0,
            cap_bytes=ONE_SESSION_CAP_BYTES + 1,
        )


def test_arm_e_admission_refuses_a_negative_resident_size() -> None:
    with pytest.raises(ValueError, match="resident"):
        arm_e_admission(_frontier(), resident_bytes=-1)


def test_bounded_capture_accepts_only_frontier_quotes_and_emits_windows() -> None:
    frontier = _frontier(top_n=("AAPL",), holdings=("MSFT",), catalysts=())
    windows: list[OfiWindow] = []
    capture = BoundedQuoteCapture(frontier, on_window=windows.append, window_ns=_NS)

    capture.on_quote(_quote(bid_size="100", ts_init=100_000_000))
    capture.on_quote(_quote(bid_size="140", ts_init=400_000_000))
    capture.on_quote(_quote(bid_size="150", ts_init=1_500_000_000))

    assert windows == [
        OfiWindow("AAPL", 0, _NS, 400_000_000, 2, Decimal("40")),
    ]

    capture.flush()

    assert windows[-1] == OfiWindow("AAPL", _NS, 2 * _NS, 1_500_000_000, 1, Decimal("10"))

    with pytest.raises(ValueError, match="outside"):
        capture.on_quote(
            _quote(instrument_id=InstrumentId.from_str("NVDA.ALPACA"), ts_init=2_000_000_000)
        )


def test_bounded_capture_refuses_an_incomplete_frontier() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        BoundedQuoteCapture(_frontier(catalysts=None), on_window=lambda window: None)


def test_resident_bytes_reports_a_positive_rss() -> None:
    assert resident_bytes() > 0
