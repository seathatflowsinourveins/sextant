"""The six-mover cohort replay for PR-3: first-leg entries, B's trail, ADR-0024 slots.

The first-leg policy is the one reviewed registry: five non-decreasing prints above the quiet
price, inside ``first_leg_window_s``, spanning ``first_leg_span_s`` and no more than
``first_leg_max_move`` above quiet (``src/sextant/entry/signals.py``; ADR-0004:12,66). The
entry is the fresh ask at run completion (the same gate as ``src/sextant/entry/replay.py``), and
a stale ask is a refusal class, never loosened. B's protection is the official NautilusTrader
trailing-stop example's 2.5% reduce-only ``trailing_stop_market`` with
``TrailingOffsetType.BASIS_POINTS`` and ``TriggerType.LAST_PRICE``
(``nautechsystems/nautilus_trader@27a8e54e7ac3c57d6cbf8891f0283dfbaee97317:nautilus_trader/examples/strategies/ema_cross_trailing_stop.py``);
the replay models the fill at the triggering print, as the PR-3 witness does.

The three arms are ADR-0024's 2/5 and 8/20 mover slots plus the ADR-0006 flat-slot rotation. The
rotation follows a fast sell only: a freed slot goes to the best-ranked pending name with no lift
(ADR-0006:17); a held name is never rotated without an expected-lift estimate, and none exists.
Every case and arm writes one MODELED TrialLog row, refusals included; the ledger is cumulative.

This is research replay, not a paper or live path. The six symbols come from the owner's
2026-11-09 cross-section; the K2 ranks and the tapes are the inputs, hashed in the report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from sextant.backtest.b_e2e import EntryRule, reviewed_rule
from sextant.validation.trials import TrialLog, snapshot_hash

REPO = Path(__file__).resolve().parents[3]
RULE_PATH = REPO / "lanes/sim/entry-parameters.json"
TRAIL_FRACTION = Decimal("0.025")
QUANTITY = 1
MAX_AGE_NS = 5_000_000_000
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _ns(stamp: str) -> int:
    """Parse an ISO timestamp (with offset or Z) into integer nanoseconds."""
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp has no timezone: {stamp}")
    delta = parsed.astimezone(UTC) - EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def _iso(ns: int) -> str:
    return (EPOCH + timedelta(microseconds=ns // 1_000)).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class Trade:
    ts_ns: int
    price: Decimal
    size: int = 100


@dataclass(frozen=True)
class Quote:
    ts_ns: int
    bid: Decimal
    ask: Decimal


@dataclass(frozen=True)
class RankPoint:
    generation_ns: int
    rank: int
    computable: bool = True


@dataclass(frozen=True)
class CaseData:
    case: str
    symbol: str
    onset_ns: int
    mark: Decimal
    trades: tuple[Trade, ...]
    quotes: tuple[Quote, ...]
    ranks: tuple[RankPoint, ...]
    hashes: tuple[tuple[str, str], ...] = ()
    planned: Run | None = None


@dataclass(frozen=True)
class Run:
    start_ns: int
    flag_ns: int
    confirm_ns: int
    quiet: Decimal
    last: Decimal
    n: int
    span_ns: int


@dataclass(frozen=True)
class Entry:
    ts_ns: int
    price: Decimal
    quote_ts_ns: int
    rotated: bool = False


@dataclass(frozen=True)
class TracePoint:
    ts_ns: int
    price: Decimal
    high: Decimal
    level: Decimal


@dataclass(frozen=True)
class Trail:
    high: Decimal
    level: Decimal
    exit_ts_ns: int | None
    exit_price: Decimal | None
    protected: float | None
    hold_flat: float
    path: tuple[TracePoint, ...]
    exited: bool
    mark_price: Decimal | None


@dataclass(frozen=True)
class ArmRow:
    case: CaseData
    arm: str
    state: str
    reason: str
    rank: int
    slot: int | None
    entry: Entry | None
    walked: Trail | None
    onset_ns: int
    hold_flat: float | None
    capacity: int
    rotation: bool


@dataclass(frozen=True)
class _Pending:
    case: CaseData
    run: Run
    rank: int


def load_cases(path: Path) -> tuple[CaseData, ...]:
    """Load the committed cohort fixture; the tape is pinned by the proof test."""
    data = json.loads(Path(path).read_text())
    cases = []
    for raw in data["cases"]:
        trades = tuple(
            sorted(
                (
                    Trade(_ns(row["ts"]), Decimal(row["price"]), int(row.get("size", 100)))
                    for row in raw["trades"]
                ),
                key=lambda trade: trade.ts_ns,
            )
        )
        quotes = tuple(
            sorted(
                (
                    Quote(_ns(row["ts"]), Decimal(row["bid"]), Decimal(row["ask"]))
                    for row in raw["quotes"]
                ),
                key=lambda quote: quote.ts_ns,
            )
        )
        ranks = tuple(
            sorted(
                (
                    RankPoint(
                        _ns(row["generation"]),
                        int(row["rank"]),
                        bool(row.get("computable", True)),
                    )
                    for row in raw.get("ranks", [])
                ),
                key=lambda point: point.generation_ns,
            )
        )
        cases.append(
            CaseData(
                case=raw["case"],
                symbol=raw["symbol"],
                onset_ns=_ns(raw["onset"]),
                mark=Decimal(raw["mark"]),
                trades=trades,
                quotes=quotes,
                ranks=ranks,
            )
        )
    return tuple(cases)


def find_run(trades: tuple[Trade, ...], rule: EntryRule) -> Run | None:
    """The cross-section's ``multi_scan``: the run's first print is the flag.

    The quiet price is the print before the outer print. ``run`` grows while prints stay above
    quiet and non-decreasing; a lower print restarts it and a print at or below quiet empties it.
    The first run with five prints, a two-second span and its last print inside the 3% cap wins.
    ``flag_ns`` is the run's first print (the cross-section's entry moment); ``confirm_ns`` is
    its last, where the ask's freshness is proved.
    """
    if len(trades) <= rule.trades:
        return None
    window_ns = rule.window_s * 1_000_000_000
    span_ns = rule.span_s * 1_000_000_000
    for index in range(1, len(trades)):
        quiet = trades[index - 1].price
        if trades[index].price <= quiet:
            continue
        run = [index]
        previous = trades[index].price
        for later in range(index + 1, len(trades)):
            print_ = trades[later]
            if print_.ts_ns - trades[index].ts_ns > window_ns:
                break
            if print_.price > quiet and print_.price >= previous:
                run.append(later)
            elif print_.price > quiet:
                run = [later]
            else:
                run = []
            previous = print_.price
            if len(run) < rule.trades:
                continue
            span = trades[run[-1]].ts_ns - trades[run[0]].ts_ns
            last = trades[run[-1]].price
            if span >= span_ns and last <= quiet * (1 + rule.max_move):
                first = trades[run[0]].ts_ns
                return Run(
                    start_ns=first,
                    flag_ns=first,
                    confirm_ns=trades[run[-1]].ts_ns,
                    quiet=quiet,
                    last=last,
                    n=len(run),
                    span_ns=span,
                )
    return None


def rank_at(case: CaseData, at_ns: int) -> int:
    """The last computable K2 rank known at or before ``at_ns``; 0 means unranked."""
    best = 0
    for point in case.ranks:
        if point.generation_ns > at_ns:
            break
        if point.computable:
            best = point.rank
    return best


def _quote_at(case: CaseData, at_ns: int) -> Quote | None:
    best = None
    for quote in case.quotes:
        if quote.ts_ns > at_ns:
            break
        best = quote
    return best


def _entry_at(case: CaseData, run: Run, rule: EntryRule) -> tuple[Entry | None, str]:
    """The first-leg ask once the run is confirmed; the fill is never retrospective."""
    quote = _quote_at(case, run.confirm_ns)
    if quote is None:
        return None, "thin quote: no fresh ask at run completion (no quote at or before completion)"
    age = run.confirm_ns - quote.ts_ns
    if age > MAX_AGE_NS:
        return None, (
            "thin quote: no fresh ask at run completion "
            f"(last quote {age / 1e9:.1f}s old at completion, max 5s)"
        )
    if quote.bid >= quote.ask:
        return None, "crossed quote: no fresh two-sided ask at run completion"
    ceiling = run.quiet * (1 + rule.max_move)
    if max(run.last, quote.ask) > ceiling:
        return None, (
            "first leg is beyond the 3% cap "
            f"(max(last {run.last}, ask {quote.ask}) > quiet {run.quiet} * 1.03)"
        )
    return Entry(ts_ns=run.confirm_ns, price=quote.ask, quote_ts_ns=quote.ts_ns), ""


def _quote_entry(case: CaseData, at_ns: int) -> tuple[Entry | None, str]:
    """The rotation's entry: a fresh two-sided ask at the freed slot's moment."""
    quote = _quote_at(case, at_ns)
    if quote is None:
        return None, "thin quote: no fresh ask at the freed slot"
    age = at_ns - quote.ts_ns
    if age > MAX_AGE_NS:
        return None, f"thin quote: no fresh ask at the freed slot ({age / 1e9:.1f}s old, max 5s)"
    if quote.bid >= quote.ask:
        return None, "crossed quote: no fresh two-sided ask at the freed slot"
    return Entry(ts_ns=at_ns, price=quote.ask, quote_ts_ns=quote.ts_ns), ""


def entry(case: CaseData, run: Run, rule: EntryRule) -> tuple[Entry | None, str]:
    return _entry_at(case, run, rule)


def trail(case: CaseData, filled: Entry) -> Trail:
    """B's 2.5% broker-held trail, modeled at the triggering print (the PR-3 witness)."""
    high = filled.price
    level = high * (1 - TRAIL_FRACTION)
    path: list[TracePoint] = []
    exit_ts_ns: int | None = None
    exit_price: Decimal | None = None
    exited = False
    for print_ in case.trades:
        if print_.ts_ns <= filled.ts_ns:
            continue
        if print_.price > high:
            high = print_.price
        level = high * (1 - TRAIL_FRACTION)
        path.append(TracePoint(print_.ts_ns, print_.price, high, level))
        if print_.price <= level:
            exit_ts_ns = print_.ts_ns
            exit_price = print_.price
            exited = True
            break
    mark_price = None if exited else (path[-1].price if path else filled.price)
    return Trail(
        high=high,
        level=level,
        exit_ts_ns=exit_ts_ns,
        exit_price=exit_price,
        protected=None if exit_price is None else float(exit_price / filled.price - 1),
        hold_flat=float(case.mark / filled.price - 1),
        path=tuple(path),
        exited=exited,
        mark_price=mark_price,
    )


