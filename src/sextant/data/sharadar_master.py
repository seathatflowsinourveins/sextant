# Carried from seathatflowsinourveins/northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:
# src/northstar_trading/data/sharadar.py, lines 62-101 (scope and category constants) and
# 470-956 (dated share-class intervals). Verbatim except line wrapping and the HTTP-only
# _MAX_BODY. ADR-0013 names this file to carry "with its stated limitations". Its HTTP bridge,
# CatalystEvent master and SharadarUniverse need northstar's catalysts store and are not
# carried; #107's sharadar_client.py is the transport here. Every universe built from these
# intervals stays survivor_only until ADR-0002 §6 acceptance.
"""Dated Sharadar share-class intervals from TICKERS and ACTIONS (row 4, #42).

Upstream checked: https://sharadar.com/docs/{tickers,actions} and the source note
northstar-trading@8256c16c:docs/research/2026-10-25-sharadar-source.md.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import pairwise
from typing import Any

from .alpaca_history import symbol_name
from .universe import DatedUniverse, UniverseMember

# Explicit listed venues only; unknown venues refuse rather than becoming listed.
_LISTED = frozenset(
    {"NYSE", "NASDAQ", "NYSEARCA", "NYSEMKT", "NYSEAMERICAN", "BATS", "CBOE", "IEX", "TXSE"}
)
# ACTIONS/descriptions: these date last trade. Acquisition consideration
# (FAQ: cash/share or share ratio) annotates an exit but never establishes one.
_EXITS = (
    "bankruptcyliquidation",
    "acquisitionby",
    "mergerto",
    "regulatorydelisting",
    "voluntarydelisting",
    "delisted",
)
_DELISTS = frozenset({"regulatorydelisting", "voluntarydelisting", "delisted"})
_EXIT_REASONS = (_EXITS[0], "acquisitioncash", "acquisitionstock", *_EXITS[1:])
_TABLE_ALIASES = {"stocks": "SEP", "SEP": "SEP", "funds": "SFP", "SFP": "SFP"}
_INSTRUMENT_TYPES = ("common", "preferred", "etf", "etn", "fund", "unsupported")
# TICKERS category dictionary: /docs/tickers, public metadata bundle, 2026-10-25.
# ETD is debt, IDX an index, and UNIT has no documented fund-unit subtype.
# Coordinator-approved conservative scope: none is silently labelled a fund.
_CATEGORY_TYPES = {
    **{
        f"{origin} Common Stock{share_class}": "common"
        for origin in ("Domestic", "ADR", "Canadian")
        for share_class in ("", " Primary Class", " Secondary Class")
    },
    **{f"{origin} Preferred Stock": "preferred" for origin in ("Domestic", "ADR", "Canadian")},
    "ETF": "etf",
    "ETN": "etn",
    "CEF": "fund",
    "CEF Preferred": "preferred",
    "ETMF": "fund",
    "MF": "fund",
}


def _scope(scope: str) -> None:
    if scope not in {"SEP", "SEP+SFP"}:
        raise ValueError("Sharadar scope must be SEP or SEP+SFP")


class _SecurityExclusion(ValueError):
    """Only expected security-evidence failures are downgraded to exclusions."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class SharadarMember(UniverseMember):
    exchange: str = ""
    dataset_ticker: str = ""
    relatedtickers: tuple[str, ...] = ()
    evidence_class: str = "explicit_action"
    start_evidence: str = "explicit_action"
    end_evidence: str = "explicit_action"
    actions_coverage_start: date | None = None

    @property
    def instrument_type(self) -> str:
        """Derived field: retain byte-identical r3 dataclass serialization/identity."""
        return _CATEGORY_TYPES.get(self.security_class, "unsupported")


@dataclass(frozen=True)
class _MembershipBounds:
    first: date
    last: date | None
    start_evidence: str = "explicit_action"
    end_evidence: str = "explicit_action"


def _venue(value: str) -> str:
    venue = value.upper().replace(" ", "")
    if venue not in _LISTED | {"OTC"}:
        raise _SecurityExclusion("unknown_exchange")
    return venue


