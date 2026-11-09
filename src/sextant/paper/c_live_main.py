"""Run the C first-leg node in the foreground against Alpaca paper account C.

The runner follows the merged B precedent (``b_protector_main.py``): keys and the
expected account come only from the environment, every broker call after the
startup checks goes through the repo's account pacer, one writer lease owns the
account, and SIGTERM/SIGINT stop the stream without cancelling the broker-held
trail.  The C decision core (``c_session.py``) is unchanged: this module only
wires it to alpaca-py's SIP feed and trading client (v0.44.0
``examples/stocks/stocks-trading-basic.ipynb`` cells 25-36), submits the one
witness-size LIMIT entry, then the native GTC trailing stop the session emits
after the fill.

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
import signal
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import FrameType
from typing import Any, Protocol, cast

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, LimitOrderRequest, TrailingStopOrderRequest
from nautilus_trader.model import Currency, Equity, InstrumentId, Price, Quantity, Symbol

from sextant.entry.parameters import EntryParameters
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
from sextant.paper.config import PaperAccount
from sextant.paper.sessions import Session
from sextant.ranking.baseline import BaselineTable, load_baseline, segment_start
from sextant.risk.controls import Controls
from sextant.risk.guard import Guard
from sextant.validation.trials import WITNESS_PATH, TrialLog

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTROLS = ROOT / "lanes/custody-parameters.json"
DEFAULT_ENTRY_PARAMETERS = ROOT / "lanes/sim/entry-parameters.json"
CONFIG_KEYS = frozenset({"lane", "account_id", "client_id", "namespace", "sessions"})
C_LANE = "alpaca-paper-c"
KEY_NAMES = ("ALPACA_PAPER_3_API_KEY", "ALPACA_PAPER_3_SECRET_KEY")
EXPECTED_SUFFIX_ENV = "C_EXPECTED_ACCOUNT_SUFFIX"
DEFAULT_CLIENT_FACTORY: Callable[..., Any] = cast(Callable[..., Any], TradingClient)
POLL_INTERVAL_S = 0.5
ORDER_TIMEOUT_S = 30.0
OPEN_ORDER_LIMIT = 500
STOP_STATUSES = frozenset(
    {"CANCELED", "CANCELLED", "DONE_FOR_DAY", "EXPIRED", "REJECTED", "REPLACED", "STOPPED"}
)


class LiveRefusal(RuntimeError):
    """The C runner will not act, or cannot know an order's state; it stops."""


class PacerRefused(RuntimeError):
    """The account pacer did not admit a broker call; the caller must fail closed."""


class TradingClientLike(Protocol):
    """The alpaca-py trading surface this runner uses, kept explicit for the fake."""

    def get_account(self) -> Any: ...

    def get_all_positions(self) -> Any: ...

    def get_orders(self, filter: Any = None) -> Any: ...

    def get_asset(self, symbol_or_asset_id: object) -> Any: ...

    def get_order_by_id(self, order_id: object) -> Any: ...

    def submit_order(self, order_data: Any) -> Any: ...


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

    def get_asset(self, symbol_or_asset_id: object) -> Any:
        return self._call(ActionKind.QUERY, self._client.get_asset, symbol_or_asset_id)

    def get_order_by_id(self, order_id: object) -> Any:
        return self._call(ActionKind.QUERY, self._client.get_order_by_id, order_id)

    def submit_order(self, order_data: Any, *, kind: ActionKind) -> Any:
        return self._call(kind, self._client.submit_order, order_data)


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


def _record_command(
    run: RunRecord, command: OrderCommand, cid: str, *, status: str
) -> dict[str, Any]:
    row = {
        "cid": cid,
        "kind": command.order_type,
        "side": command.side,
        "qty": _decimal_text(command.quantity),
        "limit": None if command.limit_price is None else _decimal_text(command.limit_price),
        "trail": None if command.trail_price is None else _decimal_text(command.trail_price),
        "ack": "",
        "fill": "0",
        "status": status,
        "venue_id": "",
    }
    run.commands.append(row)
    return row


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
    baseline: BaselineTable,
    config: CConfig,
    stamp: str,
) -> Path:
    payload = {
        "tier": "BROKER-PAPER",
        "lane": account.lane,
        "account_suffix": account_suffix,
        "symbols": list(symbols),
        "commands": run.commands,
        "protection_cid": run.protection_cid,
        "errors": run.errors,
        "baseline": {
            "provenance": baseline.provenance,
            "known_at": baseline.known_at,
            "feed": baseline.feed,
        },
        "entry_params_hash": config.params.params_hash,
        "dry_run": run.dry_run,
        "started_ns": run.started_ns,
        "stopped_ns": run.stopped_ns,
        "segment": {
            "name": config.segment.name,
            "session_date": config.segment.session_date.isoformat(),
            "start_ns": config.segment.start_ns,
            "end_ns": config.segment.end_ns,
        },
    }
    path = Path("reports/paper-c") / stamp / "session.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def _trial_config(config: CConfig, started_ns: int) -> dict[str, str]:
    return {
        "tier": "BROKER-PAPER",
        "block_set_id": (
            f"paper-c:{config.segment.session_date.isoformat()}:{config.segment.name}:{started_ns}"
        ),
    }


