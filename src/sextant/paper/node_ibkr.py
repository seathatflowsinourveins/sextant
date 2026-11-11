"""The IBKR paper node entry: the official adapter only, DEFAULT-REFUSING until the lane is ON.

One command builds the IBKR paper account's live node from the engine's first-party Interactive
Brokers adapter and nothing of ours on the order path: ``InteractiveBrokersDataClientFactory``
and ``InteractiveBrokersExecutionClientFactory`` with their native configs (built by
``paper/ibkr.py``), the engine's built-in ``ExecTester`` Strategy in one of the adapter's own
execution profiles, then ``node.run()`` on the main thread (nautilus_trader v2.0.0rc8
``examples/live/interactive_brokers/exec_tester.py:83-135``,
``crates/adapters/interactive_brokers/examples/node_exec_tester.rs:241-322``,
``docs/concepts/live.md:117-120``). A timer stops it through ``LiveNodeHandle.stop()``
(``live.md:186-189``). No Gateway is started here: the Gateway's address is an argument and its
login is the owner's (``docs/integrations/interactive_brokers.md:96-125``).

Orders follow upstream's two opt-ins (``node_exec_tester.rs:181-186,257``): running the command
connects in dry run, and ``--send-orders`` is the second opt-in. Every start condition is a
named refusal, in this order: the arguments, the lane registry (``lanes/paper/ibkr.toml``
``state`` must be ON, which only a reviewed change after the owner's login word sets), the
account from its key NAME, the native configs, the main thread, the account's writer lease.
A refusal writes the receipt. The account code is never printed or written; the receipt keeps
only the sha256 of the writer scope.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import threading
import tomllib
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from nautilus_trader.adapters.interactive_brokers import (
    InteractiveBrokersDataClientFactory,
    InteractiveBrokersExecutionClientFactory,
    MarketDataType,
)
from nautilus_trader.common import Cache, DataActor, Environment, LoggerConfig, LogLevel
from nautilus_trader.config import DataActorConfig
from nautilus_trader.live import LiveNode, LiveRiskEngineConfig
from nautilus_trader.model import (
    ClientId,
    InstrumentId,
    OrderType,
    Quantity,
    StrategyId,
    TraderId,
)
from nautilus_trader.testkit import ExecTesterConfig

from sextant.execution.custody import AccountScope, CustodyError, WriterLease
from sextant.execution.state import write_atomic
from sextant.paper.config import PaperAccount, require_ibkr_paper_account
from sextant.paper.ibkr import IbkrClientConfigs, build_client_configs
from sextant.paper.sessions import Session

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "lanes/paper/ibkr.toml"
NODE_NAME = "IBKR-PAPER"
CLIENT_NAME = "IB"  # the factories' own name (factories.rs:114-116,193-195; common/consts.rs:24)
NAMESPACE = "IBKR"
WRITER = "ibkr-node"
RECEIPT = "ibkr-node-receipt.json"
PAPER_PORTS = frozenset({4002, 7497})  # Gateway and TWS paper (interactive_brokers.md:15-18)
LIVE_PORTS = frozenset({4001, 7496})
PIN = "nautechsystems/nautilus_trader@v2.0.0rc8 d53849b216e20f2c122ca01b4dd0da377638b186"
# The adapter's own execution profiles, as node_exec_tester.rs:261-322 sets them; options,
# rejection and unsupported-flags are left out (US equities only, and no deliberate denial).
PROFILES: dict[str, dict[str, Any]] = {
    "lifecycle": {"open_position_on_first_quote": True},
    "cancel-modify": {
        "enable_limit_buys": True,
        "enable_limit_sells": True,
        "modify_orders_to_maintain_tob_offset": True,
        "modify_stop_orders_to_maintain_offset": True,
        "use_individual_cancels_on_stop": True,
    },
    "stop": {
        "stop_order_type": OrderType.STOP_MARKET,
        "modify_stop_orders_to_maintain_offset": True,
    },
    "stop-limit": {"stop_order_type": OrderType.STOP_LIMIT, "stop_limit_offset_ticks": 25},
    "trailing": {"stop_order_type": OrderType.TRAILING_STOP_MARKET, "trailing_offset": Decimal(25)},
    "bracket": {
        "enable_limit_buys": True,
        "enable_limit_sells": True,
        "enable_brackets": True,
        "bracket_entry_order_type": OrderType.LIMIT,
        "bracket_offset_ticks": 500,
    },
}
for _name in ("lifecycle", "stop", "stop-limit", "trailing"):
    PROFILES[_name].update(enable_limit_buys=False, enable_limit_sells=False)
for _name in ("stop", "stop-limit", "trailing"):
    PROFILES[_name].update(enable_stop_buys=True, enable_stop_sells=True)
_WHOLE = re.compile(r"[1-9][0-9]*")


class IbkrNodeRefused(ValueError):
    """A start condition failed; ``reason`` names it and the receipt records it."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail = reason, detail
        self.receipt_dir: Path | None = None


