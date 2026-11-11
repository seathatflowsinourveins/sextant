"""Offline custody/logging/receipt regressions adapted from the exact-head review.

The stop witness executes the native Strategy API call selected by ExecTester
(crates/testkit/src/testers/exec/strategy.rs:2149 at d53849b). It is not an IB connection.
"""

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
from nautilus_trader.common import LoggerConfig, LogLevel, logging_sync_to_disk
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType,
    Currency,
    Equity,
    InstrumentId,
    Money,
    OmsType,
    OrderSide,
    OrderStatus,
    Price,
    Quantity,
    QuoteTick,
    StrategyId,
    Symbol,
    Venue,
)
from nautilus_trader.trading import Strategy, StrategyConfig
from test_ibkr_node import CODE, ENV, _argv, _Node, _receipt
from test_ibkr_node import _account_home as _account_home

from sextant.execution.custody import AccountScope, WriterLease
from sextant.paper import node_ibkr

IID = InstrumentId.from_str("AAPL.NASDAQ")
OWNER = StrategyId.from_str("OWNER-002")


def _engine(logging: LoggerConfig, *, account_venue: bool = False) -> BacktestEngine:
    engine = BacktestEngine(BacktestEngineConfig(run_analysis=False, logging=logging))
    currency = Currency.from_str("USD")
    venue = Venue.from_str(f"IB-{CODE}" if account_venue else "NASDAQ")
    iid = InstrumentId.from_str(f"AAPL.{venue}")
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=currency,
        starting_balances=[Money.from_str("100000 USD")],
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
    )
    engine.add_instrument(
        Equity(
            iid,
            Symbol.from_str("AAPL"),
            currency,
            2,
            Price.from_str("0.01"),
            0,
            0,
            lot_size=Quantity.from_str("1"),
        )
    )
    engine.add_data(
        [
            QuoteTick(
                iid,
                Price.from_str("10.00"),
                Price.from_str("10.01"),
                Quantity.from_str("100"),
                Quantity.from_str("100"),
                1794403800000000000 + index * 1000000000,
                1794403800000000000 + index * 1000000000,
            )
            for index in range(3)
        ]
    )
    return engine


@pytest.mark.parametrize("send_orders", [False, True])
def test_exact_head_shutdown_call_preserves_owner_order(tmp_path: Path, send_orders: bool) -> None:
    class Owner(Strategy):
        def on_start(self) -> None:
            self.submit_order(
                self.order_factory.limit(
                    IID, OrderSide.BUY, Quantity.from_str("1"), Price.from_str("1.00")
                )
            )

    args = node_ibkr.parse(
        _argv(tmp_path, *(["--send-orders"] if send_orders else []), profile="lifecycle")
    )
    config = node_ibkr.tester_config(args)

    class StopCallWitness(Strategy):
        def on_stop(self) -> None:
            if not config.dry_run and config.cancel_orders_on_stop:
                assert not config.use_individual_cancels_on_stop
                assert not config.use_batch_cancel_on_stop
                self.cancel_all_orders(IID, strategy_only=False)

    engine = _engine(LoggerConfig(stdout_level=LogLevel.OFF))
    engine.add_strategy(Owner(StrategyConfig(strategy_id=OWNER)))
    engine.add_strategy(StopCallWitness(StrategyConfig(strategy_id=config.strategy_id)))
    try:
        engine.run()
        orders = engine.cache.orders(strategy_id=OWNER)
        assert len(orders) == 1
        assert orders[0].status == OrderStatus.ACCEPTED
    finally:
        engine.dispose()


@pytest.mark.parametrize("profile", sorted(node_ibkr.PROFILES))
def test_no_profile_cancels_or_closes_on_stop(tmp_path: Path, profile: str) -> None:
    args = node_ibkr.parse(_argv(tmp_path, profile=profile))
    config = node_ibkr.tester_config(args)
    assert not config.cancel_orders_on_stop and not config.close_positions_on_stop


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"port": "4001"}, "live_port"),
        ({"port": "7496"}, "live_port"),
        ({"port": "5000"}, "paper_port"),
        ({"duration_s": "0"}, "arguments"),
        ({"order_qty": "1.5"}, "order_qty"),
        ({"instrument": "bad"}, "instrument"),
    ],
)
def test_argument_refusal_writes_promised_receipt(
    tmp_path: Path,
    changes: dict[str, str],
    reason: str,
) -> None:
    assert node_ibkr.main(_argv(tmp_path, **changes)) == 2
    receipt = _receipt(tmp_path)
    assert (receipt["phase"], receipt["reason"]) == ("refused", reason)
    assert CODE not in json.dumps(receipt)