def _record_trial(
    *,
    ledger_path: Path,
    run: RunRecord,
    baseline: BaselineTable,
    config: CConfig,
    failure: str | None,
) -> None:
    """Append one BROKER-PAPER row; flags/entries/fills are counts, never a P&L claim."""

    flags = sum(
        1
        for key, state in run.snapshot.items()
        if key != "params_hash" and isinstance(state, dict) and state.get("flag_ts") is not None
    )
    entries = sum(1 for row in run.commands if row["kind"] == "LIMIT" and row["side"] == "BUY")
    fills = sum(1 for row in run.commands if Decimal(str(row["fill"])) > 0)
    params = {
        "symbols": list(config.symbols),
        "segment": config.segment.name,
        "session_date": config.segment.session_date.isoformat(),
        "flags": flags,
        "entries": entries,
        "fills": fills,
        "protection_cid": run.protection_cid or "",
        "dry_run": run.dry_run,
        "commands": run.commands,
        "errors": list(run.errors),
        "baseline_known_at": baseline.known_at,
        "baseline_provenance": baseline.provenance,
        "entry_params_hash": config.params.params_hash,
    }
    identity = _trial_config(config, run.started_ns)

    class TrialFailed(Exception):
        """Carries the session failure into the ledger's FAIL state."""

    try:
        with TrialLog(ledger_path).attempts({"c-live-main": {}}, params, identity):
            if failure is not None:
                raise TrialFailed(failure)
    except TrialFailed:
        return


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[..., TradingClientLike] = DEFAULT_CLIENT_FACTORY,
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
    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
        metavar="FULL_ID",
        help="full Alpaca instrument ids, e.g. OMH.ALPACA",
    )
    parser.add_argument("--baseline", type=Path, required=True, help="baseline JSON")
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

        symbols = tuple(args.symbols)
        instruments: dict[str, Equity] = {}
        for full_id in symbols:
            try:
                iid = InstrumentId.from_str(full_id)
            except ValueError as exc:
                raise SystemExit(f"C live main refused: bad instrument id {full_id}") from exc
            if str(iid.venue) != "ALPACA":
                raise SystemExit(f"C live main refused: {full_id} is not an ALPACA instrument")
            asset = client.get_asset(iid.symbol.value)
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

        baseline = load_baseline(Path(args.baseline).read_text())
        segment, _, _ = segment_start(now_ns())
        if segment is None:
            raise SystemExit("C live main refused: the XNYS session is closed")
        params = EntryParameters.from_rows(
            json.loads(DEFAULT_ENTRY_PARAMETERS.read_text()),
            first_leg_only=True,
        )
        config = CConfig(
            symbols=symbols,
            chase_cap_fraction=Decimal("0.03"),  # 0.03 = the recorded first_leg_max_move
            trail_fraction=Decimal("0.025"),  # ADR-0025 C-scope, UNCALIBRATED
            slot_count=2,  # ADR-0024 2-of-5 pool
            segment=segment,
            params=params,
        )

        run.started_ns = now_ns()
        session_ref: list[CSession] = []
        pending_fills: list[OrderFact] = []

        def place(command: OrderCommand) -> None:
            cid = command.client_order_id or _house_cid(account, command)
            if run.dry_run:
                print(json.dumps(_command_payload(command, cid), sort_keys=True), flush=True)
                _record_command(run, command, cid, status="DRY_RUN")
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

            row = _record_command(run, command, cid, status="SUBMITTED")
            request = _request_for(command, cid, extended_hours=config.segment.name != "RTH")
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
            # CSession records ``state.cid`` only after its synchronous ``_submit``
            # returns, so calling ``on_fill`` here would look up a still-None cid.
            # Queue the fact and flush it after the feed callback unwinds.
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

        session = CSession(config, baseline, now_ns, place, instruments=instruments)
        session_ref.append(session)

        def flush_fills() -> None:
            while pending_fills:
                session.on_fill(pending_fills.pop(0))

        def on_trade(tick: Any) -> None:
            session.on_trade(tick)
            flush_fills()

        def on_quote(tick: Any) -> None:
            session.on_quote(tick)
            flush_fills()

        feed = feed_factory(
            instruments,
            on_trade=on_trade,
            on_quote=on_quote,
            api_key=api_key,
            secret_key=secret_key,
            feed="sip",
        )

        def stop_feed(signum: int, frame: FrameType | None) -> None:
            feed.stop()

        previous_term = signal.signal(signal.SIGTERM, stop_feed)
        previous_int = signal.signal(signal.SIGINT, stop_feed)
        timer: threading.Timer | None = None
        failure: str | None = None
        try:
            timer = threading.Timer(float(args.seconds), feed.stop)
            timer.daemon = True
            timer.start()
            feed.start()
        except LiveRefusal as exc:
            failure = f"refused: {exc}"
        except Exception as exc:
            failure = f"feed failure: {type(exc).__name__}: {exc}"
        finally:
            if timer is not None:
                timer.cancel()
            signal.signal(signal.SIGTERM, previous_term)
            signal.signal(signal.SIGINT, previous_int)
            with contextlib.suppress(Exception):
                feed.stop()

        if failure is None and getattr(feed, "failure", None) is not None:
            caught = feed.failure
            failure = f"feed failure: {type(caught).__name__}: {caught}"
        if failure is not None:
            run.errors.append(failure)
        run.stopped_ns = now_ns()
        run.snapshot = session.snapshot()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        try:
            receipt = _write_receipt(
                account=account,
                account_suffix=account_number[-4:],
                symbols=symbols,
                run=run,
                baseline=baseline,
                config=config,
                stamp=stamp,
            )
            receipt_written = True
            print(f"receipt {receipt}", flush=True)
        except OSError as exc:
            run.errors.append(f"receipt: {type(exc).__name__}: {exc}")
            print(f"receipt not written: {type(exc).__name__}: {exc}", file=sys.stderr)

        try:
            _record_trial(
                ledger_path=Path(ledger_path) if ledger_path is not None else Path(WITNESS_PATH),
                run=run,
                baseline=baseline,
                config=config,
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
