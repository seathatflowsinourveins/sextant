"""B's owner-fill protector on alpaca-py's TradingClient and TradingStream (clean B PR-1).

The protector covers every unreserved whole long share with exactly one native trailing stop
of the full net quantity, re-arms it on every change, and never cancels, replaces or resizes
an owner order. Outside regular market hours the native trail rests but does not trigger, so
the protector adopts or emulates its trigger from quotes through NautilusTrader's own
calculator and, after a persistent run of eligible trades, cancels the trail and releases one
marketable extended-hours LIMIT (``docs/design.md``:31 and
``docs/adr/0005-exit-engine.md`` X4; Alpaca orders page read 2026-11-09).

The trade-update stream is event-driven, so the protector also reconciles on a fixed cadence
and once when the regular session opens: a resting trail the broker lost, or a position that
rested unprotected through the close, is re-armed without waiting for an unrelated event.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol, cast

from alpaca.common.enums import Sort
from alpaca.common.exceptions import APIError
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.models import Order, Position, TradeAccount, TradeUpdate
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    OrderRequest,
    TrailingStopOrderRequest,
)
from alpaca.trading.stream import TradingStream

from sextant.execution.pacer import PacerRefused
from sextant.exits.policy import ExitParams
from sextant.paper.b_feed import (
    BHistoricalTape,
    BMarketDataFeed,
    FeedBatch,
    HistoricalQuoteClient,
    LatestDataClient,
    feed_for,
    timestamp_ns,
)
from sextant.paper.config import PaperAccount
from sextant.paper.outside_rth import (
    OutsideRthError,
    OutsideRthTrail,
    QuoteLike,
    rebuild_trigger,
)
from sextant.paper.sessions import ET, Session, session_at, session_start_ns

B_LANE = "alpaca-paper-b"
TRAIL_PERCENT_NAME = "native_trail_fraction"
RECONCILE_INTERVAL_NAME = "reconcile_interval_s"
FEED_POLL_NAME = "feed_poll_interval_s"
FEED_SILENCE_NAME = "feed_silence_s"
PARAMETER_NAMES = frozenset(
    {TRAIL_PERCENT_NAME, RECONCILE_INTERVAL_NAME, FEED_POLL_NAME, FEED_SILENCE_NAME}
)
PARAMETER_KEYS = frozenset({"name", "unit", "value", "source", "calibration_state", "last_change"})
MAX_TRAIL_FRACTION = Decimal("0.025")
FILL_EVENTS = frozenset({"fill", "partial_fill"})
TERMINAL_EVENTS = frozenset({"canceled", "expired", "rejected", "stopped", "done_for_day"})
OPEN_ORDER_LIMIT = 500
MAX_CLIENT_ORDER_ID = 128
NS_PER_SECOND = Decimal(1_000_000_000)


class ProtectorRefusal(RuntimeError):
    """The protector will not act on this account or order."""


@dataclass(frozen=True)
class Page:
    """One operator alert; the runner decides where it goes."""

    reason: str
    symbol: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class _PendingRelease:
    """One broken trail waiting for its terminal cancellation before the LIMIT goes out."""

    trail_order_id: str


@dataclass(frozen=True)
class BParameters:
    """B's four reviewed starting parameters, all UNCALIBRATED."""

    native_trail_fraction: Decimal
    reconcile_interval_s: Decimal
    feed_poll_interval_s: Decimal
    feed_silence_s: Decimal

    def __post_init__(self) -> None:
        fraction = _decimal(self.native_trail_fraction, TRAIL_PERCENT_NAME)
        interval = _decimal(self.reconcile_interval_s, RECONCILE_INTERVAL_NAME)
        poll = _decimal(self.feed_poll_interval_s, FEED_POLL_NAME)
        silence = _decimal(self.feed_silence_s, FEED_SILENCE_NAME)
        object.__setattr__(self, "native_trail_fraction", fraction)
        object.__setattr__(self, "reconcile_interval_s", interval)
        object.__setattr__(self, "feed_poll_interval_s", poll)
        object.__setattr__(self, "feed_silence_s", silence)
        if fraction <= 0 or fraction > MAX_TRAIL_FRACTION:
            raise ValueError("native_trail_fraction must be in (0, 0.025]")
        if interval <= 0:
            raise ValueError("reconcile_interval_s must be positive")
        if poll <= 0:
            raise ValueError("feed_poll_interval_s must be positive")
        if silence <= 0:
            raise ValueError("feed_silence_s must be positive")
        if poll >= silence:
            raise ValueError("feed_poll_interval_s must be shorter than feed_silence_s")


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int) and not isinstance(value, bool):
        result = Decimal(value)
    elif isinstance(value, str):
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"{field} must be a decimal string") from exc
    else:
        raise ValueError(f"{field} must be a Decimal, int or string")
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def load_b_parameters(path: Path) -> BParameters:
    """Read B's registry rows, refusing anything not reviewed and UNCALIBRATED."""

    try:
        rows = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path.name}") from exc
    if not isinstance(rows, list):
        raise ValueError("B parameter registry must be a list")
    values: dict[str, Decimal] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != PARAMETER_KEYS:
            raise ValueError("B parameter row has the wrong keys")
        name = row["name"]
        if not isinstance(name, str) or name not in PARAMETER_NAMES or name in values:
            raise ValueError("B parameter row has an unknown or duplicate name")
        if row["calibration_state"] != "UNCALIBRATED":
            raise ValueError("B parameters start UNCALIBRATED")
        for key in ("unit", "value", "source", "last_change"):
            if not isinstance(row[key], str) or not row[key].strip():
                raise ValueError(f"B parameter row needs a nonempty {key}")
        try:
            date.fromisoformat(row["last_change"])
        except ValueError as exc:
            raise ValueError("B parameter last_change must be an ISO date") from exc
        values[name] = _decimal(row["value"], name)
    if set(values) != PARAMETER_NAMES:
        raise ValueError("B parameter registry is incomplete")
    return BParameters(
        values[TRAIL_PERCENT_NAME],
        values[RECONCILE_INTERVAL_NAME],
        values[FEED_POLL_NAME],
        values[FEED_SILENCE_NAME],
    )


class TradingClientLike(Protocol):
    def get_account(self) -> TradeAccount: ...

    def get_all_positions(self) -> list[Position]: ...

    def get_orders(self, filter: GetOrdersRequest | None = None) -> list[Order]: ...

    def get_order_by_client_id(self, client_id: str) -> Order: ...

    def submit_order(self, order_data: OrderRequest) -> Any: ...

    def cancel_order_by_id(self, order_id: object) -> None: ...


class HistoricalTape(Protocol):
    """The historical-quote read the outside-RTH rebuild needs; the runner supplies alpaca-py."""

    def quotes(
        self,
        symbol: str,
        start_ns: int,
        end_ns: int,
        feed: str,
    ) -> Sequence[QuoteLike]: ...


