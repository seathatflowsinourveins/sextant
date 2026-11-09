"""One-session replay: K2 comparator then the frozen arms, streamed.

Fidelity is named, not hidden: one synthetic tick per non-zero-volume minute
at the bar close, a zero-size anchor only when the first bar starts exactly at
the segment boundary, zero-volume minutes skipped, one generation per minute,
no freshness ages applied.  The K3 section is detection-only, so this runner
emits a development table and never a TrialLog row.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from sextant.ranking.engine import (
    MoverState,
    ReferencePrices,
    Segment,
    advance_mover,
    qualifies,
    rank_movers,
)
from sextant.ranking.registry import ROWS, Registry, RegistryRow

from . import arms, bars, baseline, cohort, metrics, protocol, seal

NS = 1_000_000_000
MINUTE_NS = 60 * NS
ZERO = Decimal(0)
HALF_DECADE = Decimal("0.05")
ET = ZoneInfo("America/New_York")
PRE_START = (4, 0)
RTH_START = (9, 30)
PRE_MINUTES = 330
RTH_MINUTES = 125
SESSION_HOURS = Decimal(455) / 60
ROOT = Path(__file__).resolve().parents[2]


def _at(day: date, hour: int, minute: int) -> int:
    return int(datetime.combine(day, time(hour, minute), tzinfo=ET).timestamp()) * NS


def load_registry(path: Path) -> Registry:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != "k2-ranking.registry/1":
        raise ValueError("unexpected registry schema")
    rows = []
    for row in data["rows"]:
        kind, _ = ROWS[row["name"]]
        value = Decimal(row["value"]) if kind is Decimal else int(row["value"])
        rows.append(
            RegistryRow(
                row["name"],
                row["unit"],
                value,
                row["source"],
                row["calibration_state"],
                date.fromisoformat(row["last_change"]),
            )
        )
    return Registry(tuple(rows))


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tree_sha(paths: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _day_receipt(root: Path, day: date) -> str:
    directory = Path(root) / "1min" / day.isoformat()
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.json")):
        digest.update(path.name.encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _prior_curves(
    root: Path,
    prior: Sequence[date],
    symbols: Sequence[str],
    *,
    start: tuple[int, int],
    minutes: int,
) -> dict[str, tuple[tuple[Decimal, ...], ...]]:
    start_ns = _at(prior[0], *start)
    per_symbol: dict[str, list[tuple[Decimal, ...]]] = {symbol: [] for symbol in symbols}
    for day in prior:
        day_bars = bars.load_raw_day(root, day, symbols=set(symbols))
        curves = baseline.cumulative_curves(day_bars, symbols, _at(day, *start), minutes)
        for symbol in symbols:
            per_symbol[symbol].append(curves[symbol])
        del day_bars, curves
    del start_ns
    return {symbol: tuple(curves) for symbol, curves in per_symbol.items()}


@dataclass(slots=True)
class SessionResult:
    session: date
    truth_count: int
    control_count: int
    onsets: dict[str, int]
    rows: dict[str, dict[str, Any]]
    arms: dict[str, dict[str, Any]]
    trial_status: str
    trial_row: dict[str, Any] | None
    seal: tuple[seal.SealItem, ...]
    report: dict[str, Any]


def _replay_arm(
    *,
    arm_name: str,
    root: Path,
    session: date,
    segment: Segment,
    minutes: int,
    symbols: Sequence[str],
    today: Mapping[str, Sequence[bars.Bar]],
    refs: Mapping[str, ReferencePrices],
    baseline_source: baseline.CurveBaseline,
    registry: Registry,
    onsets: Mapping[str, int],
    out_path: Path,
    gap_arm: arms.GapArm | None = None,
    keep: arms.KeepAlive | None = None,
    publish_interval_ns: int = NS,
) -> tuple[
    dict[str, int],
    dict[str, int],
    dict[str, int | None],
    dict[str, int],
    dict[str, bool],
    dict[str, bool],
    dict[str, int],
    dict[str, dict[str, object]],
]:
    """Replay one segment and publish full K2 generations.

    Every generation ranks the latest computable row of every symbol in the
    segment, not only the symbols whose bar closed in that minute (K2 section
    5).  A symbol with no bar in the minute keeps its previous row until a new
    tick replaces it.  The one synthetic tick allowed is the real opening price
    of a bar that starts exactly at the segment boundary; when that bar is
    absent the state starts at its first real bar and the prefix stays
    uncovered.  No prior-close anchor is fabricated.
    """
    del root
    segment_bars = {
        symbol: tuple(
            bar for bar in today.get(symbol, ()) if segment.start_ns <= bar.ts_ns < segment.end_ns
        )
        for symbol in symbols
    }
    states = {symbol: MoverState() for symbol in symbols if segment_bars[symbol] and symbol in refs}
    pointers = {symbol: 0 for symbol in states}
    first30: dict[str, int] = {}
    first100: dict[str, int] = {}
    rank_at_onset: dict[str, int | None] = {}
    keepalive_first: dict[str, int] = {}
    members_at_onset: dict[str, bool] = {}
    baseline_available: dict[str, bool] = {}
    universe_at_onset: dict[str, int] = {}
    gap_flags: dict[str, dict[str, object]] = {}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    last_publish = segment.start_ns - publish_interval_ns
    with out_path.open("w", encoding="utf-8") as stream:
        # Bar fidelity: the opening bar's open is the first real price.  Use it
        # as a zero-size anchor only when that bar actually starts at the
        # boundary; a later first bar leaves the prefix unknown.
        for symbol, blist in segment_bars.items():
            if symbol not in states or not blist or blist[0].ts_ns != segment.start_ns:
                continue
            anchor = bars.anchor_tick(symbol, blist[0].open, segment.start_ns)
            states[symbol], _ = advance_mover(
                states[symbol],
                cast(Any, anchor),
                refs[symbol],
                cast(Any, baseline_source),
                segment=segment,
                feed="sip",
                registry=registry,
            )
        for tick_ns in range(segment.start_ns + MINUTE_NS, segment.end_ns + 1, MINUTE_NS):
            for symbol, state in states.items():
                pointer = pointers[symbol]
                blist = segment_bars[symbol]
                while pointer < len(blist) and blist[pointer].close_ns <= tick_ns:
                    if blist[pointer].close_ns == tick_ns:
                        bar = blist[pointer]
                        if gap_arm is not None:
                            flag = gap_arm.observe(bar, refs[symbol].prior_close)
                            if flag is not None and symbol not in gap_flags:
                                gap_flags[symbol] = {
                                    "flag_ts": flag.ts_ns,
                                    "price": flag.price,
                                    "gap": flag.gap,
                                    "reason": flag.reason,
                                }
                        state, row = advance_mover(
                            state,
                            cast(Any, bars.tick_from_bar(bar)),
                            refs[symbol],
                            cast(Any, baseline_source),
                            segment=segment,
                            feed="sip",
                            registry=registry,
                        )
                        states[symbol] = state
                    pointer += 1
                pointers[symbol] = pointer
            ranked: tuple[Any, ...] = ()
            if tick_ns - last_publish >= publish_interval_ns:
                generation = [state.latest for state in states.values() if state.latest is not None]
                ranked = rank_movers(generation)
                last_publish = tick_ns
            rank_map = {row.symbol: row.rank for row in ranked}
            qualified = {row.symbol for row in ranked if qualifies(row)}
            members = keep.update(rank=rank_map, qualified=qualified) if keep is not None else set()
            for row in ranked:
                if row.rank is not None and row.rank <= 30 and row.symbol not in first30:
                    first30[row.symbol] = tick_ns
                if row.rank is not None and row.rank <= 100 and row.symbol not in first100:
                    first100[row.symbol] = tick_ns
            for symbol in members:
                keepalive_first.setdefault(symbol, tick_ns)
            if onsets:
                by_symbol = {row.symbol: row for row in ranked}
                for symbol, onset in onsets.items():
                    if onset != tick_ns:
                        continue
                    rank_at_onset[symbol] = rank_map.get(symbol)
                    members_at_onset[symbol] = symbol in members
                    row = by_symbol.get(symbol)
                    baseline_available[symbol] = (
                        row is not None
                        and row.observations.get("baseline_sessions") is not None
                        and row.observations.get("baseline_dollar_volume") is not None
                    )
                    universe_at_onset[symbol] = len(ranked)
            stream.write(
                json.dumps(
                    {
                        "ts_ns": tick_ns,
                        "segment": segment.name,
                        "arm": arm_name,
                        "universe": len(ranked),
                        "top30": [row.symbol for row in ranked[:30]],
                        "top100": [row.symbol for row in ranked[:100]],
                        "members": sorted(members),
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
    return (
        first30,
        first100,
        rank_at_onset,
        keepalive_first,
        members_at_onset,
        baseline_available,
        universe_at_onset,
        gap_flags,
    )


def _strata(onsets: Mapping[str, int], session: date) -> dict[str, list[str]]:
    bounds = [
        ("pre_open_30", _at(session, 4, 0), _at(session, 4, 30)),
        ("pre_rest", _at(session, 4, 30), _at(session, 9, 30)),
        ("rth_open_30", _at(session, 9, 30), _at(session, 10, 0)),
        ("rth_rest", _at(session, 10, 0), _at(session, 11, 35)),
    ]
    out = {name: [] for name, _, _ in bounds}
    for symbol, onset in onsets.items():
        for name, lo, hi in bounds:
            if lo <= onset < hi:
                out[name].append(symbol)
                break
    return out


def _stratum_metrics(
    onsets: Mapping[str, int],
    k2_rank: Mapping[str, int | None],
    mean_rank: Mapping[str, int | None],
    gap_flags: Mapping[str, Mapping[str, object]],
    session: date,
) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for name, members in _strata(onsets, session).items():
        total = len(members)

        def recall(
            rank_map: Mapping[str, int | None],
            k: int,
            members: Sequence[str] = members,
            total: int = total,
        ) -> str:
            hits = sum(
                1
                for symbol in members
                if (place := rank_map.get(symbol)) is not None and place <= k
            )
            return str(Decimal(hits) / total) if total else "0"

        out[name] = {
            "truth": total,
            "k2_recall": {k: recall(k2_rank, k) for k in (30, 100)},
            "mean_recall": {k: recall(mean_rank, k) for k in (30, 100)},
            "gap_detected": sum(1 for symbol in members if symbol in gap_flags),
        }
    return out


def run_session(
    *,
    cohort_path: Path,
    bars_root: Path,
    reg_path: Path,
    out_dir: Path,
    protocol_doc: Path | None = None,
    verify_protocol: bool = True,
    protocol_required: bool = True,
) -> SessionResult:
    sealed = cohort.load_cohort(Path(cohort_path))
    registry = load_registry(Path(reg_path))
    receipt = None
    if verify_protocol:
        doc = Path(protocol_doc or ROOT / "docs" / "research" / "2026-11-06-ranking.md")
        receipt = protocol.verify_protocol(doc)
        if protocol_required:
            receipt.require_frozen()
    symbols = sealed.symbols
    prior = sealed.prior_sessions
    today = bars.load_raw_day(Path(bars_root), sealed.session, symbols=set(symbols))
    onsets: dict[str, int] = {}
    for candidate in sealed.truth:
        if candidate.prior_close is None:
            continue
        threshold = candidate.prior_close * (1 + HALF_DECADE)
        for bar in today.get(candidate.symbol, ()):
            if bar.close >= threshold:
                onsets[candidate.symbol] = bar.close_ns
                break
    refs: dict[str, ReferencePrices] = {}
    missing_today: list[str] = []
    for candidate in sealed.candidates:
        if candidate.prior_close is None:
            continue
        if candidate.symbol not in today:
            missing_today.append(candidate.symbol)
            continue
        refs[candidate.symbol] = ReferencePrices(
            candidate.prior_close,
            _at(prior[-1], 16, 0),
            "official prior-session daily close carried by the sealed cohort; no fallback",
        )
    if not refs:
        raise ValueError("no candidate has both a prior close and today's bars")
    known_at = _at(prior[-1], 20, 0)
    latest = prior[-1]
    pre_curves = _prior_curves(bars_root, prior, list(refs), start=PRE_START, minutes=PRE_MINUTES)
    rth_curves = _prior_curves(bars_root, prior, list(refs), start=RTH_START, minutes=RTH_MINUTES)
    median_pre = baseline.MedianCurveBaseline(
        pre_curves,
        feed="sip",
        known_at=known_at,
        provenance="median of prior-session cumulative curves",
        latest_session=latest,
    )
    median_rth = baseline.MedianCurveBaseline(
        rth_curves,
        feed="sip",
        known_at=known_at,
        provenance="median of prior-session cumulative curves",
        latest_session=latest,
    )
    mean_pre = baseline.MeanCurveBaseline(
        pre_curves,
        feed="sip",
        known_at=known_at,
        provenance="mean of prior-session cumulative curves",
        latest_session=latest,
    )
    mean_rth = baseline.MeanCurveBaseline(
        rth_curves,
        feed="sip",
        known_at=known_at,
        provenance="mean of prior-session cumulative curves",
        latest_session=latest,
    )
    # Bar fidelity: the 09:29-09:30 bar (and the 11:34-11:35 bar) closes at the
    # segment boundary.  Widen the engine's half-open end by one nanosecond so
    # that boundary close is accepted while every reported timestamp stays at
    # 09:30 / 11:35.  The prior curves carry one extra slot (offset == minutes)
    # for exactly this final bar.
    pre = Segment(
        "PRE",
        sealed.session,
        _at(sealed.session, 4, 0),
        _at(sealed.session, 9, 30) + 1,
        "XNYS regular session, Alpaca SIP bars",
    )
    rth = Segment(
        "RTH",
        sealed.session,
        _at(sealed.session, 9, 30),
        _at(sealed.session, 11, 35) + 1,
        "XNYS regular session truncated at the cohort's 11:35 ET data end",
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    gap_arm = arms.GapArm(
        window_start_ns=_at(sealed.session, 4, 0),
        window_end_ns=_at(sealed.session, 4, 5),
    )
    keep = arms.KeepAlive(top_n=int(registry.top_n))
    publish_interval_ns = int(registry.publish_min_interval_s) * NS
    k2_first30_seg: dict[str, dict[str, int]] = {}
    k2_first100_seg: dict[str, dict[str, int]] = {}
    k2_rank_seg: dict[str, dict[str, int | None]] = {}
    k2_universe_seg: dict[str, dict[str, int]] = {}
    k2_baseline_seg: dict[str, dict[str, bool]] = {}
    ka_first_seg: dict[str, dict[str, int]] = {}
    ka_members_seg: dict[str, dict[str, bool]] = {}
    gap_flags: dict[str, dict[str, object]] = {}
    mean_first30_seg: dict[str, dict[str, int]] = {}
    mean_first100_seg: dict[str, dict[str, int]] = {}
    mean_rank_seg: dict[str, dict[str, int | None]] = {}
    for segment, minutes, median_base, mean_base, tag in (
        (pre, PRE_MINUTES, median_pre, mean_pre, "pre"),
        (rth, RTH_MINUTES, median_rth, mean_rth, "rth"),
    ):
        f30, f100, rank, ka, m_at_onset, base_avail, universe, gaps = _replay_arm(
            arm_name="k2",
            root=bars_root,
            session=sealed.session,
            segment=segment,
            minutes=minutes,
            symbols=list(refs),
            today=today,
            refs=refs,
            baseline_source=median_base,
            registry=registry,
            onsets=onsets,
            out_path=out_dir / f"generations-k2-{tag}.jsonl",
            gap_arm=gap_arm,
            keep=keep,
            publish_interval_ns=publish_interval_ns,
        )
        k2_first30_seg[segment.name] = f30
        k2_first100_seg[segment.name] = f100
        k2_rank_seg[segment.name] = rank
        k2_universe_seg[segment.name] = universe
        k2_baseline_seg[segment.name] = base_avail
        ka_first_seg[segment.name] = ka
        ka_members_seg[segment.name] = m_at_onset
        gap_flags.update(gaps)
        f30, f100, rank, _, _, _, _, _ = _replay_arm(
            arm_name="mean",
            root=bars_root,
            session=sealed.session,
            segment=segment,
            minutes=minutes,
            symbols=list(refs),
            today=today,
            refs=refs,
            baseline_source=mean_base,
            registry=registry,
            onsets=onsets,
            out_path=out_dir / f"generations-mean-{tag}.jsonl",
            gap_arm=None,
            keep=None,
            publish_interval_ns=publish_interval_ns,
        )
        mean_first30_seg[segment.name] = f30
        mean_first100_seg[segment.name] = f100
        mean_rank_seg[segment.name] = rank

    # One K2 generation stream for readers that want the frozen comparator as a
    # single time-ordered file; per-arm and per-segment streams stay beside it.
    merged = out_dir / "generations.jsonl"
    with merged.open("wb") as dst:
        for tag in ("pre", "rth"):
            part = out_dir / f"generations-k2-{tag}.jsonl"
            if part.exists():
                dst.write(part.read_bytes())

    truth_onsets = {
        symbol: ts for symbol, ts in onsets.items() if symbol in {c.symbol for c in sealed.truth}
    }

    def segment_for(ts: int) -> str:
        return "PRE" if ts < rth.start_ns else "RTH"

    k2_rank = {
        symbol: k2_rank_seg[segment_for(ts)].get(symbol) for symbol, ts in truth_onsets.items()
    }
    k2_first100 = {
        symbol: k2_first100_seg[segment_for(ts)].get(symbol) for symbol, ts in truth_onsets.items()
    }
    k2_universe = {
        symbol: k2_universe_seg[segment_for(ts)].get(symbol, 0)
        for symbol, ts in truth_onsets.items()
    }
    k2_baseline_available = {
        symbol: k2_baseline_seg[segment_for(ts)].get(symbol, False)
        for symbol, ts in truth_onsets.items()
    }
    mean_rank = {
        symbol: mean_rank_seg[segment_for(ts)].get(symbol) for symbol, ts in truth_onsets.items()
    }
    mean_first100 = {
        symbol: mean_first100_seg[segment_for(ts)].get(symbol)
        for symbol, ts in truth_onsets.items()
    }
    ka_first = {
        symbol: ka_first_seg[segment_for(ts)].get(symbol) for symbol, ts in truth_onsets.items()
    }
    ka_members = {
        symbol: ka_members_seg[segment_for(ts)].get(symbol, False)
        for symbol, ts in truth_onsets.items()
    }
    # A control is never-crossed when no bar-close on the same path reaches
    # +5% over its prior close.  The cohort's close move alone cannot answer
    # this, so replay the sealed intraday bars rather than imputing.
    never_crossed: list[str] = []
    for control in sealed.controls:
        if control.prior_close is None:
            continue
        control_bars = today.get(control.symbol, ())
        if not control_bars:
            continue
        peak = max(bar.close / control.prior_close - 1 for bar in control_bars)
        if peak < HALF_DECADE:
            never_crossed.append(control.symbol)
    k2_rm = metrics.ranking_metrics(
        truth_onsets,
        k2_rank,
        k2_first100,
        arm="k2",
        universe_at_onset=k2_universe,
    )
    mean_rm = metrics.ranking_metrics(
        truth_onsets,
        mean_rank,
        mean_first100,
        arm="mean",
        universe_at_onset=k2_universe,
    )
    gap_dm = metrics.detection_metrics(
        truth_onsets,
        {symbol: int(cast(int, row["flag_ts"])) for symbol, row in gap_flags.items()},
        arm="gap",
        controls=[c.symbol for c in sealed.controls],
        session_hours=SESSION_HOURS,
        never_crossed=never_crossed,
    )
    entered_before = [
        symbol
        for symbol in truth_onsets
        if (entry := ka_first.get(symbol)) is not None and entry <= truth_onsets[symbol]
    ]
    persisted = [symbol for symbol in entered_before if ka_members.get(symbol, False)]
    persistence_rate = Decimal(len(persisted)) / len(entered_before) if entered_before else ZERO
    arms_report: dict[str, dict[str, object]] = {
        "k2": {
            "status": "MODELED",
            "fidelity": "BAR_CLOSE_U10_SENSITIVITY",
            "metrics": asdict(k2_rm),
            "false_flags_per_symbol_hour": metrics.ranking_false_flags(
                k2_first100,
                controls=[c.symbol for c in sealed.controls],
                session_hours=SESSION_HOURS,
            ),
        },
        "mean": {
            "status": "MODELED",
            "fidelity": "BAR_CLOSE_U10_SENSITIVITY",
            "metrics": asdict(mean_rm),
            "paired_k2": metrics.paired_recall(truth_onsets, k2_rank, mean_rank),
            "false_flags_per_symbol_hour": metrics.ranking_false_flags(
                mean_first100,
                controls=[c.symbol for c in sealed.controls],
                session_hours=SESSION_HOURS,
            ),
        },
        "keepalive": {
            "status": "MODELED",
            "persistence_at_onset": len(persisted),
            "persistence_denominator": len(entered_before),
            "persistence_rate": str(persistence_rate),
            "unconditional_members_at_onset": sum(1 for v in ka_members.values() if v),
            "first_entry": ka_first,
            "note": (
                "qualified fresh admits only; quota top_n enforced; retained only through "
                "an incomplete generation while qualified; 20:00 reset not reached at 11:35"
            ),
        },
        "gap": {
            "status": "MODELED",
            "fidelity": "BAR_CLOSE_U10_SENSITIVITY",
            "mode": "fixed_04:00-04:05_first_open",
            "trigger_mode": {
                "status": "NOT_RUN",
                "reason": "ADR-0024 records no numeric gap/sum(close x volume) thresholds",
            },
            "metrics": asdict(gap_dm),
            **{symbol: row for symbol, row in gap_flags.items()},
        },
        "page": {
            "status": "NOT_RUN",
            "reason": arms.page_arm_status().reason,
            "parameters": dict(arms.page_arm_status().parameters),
        },
        "ofi": {
            "status": "NOT_IN_FROZEN_PROTOCOL",
            "reason": "the frozen K3 section defines (a)-(d)+K/H only; no OFI arm or threshold",
        },
        "catalyst": {
            "status": "NOT_IN_FROZEN_PROTOCOL",
            "reason": "the frozen K3 section defines no EDGAR/catalyst arm or threshold",
        },
        "trade_count": {
            "status": "NOT_IN_FROZEN_PROTOCOL",
            "reason": (
                "the parent brief lists a bar trade-count ratio arm, but the frozen K3 "
                "section defines four arms (a)-(d) plus K/H and no trade-count arm"
            ),
        },
        "hold_flat": {
            "status": "MODELED",
            "reason": "comparator only; no fills, no costs, no returns",
        },
    }
    rows_out = {
        symbol: {
            "onset_ts": truth_onsets.get(symbol),
            "k2_rank_at_onset": k2_rank.get(symbol),
            "k2_first_top100": k2_first100.get(symbol),
            "k2_universe_at_onset": k2_universe.get(symbol),
            "k2_baseline_available": k2_baseline_available.get(symbol),
            "mean_rank_at_onset": mean_rank.get(symbol),
            "mean_first_top100": mean_first100.get(symbol),
            "keepalive_first": ka_first.get(symbol),
            "keepalive_member_at_onset": ka_members.get(symbol),
            "gap_flag_ts": gap_flags.get(symbol, {}).get("flag_ts"),
        }
        for symbol in truth_onsets
    }
    session_sha = cohort.session_list_hash([sealed.session, *prior])
    implementation = {
        "git_head": _git_head(),
        "harness_sha256": _tree_sha(list((ROOT / "research" / "ranking_e2e").glob("*.py"))),
        "ranking_code_sha256": _tree_sha(
            [
                ROOT / "src" / "sextant" / "ranking" / "engine.py",
                ROOT / "src" / "sextant" / "ranking" / "baseline.py",
                ROOT / "src" / "sextant" / "ranking" / "registry.py",
                ROOT / "src" / "sextant" / "ranking" / "window.py",
            ]
        ),
        "percentile": "linear interpolation between closest ranks (Hyndman-Fan type 7)",
        "interval_method": "UNAVAILABLE (not predeclared at the seal)",
    }
    receipts = {day.isoformat(): _day_receipt(bars_root, day) for day in [*prior, sealed.session]}
    items = seal.build(
        section_receipt=receipt,
        cohort_hash=sealed.cohort_hash,
        session_list_sha256=session_sha,
        registry_sha256=_sha256(Path(reg_path)),
        registry_partial_reason=(
            "12 display rows are reviewed; trading/entry freshness ages remain UNAVAILABLE"
        ),
        data_receipts=receipts,
        implementation=implementation,
        custodian_ruling=None,
        other_family_review=None,
    )
    trial_status = "NOT_RUN"
    report: dict[str, object] = {
        "schema": "ranking-e2e.session/1",
        "label": (
            "DEVELOPMENT_TABLE_NOT_A_TRIAL" if receipt is not None else "SYNTHETIC_NOT_VERIFIED"
        ),
        "session": sealed.session.isoformat(),
        "prior_sessions": [day.isoformat() for day in prior],
        "cohort_sha256": sealed.cohort_hash,
        "session_list_sha256": session_sha,
        "cohort_labels": dict(sealed.labels),
        "cohort_excluded": list(sealed.excluded),
        "cohort_counts": sealed.counts,
        "protocol": {
            "doc": (receipt.path.name if receipt else "NOT_VERIFIED"),
            "verified": receipt is not None,
            "k3_sha256": receipt.k3_sha256 if receipt else None,
            "k2_sha256": receipt.k2_sha256 if receipt else None,
        },
        "registry": {
            "sha256": _sha256(Path(reg_path)),
            "params_hash": registry.params_hash,
            "rows": [row.name for row in registry.rows],
        },
        "bars": {"root_name": Path(bars_root).name, "receipts": receipts},
        "fidelity": {
            "primary_estimand": (
                "NOT_RUN (K3.4 trade-tape primary; this table is the bar-close U10 sensitivity)"
            ),
            "table_label": "BAR_CLOSE_U10_SENSITIVITY_NOT_PRIMARY",
            "data": "Alpaca SIP raw 1-minute bars, 04:00-11:35 ET",
            "tick": "one synthetic tick per non-zero-volume minute at bar close",
            "trades_accel": "bar-count proxy; the bar's n field is not a trade-tick stream",
            "freshness_ages": "not applied for a historical replay",
            "rth_end": "11:35 ET data end, not the 16:00 regular close",
        },
        "pit": {
            "membership": "NOT_AVAILABLE",
            "w1_k2": "NOT_RUN",
            "reason": "no dated PIT membership receipt; labels are inherited verbatim",
        },
        "counts": {
            "candidates": len(sealed.candidates),
            "truth": len(sealed.truth),
            "controls": len(sealed.controls),
            "onsets": len(truth_onsets),
            "unobserved_truth": len(sealed.truth) - len(truth_onsets),
            "missing_today_bars": len(missing_today),
            "rankable_at_onset_k2": k2_rm.rankable,
            "rankable_at_onset_mean": mean_rm.rankable,
            "never_crossed_controls": len(never_crossed),
            "baseline_available_at_onset": sum(1 for v in k2_baseline_available.values() if v),
        },
        "strata": {
            name: len(members) for name, members in _strata(truth_onsets, sealed.session).items()
        },
        "strata_metrics": _stratum_metrics(
            truth_onsets, k2_rank, mean_rank, gap_flags, sealed.session
        ),
        "arms": arms_report,
        "rows": rows_out,
        "entry_protection": {
            "status": "UNKNOWN",
            "reason": (
                "the N1 first-leg entry and B protection replay needs PR-3's harness (#83), "
                "which is not on gate; K3.7 forbids a detection-only entry/return claim, so "
                "this leg is UNKNOWN rather than a parallel harness"
            ),
        },
        "trial": {
            "status": trial_status,
            "reason": (
                "only trading arms that run through N1 then B protection write MODELED rows "
                "with their returns; detection-only measurements stay in this hashed report "
                "and never become TrialLog rows (custodian ruling, ADR-0019:26)"
            ),
            "row": None,
            "seal": [asdict(item) for item in items],
        },
    }
    (out_dir / "session.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    return SessionResult(
        sealed.session,
        len(sealed.truth),
        len(sealed.controls),
        truth_onsets,
        rows_out,
        arms_report,
        trial_status,
        None,
        items,
        report,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One-session ranking early-entry e2e development table"
    )
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--bars-root", type=Path, required=True)
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "lanes" / "tradingview" / "k2-ranking.params.json"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--protocol-doc",
        type=Path,
        default=None,
        help="frozen ranking protocol doc; defaults to the checkout's ranking doc",
    )
    parser.add_argument(
        "--no-verify-protocol",
        action="store_true",
        help="synthetic test only: label the report NOT_VERIFIED instead of hashing the protocol",
    )
    args = parser.parse_args(argv)
    result = run_session(
        cohort_path=args.cohort,
        bars_root=args.bars_root,
        reg_path=args.registry,
        out_dir=args.out,
        protocol_doc=args.protocol_doc,
        verify_protocol=not args.no_verify_protocol,
        protocol_required=not args.no_verify_protocol,
    )
    k2 = result.arms["k2"]
    summary = {
        "session": result.session.isoformat(),
        "label": result.report["label"],
        "counts": result.report["counts"],
        "k2_recall": k2["metrics"]["recall"],
        "k2_false_flags_per_symbol_hour": k2["false_flags_per_symbol_hour"],
        "mean_recall": result.arms["mean"]["metrics"]["recall"],
        "gap_detected": result.arms["gap"]["metrics"]["detected"],
        "page": result.arms["page"]["status"],
        "ofi": result.arms["ofi"]["status"],
        "trial_status": result.trial_status,
        "out": str(args.out),
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