def _free_slot(slots: list[ArmRow | None], at_ns: int, *, allow_exited: bool) -> int | None:
    for index, row in enumerate(slots):
        if row is None:
            return index
        if (
            allow_exited
            and row.walked is not None
            and row.walked.exited
            and row.walked.exit_ts_ns is not None
            and row.walked.exit_ts_ns <= at_ns
        ):
            return index
    return None


def _rotate(
    slots: list[ArmRow | None],
    rows: dict[str, ArmRow],
    pending: list[_Pending],
    *,
    at_ns: int,
    slot: int,
    arm: str,
    capacity: int,
    rotation: bool,
    rule: EntryRule,
) -> bool:
    candidates = [
        item
        for item in pending
        if item.run.flag_ns <= at_ns <= item.run.flag_ns + rule.window_s * 1_000_000_000
    ]
    candidates.sort(key=lambda item: (item.rank == 0, item.rank, item.run.flag_ns, item.case.case))
    for item in candidates:
        filled, _ = _quote_entry(item.case, at_ns)
        if filled is None:
            continue
        ceiling = item.run.quiet * (1 + rule.max_move)
        if filled.price < item.run.quiet or max(item.run.last, filled.price) > ceiling:
            continue
        filled = Entry(filled.ts_ns, filled.price, filled.quote_ts_ns, rotated=True)
        walked = trail(item.case, filled)
        row = ArmRow(
            case=item.case,
            arm=arm,
            state="COMPLETE" if walked.exited else "HELD",
            reason="rotated into a flat slot after a fast sell; no lift required (ADR-0006)",
            rank=item.rank,
            slot=slot + 1,
            entry=filled,
            walked=walked,
            onset_ns=item.case.onset_ns,
            hold_flat=walked.hold_flat,
            capacity=capacity,
            rotation=rotation,
        )
        slots[slot] = row
        rows[item.case.case] = row
        pending.remove(item)
        return True
    return False


