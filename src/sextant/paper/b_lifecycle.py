"""Paper B's lifecycle as one NautilusTrader Strategy (LEAD-2201 S1, component map rows 1-2).

S1-1, ranking in: ``on_start`` subscribes to the ranking data type and ``on_data`` feeds the
reviewed ``RankingConsumer``, the code ``RankingDataActor`` runs (consumer.py:221-232), moved
into the Strategy because a Strategy is an Actor (rc8 trading stub ``subscribe_data``
:690-694, ``on_data`` :632). Each candidate decision reads the consumer's current
``entry_rank`` and the default-off rank gate; a stale, missing or refused generation gives no
candidate and the consumer's reason (ADR-0003, ADR-0006 R5). The heartbeat reaches
``consumer.accept_heartbeat`` from its host; this Strategy never manufactures one.

S1-2, entry (ADR-0004 N1/N4/N5): C's reviewed first-leg wiring (c_session.py: EntryState,
advance_surge, first_leg_ready) and the reviewed native entry episode (entry/replay.py: LIMIT
at ``limit_price(ask)``, reprice inside ``entry_chase_bps``, TTL cancel by its own id). The
order is built in the completing trade's handler with ``order_factory.limit`` (common stub
:1388-1406), sized by ``size_entry``/``FixedRiskSizer`` as a ``Quantity``, and sent with
``submit_order(params={"extended_hours": ...})`` (trading stub :538-543), native.py's
convention. Without B's entry rows the Strategy refuses entries and names the missing rows;
no row has a default here (Rule 2). With the rank gate off there are no house entries. One
entry per instrument: re-entry belongs to a later part. Money is Price, Quantity or Decimal.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import (
    Bar,
    ClientOrderId,
    CustomData,
    Equity,
    InstrumentId,
    OrderSide,
    Price,
    Quantity,
    QuoteTick,
    StrategyId,
    TimeInForce,
    TradeTick,
)
from nautilus_trader.trading import Strategy

from sextant.entry.orders import limit_price, within_chase
from sextant.entry.parameters import FIRST_LEG, SIZING, EntryParameters
from sextant.entry.signals import EntryState
from sextant.entry.sizing import SegmentBasis, Sizing, size_entry
from sextant.entry.surge import SurgeState, advance_surge
from sextant.exits.policy import ExitParams, buffer
from sextant.paper.sessions import Session, session_at
from sextant.ranking.baseline import BaselineTable
from sextant.ranking.consumer import RankingConsumer
from sextant.ranking.publisher import ranking_data_type
from sextant.ranking.rank_gate import RankGateDecision, RankGateStatus, decide_rank_gate
from sextant.ranking.registry import RegistryRow

Journal = Callable[[dict[str, Any]], None]
ENTRY_ROWS = FIRST_LEG | SIZING
NS = 1_000_000_000


class BLifecycleConfig(StrategyConfig):
    def __new__(cls, *, namespace: str, **_kwargs: Any):
        # rc8's PyO3 configs initialize their native fields in __new__ (native.py's shape).
        return cast(Any, super().__new__)(
            cls, strategy_id=StrategyId.from_str(f"BLIFECYCLE-{namespace}"), order_id_tag=namespace
        )

    def __init__(
        self,
        *,
        namespace: str,
        instrument_ids: Sequence[InstrumentId],
        consumer: RankingConsumer,
        rank_gate: RegistryRow,
        journal: Journal | None = None,
        entry_params: EntryParameters | None = None,
        exit_params: ExitParams | None = None,
        commission_rate: Decimal | None = None,
        basis_path: Path | None = None,
        baseline: BaselineTable | None = None,
    ) -> None:
        super().__init__()
        ids = tuple(instrument_ids)
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("B needs unique instrument ids")
        if not all(isinstance(iid, InstrumentId) for iid in ids):
            raise ValueError("B instrument ids must be native InstrumentIds")
        if not isinstance(consumer, RankingConsumer):
            raise ValueError("B needs the reviewed RankingConsumer")
        if not isinstance(rank_gate, RegistryRow) or rank_gate.name != "rank_gate_enabled":
            raise ValueError("B needs the rank_gate_enabled registry row")
        if baseline is not None and (
            baseline.identity != consumer.reader.baseline_hash or baseline.feed != consumer.feed
        ):
            raise ValueError("the surge baseline differs from the ranking's baseline")
        self.namespace, self.instrument_ids = namespace, ids
        self.consumer, self.rank_gate, self.journal = consumer, rank_gate, journal
        self.entry_params, self.exit_params = entry_params, exit_params
        self.commission_rate, self.basis_path, self.baseline = commission_rate, basis_path, baseline


@dataclass(slots=True)
class _Book:
    """Per-instrument state; later parts add protection and campaign state."""

    instrument_id: InstrumentId
    gate: RankGateDecision | None = None
    gate_ns: int | None = None
    instrument: Equity | None = None
    entry: EntryState | None = None
    surge: SurgeState = field(default_factory=SurgeState)
    quote: QuoteTick | None = None
    trades: deque[tuple[int, Decimal]] = field(default_factory=deque)
    entry_id: ClientOrderId | None = None
    first_limit: Decimal | None = None
    expiry_ns: int | None = None
    refused_flag: int | None = None


class BLifecycle(Strategy):
    """One writer's Strategy for every instrument B trades or protects (LEAD-2201 A1)."""

    def __init__(self, config: BLifecycleConfig) -> None:
        super().__init__(config)
        self.consumer, self.rank_gate = config.consumer, config.rank_gate
        self._journal = config.journal
        self.journal_errors = 0
        self.books = {iid: _Book(iid) for iid in config.instrument_ids}
        self.params, self.exit = config.entry_params, config.exit_params
        self.commission, self.baseline = config.commission_rate, config.baseline
        self.basis_path = config.basis_path
        self.basis: Decimal | None = None  # N5: frozen at node start, or no entry
        rows = self.params
        missing = sorted(n for n in ENTRY_ROWS if rows is None or not rows.has(n))
        named = (
            ("exit_params", self.exit),
            ("commission_rate", self.commission),
            ("basis_path", self.basis_path),
            ("baseline", self.baseline),
        )
        self.missing = missing + [name for name, value in named if value is None]

    def on_start(self) -> None:
        self.subscribe_data(ranking_data_type(self.consumer.feed))
        now, segment = self.clock.timestamp_ns(), self.consumer.reader.segment
        for iid, book in self.books.items():
            self.subscribe_trades(iid)
            self.subscribe_quotes(iid)
            instrument = self.cache.instrument(iid)
            if self.missing or not isinstance(instrument, Equity):
                continue
            book.instrument = instrument
            book.entry = EntryState(iid, self._p, segment.name, start_ns=segment.start_ns)
            self.subscribe_bars(book.entry.bar_type)
        if self.missing:
            self._record(kind="entry_refused", ts=now, missing=self.missing)
            return
        book = next((b for b in self.books.values() if b.instrument is not None), None)
        account = None if book is None else self.portfolio.account(book.instrument_id.venue)
        if book is not None and account is not None and self.basis_path is not None:
            key = f"{segment.session_date.isoformat()}:{segment.name}:{segment.start_ns}"
            store = SegmentBasis(self.basis_path, str(account.id), self._p)
            free = self._balance(book, "free")
            self.basis = store.freeze(key, free, first_read="node_start")  # N5's frozen basis

    @property
    def _p(self) -> EntryParameters:
        assert self.params is not None  # only reached when no entry row is missing
        return self.params

    def on_data(self, data: CustomData) -> None:
        now = self.clock.timestamp_ns()
        accepted = self.consumer.handle(data, now=now)
        self._record(kind="generation", ts=now, accepted=accepted, reason=self.consumer.reason)

    def on_bar(self, bar: Bar) -> None:
        book = self.books.get(bar.bar_type.instrument_id)
        if book is not None and book.entry is not None:
            book.entry.on_bar(bar, now=self.clock.timestamp_ns())

    def on_quote(self, quote: QuoteTick) -> None:
        book, now = self.books.get(quote.instrument_id), self.clock.timestamp_ns()
        if book is None or not 0 <= quote.ts_event <= quote.ts_init <= now:
            return
        if book.quote is not None and quote.ts_event < book.quote.ts_event:
            return
        book.quote = quote
        if book.entry_id is not None:
            self._reprice(book, now)

    def on_trade(self, trade: TradeTick) -> None:
        book = self.books.get(trade.instrument_id)
        if book is None:
            return
        now = self.clock.timestamp_ns()
        allowed = self.candidate(book, now)
        if book.entry is None or self.baseline is None or self.exit is None:
            return
        book.entry.on_trade(trade, now=now)
        book.trades.append((trade.ts_event, trade.price.as_decimal()))  # R_w (exits/engine.py)
        start = trade.ts_event - int(self.exit.prearm_range_window_s * NS)
        while book.trades[0][0] < start:
            book.trades.popleft()
        quote = book.quote
        quote = quote if quote is not None and quote.ts_event <= trade.ts_event else None
        try:  # C's order: the entry state first, then the surge detector (c_session.py:200-222)
            book.surge, flag = advance_surge(
                book.surge,
                trade,
                self.baseline,
                segment=self.consumer.reader.segment,
                feed=self.baseline.feed,
                params=self._p,
                quote=quote,
            )
        except ValueError as error:
            self._record(
                kind="refuse", ts=now, instrument=str(book.instrument_id), reason=str(error)
            )
            return
        if flag is not None:
            book.entry.arm(flag)
        if book.entry_id is not None:
            self._reprice(book, now)
        elif allowed:
            self._enter(book, now)

    def candidate(self, book: _Book, now: int) -> bool:
        """The rank gate over one current ``entry_rank``; DISABLED means no house entry."""
        enabled = self.rank_gate.value
        rank = None
        if enabled is True:
            rank = self.consumer.entry_rank(str(book.instrument_id.symbol), now=now)
        decision = decide_rank_gate(
            enabled=cast(bool, enabled), rank=rank, consumer_reason=self.consumer.reason
        )
        book.gate, book.gate_ns = decision, now
        allowed = decision.status is RankGateStatus.PASS
        self._record(
            kind="rank",
            ts=now,
            instrument=str(book.instrument_id),
            status=decision.status.name,
            reason=decision.reason,
            rank=rank,
            candidate=allowed,
        )
        return allowed

    def _enter(self, book: _Book, now: int) -> None:
        """N1/N4 in the completing trade's handler: one LIMIT BUY at the ask, never market."""
        entry, quote, p = book.entry, self._fresh_quote(book, now), self._p
        assert entry is not None and book.instrument is not None
        surge = entry.surge
        if surge is None or quote is None or surge.flag_ts == book.refused_flag:
            return
        if not entry.first_leg_ready(quote_ask(quote), now):
            return
        expiry = min(now + p.ns("entry_ttl_s"), surge.flag_ts + p.ns("first_leg_window_s"))
        if expiry <= now:  # replay.py: a submit here would cancel inside its own borrow
            return self._refuse(book, now, "first_leg_window_s")
        price = limit_price(quote_ask(quote), book.instrument.price_increment.as_decimal())
        sizing = self._size(book, price, quote, now)
        if sizing.refusal is not None:
            book.refused_flag = surge.flag_ts  # c_session.py: refused until a new flag
            return self._refuse(book, now, sizing.refusal)
        order = self.order_factory.limit(
            book.instrument_id,
            OrderSide.BUY,
            sizing.quantity,
            Price.from_decimal_dp(price, book.instrument.price_precision),
            time_in_force=TimeInForce.DAY,
            tags=[f"params_hash={p.params_hash}", "setup=FIRST_LEG"],
        )
        book.entry_id, book.first_limit, book.expiry_ns = order.client_order_id, price, expiry
        self._record(kind="submit", ts=now, limit=str(price), **sizing.journal())
        iid = book.instrument_id
        self.clock.set_time_alert_ns(
            f"b-entry-ttl-{order.client_order_id}", expiry, callback=lambda _e: self._expire(iid)
        )
        outside = session_at(now) is not Session.RTH
        self.submit_order(order, params={"extended_hours": outside})

    def _reprice(self, book: _Book, now: int) -> None:
        """Reprice up to the ask, never past ``entry_chase_bps`` above the first limit."""
        order = None if book.entry_id is None else self.cache.order(book.entry_id)
        quote = self._fresh_quote(book, now)
        if order is None or not order.is_open or order.is_inflight or order.is_pending_cancel:
            return
        if quote is None or book.expiry_ns is None or now >= book.expiry_ns:
            return
        assert book.entry is not None and book.instrument is not None
        price = limit_price(quote_ask(quote), book.instrument.price_increment.as_decimal())
        if book.first_limit is None or price <= order.price.as_decimal():
            return
        if not book.entry.first_leg_ready(quote_ask(quote), now):
            return
        if not within_chase(price, book.first_limit, self._p):
            return self._refuse(book, now, "entry_chase_bps")
        sizing = self._size(book, price, quote, now, working=order)
        if sizing.refusal is not None or sizing.quantity < order.quantity:
            return self._refuse(book, now, sizing.refusal or "quantity")
        if not self.candidate(book, now):
            return
        self._record(kind="modify", ts=now, limit=str(price))
        native = Price.from_decimal_dp(price, book.instrument.price_precision)
        self.modify_order(order.client_order_id, price=native)

    def _expire(self, iid: InstrumentId) -> None:
        """TTL: cancel the remainder of this book's own entry, by its own id only."""
        book = self.books[iid]
        order = None if book.entry_id is None else self.cache.order(book.entry_id)
        if order is None or order.is_closed or order.is_pending_cancel:
            return
        self._record(kind="cancel", ts=self.clock.timestamp_ns(), order=str(order.client_order_id))
        self.cancel_order(order.client_order_id)

    def on_order_cancel_rejected(self, event: Any) -> None:
        self._record(kind="page", ts=event.ts_event, order=str(event.client_order_id))

    def _fresh_quote(self, book: _Book, now: int) -> QuoteTick | None:
        quote = book.quote
        if quote is None or now - quote.ts_event > self._p.ns("max_data_age_s"):
            return None
        if not 0 < quote.bid_price.as_decimal() <= quote_ask(quote):
            return None  # crossed or one-sided: UNKNOWN, never the older quote (replay.py)
        return quote

    def _size(
        self, book: _Book, price: Decimal, quote: QuoteTick, now: int, working: Any = None
    ) -> Sizing:
        """N5 through ``size_entry``; the initial trigger is ``entry - buffer`` (ADR-0004)."""
        assert book.entry is not None and book.instrument is not None and self.exit is not None
        prices = [traded for _, traded in book.trades]
        spread = quote_ask(quote) - quote.bid_price.as_decimal()
        tick = book.instrument.price_increment.as_decimal()
        width = buffer(
            tick, spread, price, max(prices) - min(prices) if prices else None, self.exit
        )
        if width is None:  # an unknown R_w makes the buffer unknown (policy.buffer)
            return Sizing(Quantity.from_int(0), None, None, None, None, "buffer_unknown", None)
        free = self._balance(book, "free")
        if free is not None and working is not None:  # replay.py: the working order's own funds
            free += working.leaves_qty.as_decimal() * working.price.as_decimal()
        return size_entry(
            instrument=book.instrument,
            params=self._p,
            setup="FIRST_LEG",
            entry=price,
            initial_trigger=price - width,
            equity=self._balance(book, "total"),
            basis=self.basis,
            buying_power=free,
            dollar_volume=book.entry.flow_dollars(now),
            confidence=None,
            prearm_stopouts=0,
            commission_rate=self.commission,
        )

    def _balance(self, book: _Book, name: str) -> Decimal | None:
        account = self.portfolio.account(book.instrument_id.venue)
        if account is None or book.instrument is None:
            return None
        balance = getattr(account, f"balance_{name}")(book.instrument.quote_currency)
        return None if balance is None else balance.as_decimal()

    def _refuse(self, book: _Book, now: int, reason: str) -> None:
        self._record(kind="refuse", ts=now, instrument=str(book.instrument_id), reason=reason)

    def _record(self, **row: Any) -> None:
        if self._journal is None:
            return
        try:
            self._journal(row)
        except Exception:  # containment: evidence never changes a decision
            self.journal_errors += 1


def quote_ask(quote: QuoteTick) -> Decimal:
    return quote.ask_price.as_decimal()
