"""Bounded SIP L1 quote capture for arm e (ADR-0003:13, ADR-0024:38).

Arm e ranks long-only on L1 order-flow imbalance (OFI). The state it needs is
narrow, so the subscription is explicit: the top-N ranking set, the owner's
holdings and the pre-positioned catalyst names, never the whole market. Every
name is a ticker the caller provides from its own authority; this module has no
local symbol list and no wildcard path.

Quotes are joined on the local receipt clock (``QuoteTick.ts_init``), not the
vendor timestamp, because arm e acts on what the process had received. OFI is
Cont, Kukanov & Stoikov's (2014) Level-I event sum, accumulated on a ten-second
receipt grid. The capture refuses to arm when the frontier is incomplete or the
one-session 8 GiB command cap is already reached; it never raises that cap.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from nautilus_trader.model import InstrumentId, QuoteTick

from sextant.data.alpaca_history import symbol_name

Role = Literal["top_n", "holding", "catalyst"]
ROLES: tuple[Role, ...] = ("top_n", "holding", "catalyst")

NS = 1_000_000_000
# Cont, Kukanov & Stoikov (2014) measure OFI on a ten-second interval grid.
OFI_WINDOW_NS = 10 * NS
ZERO = Decimal(0)

# The lead's one-session command cap (ranking-early-e2e, 2026-11-09); never raised.
ONE_SESSION_CAP_BYTES = 8 * 1024**3
INCOMPLETE_FRONTIER = "frontier_incomplete"
MEMORY_CAP = "memory_cap"


def _names(value: Iterable[str], role: Role) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{role} quote names must be an iterable of symbols, not a string")
    names: list[str] = []
    for name in value:
        if not isinstance(name, str):
            raise ValueError(f"{role} quote name must be a string: {name!r}")
        if name == "*":
            raise ValueError("wildcard quote subscriptions are refused; name every symbol")
        names.append(symbol_name(name))
    return tuple(names)


@dataclass(frozen=True, slots=True)
class FrontierMember:
    """One named symbol and every role that put it in the frontier."""

    symbol: str
    roles: tuple[Role, ...]


class Instrument(Protocol):
    """The rc8 surface the quote capture reads; rc8 exports no shared instrument base."""

    @property
    def id(self) -> InstrumentId: ...

    @property
    def price_precision(self) -> int: ...


def frontier_instruments(
    frontier: QuoteFrontier,
    instruments: Mapping[str, Instrument],
) -> dict[str, Instrument]:
    """Select exactly the frontier's instruments, keyed by instrument id for the feed."""
    selected: dict[str, Instrument] = {}
    missing: list[str] = []
    for symbol in frontier.symbols:
        instrument = instruments.get(symbol)
        if instrument is None:
            missing.append(symbol)
            continue
        id_symbol = instrument.id.symbol.value
        if id_symbol != symbol:
            raise ValueError(
                f"instrument id symbol {id_symbol!r} does not match frontier name {symbol!r}"
            )
        key = str(instrument.id)
        if key in selected:
            raise ValueError(f"duplicate instrument id in quote frontier: {key}")
        selected[key] = instrument
    if missing:
        raise ValueError(f"quote frontier names have no instrument: {', '.join(missing)}")
    return selected