def _process_exits(
    slots: list[ArmRow | None],
    rows: dict[str, ArmRow],
    pending: list[_Pending],
    *,
    before_ns: int,
    arm: str,
    capacity: int,
    rotation: bool,
    rule: EntryRule,
) -> None:
    while True:
        exits: list[tuple[int, int]] = []
        for index, row in enumerate(slots):
            if row is None or row.walked is None or not row.walked.exited:
                continue
            exit_ns = row.walked.exit_ts_ns
            if exit_ns is not None and exit_ns <= before_ns:
                exits.append((exit_ns, index))
        if not exits:
            return
        at_ns, slot = min(exits)
        slots[slot] = None
        if rotation:
            _rotate(
                slots,
                rows,
                pending,
                at_ns=at_ns,
                slot=slot,
                arm=arm,
                capacity=capacity,
                rotation=rotation,
                rule=rule,
            )


def run_arms(
    cases: list[CaseData] | tuple[CaseData, ...],
    *,
    capacity: int,
    rotation: bool,
    arm: str | None = None,
    rule: EntryRule | None = None,
) -> tuple[ArmRow, ...]:
    """Allocate one arm's slots and replay each case's entry, trail and exit."""
    rule = rule or reviewed_rule()
    label = arm or f"{capacity}-slot" + ("-rotation" if rotation else "")
    rows: dict[str, ArmRow] = {}
    slots: list[ArmRow | None] = [None] * capacity
    pending: list[_Pending] = []
    runs = {case.case: _run_of(case, rule) for case in cases}

    def order(case: CaseData) -> tuple[int, str]:
        run = runs[case.case]
        return (2**63 if run is None else run.flag_ns, case.case)

    ordered = sorted(cases, key=order)
    for case in ordered:
        run = runs[case.case]
        if run is None:
            rows[case.case] = ArmRow(
                case=case,
                arm=label,
                state="FAIL",
                reason="no first-leg run under the reviewed rule",
                rank=0,
                slot=None,
                entry=None,
                walked=None,
                onset_ns=case.onset_ns,
                hold_flat=None,
                capacity=capacity,
                rotation=rotation,
            )
            continue
        rank = rank_at(case, run.flag_ns)
        if rotation:
            _process_exits(
                slots,
                rows,
                pending,
                before_ns=run.flag_ns,
                arm=label,
                capacity=capacity,
                rotation=rotation,
                rule=rule,
            )
        filled, reason = entry(case, run, rule)
        if filled is None:
            rows[case.case] = ArmRow(
                case=case,
                arm=label,
                state="FAIL",
                reason=reason,
                rank=rank,
                slot=None,
                entry=None,
                walked=None,
                onset_ns=case.onset_ns,
                hold_flat=float(case.mark / run.last - 1),
                capacity=capacity,
                rotation=rotation,
            )
            continue
        slot = _free_slot(slots, run.flag_ns, allow_exited=rotation)
        if slot is None:
            rows[case.case] = ArmRow(
                case=case,
                arm=label,
                state="FAIL",
                reason="no slot under this arm",
                rank=rank,
                slot=None,
                entry=None,
                walked=None,
                onset_ns=case.onset_ns,
                hold_flat=float(case.mark / run.last - 1),
                capacity=capacity,
                rotation=rotation,
            )
            if rotation:
                pending.append(_Pending(case, run, rank))
            continue
        walked = trail(case, filled)
        row = ArmRow(
            case=case,
            arm=label,
            state="COMPLETE" if walked.exited else "HELD",
            reason="",
            rank=rank,
            slot=slot + 1,
            entry=filled,
            walked=walked,
            onset_ns=case.onset_ns,
            hold_flat=walked.hold_flat,
            capacity=capacity,
            rotation=rotation,
        )
        slots[slot] = row
        rows[case.case] = row
    if rotation:
        horizon = max(
            (print_.ts_ns for case in cases for print_ in case.trades),
            default=0,
        )
        _process_exits(
            slots,
            rows,
            pending,
            before_ns=horizon,
            arm=label,
            capacity=capacity,
            rotation=rotation,
            rule=rule,
        )
    return tuple(rows[case.case] for case in ordered)


