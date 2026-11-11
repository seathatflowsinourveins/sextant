"""Paper C's former first-leg runner, without its entry point: C's account is revoked.

The runner follows the merged B precedent (``b_protector_main.py``): keys and the
expected account come only from the environment, every broker call after the
startup checks goes through the repo's account pacer, one writer lease owns the
account, and SIGTERM/SIGINT stop the stream without cancelling the broker-held
trail.  The C decision core (``c_session.py``) owns the decision: this module only
wires it to alpaca-py's trading client (v0.44.0
``examples/stocks/stocks-trading-basic.ipynb`` cells 25-36), selects SIP in the
day sessions and BOATS overnight, loads the current segment's baseline, submits
the one sized LIMIT entry, then the native GTC trailing stop in RTH or a
resting GTC LIMIT at the ADR-0025 trail price outside it, re-priced as the trail
rises.

The account config is a JSON object with ``PaperAccount``'s fields: ``lane``,
``account_id``, ``client_id``, ``namespace`` and ``sessions``.  The fetched
broker account number is compared to ``C_EXPECTED_ACCOUNT_SUFFIX`` and never
printed; the receipt carries only its last four characters.  The run is paper
only: ``TradingClient(paper=True)`` and no live endpoint.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Protocol, cast

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import (
    LimitOrderRequest,
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
    PositionAuthority,
)
from sextant.execution.pacer import ActionKind
from sextant.paper.c_session import CConfig
from sextant.paper.c_universe import AssetSkips, rank_universe
from sextant.paper.config import PaperAccount
from sextant.paper.sessions import Session
from sextant.ranking.baseline import BaselineTable, load_baseline
from sextant.ranking.baseline_coverage import bare_symbol
from sextant.ranking.engine import Segment
from sextant.validation.trials import TrialLog, snapshot_hash

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTROLS = ROOT / "lanes/custody-parameters.json"
DEFAULT_ENTRY_PARAMETERS = ROOT / "lanes/sim/entry-parameters.json"
DEFAULT_LEASE_ROOT = Path.home() / "sextant-data" / "locks"
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
_PROTECTIVE_STOP_TYPES = frozenset({"TRAILING_STOP", "STOP", "STOP_LIMIT"})


def _declared_slots(rows: Sequence[dict[str, Any]]) -> int | None:
    """Return the lane's declared slot count, or None while it is UNAVAILABLE."""
    row = next((item for item in rows if item.get("name") == "portfolio_slots"), None)
    if row is None or row.get("value") is None:
        return None
    value = row["value"]
    if type(value) is not int or value <= 0:
        raise ValueError("portfolio_slots: positive integer required")
    return value


class LiveRefusal(RuntimeError):
    """The C runner will not act, or cannot know an order's state; it stops."""


class _OrderEnded(LiveRefusal):
    """A broker order reached a terminal status; the final order is attached."""

    def __init__(self, message: str, order: Any) -> None:
        super().__init__(message)
        self.order = order


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

    def get_order_by_client_id(self, client_id: str) -> Any: ...

    def submit_order(self, order_data: Any) -> Any: ...

    def cancel_order_by_id(self, order_id: object) -> Any: ...

    def replace_order_by_id(self, order_id: object, order_data: Any) -> Any: ...


class PacedTradingClient:
    """Route every broker read and write through the repo's existing account pacer."""

    def __init__(self, client: TradingClientLike, pacer: Any, assets_client: Any = None) -> None:
        self._assets_client = assets_client if assets_client is not None else client
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
        return self._call(ActionKind.QUERY, self._assets_client.get_all_assets, filter)

    def get_asset(self, symbol_or_asset_id: object) -> Any:
        return self._call(ActionKind.QUERY, self._client.get_asset, symbol_or_asset_id)

    def get_order_by_id(self, order_id: object) -> Any:
        return self._call(ActionKind.QUERY, self._client.get_order_by_id, order_id)

    def get_order_by_client_id(self, client_id: str) -> Any:
        return self._call(ActionKind.QUERY, self._client.get_order_by_client_id, client_id)

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
    asset_skips: AssetSkips = field(default_factory=AssetSkips)
    segment_snapshots: list[dict[str, Any]] = field(default_factory=list)
    trial_file: dict[str, str] | None = None


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
    """Poll the acknowledged order by its client order id; never resubmit or guess."""

    order = ack
    deadline = monotonic() + timeout_s
    while True:
        status = _status(order)
        if status == "FILLED":
            return order
        if status in STOP_STATUSES:
            raise _OrderEnded(f"order {cid} ended {status}", order)
        current = monotonic()
        if current >= deadline:
            raise LiveRefusal(
                f"order {cid} state unknown after {timeout_s:g}s; it was not resubmitted"
            )
        sleep(min(poll_interval_s, deadline - current))
        order = client.get_order_by_client_id(cid)


