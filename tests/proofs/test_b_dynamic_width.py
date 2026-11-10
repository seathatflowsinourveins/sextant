"""B's protector takes each symbol's width (D-30); fixture prices, no calibrated value."""

import asyncio
import json
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from test_b_protector import FakeTradingClient, api_position, api_update, b_account
from test_b_protector import api_order as rth_order
from test_b_width import MINUTE_NS

from sextant.paper.b_feed import BHistoricalTape, QuoteObservation
from sextant.paper.b_protector import BParameters, Protector, ProtectorStream, load_b_parameters
from sextant.paper.b_width import BarRow
from sextant.paper.sessions import ET
from sextant.validation.tuning import _PROPOSAL_ROWS

ROOT = Path(__file__).parents[2]
SEC = 1_000_000_000
RTH_NS = int(datetime(2026, 11, 9, 10, 0, tzinfo=ET).timestamp()) * SEC
POST_NS = int(datetime(2026, 11, 9, 18, 10, tzinfo=ET).timestamp()) * SEC
INTERVAL_NS = 5 * MINUTE_NS
WIDTH_ROWS = {
    "alpaca_min_trail_fraction": Decimal("0.001"),
    "trail_atr_period": Decimal("3"),
    "trail_atr_bar_minutes": Decimal("5"),
    "trail_atr_multiple": Decimal("3"),
}


def width_params(**overrides: Decimal) -> BParameters:
    facts = {
        "native_trail_fraction": Decimal("0.025"),
        "reconcile_interval_s": Decimal("10"),
        "feed_poll_interval_s": Decimal("1"),
        "feed_silence_s": Decimal("5"),
        "tape_deadline_s": Decimal("10"),
        "tape_max_requests": Decimal("100"),
        "tape_max_bars": Decimal("10000"),
    }
    return BParameters(**(facts | WIDTH_ROWS | overrides))


def steady_bars(now_ns: int, *, count: int = 4, bar_range: str = "0.12", close: str = "200"):
    """``count`` completed 5-minute bars of one range, the newest closing at or before now."""

    last_open = now_ns - now_ns % INTERVAL_NS - INTERVAL_NS
    level, half = Decimal(close), Decimal(bar_range) / 2
    return tuple(
        BarRow(
            ts_ns=last_open - index * INTERVAL_NS,
            high=level + half,
            low=level - half,
            close=level,
        )
        for index in range(count)
    )


class FakeBars:
    def __init__(self, rows=None, *, error: Exception | None = None) -> None:
        self.rows = dict(rows or {})
        self.error = error
        self.calls: list[tuple[tuple[str, ...], int]] = []

    def bar_page(self, symbols, bar_minutes, now_ns):
        self.calls.append((tuple(symbols), bar_minutes))
        if self.error is not None:
            raise self.error
        return {s: self.rows.get(s, ()) for s in symbols}, None, now_ns


class FakeQuotes:
    def __init__(self, quotes=(), *, error: Exception | None = None) -> None:
        self.quotes = list(quotes)
        self.error = error
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def __call__(self, symbols, feed):
        self.calls.append((tuple(symbols), feed))
        if self.error is not None:
            raise self.error
        return [q for q in self.quotes if q.symbol in symbols and 0 < q.bid <= q.ask]


def quote(bid: str, ask: str, at_ns: int, symbol: str = "AAPL") -> QuoteObservation:
    return QuoteObservation(symbol, Decimal(bid), Decimal(ask), None, at_ns)


def make(client, bars, quotes, clock, *, feed="none", history=None, **overrides) -> Protector:
    return Protector(
        client,
        b_account(),
        width_params(**overrides),
        now_ns=lambda: clock[0],
        feed=feed,
        history=history,
        bars=bars,
        quotes=quotes,
    )


def reasons(p: Protector) -> list[str]:
    return [page.reason for page in p.pages]


def held(*symbols: str) -> FakeTradingClient:
    return FakeTradingClient(positions=[api_position("10", s) for s in symbols])


def calm(now_ns: int, *symbols: str) -> tuple[FakeBars, FakeQuotes]:
    names = symbols or ("AAPL",)
    bars = FakeBars({s: steady_bars(now_ns) for s in names})
    quotes = FakeQuotes([quote("200.00", "200.01", now_ns, s) for s in names])
    return bars, quotes


