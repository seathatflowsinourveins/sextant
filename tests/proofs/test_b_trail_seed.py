# pyright: reportIncompatibleMethodOverride=false, reportArgumentType=false, reportAttributeAccessIssue=false
"""Trail seed (MODELED): a held name with a quote and no print after start.

When a trail is denied for want of a trade, B asks the venue's data client once, for that name
only, for its latest trade of this session (never at start, where the node's command queue holds
the whole directory's subscriptions: node_order.QUEUE), through the engine's own request
(nautilus_trader d53849b2 python/nautilus_trader/trading/__init__.pyi:973; the DataEngine caches
a trades response, crates/data/src/engine/mod.rs:1946-1951 and :1974-1981, before the Strategy's
``on_historical_trades``), so the RiskEngine can price the trail
(crates/risk/src/engine/mod.rs:2368-2391) without waiting for the next print. The client reads
that latest trade as the official IB adapter does, the last ``limit`` of the window
(crates/adapters/interactive_brokers/src/data/core.rs:2056-2061), through alpaca-py's descending
sort (cc4cb3b7 alpaca/data/requests.py:32,40). A real LiveNode with the Alpaca data client over
a stand-in stream and history, and the native sandbox execution client; no wire, no key. Fixture
values only.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import msgpack
from alpaca.common.enums import Sort
from alpaca.data.enums import DataFeed
from alpaca.data.models import TradeSet
from alpaca.data.requests import StockTradesRequest
from nautilus_trader.adapters.sandbox import SandboxExecutionClientFactory
from nautilus_trader.config import DataClientConfig
from nautilus_trader.live import InstrumentProviderConfig, LiveNodeBuilder
from nautilus_trader.live.clients import DataClientFactory
from nautilus_trader.model import (
    ClientOrderId,
    OrderSide,
    OrderStatus,
    OrderType,
    Price,
    Quantity,
    Venue,
)
from nautilus_trader.trading import Strategy
from test_alpaca_data import INSTRUMENT_ID, QUOTE, TRADE, ProofProvider, _WireTimestamp
from test_b_lifecycle import GATE_ON
from test_b_lifecycle_protect import NATIVE
from test_paper_config import account

from sextant.alpaca import data as adapter
from sextant.paper.b_lifecycle import BLifecycle, BLifecycleConfig
from sextant.paper.native import node_config, sandbox_client_config
from sextant.paper.sessions import session_start_ns

OLDER = {**TRADE, "p": 10.00, "i": 122}  # the session's first trade
LATEST = {**TRADE, "p": 10.02, "i": 123}  # its latest


class QuotesOnly:
    """The stream stand-in: one quote on subscribe and never a print."""

    def __init__(self, stream):
        self.stream = stream

    async def send(self, data):
        payload = msgpack.unpackb(data if isinstance(data, bytes) else b"".join(data))
        if "AAPL" in payload.get("quotes", ()) and not self.stream.quoted:
            self.stream.quoted = True
            await self.stream._dispatch({**QUOTE, "t": _WireTimestamp(datetime.now(UTC))})

    async def close(self):
        pass


class History:
    """The vendor's ordering: ascending unless asked to sort descending, then ``limit``."""

    def __init__(self):
        self.requests: list[StockTradesRequest] = []

    def get_stock_trades(self, request: StockTradesRequest):
        self.requests.append(request)
        rows = [OLDER, LATEST][:: -1 if request.sort == Sort.DESC else 1][: request.limit]
        stamp = datetime.now(UTC) - timedelta(seconds=1)
        return TradeSet({"AAPL": [{**row, "t": stamp.isoformat()} for row in rows]})


class Held(BLifecycle):
    """B, plus one owner BUY under its strategy id on the first quote (the claimed shape)."""

    def __init__(self, config):
        super().__init__(config)
        self.placed, self.done = False, asyncio.Event()

    def on_quote(self, quote):
        super().on_quote(quote)
        if not self.placed:
            self.placed, self.asked_at_start = True, len(self.history.requests)
            order = self.order_factory.limit(
                INSTRUMENT_ID,
                OrderSide.BUY,
                Quantity.from_int(10),
                Price.from_str("10.05"),
                client_order_id=ClientOrderId("OWNER-1"),
            )
            Strategy.submit_order(self, order)

    def on_order_accepted(self, event):
        super().on_order_accepted(event)
        order = self.cache.order(event.client_order_id)
        if order is not None and order.order_type is OrderType.TRAILING_STOP_MARKET:
            self.done.set()


