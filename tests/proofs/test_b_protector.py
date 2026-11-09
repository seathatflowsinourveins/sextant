"""B's owner-fill protector against mocked alpaca-py models and client responses (clean B PR-1)."""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.models import Order, Position, TradeAccount, TradeUpdate
from alpaca.trading.requests import TrailingStopOrderRequest
from alpaca.trading.stream import TradingStream

from sextant.paper.b_protector import (
    BParameters,
    Protector,
    ProtectorRefusal,
    ProtectorStream,
    load_b_parameters,
)
from sextant.paper.config import PaperAccount
from sextant.paper.sessions import Session, session_at

ROOT = Path(__file__).parents[2]
ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 9, 10, 0, tzinfo=ET)
NOW_NS = int(NOW.timestamp()) * 1_000_000_000


def ns(local: datetime) -> int:
    return int(local.timestamp()) * 1_000_000_000


def b_account() -> PaperAccount:
    return PaperAccount(
        lane="alpaca-paper-b",
        account_id="paper-fixture",
        client_id="ALPACA-B",
        namespace="B001",
        sessions=(Session.RTH,),
    )


def b_params(**overrides: Decimal) -> BParameters:
    facts = {
        "native_trail_fraction": Decimal("0.025"),
        "claim_max_latency_s": Decimal("11"),
    }
    return BParameters(**(facts | overrides))


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
    client_order_id: str = "owner-buy-1",
    symbol: str = "AAPL",
    qty: str = "10",
    filled_qty: str = "0",
    side: str = "buy",
    order_type: str = "limit",
    status: str = "new",
    trail_percent: str | None = None,
) -> Order:
    payload = {
        "id": str(uuid4()),
        "client_order_id": client_order_id,
        "created_at": "2026-11-09T14:59:00Z",
        "updated_at": "2026-11-09T14:59:00Z",
        "submitted_at": "2026-11-09T14:59:00Z",
        "order_class": "simple",
        "time_in_force": "gtc",
        "status": status,
        "extended_hours": False,
        "symbol": symbol,
        "qty": qty,
        "filled_qty": filled_qty,
        "side": side,
        "type": order_type,
    }
    if trail_percent is not None:
        payload["trail_percent"] = trail_percent
    return Order.model_validate(payload)


def api_update(
    order: Order,
    *,
    event: str = "fill",
    at: datetime | None = None,
    position_qty: float = 10.0,
) -> TradeUpdate:
    return TradeUpdate.model_validate(
        {
            "event": event,
            "order": order.model_dump(mode="json"),
            "timestamp": (at or NOW - timedelta(seconds=1)).isoformat(),
            "position_qty": position_qty,
            "price": 100.5,
            "qty": 10.0,
        }
    )


class FakeTradingClient:
    """Records order writes and serves the configured alpaca-py models."""

    def __init__(self, *, account=None, positions=(), orders=()):
        self.account = account or api_account()
        self.positions = list(positions)
        self.orders = list(orders)
        self.calls: list[str] = []
        self.submitted: list[TrailingStopOrderRequest] = []
        self.cancelled: list[str] = []
        self.replaced: list[object] = []

    def get_account(self) -> TradeAccount:
        self.calls.append("get_account")
        return self.account

    def get_all_positions(self) -> list[Position]:
        self.calls.append("get_all_positions")
        return list(self.positions)

    def get_orders(self, filter=None) -> list[Order]:
        self.calls.append("get_orders")
        return list(self.orders)

    def submit_order(self, order_data):
        self.calls.append("submit_order")
        assert isinstance(order_data, TrailingStopOrderRequest)
        assert order_data.client_order_id is not None
        assert order_data.symbol is not None
        self.submitted.append(order_data)
        order = api_order(
            client_order_id=order_data.client_order_id,
            symbol=order_data.symbol,
            qty=str(order_data.qty),
            side="sell",
            order_type="trailing_stop",
            status="new",
            trail_percent=str(order_data.trail_percent),
        )
        self.orders.append(order)
        return order

    def cancel_order_by_id(self, order_id) -> None:
        self.calls.append("cancel_order_by_id")
        self.cancelled.append(str(order_id))
        self.orders = [o for o in self.orders if str(o.id) != str(order_id)]

    def replace_order_by_id(self, *args, **kwargs):
        self.replaced.append((args, kwargs))
        raise AssertionError("the protector must never replace an order")