def test_the_registry_carries_the_width_rows_uncalibrated_and_never_cited_to_alpaca():
    path = ROOT / "lanes/paper/b-parameters.json"
    rows = {row["name"]: row for row in json.loads(path.read_text())}
    params = load_b_parameters(path)
    assert params.alpaca_min_trail_fraction == Decimal("0.001")
    assert params.trail_atr_period == Decimal("22")
    assert params.trail_atr_bar_minutes == Decimal("5")
    assert params.trail_atr_multiple == Decimal("3")
    assert not {"trail_min_fraction", "large_cap_symbols", "large_cap_trail_fraction"} & set(rows)
    minimum = rows["alpaca_min_trail_fraction"]["source"]
    assert "observed on paper, not documented" in minimum
    assert "docs/handbook/lessons.jsonl:52" in minimum
    assert "alpaca.markets" not in minimum
    assert "rounded up" in minimum and "ours" in minimum
    for name in WIDTH_ROWS:
        assert rows[name]["calibration_state"] == "UNCALIBRATED"
        assert rows[name]["last_change"] == "2026-11-10"
        assert "UNCALIBRATED" in rows[name]["source"]
        assert _PROPOSAL_ROWS[name][:2] == ("lanes/paper/b-parameters.json", name)


def test_one_refresh_is_one_bars_and_one_quote_request_for_all_held_symbols():
    clock = [RTH_NS]
    bars, quotes = calm(RTH_NS, "AAPL", "MSFT")
    p = make(held("AAPL", "MSFT"), bars, quotes, clock)
    p.reconcile()

    assert p.refresh_widths_when_due() is True
    assert bars.calls == [(("AAPL", "MSFT"), 5)]
    assert quotes.calls == [(("AAPL", "MSFT"), "sip")]
    assert p.trail_width("AAPL") == Decimal("0.0018")  # 3 x 0.12 / 200

    clock[0] += 60 * SEC  # the same bar interval: nothing more is read
    assert p.refresh_widths_when_due() is False
    clock[0] = RTH_NS - RTH_NS % INTERVAL_NS + INTERVAL_NS  # the next bar completes
    assert p.refresh_widths_when_due() is True
    assert (len(bars.calls), len(quotes.calls)) == (2, 2)


def test_a_newly_held_symbol_is_warmed_once_without_waiting_for_the_next_bar():
    clock = [RTH_NS]
    client = held("AAPL")
    bars, quotes = calm(RTH_NS, "AAPL", "MSFT")
    p = make(client, bars, quotes, clock)
    p.reconcile()
    p.refresh_widths_when_due()
    client.positions.append(api_position("5", "MSFT"))
    p.reconcile()
    clock[0] += SEC
    assert p.refresh_widths_when_due() is True
    assert p.refresh_widths_when_due() is False
    assert len(bars.calls) == 2
    assert p.trail_width("MSFT") == Decimal("0.0018")


def test_too_few_completed_bars_keeps_the_native_width_and_pages_once_per_episode():
    clock = [RTH_NS]
    bars = FakeBars({"AAPL": steady_bars(RTH_NS, count=2)})
    quotes = FakeQuotes([quote("200.00", "200.01", RTH_NS)])
    p = make(held("AAPL"), bars, quotes, clock)
    p.reconcile()
    p.refresh_widths_when_due()
    clock[0] += INTERVAL_NS
    p.refresh_widths_when_due()

    assert p.trail_width("AAPL") == Decimal("0.025")
    assert reasons(p) == ["dynamic_width_bars_unavailable"]

    clock[0] += INTERVAL_NS
    bars.rows["AAPL"] = steady_bars(clock[0])  # a computed width ends the episode
    p.refresh_widths_when_due()
    assert p.trail_width("AAPL") == Decimal("0.0018")
    bars.error = TimeoutError("bars")
    clock[0] += INTERVAL_NS
    p.refresh_widths_when_due()
    assert reasons(p) == ["dynamic_width_bars_unavailable"] * 2


def test_a_failed_bars_request_keeps_the_last_width_and_pages_once():
    clock = [RTH_NS]
    bars, quotes = calm(RTH_NS)
    p = make(held("AAPL"), bars, quotes, clock)
    p.reconcile()
    p.refresh_widths_when_due()
    bars.error = RuntimeError("down")
    for _ in range(2):
        clock[0] += INTERVAL_NS
        p.refresh_widths_when_due()

    assert p.trail_width("AAPL") == Decimal("0.0018")
    assert reasons(p) == ["dynamic_width_bars_unavailable"]