@dataclass(frozen=True)
class NodeArguments:
    host: str
    port: int
    data_client_id: int
    exec_client_id: int
    account_id_env: str
    instrument: InstrumentId
    order_qty: Quantity
    profile: str
    send_orders: bool
    duration_s: int
    receipt_dir: Path
    lease_root: Path
    registry: Path = REGISTRY


@dataclass(frozen=True)
class Registry:
    state: str
    connection_timeout: int
    request_timeout: int
    policy: dict[str, Any]


def parse(argv: list[str] | None = None) -> NodeArguments:
    parser = argparse.ArgumentParser(prog="python -m sextant.paper.node_ibkr", allow_abbrev=False)
    required = parser.add_argument_group("required")
    for flag, kind in (
        ("--host", str),
        ("--port", int),
        ("--data-client-id", int),
        ("--exec-client-id", int),
        ("--account-id-env", str),
        ("--instrument", str),
        ("--order-qty", str),
        ("--duration-s", int),
        ("--receipt-dir", Path),
        ("--lease-root", Path),
    ):
        required.add_argument(flag, type=kind, required=True)
    required.add_argument("--profile", choices=sorted(PROFILES), required=True)
    parser.add_argument("--send-orders", action="store_true", help="upstream's second opt-in")
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    raw = parser.parse_args(argv)
    try:
        return _validate_arguments(raw)
    except IbkrNodeRefused as refusal:
        refusal.receipt_dir = raw.receipt_dir
        raise


def _validate_arguments(raw: argparse.Namespace) -> NodeArguments:
    if raw.port in LIVE_PORTS:
        raise IbkrNodeRefused("live_port", f"{raw.port} is a live trading port")
    if raw.port not in PAPER_PORTS:
        raise IbkrNodeRefused("paper_port", f"{raw.port} is neither 4002 nor 7497")
    if not raw.host or raw.duration_s <= 0:
        raise IbkrNodeRefused("arguments", "a host and a positive --duration-s are required")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", raw.account_id_env):
        raise IbkrNodeRefused("arguments", "--account-id-env takes a key NAME")
    if _WHOLE.fullmatch(raw.order_qty) is None:
        raise IbkrNodeRefused("order_qty", "a positive whole number of shares")
    try:
        instrument = InstrumentId.from_str(raw.instrument)
    except ValueError as error:
        raise IbkrNodeRefused("instrument", str(error)) from error
    return NodeArguments(
        raw.host,
        raw.port,
        raw.data_client_id,
        raw.exec_client_id,
        raw.account_id_env,
        instrument,
        Quantity.from_str(raw.order_qty),
        raw.profile,
        raw.send_orders,
        raw.duration_s,
        raw.receipt_dir,
        raw.lease_root,
        raw.registry,
    )


def load_registry(path: Path) -> Registry:
    """The lane's state and its UNCALIBRATED starts, read the way the registry proof reads them."""
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        rows = data["parameters"]
        timeouts = [
            Decimal(rows[name]["start"]) for name in ("connection_timeout", "request_timeout")
        ]
        policy = {
            name: rows[name]["start"]
            for name in (
                "use_regular_trading_hours",
                "ignore_quote_tick_size_updates",
                "batch_quotes",
            )
        }
        policy["market_data_type"] = getattr(MarketDataType, rows["market_data_type"]["start"])
        state = data["state"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError, InvalidOperation) as error:
        raise IbkrNodeRefused("registry", f"{type(error).__name__}: {error}") from error
    except AttributeError as error:
        raise IbkrNodeRefused("registry", f"market_data_type: {error}") from error
    if any(not t.is_finite() or t <= 0 or t != t.to_integral_value() for t in timeouts):
        raise IbkrNodeRefused("registry", "timeouts must be positive whole seconds")
    if any(type(policy[name]) is not bool for name in policy if name != "market_data_type"):
        raise IbkrNodeRefused("registry", "data-policy rows must be booleans")
    return Registry(state, int(timeouts[0]), int(timeouts[1]), policy)


