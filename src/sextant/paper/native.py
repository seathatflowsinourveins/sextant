"""rc7 node/strategy composition adapted from the pinned node builders.

``build_shell`` is inert: no clients, sockets, key lookup or run entrypoint.
PaperStrategy's hook counts native simulated commands, not broker wire sends.
A broker account still owes adapter-level row-8 wiring and acceptance receipts.
"""

from dataclasses import dataclass
from typing import Any, cast

from nautilus_trader.common import Environment
from nautilus_trader.config import StrategyConfig
from nautilus_trader.live import (
    LiveExecutionEngineConfig,
    LiveNode,
    LiveNodeConfig,
    LiveRiskEngineConfig,
    SubmissionRecoveryPolicy,
)
from nautilus_trader.model import (
    ClientId,
    ClientOrderId,
    Equity,
    InstrumentId,
    OrderSide,
    Price,
    Quantity,
    StrategyId,
    TimeInForce,
    TraderId,
    TrailingOffsetType,
)
from nautilus_trader.trading import Strategy

from sextant.paper.config import PaperAccount, PaperBudget
from sextant.paper.runtime import PaperIntent, PaperRuntime, PaperServices
from sextant.paper.sessions import Session, session_at


def node_config(account: PaperAccount) -> LiveNodeConfig:
    """Native defaults remain pinned SDK starts; no paper notional veto or bypass."""
    return LiveNodeConfig(
        environment=Environment.SANDBOX,
        trader_id=TraderId.from_str(f"PAPER{account.namespace}-001"),
        risk_engine=LiveRiskEngineConfig(bypass=False, max_notional_per_order={}),
        exec_engine=LiveExecutionEngineConfig(
            reconciliation=True,
            filter_unclaimed_external_orders=True,
            inflight_check_interval_ms=0,
            submission_recovery_policy=SubmissionRecoveryPolicy.RETAIN_UNRESOLVED,
        ),
    )


class PaperStrategyConfig(StrategyConfig):
    def __new__(cls, *, account: PaperAccount, budget: PaperBudget, services: PaperServices):
        # rc7's PyO3 configs initialize their native fields in __new__.
        # Its generated stub omits __new__'s keyword signature.
        return cast(Any, super().__new__)(
            cls,
            strategy_id=StrategyId.from_str(f"PAPER-{account.namespace}"),
            order_id_tag=account.namespace,
            external_order_instrument_ids=list(account.external_claims),
            use_uuid_client_order_ids=True,
        )

    def __init__(self, *, account: PaperAccount, budget: PaperBudget, services: PaperServices):
        super().__init__()
        self.account, self.budget, self.services = account, budget, services


class PaperStrategy(Strategy):
    """Native replay/sim sink shared by account plug-ins; no autonomous alpha/data subscription."""

    def __init__(self, config: PaperStrategyConfig):
        super().__init__(config)
        self.account = config.account
        self.runtime = PaperRuntime(
            config.account,
            config.budget,
            config.services,
            now_ns=lambda: self.clock.timestamp_ns(),
            send=self._dispatch,
        )

    def on_start(self):
        if not self.runtime.services.writer.held:
            self.runtime.open()

    def on_stop(self):
        self.runtime.close()

    def _dispatch(self, intent: PaperIntent, before_wire) -> None:
        iid = InstrumentId.from_str(intent.instrument)
        cid = ClientOrderId.from_str(intent.client_order_id)
        instrument = self.cache.instrument(iid)
        if not isinstance(instrument, Equity):
            raise ValueError("shared paper slice supports cached US equities only")
        client = ClientId.from_str(self.account.client_id)
        outside = session_at(self.clock.timestamp_ns()) is not Session.RTH
        params = {"extended_hours": outside} if self.account.broker == "ALPACA" else {}
        if intent.action in {"CANCEL", "MODIFY"}:
            order = self.cache.order(cid)
            if order is None or order.instrument_id != iid:
                raise ValueError("native order identity is unavailable or mismatched")
            if intent.action == "CANCEL":
                before_wire()
                self.cancel_order(cid, client_id=client)
            else:
                if outside and order.order_type.name != "LIMIT":
                    raise ValueError("outside RTH cannot amend a non-LIMIT native order")
                before_wire()
                self.modify_order(
                    cid, price=Price.from_str(str(intent.price)), client_id=client, params=params
                )
            return
        kwargs: dict[str, Any] = dict(
            instrument_id=iid,
            client_order_id=cid,
            order_side=OrderSide.BUY if intent.action == "ENTRY" else OrderSide.SELL,
            quantity=Quantity.from_str(str(intent.quantity)),
            time_in_force=TimeInForce.DAY if intent.time_in_force == "DAY" else TimeInForce.GTC,
        )
        if self.account.broker == "INTERACTIVE_BROKERS" and outside:
            overnight = session_at(self.clock.timestamp_ns()) is Session.OVERNIGHT
            kwargs["tags"] = [
                'IBOrderTags:{"outside_rth":true,"include_overnight":'
                + ("true" if overnight else "false")
                + "}"
            ]
        if intent.order_type in {"LIMIT", "STOP_LIMIT"}:
            kwargs["price"] = Price.from_str(str(intent.price))
        if intent.order_type in {"STOP_MARKET", "STOP_LIMIT"}:
            kwargs["trigger_price"] = Price.from_str(str(intent.trigger_price))
        if intent.order_type == "TRAILING_STOP_MARKET":
            kwargs["trailing_offset"] = intent.trailing_offset
            kwargs["trailing_offset_type"] = TrailingOffsetType.PRICE
        order = getattr(self.order_factory, intent.order_type.lower())(**kwargs)
        before_wire()
        self.submit_order(order, client_id=client, params=params)


@dataclass
class BuiltPaperShell:
    node: LiveNode
    strategy: PaperStrategy
    runtime: PaperRuntime

    def dispose(self) -> None:
        try:
            self.node.dispose()
        finally:
            self.runtime.close()


def build_shell(
    account: PaperAccount, budget: PaperBudget, services: PaperServices
) -> BuiltPaperShell:
    strategy = PaperStrategy(PaperStrategyConfig(account=account, budget=budget, services=services))
    strategy.runtime.open()
    node = None
    try:
        node = LiveNode.build(f"paper-{account.namespace}", node_config(account))
        node.add_strategy(strategy)
        return BuiltPaperShell(node, strategy, strategy.runtime)
    except Exception:
        if node is not None:
            node.dispose()
        strategy.runtime.close()
        raise