def _pairs(rows: Sequence[dict[str, str]], prefix: str, field: str) -> list[tuple[date, str, str]]:
    grouped: dict[date, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row["action"] in {prefix + "from", prefix + "to"}:
            grouped[date.fromisoformat(row["date"])][row["action"]].append(row[field])
    result = []
    for day, pair in sorted(grouped.items()):
        before, after = pair[prefix + "from"], pair[prefix + "to"]
        if len(before) != 1 or len(after) != 1:
            raise _SecurityExclusion(f"ambiguous_{prefix}_pair")
        if not before[0] or not after[0] or "N/A" in {before[0], after[0]}:
            raise _SecurityExclusion(f"missing_{prefix}_identity")
        result.append((day, before[0], after[0]))
    return result


def _membership_bounds(
    record: dict[str, str],
    rows: Sequence[dict[str, str]],
    *,
    actions_start: date | None,
    legacy_action_only: bool,
) -> _MembershipBounds:
    """Explicit actions win; weaker fields never claim an IPO or listing date.

    Public TICKERS metadata (2026-10-25) says firstpricedate is NOT the IPO date.
    None exists: a PIT-universe recipe in the checked docs/FAQ/llms.txt.
    Coordinator-approved house deviation: pre-capture trading permits membership
    only FROM the capture boundary, never from the first price. See the note's
    REDESIGN-NEED and before-landing approval requirement. Repeated listings
    remain ambiguous; no documented unique episode-pairing contract exists.
    """
    listings = [date.fromisoformat(row["date"]) for row in rows if row["action"] == "listed"]
    start_evidence = "explicit_action"
    if len(listings) > 1:
        raise _SecurityExclusion("ambiguous_listing_actions")
    if listings:
        first = listings[0]
    else:
        if legacy_action_only or actions_start is None:
            raise _SecurityExclusion("missing_listing_action")
        if not record["firstpricedate"]:
            raise _SecurityExclusion("missing_pre_coverage_price")
        try:
            first_price = date.fromisoformat(record["firstpricedate"])
        except ValueError:
            raise _SecurityExclusion("invalid_first_price_date") from None
        if first_price >= actions_start:
            raise _SecurityExclusion("missing_listing_action")
        first, start_evidence = actions_start, "pre_coverage_listing"
    if record["isdelisted"] not in {"Y", "N"}:
        raise _SecurityExclusion("unknown_listing_status")
    exits = [row for row in rows if row["action"] in _EXITS]
    terminal_dates = {
        date.fromisoformat(row["date"]) for row in exits if row["action"] not in _DELISTS
    }
    if len(terminal_dates) > 1:
        raise _SecurityExclusion("conflicting_terminal_exit_actions")
    last = next(iter(terminal_dates), None)
    end_evidence = "explicit_action" if last is not None else "open_status"
    if record["isdelisted"] == "Y" and last is None:
        if exits:
            last = max(date.fromisoformat(row["date"]) for row in exits)
            end_evidence = "explicit_action"
        else:
            if legacy_action_only or not record["lastpricedate"]:
                raise _SecurityExclusion("missing_exit_action")
            try:
                last = date.fromisoformat(record["lastpricedate"])
            except ValueError:
                raise _SecurityExclusion("invalid_last_price_date") from None
            end_evidence = "tickers_field"
    if last is not None and last < first and start_evidence == "pre_coverage_listing":
        raise _SecurityExclusion("ended_before_actions_coverage")
    if (last is not None and last < first) or any(
        date.fromisoformat(row["date"]) < first
        or (last is not None and date.fromisoformat(row["date"]) > last)
        for row in exits
    ):
        raise _SecurityExclusion("conflicting_listing_exit_actions")
    return _MembershipBounds(first, last, start_evidence, end_evidence)


def _market_symbol(value: str) -> str:
    try:
        return symbol_name(value)
    except ValueError:
        raise _SecurityExclusion("invalid_market_symbol") from None


def _market_ticker(
    record: dict[str, str],
    masters: Mapping[str, dict[str, str]],
    lifetimes: Mapping[str, _MembershipBounds],
) -> str:
    ticker = _market_symbol(record["ticker"])
    suffix = re.fullmatch(r"(.+?)[1-9][0-9]*", ticker)
    related = record["relatedtickers"].split()
    if suffix and suffix[1] in related:
        owner = masters.get(suffix[1])
        last = lifetimes[ticker].last
        if (
            record["isdelisted"] != "Y"
            or owner is None
            or owner["ticker"] not in lifetimes
            or record["permaticker"] == owner["permaticker"]
            or last is None
            or last >= lifetimes[owner["ticker"]].first
        ):
            raise _SecurityExclusion("unproven_ticker_reuse")
        return _market_symbol(suffix[1])
    return ticker


def _record_intervals(
    record: dict[str, str],
    rows: Sequence[dict[str, str]],
    masters: Mapping[str, dict[str, str]],
    lifetimes: Mapping[str, _MembershipBounds],
    *,
    start: date,
    end: date,
    actions_start: date | None,
    legacy_action_only: bool,
) -> list[SharadarMember]:
    bounds = lifetimes[record["ticker"]]
    first, terminal = bounds.first, bounds.last
    last = min(terminal, end) if terminal is not None else end
    if not record["permaticker"] or not record["category"]:
        raise _SecurityExclusion("missing_share_class_identity")
    if first > end or last < start:
        return []  # Outside the evidenced lifetime, not merely absent recent prices.
    final_symbol = _market_ticker(record, masters, lifetimes)
    renames = _pairs(rows, "tickerchange", "contraticker")
    venues = [
        (day, _venue(before), _venue(after))
        for day, before, after in _pairs(rows, "exchange", "contraname")
    ]
    symbol = _market_symbol(renames[0][1]) if renames else final_symbol
    exchange = venues[0][1] if venues else _venue(record["exchange"])
    listed = exchange
    for day, before, after in renames:
        if (
            before != symbol
            or day < first
            or (legacy_action_only and terminal is not None and day > terminal)
        ):
            raise _SecurityExclusion("discontinuous_tickerchange_chain")
        symbol = _market_symbol(after)
    if symbol != final_symbol:
        raise _SecurityExclusion("tickerchange_target_mismatch")
    current = exchange
    for day, before, after in venues:
        if (
            before != current
            or day < first
            or (legacy_action_only and terminal is not None and day > terminal)
        ):
            raise _SecurityExclusion("discontinuous_exchange_chain")
        current = after
        if current != "OTC":
            listed = current
    # TICKERS.exchange retains the last LISTED exchange even after an OTC move.
    if _venue(record["exchange"]) not in {current, listed}:
        raise _SecurityExclusion("exchange_history_mismatch")
    exits = [row for row in rows if row["action"] in _EXITS]
    terminal_rows = [row for row in rows if date.fromisoformat(row["date"]) == terminal]
    reason = next(
        (kind for kind in _EXIT_REASONS if any(row["action"] == kind for row in terminal_rows)),
        None,
    )
    # An exchange exit can precede final OTC prices. Do not stretch the listed
    # interval across that gap; resume only at an explicit exchange-to action.
    removals = {
        date.fromisoformat(row["date"]): row["action"]
        for row in exits
        if row["action"] in _DELISTS and date.fromisoformat(row["date"]) < last
    }
    if not legacy_action_only:
        # Last-trade rename followed by a later explicit OTC move: the new
        # ticker is post-exit, not the symbol traded on that inclusive last day.
        # Original full chains were validated above, including post-terminal rows.
        exit_days = {date.fromisoformat(row["date"]) for row in exits}
        renames = [
            (
                day + timedelta(days=1)
                if day in exit_days
                and next(((before, after) for at, before, after in venues if at > day), None)
                in {(venue, "OTC") for venue in _LISTED}
                else day,
                before,
                after,
            )
            for day, before, after in renames
        ]
    changes = {day for day, _, _ in renames + venues if day <= last}
    evidence_class = (
        "tickers_field" if bounds.end_evidence == "tickers_field" else bounds.start_evidence
    )
    if terminal is not None and bounds.end_evidence == "tickers_field":
        reason = "tickers_lastpricedate"
    boundaries = sorted(
        {first, last + timedelta(days=1), *changes, *(day + timedelta(days=1) for day in removals)}
    )
    symbol = renames[0][1] if renames else final_symbol
    rename_at = {day: after for day, _, after in renames}
    venue_at = {day: after for day, _, after in venues}
    result = []
    removed = False
    for left, right in pairwise(boundaries):
        symbol, exchange = rename_at.get(left, symbol), venue_at.get(left, exchange)
        if left - timedelta(days=1) in removals:
            removed = True
        if left in venue_at:
            removed = False
        begin, finish = max(left, start), min(right - timedelta(days=1), end)
        if begin <= finish and not removed:
            result.append(
                SharadarMember(
                    symbol=_market_symbol(symbol),
                    first_date=begin,
                    last_date=finish,
                    exit_reason=removals.get(finish, reason if finish == terminal else None),
                    source="sharadar",
                    security_id=f"sharadar:{record['permaticker']}",
                    security_class=record["category"],
                    exchange=exchange,
                    dataset_ticker=record["ticker"],
                    relatedtickers=tuple(record["relatedtickers"].split()),
                    evidence_class=evidence_class,
                    start_evidence=bounds.start_evidence,
                    end_evidence=bounds.end_evidence,
                    actions_coverage_start=actions_start,
                )
            )
    return result


@dataclass(frozen=True)
class IntervalCoverage:
    intervals: tuple[SharadarMember, ...]
    exclusions: dict[str, str]  # Dataset ticker -> one named primary evidence failure.
    input_security_count: int
    outside_window_security_count: int
    actions_start: date | None = None
    legacy_action_only: bool = False
    scope: str = "SEP"
    # Dataset ticker -> (canonical price table, instrument type, original category).
    security_metadata: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    _legacy_scope_counts: bool = False

    @property
    def summary(self) -> dict[str, Any]:
        """Aggregate-only provenance; the raw source remains the identity evidence."""
        summary: dict[str, Any] = {
            "input_security_count": self.input_security_count,
            "included_security_count": len({row.dataset_ticker for row in self.intervals}),
            "outside_window_security_count": self.outside_window_security_count,
            "excluded_security_count": len(self.exclusions),
            "dated_interval_count": len(self.intervals),
            "exclusion_counts": dict(sorted(Counter(self.exclusions.values()).items())),
        }
        if not self.legacy_action_only:
            summary.update(
                membership_policy="layered-v1",
                security_scope=(
                    "stocks/SEP only (common and preferred); funds/SFP excluded"
                    if self.scope == "SEP"
                    else "stocks/SEP and funds/SFP; supported common, preferred, etf, etn, "
                    "fund categories"
                ),
                actions_coverage_start=self.actions_start.isoformat()
                if self.actions_start
                else None,
                evidence_class_counts=self._evidence_counts("evidence_class"),
                boundary_evidence_counts={
                    "start": self._evidence_counts("start_evidence"),
                    "end": self._evidence_counts("end_evidence"),
                },
            )
        if not self._legacy_scope_counts:
            summary.update(
                scope=self.scope,
                table_counts=self._population_counts(0, ("SEP", "SFP")),
                instrument_type_counts=self._population_counts(1, _INSTRUMENT_TYPES),
                unsupported_category_counts=dict(
                    sorted(
                        Counter(
                            meta[2]
                            for meta in self.security_metadata.values()
                            if meta[1] == "unsupported"
                        ).items()
                    )
                ),
            )
        return summary

    def _population_counts(self, index: int, groups: Sequence[str]) -> dict[str, dict[str, int]]:
        included = {row.dataset_ticker for row in self.intervals}
        interval_counts = Counter(
            self.security_metadata[row.dataset_ticker][index] for row in self.intervals
        )
        counts = {}
        for group in groups:
            tickers = {
                ticker for ticker, meta in self.security_metadata.items() if meta[index] == group
            }
            inside, excluded = len(tickers & included), len(tickers & self.exclusions.keys())
            counts[group] = {
                "input_security_count": len(tickers),
                "included_security_count": inside,
                "outside_window_security_count": len(tickers) - inside - excluded,
                "excluded_security_count": excluded,
                "dated_interval_count": interval_counts[group],
            }
        return counts

    def _evidence_counts(self, attribute: str) -> dict[str, int]:
        classes = {
            "evidence_class": ("explicit_action", "pre_coverage_listing", "tickers_field"),
            "start_evidence": ("explicit_action", "pre_coverage_listing"),
            "end_evidence": ("explicit_action", "open_status", "tickers_field"),
        }[attribute]
        counts = Counter({kind: 0 for kind in classes})
        counts.update(getattr(row, attribute) for row in self.intervals)
        return dict(sorted(counts.items()))


def _overlapping_tickers(intervals: Sequence[SharadarMember]) -> set[str]:
    conflicts: set[str] = set()
    for attribute in ("symbol", "security_id"):
        groups: dict[str, list[SharadarMember]] = defaultdict(list)
        for row in intervals:
            groups[getattr(row, attribute)].append(row)
        for group in groups.values():
            component: set[str] = set()
            through = date.min
            for row in sorted(group, key=lambda item: item.first_date):
                if component and row.first_date <= through:
                    conflicts.update(component)
                    conflicts.add(row.dataset_ticker)
                else:
                    component = set()
                    through = date.min
                component.add(row.dataset_ticker)
                through = max(through, row.last_date or date.max)
    return conflicts


def interval_coverage(
    tickers: Sequence[dict[str, str]],
    actions: Sequence[dict[str, str]],
    *,
    start: date,
    end: date,
    actions_start: date | None = None,
    scope: str = "SEP",
    _legacy_action_only: bool = False,
    _legacy_scope_counts: bool = False,
) -> IntervalCoverage:
    """Join by LAST dataset ticker, excluding insufficient evidence per security.

    From/to pairs describe one permaticker, not merger counterparties. Weaker
    starts need an explicit complete-capture boundary, never a slice's first row.
    Named exclusions count once per security;
    malformed table shape/duplicate identities still refuse the input as a whole.
    """
    _scope(scope)
    if start > end:
        raise ValueError("Invalid Sharadar coverage")
    masters: dict[str, dict[str, str]] = {}
    identities: set[str] = set()
    metadata = {}
    for record in tickers:
        table = _TABLE_ALIASES.get(record["table"])
        if table is None or (table == "SFP" and scope == "SEP"):
            continue
        if record["ticker"] in masters or record["permaticker"] in identities:
            raise ValueError("Duplicate Sharadar share class or dataset ticker")
        masters[record["ticker"]] = record
        identities.add(record["permaticker"])
        metadata[record["ticker"]] = (
            table,
            _CATEGORY_TYPES.get(record["category"], "unsupported"),
            record["category"],
        )
    if not masters:
        raise ValueError("Sharadar master contains no securities in the requested scope")
    by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in actions:
        by_ticker[row["ticker"]].append(row)
    lifetimes = {}
    exclusions = {}
    for ticker, record in masters.items():
        try:
            if metadata[ticker][:2] == ("SFP", "unsupported"):
                raise _SecurityExclusion("unsupported_instrument_type")
            for row in by_ticker[ticker]:
                try:
                    date.fromisoformat(row["date"])
                except ValueError:
                    raise _SecurityExclusion("invalid_action_date") from None
            lifetimes[ticker] = _membership_bounds(
                record,
                by_ticker[ticker],
                actions_start=actions_start,
                legacy_action_only=_legacy_action_only,
            )
        except _SecurityExclusion as exc:
            exclusions[ticker] = exc.reason
    intervals = []
    outside = 0
    for ticker in lifetimes:
        try:
            rows = _record_intervals(
                masters[ticker],
                by_ticker[ticker],
                masters,
                lifetimes,
                start=start,
                end=end,
                actions_start=actions_start,
                legacy_action_only=_legacy_action_only,
            )
        except _SecurityExclusion as exc:
            exclusions[ticker] = exc.reason
            continue
        if not rows:
            outside += 1
        intervals.extend(rows)
    for ticker in _overlapping_tickers(intervals):
        exclusions[ticker] = "overlapping_dated_identity"
    included = tuple(row for row in intervals if row.dataset_ticker not in exclusions)
    # Keep the house validator, even for OTC intervals; never pick a collision winner.
    DatedUniverse(included, source="sharadar", start=start, end=end)
    return IntervalCoverage(
        included,
        exclusions,
        len(masters),
        outside,
        actions_start,
        _legacy_action_only,
        scope,
        metadata,
        _legacy_scope_counts,
    )


def dated_intervals(
    tickers: Sequence[dict[str, str]],
    actions: Sequence[dict[str, str]],
    *,
    start: date,
    end: date,
    actions_start: date | None = None,
    scope: str = "SEP",
) -> tuple[SharadarMember, ...]:
    """Compatibility view; SFP requires explicit scope=SEP+SFP."""
    return interval_coverage(
        tickers, actions, start=start, end=end, actions_start=actions_start, scope=scope
    ).intervals