@dataclass(frozen=True, slots=True)
class QuoteFrontier:
    """The named, count-bounded set of symbols whose quotes arm e may consume."""

    members: tuple[FrontierMember, ...]
    max_symbols: int
    missing_sources: tuple[Role, ...] = ()

    @classmethod
    def build(
        cls,
        *,
        top_n: Iterable[str] | None,
        holdings: Iterable[str] | None,
        catalysts: Iterable[str] | None,
        max_symbols: int,
    ) -> QuoteFrontier:
        """Union the three authority lists, refusing anything unbounded or unnamed."""
        if type(max_symbols) is not int or max_symbols <= 0:
            raise ValueError(f"quote frontier bound must be a positive int: {max_symbols!r}")

        sources: dict[Role, Iterable[str] | None] = {
            "top_n": top_n,
            "holding": holdings,
            "catalyst": catalysts,
        }
        names_by_role: dict[Role, tuple[str, ...]] = {}
        missing: list[Role] = []
        for role in ROLES:
            value = sources[role]
            if value is None:
                missing.append(role)
                names_by_role[role] = ()
            else:
                names_by_role[role] = _names(value, role)

        merged: dict[str, list[Role]] = {}
        for role in ROLES:
            for symbol in names_by_role[role]:
                roles = merged.setdefault(symbol, [])
                if role not in roles:
                    roles.append(role)

        members = tuple(
            FrontierMember(symbol=symbol, roles=tuple(roles)) for symbol, roles in merged.items()
        )
        if not members:
            raise ValueError("quote frontier is empty; arm e has nothing to watch")
        if len(members) > max_symbols:
            raise ValueError(
                f"quote frontier has {len(members)} symbols, above the bound {max_symbols}"
            )
        return cls(members=members, max_symbols=max_symbols, missing_sources=tuple(missing))

    def __post_init__(self) -> None:
        if type(self.max_symbols) is not int or self.max_symbols <= 0:
            raise ValueError(f"quote frontier bound must be a positive int: {self.max_symbols!r}")
        if not self.members:
            raise ValueError("quote frontier is empty; arm e has nothing to watch")
        if len(self.members) > self.max_symbols:
            raise ValueError(
                f"quote frontier has {len(self.members)} symbols, above the bound "
                f"{self.max_symbols}"
            )

        seen: set[str] = set()
        for member in self.members:
            if not isinstance(member, FrontierMember):
                raise ValueError(f"quote frontier member must be a FrontierMember: {member!r}")
            if member.symbol in seen:
                raise ValueError(f"duplicate quote frontier symbol: {member.symbol}")
            seen.add(member.symbol)
            if not member.roles:
                raise ValueError(f"quote frontier member {member.symbol} has no role")
            if tuple(role for role in ROLES if role in member.roles) != member.roles:
                raise ValueError(f"quote frontier roles are not canonical: {member.roles!r}")

        if tuple(role for role in ROLES if role in self.missing_sources) != self.missing_sources:
            raise ValueError(f"missing quote sources are not canonical: {self.missing_sources!r}")

    @property
    def symbols(self) -> tuple[str, ...]:
        """Bare tickers in first-seen order: top-N, holdings, then catalysts."""
        return tuple(member.symbol for member in self.members)

    @property
    def complete(self) -> bool:
        """False when an authority list was unavailable, so arm e must not run."""
        return not self.missing_sources

    def roles_for(self, symbol: str) -> tuple[Role, ...]:
        for member in self.members:
            if member.symbol == symbol:
                return member.roles
        raise KeyError(f"{symbol!r} is not in the quote frontier")


def _book(tick: QuoteTick, label: str) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    bid = tick.bid_price.as_decimal()
    ask = tick.ask_price.as_decimal()
    bid_size = tick.bid_size.as_decimal()
    ask_size = tick.ask_size.as_decimal()
    if bid <= ZERO or ask <= ZERO:
        raise ValueError(f"{label} quote prices must be positive: bid {bid} ask {ask}")
    if bid >= ask:
        raise ValueError(f"{label} quote book is crossed or locked: bid {bid} ask {ask}")
    if bid_size < ZERO or ask_size < ZERO:
        raise ValueError(f"{label} quote sizes must be non-negative")
    return bid, ask, bid_size, ask_size


@dataclass(frozen=True, slots=True)
class OfiWindow:
    """One interval of L1 OFI, joined and stamped on the local receipt clock."""

    symbol: str
    start_ns: int
    end_ns: int
    receipt_ts: int
    updates: int
    imbalance: Decimal

    def __post_init__(self) -> None:
        symbol_name(self.symbol)
        if type(self.start_ns) is not int or self.start_ns < 0:
            raise ValueError(f"OFI window start must be a non-negative int: {self.start_ns!r}")
        if type(self.end_ns) is not int or self.end_ns <= self.start_ns:
            raise ValueError(f"OFI window end must follow its start: {self.end_ns!r}")
        if type(self.receipt_ts) is not int or not (self.start_ns <= self.receipt_ts < self.end_ns):
            raise ValueError(f"OFI receipt is outside its window: {self.receipt_ts!r}")
        if type(self.updates) is not int or self.updates <= 0:
            raise ValueError(f"OFI window needs at least one update: {self.updates!r}")
        if not isinstance(self.imbalance, Decimal):
            raise ValueError(f"OFI imbalance must be Decimal: {self.imbalance!r}")


def quote_event_imbalance(previous: QuoteTick, current: QuoteTick) -> Decimal:
    """Return Cont, Kukanov & Stoikov's Level-I e_n for one quote update."""
    if previous.instrument_id != current.instrument_id:
        raise ValueError(
            "quote event imbalance needs one instrument: "
            f"{previous.instrument_id} and {current.instrument_id}"
        )
    pb0, pa0, qb0, qa0 = _book(previous, "previous")
    pb1, pa1, qb1, qa1 = _book(current, "current")
    bid_event = qb1 if pb1 > pb0 else (qb1 - qb0 if pb1 == pb0 else -qb0)
    ask_event = qa0 if pa1 > pa0 else (qa0 - qa1 if pa1 == pa0 else -qa1)
    return bid_event + ask_event


