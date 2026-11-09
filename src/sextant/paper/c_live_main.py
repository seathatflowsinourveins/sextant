"""Run the C first-leg node in the foreground against Alpaca paper account C.

The runner follows the merged B precedent (``b_protector_main.py``): keys and the
expected account come only from the environment, every broker call after the
startup checks goes through the repo's account pacer, one writer lease owns the
account, and SIGTERM/SIGINT stop the stream without cancelling the broker-held
trail.  The C decision core (``c_session.py``) is unchanged: this module only
wires it to alpaca-py's trading client (v0.44.0
``examples/stocks/stocks-trading-basic.ipynb`` cells 25-36), selects SIP in the
day sessions and BOATS overnight, loads the current segment's baseline, submits
the one witness-size LIMIT entry, then the native GTC trailing stop in RTH or a
resting GTC LIMIT at the ADR-0025 trail price outside it, re-priced as the trail
rises.

The account config is a JSON object with ``PaperAccount``'s fields: ``lane``,
``account_id``, ``client_id``, ``namespace`` and ``sessions``.  The fetched
broker account number is compared to ``C_EXPECTED_ACCOUNT_SUFFIX`` and never
printed; the receipt carries only its last four characters.  The run is paper
only: ``TradingClient(paper=True)`` and no live endpoint.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from types import FrameType
from typing import Any, Protocol, cast

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    ReplaceOrderRequest,
    TrailingStopOrderRequest,
)
from nautilus_trader.model import Currency, Equity, InstrumentId, Price, Quantity, Symbol

from sextant.entry.parameters import EntryParameters
from sextant.entry.slots import Candidate, SlotPool
from sextant.execution.alpaca import OrderCommand
from sextant.execution.custody import (
    AccountScope,
    AccountSnapshot,
    Custody,
    CustodyError,
    OrderFact,
    PositionAuthority,
    WriterLease,
)
from sextant.execution.pacer import AccountPacer, ActionKind
from sextant.paper.alpaca_feed import AlpacaTickFeed
from sextant.paper.c_session import CConfig, CSession
from sextant.paper.c_universe import rank_universe
from sextant.paper.config import PaperAccount
from sextant.paper.sessions import Session
from sextant.ranking.baseline import BaselineTable, load_baseline, segment_start
from sextant.ranking.engine import Segment
from sextant.risk.controls import Controls
from sextant.risk.guard import Guard
from sextant.validation.trials import WITNESS_PATH, TrialLog, snapshot_hash

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTROLS = ROOT / "lanes/custody-parameters.json"
DEFAULT_ENTRY_PARAMETERS = ROOT / "lanes/sim/entry-parameters.json"
CONFIG_KEYS = frozenset({"lane", "account_id", "client_id", "namespace", "sessions"})
C_LANE = "alpaca-paper-c"
KEY_NAMES = ("ALPACA_PAPER_3_API_KEY", "ALPACA_PAPER_3_SECRET_KEY")
EXPECTED_SUFFIX_ENV = "C_EXPECTED_ACCOUNT_SUFFIX"
DEFAULT_CLIENT_FACTORY: Callable[..., Any] = cast(Callable[..., Any], TradingClient)
DEFAULT_DATA_FACTORY: Callable[..., Any] = cast(Callable[..., Any], StockHistoricalDataClient)
C_ARM_ID = "paper-c-24x5"
POLL_INTERVAL_S = 0.5
ORDER_TIMEOUT_S = 30.0
OPEN_ORDER_LIMIT = 500
STOP_STATUSES = frozenset(
    {"CANCELED", "CANCELLED", "DONE_FOR_DAY", "EXPIRED", "REJECTED", "REPLACED", "STOPPED"}
)
SEGMENT_BASELINES = {
    "OVERNIGHT": "overnight.json",
    "PRE": "pre.json",
    "RTH": "rth.json",
    "POST": "post.json",
}
_NS_PER_S = 1_000_000_000
_SHA = re.compile(r"[0-9a-f]{40}")
_PROTECTION_ACKS = frozenset({"NEW", "ACCEPTED", "PENDING_NEW", "PARTIALLY_FILLED"})
_PROTECTION_GONE = frozenset({"CANCELED", "CANCELLED", "REPLACED"})


class LiveRefusal(RuntimeError):
    """The C runner will not act, or cannot know an order's state; it stops."""


class PacerRefused(RuntimeError):
    """The account pacer did not admit a broker call; the caller must fail closed."""


class TradingClientLike(Protocol):
    """The alpaca-py trading surface this runner uses, kept explicit for the fake."""

    def get_account(self) -> Any: ...

    def get_all_positions(self) -> Any: ...

    def get_orders(self, filter: Any = None) -> Any: ...

    def get_all_assets(self, filter: Any = None) -> Any: ...

    def get_asset(self, symbol_or_asset_id: object) -> Any: ...

    def get_order_by_id(self, order_id: object) -> Any: ...

    def submit_order(self, order_data: Any) -> Any: ...

    def cancel_order_by_id(self, order_id: object) -> Any: ...

    def replace_order_by_id(self, order_id: object, order_data: Any) -> Any: ...


