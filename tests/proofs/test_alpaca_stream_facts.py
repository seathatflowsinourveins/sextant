"""N1e: a trade's vendor conditions and every stream reconnect reach the ranking Actor.

Rows enter as msgpack frames from a stand-in websocket's ``recv`` into alpaca-py's own
``_consume`` and reconnect loop (websocket.py:231-283, 445-492); the stand-in replaces only
``_connect`` and ``_auth``, the network. A real live node runs the data client, the sandbox
execution client and a RankingActor whose host records what it is handed.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal as D
from typing import Any, cast

import msgpack
import pytest
import websockets
from alpaca.data.enums import DataFeed
from alpaca.data.models import Trade
from nautilus_trader.adapters.sandbox import SandboxExecutionClientFactory
from nautilus_trader.config import DataClientConfig
from nautilus_trader.live import InstrumentProviderConfig, LiveNodeBuilder
from nautilus_trader.live.clients import DataClientFactory
from nautilus_trader.model import (
    AggressorSide,
    InstrumentId,
    Price,
    Quantity,
    TradeId,
    TradeTick,
    Venue,
)
from test_alpaca_data import INSTRUMENT_ID, ProofProvider
from test_paper_config import account

from sextant.alpaca.data import AlpacaDataClient, AlpacaStockDataStream
from sextant.alpaca.stream_facts import AlpacaTradeFacts, StreamFacts, trade_facts
from sextant.paper.native import node_config, sandbox_client_config
from sextant.ranking.engine import ReferencePrices
from sextant.ranking.generation import Coverage, CoverageState
from sextant.ranking.node_actor import Priming, RankingActor, RankingActorConfig
from sextant.ranking.publisher import AssetState

DROP = "drop"


def row(trade_id: int, conditions: object) -> dict[str, Any]:
    stamp = msgpack.Timestamp.from_unix_nano(time.time_ns())  # after the Actor's watch began
    return {
        "T": "t",
        "S": "AAPL",
        "t": stamp,
        "p": 10.02,
        "s": 7,
        "x": "D",
        "i": trade_id,
        "c": conditions,
        "z": "C",
    }


class Wire:
    """One connection: waits for the trades subscription, then plays its script."""

    def __init__(self, script: list[Any]) -> None:
        self.script, self.subscribed = list(script), asyncio.Event()

    async def send(self, data) -> None:
        payload = msgpack.unpackb(data if isinstance(data, bytes) else b"".join(data))
        if payload.get("action") == "subscribe" and "AAPL" in payload.get("trades", ()):
            self.subscribed.set()

    async def recv(self) -> bytes:
        await self.subscribed.wait()
        if not self.script:
            await asyncio.Future()  # quiet: the SDK's own receive timeout wakes it
        step = self.script.pop(0)
        if step == DROP:
            raise websockets.WebSocketException("fixture transport loss")
        return cast(bytes, msgpack.packb([row(*step)]))

    async def close(self) -> None:
        return None


class Stream(AlpacaStockDataStream):
    def __init__(self, scripts: list[list[Any]]) -> None:
        super().__init__("fixture", "fixture", feed=DataFeed.SIP)
        self.scripts = scripts
        self._reconnect_min_backoff = self._reconnect_max_backoff = 0.01

    async def _connect(self) -> None:  # the network only; _start_ws stays the SDK's
        self._ws = Wire(self.scripts.pop(0))

    async def _auth(self) -> None:
        return None


class Host:
    def __init__(self, log: list[tuple]) -> None:
        self.log = log

    def on_trade(self, tick, *, facts):
        self.log.append(("trade", tick.trade_id.value, facts))

    def set_symbol(self, name, *, references, asset):
        self.log.append(("symbol", None if asset is None else asset.halted))

    def set_coverage(self, coverage):
        self.log.append(("coverage", coverage.state.name))

    def close(self) -> None:
        return None


def priming() -> Priming:
    now = time.time_ns()
    return Priming(
        coverage=Coverage(CoverageState.READY, True, 1, 1, 0, 0, 0),
        symbols={
            "AAPL": (
                ReferencePrices(D("10"), now - 10**9, "fixture official close"),
                AssetState(now - 10**9, now + 3600 * 10**9, False, "common", "fixture vendor"),
            )
        },
    )


async def run_node(scripts: list[list[Any]], trades: int):
    log: list[tuple] = []
    finished = asyncio.Event()
    stream = Stream(scripts)

    class Counted(RankingActor):
        def on_trade(self, trade: TradeTick) -> None:
            super().on_trade(trade)
            if sum(entry[0] == "trade" for entry in log) == trades:
                finished.set()

    actor = Counted(
        RankingActorConfig(
            instrument_ids=(INSTRUMENT_ID,),
            feed="sip",
            host_factory=lambda: Host(log),
            priming=priming,
            page_window_s=60,
            trade_facts=StreamFacts("sip"),
        )
    )
    clients: list[AlpacaDataClient] = []

    class Factory(DataClientFactory):
        @staticmethod
        def create(*, name, config, cache, clock):
            clients.append(
                AlpacaDataClient(
                    name=name,
                    config=config,
                    cache=cache,
                    clock=clock,
                    instrument_provider=ProofProvider(InstrumentProviderConfig(load_all=True)),
                    stream=stream,
                    feed=DataFeed.SIP,
                    venue=Venue.from_str("ALPACA"),
                )
            )
            return clients[-1]

    settings = account()
    node = (
        LiveNodeBuilder.from_config("alpaca-stream-facts", node_config(settings))
        .with_delay_post_stop_secs(0)
        .add_data_client("ALPACA", Factory(), DataClientConfig())
        .add_simulated_exec_client(
            settings.client_id,
            SandboxExecutionClientFactory(),
            sandbox_client_config(settings, "10000 USD"),
        )
        .build()
    )
    node.add_actor(actor)
    handle = node.handle()
    task = asyncio.create_task(node.run_async())
    try:
        await asyncio.wait_for(finished.wait(), timeout=10)
    finally:
        handle.stop()
        try:
            await asyncio.wait_for(task, timeout=10)
        finally:
            node.dispose()
    return log, actor, clients[0], stream


def after_priming(log: list[tuple]) -> list[tuple]:
    return log[2:]  # coverage READY, then AAPL primed unknown


def test_both_readers_see_the_vendor_conditions_through_the_sdk_consume_path() -> None:
    log, actor, client, _ = asyncio.run(run_node([[(1, ["Z"]), (2, ["@"])]], trades=2))
    assert log[:2] == [("coverage", "READY"), ("symbol", None)]
    assert after_priming(log) == [
        ("trade", "D-1", (True, ("Z",))),  # masked: the halt state stays unknown
        ("symbol", False),  # the first regular print clears, before the host sees it
        ("trade", "D-2", (True, ("@",))),
    ]
    assert actor.evidence()["cleared_by_print"] == 1 and client.stream_gap_count == 0


def test_a_reconnect_reaches_the_actor_before_any_later_trade() -> None:
    scripts = [[(1, ["@"]), DROP], [(2, ["@"])]]
    log, actor, client, stream = asyncio.run(run_node(scripts, trades=2))
    assert after_priming(log) == [
        ("symbol", False),
        ("trade", "D-1", (True, ("@",))),
        ("symbol", None),  # the gap: every name unknown again
        ("coverage", "DEGRADED"),  # and coverage DEGRADED for the segment (LEAD-0033 2e)
        ("symbol", False),  # the rule applies again on the new connection
        ("trade", "D-2", (True, ("@",))),
    ]
    assert stream.connects == 2 and client.stream_gap_count == 1
    assert actor.evidence()["resets"] == 1 and actor.stream_gaps == 1


def test_a_reconnect_cannot_proceed_without_its_notice() -> None:
    async def connect(notice):
        stream = Stream([[], []])
        stream.on_reconnect = notice
        await stream._start_ws()
        await stream._start_ws()  # the second connect, as the SDK's loop makes it
        return stream

    def broken(_connects: int) -> None:
        raise RuntimeError("fixture node loop closed")

    with pytest.raises(RuntimeError, match="node loop closed"):
        asyncio.run(connect(broken))  # the SDK treats it as a failed connect and retries
    with pytest.raises(RuntimeError, match="gap notice"):
        asyncio.run(connect(None))
    seen: list[int] = []
    assert asyncio.run(connect(seen.append)).connects == 2 and seen == [2]


@pytest.mark.parametrize(
    ("conditions", "expected"),
    [(["@", "I"], ("@", "I")), ([], ()), (None, None), ("@", None), (["@", 7], None)],
)
def test_conditions_are_kept_only_as_the_vendors_string_list(conditions, expected) -> None:
    raw = {"t": "2026-11-09T15:00:00Z", "p": 10.02, "s": 7, "x": "D", "i": 1, "z": "C"}
    if conditions is not None:
        raw["c"] = conditions
    tick = TradeTick(
        INSTRUMENT_ID,
        Price.from_str("10.02"),
        Quantity.from_int(7),
        AggressorSide.NO_AGGRESSOR,
        TradeId("D-1"),
        1,
        2,
    )
    try:
        trade = Trade("AAPL", raw)
    except Exception:  # the SDK model refuses a mixed list itself
        assert expected is None
        return
    assert trade_facts(trade, tick).conditions == expected


def test_the_actor_reads_facts_only_for_the_same_trade() -> None:
    source = StreamFacts("sip")
    other = InstrumentId.from_str("MSFT.ALPACA")

    def tick(trade_id: str, iid: InstrumentId = INSTRUMENT_ID) -> TradeTick:
        return TradeTick(
            iid,
            Price.from_str("10.02"),
            Quantity.from_int(7),
            AggressorSide.NO_AGGRESSOR,
            TradeId(trade_id),
            1,
            2,
        )

    assert source(tick("D-1")) is None  # nothing seen yet
    source.record(AlpacaTradeFacts(INSTRUMENT_ID, "D-1", ("@",), "C", 1, 2))
    assert source(tick("D-1")) == (True, ("@",))
    assert source(tick("D-2")) is None  # a different trade never borrows these facts
    assert source(tick("D-1", other)) is None
    source.record(AlpacaTradeFacts(INSTRUMENT_ID, "D-3", None, "C", 1, 2))
    assert source(tick("D-3")) is None  # unknown conditions are unknown facts
    assert source.facts_type.type_name == "AlpacaTradeFacts"
    assert source.gap_type.type_name == "AlpacaStreamGap"