@dataclass(frozen=True)
class TapeRead:
    """One historical-tape rebuild: the adoption instant, its level and how completely it read."""

    symbol: str
    qty: Decimal
    adoption_ns: int
    level: Decimal | None
    status: str
    reason: str = ""
    detail: str = ""


def tape_windows(start_ns: int, end_ns: int) -> tuple[tuple[int, int, str], ...]:
    """Split a span at the 04:00/20:00 ET boundaries: SIP 04:00-20:00, BOATS 20:00-04:00."""

    if end_ns <= start_ns:
        return ()
    windows: list[tuple[int, int, str]] = []
    cursor = start_ns
    while cursor < end_ns:
        local = datetime.fromtimestamp(cursor / 1_000_000_000, tz=ET)
        if 4 <= local.hour < 20:
            feed = "sip"
            boundary = local.replace(hour=20, minute=0, second=0, microsecond=0)
        else:
            feed = "boats"
            if local.hour >= 20:
                boundary = (local + timedelta(days=1)).replace(
                    hour=4, minute=0, second=0, microsecond=0
                )
            else:
                boundary = local.replace(hour=4, minute=0, second=0, microsecond=0)
        window_end = min(timestamp_ns(boundary), end_ns)
        if window_end <= cursor:
            window_end = end_ns
        windows.append((cursor, window_end, feed))
        cursor = window_end
    return tuple(windows)


def _order_time_ns(order: Order, field: str) -> int | None:
    at = getattr(order, field, None)
    return timestamp_ns(at) if isinstance(at, datetime) else None


def _is_house_order(order: Order, house_prefix: str) -> bool:
    client_order_id = getattr(order, "client_order_id", None)
    return isinstance(client_order_id, str) and client_order_id.startswith(house_prefix)


def read_tape(
    client: TradingClientLike,
    history: HistoricalTape,
    symbol: str,
    qty: Decimal,
    now_ns: int,
    *,
    trail_fraction: Decimal,
    params: ExitParams,
    house_prefix: str,
) -> TapeRead:
    """The broker record's adoption mark plus every feed window since, rebuilt off the loop."""

    try:
        orders = list(
            client.get_orders(
                GetOrdersRequest(
                    status=QueryOrderStatus.ALL,
                    symbols=[symbol],
                    direction=Sort.DESC,
                    limit=OPEN_ORDER_LIMIT,
                )
            )
        )
    except Exception as exc:
        return TapeRead(
            symbol,
            qty,
            now_ns,
            None,
            "none",
            "outside_rth_tape_unreadable",
            f"orders: {type(exc).__name__}",
        )
    buys: list[tuple[int, Order]] = []
    for order in orders:
        if _event_name(getattr(order, "side", None)) != "buy":
            continue
        filled = getattr(order, "filled_qty", None)
        at = getattr(order, "filled_at", None)
        if filled is None or not isinstance(at, datetime):
            continue
        try:
            quantity = _decimal(filled, "order.filled_qty")
        except ValueError:
            continue
        if quantity > 0:
            buys.append((timestamp_ns(at), order))
    if not buys:
        return TapeRead(
            symbol,
            qty,
            now_ns,
            None,
            "none",
            "outside_rth_entry_unknown",
            "no filled buy covers the held quantity",
        )
    fill_ns, fill_order = max(buys, key=lambda item: item[0])
    lower_ns = _order_time_ns(fill_order, "submitted_at")
    if lower_ns is None:
        lower_ns = fill_ns
    house_times = [
        at
        for order in orders
        if _is_house_order(order, house_prefix)
        for at in [_order_time_ns(order, "submitted_at")]
        if at is not None and at >= lower_ns
    ]
    adoption_ns = min(now_ns, max(fill_ns, min(house_times) if house_times else now_ns))
    observations: list[QuoteLike] = []
    failures: list[str] = []
    read_ok = 0
    for start_ns, end_ns, feed in tape_windows(adoption_ns, now_ns):
        try:
            observations.extend(history.quotes(symbol, start_ns, end_ns, feed))
            read_ok += 1
        except Exception as exc:
            failures.append(f"{feed}: {type(exc).__name__}")
    level = (
        rebuild_trigger(observations, trail_fraction=trail_fraction, params=params)
        if observations
        else None
    )
    if not failures:
        status = "ok"
    elif read_ok:
        status = "partial"
    else:
        status = "none"
    return TapeRead(
        symbol,
        qty,
        adoption_ns,
        level,
        status,
        "outside_rth_tape_unreadable" if failures else "",
        "; ".join(failures),
    )


def _event_name(event: object) -> str:
    return str(getattr(event, "value", event))


def _leaves(order: Order) -> Decimal:
    quantity = _decimal(order.qty or "0", "order.qty")
    filled = _decimal(order.filled_qty or "0", "order.filled_qty")
    return quantity - filled


def _is_limit(order: Order) -> bool:
    kind = getattr(order, "type", None)
    if kind is None:
        kind = getattr(order, "order_type", None)
    return _event_name(kind) == "limit"