def account(args: NodeArguments, environ: Mapping[str, str]) -> PaperAccount:
    """The paper account from its key NAME; the value is checked, never echoed."""
    code = environ.get(args.account_id_env)
    if not code:
        raise IbkrNodeRefused(
            "account", f"{args.account_id_env} is not set (with-keys supplies it)"
        )
    try:
        require_ibkr_paper_account(code)
        return PaperAccount(
            "ibkr-paper", code, CLIENT_NAME, NAMESPACE, (Session.RTH,), ib_port=args.port
        )
    except ValueError:
        raise IbkrNodeRefused("account", "not a bare D-prefixed paper account code") from None


def client_configs(
    args: NodeArguments, paper: PaperAccount, registry: Registry
) -> IbkrClientConfigs:
    try:
        return build_client_configs(
            account=paper,
            host=args.host,
            data_client_id=args.data_client_id,
            exec_client_id=args.exec_client_id,
            load_ids=frozenset({args.instrument}),
            connection_timeout=registry.connection_timeout,
            request_timeout=registry.request_timeout,
            **registry.policy,
        )
    except ValueError as error:
        raise IbkrNodeRefused("client_config", str(error)) from error


def tester_config(args: NodeArguments) -> ExecTesterConfig:
    """Upstream's tester in one profile; dry run unless the second opt-in is given."""
    profile = dict(PROFILES[args.profile])
    if profile.pop("open_position_on_first_quote", False):
        profile.update(
            open_position_on_start_qty=args.order_qty.as_decimal(),
            open_position_on_first_quote=True,
        )
    return ExecTesterConfig(
        strategy_id=StrategyId.from_str("EXEC_TESTER-001"),
        use_uuid_client_order_ids=True,
        instrument_id=args.instrument,
        client_id=ClientId.from_str(CLIENT_NAME),
        order_qty=args.order_qty,
        subscribe_quotes=True,
        subscribe_trades=False,  # exec_tester.py:119
        use_post_only=False,  # IB rejects post-only (interactive_brokers.md:425)
        reduce_only_on_stop=False,  # the adapter denies reduce-only (execution/core.rs:2191-2196)
        # Use the tester's own stop switches (exec/config.rs:172,175). IB's bulk cancel
        # deliberately ignores strategy identity (execution/core.rs:2295).
        cancel_orders_on_stop=False,
        close_positions_on_stop=False,
        dry_run=not args.send_orders,  # node_exec_tester.rs:257
        log_data=False,
        **profile,
    )


def build(args: NodeArguments, configs: IbkrClientConfigs, registry: Registry) -> LiveNode:
    """The official builder chain, offline: no client connects before ``node.run()``."""
    node = (
        LiveNode.builder(NODE_NAME, TraderId.from_str(f"PAPER{NAMESPACE}-001"), Environment.LIVE)
        # Native bypass covers all account-bearing levels/components, including errors.
        # common/src/logging/config.rs:109; common/src/python/logging.rs:49,83.
        .with_logging(
            LoggerConfig(
                stdout_level=LogLevel.OFF,
                fileout_level=LogLevel.OFF,
                bypass_logging=True,
            )
        )
        .with_reconciliation(True)
        .with_risk_engine_config(LiveRiskEngineConfig(bypass=False))
        .with_timeout_connection(registry.connection_timeout)
        .add_data_client(None, InteractiveBrokersDataClientFactory(), configs.data)
        .add_exec_client(None, InteractiveBrokersExecutionClientFactory(), configs.execution)
        .build()
    )
    node.add_builtin_strategy("ExecTester", tester_config(args))
    return node


class _CustodyAdmissionConfig(DataActorConfig):
    # The pinned Python actor config pattern (docs/concepts/actors.md:15-38).
    def __init__(self, *, args: NodeArguments, cache: Cache) -> None:
        super().__init__()
        self.args, self.cache = args, cache


