"""The Codex review witnesses of #262 at 685695d, carried into the repository.

Each was a failing probe at 685695d (the review's scratch file); here each runs offline
through the pinned alpaca-py 0.44.0 client with urllib3's pool stubbed, or through the
protector's fakes. Two are adapted: the house-LIMIT fixture moved to the post-market
(only outside-hours spans are read, G5), and a continuation token is followed (R1, which
replaced N3's "a token is partial"), so the one-admission-per-request witness expects the
token back and the second page refused without its own admission.
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
    tonight_history,
)
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.response import HTTPResponse

from sextant.paper.b_feed import BHistoricalTape, bound_transport
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
    # R1 changes the expectation, not the property: the token is returned to the caller,
    # and the next page is a second request that needs its own admission.
    from sextant.execution.pacer import PacerRefused

    pacer = paced(1)
    tape = bounded_tape(pacer)
    _, token = tape.quote_page("AAPL", POST_NS - 7200 * 1_000_000_000, POST_NS, "sip")
    assert token == "page-two"  # noqa: S105 - a page token
    assert len(calls) == pacer.wire_requests == 1
    with pytest.raises(PacerRefused):
        tape.quote_page("AAPL", POST_NS - 7200 * 1_000_000_000, POST_NS, "sip", token)
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


# R1-R3 (b-tape-pages): the start read follows continuation tokens inside the same deadline
# and request budget, and a partial read still raises the trigger from the rows it read.

AH_HIGH = datetime(2026, 11, 9, 16, 59, tzinfo=ET)


def paged_history(page_size: int) -> FakeHistory:
    # Newest first: page one is 18:09 then 16:59; page two is the 12:47 claim-time quote.
    return FakeHistory(
        [
            quote_at("36.99", datetime(2026, 11, 9, 12, 47, 18, tzinfo=ET)),
            quote_at("38.70", AH_HIGH),
            quote_at("37.62", datetime(2026, 11, 9, 18, 9, tzinfo=ET)),
            quote_at("39.50", datetime(2026, 11, 9, 16, 30, tzinfo=ET)),
        ],
        page_size=page_size,
    )


def budget_params(requests: int):
    from dataclasses import replace

    return replace(b_params(), tape_max_requests=Decimal(requests))


def paged_manager(history: FakeHistory, requests: int) -> Protector:
    return Protector(
        tonight_client(),
        b_account(),
        budget_params(requests),
        now_ns=lambda: POST_NS,
        feed="sip",
        history=history,
    )


def test_a_window_over_one_page_is_read_to_its_last_page_and_is_ok() -> None:
    # R1/R2: two pages, two requests, the window complete only at the page without a token.
    history = paged_history(page_size=2)
    manager = paged_manager(history, requests=8)
    start(manager)

    assert len(history.requests) == 2
    assert manager._tapes["AAPL"].status == "ok"
    # 39.50 x 0.975 = 38.5125 -> 38.51: the high on the second (older) page is followed.
    assert manager.emulated_trigger("AAPL") == Decimal("38.51")
    assert "tape=ok" in line_for(manager, POST_NS, "38.60")
    assert manager.pages == []


def test_a_budget_that_ends_after_one_page_still_raises_the_trigger_from_it() -> None:
    # R3: positions + orders + one page = 3 requests; the page read holds 37.62 and 38.70.
    history = paged_history(page_size=2)
    manager = paged_manager(history, requests=3)
    start(manager)

    tape = manager._tapes["AAPL"]
    assert len(history.requests) == 1
    assert tape.status == "partial"
    # 38.70 x 0.975 = 37.7325 -> 37.73: a lower bound, never above the complete read's 38.51.
    assert manager.emulated_trigger("AAPL") == Decimal("37.73")
    assert "tape=partial" in line_for(manager, POST_NS, "38.60")
    assert [page.reason for page in manager.pages] == ["outside_rth_tape_unreadable"]
    assert "1 page" in manager.pages[0].detail


def test_a_partial_read_below_the_native_stop_never_lowers_the_trigger() -> None:
    # R3: the trigger is the maximum of the native stop, the broker hwm level and the read.
    late = datetime(2026, 11, 9, 17, 30, tzinfo=ET)
    history = FakeHistory([quote_at("36.00", AH_HIGH), quote_at("35.90", late)], page_size=1)
    manager = paged_manager(history, requests=3)
    start(manager)

    assert manager._tapes["AAPL"].status == "partial"
    assert manager._tapes["AAPL"].level == Decimal("35.00")  # 35.90 x 0.975 = 35.0025
    assert manager.emulated_trigger("AAPL") == Decimal("36.465")


def test_a_partial_read_never_takes_a_row_from_before_the_adoption_instant() -> None:
    # R3: a row the server returns outside the requested window is never a source.
    class Leaky(FakeHistory):
        def quote_page(self, symbol, start_ns, end_ns, feed, page_token=None):
            self.requests.append((symbol, start_ns, end_ns, feed))
            early = quote_at("45.00", datetime(2026, 11, 9, 11, 0, tzinfo=ET))
            return (early, quote_at("38.70", AH_HIGH)), "more"

    history = Leaky()
    manager = paged_manager(history, requests=3)
    start(manager)

    assert manager._tapes["AAPL"].status == "partial"
    assert manager.emulated_trigger("AAPL") == Decimal("37.73")


def test_a_read_interrupted_by_the_deadline_keeps_the_pages_it_read() -> None:
    # R2/R3 with G1: the interval timer ends the second page; the first page still counts.
    class SlowSecondPage(FakeHistory):
        def quote_page(self, symbol, start_ns, end_ns, feed, page_token=None):
            if page_token is not None:
                for _ in range(500):
                    time.sleep(0.01)
            return super().quote_page(symbol, start_ns, end_ns, feed, page_token)

    from dataclasses import replace

    history = SlowSecondPage(paged_history(page_size=2).observations, page_size=2)
    params = replace(b_params(), tape_deadline_s=Decimal("0.3"))
    manager = Protector(
        tonight_client(), b_account(), params, now_ns=lambda: POST_NS, feed="sip", history=history
    )
    began = time.monotonic()
    start(manager)

    assert time.monotonic() - began < 2
    assert manager._tapes["AAPL"].status == "partial"
    assert manager.emulated_trigger("AAPL") == Decimal("37.73")


def test_a_start_read_off_the_main_thread_reports_tape_partial() -> None:
    # The r7 follow-up: nothing is read, one page, and the state line says partial.
    import threading

    manager = protector(tonight_client(), history=tonight_history(), now_ns=POST_NS)
    worker = threading.Thread(target=manager.rebuild_tapes)
    worker.start()
    worker.join()
    manager.reconcile()

    assert "tape=partial" in line_for(manager, POST_NS, "36.60")
    assert manager.emulated_trigger("AAPL") == Decimal("36.465")
