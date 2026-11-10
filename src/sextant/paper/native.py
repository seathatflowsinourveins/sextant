"""rc7/rc8 node/strategy composition adapted from the pinned node builders.

``build_shell`` registers the native ALPACA sandbox execution client, which fills
every command in-process: no socket, key lookup or run entrypoint. PaperStrategy's
hook counts native simulated commands, not broker wire sends. ``record_sandbox_run``
writes one startup receipt and appends one SIMULATED row to the one trial ledger.
A sandbox driver and live data client remain owed (#104).
"""

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from nautilus_trader.adapters.sandbox import (
    SandboxExecutionClientConfig,
    SandboxExecutionClientFactory,
)
from nautilus_trader.common import Environment
from nautilus_trader.config import StrategyConfig
from nautilus_trader.execution import FixedFeeModel
from nautilus_trader.live import (
    LiveExecutionEngineConfig,
    LiveNode,
    LiveNodeBuilder,
    LiveNodeConfig,
    LiveRiskEngineConfig,
    SubmissionRecoveryPolicy,
)
from nautilus_trader.model import (
    AccountId,
    ClientId,
    ClientOrderId,
    Equity,
    InstrumentId,
    Money,
    OrderPendingCancel,
    OrderSide,
    Price,
    Quantity,
    StrategyId,
    TimeInForce,
    TraderId,
    TrailingOffsetType,
    Venue,
)
from nautilus_trader.trading import Strategy

from sextant.paper.config import PaperAccount, PaperBudget
from sextant.paper.runtime import (
    NativeRefusal,
    PaperIntent,
    PaperRuntime,
    PaperServices,
    PendingCancel,
)
from sextant.paper.sessions import Session, session_at
from sextant.ranking.engine import Segment
from sextant.validation.trials import WITNESS_PATH, TrialLog, snapshot_hash

ROOT = Path(__file__).resolve().parents[3]
SIM_ARM_ID = "sim-sandbox"
SIM_LANE = "sim"
_RUN_ID = re.compile(r"[A-Za-z0-9._-]+")
_SHA = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


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


