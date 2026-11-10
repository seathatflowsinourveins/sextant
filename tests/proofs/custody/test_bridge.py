"""Offline Alpaca wire/reducer cases, not a live client or native claim stand-in."""

from decimal import Decimal as D

import pytest

from sextant.execution.alpaca import AlpacaBridge, FillFact, OrderCommand, Outcome
from sextant.execution.custody import (
    AccountSnapshot,
    CustodyError,
    PositionAuthority,
    WriterLease,
)
from sextant.execution.pacer import AccountPacer, ActionKind, PacerRefused

from .conftest import IID, SCOPE, SEC, controls, custody, order, snapshot


def bridge(tmp_path, *, response="ACK", budget=180, reserve: int | None = 0):
    book = custody(tmp_path)
    book.observe(snapshot(), now=SEC)
    lease = WriterLease(SCOPE, tmp_path / "locks", "fixture-writer")
    lease.acquire()
    clock, session, allowed, sent = [SEC], ["RTH"], [True], []
    pacer = AccountPacer(
        controls(request_budget=budget, reserve_per_open_position=reserve), lambda: clock[0]
    )

    def send(request, before_wire):
        before_wire()
        sent.append(request)
        return Outcome(response, "venue-1")

    result = AlpacaBridge(
        book, lease, pacer, send, session=lambda: session[0], admission=lambda _request: allowed[0]
    )
    return result, book, lease, clock, session, allowed, sent


def command(cid="house-exit", *, side="SELL", qty="100", price="10.01", kind="LIMIT"):
    return OrderCommand(
        cid,
        IID,
        side,
        D(qty),
        kind,
        "DAY",
        D(price) if kind == "LIMIT" else None,
        D(price) if kind == "TRAILING_STOP" else None,
    )


def test_decimal_string_envelope_and_ack_is_never_fill(tmp_path):
    b, _book, lease, _clock, _session, _allowed, sent = bridge(tmp_path)
    try:
        b.submit(command())
        assert sent[0].path == "/v2/orders"
        assert sent[0].body == {
            "client_order_id": "house-exit",
            "symbol": "AAA",
            "side": "sell",
            "qty": "100",
            "type": "limit",
            "time_in_force": "day",
            "order_class": "simple",
            "limit_price": "10.01",
            "extended_hours": False,
        }
        assert b.facts()[0].filled == 0
        assert b.facts()[0].leaves == D("100")
        assert b.pacer.wire_requests == 1
        with pytest.raises(CustodyError, match="custody"):
            b.submit(command("second-exit"))
    finally:
        lease.close()


@pytest.mark.parametrize("query", [False, True])
@pytest.mark.parametrize(
    ("reply", "resets"),
    [
        ("ACK", True),
        ("REFUSED", True),
        ("NOT_FOUND", True),
        ("UNKNOWN", False),
        ("DEFERRED", False),
    ],
)
def test_confirmed_wire_reply_resets_429_backoff_for_orders_and_queries(
    tmp_path, query, reply, resets
):
    b, _book, lease, clock, _session, _allowed, sent = bridge(tmp_path)
    try:
        if not query:
            b.submit(command())
        replies = iter(["RATE_LIMIT", "RATE_LIMIT", reply, "RATE_LIMIT"])

        def send(request, before_wire):
            before_wire()
            sent.append(request)
            return Outcome(next(replies), "venue-1")

        def request():
            if query:
                b.query("positions")
            else:
                b.cancel("house-exit")

        b.transport = send
        base = b.pacer.controls.ns("backoff_base_s")
        for pause in (base, 2 * base):
            request()
            assert b.pacer.paused_until == clock[0] + pause
            assert b.pacer.bucket.tokens == 0
            clock[0] += pause

        previous_pause = b.pacer.paused_until
        request()
        assert b.pacer.paused_until == previous_pause
        request()
        assert b.pacer.paused_until == clock[0] + (base if resets else 4 * base)
        assert b.pacer.bucket.tokens == 0
        assert len(sent) == (4 if query else 5)
    finally:
        lease.close()