def protector(client, *, now=NOW_NS, account=None, params=None) -> Protector:
    return Protector(
        client,
        account or b_account(),
        params or b_params(),
        now_ns=lambda: now,
    )


def test_the_registry_carries_b_the_reviewed_trail_and_claim_latency(tmp_path):
    path = ROOT / "lanes/paper/b-parameters.json"
    params = load_b_parameters(path)
    assert (
        params.native_trail_fraction
        == BParameters(Decimal("0.025"), Decimal("11")).native_trail_fraction
    )
    assert (
        params.claim_max_latency_s
        == BParameters(Decimal("0.025"), Decimal("11")).claim_max_latency_s
    )

    rows = json.loads(path.read_text())
    assert {row["name"] for row in rows} == {"native_trail_fraction", "claim_max_latency_s"}
    assert all(row["calibration_state"] == "UNCALIBRATED" for row in rows)
    assert all(row["source"] for row in rows)

    with pytest.raises(ValueError):
        BParameters(Decimal("0.03"), Decimal("11"))
    with pytest.raises(ValueError):
        BParameters(Decimal("0.025"), Decimal("0"))

    incomplete = tmp_path / "b-parameters.json"
    incomplete.write_text(json.dumps([rows[0]]))
    with pytest.raises(ValueError):
        load_b_parameters(incomplete)
    with pytest.raises(ValueError):
        load_b_parameters(tmp_path / "missing.json")


def test_an_owner_fill_produces_exactly_one_native_trail_for_whole_shares():
    client = FakeTradingClient(positions=[api_position("10")])
    p = protector(client)
    p.bind()
    p.handle(api_update(api_order(client_order_id="owner-buy-1"), event="fill", position_qty=10.0))

    assert len(client.submitted) == 1
    request = client.submitted[0]
    assert isinstance(request, TrailingStopOrderRequest)
    assert (request.symbol, request.qty) == ("AAPL", 10)
    assert request.side is OrderSide.SELL
    assert request.time_in_force is TimeInForce.GTC
    assert request.trail_percent == 2.5
    assert request.extended_hours is None
    assert request.client_order_id is not None
    assert request.client_order_id.startswith("B001-trail-")

    p.reconcile()
    assert len(client.submitted) == 1


def test_owner_orders_are_never_cancelled_replaced_or_resized():
    owner = api_order(client_order_id="owner-working-1", side="sell", qty="4")
    client = FakeTradingClient(positions=[api_position("10")], orders=[owner])
    p = protector(client)
    p.bind()
    p.reconcile()

    assert client.cancelled == []
    assert client.replaced == []
    assert str(owner.id) not in client.cancelled

    p.handle(api_update(owner, event="canceled", position_qty=10.0))
    assert client.cancelled == []
    assert client.replaced == []


def test_a_slot_one_lane_and_a_foreign_account_number_refuse_before_any_order():
    client = FakeTradingClient(positions=[api_position("10")])
    with pytest.raises(ProtectorRefusal):
        Protector(client, replace(b_account(), lane="alpaca-paper-a"), b_params())
    assert client.calls == []
    assert client.submitted == []

    p = protector(client, account=b_account(), params=b_params())
    client.account = api_account("another-paper-account")
    with pytest.raises(ProtectorRefusal):
        p.bind()
    assert p.pages[-1].reason == "account_number_mismatch"
    assert client.submitted == []
    assert "get_all_positions" not in client.calls


