"""The Codex review witnesses of #262 at 685695d, carried into the repository.

Each was a failing probe at 685695d (the review's scratch file); here each runs offline
through the pinned alpaca-py 0.44.0 client with urllib3's pool stubbed, or through the
protector's fakes. Two are adapted: the house-LIMIT fixture moved to the post-market
(only outside-hours spans are read, G5), and a page with a continuation token is now
partial (N3), so the one-admission-per-request witness expects that refusal.
"""

from __future__ import annotations

import io
import json
import time
from datetime import datetime
from decimal import Decimal

import pytest
from alpaca.data.historical.stock import StockHistoricalDataClient
from test_b_outside_rth_feed import paced
from test_b_protector_outside_rth import (
    ET,
    POST_NS,
    FakeClient,
    FakeHistory,
    api_order,
    api_position,
    b_account,
    b_params,
    down_window_client,
    down_window_history,
    line_for,
    ns,
    protector,
    quote_at,
    start,
    tonight_client,
)
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.response import HTTPResponse

from sextant.paper.b_feed import BHistoricalTape, TapeShapeError, bound_transport
from sextant.paper.b_protector import Protector
from sextant.paper.b_protector_main import PacedHistoricalDataClient, PacedTradingClient


def quote_payload(at: str = "2026-11-09T21:59:00Z", bid: float = 38.70) -> dict[str, object]:
    return {"t": at, "bp": bid, "ap": bid + 0.01, "bs": 1, "as": 1}


def stub_http(monkeypatch, replies: list[tuple[int, object]]) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def urlopen(pool, method, url, **kwargs):
        calls.append((method, url))
        status, payload = replies[len(calls) - 1]
        return HTTPResponse(
            body=io.BytesIO(json.dumps(payload).encode()),
            headers={"Content-Type": "application/json"},
            status=status,
            preload_content=False,
        )

    monkeypatch.setattr(HTTPSConnectionPool, "urlopen", urlopen)
    return calls


def bounded_tape(pacer) -> BHistoricalTape:
    data = StockHistoricalDataClient("fixture", "fixture")
    bound_transport(data, Decimal("3.05"))
    return BHistoricalTape(PacedHistoricalDataClient(data, pacer), 10_000)  # type: ignore[arg-type]


def test_sdk_rate_limit_retries_cannot_stretch_the_start_read(monkeypatch) -> None:
    # G1: at 685695d two 429s slept the SDK's 3 s retries: 6.005 s on a 3.05 s read, tape=ok.
    calls = stub_http(
        monkeypatch,
        [
            (429, {"code": 42910000, "message": "fixture rate limited"}),
            (429, {"code": 42910000, "message": "fixture rate limited"}),
            (200, {"quotes": {"AAPL": [quote_payload()]}}),
        ],
    )
    manager = protector(tonight_client(), history=bounded_tape(paced(1)), now_ns=POST_NS)
    began = time.monotonic()
    start(manager)
    elapsed = time.monotonic() - began

    assert elapsed <= 3.05, elapsed
    assert len(calls) == 1
    assert "tape=partial" in line_for(manager, POST_NS, "36.60")
    assert [page.reason for page in manager.pages] == ["outside_rth_tape_unreadable"]


def test_one_pacer_admission_is_one_http_request(monkeypatch) -> None:
    # N1: at 685695d the SDK's page loop sent two requests on one admission.
    calls = stub_http(
        monkeypatch,
        [
            (200, {"quotes": {"AAPL": [quote_payload()]}, "next_page_token": "page-two"}),
            (200, {"quotes": {"AAPL": [quote_payload("2026-11-09T22:00:00Z", 38.60)]}}),
        ],
    )
    pacer = paced(1)
    with pytest.raises(TapeShapeError):
        bounded_tape(pacer).quotes("AAPL", POST_NS - 7200 * 1_000_000_000, POST_NS, "sip")
    assert len(calls) == pacer.wire_requests == 1


def test_a_refused_adoption_history_read_is_not_replayed_later() -> None:
    # G6: the refused get_orders stayed queued and ran inside a later drain.
    client = tonight_client()
    pacer = paced(1)
    manager = Protector(
        PacedTradingClient(client, pacer),  # type: ignore[arg-type]
        b_account(),
        b_params(),
        now_ns=lambda: POST_NS,
        history=FakeHistory(),
    )
    manager.rebuild_tapes()
    assert manager._tapes["AAPL"].status == "partial"
    pacer.bucket.tokens = 1
    pacer.drain()
    assert client.calls == ["get_all_positions"]