def test_owner_order_cannot_be_cancelled_or_replaced_even_with_stamped_strategy(tmp_path):
    b, book, lease, *_rest, sent = bridge(tmp_path)
    try:
        book.observe(snapshot(order("owner-limit", owner=True, venue="owner-v")), now=SEC)
        with pytest.raises(CustodyError):
            b.cancel("owner-limit")
        with pytest.raises(CustodyError):
            b.replace_limit("owner-limit", D("10.02"))
        assert sent == []
    finally:
        lease.close()


def test_session_is_rechecked_after_pacing_and_trail_never_leaks_outside_rth(tmp_path):
    b, _book, lease, clock, session, _allowed, sent = bridge(tmp_path, budget=10)
    try:
        b.pacer.request(ActionKind.QUERY, lambda mark: mark())
        b.submit(command(kind="TRAILING_STOP", price="0.20"))
        session[0] = "EXTENDED"
        clock[0] += 10 * SEC
        b.pacer.drain()
        assert sent == []
        assert b.facts()[0].terminal  # Positively unsent, not an unknown POST.
    finally:
        lease.close()


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_queued_submit_rechecks_complete_custody_before_sending(tmp_path, side):
    b, book, lease, clock, _session, _allowed, sent = bridge(tmp_path, budget=10)
    try:
        b.pacer.request(ActionKind.QUERY, lambda mark: mark())
        b.submit(command(side=side))
        book.observe(snapshot(complete=False, epoch=2), now=SEC)
        clock[0] += 10 * SEC
        b.pacer.drain()
        assert sent == []
        assert b.facts()[0].terminal
    finally:
        lease.close()


def test_unknown_submit_keeps_quantity_and_404_never_releases_it(tmp_path):
    b, book, lease, *_rest, sent = bridge(tmp_path, response="UNKNOWN")
    try:
        b.submit(command())
        assert b.facts()[0].status == "UNKNOWN"
        assert not b.apply(sent[0], Outcome("NOT_FOUND"))
        book.observe(snapshot(*b.facts(), epoch=2), now=SEC)
        assert book.available_exit(IID) == 0
        assert book.flat_receipt() is None
        assert IID in book.frozen
    finally:
        lease.close()


def test_cancel_ack_retains_reservation_and_blocks_queued_price_change(tmp_path):
    b, _book, lease, clock, _session, _allowed, sent = bridge(tmp_path, budget=10)
    try:
        b.submit(command())
        b.replace_limit("house-exit", D("10.02"))
        b.cancel("house-exit")
        clock[0] += 10 * SEC
        b.pacer.drain()
        assert [r.method for r in sent] == ["POST", "DELETE"]
        assert b.facts()[0].status == "PENDING_CANCEL"
        assert b.facts()[0].leaves == D("100")
        with pytest.raises(CustodyError, match="cancel"):
            b.replace_limit("house-exit", D("10.03"))
    finally:
        lease.close()


def test_stale_get_and_old_cancel_answer_cannot_finish_newer_intent(tmp_path):
    b, _book, lease, clock, _session, _allowed, sent = bridge(tmp_path)
    try:
        b.submit(command())
        stale_epoch = b.epoch("house-exit")
        b.observe(
            order(filled="10", status="PARTIALLY_FILLED"),
            fills=(FillFact("venue-1", D("10"), D("10"), D("10.01")),),
        )
        assert not b.observe(order(status="CANCELED"), fetched_epoch=stale_epoch)
        assert b.facts()[0].filled == D("10")
        b.cancel("house-exit")
        first_cancel = sent[-1]
        b.cancel("house-exit")
        assert not b.apply(first_cancel, Outcome("REFUSED"))
        assert b.facts()[0].leaves == D("90")
        clock[0] += SEC
    finally:
        lease.close()