def _head_sha() -> str:
    @lru_cache(maxsize=1)
    def _read() -> str:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True
        )
        return out.stdout.strip()

    return _read()


def _identity(arm: str, case: str, capacity: int, rotation: bool, session: str) -> dict:
    sandbox = {
        "arm": arm,
        "case": case,
        "session": session,
        "capacity": capacity,
        "rotation": rotation,
    }
    return {
        "arm_id": f"{arm}:{case}",
        "arm_run_id": uuid.uuid4().hex,
        "implementation_sha": _head_sha(),
        "factor_mask": [],
        "sandbox_config": sandbox,
        "sandbox_config_hash": snapshot_hash(sandbox),
        "evidence_weights": {},
        "evidence_weights_hash": snapshot_hash({}),
        "params_hash": None,
        "tier": "MODELED",
        "block_set_id": session,
        "funding_divergent_session_count": None,
        "funding_unverified_session_count": None,
        "condition_returns": {},
    }


def _params(row: ArmRow, session: str) -> dict:
    entry = row.entry
    walked = row.walked
    return {
        "case": row.case.case,
        "symbol": row.case.symbol,
        "arm": row.arm,
        "session": session,
        "capacity": str(row.capacity),
        "rotation": str(row.rotation),
        "rank": str(row.rank),
        "slot": "" if row.slot is None else str(row.slot),
        "onset": _iso(row.onset_ns),
        "entry_ts": "" if entry is None else _iso(entry.ts_ns),
        "entry": "" if entry is None else str(entry.price),
        "entry_basis": (
            "ask at run completion (the then-current quote); onset is the run's first print"
        ),
        "high": "" if walked is None else str(walked.high),
        "trail_level": "" if walked is None else str(walked.level),
        "exit_ts": "" if walked is None or walked.exit_ts_ns is None else _iso(walked.exit_ts_ns),
        "exit": "" if walked is None or walked.exit_price is None else str(walked.exit_price),
        "exited": "" if walked is None else str(walked.exited),
        "protected": (
            "" if walked is None or walked.protected is None else f"{walked.protected:.6f}"
        ),
        "mark": "" if walked is None or walked.mark_price is None else str(walked.mark_price),
        "hold_flat": "" if row.hold_flat is None else f"{row.hold_flat:.6f}",
        "rule": (
            "first_leg_window_s=120 first_leg_trades_count=5 "
            "first_leg_span_s=2 first_leg_max_move=0.03"
        ),
        "hashes": [f"{name}:{digest}" for name, digest in row.case.hashes],
    }


