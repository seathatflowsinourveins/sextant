"""The IBKR paper node entry: official adapter only, every refusal named, nothing connects.

No test connects: the node is built offline as the pinned upstream's own factory proofs build it
(nautilus_trader@d53849b ``python/tests/unit/adapters/interactive_brokers/
test_interactive_brokers_factories.py:142-190``), and every ``run`` uses a recording builder.
"""

import gc
import json
import re
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.adapters.interactive_brokers import (
    InteractiveBrokersDataClientFactory,
    InteractiveBrokersExecutionClientFactory,
    MarketDataType,
)
from nautilus_trader.model import InstrumentId, OrderType

from sextant.execution.custody import AccountScope, WriterLease
from sextant.paper import node_ibkr

ROOT = Path(__file__).parents[2]
CODE = "DU0000000"  # a fixture code, not an account
ENV = "IB_PAPER_ACCOUNT_ID"


@pytest.fixture(autouse=True)
def _account_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))


def _argv(tmp_path: Path, *extra: str, **changes: str) -> list[str]:
    values = {
        "--host": "192.0.2.1",  # TEST-NET-1: unroutable, and nothing here connects anyway
        "--port": "4002",
        "--data-client-id": "91001",
        "--exec-client-id": "91002",
        "--account-id-env": ENV,
        "--instrument": "AAPL.NASDAQ",
        "--order-qty": "1",
        "--duration-s": "5",
        "--receipt-dir": str(tmp_path / "receipts"),
        "--lease-root": str(tmp_path / "locks"),
        "--profile": "trailing",
        "--registry": str(_registry(tmp_path, "ON")),
    }
    values.update({f"--{k.replace('_', '-')}": v for k, v in changes.items()})
    return [item for pair in values.items() for item in pair] + list(extra)


def _registry(tmp_path: Path, state: str, text: str | None = None) -> Path:
    path = tmp_path / f"ibkr-{state}.toml"
    source = (ROOT / "lanes/paper/ibkr.toml").read_text()
    top = re.sub(r'^state = "[A-Z]+"', f'state = "{state}"', source, count=1, flags=re.M)
    path.write_text(text or top)
    return path


class _Node:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def handle(self) -> Any:
        return self

    def stop(self) -> None:
        self.calls.append("stop")

    def run(self) -> None:
        self.calls.append(f"run:{threading.current_thread() is threading.main_thread()}")

    def dispose(self) -> None:
        self.calls.append("dispose")

    def add_builtin_strategy(self, name: str, config: Any) -> None:
        self.calls.append(f"strategy:{name}")


def _receipt(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "receipts" / node_ibkr.RECEIPT).read_text())


def test_the_node_builds_offline_from_the_official_factories_only(tmp_path: Path) -> None:
    args = node_ibkr.parse(_argv(tmp_path))
    registry = node_ibkr.load_registry(args.registry)
    configs = node_ibkr.client_configs(args, node_ibkr.account(args, {ENV: CODE}), registry)
    assert (configs.data.port, configs.execution.port) == (4002, 4002)
    assert (configs.data.client_id, configs.execution.client_id) == (91001, 91002)
    assert configs.execution.account_id == CODE
    assert configs.data.market_data_type == MarketDataType.REALTIME  # the registry's start
    # The registry's starts are the adapter's own defaults (interactive_brokers.md:742-743).
    assert (configs.data.connection_timeout, configs.data.request_timeout) == (300, 60)
    assert configs.data.instrument_provider.load_ids == {InstrumentId.from_str("AAPL.NASDAQ")}

    recorded: list[tuple[str, Any]] = []

    class Builder:
        def __getattr__(self, name: str) -> Any:
            def call(*a: Any) -> Any:
                recorded.append((name, a))
                return built if name == "build" else self

            return call

    class FakeLiveNode:
        @staticmethod
        def builder(*a: Any) -> Builder:
            recorded.append(("builder", a))
            return Builder()

    built = _Node([])
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(node_ibkr, "LiveNode", FakeLiveNode)
        node_ibkr.build(args, configs, registry)
    assert built.calls == ["strategy:ExecTester"]  # the engine's own Strategy, nothing of ours
    names = [name for name, _ in recorded]
    assert names.count("add_exec_client") == names.count("add_data_client") == 1
    factories = {name: a[1] for name, a in recorded if name.startswith("add_")}
    assert type(factories["add_data_client"]) is InteractiveBrokersDataClientFactory
    assert type(factories["add_exec_client"]) is InteractiveBrokersExecutionClientFactory
    assert dict(recorded)["with_reconciliation"] == (True,)
    assert dict(recorded)["with_risk_engine_config"][0].bypass is False

    node = node_ibkr.build(args, configs, registry)  # the real builder: still no connection
    try:
        trader_id, running = str(node.trader_id), node.is_running
    finally:
        try:
            node.dispose()
        finally:
            del node
            gc.collect()
    assert trader_id == "PAPERIBKR-001" and not running


