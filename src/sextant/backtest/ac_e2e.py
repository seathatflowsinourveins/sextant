"""A/C recorded-session e2e: the node's own decisions, B's level, no broker.

Rule 1 rows: ``docs/manifest.md`` (NautilusTrader v1.231.0 trailing stop, PR-3).
One-minute closes are not a 5-print run, so rank-armed cases refuse; SPCX's
catalyst is the one recorded auto-entry.
"""

from __future__ import annotations

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

REPOSITORY = Path(__file__).resolve().parents[3]
TAPE_PATH = REPOSITORY / "tests/fixtures/ac-e2e-session.json"
EASTERN = ZoneInfo("America/New_York")
NS = 1_000_000_000
STARTING_CASH = "1000000 USD"


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
    prints: tuple[Point, ...]
    ranks: tuple[Rank, ...] = ()
    catalyst_at: int | None = None
    catalyst_quiet: Decimal | None = None
    path: tuple[Point, ...] | None = None
    pr3: dict[str, str] | None = None


@dataclass(frozen=True)
class Decision:
    plan: EntryPlan

    @property
    def accepted(self) -> bool:
        return self.plan.accepted


@dataclass(frozen=True)
class CaseRun:
    case: TapeCase
    decisions: tuple[Decision, ...]

    @property
    def accepted(self) -> tuple[Decision, ...]:
        return tuple(d for d in self.decisions if d.accepted)


@dataclass(frozen=True)
class Outcome:
    entry: Decimal
    high: Decimal
    level: Decimal
    exit_ts_ns: int
    exit_price: Decimal
    protected: Decimal
    hold_flat: Decimal


def _ns(text: str) -> int:
    return int(datetime.fromisoformat(text).timestamp() * NS)


def _points(rows: list[dict[str, Any]]) -> tuple[Point, ...]:
    return tuple(
        Point(_ns(str(row["ts"])), Decimal(str(row["price"])), int(row["size"])) for row in rows
    )


def load_tape(path: Path = TAPE_PATH) -> tuple[list[TapeCase], list[dict[str, Any]]]:
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
    return cases, list(document.get("witnesses") or ())


def session_start_ns(session: str, segment: str) -> int:
    day = datetime.fromisoformat(session).replace(tzinfo=EASTERN)
    return int(day.replace(hour=9 if segment == "RTH" else 4).timestamp() * NS)


def trail(entry: Decimal, points: tuple[Point, ...], *, entry_ts_ns: int = 0) -> Outcome:
    # A new high lifts the level to high*(1-fraction); the first crossing fills.
    high, level = entry, entry * (1 - TRAIL_FRACTION)
    path = tuple(point for point in points if point.ts_ns >= entry_ts_ns)
    for point in path:
        if point.price > high:
            high, level = point.price, point.price * (1 - TRAIL_FRACTION)
        elif point.price <= level:
            return Outcome(
                entry,
                high,
                level,
                point.ts_ns,
                point.price,
                (point.price - entry) / entry,
                (path[-1].price - entry) / entry,
            )
    last = path[-1] if path else None
    price = last.price if last else entry
    return Outcome(
        entry,
        high,
        level,
        last.ts_ns if last else 0,
        price,
        (price - entry) / entry,
        (price - entry) / entry,
    )


def _diagnose(case: TapeCase, entry: AcEntry, window_end: int) -> str:
    if entry.armed_rank is None:
        return "no K2 generation recorded (rank 1-2) and no scheduled catalyst"
    rank_ts = entry.state.surge.known_at if entry.state.surge else case.ranks[0].ts_ns
    window = tuple(point for point in case.prints if rank_ts <= point.ts_ns <= window_end)
    peak = max((max(point.price, case.prior_close) for point in window), default=case.prior_close)
    cap = case.prior_close * (1 + entry.state.params["first_leg_max_move"])
    if peak > cap:
        return (
            f"move beyond first_leg_max_move: {peak} > {cap} above the quiet price "
            f"{case.prior_close}"
        )
    return "the first-leg run did not hold"


