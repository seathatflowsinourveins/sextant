"""B's outside-RTH market data: fed breach, truthful arming, and a page on silence.

The production entrypoint used to subscribe only the trade-update stream, so outside regular
hours the emulated BID_ASK trigger never saw a quote or a print and the state line could claim
protection it did not have. These proofs drive the REST latest-quote/latest-trade adapter and
the silence watchdog; they name the pinned alpaca-py client, requests and feeds (clean B).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from alpaca.data.enums import DataFeed
from alpaca.data.models import Quote, Trade
from alpaca.data.requests import StockLatestQuoteRequest, StockLatestTradeRequest
from alpaca.trading.models import Order, Position, TradeAccount, TradeUpdate
from alpaca.trading.requests import LimitOrderRequest, TrailingStopOrderRequest
from alpaca.trading.stream import TradingStream

from sextant.paper.b_feed import BMarketDataFeed, feed_for
from sextant.paper.b_protector import BParameters, Protector, ProtectorStream
from sextant.paper.config import PaperAccount
from sextant.paper.sessions import Session

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 9, 20, 30, tzinfo=ET)  # overnight, outside the regular session
NOW_NS = int(NOW.timestamp()) * 1_000_000_000
SEC = 1_000_000_000


def b_account() -> PaperAccount:
    return PaperAccount(
        lane="alpaca-paper-b",
        account_id="paper-fixture",
        client_id="ALPACA-B",
        namespace="B001",
        sessions=(Session.RTH,),
    )


def b_params() -> BParameters:
    return BParameters(
        native_trail_fraction=Decimal("0.025"),
        reconcile_interval_s=Decimal("10"),
        feed_poll_interval_s=Decimal("1"),
        feed_silence_s=Decimal("5"),
    )


def api_account(number: str = "paper-fixture") -> TradeAccount:
    return TradeAccount.model_validate(
        {
            "id": str(uuid4()),
            "account_number": number,
            "status": "ACTIVE",
            "currency": "USD",
            "buying_power": "100000",
            "cash": "100000",
            "portfolio_value": "100000",
            "equity": "100000",
        }
    )


def api_position(qty: str = "10", symbol: str = "AAPL") -> Position:
    return Position.model_validate(
        {
            "asset_id": str(uuid4()),
            "symbol": symbol,
            "exchange": "NASDAQ",
            "asset_class": "us_equity",
            "avg_entry_price": "100",
            "qty": qty,
            "side": "long",
            "cost_basis": "1000",
            "qty_available": qty,
        }
    )


def api_order(
    *,
    client_order_id: str = "B001-trail-1",
    symbol: str = "AAPL",
    qty: str = "10",
    filled_qty: str = "0",
    side: str = "sell",
    order_type: str = "trailing_stop",
    status: str = "new",
    stop_price: str | None = None,
    limit_price: str | None = None,
    extended_hours: bool = False,
) -> Order:
    payload = {
        "id": str(uuid4()),
        "client_order_id": client_order_id,
        "created_at": "2026-11-09T23:59:00Z",
        "updated_at": "2026-11-09T23:59:00Z",
        "submitted_at": "2026-11-09T23:59:00Z",
        "order_class": "simple",
        "time_in_force": "gtc",
        "status": status,
        "extended_hours": extended_hours,
        "symbol": symbol,
        "qty": qty,
        "filled_qty": filled_qty,
        "side": side,
        "type": order_type,
    }
    if stop_price is not None:
        payload["stop_price"] = stop_price
    if limit_price is not None:
        payload["limit_price"] = limit_price
    return Order.model_validate(payload)


def api_update(
    order: Order, event: str = "fill", at: datetime = NOW, position_qty: float | None = 10.0
) -> TradeUpdate:
    return TradeUpdate.model_validate(
        {
            "event": event,
            "execution_id": str(uuid4()),
            "order": order.model_dump(),
            "timestamp": at.isoformat(),
            "position_qty": position_qty,
        }
    )


def api_quote(bid: str = "99.505", ask: str = "99.51", at: datetime = NOW) -> Quote:
    return Quote(
        "AAPL",
        {
            "t": at.isoformat(),
            "bp": float(bid),
            "bs": 10,
            "ap": float(ask),
            "as": 10,
        },
    )


def api_trade(price: str = "99.40", at: datetime = NOW) -> Trade:
    return Trade(
        "AAPL",
        {
            "t": at.isoformat(),
            "p": float(price),
            "s": 100,
        },
    )


def _symbols(value: str | Sequence[str]) -> tuple[str, ...]:
    return (value,) if isinstance(value, str) else tuple(value)


class FakeDataClient:
    def __init__(self, *, quote: Quote | None = None, trades: Sequence[Trade] = ()) -> None:
        self.quote = quote
        self.trades = list(trades)
        self.requests: list[tuple[str, DataFeed | None, tuple[str, ...]]] = []

    def get_stock_latest_quote(self, request: StockLatestQuoteRequest) -> dict[str, Quote]:
        symbols = _symbols(request.symbol_or_symbols)
        self.requests.append(("quote", request.feed, symbols))
        if self.quote is None or self.quote.symbol not in symbols:
            return {}
        return {self.quote.symbol: self.quote}

    def get_stock_latest_trade(self, request: StockLatestTradeRequest) -> dict[str, Trade]:
        symbols = _symbols(request.symbol_or_symbols)
        self.requests.append(("trade", request.feed, symbols))
        if not self.trades or self.trades[0].symbol not in symbols:
            return {}
        trade = self.trades.pop(0)
        return {trade.symbol: trade}


class FakeClient:
    def __init__(self) -> None:
        self.account = api_account()
        self.positions: list[Position] = []
        self.orders: list[Order] = []
        self.submitted: list[TrailingStopOrderRequest | LimitOrderRequest] = []
        self.cancelled: list[str] = []

    def get_account(self) -> TradeAccount:
        return self.account

    def get_all_positions(self) -> list[Position]:
        return list(self.positions)

    def get_orders(self, filter=None) -> list[Order]:
        return list(self.orders)

    def get_order_by_client_id(self, client_id: str) -> Order:
        raise AssertionError("the feed proof never resolves a submit identity")

    def submit_order(self, order_data: object) -> object:
        assert isinstance(order_data, (TrailingStopOrderRequest, LimitOrderRequest))
        self.submitted.append(order_data)
        client_order_id = order_data.client_order_id or f"B001-echo-{len(self.submitted)}"
        if isinstance(order_data, LimitOrderRequest):
            echo = api_order(
                client_order_id=client_order_id,
                qty=str(int(order_data.qty or 0)),
                order_type="limit",
                limit_price=str(order_data.limit_price),
                extended_hours=True,
            )
        else:
            echo = api_order(
                client_order_id=client_order_id,
                qty=str(int(order_data.qty or 0)),
                order_type="trailing_stop",
            )
        self.orders.append(echo)
        return echo

    def cancel_order_by_id(self, order_id: object) -> None:
        self.cancelled.append(str(order_id))
        self.orders = [order for order in self.orders if str(order.id) != str(order_id)]


def protector(
    client: FakeClient, *, feed: str = "none", clock: list[int] | None = None
) -> Protector:
    now = clock if clock is not None else [NOW_NS]
    return Protector(
        client,
        b_account(),
        b_params(),
        now_ns=lambda: now[0],
        feed=feed,
    )


def test_a_fed_breach_cancels_the_trail_and_releases_one_limit() -> None:
    clock = [NOW_NS]
    client = FakeClient()
    client.positions = [api_position("10")]
    client.orders = [api_order(stop_price="99.45")]
    data = FakeDataClient(
        quote=api_quote(),
        trades=[
            api_trade(at=NOW),
            api_trade(at=datetime(2026, 11, 9, 20, 30, 0, 500_000, tzinfo=ET)),
            api_trade(at=datetime(2026, 11, 9, 20, 30, 1, tzinfo=ET)),
        ],
    )
    feed = BMarketDataFeed(data)
    p = protector(client, feed="sip", clock=clock)
    p.reconcile()
    trail = client.orders[0]

    for _ in range(3):
        batch = feed.poll(("AAPL",), "sip")
        for quote in batch.quotes:
            p.on_quote(
                quote.symbol,
                bid=quote.bid,
                ask=quote.ask,
                last=quote.last,
                ts_ns=quote.ts_ns,
            )
        for trade in batch.trades:
            p.on_trade(trade.symbol, trade.price, trade.ts_ns)
        clock[0] += SEC // 2

    assert any("protected=0" in line and "order=none" in line for line in p.states)
    p.handle(api_update(trail, "canceled", NOW, 10))
    assert isinstance(client.submitted[-1], LimitOrderRequest)
    assert "protected=0" in p.states[-1]
    assert "on=none" in p.states[-1]


def test_a_missing_feed_pages_instead_of_staying_silent() -> None:
    client = FakeClient()
    client.positions = [api_position("10")]
    client.orders = [api_order(stop_price="97.50")]
    p = protector(client)
    p.reconcile()
    p.watch()

    assert [page.reason for page in p.pages] == ["outside_rth_feed_silent"]
    assert p.pages[0].symbol == "AAPL"
    assert "protected=0" in p.states[-1]
    assert "feed=none" in p.states[-1]


def test_a_stale_quote_unarms_and_pages_then_a_fresh_quote_rearms() -> None:
    clock = [NOW_NS]
    client = FakeClient()
    client.positions = [api_position("10")]
    client.orders = [api_order(stop_price="97.50")]
    p = protector(client, feed="sip", clock=clock)
    p.reconcile()
    p.on_quote(
        "AAPL",
        bid=Decimal("99.50"),
        ask=Decimal("99.51"),
        last=Decimal("99.50"),
        ts_ns=NOW_NS,
    )
    p.watch()
    assert p.pages == []
    assert "protected=10" in p.states[-1]
    assert "age=0.0s" in p.states[-1]

    clock[0] += 6 * SEC
    p.watch()
    assert [page.reason for page in p.pages] == ["outside_rth_feed_silent"]
    assert "protected=0" in p.states[-1]
    assert "trigger=none" in p.states[-1]
    assert "age=6.0s" in p.states[-1]

    p.on_quote(
        "AAPL",
        bid=Decimal("99.50"),
        ask=Decimal("99.51"),
        last=Decimal("99.50"),
        ts_ns=clock[0],
    )
    p.watch()
    assert [page.reason for page in p.pages] == ["outside_rth_feed_silent"]
    assert "protected=10" in p.states[-1]
    assert "age=0.0s" in p.states[-1]


def test_pre_and_post_poll_sip_and_the_overnight_polls_boats() -> None:
    assert feed_for(Session.PRE) == "sip"
    assert feed_for(Session.POST) == "sip"
    assert feed_for(Session.OVERNIGHT) == "boats"
    assert feed_for(Session.RTH) is None
    assert feed_for(Session.CLOSED) is None

    data = FakeDataClient(quote=api_quote(), trades=[api_trade()])
    feed = BMarketDataFeed(data)
    feed.poll(("AAPL",), "sip")
    feed.poll(("AAPL",), "boats")

    assert data.requests[0] == ("quote", DataFeed.SIP, ("AAPL",))
    assert data.requests[1] == ("trade", DataFeed.SIP, ("AAPL",))
    assert data.requests[2] == ("quote", DataFeed.BOATS, ("AAPL",))
    assert data.requests[3] == ("trade", DataFeed.BOATS, ("AAPL",))


def test_the_same_latest_trade_is_counted_once() -> None:
    data = FakeDataClient(quote=api_quote(), trades=[api_trade()])
    feed = BMarketDataFeed(data)

    first = feed.poll(("AAPL",), "sip")
    second = feed.poll(("AAPL",), "sip")

    assert len(first.quotes) == 1
    assert len(first.trades) == 1
    assert second.quotes == ()
    assert second.trades == ()


def test_the_poll_interval_must_be_shorter_than_the_silence_bound() -> None:
    with pytest.raises(ValueError, match="feed_poll_interval_s"):
        BParameters(
            native_trail_fraction=Decimal("0.025"),
            reconcile_interval_s=Decimal("10"),
            feed_poll_interval_s=Decimal("5"),
            feed_silence_s=Decimal("5"),
        )


def test_the_stream_startup_line_names_the_live_feed(monkeypatch) -> None:
    async def no_connect(self) -> None:
        return None

    monkeypatch.setattr(TradingStream, "_start_ws", no_connect)
    client = FakeClient()
    client.positions = [api_position("10")]
    client.orders = [api_order(stop_price="97.50")]
    data = FakeDataClient(quote=api_quote())
    lines: list[str] = []
    stream = ProtectorStream(
        client,
        b_account(),
        b_params(),
        api_key="test-key",
        secret_key="test-secret",  # noqa: S106 - fixture, never a real key
        now_ns=lambda: NOW_NS,
        on_state=lines.append,
        data_client=data,
    )
    asyncio.run(stream._start_ws())

    assert len(lines) == 1
    assert "feed=boats" in lines[0]
    assert "protected=10" in lines[0]
    assert "age=0.0s" in lines[0]