def test_a_missing_invalid_or_failed_quote_keeps_the_last_width_and_pages_once():
    clock = [RTH_NS]
    bars, quotes = calm(RTH_NS)
    p = make(held("AAPL"), bars, quotes, clock)
    p.reconcile()
    p.refresh_widths_when_due()
    for step in ("crossed", "missing", "failed"):
        clock[0] += INTERVAL_NS
        bars.rows["AAPL"] = steady_bars(clock[0], bar_range="0.30")
        quotes.quotes = [quote("201.00", "200.00", clock[0])] if step == "crossed" else []
        quotes.error = TimeoutError("quotes") if step == "failed" else None
        p.refresh_widths_when_due()

    assert p.trail_width("AAPL") == Decimal("0.0018")
    assert reasons(p) == ["dynamic_width_quote_unavailable"]


def test_with_no_width_ever_computed_a_missing_quote_keeps_the_native_width():
    clock = [RTH_NS]
    p = make(held("AAPL"), FakeBars({"AAPL": steady_bars(RTH_NS)}), FakeQuotes(), clock)
    p.reconcile()
    p.refresh_widths_when_due()
    assert p.trail_width("AAPL") == Decimal("0.025")
    assert reasons(p) == ["dynamic_width_quote_unavailable"]


def test_main_gives_the_protector_bounded_width_reads_off_the_account_pacer(tmp_path, monkeypatch):
    from test_b_protector_main import FakeTradingClient as MainClient
    from test_b_protector_main import patch_stream, write_config

    from sextant.paper.b_protector_main import PacedHistoricalDataClient, main

    monkeypatch.setenv("ALPACA_PAPER_2_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_PAPER_2_SECRET_KEY", "test-secret")
    monkeypatch.setenv("B_EXPECTED_ACCOUNT_SUFFIX", "ture")
    patch_stream(monkeypatch)
    seen: list[Protector] = []
    original = ProtectorStream.run

    def record(self) -> None:
        seen.append(self.protector)
        original(self)

    monkeypatch.setattr(ProtectorStream, "run", record)
    config = write_config(tmp_path, "b-slot2.json")
    assert (
        main(
            ["--config", str(config), "--parameters", str(ROOT / "lanes/paper/b-parameters.json")],
            client_factory=lambda **_: MainClient(),
            on_page=lambda page: None,
        )
        == 0
    )

    protector = seen[0]
    assert isinstance(protector._bars, BHistoricalTape)
    assert not isinstance(protector._bars._client, PacedHistoricalDataClient)  # LEAD-1445 item 1
    assert getattr(protector._bars._client, "_retry", None) == 0  # bounded, no SDK retry (item 3)
    assert getattr(protector, "_admit", None) is None  # nothing asks the account pacer
    quotes = protector._quotes
    assert quotes is not None and getattr(quotes, "__name__", "") == "latest_quotes"


# --- The Codex max round on part 2 (bw2 f6d618b r1) -------------------------------------------


def owner_fill(symbol: str, qty: str):
    order = rth_order(client_order_id=f"owner-{symbol}", symbol=symbol, qty=qty, filled_qty=qty)
    return api_update(order.model_copy(update={"status": "filled"}), position_qty=float(qty))


@pytest.mark.parametrize("read_s", [0.0, 0.3])  # the no-delay control, then two slow reads
def test_width_reads_never_hold_the_trade_update_loop_an_owner_fill_is_covered_at_once(read_s):
    bars, quotes = calm(RTH_NS)
    fast_bars, fast_quotes = bars.bar_page, quotes.__call__

    def slow_bars(*args):
        time.sleep(read_s)
        return fast_bars(*args)

    def slow_quotes(*args):
        time.sleep(read_s)
        return fast_quotes(*args)

    bars.bar_page = slow_bars  # type: ignore[method-assign]
    client = held("AAPL")
    stream = ProtectorStream(
        client,
        b_account(),
        width_params(),
        api_key="test-key",
        secret_key="test-secret",  # noqa: S106 - a fixture, not a secret
        now_ns=lambda: RTH_NS,
        bars=bars,
        width_quotes=slow_quotes,
    )
    stream.protector.reconcile()

    def covered(symbol: str) -> Decimal:
        house = [o for o in client.orders if o.symbol == symbol and o.client_order_id[:4] == "B001"]
        return sum((Decimal(str(o.qty)) for o in house), Decimal(0))

    async def body() -> float:
        started = time.monotonic()
        stream._refresh_widths()  # the two reads start; the loop is free
        client.positions.append(api_position("5", "MSFT"))
        await stream._on_trade_update(owner_fill("MSFT", "5"))
        elapsed = time.monotonic() - started
        while (task := getattr(stream, "_width_task", None)) is not None and not task.done():
            await asyncio.sleep(0.01)
        getattr(stream, "_drain_widths", lambda: None)()
        return elapsed

    elapsed = asyncio.run(body())
    assert covered("MSFT") == 5
    assert elapsed < 0.25, elapsed  # the 5 shares are covered at once, not after the reads (P1)
    assert stream.protector.trail_width("AAPL") == Decimal("0.0018")  # applied on the loop