def _append(row: ArmRow, log: TrialLog, session: str) -> None:
    params = _params(row, session)
    config = _identity(row.arm, row.case.case, row.capacity, row.rotation, session)
    config["params_hash"] = snapshot_hash(params)
    if row.state == "COMPLETE":
        assert row.walked is not None and row.walked.protected is not None
        log.append(
            "b_e2e_cohort",
            params,
            config,
            0,
            state="COMPLETE",
            days=[session],
            daily_net_returns=[row.walked.protected],
            objective=row.walked.protected,
        )
    elif row.state == "HELD":
        assert row.walked is not None and row.walked.mark_price is not None
        log.append(
            "b_e2e_cohort",
            params,
            config,
            0,
            state="FAIL",
            error=(
                "HELD/NOT_EXITED: the tape ended before B's trail tripped; "
                f"unrealized mark {row.walked.mark_price} is not scored as a protected return"
            ),
        )
    else:
        log.append("b_e2e_cohort", params, config, 0, state="FAIL", error=row.reason)


def _run_of(case: CaseData, rule: EntryRule) -> Run | None:
    return case.planned if case.planned is not None else find_run(case.trades, rule)


def _hold_flat(case: CaseData, rule: EntryRule) -> tuple[float | None, str, str]:
    run = _run_of(case, rule)
    if run is None:
        return None, "", "no first-leg run"
    filled, _ = entry(case, run, rule)
    if filled is not None:
        basis = str(filled.price)
        return float(case.mark / filled.price - 1), basis, "first-leg ask at run completion"
    return float(case.mark / run.last - 1), str(run.last), "run-last (entry refused)"