async def run_node(journal):
    class Stream(adapter.AlpacaStockDataStream):
        def __init__(self):
            super().__init__("fixture", "fixture", feed=DataFeed.SIP)
            self.quoted = False

        async def _start_ws(self):
            self._ws = QuotesOnly(self)

        async def _consume(self):
            await asyncio.Future()

    history = History()

    class Factory(DataClientFactory):
        @staticmethod
        def create(*, name, config, cache, clock):
            return adapter.AlpacaDataClient(
                name=name,
                config=config,
                cache=cache,
                clock=clock,
                instrument_provider=ProofProvider(InstrumentProviderConfig(load_all=True)),
                stream=Stream(),
                historical=history,
                feed=DataFeed.SIP,
                venue=Venue.from_str("ALPACA"),
            )

    settings = account()
    node = (
        LiveNodeBuilder.from_config("b-trail-seed-proof", node_config(settings))
        .with_delay_post_stop_secs(0)
        .add_data_client("ALPACA", Factory(), DataClientConfig())
        .add_simulated_exec_client(
            settings.client_id,
            SandboxExecutionClientFactory(),
            sandbox_client_config(settings, "10000 USD"),
        )
        .build()
    )
    strategy = Held(
        BLifecycleConfig(
            namespace="BTEST",
            instrument_ids=(INSTRUMENT_ID,),
            consumer=None,
            rank_gate=replace(GATE_ON, value=False),
            native_trail_fraction=NATIVE,
            journal=journal.append,
        )
    )
    strategy.history = history
    node.add_strategy(strategy)
    handle = node.handle()
    task = asyncio.create_task(node.run_async())
    try:
        try:
            await asyncio.wait_for(strategy.done.wait(), timeout=5)
        except TimeoutError:
            pass
        orders = list(strategy.cache.orders())
    finally:
        handle.stop()
        try:
            await asyncio.wait_for(task, timeout=10)
        finally:
            node.dispose()
    return orders, history, strategy.asked_at_start


def test_a_quoted_name_without_a_print_is_seeded_and_gets_exactly_one_trail():
    journal: list[dict] = []
    orders, history, asked_at_start = asyncio.run(run_node(journal))
    assert asked_at_start == 0, "a seed was requested at start"
    (owner,) = [o for o in orders if str(o.client_order_id) == "OWNER-1"]
    assert owner.status is OrderStatus.FILLED
    placed = [
        o
        for o in orders
        if o.order_type is OrderType.TRAILING_STOP_MARKET and o.status is OrderStatus.ACCEPTED
    ]
    assert len(placed) == 1, [(str(o.client_order_id), o.status) for o in orders]
    assert placed[0].quantity.as_decimal() == Decimal(10)
    (request,) = history.requests
    assert request.limit == 1 and request.sort == Sort.DESC  # the latest, not the first
    assert request.start is not None and request.end is not None
    end_ns = int(request.end.replace(tzinfo=UTC).timestamp()) * 1_000_000_000
    window = datetime.fromtimestamp(session_start_ns(end_ns) // 1_000_000_000, tz=UTC)
    assert request.start == window.replace(tzinfo=None)  # only this session's trades
    (seed,) = [r for r in journal if r.get("kind") == "trail_seed"]
    assert seed["price"] == "10.02"


def test_one_seed_request_per_wait_never_one_per_quote():
    """Stand-in: the denial for want of a trade asks once; quotes and a second denial in the same
    wait ask nothing more; a trade ends the wait, and a later denial asks again."""
    from types import SimpleNamespace

    from nautilus_trader.model import OrderStatus as Status
    from test_b_lifecycle import PENNY, quote, trade
    from test_review_state_edges import CID, cached_order, probe

    def deny(engine, cid=CID):
        order = cached_order(pending=False)
        order.client_order_id, order.is_closed, order.status = cid, True, Status.DENIED
        engine.orders[cid] = order
        event = SimpleNamespace(instrument_id=PENNY, client_order_id=cid, ts_event=engine.now)
        engine.on_order_denied(event)

    engine = probe()
    engine.held = Decimal(100)
    deny(engine)
    assert engine.requests == [(PENNY, 1)]
    for _ in range(3):
        engine.on_quote(quote(engine.now, "0.5050", "0.5100"))
    deny(engine, ClientOrderId("O-20261027-080600-001-BTEST-3"))  # the same wait
    assert engine.requests == [(PENNY, 1)] and engine.arms == []
    engine.on_trade(trade(engine.now, "0.5100"))  # the wait ends: armed on the print
    assert engine.arms == [Decimal(100)]
    engine.trades.clear()  # a later wait, with no trade cached again
    deny(engine, ClientOrderId("O-20261027-080600-001-BTEST-4"))
    assert engine.requests == [(PENNY, 1), (PENNY, 1)]