def _house_cid(account: PaperAccount, command: OrderCommand) -> str:
    """A deterministic house id for the one session that supplies none (it always does)."""

    symbol = bare_symbol(command.instrument)
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
    symbol = bare_symbol(command.instrument)
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
        "asset_rows_skipped": run.asset_skips.count,
        "snapshot": run.snapshot,
        "segment_snapshots": run.segment_snapshots,
        "flags": run.flags,
        "trial_file": run.trial_file,
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


def _retained_symbols(book: Custody) -> frozenset[str]:
    """Read held and working symbols from the same reconciled custody snapshot."""

    snapshot = book.snapshot
    if snapshot is None or not snapshot.complete:
        raise LiveRefusal("custody symbols unavailable for C arming")
    held = {symbol for symbol, quantity in snapshot.positions.items() if quantity > 0}
    working = {order.instrument for order in snapshot.orders if order.leaves > 0}
    return frozenset(held | working)


def _observe_fill(
    book: Custody,
    scope: AccountScope,
    instrument: str,
    delta: Decimal,
    *,
    source: str,
    now: int,
) -> None:
    """Merge one fill into the last complete snapshot instead of replacing it.

    C's retained set is the custody snapshot's held and working symbols. A
    fill-only snapshot that replaces the previous one hides every earlier fill
    (and earlier exit), so the next segment's capacity count is too low.
    """

    previous = book.snapshot
    if previous is None or not previous.complete:
        raise LiveRefusal(f"the fill snapshot for {source} is not observable")
    positions = dict(previous.positions)
    net = positions.get(instrument, Decimal(0)) + delta
    if net > 0:
        positions[instrument] = net
    else:
        positions.pop(instrument, None)
    managed = {
        symbol: authority for symbol, authority in previous.managed.items() if symbol in positions
    }
    if net > 0:
        managed[instrument] = PositionAuthority(net, source)
    observed = book.observe(
        AccountSnapshot(
            scope,
            previous.epoch + 1,
            positions,
            managed,
            previous.orders,
            True,
            now,
            source,
        ),
        now=now,
    )
    if not observed:
        raise LiveRefusal(f"the fill snapshot for {source} is not observable")


@dataclass(frozen=True)
class _Arming:
    eligible: int
    slots: int
    armed: tuple[str, ...]
    custody_open: int | None
    reason: str
    max_armed_symbols: int
    held_back: tuple[str, ...] = ()
    mover_armed: frozenset[str] = frozenset()