def sandbox_client_config(
    account: PaperAccount, starting_balance: str
) -> SandboxExecutionClientConfig:
    """Bind the native ALPACA sandbox client to its own account and the caller's balance.

    The sandbox fills every command in-process and opens no wire, so it needs no key or
    endpoint. The caller supplies the starting balance: no registry value exists, and a
    fixture default would be authority this code does not have. Native SDK defaults remain
    pinned starts; upstream northstar-trading@8256c16c31dc is the source for the explicit
    zero-fee model, the ``SIM-<namespace>`` account id and the positive-USD check.
    """
    try:
        balance = Money.from_str(starting_balance)
    except ValueError as error:
        raise ValueError(
            f"sandbox starting balance is not a Money: {starting_balance!r}"
        ) from error
    if str(balance.currency) != "USD" or balance.as_decimal() <= 0:
        raise ValueError(f"sandbox starting balance must be positive USD: {starting_balance!r}")
    return SandboxExecutionClientConfig(
        venue=Venue.from_str("ALPACA"),
        starting_balances=[balance],
        account_id=AccountId.from_str(f"SIM-{account.namespace}"),
        base_currency=balance.currency,
        fee_model=FixedFeeModel(Money.from_str("0 USD")),
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
            prepare=self._prepare,
        )

    def on_start(self):
        if not self.runtime.services.writer.held:
            self.runtime.open()

    def on_stop(self):
        self.runtime.close()

    def _prepare(self, intent: PaperIntent) -> Callable[[], None]:
        """Validate and build one native command; the runtime runs it after its own hook.

        Building is the native OrderFactory's and sending is Strategy's submit_order,
        cancel_order or modify_order. The command reaches a wire only through the native
        RiskEngine and the ExecutionEngine's registered client, which denies anything else
        (rc8 crates/execution/src/engine/mod.rs:2191-2205, OrderDeniedReason::NoExecutionClient).
        """
        try:
            iid = InstrumentId.from_str(intent.instrument)
            cid = ClientOrderId.from_str(intent.client_order_id)
        except ValueError as error:  # a venue-less symbol such as 'AAPL' (#163 gate P3)
            raise NativeRefusal(str(error)) from error
        instrument = self.cache.instrument(iid)
        if not isinstance(instrument, Equity):
            raise NativeRefusal("shared paper slice supports cached US equities only")
        client = ClientId.from_str(self.account.client_id)
        outside = session_at(self.clock.timestamp_ns()) is not Session.RTH
        params = {"extended_hours": outside} if self.account.broker == "ALPACA" else {}
        if intent.action in {"CANCEL", "MODIFY"}:
            order = self.cache.order(cid)
            if order is None or order.instrument_id != iid:
                raise NativeRefusal("native order identity is unavailable or mismatched")
            if intent.action == "CANCEL":
                # rc8's Strategy.cancel_order logs and drops these (crates/trading/src/strategy/
                # mod.rs:629-631, 822-827): refuse before the token (#187). The stamp is rc8's
                # latest OrderPendingCancel, the clock as the cancel left (:891-911). A partial fill
                # keeps the order pending but moves ts_last (model/src/orders/mod.rs:1380-1402).
                if order.is_closed:
                    raise NativeRefusal("native order is already closed")
                if order.is_pending_cancel:
                    left = [e.ts_event for e in order.events() if isinstance(e, OrderPendingCancel)]
                    raise PendingCancel(left[-1])
                return lambda: self.cancel_order(cid, client_id=client)
            if outside and order.order_type.name != "LIMIT":
                raise NativeRefusal("outside RTH cannot amend a non-LIMIT native order")
            price = _exact(intent.price, instrument.price_precision, Price.from_str)
            return lambda: self.modify_order(cid, price=price, client_id=client, params=params)
        kwargs: dict[str, Any] = dict(
            instrument_id=iid,
            client_order_id=cid,
            order_side=OrderSide.BUY if intent.action == "ENTRY" else OrderSide.SELL,
            quantity=_exact(intent.quantity, instrument.size_precision, Quantity.from_str),
            time_in_force=TimeInForce.DAY if intent.time_in_force == "DAY" else TimeInForce.GTC,
        )
        if self.account.broker == "INTERACTIVE_BROKERS" and outside:
            overnight = session_at(self.clock.timestamp_ns()) is Session.OVERNIGHT
            kwargs["tags"] = [
                'IBOrderTags:{"outside_rth":true,"include_overnight":'
                + ("true" if overnight else "false")
                + "}"
            ]
        bounds = instrument.min_quantity, instrument.max_quantity
        if (bounds[0] is not None and kwargs["quantity"] < bounds[0]) or (
            bounds[1] is not None and kwargs["quantity"] > bounds[1]
        ):  # rc8's RiskEngine denies these after the token (risk/src/engine/mod.rs:1782-1799);
            # node_config sets no full_position_exit_venues, so rc8 applies them to every order
            raise NativeRefusal("quantity outside the instrument's minimum and maximum (#187)")
        if intent.order_type in {"LIMIT", "STOP_LIMIT"}:
            kwargs["price"] = _exact(intent.price, instrument.price_precision, Price.from_str)
        if intent.order_type in {"STOP_MARKET", "STOP_LIMIT"}:
            trigger = _exact(intent.trigger_price, instrument.price_precision, Price.from_str)
            kwargs["trigger_price"] = trigger
        if intent.order_type == "TRAILING_STOP_MARKET":
            kwargs["trailing_offset"] = intent.trailing_offset
            kwargs["trailing_offset_type"] = TrailingOffsetType.PRICE
        try:
            order = getattr(self.order_factory, intent.order_type.lower())(**kwargs)
        except ValueError as error:  # a native shape refusal, before the hook
            raise NativeRefusal(str(error)) from error
        return lambda: self.submit_order(order, client_id=client, params=params)

    def on_order_denied(self, event) -> None:
        """rc7 denies on this node, before any venue: custody releases the registration."""
        self.runtime.denied(str(event.client_order_id), str(event.reason))


def _exact(value, precision: int, make):
    """rc7's RiskEngine denies a finer precision after submit; refuse it before the hook.

    The value must be representable at the instrument's precision; trailing zeros are fine,
    so 9.990 builds as 9.99 and 10.0 shares as 10 (#163 #88 review).
    """
    step, number = Decimal(1).scaleb(-precision), None
    try:
        number = Decimal(str(value))
        exact = number.quantize(step) if number.is_finite() else None
    except InvalidOperation:  # an absurd magnitude such as 1E+30 (#163 gate P3)
        exact = None
    if exact is None or exact != number:
        raise NativeRefusal(
            f"{value} is not representable at the instrument's precision {precision}"
        )
    try:
        return make(format(exact, "f"))
    except ValueError as error:  # outside rc7's Price or Quantity range, such as 1E+20
        raise NativeRefusal(str(error)) from error


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