class PacedTradingClient:
    """Route every broker read and write through the repo's existing account pacer."""

    def __init__(self, client: TradingClientLike, pacer: Any) -> None:
        self._client = client
        self._pacer = pacer

    def _call(self, kind: ActionKind, method: Callable[..., Any], *args: Any) -> Any:
        results: list[Any] = []
        state = {"cancelled": False}

        def send(before_wire: Callable[[], None]) -> None:
            before_wire()
            results.append(method(*args))

        def admission() -> bool:
            return not state["cancelled"]

        self._pacer.request(kind, send, admission=admission)
        if not results:
            state["cancelled"] = True
            raise PacerRefused(f"the account pacer did not admit {method.__name__}")
        return results[0]

    def get_account(self) -> Any:
        return self._call(ActionKind.QUERY, self._client.get_account)

    def get_all_positions(self) -> Any:
        return self._call(ActionKind.QUERY, self._client.get_all_positions)

    def get_orders(self, filter: Any = None) -> Any:
        return self._call(ActionKind.QUERY, self._client.get_orders, filter)

    def get_all_assets(self, filter: Any = None) -> Any:
        return self._call(ActionKind.QUERY, self._client.get_all_assets, filter)

    def get_asset(self, symbol_or_asset_id: object) -> Any:
        return self._call(ActionKind.QUERY, self._client.get_asset, symbol_or_asset_id)

    def get_order_by_id(self, order_id: object) -> Any:
        return self._call(ActionKind.QUERY, self._client.get_order_by_id, order_id)

    def submit_order(self, order_data: Any, *, kind: ActionKind) -> Any:
        return self._call(kind, self._client.submit_order, order_data)

    def cancel_order_by_id(self, order_id: object) -> Any:
        return self._call(ActionKind.CANCEL, self._client.cancel_order_by_id, order_id)

    def replace_order_by_id(self, order_id: object, order_data: Any) -> Any:
        return self._call(ActionKind.MODIFY, self._client.replace_order_by_id, order_id, order_data)


@dataclass
class RunRecord:
    """What the session did, for the receipt and the one trial-ledger row."""

    started_ns: int = 0
    stopped_ns: int | None = None
    commands: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    protection_cid: str | None = None
    dry_run: bool = False
    snapshot: dict[str, Any] = field(default_factory=dict)
    flags: int = 0
    receipt_id: str = ""
    armings: list[dict[str, Any]] = field(default_factory=list)


def load_account_config(path: Path) -> PaperAccount:
    """Read the C account config and let PaperAccount validate it."""

    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path.name}") from exc
    if not isinstance(data, dict) or set(data) != CONFIG_KEYS:
        raise ValueError("C account config has the wrong keys")
    if data.get("lane") != C_LANE:
        raise ValueError(f"C account config must name {C_LANE}")
    for key in ("lane", "account_id", "client_id", "namespace"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"C account config needs a nonempty {key}")
    sessions = data["sessions"]
    if (
        not isinstance(sessions, list)
        or not sessions
        or any(not isinstance(name, str) for name in sessions)
    ):
        raise ValueError("C account config needs a nonempty sessions list")
    try:
        parsed_sessions = tuple(Session[name.upper()] for name in sessions)
    except KeyError as exc:
        raise ValueError(f"C account config has an unknown session: {exc.args[0]}") from exc
    return PaperAccount(
        lane=data["lane"],
        account_id=data["account_id"],
        client_id=data["client_id"],
        namespace=data["namespace"],
        sessions=parsed_sessions,
    )


def _plain_decimal(value: object) -> Decimal:
    """Read a vendor number as Decimal text; the input is never float arithmetic."""

    if isinstance(value, Decimal):
        return value
    text = str(value)
    if not text or text.lower() in {"none", "nan", "inf", "-inf"}:
        raise ValueError("a finite asset price increment is required")
    return Decimal(text)


_N4_SUB_DOLLAR_TICK = Decimal("0.0001")


def _equity_ladder(asset: object) -> tuple[int, Decimal]:
    """Return the Equity precision and tick for an Alpaca US-equity asset.

    alpaca-py's ``Asset.price_increment`` is ``None`` for US equities (the paper
    OMH asset returns None), so the vendor field cannot be the only source.
    N4's ladder (``src/sextant/entry/orders.py``: 0.0001 below $1, else 0.01,
    Alpaca Orders as cited in ADR-0004) is the authority.  The finer tick is
    carried here so a sub-$1 name is not rounded up to a penny; ``limit_price``
    applies the $1 branch when it rounds the order, so an at/above-$1 limit is
    still emitted at 2 dp.
    """

    raw = getattr(asset, "price_increment", None)
    if raw is not None:
        try:
            increment = _plain_decimal(raw).normalize()
        except (TypeError, ValueError):
            increment = Decimal(0)
        if increment.is_finite() and increment > 0:
            exponent = increment.as_tuple().exponent
            if isinstance(exponent, int):
                return max(0, -exponent), increment
    return 4, _N4_SUB_DOLLAR_TICK


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _price_text(increment: Decimal) -> str:
    text = str(increment)
    return format(increment, "f") if "e" in text.lower() else text


def _status(order: Any) -> str:
    status = getattr(order, "status", None)
    return str(getattr(status, "value", status)).upper()


def _order_id(order: Any) -> str | None:
    identifier = getattr(order, "id", None)
    return None if identifier is None else str(identifier)


def _filled(order: Any) -> Decimal:
    raw = getattr(order, "filled_qty", None)
    if raw is None:
        raise LiveRefusal("a filled order has no filled quantity")
    value = Decimal(str(raw))
    if not value.is_finite() or value <= 0:
        raise LiveRefusal("a filled order needs a positive filled quantity")
    return value


def _await_order(
    client: PacedTradingClient,
    cid: str,
    ack: Any,
    *,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    poll_interval_s: float,
    timeout_s: float,
) -> Any:
    """Poll the acknowledged order; never resubmit and never guess its state."""

    order = ack
    deadline = monotonic() + timeout_s
    while True:
        status = _status(order)
        if status == "FILLED":
            return order
        if status in STOP_STATUSES:
            raise LiveRefusal(f"order {cid} ended {status}")
        current = monotonic()
        if current >= deadline:
            raise LiveRefusal(
                f"order {cid} state unknown after {timeout_s:g}s; it was not resubmitted"
            )
        sleep(min(poll_interval_s, deadline - current))
        order = client.get_order_by_id(cid)


def _house_cid(account: PaperAccount, command: OrderCommand) -> str:
    """A deterministic house id for the one session that supplies none (it always does)."""

    symbol = command.instrument.rsplit(".", 1)[0]
    return (
        f"{account.house_prefix}{symbol}-{command.side.lower()}-"
        f"{command.order_type.lower()}-{command.quantity}"
    )