def _safe_symbol(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", symbol)[:40]


def _state_number(value: object | None) -> str:
    """A broker value as one bare line field; logging never raises on a bad value."""

    if value is None:
        return "none"
    try:
        return format(value if isinstance(value, Decimal) else Decimal(str(value)), "f")
    except (InvalidOperation, ValueError):
        return "none"


class Protector:
    """B's one-account protector; the client is called, never constructed here."""

    def __init__(
        self,
        client: TradingClientLike,
        account: PaperAccount,
        parameters: BParameters,
        *,
        now_ns: Callable[[], int] = time.time_ns,
        on_page: Callable[[Page], None] | None = None,
        exit_params: ExitParams | None = None,
        feed: str = "none",
        on_state: Callable[[str], None] | None = None,
        history: HistoricalTape | None = None,
        tape_off_loop: bool = False,
    ) -> None:
        if account.lane != B_LANE:
            raise ProtectorRefusal("B's protector runs only on the slot-2 B paper lane")
        self._client = client
        self._account = account
        self._parameters = parameters
        self._now_ns = now_ns
        self._on_page = on_page
        self._on_state = on_state
        self._history = history
        self.pages: list[Page] = []
        self.states: list[str] = []
        self._feed = feed
        self._last_quote_ns: dict[str, int] = {}
        self._last_poll_ns: int | None = None
        self._feed_silent: set[str] = set()
        self._age_flagged: dict[str, int] = {}
        self._announced: dict[str, tuple[object, ...]] = {}
        self._cancelling: set[str] = set()
        self._unresolved: dict[str, str] = {}
        self._last_position: dict[str, Decimal] = {}
        self._last_reserved: dict[str, Decimal] = {}
        self._exit_params = exit_params if exit_params is not None else ExitParams.starts()
        self._outside: dict[str, OutsideRthTrail] = {}
        self._pending_release: dict[str, _PendingRelease] = {}
        self._pending_rearm: dict[str, str] = {}
        self._released_symbols: set[str] = set()
        self._house: dict[str, list[Order]] = {}
        self._sequence = 0
        self._tape_off_loop = tape_off_loop
        self._tape_notes: dict[str, str] = {}
        self._tape_paged: set[tuple[str, int]] = set()
        self._tape_levels: dict[str, Decimal] = {}
        self._tape_adoptions: dict[str, int] = {}
        self._tape_attempts: dict[str, tuple[int, tuple[str, Decimal, int]]] = {}
        self._tape_results: dict[tuple[str, Decimal, int], Decimal | None] = {}
        opened_ns = self._now_ns()
        self._feed_started_ns: int | None = opened_ns if feed != "none" else None
        self._segment_start_ns = session_start_ns(opened_ns)
        self._last_reconcile_ns = opened_ns
        self._last_session = session_at(opened_ns)

    def page(self, reason: str, symbol: str | None = None, detail: str = "") -> None:
        page = Page(reason=reason, symbol=symbol, detail=detail)
        self.pages.append(page)
        if self._on_page is not None:
            self._on_page(page)

    def bind(self) -> None:
        """Confirm the broker account number before the stream starts."""

        fetched = self._client.get_account()
        if fetched.account_number != self._account.account_id:
            self.page("account_number_mismatch")
            raise ProtectorRefusal(
                "the broker account number does not match the configured B paper account"
            )

    def emulated_trigger(self, symbol: str) -> Decimal | None:
        """The trigger the outside-RTH node is currently watching, if any."""

        state = self._outside.get(symbol)
        return None if state is None else state.trigger

    def _poll_age(self, now_ns: int) -> str:
        """How long ago the poller last succeeded, or none before its first success."""

        if self._last_poll_ns is None:
            return "none"
        elapsed_ns = max(0, now_ns - self._last_poll_ns)
        return f"{Decimal(elapsed_ns) / NS_PER_SECOND:.1f}s"

    def _quote_age(self, symbol: str, now_ns: int) -> str:
        """How old the newest quote for this symbol is, or none when it has not seen one."""

        quote_ns = self._last_quote_ns.get(symbol)
        if quote_ns is None:
            return "none"
        elapsed_ns = max(0, now_ns - quote_ns)
        return f"{Decimal(elapsed_ns) / NS_PER_SECOND:.1f}s"

    def _poll_fresh(self, now_ns: int) -> bool:
        if self._feed == "none" or self._last_poll_ns is None:
            return False
        bound_ns = int(self._parameters.feed_silence_s * NS_PER_SECOND)
        return now_ns - self._last_poll_ns <= bound_ns

    def _priceable(self, session: Session, symbol: str, now_ns: int) -> bool:
        """True while a reference that can actually protect this symbol's shares is live.

        Outside regular hours the poller is the liveness signal; its standing quote for this
        symbol is the reference. This one predicate governs the state line, the watchdog and
        the release price, so the line never claims protection the release would refuse.
        """

        if session is Session.RTH:
            return True
        if session not in (Session.PRE, Session.POST, Session.OVERNIGHT):
            return False
        return self._poll_fresh(now_ns) and symbol in self._last_quote_ns

    def _state_snapshot(self, symbol: str, now_ns: int) -> tuple[str, tuple[object, ...]]:
        """Render the one-line custody and protection state, with its change key."""

        position = self._last_position.get(symbol, Decimal(0))
        orders = [
            order
            for order in self._house.get(symbol, [])
            if str(getattr(order, "id", "")) not in self._cancelling
        ]
        trails = [order for order in orders if not _is_limit(order)]
        limit = next((order for order in orders if _is_limit(order)), None)
        trail = trails[0] if trails else None
        resting = trail or limit
        session = session_at(now_ns)
        armed = self._priceable(session, symbol, now_ns)
        protected = sum((_leaves(order) for order in trails), Decimal(0)) if armed else Decimal(0)
        trigger: object | None = None
        basis: str | None = None
        if armed and symbol not in self._released_symbols:
            if trail is not None and session is Session.RTH:
                trigger = trail.stop_price
                basis = "trade"
            elif session in (Session.PRE, Session.POST, Session.OVERNIGHT):
                state = self._outside.get(symbol)
                if state is not None and state.has_trigger and not state.released:
                    trigger = state.trigger
                    basis = "bid"
        order_id = "none" if resting is None else str(resting.id)
        note = self._tape_notes.get(symbol)
        line = (
            f"state mode={session.value} symbol={_safe_symbol(symbol)} "
            f"position={_state_number(position)} protected={_state_number(protected)} "
            f"trigger={_state_number(trigger)} on={basis or 'none'} order={order_id} "
            f"feed={_safe_symbol(self._feed)} poll_age={self._poll_age(now_ns)} "
            f"quote_age={self._quote_age(symbol, now_ns)}"
        )
        if note is not None:
            line += f" tape={note}"
        key = (
            session.value,
            _state_number(position),
            _state_number(protected),
            tuple(sorted(str(order.id) for order in orders)),
            basis or "none",
            _safe_symbol(self._feed),
            note or "none",
        )
        return line, key

    def _emit_state(self, line: str) -> None:
        self.states.append(line)
        if self._on_state is not None:
            try:
                self._on_state(line)
            except Exception:
                # A broken log sink must never change the protection path.
                self._on_state = None

    def _announce_symbol(self, symbol: str, now_ns: int) -> None:
        held = symbol in self._last_position
        if not held and symbol not in self._announced:
            return
        line, key = self._state_snapshot(symbol, now_ns)
        if not held:
            self._emit_state(line)
            self._announced.pop(symbol, None)
            return
        if self._announced.get(symbol) != key:
            self._emit_state(line)
            self._announced[symbol] = key

    def _announce_states(self, now_ns: int) -> None:
        for symbol in sorted(set(self._last_position) | set(self._announced)):
            self._announce_symbol(symbol, now_ns)

    def set_feed(self, feed: str) -> None:
        """Switch the session's feed; a new observation window starts at the session boundary."""

        at = self._now_ns()
        segment_start_ns = session_start_ns(at)
        if feed == self._feed:
            if segment_start_ns == self._segment_start_ns:
                return
            self._segment_start_ns = segment_start_ns
            self._last_quote_ns.clear()
            self._feed_silent.clear()
            self._age_flagged.clear()
            for state in self._outside.values():
                state.reset_run()
            return
        self._feed = feed
        self._segment_start_ns = segment_start_ns
        self._last_quote_ns.clear()
        self._last_poll_ns = None
        self._feed_silent.clear()
        self._age_flagged.clear()
        self._feed_started_ns = at if feed != "none" else None
        for state in self._outside.values():
            state.reset_run()

    def held_symbols(self) -> tuple[str, ...]:
        """The symbols the broker currently reports as held."""

        return tuple(sorted(self._last_position))

    def note_poll(self, ts_ns: int | None = None) -> None:
        """Record one successful poll; liveness is measured from this receipt, not a quote."""

        at = self._now_ns() if ts_ns is None else ts_ns
        self._last_poll_ns = at if self._last_poll_ns is None else max(self._last_poll_ns, at)

    def watch(self, now_ns: int | None = None) -> None:
        """Page when the poller stops, then announce the state and any standing-quote age."""

        at = self._now_ns() if now_ns is None else now_ns
        session = session_at(at)
        if session in (Session.PRE, Session.POST, Session.OVERNIGHT):
            self._watch_feed(session, at)
            self._announce_standing_ages(at)
        else:
            self._feed_silent.clear()
            self._age_flagged.clear()
        self._announce_states(at)

    def _watch_feed(self, session: Session, now_ns: int) -> None:
        held = set(self._last_position)
        self._feed_silent &= held
        if self._poll_fresh(now_ns):
            for symbol in sorted(held):
                if symbol in self._last_quote_ns:
                    self._feed_silent.discard(symbol)
                    continue
                if symbol in self._feed_silent:
                    continue
                self._feed_silent.add(symbol)
                self.page(
                    "outside_rth_feed_silent",
                    symbol,
                    "polls succeed but no quote for this symbol; protection unarmed",
                )
            return
        bound_ns = int(self._parameters.feed_silence_s * NS_PER_SECOND)
        for symbol in sorted(held):
            if symbol in self._feed_silent:
                continue
            if self._feed == "none":
                detail = "no market-data feed; outside-RTH protection unarmed"
            elif self._last_poll_ns is None:
                started = self._feed_started_ns
                if started is None or now_ns - started <= bound_ns:
                    continue
                detail = (
                    f"no successful poll since feed {_safe_symbol(self._feed)} opened, "
                    f"bound {self._parameters.feed_silence_s}s; protection unarmed"
                )
            else:
                age_ns = max(0, now_ns - self._last_poll_ns)
                if age_ns <= bound_ns:
                    continue
                detail = (
                    f"last successful poll {Decimal(age_ns) / NS_PER_SECOND:.1f}s ago, "
                    f"bound {self._parameters.feed_silence_s}s; protection unarmed"
                )
            self._feed_silent.add(symbol)
            self.page("outside_rth_feed_silent", symbol, detail)

    def _announce_standing_ages(self, now_ns: int) -> None:
        """Emit one line when a still-armed quote crosses the silence bound.

        This is observability, not a second arm/disarm rule: the poller's success keeps the
        shares protected, and the line makes the older quote visible instead of calling it a
        silent feed.
        """

        if not self._poll_fresh(now_ns):
            return
        bound_ns = int(self._parameters.feed_silence_s * NS_PER_SECOND)
        for symbol in sorted(self._last_position):
            quote_ns = self._last_quote_ns.get(symbol)
            if quote_ns is None:
                continue
            age_ns = max(0, now_ns - quote_ns)
            if age_ns <= bound_ns:
                self._age_flagged.pop(symbol, None)
                continue
            if self._age_flagged.get(symbol) == quote_ns:
                continue
            line, key = self._state_snapshot(symbol, now_ns)
            self._emit_state(line)
            self._announced[symbol] = key
            self._age_flagged[symbol] = quote_ns

    def on_quote(
        self,
        symbol: str,
        *,
        bid: Decimal | None,
        ask: Decimal | None,
        last: Decimal | None,
        ts_ns: int | None = None,
    ) -> Decimal | None:
        """Feed one outside-RTH quote to the emulated trailing trigger.

        The node's data adapter calls this; in the regular session the native trail owns the
        trigger, so the observation is ignored there.
        """

        at = self._now_ns() if ts_ns is None else ts_ns
        session = session_at(at)
        if session not in (Session.PRE, Session.POST, Session.OVERNIGHT):
            return None
        if session is not self._last_session:
            # Adopt the resting native stop before the first observation of a new session can
            # seed an emulated trigger below it.
            self.reconcile()
        if at < self._segment_start_ns:
            return None
        if bid is None or ask is None or bid <= 0 or ask <= 0 or bid > ask:
            return None
        previous = self._last_quote_ns.get(symbol)
        if previous is not None and at < previous:
            return None
        self._last_quote_ns[symbol] = at if previous is None else max(previous, at)
        return self._outside_state(symbol).observe_quote(bid=bid, ask=ask, last=last, ts_ns=at)

    def on_trade(self, symbol: str, price: Decimal, ts_ns: int | None = None) -> bool:
        """Feed one outside-RTH trade; true when it completes a persistent breach."""

        at = self._now_ns() if ts_ns is None else ts_ns
        session = session_at(at)
        if session not in (Session.PRE, Session.POST, Session.OVERNIGHT):
            return False
        if session is not self._last_session:
            self.reconcile()
        if at < self._segment_start_ns:
            return False
        state = self._outside.get(symbol)
        if state is None or not state.observe_trade(price, at):
            return False
        self._begin_outside_release(symbol)
        return True

    def _outside_state(self, symbol: str) -> OutsideRthTrail:
        state = self._outside.get(symbol)
        if state is None:
            state = OutsideRthTrail(
                trail_fraction=self._parameters.native_trail_fraction,
                params=self._exit_params,
            )
            self._outside[symbol] = state
        return state

    def _tape_key(self, symbol: str, qty: Decimal) -> tuple[str, Decimal, int]:
        return (symbol, qty, self._segment_start_ns)

    def apply_tape(self, result: TapeRead, now_ns: int) -> None:
        """Record one tape read; only the running high may move, and never down."""

        symbol = result.symbol
        key = self._tape_key(symbol, result.qty)
        self._tape_adoptions[symbol] = result.adoption_ns
        if result.status == "ok":
            self._tape_notes[symbol] = "ok"
            self._tape_results[key] = result.level
        else:
            self._tape_notes[symbol] = result.status
            page_key = (symbol, self._segment_start_ns)
            if page_key not in self._tape_paged:
                self._tape_paged.add(page_key)
                self.page(result.reason or "outside_rth_tape_unreadable", symbol, result.detail)
        if result.level is None:
            return
        prior = self._tape_levels.get(symbol)
        if prior is None or result.level > prior:
            self._tape_levels[symbol] = result.level
        state = self._outside.get(symbol)
        if state is None or state.released or state.pending:
            return
        if state.trigger is not None and state.trigger >= result.level:
            return
        state.adopt(result.level, now_ns)

    def _rebuilt_trigger(self, symbol: str, now_ns: int) -> Decimal | None:
        """The rebuilt high-water mark; the off-loop stream reads on a cadence, tests inline."""

        if self._history is None:
            return None
        if self._tape_off_loop:
            return self._tape_levels.get(symbol)
        qty = self._last_position.get(symbol, Decimal(0))
        key = self._tape_key(symbol, qty)
        if key in self._tape_results:
            return self._tape_results[key]
        result = read_tape(
            self._client,
            self._history,
            symbol,
            qty,
            now_ns,
            trail_fraction=self._parameters.native_trail_fraction,
            params=self._exit_params,
            house_prefix=self._account.house_prefix,
        )
        self.apply_tape(result, now_ns)
        return self._tape_results.get(key)

    def tape_candidates(self, now_ns: int) -> list[tuple[str, Decimal]]:
        """Held symbols whose tape still needs a complete read for this segment."""

        if self._history is None:
            return []
        if session_at(now_ns) not in (Session.PRE, Session.POST, Session.OVERNIGHT):
            return []
        interval_ns = int(self._parameters.reconcile_interval_s * NS_PER_SECOND)
        candidates: list[tuple[str, Decimal]] = []
        for symbol in sorted(self._last_position):
            qty = self._last_position.get(symbol, Decimal(0))
            if qty <= 0:
                continue
            key = self._tape_key(symbol, qty)
            if key in self._tape_results:
                continue
            attempt = self._tape_attempts.get(symbol)
            if attempt is not None and attempt[1] == key and now_ns - attempt[0] < interval_ns:
                continue
            candidates.append((symbol, qty))
        return candidates

    def begin_tape(self, symbol: str, qty: Decimal, now_ns: int) -> None:
        """Mark an off-loop read as started; until it lands the line says none, not ok."""

        key = self._tape_key(symbol, qty)
        self._tape_attempts[symbol] = (now_ns, key)
        if key not in self._tape_results:
            self._tape_notes[symbol] = "none"

    def tape_timed_out(self, symbol: str, now_ns: int) -> None:
        """The read outlived its budget: page once, keep the trigger already in hand."""

        self._tape_notes[symbol] = "none"
        page_key = (symbol, self._segment_start_ns)
        if page_key not in self._tape_paged:
            self._tape_paged.add(page_key)
            self.page(
                "outside_rth_tape_unreadable",
                symbol,
                "the historical read exceeded its time budget",
            )

    def tape_failed(self, symbol: str, now_ns: int, detail: str) -> None:
        """An off-loop read died outside read_tape's own handling; retry next tick."""

        self._tape_notes[symbol] = "none"
        page_key = (symbol, self._segment_start_ns)
        if page_key not in self._tape_paged:
            self._tape_paged.add(page_key)
            self.page("outside_rth_tape_unreadable", symbol, detail)

    def _adopt_outside(self, symbol: str, order: Order) -> None:
        """Keep the higher of the native stop, the existing trigger and the rebuilt tape high."""

        state = self._outside_state(symbol)
        if state.released or state.pending:
            return
        stop_price = getattr(order, "stop_price", None)
        if stop_price is None:
            self.page(
                "outside_rth_trigger_missing",
                symbol,
                "the resting native trail has no stop price to emulate",
            )
            return
        stop = _decimal(str(stop_price), "order.stop_price")
        now_ns = self._now_ns()
        rebuilt = self._rebuilt_trigger(symbol, now_ns)
        seed = stop if rebuilt is None or rebuilt <= stop else rebuilt
        if state.trigger is not None and state.trigger >= seed:
            return
        state.adopt(seed, now_ns)

    def _begin_outside_release(self, symbol: str) -> None:
        """Cancel the trail and release one LIMIT after its terminal cancellation."""

        state = self._outside.get(symbol)
        if state is None or state.released or state.pending or symbol in self._released_symbols:
            return
        trails = [order for order in self._house.get(symbol, []) if not _is_limit(order)]
        if len(trails) != 1:
            self.page(
                "outside_rth_no_trail_at_breach",
                symbol,
                "the breach has no single resting native trail to cancel",
            )
            return
        now_ns = self._now_ns()
        fresh = self._priceable(session_at(now_ns), symbol, now_ns)
        try:
            state.release_price(now_ns, fresh=fresh)
        except OutsideRthError as exc:
            self.page("outside_rth_release_unpriced", symbol, str(exc))
            return
        available = self._last_position.get(symbol, Decimal(0)) - self._last_reserved.get(
            symbol, Decimal(0)
        )
        whole = int(available.to_integral_value(rounding=ROUND_FLOOR)) if available > 0 else 0
        if whole <= 0:
            self.page("outside_rth_release_unquantified", symbol, "no unreserved whole share")
            return
        if not self._cancel(trails[0], "outside_rth_breach"):
            return
        self._pending_release[symbol] = _PendingRelease(trail_order_id=str(trails[0].id))
        state.begin_release(now_ns)
        self._announce_symbol(symbol, now_ns)

    def _complete_outside_release(self, symbol: str) -> None:
        """Reprice and re-quantify from a fresh snapshot, then submit the one LIMIT."""

        state = self._outside.get(symbol)
        if state is None:
            self._released_symbols.discard(symbol)
            return
        now_ns = self._now_ns()
        if session_at(now_ns) is Session.CLOSED:
            state.rearm()
            self._released_symbols.discard(symbol)
            self.page("market_closed", symbol, "B writes only in an open session")
            return
        positions = self.reconcile()
        if symbol not in positions:
            state.rearm()
            self._released_symbols.discard(symbol)
            return
        now_ns = self._now_ns()
        fresh = self._priceable(session_at(now_ns), symbol, now_ns)
        try:
            price = state.release_price(now_ns, fresh=fresh)
        except OutsideRthError as exc:
            state.rearm()
            self._released_symbols.discard(symbol)
            self.page("outside_rth_release_unpriced", symbol, str(exc))
            return
        available = self._last_position.get(symbol, Decimal(0)) - self._last_reserved.get(
            symbol, Decimal(0)
        )
        whole = int(available.to_integral_value(rounding=ROUND_FLOOR)) if available > 0 else 0
        if whole <= 0:
            state.rearm()
            self._released_symbols.discard(symbol)
            self.page("outside_rth_release_unquantified", symbol, "no unreserved whole share")
            return
        self._submit_outside_limit(symbol, whole, price)

    def _submit_outside_limit(self, symbol: str, whole: int, price: Decimal) -> None:
        self._sequence += 1
        client_order_id = (
            f"{self._account.house_prefix}outside-{_safe_symbol(symbol)}-"
            f"{self._now_ns()}-{self._sequence}"
        )
        request = LimitOrderRequest(
            symbol=symbol,
            qty=whole,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            limit_price=str(price),
            extended_hours=True,
            client_order_id=client_order_id[:MAX_CLIENT_ORDER_ID],
        )
        try:
            submitted = self._client.submit_order(request)
        except Exception as exc:
            state = self._outside.get(symbol)
            if state is not None:
                state.rearm()
            self._released_symbols.discard(symbol)
            self.page("outside_limit_submit_failed", symbol, type(exc).__name__)
            return
        if isinstance(submitted, Order):
            self._remember(submitted)
        state = self._outside.get(symbol)
        if state is not None:
            state.mark_released(self._now_ns())
        self._announce_symbol(symbol, self._now_ns())

    def handle(self, update: TradeUpdate) -> None:
        symbol = update.order.symbol
        if not symbol:
            return
        try:
            self._handle_update(update, symbol)
        except PacerRefused as exc:
            # The pacer retains the deferred call; the next event reconciles again.
            self.page("pacer_refused", symbol, str(exc))

    def _handle_update(self, update: TradeUpdate, symbol: str) -> None:
        event = _event_name(update.event)
        if self._is_ours(update.order):
            self._handle_house(update, symbol, event)
            return
        # Any owner order event may change a reservation or the position: reconcile and
        # re-arm. Non-fill events never freeze the symbol.
        self.reconcile()

    def reconcile_when_due(self) -> bool:
        """Reconcile on B's cadence, and once when the session changes.

        A trade update reconciles only because the owner or the broker acted; the cadence is
        what notices a trail the broker lost while nothing happened. A session change is its
        own trigger so the native trail's stop is adopted at the boundary, before the new
        session's first quote can seed an emulated trigger below it. Returns whether a
        reconcile ran.
        """

        now = self._now_ns()
        session = session_at(now)
        changed = session is not self._last_session
        interval_ns = int(self._parameters.reconcile_interval_s * NS_PER_SECOND)
        if not changed and now - self._last_reconcile_ns < interval_ns:
            return False
        self.reconcile()
        return True

    def reconcile(self, *, announce: bool = True) -> dict[str, Position]:
        """Match the broker's open orders and positions, then protect the whole net shares.

        Every unreserved whole long share is covered by exactly one house trail of the full
        net quantity; a change in that quantity re-arms it during regular market hours.
        ``announce=False`` lets a startup reconcile precede the first market-data poll, so the
        one startup line names the live feed rather than an empty one.
        """

        now_ns = self._now_ns()
        self._last_reconcile_ns = now_ns
        self._last_session = session_at(now_ns)
        try:
            positions, house, owner_sells, unrecognized = self._snapshot()
        except ProtectorRefusal as exc:
            self.page("open_orders_truncated", None, str(exc))
            return {}
        self._house = {symbol: list(ours) for symbol, ours in house.items()}
        self._last_position = {
            symbol: _decimal(position.qty, "position.qty") for symbol, position in positions.items()
        }
        self._last_reserved = {symbol: owner_sells.get(symbol, Decimal(0)) for symbol in positions}
        for symbol, position in positions.items():
            self._reconcile_symbol(
                symbol,
                position,
                house.pop(symbol, []),
                owner_sells.get(symbol, Decimal(0)),
                symbol in unrecognized,
            )
        for symbol, ours in house.items():
            if symbol not in positions:
                for order in ours:
                    self._cancel(order, "flat_with_house_exit")
        held = set(positions)
        self._outside = {s: state for s, state in self._outside.items() if s in held}
        self._pending_release = {
            s: pending for s, pending in self._pending_release.items() if s in held
        }
        self._pending_rearm = {
            s: order_id for s, order_id in self._pending_rearm.items() if s in held
        }
        self._released_symbols &= held
        self._tape_notes = {s: note for s, note in self._tape_notes.items() if s in held}
        self._tape_paged = {key for key in self._tape_paged if key[0] in held}
        self._tape_levels = {s: level for s, level in self._tape_levels.items() if s in held}
        self._tape_adoptions = {s: ns for s, ns in self._tape_adoptions.items() if s in held}
        self._tape_attempts = {
            s: attempt for s, attempt in self._tape_attempts.items() if s in held
        }
        self._tape_results = {
            key: level for key, level in self._tape_results.items() if key[0] in held
        }
        if announce:
            self._announce_states(now_ns)
        return positions

    def _snapshot(
        self,
    ) -> tuple[
        dict[str, Position],
        dict[str, list[Order]],
        dict[str, Decimal],
        set[str],
    ]:
        """Read positions and open orders, without changing anything at the broker."""

        positions = {
            position.symbol: position
            for position in self._client.get_all_positions()
            if position.symbol
        }
        orders = self._client.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=OPEN_ORDER_LIMIT)
        )
        if len(orders) >= OPEN_ORDER_LIMIT:
            raise ProtectorRefusal("open order snapshot hit the page limit and may be truncated")
        house: dict[str, list[Order]] = {}
        owner_sells: dict[str, Decimal] = {}
        unrecognized: set[str] = set()
        for order in orders:
            if not order.symbol:
                continue
            if self._is_ours(order):
                house.setdefault(order.symbol, []).append(order)
                continue
            side = _event_name(order.side).lower()
            if side == "sell":
                leaves = owner_sells.get(order.symbol, Decimal(0)) + _leaves(order)
                owner_sells[order.symbol] = leaves
            elif side != "buy":
                unrecognized.add(order.symbol)
        return positions, house, owner_sells, unrecognized

    def _cancel_all(self, ours: list[Order], reason: str) -> None:
        for order in ours:
            self._cancel(order, reason)

    def _cancel_excess(self, ours: list[Order], protective: int, reason: str) -> list[Order]:
        """Cancel house exits beyond one trail no larger than the protective quantity."""

        if len(ours) > 1:
            eligible = [order for order in ours if _leaves(order) <= protective]
            keeper = max(eligible, key=_leaves) if eligible else None
            for order in ours:
                if order is not keeper:
                    self._cancel(order, reason)
            return [keeper] if keeper is not None else []
        if ours and _leaves(ours[0]) > protective:
            self._cancel(ours[0], reason)
            return []
        return list(ours)

    def _handle_house(self, update: TradeUpdate, symbol: str, event: str) -> None:
        if event in FILL_EVENTS:
            self.reconcile()
            return
        order_id = str(update.order.id)
        if event == "replaced":
            self.page("house_exit_lost", symbol, "a house exit was replaced elsewhere")
            self.reconcile()
            return
        if event in TERMINAL_EVENTS:
            known = order_id in self._cancelling
            self._cancelling.discard(order_id)
            pending = self._pending_release.get(symbol)
            if pending is not None and pending.trail_order_id == order_id:
                self._pending_release.pop(symbol, None)
                if event == "canceled":
                    self._released_symbols.add(symbol)
                    self._complete_outside_release(symbol)
                else:
                    state = self._outside.get(symbol)
                    if state is not None:
                        state.rearm()
                    self.page(
                        "outside_rth_release_failed",
                        symbol,
                        f"the resting trail ended {event} before the release",
                    )
            elif self._pending_rearm.get(symbol) == order_id:
                self._pending_rearm.pop(symbol, None)
            elif not known:
                self.page("house_exit_lost", symbol, f"a house exit ended {event}")
            self.reconcile()

    def _reconcile_symbol(
        self,
        symbol: str,
        position: Position,
        ours: list[Order],
        owner_sell_reserved: Decimal,
        unrecognized_open_order: bool,
    ) -> None:
        quantity = _decimal(position.qty, "position.qty")
        if quantity < 0:
            self.page("short_position_unprotected", symbol)
            self._cancel_all(ours, "short_position")
            return
        if quantity == 0:
            self._cancel_all(ours, "flat_with_house_exit")
            return
        if unrecognized_open_order:
            self.page(
                "unrecognized_open_order",
                symbol,
                "an open order has no buy/sell side; only owner sells are netted out",
            )
        available = quantity - owner_sell_reserved
        protective = 0
        if available > 0:
            protective = int(available.to_integral_value(rounding=ROUND_FLOOR))
        if quantity != quantity.to_integral_value() or available != protective:
            self.page("fractional_custody_unverified", symbol)
        if protective == 0:
            self._cancel_all(ours, "owner_reserved_unprotected")
            self.page("owner_reserved_unprotected", symbol)
            return
        if symbol in self._unresolved:
            client_order_id = self._unresolved[symbol]
            if any(order.client_order_id == client_order_id for order in ours):
                self._unresolved.pop(symbol)
            else:
                status, detail = self._resolve_unresolved(client_order_id)
                if status == "terminal":
                    self._unresolved.pop(symbol)
                    self.page("submit_unresolved_terminal", symbol, detail)
                    return
                if status != "absent":
                    self.page("submit_unresolved", symbol, detail)
                    return
        session = session_at(self._now_ns())
        in_rth = session is Session.RTH
        # An oversized GTC trail is cancelled before the RTH guard, so it can never
        # ride into the next open; only the replacement submit waits for RTH.
        rest = self._cancel_excess(ours, protective, "rearm_full_protective_quantity")
        if symbol in self._pending_release:
            # The breach already decided the release; wait for the trail's terminal
            # cancellation instead of arming a second exit beside it.
            return
        if symbol in self._pending_rearm:
            # A resize waits for the old exit's terminal event before it replaces it.
            return
        if session is Session.CLOSED:
            self.page("market_closed", symbol, "B writes only in an open session")
            return
        if len(rest) == 1 and _leaves(rest[0]) == protective:
            if _is_limit(rest[0]):
                self._released_symbols.discard(symbol)
            elif not in_rth:
                self._adopt_outside(symbol, rest[0])
            return
        if not in_rth:
            for order in rest:
                if self._cancel(order, "outside_rth_resize"):
                    self._pending_rearm[symbol] = str(order.id)
            if ours:
                return
            if symbol in self._released_symbols:
                return
            self._submit_trail(symbol, protective)
            return
        for order in rest:
            if self._cancel(order, "rearm_full_protective_quantity"):
                self._pending_rearm[symbol] = str(order.id)
        # The terminal canceled event of the house's own trail drives reconcile(),
        # which submits the single replacement; never submit over a live exit.
        if ours:
            return
        if symbol in self._released_symbols:
            # The release handover is about to submit its LIMIT from a fresh
            # snapshot; never arm a second full-position exit beside it.
            return
        self._submit_trail(symbol, protective)

    def _resolve_unresolved(self, client_order_id: str) -> tuple[str, str]:
        """Resolve a submit that timed out before allocating another exit identity."""

        try:
            order = self._client.get_order_by_client_id(client_order_id)
        except APIError as exc:
            if exc.status_code == 404:
                return "absent", "the broker has no order with the retained client order id"
            return "unknown", f"APIError {exc.status_code}"
        except Exception as exc:
            return "unknown", type(exc).__name__
        status = _event_name(order.status)
        if status == "filled" or status in TERMINAL_EVENTS:
            return "terminal", f"the broker order with the retained identity is {status}"
        return "open", f"the broker still lists the retained order as {status}"

    def _submit_trail(self, symbol: str, whole: int) -> None:
        client_order_id = self._unresolved.get(symbol)
        if client_order_id is None:
            self._sequence += 1
            client_order_id = (
                f"{self._account.house_prefix}trail-{_safe_symbol(symbol)}-"
                f"{self._now_ns()}-{self._sequence}"
            )[:MAX_CLIENT_ORDER_ID]
        request = TrailingStopOrderRequest(
            symbol=symbol,
            qty=whole,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            trail_percent=float(self._parameters.native_trail_fraction * 100),
            client_order_id=client_order_id,
        )
        try:
            submitted = self._client.submit_order(request)
        except PacerRefused:
            # The pacer retains the deferred submit and sends it on a later drain.
            raise
        except Exception as exc:
            self._unresolved[symbol] = client_order_id
            self.page("trail_submit_failed", symbol, type(exc).__name__)
            return
        self._unresolved.pop(symbol, None)
        if isinstance(submitted, Order):
            self._remember(submitted)

    def _remember(self, order: Order) -> None:
        """Keep an order the broker just accepted so the next breach can find it."""

        if not order.symbol:
            return
        ours = self._house.setdefault(order.symbol, [])
        if all(str(existing.id) != str(order.id) for existing in ours):
            ours.append(order)

    def _cancel(self, order: Order, reason: str) -> bool:
        if not self._is_ours(order):
            raise ProtectorRefusal("refusing to cancel an order the house does not own")
        order_id = str(order.id)
        self._cancelling.add(order_id)
        try:
            self._client.cancel_order_by_id(order.id)
        except Exception as exc:
            self._cancelling.discard(order_id)
            self.page("cancel_failed", order.symbol, f"{reason}: {type(exc).__name__}")
            return False
        if _is_limit(order) and order.symbol is not None:
            # A cancelled release no longer blocks re-arming protection, and the
            # emulator must accept quotes again for whatever exit replaces it.
            self._released_symbols.discard(order.symbol)
            state = self._outside.get(order.symbol)
            if state is not None:
                state.rearm()
        return True

    def _is_ours(self, order: Order) -> bool:
        return bool(order.client_order_id) and order.client_order_id.startswith(
            self._account.house_prefix
        )