def _append_hold_flat(case: CaseData, log: TrialLog, session: str, rule: EntryRule) -> None:
    hold_flat, basis, note = _hold_flat(case, rule)
    params = {
        "case": case.case,
        "symbol": case.symbol,
        "arm": "hold-flat",
        "session": session,
        "basis": basis,
        "note": note,
        "mark": str(case.mark),
        "onset": _iso(case.onset_ns),
        "rule": "hold the run-completion price to the cross-section mark",
        "hashes": [f"{name}:{digest}" for name, digest in case.hashes],
    }
    config = _identity("hold-flat", case.case, 0, False, session)
    config["params_hash"] = snapshot_hash(params)
    if hold_flat is None:
        log.append("b_e2e_cohort_hold_flat", params, config, 0, state="FAIL", error=note)
    else:
        log.append(
            "b_e2e_cohort_hold_flat",
            params,
            config,
            0,
            state="COMPLETE",
            days=[session],
            daily_net_returns=[hold_flat],
            objective=hold_flat,
        )


def write_rows(
    rows: tuple[ArmRow, ...] | list[ArmRow],
    cases: tuple[CaseData, ...] | list[CaseData],
    path: Path,
    *,
    session: str,
    hold_flat: bool = True,
    rule: EntryRule | None = None,
) -> None:
    rule = rule or reviewed_rule()
    log = TrialLog(Path(path))
    for row in rows:
        _append(row, log, session)
    if hold_flat:
        for case in cases:
            _append_hold_flat(case, log, session, rule)


