"""N2a (LEAD-2325 2d/2e): the data-only ranking node entry for the capacity measurement.

The start-and-stop proof reuses test_alpaca_data.py's stand-in socket, provider and history
(no second fake): the Alpaca data client runs its real code over a socket that never opens.
"""

from __future__ import annotations

import ast
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.live import LiveNodeConfig
from nautilus_trader.live.clients import DataClientFactory
from nautilus_trader.model import InstrumentId
from test_alpaca_data import ProofProvider, StandInHistory, StandInSocket

from sextant.alpaca.config import AlpacaExecutionClientConfig
from sextant.alpaca.constants import VENUE
from sextant.ranking import node_main

ROOT = Path(__file__).parents[2]
MODULE = ROOT / "src/sextant/ranking/node_main.py"


def argv(tmp_path: Path, *drop: str, duration: str = "600") -> list[str]:
    universe = tmp_path / "universe.txt"
    universe.write_text("AAPL\n")
    values = {
        "--universe": str(universe),
        "--duration-s": duration,
        "--receipt-dir": str(tmp_path / "receipts"),
        "--receipt-interval-s": "1",
        "--feed": "sip",
        "--api-key-env": "FIXTURE_KEY_NAME",
        "--api-secret-env": "FIXTURE_SECRET_NAME",
        "--lease-root": str(tmp_path / "locks"),
        "--paper-slot": "2",
        "--existing-streams": "0",
        "--lease-source": "fixture: no stream exists",
    }
    out: list[str] = []
    for flag, value in values.items():
        if flag not in drop:
            out += [flag, value]
    return out


def test_the_config_is_data_only_and_the_node_builds_with_no_network(tmp_path) -> None:
    args, _ = node_main.parse(argv(tmp_path))
    config = node_main.node_config()
    assert config.exec_clients == {}
    assert args.universe == (InstrumentId.from_str("AAPL.ALPACA"),)
    assert args.data.api_key_env == "FIXTURE_KEY_NAME"  # a name; no value is read here
    node, actor = node_main.build(args)  # the real factory: building opens nothing
    try:
        assert actor.ticks == 0
    finally:
        node.dispose()


def test_an_execution_client_is_refused(tmp_path) -> None:
    args, _ = node_main.parse(argv(tmp_path))
    execution = AlpacaExecutionClientConfig(
        api_key_env="FIXTURE_KEY_NAME",
        api_secret_env="FIXTURE_SECRET_NAME",  # noqa: S106 - a variable name, not a value
        account_id="ALPACA-1",
    )
    config = LiveNodeConfig(exec_clients={"ALPACA": execution})
    with pytest.raises(ValueError, match="data-only"):
        node_main.build(args, config=config)


def test_a_missing_lease_is_refused(tmp_path) -> None:
    args, _ = node_main.parse(argv(tmp_path))
    with pytest.raises(ValueError, match="lease"):
        node_main.run(args, lease=None)
    assert not (tmp_path / "receipts").exists()


@pytest.mark.parametrize(
    "flag",
    [
        "--universe",
        "--duration-s",
        "--receipt-dir",
        "--receipt-interval-s",
        "--feed",
        "--api-key-env",
        "--api-secret-env",
        "--lease-root",
        "--paper-slot",
        "--existing-streams",
        "--lease-source",
    ],
)
def test_every_argument_is_required(tmp_path, flag: str) -> None:
    with pytest.raises(SystemExit):
        node_main.parse(argv(tmp_path, flag))


def test_the_command_takes_the_real_lease_which_refuses_slot_2_until_it_lands(tmp_path) -> None:
    with pytest.raises(ValueError, match="slot"):
        node_main.main(argv(tmp_path))
    assert not (tmp_path / "receipts").exists()


def test_start_and_stop_on_the_duration_leave_the_final_receipt(tmp_path) -> None:
    from alpaca.data.enums import DataFeed
    from nautilus_trader.model import Venue

    import sextant.alpaca.data as adapter

    class StandInStream(adapter.AlpacaStockDataStream):
        def __init__(self) -> None:
            super().__init__("fixture", "fixture", feed=DataFeed.SIP)
            self.delivered: set[str] = set()
            self.unsubscribe_sent, self.closed = threading.Event(), threading.Event()

        async def _start_ws(self) -> None:
            self._ws = StandInSocket(self, None)

        async def _consume(self) -> bool:
            import asyncio

            await asyncio.Future()
            return False

    class StandInFactory(DataClientFactory):
        @staticmethod
        def create(*, name, config, cache, clock):
            return adapter.AlpacaDataClient(
                name=name,
                config=config,
                cache=cache,
                clock=clock,
                instrument_provider=ProofProvider(InstrumentProviderConfig(load_all=True)),
                stream=StandInStream(),
                historical=cast(Any, StandInHistory(False)),
                venue=Venue.from_str(str(VENUE)),
            )

    events: list[str] = []

    @contextmanager
    def lease():
        events.append("enter")
        yield
        events.append("exit")

    args, _ = node_main.parse(argv(tmp_path, duration="2"))
    config = LiveNodeConfig(delay_post_stop_secs=0)
    receipt = node_main.run(args, lease=lease(), factory=StandInFactory, config=config)
    body = json.loads(receipt.read_text())
    assert events == ["enter", "exit"] and body["final"] is True
    assert body["ticks"] >= 1 and body["errors"] == 0


def test_the_entry_has_no_order_path() -> None:
    tree = ast.parse(MODULE.read_text())
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert names.isdisjoint(
        {
            "add_exec_client",
            "add_simulated_exec_client",
            "add_strategy",
            "add_strategy_from_config",
            "AlpacaExecutionClientFactory",
            "submit_order",
        }
    )