class ProtectorStream(TradingStream):
    """The SDK's trade-update stream with reconcile hooks on (re)connect and on a cadence."""

    # The registry interval is the policy; a one-second tick only bounds its jitter.
    SCHEDULE_TICK_S = 1.0

    def __init__(
        self,
        client: TradingClientLike,
        account: PaperAccount,
        parameters: BParameters,
        *,
        api_key: str,
        secret_key: str,
        paper: bool = True,
        url_override: str | None = None,
        now_ns: Callable[[], int] = time.time_ns,
        on_page: Callable[[Page], None] | None = None,
        feed: str = "none",
        on_state: Callable[[str], None] | None = None,
        data_client: LatestDataClient | None = None,
    ) -> None:
        if url_override is None:
            super().__init__(api_key=api_key, secret_key=secret_key, paper=paper)
        else:
            super().__init__(
                api_key=api_key,
                secret_key=secret_key,
                paper=paper,
                url_override=url_override,
            )
        self._parameters = parameters
        self._now_ns = now_ns
        self._market_data = BMarketDataFeed(data_client) if data_client is not None else None
        self._history = (
            BHistoricalTape(cast(HistoricalQuoteClient, data_client))
            if data_client is not None
            else None
        )
        self._last_feed_poll_ns = 0
        self._feed_failure: str | None = None
        self._feed_label = "none"
        self._poll_task: asyncio.Task[FeedBatch] | None = None
        self._tape_task: asyncio.Task[TapeRead] | None = None
        self._tape_symbol = ""
        self._tape_started_ns = 0
        self._tape_timed_out = False
        self.protector = Protector(
            client,
            account,
            parameters,
            now_ns=now_ns,
            on_page=on_page,
            feed=feed,
            on_state=on_state,
            history=self._history,
            tape_off_loop=True,
        )
        self.subscribe_trade_updates(self._on_trade_update)

    def _page_feed_failure(self, detail: str) -> None:
        if self._feed_failure == detail:
            return
        self._feed_failure = detail
        self.protector.page("feed_failed", None, detail)

    async def _await_startup_poll(self) -> None:
        """Wait only the silence bound for the first poll; a stalled poll must not hide it."""

        task = self._poll_task
        if task is None:
            return
        bound_s = float(self._parameters.feed_silence_s)
        done, _ = await asyncio.wait({task}, timeout=bound_s)
        if not done:
            self._page_feed_failure(f"{self._feed_label}: TimeoutError")
            return
        self._drain_poll()

    def _drain_poll(self) -> None:
        """Apply a completed poll and record its success; a stalled poll keeps the old receipt."""

        task = self._poll_task
        if task is None or not task.done():
            return
        self._poll_task = None
        try:
            batch = task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self._page_feed_failure(f"{self._feed_label}: {type(exc).__name__}")
            return
        self._feed_failure = None
        self.protector.note_poll(self._now_ns())
        for quote in batch.quotes:
            self.protector.on_quote(
                quote.symbol,
                bid=quote.bid,
                ask=quote.ask,
                last=quote.last,
                ts_ns=quote.ts_ns,
            )
        for trade in batch.trades:
            self.protector.on_trade(trade.symbol, trade.price, trade.ts_ns)

    def _poll_feed(self, *, force: bool = False) -> None:
        """Start one background REST poll; the watch keeps running while it is in flight."""

        if self._market_data is None:
            return
        now_ns = self._now_ns()
        feed = feed_for(session_at(now_ns))
        self.protector.set_feed(feed or "none")
        if feed is None:
            return
        symbols = self.protector.held_symbols()
        if not symbols:
            return
        if self._poll_task is not None:
            return
        interval_ns = int(self._parameters.feed_poll_interval_s * 1_000_000_000)
        if not force and now_ns - self._last_feed_poll_ns < interval_ns:
            return
        self._last_feed_poll_ns = now_ns
        self._feed_label = feed
        self._poll_task = asyncio.create_task(
            asyncio.to_thread(self._market_data.poll, symbols, feed)
        )

    def _poll_tape(self, *, force: bool = False) -> None:
        """Start one off-loop tape read for the first symbol that still needs it."""

        if self._history is None or self._tape_task is not None:
            return
        now_ns = self._now_ns()
        candidates = self.protector.tape_candidates(now_ns)
        if not candidates:
            return
        symbol, qty = candidates[0]
        self.protector.begin_tape(symbol, qty, now_ns)
        self._tape_symbol = symbol
        self._tape_started_ns = now_ns
        self._tape_timed_out = False
        self._tape_task = asyncio.create_task(
            asyncio.to_thread(
                read_tape,
                self.protector._client,
                self._history,
                symbol,
                qty,
                now_ns,
                trail_fraction=self._parameters.native_trail_fraction,
                params=self.protector._exit_params,
                house_prefix=self.protector._account.house_prefix,
            )
        )

    def _drain_tape(self) -> None:
        """Apply a landed tape result, or page once when it outlives its time budget."""

        task = self._tape_task
        if task is None:
            return
        now_ns = self._now_ns()
        if not task.done():
            if not self._tape_timed_out:
                budget_ns = int(self._parameters.feed_silence_s * NS_PER_SECOND)
                if now_ns - self._tape_started_ns >= budget_ns:
                    self._tape_timed_out = True
                    self.protector.tape_timed_out(self._tape_symbol, now_ns)
            return
        self._tape_task = None
        try:
            result = task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self.protector.tape_failed(self._tape_symbol, now_ns, type(exc).__name__)
            return
        self.protector.apply_tape(result, now_ns)

    async def _on_trade_update(self, update: TradeUpdate) -> None:
        try:
            self.protector.handle(update)
        except Exception as exc:
            self.protector.page("trade_update_failed", update.order.symbol, type(exc).__name__)

    async def _start_ws(self) -> None:
        await super()._start_ws()
        try:
            self.protector.reconcile(announce=False)
        except Exception as exc:
            self.protector.page("reconcile_failed", None, type(exc).__name__)
        try:
            self._poll_tape(force=True)
        except Exception as exc:
            self.protector.page("tape_failed", None, type(exc).__name__)
        try:
            self._poll_feed(force=True)
            await self._await_startup_poll()
        except Exception as exc:
            self.protector.page("feed_failed", None, type(exc).__name__)
        try:
            self.protector.watch()
        except Exception as exc:
            self.protector.page("feed_watch_failed", None, type(exc).__name__)

    async def _scheduled_reconcile(self) -> None:
        while True:
            await asyncio.sleep(self.SCHEDULE_TICK_S)
            try:
                self._drain_poll()
                self._poll_feed()
            except Exception as exc:
                self.protector.page("feed_failed", None, type(exc).__name__)
            try:
                self._drain_tape()
                self._poll_tape()
            except Exception as exc:
                self.protector.page("tape_failed", None, type(exc).__name__)
            try:
                self.protector.watch()
            except Exception as exc:
                self.protector.page("feed_watch_failed", None, type(exc).__name__)
            try:
                self.protector.reconcile_when_due()
            except Exception as exc:
                self.protector.page("reconcile_failed", None, type(exc).__name__)

    async def _run_forever(self) -> None:
        schedule = asyncio.create_task(self._scheduled_reconcile())
        try:
            await super()._run_forever()
        finally:
            schedule.cancel()
            try:
                await schedule
            except asyncio.CancelledError:
                pass

    def run(self) -> None:
        self.protector.bind()
        super().run()
