"""C-lane first-leg decision core: one surge flag, one LIMIT BUY, one RTH trail.

This is the pure session slice between a quote/trade stream and the order wire. It
owns no socket, timer, broker client or account state: the caller injects the
event clock, the baseline table, the native order sink and the subscribed
instruments. The stream and ``AlpacaBridge`` are wired later.

Behaviour follows ADR-0024's first rising second and ADR-0025's narrow protection
cap. The first leg is sized per trade by ``size_entry`` from the registered row;
a refusal sends no order. Outside RTH a native trailing stop would be refused,
so the session records the pending protection instead of sending one.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from nautilus_trader.model import Equity, InstrumentId, QuoteTick, TradeTick

from sextant.entry.orders import limit_price
from sextant.entry.parameters import SIZING, EntryParameters
from sextant.entry.signals import EntryState, Surge
from sextant.entry.sizing import size_entry
from sextant.entry.surge import SurgeState, advance_surge
from sextant.execution.alpaca import OrderCommand
from sextant.execution.custody import OrderFact
from sextant.ranking.baseline import BaselineTable
from sextant.ranking.engine import Segment

ZERO = Decimal(0)


@dataclass(frozen=True)
class CConfig:
    """The reviewed C profile; every value is supplied, never inferred here."""

    symbols: tuple[str, ...]
    chase_cap_fraction: Decimal
    trail_fraction: Decimal
    basis: Decimal
    slot_count: int
    segment: Segment
    params: EntryParameters
    held_symbols: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if type(self.symbols) is not tuple or not self.symbols:
            raise ValueError("C needs at least one full instrument id")
        if any(not isinstance(symbol, str) or not symbol for symbol in self.symbols):
            raise ValueError("C symbols must be non-empty full instrument ids")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("C symbols must be unique")
        for symbol in self.symbols:
            InstrumentId.from_str(symbol)
        if not isinstance(self.segment, Segment):
            raise ValueError("C needs a supplied session segment")
        if not isinstance(self.params, EntryParameters):
            raise ValueError("C needs parsed entry parameters")
        for name in sorted(SIZING):
            if not self.params.has(name):
                raise ValueError(f"C needs the {name} entry registry row")
        _money(self.basis, "basis", zero=True)
        _fraction(self.chase_cap_fraction, "chase_cap_fraction", zero=True)
        _fraction(self.trail_fraction, "trail_fraction", zero=False)
        if type(self.slot_count) is not int or isinstance(self.slot_count, bool):
            raise ValueError("slot_count must be an integer")
        if self.slot_count <= 0:
            raise ValueError("slot_count must be positive")
        if type(self.held_symbols) is not frozenset:
            raise ValueError("C held symbols must be a frozenset")
        for symbol in self.held_symbols:
            if not isinstance(symbol, str) or not symbol:
                raise ValueError("C held symbols must be non-empty full instrument ids")
            InstrumentId.from_str(symbol)


def _fraction(value: Decimal, name: str, *, zero: bool) -> None:
    if not isinstance(value, Decimal):
        raise ValueError(f"{name} must be Decimal, never float")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if value < 0 or (value == 0 and not zero) or value > 1:
        raise ValueError(
            f"{name} must be a fraction in (0, 1]" if not zero else f"{name} is invalid"
        )


def _money(value: Decimal, name: str, *, zero: bool) -> None:
    if not isinstance(value, Decimal):
        raise ValueError(f"{name} must be Decimal, never float")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if value < 0 or (value == 0 and not zero):
        raise ValueError(
            f"{name} must be a nonnegative Decimal" if zero else f"{name} must be positive"
        )


@dataclass(frozen=True, slots=True)
class EntryIntent:
    """One ready first-leg entry awaiting the runner's fresh balance read."""

    client_order_id: str
    instrument: str
    limit_price: Decimal
    expiry_ns: int


@dataclass(slots=True)
class _SymbolState:
    instrument: Equity
    surge: SurgeState
    entry: EntryState
    quote: QuoteTick | None = None
    cid: str | None = None
    first_limit: Decimal | None = None
    expiry_ns: int | None = None
    pending: bool = False
    filled_qty: Decimal = field(default_factory=lambda: ZERO)
    protection: str | None = None
    intent: EntryIntent | None = None
    refused_surge: int | None = None
    refusals: dict[tuple[int, str], dict[str, Any]] = field(default_factory=dict)