class ReceiptTimeOfi:
    """Accumulate one symbol's L1 OFI, joined on ``QuoteTick.ts_init``."""

    def __init__(self, symbol: str, *, window_ns: int = OFI_WINDOW_NS) -> None:
        self._symbol = symbol_name(symbol)
        if type(window_ns) is not int or window_ns <= 0:
            raise ValueError(f"OFI window must be a positive int: {window_ns!r}")
        self._window_ns = window_ns
        self._previous: QuoteTick | None = None
        self._last_receipt: int | None = None
        self._window_start: int | None = None
        self._window_receipt: int | None = None
        self._window_updates = 0
        self._window_imbalance = ZERO

    def update(self, tick: QuoteTick) -> tuple[OfiWindow, ...]:
        """Join one quote on receipt; return any window the receipt has closed."""
        symbol = tick.instrument_id.symbol.value
        if symbol != self._symbol:
            raise ValueError(f"quote for {symbol!r} does not belong to {self._symbol!r}")
        receipt = tick.ts_init
        if type(receipt) is not int or receipt < 0:
            raise ValueError(f"quote receipt must be a non-negative int: {receipt!r}")
        if self._last_receipt is not None and receipt < self._last_receipt:
            return ()

        _book(tick, "current")

        emitted: list[OfiWindow] = []
        start = receipt // self._window_ns * self._window_ns
        if self._window_start is None:
            self._window_start = start
        elif start > self._window_start:
            emitted.append(self._close())
            self._window_start = start

        if self._previous is not None:
            self._window_imbalance += quote_event_imbalance(self._previous, tick)
        self._previous = tick
        self._last_receipt = receipt
        self._window_receipt = receipt
        self._window_updates += 1
        return tuple(emitted)

    def flush(self) -> OfiWindow | None:
        """Close the open window at shutdown; later receipts start a fresh one."""
        if self._window_start is None:
            return None
        return self._close()

    def _close(self) -> OfiWindow:
        start = self._window_start
        receipt = self._window_receipt
        if start is None or receipt is None:
            raise RuntimeError("no open OFI window")
        window = OfiWindow(
            symbol=self._symbol,
            start_ns=start,
            end_ns=start + self._window_ns,
            receipt_ts=receipt,
            updates=self._window_updates,
            imbalance=self._window_imbalance,
        )
        self._window_start = None
        self._window_receipt = None
        self._window_updates = 0
        self._window_imbalance = ZERO
        return window


@dataclass(frozen=True, slots=True)
class ArmEAdmission:
    """Why arm e may or may not run; both refusals can apply at once."""

    admitted: bool
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.admitted) is not bool:
            raise ValueError(f"admission flag must be bool: {self.admitted!r}")
        if self.admitted != (not self.reasons):
            raise ValueError("admission flag and refusal reasons disagree")
        if (
            tuple(reason for reason in (INCOMPLETE_FRONTIER, MEMORY_CAP) if reason in self.reasons)
            != self.reasons
        ):
            raise ValueError(f"refusal reasons are not canonical: {self.reasons!r}")


def arm_e_admission(
    frontier: QuoteFrontier,
    *,
    resident_bytes: int,
    cap_bytes: int = ONE_SESSION_CAP_BYTES,
) -> ArmEAdmission:
    """Refuse arm e when the frontier is incomplete or the one-session cap is reached."""
    if type(resident_bytes) is not int or resident_bytes < 0:
        raise ValueError(f"resident bytes must be a non-negative int: {resident_bytes!r}")
    if type(cap_bytes) is not int or cap_bytes <= 0:
        raise ValueError(f"session cap must be a positive int: {cap_bytes!r}")
    if cap_bytes > ONE_SESSION_CAP_BYTES:
        raise ValueError("the one-session 8 GiB cap is never raised")

    reasons: list[str] = []
    if not frontier.complete:
        reasons.append(INCOMPLETE_FRONTIER)
    if resident_bytes >= cap_bytes:
        reasons.append(MEMORY_CAP)
    return ArmEAdmission(admitted=not reasons, reasons=tuple(reasons))


def resident_bytes() -> int:
    """Current resident set size, from proc(5) statm's resident-pages field."""
    with open("/proc/self/statm", encoding="ascii") as handle:
        fields = handle.read().split()
    if len(fields) < 2:
        raise RuntimeError("proc(5) statm did not report a resident page count")
    return int(fields[1]) * int(os.sysconf("SC_PAGE_SIZE"))


class BoundedQuoteCapture:
    """Feed the frontier's quotes into per-symbol receipt-time OFI books."""

    def __init__(
        self,
        frontier: QuoteFrontier,
        *,
        on_window: Callable[[OfiWindow], None],
        window_ns: int = OFI_WINDOW_NS,
    ) -> None:
        if not frontier.complete:
            raise ValueError("arm e refuses an incomplete quote frontier")
        self._frontier = frontier
        self._on_window = on_window
        self._books = {
            symbol: ReceiptTimeOfi(symbol, window_ns=window_ns) for symbol in frontier.symbols
        }

    def on_quote(self, tick: QuoteTick) -> None:
        symbol = tick.instrument_id.symbol.value
        book = self._books.get(symbol)
        if book is None:
            raise ValueError(f"quote for {symbol!r} is outside the bounded quote frontier")
        for window in book.update(tick):
            self._on_window(window)

    def flush(self) -> None:
        for book in self._books.values():
            window = book.flush()
            if window is not None:
                self._on_window(window)