def test_filled_report_requires_real_generation_fills_and_deduplicates_them(tmp_path):
    b, _book, lease, *_rest, _sent = bridge(tmp_path)
    try:
        b.submit(command())
        assert not b.observe(order(filled="100", status="FILLED"))
        assert b.facts()[0].status == "UNKNOWN"
        fill = FillFact("venue-1", D("100"), D("100"), D("10.01"))
        assert b.observe(order(filled="100", status="FILLED"), fills=(fill,))
        same_fill = FillFact("venue-1", D("100.0"), D("100.0"), D("10.01"))
        assert b.observe(order(filled="100", status="FILLED"), fills=(same_fill,))
        assert b.observe(order(filled="100", status="FILLED"), fills=(fill,))
        assert b.facts()[0].filled == D("100")
        assert b.facts()[0].leaves == 0
        assert b.pacer.fills == 1
    finally:
        lease.close()


def test_lost_writer_fence_prevents_queued_send(tmp_path):
    b, _book, lease, clock, _session, _allowed, sent = bridge(tmp_path, budget=10)
    b.pacer.request(ActionKind.QUERY, lambda mark: mark())
    b.submit(command())
    lease.close()
    clock[0] += 10 * SEC
    b.pacer.drain()
    assert sent == []


@pytest.mark.parametrize("answer", ["REFUSED", "UNKNOWN", "ACK"])
def test_late_submit_answer_never_erases_stream_fill_or_live_leaves(tmp_path, answer):
    b, _book, lease, *_rest, sent = bridge(tmp_path, response="DEFERRED")
    try:
        b.submit(command())
        assert b.observe(
            order(filled="10", status="PARTIALLY_FILLED"),
            fills=(FillFact("venue-1", D("10"), D("10"), D("10.01")),),
        )
        b.apply(sent[0], Outcome(answer, "venue-1"))
        assert b.facts()[0].status == "PARTIALLY_FILLED"
        assert b.facts()[0].leaves == D("90")
    finally:
        lease.close()


def test_cancel_attempt_outcomes_are_retained_independently(tmp_path):
    b, _book, lease, *_rest, sent = bridge(tmp_path)
    try:
        b.submit(command())
        b.cancel("house-exit")
        first = sent[-1]
        b.cancel("house-exit")
        b.apply(first, Outcome("UNKNOWN"))
        attempts = b.cancel_attempts("house-exit", "venue-1")
        assert [a["outcome"] for a in attempts] == ["UNKNOWN", "ACK"]
        assert b.facts()[0].status == "PENDING_CANCEL"
    finally:
        lease.close()


def test_replacement_ack_waits_for_positive_successor_and_old_terminal_is_ignored(tmp_path):
    b, book, lease, *_rest, sent = bridge(tmp_path)
    try:
        b.submit(command())
        b.replace_limit("house-exit", D("10.02"))
        assert sent[-1].body["client_order_id"] == "house-exit__R1"
        b.apply(sent[-1], Outcome("ACK", "venue-2"))
        assert b.facts()[-1].venue_order_id == "venue-1"
        assert b.facts()[-1].status == "PENDING_REPLACE"
        assert b.observe(order("house-exit__R1", venue="venue-2"), replaces="venue-1")
        assert not b.observe(order(venue="venue-1", status="CANCELED"))
        assert b.facts()[-1].venue_order_id == "venue-2"
        assert b.facts()[-1].status == "NEW"
        assert set(book.registrations["house-exit"]["lineage"]) == {"venue-1", "venue-2"}
    finally:
        lease.close()