def test_a_width_quote_older_than_the_last_one_taken_is_rejected_as_on_quote_does():
    clock = [RTH_NS]
    bars, quotes = calm(RTH_NS)
    p = make(held("AAPL"), bars, quotes, clock)
    p.reconcile()
    p.refresh_widths_when_due()
    assert p.trail_width("AAPL") == Decimal("0.0018")
    clock[0] += INTERVAL_NS
    bars.rows["AAPL"] = steady_bars(clock[0])
    quotes.quotes = [quote("100.00", "100.01", RTH_NS - SEC)]  # older: 0.0036 if it were taken
    p.refresh_widths_when_due()
    assert p.trail_width("AAPL") == Decimal("0.0018")
    assert reasons(p) == ["dynamic_width_quote_unavailable"]


class TapeData:
    """The bounded tape client: alpaca-py's RESTClient.get and the latest-quote call."""

    def __init__(self) -> None:
        import requests

        self._session, self._retry = requests.Session(), 3
        self.requests: list[str] = []

    def get(self, path, data):
        self.requests.append(path)
        return {"bars": {"AAPL": []}}

    def get_stock_latest_quote(self, request):
        self.requests.append("latest-quote")
        return {}


def test_main_counts_both_width_reads_as_data_requests_never_on_the_account_pacer(
    tmp_path, monkeypatch
):
    from test_b_protector_main import FakeTradingClient as MainClient
    from test_b_protector_main import write_config

    from sextant.paper.b_protector_main import main

    monkeypatch.setenv("ALPACA_PAPER_2_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_PAPER_2_SECRET_KEY", "test-secret")
    monkeypatch.setenv("B_EXPECTED_ACCOUNT_SUFFIX", "ture")
    data: list[TapeData] = []
    seen: list[tuple[int, int, bool]] = []

    def run(stream) -> None:
        protector = stream.protector
        pacer = protector._start_client._pacer
        before = (pacer.wire_requests, pacer.bucket.tokens, len(pacer.queue))
        protector.read_widths(("AAPL",), RTH_NS)
        after = (pacer.wire_requests, pacer.bucket.tokens, len(pacer.queue))
        seen.append((len(data[-1].requests), protector.data_requests, after == before))

    monkeypatch.setattr(ProtectorStream, "run", run)
    config = write_config(tmp_path, "b-slot2.json")
    argv = ["--config", str(config), "--parameters", str(ROOT / "lanes/paper/b-parameters.json")]
    factory: Any = lambda **_: data.append(TapeData()) or data[-1]  # noqa: E731
    assert main(argv, client_factory=lambda **_: MainClient(), data_client_factory=factory) == 0
    assert seen == [(2, 2, True)]  # two data requests, counted as such; the pacer untouched


# --- 2a computes the width and uses it nowhere: orders and triggers are those of 37bb20e -------

CALLS_AT_37BB20E = "c3906ea16f601329cde4b6ffabd417d8937af9002d8b6aae6530051e21fc8495"


def order_and_trigger_calls(clock, bars=None, quotes=None) -> tuple[str, Protector]:
    """One RTH trail, its re-arm after the broker loses it, then three outside-hours quotes."""

    import hashlib

    client = FakeTradingClient(positions=[api_position("10")])
    p = make(client, bars, quotes, clock, feed="sip", trail_atr_period=Decimal("3"))
    p.reconcile()
    p.refresh_widths_when_due()
    client.orders = []  # the broker lost the trail: the re-arm
    p.reconcile()
    triggers = []
    clock[0] = POST_NS
    for bid in ("200.00", "201.00", "200.50"):
        clock[0] += SEC
        p.note_poll(clock[0])
        ask = Decimal(bid) + Decimal("0.01")
        p.on_quote("AAPL", bid=Decimal(bid), ask=ask, last=None, ts_ns=clock[0])
        triggers.append(str(p.emulated_trigger("AAPL")))
    calls = [request.model_dump(mode="json") for request in client.submitted]
    record = {"submitted": calls, "cancelled": len(client.cancelled), "triggers": triggers}
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest(), p