def _head_sha() -> str:
    """The ledger's implementation identity; mirrors the C lane's reader."""
    try:
        raw = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(f"cannot read HEAD for the trial ledger: {error}") from error
    if _SHA.fullmatch(raw) is None:
        raise ValueError(f"HEAD is not a 40-hex implementation sha: {raw!r}")
    return raw


def record_sandbox_run(
    *,
    account: PaperAccount,
    run_id: str,
    symbols: Sequence[str],
    segment: Segment,
    started_ns: int,
    starting_balance: str,
    entry_params_hash: str,
    ledger_path: Path = WITNESS_PATH,
    reports_dir: Path = Path("reports/sim"),
) -> Path:
    """Write one startup receipt and append exactly one SIMULATED row.

    The run id is the receipt's name and the ledger's ``arm_run_id``: a retry with the
    same id is refused by TrialLog, never silently counted twice. The receipt is written
    first, so a ledger refusal leaves the run auditable instead of erasing its identity.
    This records a start only; the sandbox driver and its stop receipt remain owed (#104).
    """
    if _RUN_ID.fullmatch(run_id) is None or run_id in {".", ".."}:
        raise ValueError(f"sandbox run id is not a file-name-safe token: {run_id!r}")
    if _SHA256.fullmatch(entry_params_hash) is None:
        raise ValueError(f"entry_params_hash is not a sha256 hex digest: {entry_params_hash!r}")
    client_config = sandbox_client_config(account, starting_balance)
    block_set_id = f"sim:{segment.session_date.isoformat()}:{segment.name}:{started_ns}"
    sandbox_config = {
        "tier": "SIMULATED",
        "venue": str(client_config.venue),
        "account_id": str(client_config.account_id),
        "starting_balance": str(client_config.starting_balances[0]),
        "block_set_id": block_set_id,
    }
    symbol_list = [str(symbol) for symbol in symbols]
    params = {
        "symbols": symbol_list,
        "segment": segment.name,
        "session_date": segment.session_date.isoformat(),
        "started_ns": started_ns,
        "entry_params_hash": entry_params_hash,
    }
    identity = {
        "arm_id": SIM_ARM_ID,
        "arm_run_id": run_id,
        "implementation_sha": _head_sha(),
        "factor_mask": [],
        "sandbox_config": sandbox_config,
        "sandbox_config_hash": snapshot_hash(sandbox_config),
        "evidence_weights": {},
        "evidence_weights_hash": snapshot_hash({}),
        "params_hash": snapshot_hash(params),
        "tier": "SIMULATED",
        "block_set_id": block_set_id,
        "funding_divergent_session_count": None,
        "funding_unverified_session_count": None,
        "condition_returns": {},
    }
    payload = {
        "tier": "SIMULATED",
        "lane": SIM_LANE,
        "account_suffix": account.namespace,
        "receipt_id": run_id,
        "symbols": symbol_list,
        "entry_params_hash": entry_params_hash,
        "sandbox_config": sandbox_config,
        "sandbox_config_hash": identity["sandbox_config_hash"],
        "params_hash": identity["params_hash"],
        "implementation_sha": identity["implementation_sha"],
        "started_ns": started_ns,
        "stopped_ns": None,
        "final_segment": None,
        "segment": {
            "name": segment.name,
            "session_date": segment.session_date.isoformat(),
            "start_ns": segment.start_ns,
            "end_ns": segment.end_ns,
        },
    }
    receipt = reports_dir / run_id / "session.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    TrialLog(ledger_path).append(SIM_ARM_ID, params, identity, None, state="RUNNING")
    return receipt


def build_shell(
    account: PaperAccount,
    budget: PaperBudget,
    services: PaperServices,
    *,
    starting_balance: str,
) -> BuiltPaperShell:
    client_config = sandbox_client_config(account, starting_balance)
    strategy = PaperStrategy(PaperStrategyConfig(account=account, budget=budget, services=services))
    strategy.runtime.open()
    node = None
    try:
        node = (
            LiveNodeBuilder.from_config(f"paper-{account.namespace}", node_config(account))
            .add_simulated_exec_client(
                account.client_id, SandboxExecutionClientFactory(), client_config
            )
            .build()
        )
        node.add_strategy(strategy)
        return BuiltPaperShell(node, strategy, strategy.runtime)
    except Exception:
        if node is not None:
            node.dispose()
        strategy.runtime.close()
        raise