class CSession:
    """Decision state for one C-lane segment and its subscribed instruments.

    ``instruments`` is keyed by the full instrument id in ``CConfig.symbols``. The
    native instrument supplies the price ladder; the size comes from the registered
    risk fraction through ``size_entry``, and a refusal sends no order.
    """

    def __init__(
        self,
        config: CConfig,
        baseline: BaselineTable,
        now_ns: Callable[[], int],
        submit: Callable[[OrderCommand], None],
        *,
        instruments: Mapping[str, Equity],
    ) -> None:
        if not isinstance(config, CConfig):
            raise ValueError("CConfig required")
        if not isinstance(baseline, BaselineTable):
            raise ValueError("BaselineTable required")
        if not callable(now_ns) or not callable(submit):
            raise ValueError("now_ns and submit must be callable")
        missing = [symbol for symbol in config.symbols if symbol not in instruments]
        if missing:
            raise ValueError(f"missing instruments for C symbols: {missing}")
        unknown = [symbol for symbol in instruments if symbol not in config.symbols]
        if unknown:
            raise ValueError(f"instruments outside C symbols: {unknown}")

        self.config = config
        self.baseline = baseline
        self._now_ns = now_ns
        self._submit = submit
        self._instruments = dict(instruments)
        # The runner freezes design.md:25's basis from each segment's own balance.
        self._basis = config.basis
        self._states: dict[str, _SymbolState] = {}
        for symbol in config.symbols:
            instrument = instruments[symbol]
            if str(instrument.id) != symbol:
                raise ValueError("instrument key and native id differ")
            iid = instrument.id
            self._states[symbol] = _SymbolState(
                instrument=instrument,
                surge=SurgeState(
                    symbol=str(iid.symbol), segment_key=(config.segment.name, config.segment)
                ),
                entry=EntryState(
                    iid,
                    config.params,
                    config.segment.name,
                    start_ns=config.segment.start_ns,
                ),
            )

    # -- events ---------------------------------------------------------

    def on_quote(self, quote: QuoteTick) -> None:
        """Store a valid, freshest two-sided quote and try each armed entry."""
        state = self._states.get(str(quote.instrument_id))
        if state is None:
            return
        now = self._now()
        if not _valid_quote(quote, now):
            return
        if state.quote is not None and quote.ts_event < state.quote.ts_event:
            return
        state.quote = quote
        for candidate in self._states.values():
            if candidate.quote is not None and _fresh_quote(candidate.quote, now, self.config):
                self._maybe_enter(candidate, candidate.quote, now)
            elif candidate.entry.surge is not None and candidate.cid is None:
                self._refusal(
                    candidate, "no_quote" if candidate.quote is None else "stale_quote", now
                )

    def on_trade(self, trade: TradeTick) -> None:
        """Advance the entry state, then the surge detector; arm a new flag."""
        state = self._states.get(str(trade.instrument_id))
        if state is None:
            return
        now = self._now()
        state.entry.on_trade(trade, now=now)
        quote = state.quote
        if quote is not None and quote.ts_event > trade.ts_event:
            quote = None
        # rc8's TradeTick carries no SIP condition codes; the stream slice that
        # supplies closing-print conditions is not part of this pure machine.
        state.surge, flag = advance_surge(
            state.surge,
            trade,
            self.baseline,
            segment=self.config.segment,
            feed=self.baseline.feed,
            params=self.config.params,
            quote=quote,
            conditions=(),
        )
        if flag is not None:
            state.entry.arm(flag)

    def on_fill(self, fill: OrderFact) -> None:
        """Emit the one protective trail for the tracked entry inside RTH.

        ``OrderFact`` is the bridge's cid-bearing fact; ``FillFact`` alone cannot
        identify which tracked entry filled.
        """
        state = next((s for s in self._states.values() if s.cid == fill.client_order_id), None)
        if state is None or state.cid is None:
            return
        if fill.side != "BUY" or fill.instrument != str(state.instrument.id):
            return
        if fill.filled <= ZERO or fill.filled < state.filled_qty:
            return

        state.filled_qty = fill.filled
        state.pending = False
        if state.protection is not None:
            return
        if self.config.segment.name != "RTH":
            state.protection = "outside RTH"
            return

        protection_cid = f"{state.cid}-trail"
        command = OrderCommand(
            client_order_id=protection_cid,
            instrument=str(state.instrument.id),
            side="SELL",
            quantity=state.filled_qty,
            order_type="TRAILING_STOP",
            time_in_force="GTC",
            trail_price=self.config.trail_fraction * 100,
        )
        self._submit(command)
        state.protection = protection_cid

    # -- decisions ------------------------------------------------------

    def _maybe_enter(self, state: _SymbolState, quote: QuoteTick, now: int) -> None:
        surge = state.entry.surge
        if surge is None or state.pending or state.cid is not None:
            return
        if state.refused_surge == surge.flag_ts:
            return
        if str(state.instrument.id) in self.config.held_symbols:
            self._refusal(state, "held_symbol", now)
            return
        ask = quote.ask_price.as_decimal()
        if not state.entry.first_leg_ready(ask, now):
            self._refusal(state, "first_leg_not_ready", now)
            return
        if ask > surge.quiet_price * (1 + self.config.chase_cap_fraction):
            self._refusal(state, "chase_cap", now)
            return
        if self._slots_used() >= self.config.slot_count:
            self._refusal(state, "slots_full", now)
            return

        params = self.config.params
        expiry_ns = min(
            now + params.ns("entry_ttl_s"),
            surge.flag_ts + params.ns("first_leg_window_s"),
        )
        if expiry_ns <= now:
            self._refusal(state, "intent_expired", now)
            return

        instrument = state.instrument
        native = limit_price(ask, instrument.price_increment.as_decimal())
        state.intent = EntryIntent(
            client_order_id=_entry_cid(state, surge),
            instrument=str(instrument.id),
            limit_price=native,
            expiry_ns=expiry_ns,
        )

    def take_ready(self, now: int | None = None) -> tuple[EntryIntent, ...]:
        """Consume ready intents; the runner reads the account, then calls ``enter``."""
        moment = self._now() if now is None else now
        available = self.config.slot_count - self._slots_used()
        ready: list[EntryIntent] = []
        for state in self._states.values():
            intent = state.intent
            if intent is None:
                continue
            state.intent = None
            if available <= 0 or state.pending or state.cid is not None:
                self._refusal(
                    state, "slots_full" if available <= 0 else "already_submitted", moment
                )
                continue
            if intent.expiry_ns <= moment:
                self._refusal(state, "intent_expired", moment)
                continue
            quote = state.quote
            if quote is None or not _fresh_quote(quote, moment, self.config):
                self._refusal(state, "no_quote" if quote is None else "stale_quote", moment)
                continue
            ready.append(intent)
            available -= 1
        return tuple(ready)

    def enter(
        self,
        intent: EntryIntent,
        *,
        equity: Decimal,
        buying_power: Decimal,
        now: int | None = None,
    ) -> None:
        """Size one consumed intent from the runner's fresh balance and submit it."""
        if not isinstance(intent, EntryIntent):
            raise ValueError("EntryIntent required")
        moment = self._now() if now is None else now
        state = self._states.get(intent.instrument)
        if state is None or state.entry.surge is None:
            return
        if state.pending or state.cid is not None or intent.expiry_ns <= moment:
            self._refusal(
                state, "already_submitted" if state.cid is not None else "intent_expired", moment
            )
            return
        quote = state.quote
        if quote is None or not _fresh_quote(quote, moment, self.config):
            self._refusal(state, "no_quote" if quote is None else "stale_quote", moment)
            return
        _money(equity, "equity", zero=False)
        _money(buying_power, "buying_power", zero=True)
        # ADR-0004:21: the trigger is entry minus the buffer; the trail uses 0.025.
        sizing = size_entry(
            instrument=state.instrument,
            params=self.config.params,
            setup="FIRST_LEG",
            entry=intent.limit_price,
            initial_trigger=intent.limit_price * (1 - self.config.trail_fraction),
            equity=equity,
            basis=self._basis,
            buying_power=buying_power,
            dollar_volume=state.entry.flow_dollars(moment),
            confidence=None,
            prearm_stopouts=0,
            commission_rate=ZERO,
        )
        quantity = sizing.quantity.as_decimal()
        if sizing.refusal is not None or quantity <= ZERO:
            self._refusal(state, f"sizing: {sizing.refusal or 'nonpositive quantity'}", moment)
            state.refused_surge = state.entry.surge.flag_ts
            return
        command = OrderCommand(
            client_order_id=intent.client_order_id,
            instrument=intent.instrument,
            side="BUY",
            quantity=quantity,
            order_type="LIMIT",
            time_in_force="DAY",
            limit_price=intent.limit_price,
        )
        self._submit(command)
        state.cid = command.client_order_id
        state.first_limit = intent.limit_price
        state.expiry_ns = intent.expiry_ns
        state.pending = True

    def refuse(self, intent: EntryIntent, reason: str = "balance_read_failed") -> None:
        """A failed or stale balance read refuses the entry until a new flag."""
        state = self._states.get(intent.instrument)
        surge = None if state is None else state.entry.surge
        if state is not None and surge is not None:
            self._refusal(state, reason, self._now())
            state.refused_surge = surge.flag_ts

    def _refusal(self, state: _SymbolState, reason: str, now: int) -> None:
        surge = state.entry.surge
        if surge is None:
            return
        row = state.refusals.setdefault(
            (surge.flag_ts, reason),
            {"flag_ts": surge.flag_ts, "reason": reason, "first_ns": now, "count": 0},
        )
        row["count"] += 1
        row["last_ns"] = now
        if reason == "first_leg_not_ready":
            run = state.entry.run
            row.update(
                first_leg_trades=len(run),
                first_leg_span_ns=run[-1].ts_event - run[0].ts_event if run else 0,
                trade_fresh=state.entry.fresh(now),
                last_trade_price=str(run[-1].price.as_decimal()) if run else None,
                entry_failure=state.entry.failure,
                ask=str(state.quote.ask_price.as_decimal()) if state.quote else None,
                quiet_price=str(surge.quiet_price),
                flag_known_ns=surge.known_at,
                flag_expires_ns=surge.expires_ts,
            )

    def _slots_used(self) -> int:
        return sum(1 for state in self._states.values() if state.cid is not None)

    def _now(self) -> int:
        now = self._now_ns()
        if type(now) is not int or now < 0:
            raise ValueError("now_ns must return a non-negative integer")
        return now

    # -- ledger ---------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """A plain runner ledger: per-symbol first-leg state plus the params hash."""
        ledger: dict[str, object] = {"params_hash": self.config.params.params_hash}
        for symbol, state in self._states.items():
            surge = state.entry.surge
            status = "submitted" if state.cid is not None else "unarmed"
            if surge is not None and state.cid is None:
                status = "waiting"
                if state.quote is None:
                    status = "no_quote"
                elif not _fresh_quote(state.quote, self._now(), self.config):
                    status = "stale_quote"
                elif state.refused_surge == surge.flag_ts:
                    status = "refused"
                elif not state.refusals and state.intent is None:
                    status = "awaiting_quote"
            ledger[symbol] = {
                "armed": surge is not None,
                "flag_ts": surge.flag_ts if surge is not None else None,
                "pending_cid": state.cid if state.pending else None,
                "filled_qty": state.filled_qty,
                "protection": state.protection,
                "entry_status": status,
                "refusals": [dict(row) for row in state.refusals.values()],
            }
        return ledger


def _entry_cid(state: _SymbolState, surge: Surge) -> str:
    raw = "".join(ch for ch in str(state.instrument.id.symbol) if ch.isalnum())[:24]
    return f"c-{raw}-{surge.flag_ts}"


def _valid_quote(quote: QuoteTick, now: int) -> bool:
    if not 0 <= quote.ts_event <= quote.ts_init <= now:
        return False
    bid = quote.bid_price.as_decimal()
    ask = quote.ask_price.as_decimal()
    return bool(ask.is_finite() and bid.is_finite() and bid > ZERO and ask >= bid)


def _fresh_quote(quote: QuoteTick, now: int, config: CConfig) -> bool:
    return bool(
        quote.ts_event <= now and now - quote.ts_event <= config.params.ns("max_data_age_s")
    )


__all__ = ["CConfig", "CSession", "EntryIntent"]
