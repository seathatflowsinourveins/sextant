"""A/C recorded-session e2e: the node's own decisions, B's level, no broker.

Template (Rule 1 rows in ``docs/manifest.md``): NautilusTrader's trailing-stop
example at ``nautechsystems/nautilus_trader@v1.231.0`` (entry LIMIT at the
trigger, ``trailing_stop_market`` at 2.5% for protection) and this repo's PR-3
recorded run (``docs/research/2026-11-09-b-e2e-pr3.md``, branch
``seathatflowsinourveins/b-clean-pr3`` commit ``2047d46``): the same level
trail, the same PR-3 values for OMH, PARA and SPCX.

The tape is today's recorded session (``tests/fixtures/ac-e2e-session.json``):
the e2e-omh 1-minute K2 generations for ONDS, NWGL, TTD, MF, OMH and CKX, and
SPCX's recorded 2026-10-21 catalyst print plus its new-high path. One-minute
bar closes are not a 5-print run, so the rank-armed cases refuse on coverage or
extension; SPCX's catalyst is the one recorded auto-entry. Every row is
MODELED: no broker client, no order, no live endpoint is constructed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from nautilus_trader.model import Money

from sextant.data.catalog import equity
from sextant.paper.ac_node import (
    TRAIL_FRACTION,
    AcEntry,
    AcLedger,
    EntryPlan,
    Profile,
    entry_parameters,
    profiles,
    refused_plan,
)

REPOSITORY = Path(__file__).resolve().parents[1]
TAPE_PATH = REPOSITORY / "tests/fixtures/ac-e2e-session.json"
EASTERN = ZoneInfo("America/New_York")
NS = 1_000_000_000
STARTING_CASH = "1000000 USD"

__all__ = [
    "CaseRun",
    "Decision",
    "Outcome",
    "Point",
    "TapeCase",
    "load_tape",
    "run",
    "run_case",
    "trail",
]


@dataclass(frozen=True)
class Point:
    ts_ns: int
    price: Decimal
    size: int = 1


@dataclass(frozen=True)
class Rank:
    ts_ns: int
    rank: int
    quiet_price: Decimal
    first_print_ts: int


@dataclass(frozen=True)
class TapeCase:
    symbol: str
    session: str
    segment: str
    prior_close: Decimal
    tape: str
    prints: tuple[Point, ...]
    ranks: tuple[Rank, ...] = ()
    catalyst_at: int | None = None
    catalyst_quiet: Decimal | None = None
    path: tuple[Point, ...] | None = None
    pr3: dict[str, str] | None = None


@dataclass(frozen=True)
class Decision:
    profile: str
    plan: EntryPlan

    @property
    def accepted(self) -> bool:
        return self.plan.accepted


@dataclass(frozen=True)
class CaseRun:
    case: TapeCase
    decisions: tuple[Decision, ...]
    reason: str = ""

    @property
    def accepted(self) -> tuple[Decision, ...]:
        return tuple(d for d in self.decisions if d.accepted)


@dataclass(frozen=True)
class Outcome:
    symbol: str
    entry: Decimal
    high: Decimal
    level: Decimal
    exit_ts_ns: int
    exit_price: Decimal
    prints: int
    protected: Decimal
    hold_flat: Decimal


def _ns(text: str) -> int:
    return int(datetime.fromisoformat(text).timestamp() * NS)


def _points(rows: list[dict[str, Any]]) -> tuple[Point, ...]:
    return tuple(
        Point(_ns(str(row["ts"])), Decimal(str(row["price"])), int(row["size"])) for row in rows
    )


def load_tape(
    path: Path = TAPE_PATH,
) -> tuple[dict[str, Any], list[TapeCase], list[dict[str, Any]]]:
    """Read the committed tape; every Decimal and every ns is explicit."""
    document = json.loads(path.read_text())
    cases = []
    for row in document["cases"]:
        catalyst = row.get("catalyst") or {}
        cases.append(
            TapeCase(
                symbol=str(row["symbol"]),
                session=str(row["session"]),
                segment=str(row["segment"]),
                prior_close=Decimal(str(row["prior_close"])),
                tape=str(row["tape"]),
                prints=_points(row["prints"]),
                ranks=tuple(
                    Rank(
                        _ns(str(rank["ts"])),
                        int(rank["rank"]),
                        Decimal(str(rank["quiet"])),
                        _ns(str(rank["first_print"])),
                    )
                    for rank in row.get("ranks") or ()
                ),
                catalyst_at=_ns(str(catalyst["knowable_at"])) if catalyst else None,
                catalyst_quiet=Decimal(str(catalyst["quiet"])) if catalyst else None,
                path=_points(row["path"]) if row.get("path") else None,
                pr3=row.get("pr3"),
            )
        )
    return document, cases, list(document.get("witnesses") or ())


def session_start_ns(session: str, segment: str) -> int:
    day = datetime.fromisoformat(session).replace(tzinfo=EASTERN)
    hour = 9 if segment == "RTH" else 4
    return int(day.replace(hour=hour, minute=30 if segment == "RTH" else 0).timestamp() * NS)


def trail(entry: Decimal, points: tuple[Point, ...], *, entry_ts_ns: int = 0) -> Outcome:
    """The 2.5% level trail exactly as PR-3's Nautilus run filled it.

    A new high lifts the level to ``high * (1 - fraction)``; the first print at
    or below the level is the exit fill. This is the same rule the live owner-B
    protector submits, so it is not a second protection model.
    """
    high, level = entry, entry * (1 - TRAIL_FRACTION)
    path = tuple(point for point in points if point.ts_ns >= entry_ts_ns)
    for point in path:
        if point.price > high:
            high, level = point.price, point.price * (1 - TRAIL_FRACTION)
        elif point.price <= level:
            return Outcome(
                "",
                entry,
                high,
                level,
                point.ts_ns,
                point.price,
                len(path),
                (point.price - entry) / entry,
                (path[-1].price - entry) / entry,
            )
    last = path[-1].price if path else entry
    return Outcome(
        "",
        entry,
        high,
        level,
        path[-1].ts_ns if path else 0,
        last,
        len(path),
        (last - entry) / entry,
        (last - entry) / entry,
    )


def _diagnose(case: TapeCase, entry: AcEntry, window_end: int) -> str:
    if entry.armed_rank is None:
        return "no K2 generation recorded (rank 1-2) and no scheduled catalyst"
    rank_ts = entry.state.surge.known_at if entry.state.surge else case.ranks[0].ts_ns
    window = tuple(point for point in case.prints if rank_ts <= point.ts_ns <= window_end)
    if not window:
        return "no print after the K2 generation"
    peak = max(max(point.price, case.prior_close) for point in window)
    cap = case.prior_close * (1 + entry.state.params["first_leg_max_move"])
    if peak > cap:
        return (
            "move beyond first_leg_max_move: "
            f"{peak} > {cap} above the quiet price {case.prior_close}"
        )
    if len(window) < int(entry.state.params["first_leg_trades_count"]):
        window_s = int(entry.state.params["first_leg_window_s"])
        return (
            "coverage below first_leg_trades_count: "
            f"{len(window)} prints inside the {window_s}s window"
        )
    return "the first-leg run did not hold"


def run_case(case: TapeCase, profile: Profile, params) -> CaseRun:
    """Feed one recorded case through the node's own decision code."""
    instrument = equity(case.symbol)
    start_ns = session_start_ns(case.session, case.segment)
    entry = AcEntry(
        instrument=instrument,
        params=params,
        profile=profile,
        start_ns=start_ns,
        segment=case.segment,
        equity=Money.from_str(STARTING_CASH),
        fixture=True,
    )
    if case.catalyst_at is not None:
        entry.observe_catalyst(
            knowable_at_ns=case.catalyst_at,
            quiet_price=case.catalyst_quiet or case.prior_close,
            source="recorded scheduled catalyst",
        )
    decisions: list[Decision] = []
    ranks = iter(case.ranks)
    next_rank = next(ranks, None)
    latest_rank: Rank | None = None
    for point in sorted(case.prints, key=lambda p: p.ts_ns):
        while next_rank is not None and next_rank.ts_ns <= point.ts_ns:
            entry.observe_rank(
                ts_ns=next_rank.ts_ns,
                rank=next_rank.rank,
                quiet_price=next_rank.quiet_price,
                first_print_ts=next_rank.first_print_ts,
            )
            latest_rank = next_rank
            next_rank = next(ranks, None)
        regular = case.segment == "RTH"
        plan = entry.observe_print(
            ts_ns=point.ts_ns,
            price=point.price,
            size=point.size,
            regular_hours=regular,
            ask=point.price,
            ask_ts_ns=point.ts_ns,
        )
        if plan is not None:
            decisions.append(Decision(profile.key, plan))
            if plan.accepted:
                break
    if not decisions:
        window_end = (latest_rank.ts_ns if latest_rank else start_ns) + int(
            params["first_leg_window_s"]
        )
        decisions.append(
            Decision(
                profile.key,
                refused_plan(
                    profile,
                    symbol=case.symbol,
                    ts_ns=case.prints[-1].ts_ns if case.prints else start_ns,
                    setup="FIRST_LEG" if case.ranks else "CATALYST",
                    rank=latest_rank.rank if latest_rank else None,
                    reason=_diagnose(case, entry, window_end),
                ),
            )
        )
    return CaseRun(case, tuple(decisions))


