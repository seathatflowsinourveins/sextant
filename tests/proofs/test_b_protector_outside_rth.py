"""B's outside-RTH path: emulated trigger, one release, and the extended-hours LIMIT.

Alpaca's native trailing stop rests outside regular hours but does not trigger, so B emulates
the trigger from quotes and releases one marketable LIMIT after a persistent run of eligible
trades (``docs/design.md`` X4; Alpaca orders page read 2026-11-09).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from alpaca.trading.models import Order, Position, TradeAccount, TradeUpdate
from alpaca.trading.requests import LimitOrderRequest, TrailingStopOrderRequest

from sextant.paper.b_protector import BParameters, Protector
from sextant.paper.config import PaperAccount
from sextant.paper.sessions import Session

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 9, 20, 30, tzinfo=ET)  # after-hours, outside the regular session
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
    return BParameters(native_trail_fraction=Decimal("0.025"), claim_max_latency_s=Decimal("11"))


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


class FakeClient:
    def __init__(self) -> None:
        self.account = api_account()
        self.positions: list[Position] = []
        self.orders: list[Order] = []
        self.submitted: list[TrailingStopOrderRequest | LimitOrderRequest] = []
        self.cancelled: list[str] = []
        self.calls: list[str] = []

    def get_account(self) -> TradeAccount:
        self.calls.append("get_account")
        return self.account

    def get_all_positions(self) -> list[Position]:
        self.calls.append("get_all_positions")
        return list(self.positions)

    def get_orders(self, filter=None) -> list[Order]:
        self.calls.append("get_orders")
        return list(self.orders)

    def submit_order(self, order_data: object) -> object:
        self.calls.append("submit_order")
        assert isinstance(order_data, (TrailingStopOrderRequest, LimitOrderRequest))
        self.submitted.append(order_data)
        return order_data

    def cancel_order_by_id(self, order_id: object) -> None:
        self.calls.append("cancel_order_by_id")
        self.cancelled.append(str(order_id))
        self.orders = [order for order in self.orders if str(order.id) != str(order_id)]


def protector(client: FakeClient) -> Protector:
    return Protector(client, b_account(), b_params(), now_ns=lambda: NOW_NS)


def test_outside_rth_arms_the_native_trail_instead_of_paging() -> None:
    client = FakeClient()
    client.positions = [api_position("10")]
    p = protector(client)
    p.reconcile()
    assert p.pages == []
    assert len(client.submitted) == 1
    assert isinstance(client.submitted[0], TrailingStopOrderRequest)


def test_outside_rth_adopts_the_resting_trails_stop_price() -> None:
    client = FakeClient()
    client.positions = [api_position("10")]
    client.orders = [api_order(stop_price="97.50")]
    p = protector(client)
    p.reconcile()
    assert p.pages == []
    assert client.submitted == []
    assert p.emulated_trigger("AAPL") == Decimal("97.50")


def test_a_persistent_breach_cancels_the_trail_then_releases_one_extended_hours_limit() -> None:
    client = FakeClient()
    client.positions = [api_position("10")]
    trail = api_order(stop_price="99.45")
    client.orders = [trail]
    p = protector(client)
    p.reconcile()
    p.on_quote(
        "AAPL", bid=Decimal("99.505"), ask=Decimal("99.51"), last=Decimal("99.51"), ts_ns=NOW_NS
    )
    assert p.on_trade("AAPL", Decimal("99.40"), NOW_NS) is False
    assert p.on_trade("AAPL", Decimal("99.40"), NOW_NS + SEC // 2) is False
    assert p.on_trade("AAPL", Decimal("99.40"), NOW_NS + SEC) is True
    assert client.cancelled == [str(trail.id)]
    assert client.submitted == []  # the LIMIT waits for the terminal cancellation
    p.handle(api_update(trail, event="canceled"))
    assert len(client.submitted) == 1
    request = client.submitted[0]
    assert isinstance(request, LimitOrderRequest)
    assert request.side is not None and request.side.value == "sell"
    assert request.time_in_force is not None and request.time_in_force.value == "gtc"
    assert request.extended_hours is True
    assert Decimal(str(request.limit_price)) == Decimal("99.50")
    assert Decimal(str(request.qty)) == Decimal("10")
    assert p.pages == []


def test_a_breach_without_a_fresh_quote_pages_and_keeps_the_trail() -> None:
    client = FakeClient()
    client.positions = [api_position("10")]
    client.orders = [api_order(stop_price="99.45")]
    p = protector(client)
    p.reconcile()
    p.on_quote(
        "AAPL",
        bid=Decimal("99.50"),
        ask=Decimal("99.52"),
        last=Decimal("99.51"),
        ts_ns=NOW_NS - 3 * SEC,
    )
    assert p.on_trade("AAPL", Decimal("99.40"), NOW_NS) is False
    assert p.on_trade("AAPL", Decimal("99.40"), NOW_NS + SEC // 2) is False
    assert p.on_trade("AAPL", Decimal("99.40"), NOW_NS + SEC) is True
    assert client.cancelled == []
    assert [page.reason for page in p.pages].count("outside_rth_release_unpriced") == 1
    assert client.submitted == []


def test_a_breach_without_a_resting_trail_pages() -> None:
    client = FakeClient()
    client.positions = [api_position("10")]
    p = protector(client)
    p.reconcile()  # arms a trail, but the broker has not echoed it yet
    p.on_quote(
        "AAPL", bid=Decimal("99.50"), ask=Decimal("99.52"), last=Decimal("99.51"), ts_ns=NOW_NS
    )
    for at in (NOW_NS, NOW_NS + SEC // 2, NOW_NS + SEC):
        p.on_trade("AAPL", Decimal("96.90"), at)
    assert [page.reason for page in p.pages] == ["outside_rth_no_trail_at_breach"]


def test_an_owner_add_outside_rth_resizes_the_trail_instead_of_paging() -> None:
    client = FakeClient()
    client.positions = [api_position("12")]
    client.orders = [api_order(qty="10", stop_price="97.50")]
    p = protector(client)
    p.reconcile()
    assert len(client.cancelled) == 1
    assert len(client.submitted) == 1
    assert Decimal(str(client.submitted[0].qty)) == Decimal("12")
    assert p.pages == []


def test_closed_session_never_writes() -> None:
    saturday = datetime(2026, 11, 7, 12, 0, tzinfo=ET)
    client = FakeClient()
    client.positions = [api_position("10")]
    p = Protector(client, b_account(), b_params(), now_ns=lambda: int(saturday.timestamp()) * SEC)
    p.reconcile()
    assert client.submitted == []
    assert [page.reason for page in p.pages] == ["market_closed"]


def test_a_reconcile_while_the_cancel_is_pending_does_not_rearm_the_trail() -> None:
    client = FakeClient()
    client.positions = [api_position("10")]
    trail = api_order(stop_price="99.45")
    client.orders = [trail]
    p = protector(client)
    p.reconcile()
    p.on_quote(
        "AAPL", bid=Decimal("99.505"), ask=Decimal("99.51"), last=Decimal("99.51"), ts_ns=NOW_NS
    )
    assert p.on_trade("AAPL", Decimal("99.40"), NOW_NS) is False
    assert p.on_trade("AAPL", Decimal("99.40"), NOW_NS + SEC // 2) is False
    assert p.on_trade("AAPL", Decimal("99.40"), NOW_NS + SEC) is True
    assert client.cancelled == [str(trail.id)]

    # The broker has not delivered the terminal cancellation yet. Reconciling now must
    # wait for it rather than arm a second trail beside the release.
    p.reconcile()

    assert client.submitted == []
    assert p.pages == []