def load_real(
    *,
    tapes: Path,
    work: Path,
    session: str,
) -> tuple[CaseData, ...]:
    """Load today's six SIP tapes and the e2e-omh K2 ranks; every input is hashed."""
    import numpy as np

    plan_path = tapes / "multi-plan.json"
    ranks_path = work / "ranks.npz"
    cohort_path = work / "cohort.json"
    plan = json.loads(plan_path.read_text())
    ranks = np.load(ranks_path)
    symbols = [str(symbol) for symbol in ranks["symbols"]]
    generations = ranks["generation_ns"]
    computable = ranks["computable"]
    rank_matrix = ranks["rank"]
    cases = []
    for symbol in ("ONDS", "NWGL", "TTD", "MF", "OMH", "CKX"):
        if symbol == "OMH":
            trade_file = tapes / "omh-trades-day.json"
            quote_file = tapes / "omh-quotes-run1.json"
            raw_trades = json.loads(trade_file.read_text())
            raw_quotes = json.loads(quote_file.read_text())
            trades = tuple(
                Trade(_ns(row["t"]), Decimal(str(row["p"])), int(row["s"])) for row in raw_trades
            )
            quotes = tuple(
                Quote(_ns(row["t"]), Decimal(str(row["bp"])), Decimal(str(row["ap"])))
                for row in raw_quotes
            )
        else:
            trade_file = tapes / f"multi-{symbol}.json"
            quote_file = trade_file
            tape = trade_file
            raw = json.loads(tape.read_text())
            raw_trades = raw["trades"]
            raw_quotes = raw["quotes"]
            trades = tuple(
                Trade(_ns(row["t"]), Decimal(str(row["p"])), int(row["s"])) for row in raw_trades
            )
            quotes = tuple(
                Quote(_ns(row["t"]), Decimal(str(row["bp"])), Decimal(str(row["ap"])))
                for row in raw_quotes
            )
        index = symbols.index(symbol)
        points = tuple(
            RankPoint(int(generations[i]), int(rank_matrix[i, index]), bool(computable[i]))
            for i in range(len(generations))
        )
        plan_row = plan[symbol]
        flag_ns = _ns(plan_row["flag"])
        span_ns = int(Decimal(str(plan_row["span_s"])) * 1_000_000_000)
        planned = Run(
            start_ns=flag_ns,
            flag_ns=flag_ns,
            confirm_ns=flag_ns + span_ns,
            quiet=Decimal(str(plan_row["quiet"])),
            last=Decimal(str(plan_row["last"])),
            n=int(plan_row["n"]),
            span_ns=span_ns,
        )
        hashes = (
            ("trades", _sha256(trade_file)),
            ("quotes", _sha256(quote_file)),
            ("ranks", _sha256(ranks_path)),
            ("plan", _sha256(plan_path)),
            ("cohort", _sha256(cohort_path)),
        )
        cases.append(
            CaseData(
                case=symbol.lower(),
                symbol=symbol,
                onset_ns=trades[0].ts_ns,
                mark=Decimal(str(plan_row["mark"])),
                trades=tuple(sorted(trades, key=lambda trade: trade.ts_ns)),
                quotes=tuple(sorted(quotes, key=lambda quote: quote.ts_ns)),
                ranks=tuple(sorted(points, key=lambda point: point.generation_ns)),
                hashes=hashes,
                planned=planned,
            )
        )
    return tuple(cases)


def _row_dict(row: ArmRow) -> dict:
    return {
        "case": row.case.case,
        "symbol": row.case.symbol,
        "arm": row.arm,
        "state": row.state,
        "reason": row.reason,
        "rank": row.rank,
        "slot": row.slot,
        "onset": _iso(row.onset_ns),
        "onset_to_entry_s": (None if row.entry is None else (row.entry.ts_ns - row.onset_ns) / 1e9),
        "entry_ts": None if row.entry is None else _iso(row.entry.ts_ns),
        "entry": None if row.entry is None else str(row.entry.price),
        "rotated": bool(row.entry and row.entry.rotated),
        "high": None if row.walked is None else str(row.walked.high),
        "trail_level": None if row.walked is None else str(row.walked.level),
        "exit_ts": (
            None
            if row.walked is None or row.walked.exit_ts_ns is None
            else _iso(row.walked.exit_ts_ns)
        ),
        "exit": (
            None
            if row.walked is None or row.walked.exit_price is None
            else str(row.walked.exit_price)
        ),
        "exited": None if row.walked is None else row.walked.exited,
        "protected": None if row.walked is None else row.walked.protected,
        "mark": (
            None
            if row.walked is None or row.walked.mark_price is None
            else str(row.walked.mark_price)
        ),
        "hold_flat": row.hold_flat,
    }