def _outcome(case: TapeCase, plan: EntryPlan) -> Outcome:
    entry_price = plan.limit.as_decimal() if plan.limit is not None else case.prior_close
    points = case.path if case.path is not None else case.prints
    result = trail(entry_price, points, entry_ts_ns=plan.ts_ns)
    return Outcome(
        case.symbol,
        result.entry,
        result.high,
        result.level,
        result.exit_ts_ns,
        result.exit_price,
        result.prints,
        result.protected,
        result.hold_flat,
    )


def _witness(witness: dict[str, Any]) -> dict[str, Any]:
    entry = Decimal(str(witness["entry"]))
    path = _points(witness["path"]) if witness.get("path") else ()
    cited = dict(witness.get("pr3") or {})
    result = {
        "symbol": witness["symbol"],
        "tape": witness["tape"],
        "entry": str(entry),
        "entry_ts": witness.get("entry_ts"),
        "path_points": len(path),
        "pr3": cited,
        "agrees": None,
    }
    if not path:
        return result
    outcome = trail(entry, path)
    result.update(
        {
            "high": str(outcome.high),
            "level": str(outcome.level),
            "exit": str(outcome.exit_price),
            "exit_ts": datetime.fromtimestamp(outcome.exit_ts_ns / NS, tz=EASTERN).isoformat()
            if outcome.exit_ts_ns
            else None,
            "protected": f"{outcome.protected:.6f}",
            "hold_flat": f"{outcome.hold_flat:.6f}",
            "agrees": (
                Decimal(cited["high"]) == outcome.high
                and Decimal(cited["level"]) == outcome.level
                and Decimal(cited["exit"]) == outcome.exit_price
                and abs(Decimal(cited["protected"]) - outcome.protected) <= Decimal("0.0002")
                and abs(Decimal(cited["hold_flat"]) - outcome.hold_flat) <= Decimal("0.0002")
            ),
        }
    )
    return result


