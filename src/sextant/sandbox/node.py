"""Pre-stream native S node; no broker factory, credentials or network transport.

Native APIs: Nautilus rc7 55c0e8205314 LiveNodeBuilder and sandbox adapter.
Composition: northstar-trading 8256c16c31dc sim_lanes/sandbox.py and
nautilus_alpaca/factories.py. ADR-0002 requires the account issuer to equal
the simulated client name, superseding the old S0 ALPACA account prefix.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from nautilus_trader.adapters.sandbox import (
    SandboxExecutionClientConfig,
    SandboxExecutionClientFactory,
)
from nautilus_trader.common import Environment, LoggerConfig
from nautilus_trader.live import (
    DataClientConfig,
    LiveExecutionEngineConfig,
    LiveNode,
    LiveNodeConfig,
    LiveRiskEngineConfig,
)
from nautilus_trader.live.clients import DataClientFactory, MarketDataClient
from nautilus_trader.model import (
    AccountId,
    AccountType,
    ClientId,
    Money,
    OmsType,
    StrategyId,
    TraderId,
    Venue,
)


@dataclass(frozen=True)
class SandboxBinding:
    arm_id: str
    client_id: str
    account_id: str
    strategy_id: str
    order_namespace: str

    def __post_init__(self):
        if not self.arm_id or not re.fullmatch(r"S[A-Z0-9_]+", self.client_id):
            raise ValueError("explicit S client identity required")
        ClientId(self.client_id)
        AccountId(self.account_id)
        StrategyId(self.strategy_id)
        if self.account_id.split("-", 1)[0] != self.client_id:
            raise ValueError("sandbox account issuer must be its simulated client")
        if self.order_namespace != self.client_id:
            raise ValueError("order namespace must identify the simulated client")


@dataclass(frozen=True)
class SandboxPlan:
    bindings: tuple[SandboxBinding, ...]
    config: LiveNodeConfig
    clients: Any
    authority: str
    connection_state: str = "DISABLED"


def build_plan(
    *,
    bindings: tuple[SandboxBinding, ...],
    starting_balance: Money,
    leverage: Decimal,
    fee_model: Any,
    latency_model: Any,
    authority: str,
) -> SandboxPlan:
    if not bindings or any(
        len({getattr(binding, key) for binding in bindings}) != len(bindings)
        for key in ("arm_id", "client_id", "account_id", "strategy_id", "order_namespace")
    ):
        raise ValueError("sandbox arms require distinct identities and namespaces")
    if (
        not authority
        or starting_balance.as_decimal() <= 0
        or str(starting_balance.currency) != "USD"
    ):
        raise ValueError("positive USD balance and explicit model authority required")
    if type(leverage) is not Decimal or not leverage.is_finite() or leverage <= 0:
        raise ValueError("explicit finite Decimal leverage required")
    clients = {
        binding.client_id: SandboxExecutionClientConfig(
            venue=Venue("ALPACA"),
            account_id=AccountId(binding.account_id),
            starting_balances=[starting_balance],
            base_currency=starting_balance.currency,
            oms_type=OmsType.HEDGING,
            account_type=AccountType.MARGIN,
            default_leverage=leverage,
            use_random_ids=len(bindings) > 1,
            bar_execution=False,
            trade_execution=False,
            reject_stop_orders=True,
            fee_model=fee_model,
            latency_model=latency_model,
        )
        for binding in bindings
    }
    config = LiveNodeConfig(
        environment=Environment.SANDBOX,
        trader_id=TraderId("SANDBOX-001"),
        risk_engine=LiveRiskEngineConfig(bypass=False),
        exec_engine=LiveExecutionEngineConfig(reconciliation=False),
        exec_clients=clients,
    )
    return SandboxPlan(bindings, config, MappingProxyType(clients), authority)


class PrestreamFeed(MarketDataClient):
    """Native adapter seam: construction is inert; no connection is implemented."""

    async def _connect(self):
        raise RuntimeError("S feed connection disabled pending the owner's data-plan decision")

    async def _disconnect(self):
        pass


class PrestreamFeedFactory(DataClientFactory):
    @staticmethod
    def create(*, name, config, cache, clock):
        return PrestreamFeed(
            name=name, config=config, cache=cache, clock=clock, venue=Venue("ALPACA")
        )


def build_shell(plan: SandboxPlan, *, arm_id: str, strategies: tuple) -> LiveNode:
    """Build only. Live-feed activation and strategy/ledger acceptance remain separate."""
    if plan.connection_state != "DISABLED":
        raise ValueError("this build has no connection authority")
    matching = [binding for binding in plan.bindings if binding.arm_id == arm_id]
    if len(matching) != 1:
        raise ValueError("one registered arm per native S node required")
    binding = matching[0]
    expected = {binding.strategy_id}
    identities = [str(strategy.strategy_id) for strategy in strategies]
    if len(identities) != len(set(identities)) or set(identities) - expected:
        raise ValueError("strategy identity differs from sandbox bindings")
    builder = (
        LiveNode.builder(
            f"sandbox-{binding.client_id}",
            TraderId(f"{binding.client_id}-001"),
            Environment.SANDBOX,
        )
        .with_risk_engine_config(plan.config.risk_engine)
        .with_exec_engine_config(plan.config.exec_engine)
        .with_logging(LoggerConfig(bypass_logging=True))
    )
    builder.add_data_client("SFEED", PrestreamFeedFactory, DataClientConfig())
    builder.add_simulated_exec_client(
        binding.client_id, SandboxExecutionClientFactory(), plan.clients[binding.client_id]
    )
    node = builder.build()
    try:
        for strategy in strategies:
            node.add_strategy(strategy)
    except Exception:
        node.dispose()
        raise
    return node