def test_a_partial_owner_add_cannot_reuse_the_pre_add_high() -> None:
    # G2: a 50-share partial add with no filled_at seeded 11.70 above the 11.50 bid.
    client = FakeClient()
    client.positions = [api_position("150")]
    client.orders = [
        api_order(qty="150", stop_price="11.456", submitted_at="2026-11-09T16:30:01Z"),
        api_order(
            client_order_id="owner-add-partial",
            qty="100",
            filled_qty="50",
            side="buy",
            order_type="limit",
            status="partially_filled",
            submitted_at="2026-11-09T16:20:00Z",
        ).model_copy(update={"updated_at": datetime(2026, 11, 9, 11, 30, tzinfo=ET)}),
    ]
    client.closed_orders = [
        api_order(
            client_order_id="owner-entry",
            qty="100",
            filled_qty="100",
            side="buy",
            order_type="limit",
            status="filled",
            submitted_at="2026-11-09T15:55:00Z",
            filled_at="2026-11-09T16:00:00Z",
        ),
        api_order(
            qty="100", status="canceled", stop_price="11.00", submitted_at="2026-11-09T16:00:01Z"
        ),
    ]
    history = FakeHistory(
        [
            quote_at("12.00", datetime(2026, 11, 9, 11, 10, tzinfo=ET)),
            quote_at("11.70", datetime(2026, 11, 9, 11, 45, tzinfo=ET)),
        ]
    )
    manager = protector(client, history=history, now_ns=POST_NS)
    start(manager)
    assert manager.emulated_trigger("AAPL") == Decimal("11.456")


def test_a_house_limit_is_not_an_adoption_trail() -> None:
    # N2: a released house LIMIT at 16:46 started the window and let the 17:30 high in.
    released_limit = api_order(
        qty="100",
        order_type="limit",
        limit_price="36.00",
        status="canceled",
        submitted_at="2026-11-09T21:46:00Z",
    )
    client = down_window_client(released_limit)
    manager = protector(
        client, history=down_window_history(), now_ns=ns(datetime(2026, 11, 9, 19, 30, tzinfo=ET))
    )
    start(manager)
    assert manager.emulated_trigger("AAPL") == Decimal("36.08")


def test_a_stale_quantity_cannot_still_be_reported_as_tape_ok_during_rearm() -> None:
    # G8: 55 shares read, 155 held; the line said position=155 protected=0 ... tape=ok.
    client = tonight_client()
    manager = protector(client, history=FakeHistory(), now_ns=POST_NS)
    manager.rebuild_tapes()
    client.positions = [api_position("155")]
    manager.reconcile()
    assert "tape=ok" not in line_for(manager, POST_NS, "36.60")


@pytest.mark.parametrize("reaches_bound", [False, True], ids=["null-row", "truncated-null-page"])
def test_sdk_normalization_cannot_hide_a_malformed_or_truncated_window(
    monkeypatch, reaches_bound: bool
) -> None:
    # N3: QuoteSet dropped null rows, so both windows read tape=ok at 685695d.
    rows = [quote_payload()] * 9_999 + [None] if reaches_bound else [None]
    payload: dict[str, object] = {"quotes": {"AAPL": rows}}
    if reaches_bound:
        payload["next_page_token"] = "unread-high-page"  # noqa: S105 - a page token
    stub_http(monkeypatch, [(200, payload)])
    manager = protector(tonight_client(), history=bounded_tape(paced(1)), now_ns=POST_NS)
    start(manager)
    assert "tape=partial" in line_for(manager, POST_NS, "36.60")
    assert [page.reason for page in manager.pages] == ["outside_rth_tape_unreadable"]


def test_a_partial_start_read_keeps_breach_counting_and_silence_paging() -> None:
    client = tonight_client()
    trail_id = str(client.orders[0].id)
    manager = protector(client, history=FakeHistory(error=RuntimeError("fixture")), now_ns=POST_NS)
    start(manager)
    line_for(manager, POST_NS, "36.40")
    assert not manager.on_trade("AAPL", Decimal("36.40"), POST_NS)
    assert not manager.on_trade("AAPL", Decimal("36.40"), POST_NS + 500_000_000)
    assert manager.on_trade("AAPL", Decimal("36.40"), POST_NS + 1_000_000_000)
    assert client.cancelled == [trail_id]
    manager.watch(POST_NS + 6_000_000_000)
    assert [page.reason for page in manager.pages] == [
        "outside_rth_tape_unreadable",
        "outside_rth_feed_silent",
    ]