def _command_payload(command: OrderCommand, cid: str) -> dict[str, Any]:
    return {
        "client_order_id": cid,
        "instrument": command.instrument,
        "side": command.side,
        "quantity": str(command.quantity),
        "order_type": command.order_type,
        "time_in_force": command.time_in_force,
        "limit_price": None if command.limit_price is None else str(command.limit_price),
        "trail_price": None if command.trail_price is None else str(command.trail_price),
    }


def _record_row(
    run: RunRecord,
    *,
    cid: str,
    kind: str,
    side: str,
    quantity: Decimal,
    limit_price: Decimal | None,
    trail_price: Decimal | None,
    status: str,
    segment: str,
) -> dict[str, Any]:
    row = {
        "cid": cid,
        "kind": kind,
        "side": side,
        "qty": _decimal_text(quantity),
        "limit": None if limit_price is None else _decimal_text(limit_price),
        "trail": None if trail_price is None else _decimal_text(trail_price),
        "ack": "",
        "fill": "0",
        "status": status,
        "venue_id": "",
        "segment": segment,
    }
    run.commands.append(row)
    return row


def _record_command(
    run: RunRecord,
    command: OrderCommand,
    cid: str,
    *,
    status: str,
    segment: str,
) -> dict[str, Any]:
    return _record_row(
        run,
        cid=cid,
        kind=command.order_type,
        side=command.side,
        quantity=command.quantity,
        limit_price=command.limit_price,
        trail_price=command.trail_price,
        status=status,
        segment=segment,
    )


def _request_for(command: OrderCommand, cid: str, *, extended_hours: bool) -> Any:
    symbol = command.instrument.rsplit(".", 1)[0]
    if command.order_type == "LIMIT" and command.limit_price is not None:
        return LimitOrderRequest(
            symbol=symbol,
            qty=command.quantity,
            side=OrderSide.BUY if command.side == "BUY" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY if command.time_in_force == "DAY" else TimeInForce.GTC,
            limit_price=command.limit_price,
            client_order_id=cid,
            extended_hours=extended_hours,
        )
    if (
        command.order_type == "TRAILING_STOP"
        and command.side == "SELL"
        and command.trail_price is not None
    ):
        return TrailingStopOrderRequest(
            symbol=symbol,
            qty=command.quantity,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            trail_percent=command.trail_price,  # the session emits a percent, not a fraction
            client_order_id=cid,
        )
    raise LiveRefusal(f"unsupported C order shape: {command.order_type} {command.side}")


def _write_receipt(
    *,
    account: PaperAccount,
    account_suffix: str,
    symbols: Sequence[str],
    run: RunRecord,
    baseline: BaselineTable | None,
    segment: Segment,
    entry_params_hash: str,
    final_segment: str,
    stamp: str,
) -> Path:
    payload = {
        "tier": "BROKER-PAPER",
        "lane": account.lane,
        "account_suffix": account_suffix,
        "receipt_id": run.receipt_id,
        "symbols": list(symbols),
        "arming": run.armings,
        "commands": run.commands,
        "protection_cid": run.protection_cid,
        "errors": run.errors,
        "baseline": None
        if baseline is None
        else {
            "provenance": baseline.provenance,
            "known_at": baseline.known_at,
            "feed": baseline.feed,
        },
        "entry_params_hash": entry_params_hash,
        "dry_run": run.dry_run,
        "started_ns": run.started_ns,
        "stopped_ns": run.stopped_ns,
        "final_segment": final_segment,
        "segment": {
            "name": segment.name,
            "session_date": segment.session_date.isoformat(),
            "start_ns": segment.start_ns,
            "end_ns": segment.end_ns,
        },
    }
    path = Path("reports/paper-c") / stamp / "session.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def _trial_config(segment: Segment, started_ns: int) -> dict[str, str]:
    return {
        "tier": "BROKER-PAPER",
        "block_set_id": (f"paper-c:{segment.session_date.isoformat()}:{segment.name}:{started_ns}"),
    }


def _head_sha() -> str:
    """The full HEAD commit, or a refusal; the ledger admits only 40 lowercase hex."""

    try:
        raw = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LiveRefusal(f"cannot read HEAD for the trial ledger: {exc}") from exc
    if _SHA.fullmatch(raw) is None:
        raise LiveRefusal(f"HEAD is not a 40-hex implementation sha: {raw!r}")
    return raw


def _custody_open(book: Custody) -> int | None:
    """Count open positions the slot pool must charge before arming new symbols."""

    snapshot = book.snapshot
    if snapshot is None:
        return None
    return sum(1 for quantity in snapshot.positions.values() if quantity > 0)


@dataclass(frozen=True)
class _Arming:
    eligible: int
    slots: int
    armed: tuple[str, ...]
    custody_open: int | None
    reason: str


def _arm_universe(
    *,
    client: PacedTradingClient,
    data: Any,
    segment: Segment,
    custody_open: int | None,
    now: datetime,
) -> tuple[_Arming, str | None]:
    """Rank the eligible 24/5 universe and let the 0.4 slot pool pick the session's symbols."""

    try:
        ranked = rank_universe(client, data, segment.name.lower(), now=now)
    except Exception as exc:  # the broker/data surface must fail closed, not arm blindly
        return (
            _Arming(0, 0, (), custody_open, "universe ranking failed"),
            f"refused: the {segment.name} universe ranking failed: {type(exc).__name__}: {exc}",
        )
    if not ranked:
        reason = f"no eligible symbols for the {segment.name} session"
        return _Arming(0, 0, (), custody_open, reason), f"refused: {reason}"
    candidates = tuple(Candidate(f"{row.symbol}.ALPACA", index) for index, row in enumerate(ranked))
    allocation = SlotPool().allocate(candidates, custody_open=custody_open)
    reason = (
        f"slot pool {allocation.reason}: eligible={len(ranked)} slots={allocation.slots} "
        f"custody_open={custody_open}"
    )
    arming = _Arming(len(ranked), allocation.slots, tuple(allocation.armed), custody_open, reason)
    if not allocation.armed:
        return arming, f"refused: {reason}"
    return arming, None