def _markdown(rows: list[ArmRow], cases: tuple[CaseData, ...] | list[CaseData]) -> str:
    lines = [
        "# Six-mover cohort replay (PR-3)",
        "",
        "The owner's 2026-11-09 cross-section. Entry = the reviewed first-leg ask once the "
        "five-print run is confirmed (the then-current quote); the entry-onset column keeps the "
        "run's first print. Protection = B's 2.5% broker-held trail; a position the tape never "
        "stops is HELD and its mark is not scored. Rows are MODELED in the one cumulative ledger.",
        "",
        "| arm | case | state | K2 rank | slot | entry | entry-onset (s) | high | exit "
        "| protected | hold-flat | note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        entry = "" if row.entry is None else str(row.entry.price)
        high = "" if row.walked is None else str(row.walked.high)
        if row.walked is None:
            exit_ = ""
        elif row.walked.exited:
            exit_ = "" if row.walked.exit_price is None else str(row.walked.exit_price)
        else:
            exit_ = f"held @ {row.walked.mark_price}"
        if row.walked is None or row.walked.protected is None:
            protected = "not scored"
        else:
            protected = f"{row.walked.protected:+.2%}"
        hold = "" if row.hold_flat is None else f"{row.hold_flat:+.2%}"
        note = row.reason or ("rotated" if row.entry and row.entry.rotated else "")
        lag = "" if row.entry is None else f"{(row.entry.ts_ns - row.onset_ns) / 1e9:.1f}"
        lines.append(
            f"| {row.arm} | {row.case.symbol} | {row.state} | {row.rank} | "
            f"{'' if row.slot is None else row.slot} | {entry} | {lag} | {high} | {exit_} | "
            f"{protected} | {hold} | {note} |"
        )
    lines.extend(["", "## Inputs", ""])
    for case in cases:
        inputs = ", ".join(f"{name} `{digest[:16]}`" for name, digest in case.hashes)
        lines.append(f"- {case.symbol}: {inputs}")
    return "\n".join(lines) + "\n"


def run_all(
    *,
    out: Path,
    log: Path,
    tapes: Path,
    work: Path,
    session: str,
) -> dict:
    cases = load_real(tapes=tapes, work=work, session=session)
    arms = (
        ("2-of-5", 2, False),
        ("8-of-20", 8, False),
        ("2-of-5-rotation", 2, True),
    )
    out.mkdir(parents=True, exist_ok=True)
    all_rows: list[ArmRow] = []
    for name, capacity, rotation in arms:
        rows = run_arms(cases, capacity=capacity, rotation=rotation, arm=name)
        all_rows.extend(rows)
        (out / f"{name}.json").write_text(
            json.dumps([_row_dict(row) for row in rows], indent=2) + "\n"
        )
        write_rows(rows, cases, log, session=session, hold_flat=False)
    write_rows((), cases, log, session=session, hold_flat=True)
    report = {
        "session": session,
        "arms": [name for name, _, _ in arms],
        "rows": [_row_dict(row) for row in all_rows],
        "cases": {
            case.symbol: {
                "onset": _iso(case.onset_ns),
                "mark": str(case.mark),
                "hashes": [[name, digest] for name, digest in case.hashes],
            }
            for case in cases
        },
    }
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / "summary.md").write_text(_markdown(all_rows, cases))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="replay the six-mover cohort into the ledger and the report")
    run.add_argument("--out", type=Path, default=REPO / "reports/research/b-e2e-cohort")
    run.add_argument("--log", type=Path, default=REPO / "reports/research/trials.parquet")
    run.add_argument("--tapes", type=Path, default=Path("/tmp"))  # noqa: S108
    run.add_argument(
        "--work",
        type=Path,
        default=Path("/home/sextant/sextant-data/handoffs/e2e-omh/work"),
    )
    run.add_argument("--session", default="2026-11-09")
    args = parser.parse_args(argv)
    if args.command == "run":
        run_all(out=args.out, log=args.log, tapes=args.tapes, work=args.work, session=args.session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