def _native_logging_witness(tmp_path: Path) -> None:
    selected = LoggerConfig()  # reproduces the builder's default before the fix

    class Builder:
        def with_logging(self, config: LoggerConfig) -> Any:
            nonlocal selected
            selected = config
            return self

        def __getattr__(self, name: str) -> Any:
            return lambda *a, **kw: (
                SimpleNamespace(add_builtin_strategy=lambda *a: None) if name == "build" else self
            )

    args = node_ibkr.parse(_argv(tmp_path))
    registry = node_ibkr.load_registry(args.registry)
    configs = node_ibkr.client_configs(args, node_ibkr.account(args, {ENV: CODE}), registry)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(node_ibkr, "LiveNode", SimpleNamespace(builder=lambda *a: Builder()))
        node_ibkr.build(args, configs, registry)
    engine = _engine(selected, account_venue=True)
    try:
        engine.run()
    finally:
        engine.dispose()
    logging_sync_to_disk()
    assert selected.bypass_logging
    assert selected.stdout_level == selected.fileout_level == LogLevel.OFF


def test_native_portfolio_logging_never_outputs_account_code(tmp_path: Path) -> None:
    # Native logger is process-global: isolate this witness from other test configurations.
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert CODE not in result.stdout and CODE not in result.stderr
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.rglob("*.log"))


@pytest.mark.parametrize("kind", ["order", "inflight", "position", "own", "empty", "dry"])
def test_reconciled_custody_admission_and_refusal_receipt(tmp_path: Path, kind: str) -> None:
    send = kind != "dry"
    args = node_ibkr.parse(
        _argv(tmp_path, *(["--send-orders"] if send else []), profile="lifecycle")
    )
    tester = node_ibkr.tester_config(args).strategy_id
    foreign = SimpleNamespace(strategy_id=OWNER)
    own = SimpleNamespace(strategy_id=tester)
    calls: list[str] = []

    class Started(Strategy):
        def on_start(self) -> None:
            calls.append("strategy-start")

    engine = _engine(LoggerConfig(stdout_level=LogLevel.OFF))
    engine.add_strategy(Started(StrategyConfig(strategy_id=tester)))

    def rows(value: str) -> Any:
        def query(*, instrument_id: InstrumentId) -> list[Any]:
            assert instrument_id == IID
            if kind in {value, "dry"}:
                return [foreign]
            return [own] if kind == "own" else []

        return query

    class Node:
        cache = SimpleNamespace(
            orders_open=rows("order"),
            orders_inflight=rows("inflight"),
            positions_open=rows("position"),
        )

        def add_actor(self, actor: Any) -> None:
            engine.add_actor(actor)

        def handle(self) -> Any:
            return SimpleNamespace(stop=lambda: None)

        def run(self) -> None:
            engine.run()  # exercise native actor-before-strategy failure propagation

        def dispose(self) -> None:
            engine.dispose()
            calls.append("dispose")

    _, status = node_ibkr.run(args, environ={ENV: CODE}, builder=lambda *a: Node())
    refused = kind in {"order", "inflight", "position"}
    assert status == (2 if refused else 0)
    assert calls == (["dispose"] if refused else ["strategy-start", "dispose"])
    receipt = _receipt(tmp_path)
    if refused:
        assert (receipt["phase"], receipt["reason"]) == ("refused", "custody")
    assert CODE not in json.dumps(receipt)
    after = WriterLease(AccountScope("INTERACTIVE_BROKERS", CODE), args.lease_root, "next")
    after.acquire()
    after.close()