def test_a_reconnect_and_outside_rth_page_instead_of_submitting(monkeypatch):
    async def no_connect(self) -> None:
        return None

    monkeypatch.setattr(TradingStream, "_start_ws", no_connect)
    client = FakeTradingClient(positions=[api_position("10")])
    stream = ProtectorStream(
        client,
        b_account(),
        b_params(),
        api_key="test-key",
        secret_key="test-secret",  # noqa: S106 - fixture, never a real key
        now_ns=lambda: NOW_NS,
    )
    asyncio.run(stream._start_ws())
    assert "get_all_positions" in client.calls
    assert len(client.submitted) == 1

    after_hours = datetime(2026, 11, 9, 20, 30, tzinfo=ET)
    assert session_at(ns(after_hours)) is not Session.RTH
    client = FakeTradingClient(positions=[api_position("10")])
    p = protector(client, now=ns(after_hours))
    p.bind()
    p.handle(
        api_update(
            api_order(client_order_id="owner-buy-after-hours"),
            event="fill",
            at=after_hours - timedelta(seconds=1),
            position_qty=10.0,
        )
    )
    assert client.submitted == []
    assert [page.reason for page in p.pages] == ["unprotected_outside_rth_until_pr2"]


def test_a_house_trail_that_would_oversell_is_cancelled_and_pages():
    house = api_order(
        client_order_id="B001-trail-AAPL-old",
        side="sell",
        qty="10",
        order_type="trailing_stop",
        trail_percent="2.5",
    )
    client = FakeTradingClient(positions=[api_position("9")], orders=[house])
    p = protector(client)
    p.bind()
    p.reconcile()

    assert client.cancelled == [str(house.id)]
    assert client.submitted == []
    assert "quantity_mismatch" in [page.reason for page in p.pages]


def test_a_fractional_position_protects_whole_shares_and_pages_the_remainder():
    client = FakeTradingClient(positions=[api_position("10.5")])
    p = protector(client)
    p.bind()
    p.reconcile()

    assert [request.qty for request in client.submitted] == [10]
    assert "fractional_custody_unverified" in [page.reason for page in p.pages]


def test_an_owner_add_pages_and_leaves_the_house_trail_alone():
    house = api_order(
        client_order_id="B001-trail-AAPL-old",
        side="sell",
        qty="10",
        order_type="trailing_stop",
        trail_percent="2.5",
    )
    client = FakeTradingClient(positions=[api_position("12")], orders=[house])
    p = protector(client)
    p.bind()
    p.reconcile()

    assert client.cancelled == []
    assert client.submitted == []
    assert "owner_add_unprotected" in [page.reason for page in p.pages]


def test_a_late_or_invalid_claim_clock_never_claims():
    client = FakeTradingClient(positions=[api_position("10")])
    p = protector(client)
    p.bind()
    p.handle(
        api_update(
            api_order(client_order_id="owner-late"),
            event="fill",
            at=NOW - timedelta(seconds=12),
            position_qty=10.0,
        )
    )
    assert client.submitted == []
    assert "claim_too_late" in [page.reason for page in p.pages]

    p.handle(
        api_update(
            api_order(client_order_id="owner-future"),
            event="fill",
            at=NOW + timedelta(seconds=1),
            position_qty=10.0,
        )
    )
    assert client.submitted == []
    assert "invalid_claim_clock" in [page.reason for page in p.pages]


def test_a_lost_house_trail_pages_and_rearms():
    lost = api_order(
        client_order_id="B001-trail-AAPL-lost",
        side="sell",
        qty="10",
        order_type="trailing_stop",
        trail_percent="2.5",
    )
    client = FakeTradingClient(positions=[api_position("10")])
    p = protector(client)
    p.bind()
    p.handle(api_update(lost, event="canceled", position_qty=10.0))

    assert "house_exit_lost" in [page.reason for page in p.pages]
    assert len(client.submitted) == 1


def test_a_flat_position_cancels_the_house_trail_and_never_an_owner_order():
    house = api_order(
        client_order_id="B001-trail-AAPL-flat",
        side="sell",
        qty="10",
        order_type="trailing_stop",
        trail_percent="2.5",
    )
    owner = api_order(client_order_id="owner-working-2", side="buy", qty="5")
    client = FakeTradingClient(positions=[], orders=[house, owner])
    p = protector(client)
    p.bind()
    p.reconcile()

    assert client.cancelled == [str(house.id)]
    assert str(owner.id) not in client.cancelled
    assert client.submitted == []