class _CustodyAdmission(DataActor):
    """Read the engine's reconciled cache before the tester can start.

    live/src/node/mod.rs:535-551 reconciles before starting the trader;
    system/src/trader.rs:921-929 starts actors first and propagates failure.
    """

    def __init__(self, config: _CustodyAdmissionConfig) -> None:
        super().__init__(config)
        self.instrument = config.args.instrument
        self.tester = tester_config(config.args).strategy_id
        self.reconciled_cache = config.cache
        self.refusal: IbkrNodeRefused | None = None

    def on_start(self) -> None:
        cache = self.reconciled_cache
        visible = (
            cache.orders_open(instrument_id=self.instrument),
            cache.orders_inflight(instrument_id=self.instrument),
            cache.positions_open(instrument_id=self.instrument),
        )
        if any(item.strategy_id != self.tester for rows in visible for item in rows):
            self.refusal = IbkrNodeRefused(
                "custody",
                "instrument has orders or holdings outside the tester's ownership",
            )
            raise self.refusal


def write_receipt(args: NodeArguments, phase: str, scope: str | None = None, **body: Any) -> Path:
    write_atomic(
        args.receipt_dir / RECEIPT,
        {
            "schema": "sextant.ibkr-node.receipt/1",
            "phase": phase,
            "engine": PIN,
            "endpoint": {"host": args.host, "port": args.port},
            "client_ids": {"data": args.data_client_id, "execution": args.exec_client_id},
            "instrument": str(args.instrument),
            "profile": args.profile,
            "dry_run": not args.send_orders,
            "lease": {
                "writer": WRITER,
                "scope_sha256": scope and hashlib.sha256(scope.encode()).hexdigest(),
            },
            **body,
        },
    )
    return args.receipt_dir / RECEIPT


def run(
    args: NodeArguments,
    *,
    environ: Mapping[str, str],
    builder: Callable[[NodeArguments, IbkrClientConfigs, Registry], Any] = build,
) -> tuple[Path, int]:
    """The start conditions in order, then the node; (receipt, exit code)."""
    scope: str | None = None
    with ExitStack() as held:
        try:
            registry = load_registry(args.registry)
            if registry.state != "ON":
                raise IbkrNodeRefused("lane_off", f"{args.registry.name} state is {registry.state}")
            paper = account(args, environ)
            scope = AccountScope(paper.broker, paper.account_id).key
            configs = client_configs(args, paper, registry)
            if threading.current_thread() is not threading.main_thread():
                # run() owns the calling thread and its signals (live.md:117-120; python
                # node.rs:1075-1083); Python installs signal handlers on the main thread only.
                raise IbkrNodeRefused("main_thread", "node.run() must own the main thread")
            lease = WriterLease(
                AccountScope(paper.broker, paper.account_id), args.lease_root, WRITER
            )
            try:
                lease.acquire()
            except CustodyError as error:
                raise IbkrNodeRefused("writer_lease", str(error)) from error
            held.callback(lease.close)
            node = builder(args, configs, registry)
        except IbkrNodeRefused as refusal:
            receipt = write_receipt(
                args, "refused", scope, reason=refusal.reason, detail=refusal.detail
            )
            return receipt, 2
        write_receipt(args, "starting", scope)
        timer = threading.Timer(args.duration_s, node.handle().stop)
        timer.daemon = True
        failure = None
        admission: _CustodyAdmission | None = None
        try:
            if args.send_orders:
                admission = _CustodyAdmission(_CustodyAdmissionConfig(args=args, cache=node.cache))
                node.add_actor(admission)
            timer.start()
            node.run()
        except Exception as error:  # the run's own failure is recorded, then the exit is nonzero
            failure = f"{type(error).__name__}: {error}"
        finally:
            timer.cancel()
            node.dispose()
        del node  # the msgbus is thread-local (crates/live/src/python/node.rs:211-216)
        if admission is not None and admission.refusal is not None:
            refusal = admission.refusal
            return write_receipt(
                args,
                "refused",
                scope,
                reason=refusal.reason,
                detail=refusal.detail,
            ), 2
        phase = "failed" if failure else "stopped"
        return write_receipt(args, phase, scope, reason=failure), 2 if failure else 0


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse(argv)
    except IbkrNodeRefused as refusal:
        if refusal.receipt_dir is not None:
            write_atomic(
                refusal.receipt_dir / RECEIPT,
                {
                    "schema": "sextant.ibkr-node.receipt/1",
                    "engine": PIN,
                    "phase": "refused",
                    "reason": refusal.reason,
                    "detail": refusal.detail,
                },
            )
        print(f"ibkr node refused: {refusal}", flush=True)
        return 2
    _, code = run(args, environ=os.environ)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