def run_case(case: TapeCase, profile: Profile, params) -> CaseRun:
    entry = AcEntry(
        instrument=equity(case.symbol),
        params=params,
        profile=profile,
        start_ns=session_start_ns(case.session, case.segment),
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
    next_rank, latest_rank = next(ranks, None), None
    for point in sorted(case.prints, key=lambda p: p.ts_ns):
        while next_rank is not None and next_rank.ts_ns <= point.ts_ns:
            entry.observe_rank(
                ts_ns=next_rank.ts_ns,
                rank=next_rank.rank,
                quiet_price=next_rank.quiet_price,
                first_print_ts=next_rank.first_print_ts,
            )
            latest_rank, next_rank = next_rank, next(ranks, None)
        plan = entry.observe_print(
            ts_ns=point.ts_ns,
            price=point.price,
            size=point.size,
            regular_hours=case.segment == "RTH",
            ask=point.price,
            ask_ts_ns=point.ts_ns,
        )
        if plan is not None:
            decisions.append(Decision(plan))
            if plan.accepted:
                break
    if not decisions:
        window_end = (
            latest_rank.ts_ns if latest_rank else session_start_ns(case.session, case.segment)
        ) + int(params["first_leg_window_s"])
        decisions.append(
            Decision(
                refused_plan(
                    profile,
                    symbol=case.symbol,
                    ts_ns=case.prints[-1].ts_ns if case.prints else 0,
                    setup="FIRST_LEG" if case.ranks else "CATALYST",
                    rank=latest_rank.rank if latest_rank else None,
                    reason=_diagnose(case, entry, window_end),
                ),
            )
        )
    return CaseRun(case, tuple(decisions))


def _outcome(case: TapeCase, plan: EntryPlan) -> Outcome:
    entry_price = plan.limit.as_decimal() if plan.limit is not None else case.prior_close
    return trail(
        entry_price, case.path if case.path is not None else case.prints, entry_ts_ns=plan.ts_ns
    )


def _witness(witness: dict[str, Any]) -> dict[str, Any]:
    entry = Decimal(str(witness["entry"]))
    path = _points(witness["path"]) if witness.get("path") else ()
    cited = dict(witness.get("pr3") or {})
    result: dict[str, Any] = {
        "symbol": witness["symbol"],
        "path_points": len(path),
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
    sha = subprocess.run(
        ["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if len(sha) == 40:
        return sha
    return hashlib.sha256((REPOSITORY / "src/sextant/backtest/ac_e2e.py").read_bytes()).hexdigest()[
        :40
    ]


def run(path: Path = TAPE_PATH) -> dict[str, Any]:
    cases, witnesses = load_tape(path)
    params = entry_parameters(fixture=True)
    registry = profiles()
    runs = [
        (case, key, run_case(case, registry[key], params)) for case in cases for key in ("a", "c")
    ]
    ledgers = {
        key: AcLedger(Money.from_str(STARTING_CASH), profile.equity_mode)
        for key, profile in registry.items()
    }
    outcomes: dict[tuple[str, str], Outcome] = {}
    for case, key, result in runs:
        for decision in result.accepted:
            outcome = _outcome(case, decision.plan)
            outcomes[(case.symbol, key)] = outcome
            assert decision.plan.quantity is not None
            ledgers[key].record(
                entry=outcome.entry,
                exit_price=outcome.exit_price,
                quantity=decision.plan.quantity.as_decimal(),
            )
    orders = []
    for (symbol, key), outcome in sorted(outcomes.items()):
        _, _, result = next(row for row in runs if row[0].symbol == symbol and row[1] == key)
        plan = result.accepted[0].plan
        orders.append(
            {
                "profile": key,
                "mode": "replay" if key == "a" else "paper-slot-3",
                "symbol": symbol,
                "setup": plan.setup,
                "side": "BUY",
                "order_type": "LIMIT",
                "time_in_force": "DAY",
                "limit": str(plan.limit),
                "quantity": str(plan.quantity),
                "stop": str(plan.stop),
                "protected": f"{outcome.protected:.6f}",
                "hold_flat": f"{outcome.hold_flat:.6f}",
                "tier": "MODELED",
            }
        )
    trial_rows = []
    for case, key, result in runs:
        for decision in result.decisions:
            outcome = outcomes.get((case.symbol, key))
            plan = decision.plan
            trial_params = _trial_params(registry[key], plan.setup)
            trial_rows.append(
                {
                    "arm": f"paper-ac-{case.symbol.lower()}-{plan.setup.lower()}-{key}",
                    "profile": key,
                    "symbol": case.symbol,
                    "state": "ACCEPTED" if decision.accepted else "REFUSED",
                    "reason": plan.refusal,
                    "params": trial_params,
                    "params_hash": _snapshot_hash(trial_params),
                    "tier": "MODELED",
                }
            )
    return {
        "orders": orders,
        "accounts": {
            key: {
                "mode": profile.equity_mode,
                "end_equity": str(ledgers[key].end_equity()),
                "next_sizing_equity": str(ledgers[key].sizing_equity()),
                "next_risk_budget": str(
                    ledgers[key].sizing_equity().as_decimal() * profile.risk_per_trade
                ),
            }
            for key, profile in registry.items()
        },
        "witnesses": [_witness(witness) for witness in witnesses],
        "trial_rows": trial_rows,
    }


def append_trials(report: dict[str, Any], log_path: Path) -> int:
    from sextant.validation.trials import TrialLog

    implementation_sha = _implementation_sha()
    sandbox_config = {
        "tape": "ac-e2e-session.json",
        "recorded_at": "2026-11-09/2026-10-21",
        "starting_equity": STARTING_CASH,
        "source": "src/sextant/backtest/ac_e2e.py",
    }
    evidence_weights = {
        "k2_generation": "recorded e2e-omh generations",
        "first_leg": "lanes/sim/entry-parameters.json",
        "catalyst": "recorded SPCX EDGAR knowable_at",
        "protection": "native 2.5% trail, PR-3 agreement",
    }
    log = TrialLog(log_path)
    rows = report["trial_rows"]
    base = {
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
        "tier": "MODELED",
        "block_set_id": "ac-e2e-recorded-session",
        "funding_divergent_session_count": None,
        "funding_unverified_session_count": None,
        "condition_returns": {},
    }
    for row in rows:
        params = row["params"]
        params_hash = _snapshot_hash(params)
        if params_hash != row["params_hash"]:
            raise ValueError("trial params drifted from the frozen report identity")
        config = dict(
            base,
            arm_id=row["arm"],
            arm_run_id=f"{row['arm']}-{uuid4().hex[:12]}",
            params_hash=params_hash,
        )
        log.append(
            strategy="paper-ac-node",
            params=params,
            config=config,
            seed=0,
            state="COMPLETE" if row["state"] == "ACCEPTED" else "FAIL",
            error=row["reason"],
        )
    return len(rows)