@pytest.mark.parametrize("profile", ["cancel-modify", "stop", "stop-limit", "trailing", "bracket"])
def test_order_sending_resting_sell_profile_refuses_before_build(
    tmp_path: Path, profile: str
) -> None:
    args = node_ibkr.parse(_argv(tmp_path, "--send-orders", profile=profile))
    calls: list[str] = []

    def builder(*a: Any) -> Any:
        calls.append("build")
        engine = _engine(LoggerConfig(stdout_level=LogLevel.OFF))

        class FlatNode:
            cache = engine.cache

            def add_actor(self, actor: Any) -> None:
                engine.add_actor(actor)

            def handle(self) -> Any:
                return SimpleNamespace(stop=lambda: None)

            def run(self) -> None:
                calls.append("run")
                engine.run()

            def dispose(self) -> None:
                engine.dispose()

        return FlatNode()

    _, status = node_ibkr.run(args, environ={ENV: CODE}, builder=builder)
    assert calls == [], "a resting SELL profile must refuse before any node can send"
    receipt = _receipt(tmp_path)
    assert (status, receipt["phase"], receipt["reason"]) == (
        2,
        "refused",
        "no sourced continuous custody fence",
    )
    assert CODE not in json.dumps(receipt)


@pytest.mark.parametrize("switch", ["enable_limit_sells", "enable_stop_sells", "enable_brackets"])
def test_order_sending_config_requests_for_sells_are_refused_not_masked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, switch: str
) -> None:
    monkeypatch.setitem(node_ibkr.PROFILES["lifecycle"], switch, True)
    args = node_ibkr.parse(_argv(tmp_path, "--send-orders", profile="lifecycle"))
    with pytest.raises(node_ibkr.IbkrNodeRefused, match="no sourced continuous custody fence"):
        node_ibkr.tester_config(args)


@pytest.mark.parametrize("second_code", [CODE, "DU0000001"])
def test_two_invocations_share_one_account_lease_despite_different_roots(
    tmp_path: Path, second_code: str
) -> None:
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = node_ibkr.parse(_argv(first_dir))
    second = node_ibkr.parse(
        _argv(
            second_dir,
            exec_client_id="91004",
            data_client_id="91003",
            port="7497",
            instrument="MSFT.NASDAQ",
        )
    )
    inner_calls: list[str] = []
    statuses: list[int] = []

    def outer_builder(*a: Any) -> _Node:
        def inner_builder(*a: Any) -> _Node:
            inner_calls.append("build")
            return _Node(inner_calls)

        _, status = node_ibkr.run(second, environ={ENV: second_code}, builder=inner_builder)
        statuses.append(status)
        return _Node([])

    _, status = node_ibkr.run(first, environ={ENV: CODE}, builder=outer_builder)
    assert status == 0
    if second_code == CODE:
        assert statuses == [2], "different launch roots must not create a second account writer"
        assert inner_calls == []
        assert _receipt(second_dir)["reason"] == "writer_lease"
    else:
        assert statuses == [0] and inner_calls == ["build", "run:True", "dispose"]
    after = WriterLease(AccountScope("INTERACTIVE_BROKERS", CODE), tmp_path / "third", "after")
    after.acquire()
    after.close()


def test_another_process_cannot_choose_a_different_ibkr_account_lock(tmp_path: Path) -> None:
    first = WriterLease(AccountScope("INTERACTIVE_BROKERS", CODE), tmp_path / "first", "first")
    program = """
import sys
from pathlib import Path
from sextant.execution.custody import AccountScope, CustodyError, WriterLease
lease = WriterLease(AccountScope('INTERACTIVE_BROKERS', 'DU0000000'), Path('different'), 'second')
try:
    lease.acquire()
except CustodyError:
    sys.exit(2)
lease.close()
"""

    def other_process() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", program],
            cwd=tmp_path,
            env={"HOME": str(tmp_path), "PATH": os.defpath},
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    first.acquire()
    try:
        refused = other_process()
        assert refused.returncode == 2, refused.stderr
        assert not refused.stdout and not refused.stderr
    finally:
        first.close()
    released = other_process()
    assert released.returncode == 0, released.stderr


if __name__ == "__main__":
    _native_logging_witness(Path(sys.argv[1]))