def _record_arming(run: RunRecord, segment: Segment, arming: _Arming) -> None:
    run.armings.append(
        {
            "segment": segment.name,
            "eligible": arming.eligible,
            "slots": arming.slots,
            "armed": list(arming.armed),
            "custody_open": arming.custody_open,
            "reason": arming.reason,
        }
    )


def _record_trial(
    *,
    ledger_path: Path,
    run: RunRecord,
    baseline: BaselineTable | None,
    symbols: Sequence[str],
    segment: Segment,
    entry_params_hash: str,
    failure: str | None,
) -> None:
    """Append one BROKER-PAPER row with the full ADR-0018 identity; counts, never a P&L claim."""

    entries = sum(1 for row in run.commands if row["kind"] == "LIMIT" and row["side"] == "BUY")
    fills = sum(1 for row in run.commands if Decimal(str(row["fill"])) > 0)
    params = {
        "symbols": list(symbols),
        "arming": run.armings,
        "segment": segment.name,
        "session_date": segment.session_date.isoformat(),
        "flags": run.flags,
        "entries": entries,
        "fills": fills,
        "protection_cid": run.protection_cid or "",
        "dry_run": run.dry_run,
        "commands": run.commands,
        "errors": list(run.errors),
        "baseline_known_at": None if baseline is None else baseline.known_at,
        "baseline_provenance": "" if baseline is None else baseline.provenance,
        "entry_params_hash": entry_params_hash,
    }
    sandbox = _trial_config(segment, run.started_ns)
    # TrialLog validates params_hash as snapshot_hash(params), so the registry
    # digest travels inside params as entry_params_hash instead.
    identity = {
        "arm_id": C_ARM_ID,
        "arm_run_id": run.receipt_id,
        "implementation_sha": _head_sha(),
        "factor_mask": [],
        "sandbox_config": sandbox,
        "sandbox_config_hash": snapshot_hash(sandbox),
        "evidence_weights": {},
        "evidence_weights_hash": snapshot_hash({}),
        "params_hash": snapshot_hash(params),
        "tier": "BROKER-PAPER",
        "block_set_id": sandbox["block_set_id"],
        "funding_divergent_session_count": None,
        "funding_unverified_session_count": None,
        "condition_returns": {},
    }
    state = "FAIL" if failure is not None else "COMPLETE"
    TrialLog(ledger_path).append(
        C_ARM_ID,
        params,
        identity,
        None,
        state=state,
        error="" if failure is None else failure,
    )


@dataclass
class _LimitProtection:
    """A resting limit exit that stands in for the RTH-only native trail."""

    instrument: str
    entry_cid: str
    cid: str
    venue_id: str
    quantity: Decimal
    fill_price: Decimal
    limit_price: Decimal
    hwm: Decimal
    replacements: int = 0


def _segment_baseline(
    baseline: Path | None, baseline_dir: Path | None, segment: Segment
) -> BaselineTable:
    if baseline is not None:
        path = baseline
    elif baseline_dir is not None:
        path = Path(baseline_dir) / SEGMENT_BASELINES[segment.name]
    else:
        raise LiveRefusal("no baseline source was given")
    try:
        return load_baseline(path.read_text())
    except (OSError, ValueError) as exc:
        raise LiveRefusal(f"the {segment.name} baseline is unavailable at {path}: {exc}") from exc


def _feed_for(segment: Segment) -> str:
    return "boats" if segment.name == "OVERNIGHT" else "sip"


def _attribute(asset: object, name: str) -> bool:
    """Read the Assets API attribute list the way the live model carries it.

    alpaca-py v0.44.0 has no top-level ``overnight_tradable`` on ``Asset``; the
    live GET /v2/assets response carries the flag in ``attributes``.
    """
    values = getattr(asset, "attributes", None) or ()
    if isinstance(values, str):
        values = (values,)
    return any(str(item).lower() == name for item in values)


def _require_eligible(asset: object, symbol: str, segment: Segment) -> None:
    if getattr(asset, "tradable", None) is not True:
        raise LiveRefusal(f"{symbol} is not tradable")
    if segment.name != "OVERNIGHT":
        return
    overnight_tradable = getattr(asset, "overnight_tradable", None) is True or _attribute(
        asset, "overnight_tradable"
    )
    if getattr(asset, "overnight_halted", None) is True or _attribute(asset, "overnight_halted"):
        raise LiveRefusal(f"{symbol} is not overnight-eligible (overnight_halted)")
    if overnight_tradable is not True:
        raise LiveRefusal(
            f"{symbol} is not overnight-eligible "
            f"(attributes={getattr(asset, 'attributes', None)!r})"
        )


def _instruments_for(
    client: PacedTradingClient, symbols: Sequence[str], segment: Segment
) -> dict[str, Equity]:
    instruments: dict[str, Equity] = {}
    for full_id in symbols:
        try:
            iid = InstrumentId.from_str(full_id)
        except ValueError as exc:
            raise LiveRefusal(f"bad instrument id {full_id}") from exc
        if str(iid.venue) != "ALPACA":
            raise LiveRefusal(f"{full_id} is not an ALPACA instrument")
        asset = client.get_asset(iid.symbol.value)
        _require_eligible(asset, iid.symbol.value, segment)
        precision, increment = _equity_ladder(asset)
        instruments[full_id] = Equity(
            iid,
            Symbol(iid.symbol.value),
            Currency.from_str("USD"),
            precision,
            Price.from_str(_price_text(increment)),
            0,
            0,
            lot_size=Quantity.from_int(1),
        )
    return instruments


def _fill_price(order: Any) -> Decimal:
    raw = getattr(order, "filled_avg_price", None)
    if raw is None:
        raise LiveRefusal(
            "the filled entry has no average price; the ADR-0025 limit exit cannot be priced"
        )
    try:
        price = _plain_decimal(raw)
    except (TypeError, ValueError) as exc:
        raise LiveRefusal(f"the filled entry average price is invalid: {exc}") from exc
    if price <= 0:
        raise LiveRefusal("the filled entry average price is not positive")
    return price