def _arm_universe(
    *,
    client: PacedTradingClient,
    data: Any,
    segment: Segment,
    max_armed_symbols: int,
    retained: frozenset[str],
    mover_armed: frozenset[str],
    now: datetime,
    asset_skips: AssetSkips | None = None,
) -> tuple[_Arming, str | None]:
    """Preserve the ranked universe and fill C's configured shared-pool capacity."""

    custody_open = len(retained)
    try:
        ranked = rank_universe(client, data, segment.name.lower(), now=now, asset_skips=asset_skips)
    except Exception as exc:  # the broker/data surface must fail closed, not arm blindly
        retained_movers = frozenset(retained) & mover_armed
        return (
            _Arming(
                0,
                0,
                tuple(sorted(retained)),
                custody_open,
                "universe ranking failed",
                max_armed_symbols,
                mover_armed=retained_movers,
            ),
            f"refused: the {segment.name} universe ranking failed: {type(exc).__name__}: {exc}",
        )
    if not ranked:
        reason = f"no eligible symbols for the {segment.name} session"
        retained_movers = frozenset(retained) & mover_armed
        return (
            _Arming(
                0,
                0,
                tuple(sorted(retained)),
                custody_open,
                reason,
                max_armed_symbols,
                mover_armed=retained_movers,
            ),
            f"refused: {reason}",
        )
    candidates = tuple(Candidate(f"{row.symbol}.ALPACA") for row in ranked)
    allocation = SlotPool().allocate(
        candidates,
        max_armed_symbols=max_armed_symbols,
        potential=(),
        retained=retained,
        mover_armed=mover_armed,
    )
    armed = tuple(
        candidate.symbol for candidate in candidates if candidate.symbol in allocation.chosen
    )
    ranked_symbols = {f"{row.symbol}.ALPACA" for row in ranked}
    held_back: list[str] = []
    for symbol in sorted(retained):
        if symbol in ranked_symbols:
            continue
        try:
            iid = InstrumentId.from_str(symbol)
            _require_eligible(client.get_asset(iid.symbol.value), iid.symbol.value, segment)
        except Exception:  # an ineligible hold stays charged but leaves the segment's feed
            held_back.append(symbol)
    armed += tuple(
        symbol for symbol in sorted(retained) if symbol not in armed and symbol not in held_back
    )
    reason = (
        f"slot pool {allocation.reason}: eligible={len(ranked)} slots={allocation.slots} "
        f"custody_open={custody_open}"
    )
    arming = _Arming(
        len(ranked),
        allocation.slots,
        armed,
        custody_open,
        reason,
        max_armed_symbols,
        tuple(held_back),
        allocation.mover_armed,
    )
    if not armed:
        return arming, f"refused: {reason}"
    return arming, None


def _record_arming(run: RunRecord, segment: Segment, arming: _Arming) -> None:
    run.armings.append(
        {
            "segment": segment.name,
            "eligible": arming.eligible,
            "slots": arming.slots,
            "max_armed_symbols": arming.max_armed_symbols,
            "armed": list(arming.armed),
            "mover_armed": sorted(arming.mover_armed),
            "custody_open": arming.custody_open,
            "held_back": list(arming.held_back),
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


def _account_money(value: object, name: str, *, zero: bool) -> Decimal:
    """The broker account's Decimal field; a missing or float value is unavailable."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError(f"the broker account {name} is unavailable")
    result = Decimal(value)
    if not result.is_finite() or result < 0 or (result == 0 and not zero):
        kind = "nonnegative" if zero else "positive"
        raise ValueError(f"the broker account {name} is not a finite {kind} Decimal")
    return result


def _read_balance(client: Any) -> tuple[Decimal, Decimal]:
    """One paced account read; a failure refuses the entry, never a cached number."""
    try:
        account = client.get_account()
    except Exception as exc:
        raise LiveRefusal(f"the account balance read failed: {type(exc).__name__}: {exc}") from exc
    try:
        return (
            _account_money(getattr(account, "equity", None), "equity", zero=False),
            _account_money(getattr(account, "buying_power", None), "buying_power", zero=True),
        )
    except ValueError as exc:
        raise LiveRefusal(str(exc)) from exc


def _config_for(
    symbols: Sequence[str],
    params: EntryParameters,
    segment: Segment,
    *,
    basis: Decimal,
    slot_count: int = 2,
    held_symbols: frozenset[str] = frozenset(),
) -> CConfig:
    return CConfig(
        symbols=tuple(symbols),
        chase_cap_fraction=Decimal("0.03"),  # 0.03 = the recorded first_leg_max_move
        trail_fraction=Decimal("0.025"),  # ADR-0025 C-scope, UNCALIBRATED
        basis=basis,
        slot_count=slot_count,  # --symbols keeps ADR-0024's 2-of-5; --universe uses the pool
        segment=segment,
        params=params,
        held_symbols=held_symbols,
    )