def test_the_tester_is_upstreams_and_dry_runs_without_the_second_opt_in(tmp_path: Path) -> None:
    dry = node_ibkr.tester_config(node_ibkr.parse(_argv(tmp_path)))
    assert dry.dry_run is True and dry.reduce_only_on_stop is False and dry.use_post_only is False
    assert (str(dry.client_id), dry.stop_order_type) == ("IB", OrderType.TRAILING_STOP_MARKET)
    assert (
        dry.trailing_offset == Decimal(25) and dry.enable_stop_sells and not dry.enable_limit_buys
    )
    live = node_ibkr.tester_config(
        node_ibkr.parse(_argv(tmp_path, "--send-orders", profile="lifecycle"))
    )
    assert live.dry_run is False
    assert not live.enable_limit_sells and not live.enable_stop_sells and not live.enable_brackets
    lifecycle = node_ibkr.tester_config(node_ibkr.parse(_argv(tmp_path, profile="lifecycle")))
    assert lifecycle.open_position_on_start_qty == Decimal(1)
    assert lifecycle.open_position_on_first_quote and not lifecycle.enable_limit_sells
    bracket = node_ibkr.tester_config(node_ibkr.parse(_argv(tmp_path, profile="bracket")))
    assert bracket.enable_brackets and bracket.bracket_offset_ticks == 500
    assert set(node_ibkr.PROFILES) == {
        "lifecycle",
        "cancel-modify",
        "stop",
        "stop-limit",
        "trailing",
        "bracket",
    }


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"port": "4001"}, "live_port"),
        ({"port": "7496"}, "live_port"),
        ({"port": "5000"}, "paper_port"),
        ({"duration_s": "0"}, "arguments"),
        ({"account_id_env": "DU0000000x"}, "arguments"),
        ({"order_qty": "0"}, "order_qty"),
        ({"order_qty": "1.5"}, "order_qty"),
        ({"instrument": "not-an-id"}, "instrument"),
    ],
)
def test_argument_refusals_are_named(tmp_path: Path, changes: dict[str, str], reason: str) -> None:
    with pytest.raises(node_ibkr.IbkrNodeRefused) as refused:
        node_ibkr.parse(_argv(tmp_path, **changes))
    assert refused.value.reason == reason


def _run(tmp_path: Path, argv: list[str], environ: dict[str, str]) -> tuple[int, list[str]]:
    calls: list[str] = []

    def builder(*a: Any) -> _Node:
        calls.append("build")
        return _Node(calls)

    _, code = node_ibkr.run(node_ibkr.parse(argv), environ=environ, builder=builder)
    return code, calls