def _filled_quantity(order: Any) -> Decimal:
    raw = getattr(order, "filled_qty", None)
    if raw is None:
        return Decimal(0)
    try:
        filled = _plain_decimal(raw)
    except (TypeError, ValueError):
        return Decimal(0)
    return filled if filled > 0 else Decimal(0)


def _trail_limit(price: Decimal, trail_fraction: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0:
        raise LiveRefusal("the instrument has no positive price increment")
    steps = (price * (Decimal(1) - trail_fraction) / increment).to_integral_value(
        rounding=ROUND_FLOOR
    )
    limit = steps * increment
    if limit <= 0:
        raise LiveRefusal("the ADR-0025 trail price is not positive")
    return limit


def _await_cancel(
    client: PacedTradingClient,
    order_id: str,
    *,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    poll_interval_s: float,
    timeout_s: float,
) -> Any:
    deadline = monotonic() + timeout_s
    settled = _PROTECTION_GONE | {"FILLED"}
    while True:
        order = client.get_order_by_id(order_id)
        status = _status(order)
        if status in settled:
            return order
        if status in STOP_STATUSES:
            raise LiveRefusal(f"the protection order {order_id} ended {status}")
        now = monotonic()
        if now >= deadline:
            raise LiveRefusal(
                f"the protection order {order_id} did not settle after {timeout_s:g}s"
            )
        sleep(min(poll_interval_s, deadline - now))


def _flag_count(snapshot: dict[str, Any]) -> int:
    return sum(
        1
        for key, state in snapshot.items()
        if key != "params_hash" and isinstance(state, dict) and state.get("flag_ts") is not None
    )


def _config_for(
    symbols: Sequence[str],
    params: EntryParameters,
    segment: Segment,
    *,
    slot_count: int = 2,
) -> CConfig:
    return CConfig(
        symbols=tuple(symbols),
        chase_cap_fraction=Decimal("0.03"),  # 0.03 = the recorded first_leg_max_move
        trail_fraction=Decimal("0.025"),  # ADR-0025 C-scope, UNCALIBRATED
        slot_count=slot_count,  # --symbols keeps ADR-0024's 2-of-5; --universe uses the pool
        segment=segment,
        params=params,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[..., TradingClientLike] = DEFAULT_CLIENT_FACTORY,
    data_factory: Callable[..., Any] = DEFAULT_DATA_FACTORY,
    feed_factory: Callable[..., Any] = AlpacaTickFeed,
    now_ns: Callable[[], int] = time.time_ns,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    poll_interval_s: float = POLL_INTERVAL_S,
    order_timeout_s: float = ORDER_TIMEOUT_S,
    ledger_path: Path | None = None,
) -> int:
    """Run the C paper node in the foreground; 0 only when the session completed."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="C PaperAccount JSON")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument(
        "--symbols",
        nargs="+",
        metavar="FULL_ID",
        help="full Alpaca instrument ids, e.g. OMH.ALPACA (tests and dry runs)",
    )
    selector.add_argument(
        "--universe",
        action="store_true",
        help="rank the eligible 24/5 universe and arm the slot pool at every segment",
    )
    baseline_source = parser.add_mutually_exclusive_group(required=True)
    baseline_source.add_argument(
        "--baseline-dir",
        type=Path,
        help="directory holding overnight.json, pre.json, rth.json and post.json",
    )
    baseline_source.add_argument(
        "--baseline",
        type=Path,
        help="single-segment baseline JSON; the run does not switch segments",
    )
    parser.add_argument("--state", type=Path, required=True, help="writer/custody/guard state dir")
    parser.add_argument("--seconds", type=int, default=300, help="foreground run length")
    parser.add_argument("--dry-run", action="store_true", help="print commands; send nothing")
    args = parser.parse_args(argv)

    api_key = os.environ.get(KEY_NAMES[0])
    secret_key = os.environ.get(KEY_NAMES[1])
    if not api_key or not secret_key:
        raise SystemExit(f"{KEY_NAMES[0]} and {KEY_NAMES[1]} must be set by with-keys")
    expected_suffix = os.environ.get(EXPECTED_SUFFIX_ENV) or ""
    if not expected_suffix:
        raise SystemExit(f"{EXPECTED_SUFFIX_ENV} must be set")
    if args.seconds < 0:
        raise SystemExit("--seconds must not be negative")

    try:
        account = load_account_config(args.config)
    except ValueError as exc:
        raise SystemExit(f"C live main refused: {exc}") from exc

    raw_client = client_factory(api_key=api_key, secret_key=secret_key, paper=True)
    broker_account = raw_client.get_account()
    account_number = str(getattr(broker_account, "account_number", ""))
    if not account_number.endswith(expected_suffix):
        raise SystemExit(
            "C live main refused: the broker account number does not match the expected "
            "C paper account"
        )
    if raw_client.get_all_positions():
        raise SystemExit("C live main refused: account C already has a position")
    open_orders = raw_client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
    if open_orders:
        raise SystemExit("C live main refused: account C already has an open order")
    if len(open_orders) >= OPEN_ORDER_LIMIT:
        raise SystemExit("C live main refused: the open-order list may be truncated")

    try:
        controls = Controls.from_rows(json.loads(DEFAULT_CONTROLS.read_text()))
        pacer = AccountPacer(controls, now_ns=now_ns)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"C live main refused: custody controls unavailable: {exc}") from exc
    client = PacedTradingClient(raw_client, pacer)

    state = Path(args.state)
    state.mkdir(parents=True, exist_ok=True)
    scope = AccountScope(account.broker, account_number)
    try:
        book = Custody(scope, state / "custody.json", create=True)
        guard = Guard(
            scope,
            state / "guard.json",
            state / "guard.halt",
            controls,
            mode="paper",
        )
        lease = WriterLease(scope, state / "writer.lock", "c-live")
        lease.acquire()
    except (OSError, ValueError, CustodyError) as exc:
        raise SystemExit(f"C live main refused: {exc}") from exc
    if not lease.held:
        raise SystemExit("C live main refused: the C writer lease is not held")

    run = RunRecord(dry_run=bool(args.dry_run))
    receipt_written = False
    try:
        start_now = now_ns()
        started = book.observe(
            AccountSnapshot(scope, 1, {}, {}, (), True, start_now, "alpaca paper start"),
            now=start_now,
        )
        if not started:
            raise SystemExit("C live main refused: the start snapshot is not observable")
        guard.initialize(book.flat_receipt())

        first, _, _ = segment_start(now_ns())
        if first is None:
            raise SystemExit("C live main refused: the XNYS session is closed")
        try:
            params = EntryParameters.from_rows(
                json.loads(DEFAULT_ENTRY_PARAMETERS.read_text()),
                first_leg_only=True,
            )
        except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
            raise SystemExit(f"C live main refused: entry parameters unavailable: {exc}") from exc
        try:
            current_baseline = _segment_baseline(args.baseline, args.baseline_dir, first)
        except LiveRefusal as exc:
            raise SystemExit(f"C live main refused: {exc}") from exc

        run.started_ns = now_ns()
        run.receipt_id = uuid.uuid4().hex
        failure: str | None = None
        data_client: Any = None
        current_symbols: tuple[str, ...] = ()
        current_slot_count = 2
        current_instruments: dict[str, Equity] = {}
        final_segment_obj = first
        if args.universe:
            try:
                data_client = data_factory(api_key=api_key, secret_key=secret_key)
            except Exception as exc:
                failure = f"refused: data client unavailable: {type(exc).__name__}: {exc}"
            else:
                arming, failure = _arm_universe(
                    client=client,
                    data=data_client,
                    segment=first,
                    custody_open=_custody_open(book),
                    now=datetime.fromtimestamp(now_ns() / _NS_PER_S, tz=UTC),
                )
                _record_arming(run, first, arming)
                current_symbols = arming.armed
                current_slot_count = arming.slots
            if failure is None:
                try:
                    current_instruments = _instruments_for(client, current_symbols, first)
                except LiveRefusal as exc:
                    failure = f"refused: {exc}"
        else:
            current_symbols = tuple(args.symbols)
            try:
                current_instruments = _instruments_for(client, current_symbols, first)
            except LiveRefusal as exc:
                raise SystemExit(f"C live main refused: {exc}") from exc

        deadline = monotonic() + float(args.seconds)
        stop_requested = [False]
        active_feed: list[Any] = [None]

        def run_segment(
            segment: Segment,
            baseline: BaselineTable,
            instruments: dict[str, Equity],
            config: CConfig,
        ) -> tuple[dict[str, Any], str | None, bool, bool]:
            pending_fills: list[OrderFact] = []
            protections: dict[str, _LimitProtection] = {}

            def _place_limit_exit(
                entry_cid: str,
                instrument: str,
                quantity: Decimal,
                entry: Any,
            ) -> None:
                fill_price = _fill_price(entry)
                increment = instruments[instrument].price_increment.as_decimal()
                limit_price = _trail_limit(fill_price, config.trail_fraction, increment)
                cid = f"{entry_cid}-exit"
                if not lease.held:
                    raise LiveRefusal("the C writer lease is not held")
                if not book.submission_ready(instrument):
                    raise LiveRefusal(f"custody is not submission-ready for {instrument}")
                if book.available_exit(instrument) < quantity:
                    raise LiveRefusal(
                        f"{quantity} shares of {instrument} are not available to protect"
                    )
                command = OrderCommand(
                    client_order_id=cid,
                    instrument=instrument,
                    side="SELL",
                    quantity=quantity,
                    order_type="LIMIT",
                    time_in_force="GTC",
                    limit_price=limit_price,
                )
                row = _record_command(run, command, cid, status="SUBMITTED", segment=segment.name)
                request = _request_for(command, cid, extended_hours=True)
                ack = client.submit_order(request, kind=ActionKind.REDUCE)
                row["ack"] = _status(ack)
                row["venue_id"] = _order_id(ack) or ""
                print(
                    f"protection {cid} SELL LIMIT GTC {_decimal_text(limit_price)} "
                    f"ack={row['ack']}",
                    flush=True,
                )
                if row["ack"] == "FILLED":
                    row["status"] = "FILLED"
                    row["fill"] = _decimal_text(quantity)
                    run.protection_cid = cid
                    return
                if row["ack"] not in _PROTECTION_ACKS:
                    raise LiveRefusal(
                        f"the {segment.name} limit exit {cid} was not accepted "
                        f"({row['ack']}); the position is unprotected"
                    )
                if not row["venue_id"]:
                    raise LiveRefusal(
                        f"the {segment.name} limit exit {cid} has no venue id; "
                        "the position is unprotected"
                    )
                protections[instrument] = _LimitProtection(
                    instrument=instrument,
                    entry_cid=entry_cid,
                    cid=cid,
                    venue_id=row["venue_id"],
                    quantity=quantity,
                    fill_price=fill_price,
                    limit_price=limit_price,
                    hwm=fill_price,
                )
                run.protection_cid = cid

            def _replace_protection(protection: _LimitProtection, new_limit: Decimal) -> None:
                cancel_row = _record_row(
                    run,
                    cid=protection.cid,
                    kind="CANCEL",
                    side="SELL",
                    quantity=protection.quantity,
                    limit_price=protection.limit_price,
                    trail_price=None,
                    status="SUBMITTED",
                    segment=segment.name,
                )
                try:
                    client.cancel_order_by_id(protection.venue_id)
                except Exception as exc:
                    raise LiveRefusal(
                        f"cancel of {protection.cid} failed; the position may be unprotected: {exc}"
                    ) from exc
                cancel_row["ack"] = "ACCEPTED"
                print(
                    f"protection cancel {protection.cid} (venue {protection.venue_id})",
                    flush=True,
                )
                final = _await_cancel(
                    client,
                    protection.venue_id,
                    sleep=sleep,
                    monotonic=monotonic,
                    poll_interval_s=poll_interval_s,
                    timeout_s=order_timeout_s,
                )
                status = _status(final)
                if status == "FILLED":
                    cancel_row["status"] = "FILLED"
                    filled = _filled_quantity(final)
                    cancel_row["fill"] = _decimal_text(filled)
                    if filled < protection.quantity:
                        raise LiveRefusal(
                            f"the limit exit for {protection.instrument} filled {filled} "
                            f"of {protection.quantity}; the rest is unprotected"
                        )
                    protections.pop(protection.instrument, None)
                    return
                if status not in _PROTECTION_GONE:
                    raise LiveRefusal(
                        f"the protection for {protection.instrument} ended {status}; "
                        "the position is unprotected"
                    )
                cancel_row["status"] = status
                filled = _filled_quantity(final)
                if filled > 0:
                    raise LiveRefusal(
                        f"the limit exit for {protection.instrument} filled {filled} "
                        "before cancel; the rest is unprotected"
                    )
                replacements = protection.replacements + 1
                new_cid = f"{protection.entry_cid}-exit-r{replacements}"
                modify_row = _record_row(
                    run,
                    cid=new_cid,
                    kind="MODIFY",
                    side="SELL",
                    quantity=protection.quantity,
                    limit_price=new_limit,
                    trail_price=None,
                    status="SUBMITTED",
                    segment=segment.name,
                )
                try:
                    replaced = client.replace_order_by_id(
                        protection.venue_id,
                        # alpaca-py annotates limit_price as float; pydantic accepts
                        # the already-quantized Decimal and serializes the price.
                        ReplaceOrderRequest(
                            limit_price=new_limit,  # pyright: ignore[reportArgumentType]
                            client_order_id=new_cid,
                        ),
                    )
                except Exception as exc:
                    raise LiveRefusal(
                        f"replace of {protection.cid} failed after cancel; the position "
                        f"is unprotected: {exc}"
                    ) from exc
                modify_row["ack"] = _status(replaced)
                modify_row["venue_id"] = _order_id(replaced) or ""
                print(
                    f"protection {new_cid} SELL LIMIT GTC {_decimal_text(new_limit)} "
                    f"ack={modify_row['ack']}",
                    flush=True,
                )
                if modify_row["ack"] not in _PROTECTION_ACKS or not modify_row["venue_id"]:
                    raise LiveRefusal(
                        f"the replacement protection {new_cid} was not accepted; "
                        "the position is unprotected"
                    )
                protection.cid = new_cid
                protection.venue_id = modify_row["venue_id"]
                protection.limit_price = new_limit
                protection.replacements = replacements
                run.protection_cid = new_cid

            def _reprice_protection(tick: Any) -> None:
                protection = protections.get(str(tick.instrument_id))
                if protection is None:
                    return
                price = tick.price.as_decimal()
                if price <= protection.hwm:
                    return
                protection.hwm = price
                increment = instruments[protection.instrument].price_increment.as_decimal()
                new_limit = _trail_limit(price, config.trail_fraction, increment)
                if new_limit > protection.limit_price:
                    _replace_protection(protection, new_limit)

            def place(command: OrderCommand) -> None:
                cid = command.client_order_id or _house_cid(account, command)
                if run.dry_run:
                    print(json.dumps(_command_payload(command, cid), sort_keys=True), flush=True)
                    _record_command(run, command, cid, status="DRY_RUN", segment=segment.name)
                    return
                if not lease.held:
                    raise LiveRefusal("the C writer lease is not held")
                if not book.submission_ready(command.instrument):
                    raise LiveRefusal(f"custody is not submission-ready for {command.instrument}")
                if command.side == "BUY" and not guard.entry_allowed():
                    raise LiveRefusal("the guard does not allow a C entry")
                if command.side == "SELL" and (
                    book.available_exit(command.instrument) < command.quantity
                ):
                    raise LiveRefusal(
                        f"exit quantity exceeds the reconciled position for {command.instrument}"
                    )

                row = _record_command(run, command, cid, status="SUBMITTED", segment=segment.name)
                request = _request_for(command, cid, extended_hours=segment.name != "RTH")
                ack = client.submit_order(
                    request,
                    kind=ActionKind.SUBMIT if command.side == "BUY" else ActionKind.REDUCE,
                )
                row["ack"] = _status(ack)
                row["venue_id"] = _order_id(ack) or ""
                print(
                    f"command {cid} {command.side} {command.order_type} ack={row['ack']}",
                    flush=True,
                )
                final = _await_order(
                    client,
                    cid,
                    ack,
                    sleep=sleep,
                    monotonic=monotonic,
                    poll_interval_s=poll_interval_s,
                    timeout_s=order_timeout_s,
                )
                filled = _filled(final)
                row["fill"] = _decimal_text(filled)
                row["status"] = _status(final)
                if command.side == "SELL":
                    run.protection_cid = cid
                    return
                now = now_ns()
                epoch = (book.snapshot.epoch + 1) if book.snapshot is not None else 2
                observed = book.observe(
                    AccountSnapshot(
                        scope,
                        epoch,
                        {command.instrument: filled},
                        {command.instrument: PositionAuthority(filled, f"alpaca fill {cid}")},
                        (),
                        True,
                        now,
                        f"alpaca fill {cid}",
                    ),
                    now=now,
                )
                if not observed:
                    raise LiveRefusal(f"the fill snapshot for {cid} is not observable")
                pending_fills.append(
                    OrderFact(
                        cid,
                        command.instrument,
                        "BUY",
                        command.quantity,
                        filled,
                        "FILLED",
                        _order_id(final),
                    )
                )
                if segment.name != "RTH":
                    _place_limit_exit(cid, command.instrument, filled, final)

            try:
                session = CSession(config, baseline, now_ns, place, instruments=instruments)
            except Exception as exc:
                return (
                    {},
                    f"session failure: {type(exc).__name__}: {exc}",
                    bool(stop_requested[0]),
                    False,
                )

            def flush_fills() -> None:
                while pending_fills:
                    session.on_fill(pending_fills.pop(0))

            def on_trade(tick: Any) -> None:
                session.on_trade(tick)
                flush_fills()
                _reprice_protection(tick)

            def on_quote(tick: Any) -> None:
                session.on_quote(tick)
                flush_fills()

            try:
                feed = feed_factory(
                    instruments,
                    on_trade=on_trade,
                    on_quote=on_quote,
                    api_key=api_key,
                    secret_key=secret_key,
                    feed=_feed_for(segment),
                )
            except Exception as exc:
                return (
                    {},
                    f"feed failure: {type(exc).__name__}: {exc}",
                    bool(stop_requested[0]),
                    False,
                )

            active_feed[0] = feed
            boundary = [False]
            remaining = max(0.0, deadline - monotonic())
            until_boundary = max(0.0, (segment.end_ns - now_ns()) / _NS_PER_S)
            timer_seconds = min(remaining, until_boundary)
            boundary_timer = until_boundary <= remaining

            def stop_at_timer() -> None:
                if boundary_timer:
                    boundary[0] = True
                feed.stop()

            timer = threading.Timer(timer_seconds, stop_at_timer)
            timer.daemon = True
            timer.start()
            failure: str | None = None
            try:
                feed.start()
            except LiveRefusal as exc:
                failure = f"refused: {exc}"
            except Exception as exc:
                failure = f"feed failure: {type(exc).__name__}: {exc}"
            finally:
                timer.cancel()
                active_feed[0] = None
                with contextlib.suppress(Exception):
                    feed.stop()
            if failure is None and getattr(feed, "failure", None) is not None:
                caught = feed.failure
                failure = f"feed failure: {type(caught).__name__}: {caught}"
            return session.snapshot(), failure, bool(stop_requested[0]), boundary[0]

        def stop_feed(signum: int, frame: FrameType | None) -> None:
            stop_requested[0] = True
            feed = active_feed[0]
            if feed is not None:
                feed.stop()

        previous_term = signal.signal(signal.SIGTERM, stop_feed)
        previous_int = signal.signal(signal.SIGINT, stop_feed)
        final_segment = first.name
        final_segment_obj = first
        final_baseline: BaselineTable | None = current_baseline
        current = first
        try:
            while failure is None:
                final_segment_obj = current
                final_segment = current.name
                final_baseline = current_baseline
                final_config = _config_for(
                    current_symbols, params, current, slot_count=current_slot_count
                )
                snapshot, failure, stopped, boundary = run_segment(
                    current, current_baseline, current_instruments, final_config
                )
                run.snapshot = snapshot
                run.flags += _flag_count(snapshot)
                if failure is not None or stopped:
                    break
                if args.baseline is not None:
                    break
                if monotonic() >= deadline:
                    break
                nxt = segment_start(now_ns())[0]
                if nxt is None:
                    failure = "refused: the XNYS session is closed"
                    break
                if nxt.name == current.name:
                    if not boundary:
                        break
                    wait = max(0.0, (current.end_ns - now_ns()) / _NS_PER_S) + 0.05
                    if monotonic() + wait >= deadline:
                        break
                    sleep(wait)
                    nxt = segment_start(now_ns())[0]
                    if nxt is None:
                        failure = "refused: the XNYS session is closed"
                        break
                    if nxt.name == current.name:
                        break
                final_segment_obj = nxt
                final_segment = nxt.name
                try:
                    next_baseline = _segment_baseline(args.baseline, args.baseline_dir, nxt)
                except LiveRefusal as exc:
                    failure = f"refused: {exc}"
                    final_baseline = None
                    break
                next_symbols = current_symbols
                next_slot_count = current_slot_count
                if args.universe:
                    arming, failure = _arm_universe(
                        client=client,
                        data=data_client,
                        segment=nxt,
                        custody_open=_custody_open(book),
                        now=datetime.fromtimestamp(now_ns() / _NS_PER_S, tz=UTC),
                    )
                    _record_arming(run, nxt, arming)
                    next_symbols = arming.armed
                    next_slot_count = arming.slots
                    current_symbols = next_symbols
                    current_slot_count = next_slot_count
                    if failure is not None:
                        final_baseline = next_baseline
                        break
                else:
                    current_symbols = next_symbols
                    current_slot_count = next_slot_count
                try:
                    next_instruments = _instruments_for(client, next_symbols, nxt)
                except LiveRefusal as exc:
                    failure = f"refused: {exc}"
                    final_baseline = next_baseline
                    break
                current = nxt
                current_baseline = next_baseline
                current_instruments = next_instruments
                current_symbols = next_symbols
                current_slot_count = next_slot_count
        finally:
            signal.signal(signal.SIGTERM, previous_term)
            signal.signal(signal.SIGINT, previous_int)

        if failure is not None:
            run.errors.append(failure)
        run.stopped_ns = now_ns()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        try:
            receipt = _write_receipt(
                account=account,
                account_suffix=account_number[-4:],
                symbols=current_symbols,
                run=run,
                baseline=final_baseline,
                segment=final_segment_obj,
                entry_params_hash=params.params_hash,
                final_segment=final_segment,
                stamp=stamp,
            )
            receipt_written = True
            print(f"receipt {receipt}", flush=True)
        except OSError as exc:
            run.errors.append(f"receipt: {type(exc).__name__}: {exc}")
            print(
                f"receipt not written: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

        try:
            _record_trial(
                ledger_path=Path(ledger_path) if ledger_path is not None else Path(WITNESS_PATH),
                run=run,
                baseline=final_baseline,
                symbols=current_symbols,
                segment=final_segment_obj,
                entry_params_hash=params.params_hash,
                failure=failure,
            )
        except Exception as exc:
            print(
                f"trial ledger refused: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 1
        return 0 if failure is None and receipt_written else 1
    finally:
        lease.close()


if __name__ == "__main__":
    raise SystemExit(main())