def test_2a_changes_no_order_trigger_or_submitted_width_against_37bb20e():
    measured, p = order_and_trigger_calls([RTH_NS], *calm(RTH_NS))
    assert p.trail_width("AAPL") == Decimal("0.0018")  # the width was computed, and not used
    assert measured == CALLS_AT_37BB20E
    assert order_and_trigger_calls([RTH_NS])[0] == CALLS_AT_37BB20E  # no width source at all


# --- 2a-res v4 (LEAD-1445): the width reads are data requests, never on the trading pacer -------

INVARIANT_SYMBOLS = ("AAPL", "MSFT", "AMD")
TRADING_EVENTS = ("fill", "cancel", "reconcile")


def interleavings() -> list[tuple[str, ...]]:
    """Every order of an owner fill, a cancel and a reconcile, with the width read started
    before all of them and finished after, or started and finished between them."""

    import itertools

    runs: list[tuple[str, ...]] = []
    for a, b, c in itertools.permutations(TRADING_EVENTS):
        runs += [("w+", a, b, c, "w-"), (a, "w+", b, "w-", c)]
    return runs


def trading_run(tokens: int, held_count: int, queued: int, events, width: bool, *, hold=None):
    """One run on B's real shared pacer: its token level, queue and wire counter, and the cover
    each owner fill received. ``width`` False is the same run with the width reads off."""

    import contextlib
    import inspect
    from typing import cast

    from sextant.execution.pacer import AccountPacer, PacerRefused
    from sextant.paper import b_protector_main as entry
    from sextant.paper.config import PaperBudget
    from sextant.risk.controls import Controls

    clock = [RTH_NS]
    positions = [api_position("10", s) for s in INVARIANT_SYMBOLS[:held_count]]
    raw = FakeTradingClient(positions=positions)
    budget = PaperBudget(
        requests=180, window_s=60, broker_cap=200, external_reserve=20, source="lanes/limits.yaml"
    )
    pacer = AccountPacer(cast(Controls, entry.BudgetControls(budget)), now_ns=lambda: clock[0])
    client = entry.PacedTradingClient(raw, pacer)
    bars, quotes = calm(RTH_NS, *INVARIANT_SYMBOLS) if width else (None, None)
    if bars is not None and hold is not None:
        on_time = bars.bar_page

        def held_bars(*args):
            hold()
            return on_time(*args)

        bars.bar_page = held_bars  # type: ignore[method-assign]
    extra: dict[str, Any] = {"bars": bars, "width_quotes": quotes}
    if width and "width_admit" in inspect.signature(ProtectorStream).parameters:
        extra["width_admit"] = getattr(client, "admit_query", None)  # 2a's main wiring
    stream = ProtectorStream(
        client,
        b_account(),
        width_params(),
        api_key="test-key",
        secret_key="test-secret",  # noqa: S106 - a fixture, not a secret
        now_ns=lambda: clock[0],
        **extra,
    )
    stream.protector.reconcile()
    pacer.paused_until = clock[0] + SEC  # house cancels queue behind a pause, as after a 429
    for n in range(queued):
        with contextlib.suppress(PacerRefused):
            client.cancel_order_by_id(f"house-gone-{n}")
    clock[0] += SEC
    pacer.bucket.tokens, pacer.bucket.anchor = tokens, clock[0]
    covers: list[Decimal] = []

    def cover(symbol: str) -> Decimal:
        house = [o for o in raw.orders if o.symbol == symbol and o.client_order_id[:4] == "B001"]
        return sum((Decimal(str(o.qty)) for o in house), Decimal(0))

    async def body() -> None:
        for event in events:
            if event == "w+":
                stream._refresh_widths()
            elif event == "w-":
                task = stream._width_task
                if task is not None:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(asyncio.shield(task), timeout=3)
                stream._drain_widths()
            elif event == "cancel":
                with contextlib.suppress(PacerRefused):
                    client.cancel_order_by_id("house-gone-late")
            elif event == "reconcile":  # as the scheduled tick does: a refusal pages, then waits
                with contextlib.suppress(PacerRefused):
                    stream.protector.reconcile()
            else:
                symbol = f"F{len(covers)}"
                raw.positions.append(api_position("5", symbol))
                await stream._on_trade_update(owner_fill(symbol, "5"))
                covers.append(cover(symbol))

    asyncio.run(body())
    return (pacer.bucket.tokens, len(pacer.queue), pacer.wire_requests), covers