@pytest.mark.parametrize(
    ("environ", "changes", "registry", "reason"),
    [
        ({ENV: CODE}, {}, "OFF", "lane_off"),
        ({ENV: CODE}, {}, "BROKEN", "registry"),
        ({}, {}, "ON", "account"),
        ({ENV: "U1234567"}, {}, "ON", "account"),
        ({ENV: f"{CODE}-U1234567"}, {}, "ON", "account"),
        ({ENV: f"IB-{CODE}"}, {}, "ON", "account"),
        ({ENV: CODE}, {"exec_client_id": "91001"}, "ON", "client_config"),
        ({ENV: CODE}, {"exec_client_id": "2000"}, "ON", "client_config"),
        ({ENV: CODE}, {"instrument": "ESZ6.XCME"}, "ON", "client_config"),
        ({ENV: CODE}, {"instrument": "AAPL=STK.SMART"}, "ON", "client_config"),
    ],
)
def test_start_refusals_write_the_receipt_and_never_build(
    tmp_path: Path, environ: dict[str, str], changes: dict[str, str], registry: str, reason: str
) -> None:
    argv = _argv(tmp_path, **changes)
    path = _registry(tmp_path, registry, "state = 1\n" if registry == "BROKEN" else None)
    argv[argv.index("--registry") + 1] = str(path)
    code, calls = _run(tmp_path, argv, environ)
    assert (code, calls) == (2, [])
    receipt = _receipt(tmp_path)
    assert (receipt["phase"], receipt["reason"]) == ("refused", reason)
    text = json.dumps(receipt)
    assert "U1234567" not in text and CODE not in text  # the account is never written


@pytest.mark.parametrize("send_orders", [False, True])
def test_the_committed_registry_turns_the_lane_on(tmp_path: Path, send_orders: bool) -> None:
    # ON for the paper account only; without the key the start still refuses.
    argv = _argv(tmp_path, *(["--send-orders"] if send_orders else []))
    argv[argv.index("--registry") + 1] = str(ROOT / "lanes/paper/ibkr.toml")
    assert _run(tmp_path, argv, {}) == (2, [])
    # An order-sending start with the default (SELL-resting) profile is refused by name first.
    reason = "no sourced continuous custody fence" if send_orders else "account"
    assert _receipt(tmp_path)["reason"] == reason


def test_a_held_writer_lease_refuses_the_start(tmp_path: Path) -> None:
    other = WriterLease(AccountScope("INTERACTIVE_BROKERS", CODE), tmp_path / "locks", "other")
    other.acquire()
    try:
        assert _run(tmp_path, _argv(tmp_path), {ENV: CODE}) == (2, [])
    finally:
        other.close()
    assert _receipt(tmp_path)["reason"] == "writer_lease"


def test_an_unavailable_shared_lease_directory_refuses_before_build(tmp_path: Path) -> None:
    (tmp_path / ".cache").write_text("not a directory")
    assert _run(tmp_path, _argv(tmp_path), {ENV: CODE}) == (2, [])
    receipt = _receipt(tmp_path)
    assert (receipt["phase"], receipt["reason"]) == ("refused", "writer_lease")


def test_the_node_refuses_off_the_main_thread(tmp_path: Path) -> None:
    out: list[tuple[int, list[str]]] = []
    worker = threading.Thread(
        target=lambda: out.append(_run(tmp_path, _argv(tmp_path), {ENV: CODE}))
    )
    worker.start()
    worker.join()
    assert out == [(2, [])] and _receipt(tmp_path)["reason"] == "main_thread"


def test_a_clean_start_holds_the_lease_runs_on_the_main_thread_and_releases(
    tmp_path: Path,
) -> None:
    code, calls = _run(tmp_path, _argv(tmp_path), {ENV: CODE})
    assert (code, calls) == (0, ["build", "run:True", "dispose"])
    receipt = _receipt(tmp_path)
    assert (receipt["phase"], receipt["dry_run"], receipt["profile"]) == (
        "stopped",
        True,
        "trailing",
    )
    assert len(receipt["lease"]["scope_sha256"]) == 64 and CODE not in json.dumps(receipt)
    after = WriterLease(AccountScope("INTERACTIVE_BROKERS", CODE), tmp_path / "locks", "next")
    after.acquire()  # released at exit
    after.close()