def _snapshot_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _trial_params(profile: Profile, setup: str) -> dict[str, Any]:
    params = entry_parameters(fixture=True)
    return {
        "profile": profile.key,
        "setup": setup,
        "risk_per_trade": str(profile.risk_per_trade),
        "rank_ceilings": [str(value) for value in profile.rank_ceilings],
        "mover_slots": profile.mover_slots,
        "equity_mode": profile.equity_mode,
        "trail_fraction": str(TRAIL_FRACTION),
        "entry_rule": {name: str(value) for name, value in sorted(params.values.items())},
    }


def _implementation_sha() -> str:
    """A concrete 40-hex code identity: the checkout's HEAD, else this file's digest."""
    try:
        result = subprocess.run(
            ["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        sha = result.stdout.strip()
        if len(sha) == 40 and all(character in "0123456789abcdef" for character in sha):
            return sha
    except (OSError, subprocess.CalledProcessError):
        pass
    digest = hashlib.sha256((REPOSITORY / "scripts/ac_e2e.py").read_bytes())
    return digest.hexdigest()[:40]


def run(path: Path = TAPE_PATH) -> dict[str, Any]:
    document, cases, witnesses = load_tape(path)
    params = entry_parameters(fixture=True)
    registry = profiles()
    runs: list[CaseRun] = []
    outcomes: dict[tuple[str, str], Outcome] = {}
    ledgers = {
        key: AcLedger(Money.from_str(STARTING_CASH), value.equity_mode)
        for key, value in registry.items()
    }
    for case in cases:
        for key in ("a", "c"):
            profile = registry[key]
            result = run_case(case, profile, params)
            runs.append(result)
            for decision in result.accepted:
                outcome = _outcome(case, decision.plan)
                outcomes[(case.symbol, key)] = outcome
                assert decision.plan.quantity is not None
                quantity = decision.plan.quantity.as_decimal()
                ledgers[key].record(
                    entry=outcome.entry,
                    exit_price=outcome.exit_price,
                    quantity=quantity,
                )
    orders = []
    for symbol, key in sorted(outcomes):
        decision = next(
            d for r in runs if r.case.symbol == symbol for d in r.accepted if d.profile == key
        )
        outcome = outcomes[(symbol, key)]
        profile = registry[key]
        orders.append(
            {
                "profile": key,
                "lane": profile.lane,
                "mode": "replay" if key == "a" else "paper-slot-3",
                "symbol": symbol,
                "setup": decision.plan.setup,
                "ts": datetime.fromtimestamp(decision.plan.ts_ns / NS, tz=EASTERN).isoformat(),
                "side": "BUY",
                "order_type": "LIMIT",
                "time_in_force": "DAY",
                "limit": str(decision.plan.limit),
                "quantity": str(decision.plan.quantity),
                "stop": str(decision.plan.stop),
                "trail_fraction": str(TRAIL_FRACTION),
                "protected": f"{outcome.protected:.6f}",
                "hold_flat": f"{outcome.hold_flat:.6f}",
                "tier": "MODELED",
            }
        )
    trial_rows = []
    for result in runs:
        for decision in result.decisions:
            outcome = outcomes.get((result.case.symbol, decision.profile))
            params = _trial_params(registry[decision.profile], decision.plan.setup)
            trial_rows.append(
                {
                    "arm": f"paper-ac-{result.case.symbol.lower()}-"
                    f"{decision.plan.setup.lower()}-{decision.profile}",
                    "profile": decision.profile,
                    "symbol": result.case.symbol,
                    "setup": decision.plan.setup,
                    "rank": decision.plan.rank,
                    "state": "ACCEPTED" if decision.accepted else "REFUSED",
                    "reason": decision.plan.refusal,
                    "limit": str(decision.plan.limit) if decision.plan.limit else None,
                    "quantity": str(decision.plan.quantity) if decision.plan.quantity else None,
                    "protected": f"{outcome.protected:.6f}" if outcome else None,
                    "hold_flat": f"{outcome.hold_flat:.6f}" if outcome else None,
                    "params": params,
                    "params_hash": _snapshot_hash(params),
                    "tier": "MODELED",
                }
            )
    account_path = {
        key: {
            "mode": value.equity_mode,
            "start_equity": STARTING_CASH,
            "end_equity": str(ledgers[key].end_equity()),
            "realized": str(ledgers[key].realized),
            "fills": ledgers[key].fills,
            "next_sizing_equity": str(ledgers[key].sizing_equity()),
            "next_risk_budget": str(
                ledgers[key].sizing_equity().as_decimal() * value.risk_per_trade
            ),
        }
        for key, value in registry.items()
    }
    return {
        "schema": 1,
        "tape": document.get("source"),
        "recorded_at": document.get("recorded_at"),
        "starting_equity": STARTING_CASH,
        "profiles": {
            key: {
                "lane": value.lane,
                "slot": value.slot,
                "risk_per_trade": str(value.risk_per_trade),
                "risk_scope": value.risk_scope,
                "target_names": value.target_names,
                "mover_slots": value.mover_slots,
                "rank_ceilings": [str(item) for item in value.rank_ceilings],
                "equity_mode": value.equity_mode,
            }
            for key, value in registry.items()
        },
        "cases": [
            {
                "symbol": result.case.symbol,
                "segment": result.case.segment,
                "tape": result.case.tape,
                "pr3": result.case.pr3,
                "decisions": [
                    {
                        "profile": decision.profile,
                        "setup": decision.plan.setup,
                        "accepted": decision.accepted,
                        "rank": decision.plan.rank,
                        "limit": str(decision.plan.limit) if decision.plan.limit else None,
                        "quantity": str(decision.plan.quantity) if decision.plan.quantity else None,
                        "reason": decision.plan.refusal,
                    }
                    for decision in result.decisions
                ],
                "orders": [row for row in orders if row["symbol"] == result.case.symbol],
            }
            for result in runs
        ],
        "orders": orders,
        "accounts": account_path,
        "witnesses": [_witness(witness) for witness in witnesses],
        "trial_rows": trial_rows,
    }


def append_trials(report: dict[str, Any], log_path: Path) -> int:
    """Append the MODELED rows to the cumulative trial ledger (row 8's TrialLog).

    Every arm is one row, refused ones included. The rows carry TrialLog's full
    identity contract (a concrete code SHA, an explicit factor mask, frozen
    sandbox/evidence/params payloads and the hash of each), a terminal state
    and a fresh ``arm_run_id`` so a rerun appends a new attempt instead of
    rewriting history.
    """
    from sextant.validation.trials import TrialLog

    log = TrialLog(log_path)
    rows = report["trial_rows"]
    implementation_sha = _implementation_sha()
    sandbox_config = {
        "tape": "ac-e2e-session.json",
        "recorded_at": str(report.get("recorded_at") or "recorded-session"),
        "starting_equity": STARTING_CASH,
        "source": "scripts/ac_e2e.py",
    }
    evidence_weights = {
        "k2_generation": "recorded e2e-omh generations",
        "first_leg": "lanes/sim/entry-parameters.json",
        "catalyst": "recorded SPCX EDGAR knowable_at",
        "protection": "native 2.5% trail, PR-3 agreement",
    }
    for row in rows:
        params = row["params"]
        params_hash = _snapshot_hash(params)
        if params_hash != row["params_hash"]:
            raise ValueError("trial params drifted from the frozen report identity")
        config = {
            "arm_id": row["arm"],
            "arm_run_id": f"{row['arm']}-{uuid4().hex[:12]}",
            "implementation_sha": implementation_sha,
            "factor_mask": [
                "k2_generation",
                "first_leg",
                "catalyst",
                "fixed_risk_sizing",
                "native_trail_2p5",
            ],
            "sandbox_config": sandbox_config,
            "sandbox_config_hash": _snapshot_hash(sandbox_config),
            "evidence_weights": evidence_weights,
            "evidence_weights_hash": _snapshot_hash(evidence_weights),
            "params_hash": params_hash,
            "tier": "MODELED",
            "block_set_id": "ac-e2e-recorded-session",
            "funding_divergent_session_count": None,
            "funding_unverified_session_count": None,
            "condition_returns": {},
        }
        log.append(
            strategy="paper-ac-node",
            params=params,
            config=config,
            seed=0,
            state="COMPLETE" if row["state"] == "ACCEPTED" else "FAIL",
            error=row["reason"],
        )
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tape", type=Path, default=TAPE_PATH)
    parser.add_argument("--out", type=Path, default=None, help="write report.json here")
    parser.add_argument("--log", type=Path, default=None, help="append MODELED trial rows")
    args = parser.parse_args(argv)
    report = run(args.tape)
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    if args.log is not None:
        append_trials(report, args.log)
    print(
        json.dumps(
            {
                "orders": len(report["orders"]),
                "accepted": [
                    row["arm"] for row in report["trial_rows"] if row["state"] == "ACCEPTED"
                ],
                "refused": len([row for row in report["trial_rows"] if row["state"] == "REFUSED"]),
                "accounts": report["accounts"],
                "witnesses": {row["symbol"]: row["agrees"] for row in report["witnesses"]},
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