@pytest.mark.parametrize("successor_filled", [D("0"), D("15")])
def test_replacement_facts_keep_fills_per_venue_and_reserve_current_leaves(
    tmp_path, successor_filled
):
    b, book, lease, *_rest, sent = bridge(tmp_path)
    try:
        b.submit(command(qty="50"))
        assert b.observe(
            order(qty="50", filled="10", status="PARTIALLY_FILLED"),
            fills=(FillFact("venue-1", D("10"), D("10"), D("10.01")),),
        )
        book.observe(snapshot(*b.facts(), net="90", epoch=2), now=SEC)
        b.replace_limit("house-exit", D("10.02"))
        b.apply(sent[-1], Outcome("ACK", "venue-2"))
        fills = (
            (FillFact("venue-2", successor_filled, successor_filled, D("10.02")),)
            if successor_filled
            else ()
        )
        assert b.observe(
            order(
                "house-exit__R1",
                qty="50",
                filled=str(successor_filled),
                status="PARTIALLY_FILLED" if successor_filled else "NEW",
                venue="venue-2",
            ),
            fills=fills,
            replaces="venue-1",
        )
        facts = b.facts()
        retired, current = facts
        assert retired.status == "REPLACED"
        assert retired.filled == D("10")
        assert current.venue_order_id == "venue-2"
        assert current.filled == successor_filled
        assert sum((fact.filled for fact in facts), D("0")) == D("10") + successor_filled
        assert current.leaves == D("50") - successor_filled
        book.observe(snapshot(*facts, net=str(D("90") - successor_filled), epoch=3), now=SEC)
        assert book.available_exit(IID) == D("40")
        with pytest.raises(CustodyError, match="unreserved"):
            b.submit(command("second-exit", qty="41"))
    finally:
        lease.close()


def test_one_account_writer_cannot_attach_two_independent_pacers(tmp_path):
    b, book, lease, clock, session, _allowed, _sent = bridge(tmp_path)
    try:
        another = AccountPacer(controls(), lambda: clock[0])
        with pytest.raises(CustodyError, match="pacer"):
            AlpacaBridge(
                book,
                lease,
                another,
                b.transport,
                session=lambda: session[0],
                admission=lambda _request: True,
            )
    finally:
        lease.close()


def test_unknown_session_refuses_new_entry_before_registering_or_sending(tmp_path):
    b, book, lease, _clock, session, _allowed, sent = bridge(tmp_path)
    try:
        session[0] = "UNKNOWN"
        with pytest.raises(CustodyError, match="session"):
            b.submit(command(side="BUY"))
        assert sent == []
        assert book.registrations == {}
    finally:
        lease.close()


def test_unread_custody_allows_paced_reconciliation_queries_but_no_orders(tmp_path):
    b, book, lease, *_rest, sent = bridge(tmp_path)
    try:
        book.loaded = False  # Injection at the external durable-state boundary.
        b.query("positions")
        assert [r.path for r in sent] == ["/v2/positions"]
        with pytest.raises(CustodyError):
            b.submit(command())
    finally:
        lease.close()


def test_late_action_answer_after_writer_retirement_cannot_mutate_its_state(tmp_path):
    b, _book, lease, *_rest, sent = bridge(tmp_path, response="DEFERRED")
    b.submit(command())
    before = b.facts()
    lease.close()
    assert not b.apply(sent[0], Outcome("ACK", "venue-1"))
    assert b.facts() == before


def test_unavailable_entry_reserve_refuses_before_registering_a_phantom_order(tmp_path):
    b, book, lease, *_rest, sent = bridge(tmp_path, reserve=None)
    try:
        with pytest.raises(CustodyError, match="reserve"):
            b.submit(command(side="BUY"))
        assert book.registrations == {}
        assert sent == []
    finally:
        lease.close()


def _flat_snapshot(count: int, *, epoch: int = 1):
    positions = {IID: D("100")} | {f"S{index}.ALPACA": D("100") for index in range(count - 1)}
    authority = {
        iid: PositionAuthority(quantity, "TEST supplied prior custody; no native claim proof")
        for iid, quantity in positions.items()
    }
    return AccountSnapshot(
        SCOPE,
        epoch,
        positions,
        authority,
        (),
        True,
        SEC,
        "TEST complete account observation",
    )


def test_refused_entry_releases_custody_and_reaches_its_caller(tmp_path):
    b, book, lease, *_rest, sent = bridge(tmp_path, reserve=2)
    try:
        book.observe(_flat_snapshot(8), now=SEC)
        with pytest.raises(PacerRefused, match="entry-reserve-exceeds-burst"):
            b.submit(command(cid="refused-entry", side="BUY"))
        assert book.registrations["refused-entry"].get("unsent") == ("entry-reserve-exceeds-burst")
        assert book.submission_ready(IID)
        assert sent == []
    finally:
        lease.close()
