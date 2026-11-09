"""One-session replay: K2 comparator then the frozen arms, streamed.

Fidelity is named, not hidden: one synthetic tick per non-zero-volume minute
at the bar close, a zero-size anchor at the segment start, zero-volume minutes
skipped, one generation per minute, no freshness ages applied.  The K3
section is detection-only, so this runner emits a development table and a
TrialLog reservation whose append is refused until the custodian rules.
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
from typing import Any
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

from . import arms, bars, baseline, cohort, ledger, metrics, protocol, seal

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
    trial_row: dict[str, Any]
    seal: tuple[seal.SealItem, ...]
    report: dict[str, object]


def _anchor_price(segment_bars: Sequence[bars.Bar], start_ns: int, prior_close: Decimal) -> Decimal:
    for bar in segment_bars:
        if bar.ts_ns >= start_ns:
            return bar.open if bar.ts_ns == start_ns else prior_close
    return prior_close


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
    with_gap: bool,
) -> tuple[
    dict[str, int],
    dict[str, int],
    dict[str, int | None],
    dict[str, int],
    dict[str, bool],
    dict[str, dict[str, object]],
]:
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
    gap_flags: dict[str, dict[str, object]] = {}
    gap_arm = arms.GapArm()
    keep = arms.KeepAlive(top_n=int(registry.top_n))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as stream:
        for symbol, blist in segment_bars.items():
            if symbol not in states:
                continue
            anchor_at = segment.start_ns
            anchor = bars.anchor_tick(
                symbol, _anchor_price(blist, anchor_at, refs[symbol].prior_close or ZERO), anchor_at
            )
            states[symbol], _ = advance_mover(
                states[symbol],
                anchor,
                refs[symbol],
                baseline_source,
                segment=segment,
                feed="sip",
                registry=registry,
            )
        for tick_ns in range(segment.start_ns + MINUTE_NS, segment.end_ns + 1, MINUTE_NS):
            rows = []
            for symbol, state in states.items():
                pointer = pointers[symbol]
                blist = segment_bars[symbol]
                while pointer < len(blist) and blist[pointer].close_ns <= tick_ns:
                    if blist[pointer].close_ns == tick_ns:
                        bar = blist[pointer]
                        if with_gap and symbol not in gap_arm._seen:
                            flag = gap_arm.observe(bar, refs[symbol].prior_close)
                            if flag is not None:
                                gap_flags[symbol] = {
                                    "flag_ts": flag.ts_ns,
                                    "price": flag.price,
                                    "gap": flag.gap,
                                    "reason": flag.reason,
                                }
                        state, row = advance_mover(
                            state,
                            bars.tick_from_bar(bar),
                            refs[symbol],
                            baseline_source,
                            segment=segment,
                            feed="sip",
                            registry=registry,
                        )
                        states[symbol] = state
                        if row is not None:
                            rows.append(row)
                    pointer += 1
                pointers[symbol] = pointer
            ranked = rank_movers(rows)
            rank_map = {row.symbol: row.rank for row in ranked}
            qualified = {row.symbol for row in rows if qualifies(row)}
            members = keep.update(rank=rank_map, qualified=qualified)
            for row in ranked:
                if row.rank is not None and row.rank <= 30 and row.symbol not in first30:
                    first30[row.symbol] = tick_ns
                if row.rank is not None and row.rank <= 100 and row.symbol not in first100:
                    first100[row.symbol] = tick_ns
            for symbol in members:
                keepalive_first.setdefault(symbol, tick_ns)
            for symbol in onsets:
                if onsets[symbol] == tick_ns:
                    rank_at_onset[symbol] = rank_map.get(symbol)
                    members_at_onset[symbol] = symbol in members
            stream.write(
                json.dumps(
                    {
                        "ts_ns": tick_ns,
                        "segment": segment.name,
                        "arm": arm_name,
                        "top30": [row.symbol for row in ranked[:30]],
                        "top100": [row.symbol for row in ranked[:100]],
                        "members": sorted(members),
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
    return first30, first100, rank_at_onset, keepalive_first, members_at_onset, gap_flags


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
    for candidate in sealed.candidates:
        if candidate.prior_close is None or candidate.symbol not in today:
            continue
        refs[candidate.symbol] = ReferencePrices(
            candidate.prior_close,
            _at(prior[-1], 16, 0),
            "official completed regular close carried by the sealed cohort (last_close)",
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

    k2_first30: dict[str, int] = {}
    k2_first100: dict[str, int] = {}
    k2_rank: dict[str, int | None] = {}
    ka_first: dict[str, int] = {}
    ka_members_at_onset: dict[str, bool] = {}
    gap_flags: dict[str, dict[str, object]] = {}
    mean_first30: dict[str, int] = {}
    mean_first100: dict[str, int] = {}
    mean_rank: dict[str, int | None] = {}
    for segment, minutes, median_base, mean_base, tag in (
        (pre, PRE_MINUTES, median_pre, mean_pre, "pre"),
        (rth, RTH_MINUTES, median_rth, mean_rth, "rth"),
    ):
        f30, f100, rank, ka, m_at_onset, gaps = _replay_arm(
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
            with_gap=True,
        )
        for symbol, ts in f30.items():
            k2_first30[symbol] = min(ts, k2_first30.get(symbol, ts))
        for symbol, ts in f100.items():
            k2_first100[symbol] = min(ts, k2_first100.get(symbol, ts))
        for symbol, ts in ka.items():
            ka_first[symbol] = min(ts, ka_first.get(symbol, ts))
        k2_rank.update(rank)
        ka_members_at_onset.update(m_at_onset)
        gap_flags.update(gaps)
        f30, f100, rank, _, _, _ = _replay_arm(
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
            with_gap=False,
        )
        for symbol, ts in f30.items():
            mean_first30[symbol] = min(ts, mean_first30.get(symbol, ts))
        for symbol, ts in f100.items():
            mean_first100[symbol] = min(ts, mean_first100.get(symbol, ts))
        mean_rank.update(rank)

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
        if peak < Decimal("0.05"):
            never_crossed.append(control.symbol)
    k2_rm = metrics.ranking_metrics(truth_onsets, k2_rank, k2_first100, arm="k2")
    mean_rm = metrics.ranking_metrics(truth_onsets, mean_rank, mean_first100, arm="mean")
    gap_dm = metrics.detection_metrics(
        truth_onsets,
        {symbol: int(row["flag_ts"]) for symbol, row in gap_flags.items()},
        arm="gap",
        controls=[c.symbol for c in sealed.controls],
        session_hours=SESSION_HOURS,
        never_crossed=never_crossed,
    )
    keep_leads = [
        truth_onsets[symbol] - ka_first[symbol] for symbol in truth_onsets if symbol in ka_first
    ]
    member_at_onset = sum(1 for symbol in truth_onsets if ka_members_at_onset.get(symbol, False))
    arms_report: dict[str, dict[str, object]] = {
        "k2": {
            "status": "MODELED",
            "metrics": asdict(k2_rm),
            "false_flags_per_symbol_hour": metrics.ranking_false_flags(
                k2_first100,
                controls=[c.symbol for c in sealed.controls],
                session_hours=SESSION_HOURS,
            ),
        },
        "mean": {
            "status": "MODELED",
            "metrics": asdict(mean_rm),
            "false_flags_per_symbol_hour": metrics.ranking_false_flags(
                mean_first100,
                controls=[c.symbol for c in sealed.controls],
                session_hours=SESSION_HOURS,
            ),
        },
        "keepalive": {
            "status": "MODELED",
            "persistence_at_onset": member_at_onset,
            "p50_lead_s": metrics.percentile(keep_leads, 50),
            "p90_lead_s": metrics.percentile(keep_leads, 90),
            "first_entry": ka_first,
            "note": (
                "retention only through uncomputable inputs; "
                "rank>top_n with complete inputs is churn"
            ),
        },
        "gap": {
            "status": "MODELED",
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
            "mean_rank_at_onset": mean_rank.get(symbol),
            "mean_first_top100": mean_first100.get(symbol),
            "keepalive_first": ka_first.get(symbol),
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
    trial_status = "NOT_RUN" if not seal.trial_ready(items) else "READY"
    trial_row = ledger.detection_row(
        arm_id="ranking_e2e.development",
        arm_run_id=f"{sealed.session.isoformat()}-{implementation['git_head'][:12]}",
        implementation_sha=implementation["git_head"],
        block_set_id=sealed.session.isoformat(),
        session_list_sha256=session_sha,
    )
    report: dict[str, object] = {
        "schema": "ranking-e2e.session/1",
        "label": "DEVELOPMENT_TABLE_NOT_A_TRIAL",
        "session": sealed.session.isoformat(),
        "prior_sessions": [day.isoformat() for day in prior],
        "cohort_sha256": sealed.cohort_hash,
        "session_list_sha256": session_sha,
        "protocol": {
            "doc": (receipt.path.name if receipt else "NOT_VERIFIED"),
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
            "data": "Alpaca SIP raw 1-minute bars, 04:00-11:35 ET",
            "tick": "one synthetic tick per non-zero-volume minute at bar close",
            "trades_accel": "bar-count proxy; the bar's n field is not a trade-tick stream",
            "freshness_ages": "not applied for a historical replay",
            "rth_end": "11:35 ET data end, not the 16:00 regular close",
        },
        "counts": {
            "candidates": len(sealed.candidates),
            "truth": len(sealed.truth),
            "controls": len(sealed.controls),
            "onsets": len(truth_onsets),
            "rankable_at_onset_k2": k2_rm.rankable,
            "rankable_at_onset_mean": mean_rm.rankable,
            "never_crossed_controls": len(never_crossed),
        },
        "strata": {
            name: len(members) for name, members in _strata(truth_onsets, sealed.session).items()
        },
        "arms": arms_report,
        "rows": rows_out,
        "trial": {
            "status": trial_status,
            "row": trial_row,
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
        trial_row,
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
        help="frozen ranking protocol doc; when given, the K3 and K2 section hashes are verified",
    )
    args = parser.parse_args(argv)
    result = run_session(
        cohort_path=args.cohort,
        bars_root=args.bars_root,
        reg_path=args.registry,
        out_dir=args.out,
        protocol_doc=args.protocol_doc,
        verify_protocol=args.protocol_doc is not None,
        protocol_required=args.protocol_doc is not None,
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
