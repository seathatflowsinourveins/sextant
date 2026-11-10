"""B's outside-RTH path: emulated trigger, one release, and the extended-hours LIMIT.

Alpaca's native trailing stop rests outside regular hours but does not trigger, so B emulates
the trigger from quotes and releases one marketable LIMIT after a persistent run of eligible
trades (``docs/design.md``:31 and ``docs/adr/0005-exit-engine.md`` X4;
Alpaca orders page read 2026-11-09).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.models import Order, Position, TradeAccount, TradeUpdate
from alpaca.trading.requests import LimitOrderRequest, TrailingStopOrderRequest

from sextant.paper.b_feed import QuoteObservation
from sextant.paper.b_protector import BParameters, Protector
from sextant.paper.config import PaperAccount
from sextant.paper.sessions import Session

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 9, 20, 30, tzinfo=ET)  # after-hours, outside the regular session
NOW_NS = int(NOW.timestamp()) * 1_000_000_000
SEC = 1_000_000_000
POST = datetime(2026, 11, 9, 18, 10, tzinfo=ET)  # the incident's post-session start
POST_NS = int(POST.timestamp()) * SEC
ENTRY = datetime(2026, 11, 9, 12, 47, 17, 479764, tzinfo=ET)  # the broker's filled entry
ENTRY_NS = int(ENTRY.timestamp()) * SEC + ENTRY.microsecond * 1_000


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
    filled_at: str | None = None,
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
    if filled_at is not None:
        payload["filled_at"] = filled_at
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
        self.closed_orders: list[Order] = []
        self.submitted: list[TrailingStopOrderRequest | LimitOrderRequest] = []
        self.echoes: list[Order] = []
        self.cancelled: list[str] = []
        self.calls: list[str] = []
        self.fail_limits = False

    def get_account(self) -> TradeAccount:
        self.calls.append("get_account")
        return self.account

    def get_all_positions(self) -> list[Position]:
        self.calls.append("get_all_positions")
        return list(self.positions)

    def get_orders(self, filter=None) -> list[Order]:
        self.calls.append("get_orders")
        if getattr(filter, "status", None) == QueryOrderStatus.CLOSED:
            return list(self.closed_orders)
        return list(self.orders)

    def get_order_by_client_id(self, client_id: str) -> Order:
        raise AssertionError("the outside-RTH proof never resolves a submit identity")

    def submit_order(self, order_data: object) -> object:
        self.calls.append("submit_order")
        assert isinstance(order_data, (TrailingStopOrderRequest, LimitOrderRequest))
        if self.fail_limits and isinstance(order_data, LimitOrderRequest):
            raise RuntimeError("the broker refused the limit")
        self.submitted.append(order_data)
        client_order_id = order_data.client_order_id or f"B001-echo-{len(self.echoes)}"
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
        self.echoes.append(echo)
        return echo

    def cancel_order_by_id(self, order_id: object) -> None:
        self.calls.append("cancel_order_by_id")
        self.cancelled.append(str(order_id))
        self.orders = [order for order in self.orders if str(order.id) != str(order_id)]


class FakeHistory:
    def __init__(
        self,
        observations: Sequence[QuoteObservation] = (),
        error: Exception | None = None,
    ) -> None:
        self.observations = tuple(observations)
        self.error = error
        self.requests: list[tuple[str, int, int, str]] = []

    def quotes(
        self, symbol: str, start_ns: int, end_ns: int, feed: str
    ) -> tuple[QuoteObservation, ...]:
        self.requests.append((symbol, start_ns, end_ns, feed))
        if self.error is not None:
            raise self.error
        return self.observations


def protector(
    client: FakeClient,
    *,
    history: FakeHistory | None = None,
    now_ns: int = NOW_NS,
) -> Protector:
    return Protector(
        client,
        b_account(),
        b_params(),
        now_ns=lambda: now_ns,
        feed="sip",
        history=history,
    )


def drive_breach(p: Protector, *, bid: str = "99.505", trade: str = "99.40") -> None:
    """Feed one quote and three eligible prints that complete the persistent breach."""

    p.on_quote(
        "AAPL",
        bid=Decimal(bid),
        ask=Decimal(bid) + Decimal("0.005"),
        last=Decimal(bid) + Decimal("0.005"),
        ts_ns=NOW_NS,
    )
    p.note_poll(NOW_NS)
    assert p.on_trade("AAPL", Decimal(trade), NOW_NS) is False
    assert p.on_trade("AAPL", Decimal(trade), NOW_NS + SEC // 2) is False
    assert p.on_trade("AAPL", Decimal(trade), NOW_NS + SEC) is True


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
    p.note_poll(NOW_NS)
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


def test_a_breach_after_the_protector_arms_its_own_trail_releases_a_limit() -> None:
    client = FakeClient()
    client.positions = [api_position("10")]
    p = protector(client)
    p.reconcile()
    assert len(client.submitted) == 1
    assert isinstance(client.submitted[0], TrailingStopOrderRequest)
    trail = client.echoes[-1]
    drive_breach(p, trade="96.90")
    assert client.cancelled == [str(trail.id)]
    assert client.submitted == [client.submitted[0]]  # the LIMIT waits for the terminal event
    p.handle(api_update(trail, event="canceled"))
    limits = [order for order in client.submitted if isinstance(order, LimitOrderRequest)]
    assert len(limits) == 1
    assert Decimal(str(limits[0].qty)) == Decimal("10")
    assert Decimal(str(limits[0].limit_price)) == Decimal("99.50")
    assert p.pages == []


def test_an_owner_add_outside_rth_resizes_after_the_terminal_cancel() -> None:
    client = FakeClient()
    client.positions = [api_position("12")]
    trail = api_order(qty="10", stop_price="97.50")
    client.orders = [trail]
    p = protector(client)
    p.reconcile()
    assert client.cancelled == [str(trail.id)]
    assert client.submitted == []  # the old trail can still fill until its terminal event
    p.handle(api_update(trail, event="canceled"))
    assert len(client.submitted) == 1
    assert isinstance(client.submitted[0], TrailingStopOrderRequest)
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
    p.note_poll(NOW_NS)
    assert p.on_trade("AAPL", Decimal("99.40"), NOW_NS) is False
    assert p.on_trade("AAPL", Decimal("99.40"), NOW_NS + SEC // 2) is False
    assert p.on_trade("AAPL", Decimal("99.40"), NOW_NS + SEC) is True
    assert client.cancelled == [str(trail.id)]

    # The broker has not delivered the terminal cancellation yet. Reconciling now must
    # wait for it rather than arm a second trail beside the release.
    p.reconcile()

    assert client.submitted == []
    assert p.pages == []


def test_the_released_limit_price_crosses_to_the_sdk_without_a_float(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    real_request = LimitOrderRequest

    def spy(**kwargs: object) -> LimitOrderRequest:
        captured.update(kwargs)
        return real_request(**kwargs)

    monkeypatch.setattr("sextant.paper.b_protector.LimitOrderRequest", spy)
    client = FakeClient()
    client.positions = [api_position("10")]
    trail = api_order(stop_price="99.45")
    client.orders = [trail]
    p = protector(client)
    p.reconcile()
    drive_breach(p)
    p.handle(api_update(trail, event="canceled"))

    assert isinstance(captured["limit_price"], str)
    assert Decimal(captured["limit_price"]) == Decimal("99.50")


def test_the_released_limit_uses_the_fresh_unreserved_residual() -> None:
    client = FakeClient()
    client.positions = [api_position("10")]
    trail = api_order(stop_price="99.45")
    client.orders = [trail]
    p = protector(client)
    p.reconcile()
    drive_breach(p)
    # The owner sells four shares while the cancellation is in flight; reconcile refreshes
    # the position, so the release may sell only the six shares still unreserved.
    client.positions = [api_position("6")]
    p.reconcile()
    p.handle(api_update(trail, event="canceled"))
    limits = [order for order in client.submitted if isinstance(order, LimitOrderRequest)]
    assert len(limits) == 1
    assert Decimal(str(limits[0].qty)) == Decimal("6")
    assert p.pages == []


def test_a_failed_release_submit_rearms_the_emulation_state() -> None:
    client = FakeClient()
    client.positions = [api_position("10")]
    trail = api_order(stop_price="99.45")
    client.orders = [trail]
    p = protector(client)
    p.reconcile()
    drive_breach(p)
    client.fail_limits = True
    p.handle(api_update(trail, event="canceled"))
    assert [page.reason for page in p.pages] == ["outside_limit_submit_failed"]

    # The failure re-armed the state, so the next quote can move the trigger again.
    moved = p.on_quote(
        "AAPL",
        bid=Decimal("110.00"),
        ask=Decimal("110.02"),
        last=Decimal("110.01"),
        ts_ns=NOW_NS + 2 * SEC,
    )
    assert moved == Decimal("107.25")


def test_a_delayed_cancel_for_another_trail_keeps_the_pending_release() -> None:
    client = FakeClient()
    client.positions = [api_position("10")]
    trail = api_order(stop_price="99.45")
    earlier = api_order(client_order_id="B001-trail-earlier", stop_price="99.00")
    client.orders = [trail]
    p = protector(client)
    p.reconcile()
    drive_breach(p)
    # A resize's trail cancels late; its terminal event must not drop the breach's pending
    # release for the trail that is actually resting.
    p.handle(api_update(earlier, event="canceled"))
    assert client.submitted == []
    p.handle(api_update(trail, event="canceled"))
    limits = [order for order in client.submitted if isinstance(order, LimitOrderRequest)]
    assert len(limits) == 1
    assert Decimal(str(limits[0].qty)) == Decimal("10")


def test_the_release_price_is_refreshed_when_the_cancellation_completes() -> None:
    clock = {"ns": NOW_NS}
    client = FakeClient()
    client.positions = [api_position("10")]
    trail = api_order(stop_price="99.45")
    client.orders = [trail]
    p = Protector(client, b_account(), b_params(), now_ns=lambda: clock["ns"], feed="sip")
    p.reconcile()
    drive_breach(p)
    clock["ns"] = NOW_NS + SEC
    p.on_quote(
        "AAPL",
        bid=Decimal("98.00"),
        ask=Decimal("98.02"),
        last=Decimal("98.01"),
        ts_ns=clock["ns"],
    )
    p.note_poll(clock["ns"])
    p.handle(api_update(trail, event="canceled"))
    limits = [order for order in client.submitted if isinstance(order, LimitOrderRequest)]
    assert len(limits) == 1
    assert Decimal(str(limits[0].limit_price)) == Decimal("98.00")


def test_a_cancelled_released_limit_rearms_the_outside_emulation() -> None:
    client = FakeClient()
    client.positions = [api_position("10")]
    trail = api_order(stop_price="99.45")
    client.orders = [trail]
    p = protector(client)
    p.reconcile()
    drive_breach(p)
    p.handle(api_update(trail, event="canceled"))
    limit = client.submitted[-1]
    assert isinstance(limit, LimitOrderRequest)
    released = client.echoes[-1]
    client.orders = [released]

    # Two more shares arrive, so the released ten-share LIMIT no longer covers the
    # position; the outside resize cancels it and re-arms the native trail.
    client.positions = [api_position("12")]
    p.reconcile()
    assert client.cancelled[-1] == str(released.id)
    assert [type(order) for order in client.submitted] == [LimitOrderRequest]
    p.handle(api_update(released, event="canceled"))
    trails = [order for order in client.submitted if isinstance(order, TrailingStopOrderRequest)]
    assert len(trails) == 1
    assert Decimal(str(trails[0].qty)) == Decimal("12")

    # The replacement trail rests outside RTH, so the emulated trigger must still
    # accept quotes; otherwise the position has no active exit.
    moved = p.on_quote(
        "AAPL",
        bid=Decimal("110.00"),
        ask=Decimal("110.02"),
        last=Decimal("110.01"),
        ts_ns=NOW_NS + 2 * SEC,
    )
    assert moved == Decimal("107.25")


def test_the_0930_handover_snapshot_submits_only_the_released_limit() -> None:
    clock = {
        "ns": int(datetime(2026, 11, 9, 9, 29, 58, 500000, tzinfo=ET).timestamp()) * 1_000_000_000
    }
    client = FakeClient()
    client.positions = [api_position("10")]
    trail = api_order(stop_price="99.45")
    client.orders = [trail]
    p = Protector(client, b_account(), b_params(), now_ns=lambda: clock["ns"], feed="sip")
    p.reconcile()

    p.on_quote(
        "AAPL",
        bid=Decimal("99.505"),
        ask=Decimal("99.510"),
        last=Decimal("99.510"),
        ts_ns=clock["ns"],
    )
    p.note_poll(clock["ns"])
    assert p.on_trade("AAPL", Decimal("99.40"), clock["ns"]) is False
    assert p.on_trade("AAPL", Decimal("99.40"), clock["ns"] + SEC // 2) is False
    assert p.on_trade("AAPL", Decimal("99.40"), clock["ns"] + SEC) is True

    # The trail's terminal cancellation arrives just after the regular session opens.
    # The handover's internal reconcile must not arm a second full-position exit
    # beside the LIMIT it is about to submit.
    clock["ns"] = int(datetime(2026, 11, 9, 9, 30, 0, 300000, tzinfo=ET).timestamp())
    clock["ns"] *= 1_000_000_000
    p.handle(api_update(trail, event="canceled"))

    exits = client.submitted
    assert len(exits) == 1
    assert isinstance(exits[0], LimitOrderRequest)
    assert Decimal(str(exits[0].qty)) == Decimal("10")
    assert Decimal(str(exits[0].limit_price)) == Decimal("99.50")


def ns(at: datetime) -> int:
    return int(at.timestamp()) * SEC + at.microsecond * 1_000


def quote_at(bid: str, at: datetime) -> QuoteObservation:
    value = Decimal(bid)
    return QuoteObservation("AAPL", value, value + Decimal("0.01"), None, ns(at))


def tonight_client() -> FakeClient:
    client = FakeClient()
    client.positions = [api_position("55")]
    client.orders = [api_order(qty="55", stop_price="36.465")]
    client.closed_orders = [
        api_order(
            client_order_id="B001-entry-1",
            qty="55",
            filled_qty="55",
            side="buy",
            order_type="market",
            status="filled",
            filled_at="2026-11-09T17:47:17.479764Z",
        )
    ]
    return client


def tonight_history() -> FakeHistory:
    return FakeHistory(
        [
            quote_at("38.70", datetime(2026, 11, 9, 16, 59, tzinfo=ET)),
            quote_at("36.99", datetime(2026, 11, 9, 12, 47, 18, tzinfo=ET)),
            quote_at("36.60", datetime(2026, 11, 9, 18, 9, tzinfo=ET)),
        ]
    )


def test_a_start_rebuilds_the_after_hours_high_water_mark_from_the_tape() -> None:
    client = tonight_client()
    history = tonight_history()
    p = protector(client, history=history, now_ns=POST_NS)
    p.reconcile()

    assert p.pages == []
    assert client.submitted == []
    assert p.emulated_trigger("AAPL") == Decimal("37.73")
    assert history.requests == [("AAPL", ENTRY_NS, POST_NS, "sip")]

    p.note_poll(POST_NS)
    p.on_quote(
        "AAPL",
        bid=Decimal("36.60"),
        ask=Decimal("36.61"),
        last=None,
        ts_ns=POST_NS,
    )
    p.watch()
    line = next(line for line in reversed(p.states) if "tape=ok" in line)
    assert "trigger=37.73" in line


def test_a_restart_mid_session_keeps_the_rebuilt_level_and_never_lowers_it() -> None:
    client = tonight_client()
    first = protector(client, history=tonight_history(), now_ns=POST_NS)
    first.reconcile()
    assert first.emulated_trigger("AAPL") == Decimal("37.73")

    second = protector(client, history=tonight_history(), now_ns=POST_NS)
    second.reconcile()
    assert second.pages == []
    assert second.emulated_trigger("AAPL") == Decimal("37.73")

    # A later native trail at a lower stop must not lower the rebuilt level.
    client.orders = [api_order(qty="55", stop_price="36.00")]
    second.reconcile()
    assert second.emulated_trigger("AAPL") == Decimal("37.73")


def test_a_session_change_rebuilds_on_the_new_feed_and_never_lowers_the_trigger() -> None:
    client = tonight_client()
    history = tonight_history()
    clock = [POST_NS]
    p = Protector(
        client,
        b_account(),
        b_params(),
        now_ns=lambda: clock[0],
        feed="sip",
        history=history,
    )
    p.reconcile()
    assert p.emulated_trigger("AAPL") == Decimal("37.73")

    overnight = datetime(2026, 11, 9, 20, 5, tzinfo=ET)
    overnight_ns = ns(overnight)
    clock[0] = overnight_ns
    history.observations = (quote_at("37.00", overnight),)
    p.set_feed("boats")
    p.reconcile()

    # The overnight tape's lower high cannot pull the after-hours level down.
    assert p.emulated_trigger("AAPL") == Decimal("37.73")
    assert history.requests[-1] == ("AAPL", ENTRY_NS, overnight_ns, "boats")


def test_an_unreadable_tape_pages_once_and_keeps_the_native_stop() -> None:
    client = tonight_client()
    history = FakeHistory(error=RuntimeError("the tape is down"))
    p = protector(client, history=history, now_ns=POST_NS)
    p.reconcile()

    assert p.emulated_trigger("AAPL") == Decimal("36.465")
    assert [page.reason for page in p.pages] == ["outside_rth_tape_unreadable"]
    p.reconcile()
    assert [page.reason for page in p.pages] == ["outside_rth_tape_unreadable"]

    p.note_poll(POST_NS)
    p.on_quote("AAPL", bid=Decimal("36.60"), ask=Decimal("36.61"), last=None, ts_ns=POST_NS)
    p.watch()
    line = next(line for line in reversed(p.states) if "tape=unreadable" in line)
    assert "trigger=36.465" in line
    assert client.cancelled == []


def test_an_unknown_entry_pages_and_keeps_the_native_stop() -> None:
    client = FakeClient()
    client.positions = [api_position("55")]
    client.orders = [api_order(qty="55", stop_price="36.465")]
    history = tonight_history()
    p = protector(client, history=history, now_ns=POST_NS)
    p.reconcile()

    assert p.emulated_trigger("AAPL") == Decimal("36.465")
    assert [page.reason for page in p.pages] == ["outside_rth_entry_unknown"]
    assert history.requests == []

    p.note_poll(POST_NS)
    p.on_quote("AAPL", bid=Decimal("36.60"), ask=Decimal("36.61"), last=None, ts_ns=POST_NS)
    p.watch()
    line = next(line for line in reversed(p.states) if "tape=entry_unknown" in line)
    assert "trigger=36.465" in line