@pytest.mark.parametrize("queued", [0, 2])
@pytest.mark.parametrize("held_count", [0, 1, 2, 3])
def test_width_reads_never_change_the_account_pacers_tokens_queue_or_wire_count(held_count, queued):
    """Invariant (a), LEAD-1445 item 4: every token level 0..burst, every interleaving."""

    for tokens in range(19):  # 0..burst, the 180/min budget's burst of 18
        for events in interleavings():
            on = trading_run(tokens, held_count, queued, events, True)[0]
            off = trading_run(tokens, held_count, queued, events, False)[0]
            assert on == off, (tokens, events)


@pytest.mark.parametrize("queued", [0, 2])
@pytest.mark.parametrize("held_count", [0, 1, 2, 3])
def test_owner_fill_cover_with_width_reads_on_equals_cover_with_them_off(held_count, queued):
    """Invariant (b), LEAD-1445 item 4: the same runs, the cover each owner fill received."""

    for tokens in range(19):
        for events in interleavings():
            on = trading_run(tokens, held_count, queued, events, True)[1]
            off = trading_run(tokens, held_count, queued, events, False)[1]
            assert on == off, (tokens, events)


def test_three_owner_fills_during_a_held_bars_read_are_covered_5_5_5():
    """Invariant (b)'s named witness: nine tokens, one held position, a bars read held open;
    0c130f7 covered 5/5/0, 37bb20e 5/5/5 (Codex max on c90fac6, burst limitation)."""

    import threading

    release = threading.Event()
    events = ("w+", "fill", "fill", "fill")
    try:
        _, covers = trading_run(9, 1, 0, events, True, hold=lambda: release.wait(3))
    finally:
        release.set()
    assert covers == [5, 5, 5]


def test_two_queued_cancels_and_a_held_width_read_leave_the_owner_fill_covered():
    """Codex max's probe test_review_scope.py:176, kept: five tokens, two queued cancels."""

    import threading

    release = threading.Event()
    try:
        _, covers = trading_run(5, 1, 2, ("w+", "fill"), True, hold=lambda: release.wait(3))
    finally:
        release.set()
    assert covers == [5]


@pytest.mark.parametrize("how", ["cancelled", "failed"])
def test_a_cancelled_or_failed_width_read_keeps_the_last_width_pages_and_moves_no_order(how):
    """Invariant (c), LEAD-1445 item 4 and LEAD-1021: the last width stays, a page says so,
    and no order or sell level moves."""

    clock = [RTH_NS]
    bars, quotes = calm(RTH_NS)
    raw = held("AAPL")
    stream = ProtectorStream(
        raw,
        b_account(),
        width_params(),
        api_key="test-key",
        secret_key="test-secret",  # noqa: S106 - a fixture, not a secret
        now_ns=lambda: clock[0],
        bars=bars,
        width_quotes=quotes,
    )
    p = stream.protector
    p.reconcile()
    p.refresh_widths_when_due()
    assert p.trail_width("AAPL") == Decimal("0.0018")
    clock[0] += INTERVAL_NS
    bars.rows["AAPL"] = steady_bars(clock[0], bar_range="0.30")  # would widen it, if taken
    orders = ([r.model_dump(mode="json") for r in raw.submitted], list(raw.cancelled))
    if how == "failed":

        def broken(*args: Any) -> Any:
            raise RuntimeError("the width worker failed")

        p.read_widths = broken  # type: ignore[method-assign]

    async def body() -> None:
        stream._refresh_widths()
        task = stream._width_task
        assert task is not None
        if how == "cancelled":
            task.cancel()
        for _ in range(100):
            if task.done():
                break
            await asyncio.sleep(0.005)
        stream._drain_widths()  # never raises out of the scheduled tick

    asyncio.run(body())
    assert p.trail_width("AAPL") == Decimal("0.0018")
    assert ([r.model_dump(mode="json") for r in raw.submitted], list(raw.cancelled)) == orders
    assert "dynamic_width_bars_unavailable" in reasons(p)
    assert stream._width_task is None
