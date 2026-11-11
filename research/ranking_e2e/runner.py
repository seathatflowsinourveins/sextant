"""One-session replay: K2 comparator then the frozen arms, streamed.

Fidelity is named, not hidden: one synthetic tick per non-zero-volume minute
at the bar close, zero-volume minutes skipped, one generation per minute, no
freshness ages applied.  No print is fabricated.  A segment's dollar-volume
prefix is covered only by an explicit recording receipt (the fetch window and
the recorded day's hash), which covers every recorded symbol from each segment
start alike; without it every name stays ``segment_prefix_unknown`` and the
ranking arms are NOT_ESTIMABLE.  The K3 section is detection-only, so this
runner emits a development table and never a TrialLog row.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
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
PREFIX_SCHEMA = "ranking-e2e.prefix-receipt/1"
NOT_ESTIMABLE = (
    "segment_prefix_unknown for every name: no prefix receipt binds the recording window, so "
    "dvol_ratio and score stay unknown and no generation can rank (K2 section 2); ranking "
    "reads are NOT_ESTIMABLE, never zero"
)


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


def _git_status() -> str:
    """Uncommitted or untracked paths; empty only for a clean checkout."""
    return subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def _day_receipt(root: Path, day: date) -> str:
    directory = Path(root) / "1min" / day.isoformat()
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.json")):
        digest.update(path.name.encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class PrefixReceipt:
    """The recording's own coverage: every requested symbol fetched over one window."""

    sha256: str
    window_et: tuple[str, str]
    window_start_ns: int
    window_end_ns: int
    data_sha256: str
    source: str

    def covers(self, segment: Segment) -> bool:
        # The engine's segment end is one nanosecond past the last bar close.
        return self.window_start_ns <= segment.start_ns and segment.end_ns - 1 <= self.window_end_ns


def _hhmm(text: str) -> tuple[int, int]:
    hour, minute = text.split(":")
    return int(hour), int(minute)


def load_prefix_receipt(path: Path, *, session: date, bars_root: Path) -> PrefixReceipt:
    """Read and bind a prefix receipt to the exact recorded bar files of the session.

    The receipt states the window the recording requested for every symbol and
    the hash of the recorded day it describes; a receipt for other bytes, another
    session or another feed is refused rather than trusted.
    """
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    if data.get("schema") != PREFIX_SCHEMA:
        raise ValueError(f"unsupported prefix receipt schema: {data.get('schema')!r}")
    if data.get("session") != session.isoformat():
        raise ValueError("prefix receipt is for another session")
    if data.get("feed") != "sip" or data.get("timeframe") != "1Min":
        raise ValueError("prefix receipt must describe the SIP 1-minute recording")
    source = str(data.get("source") or "").strip()
    if not source:
        raise ValueError("prefix receipt needs its source")
    window = (str(data["window_et"]["start"]), str(data["window_et"]["end"]))
    actual = _day_receipt(bars_root, session)
    if data.get("data_sha256") != actual:
        raise ValueError("prefix receipt does not bind the recorded bars: data_sha256 differs")
    return PrefixReceipt(
        hashlib.sha256(raw).hexdigest(),
        window,
        _at(session, *_hhmm(window[0])),
        _at(session, *_hhmm(window[1])),
        actual,
        source,
    )


def _prior_curves(
    root: Path,
    prior: Sequence[date],
    symbols: Sequence[str],
    *,
    start: tuple[int, int],
    minutes: int,
) -> dict[str, tuple[tuple[Decimal, ...], ...]]:
    per_symbol: dict[str, list[tuple[Decimal, ...]]] = {symbol: [] for symbol in symbols}
    for day in prior:
        requested: set[str] = set()
        day_bars = bars.load_raw_day(root, day, symbols=set(symbols), requested_out=requested)
        covered = [symbol for symbol in symbols if symbol in requested]
        curves = (
            baseline.cumulative_curves(day_bars, covered, _at(day, *start), minutes)
            if covered
            else {}
        )
        for symbol in covered:
            per_symbol[symbol].append(curves[symbol])
        del day_bars, curves, requested
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


@dataclass(slots=True)
class SegmentReplay:
    """One arm's replay of one segment, read from its published generations."""

    covered: bool
    first30: dict[str, int] = field(default_factory=dict)
    first100: dict[str, int] = field(default_factory=dict)
    rank_at_onset: dict[str, int | None] = field(default_factory=dict)
    universe_at_onset: dict[str, int] = field(default_factory=dict)
    onset_state: dict[str, dict[str, object]] = field(default_factory=dict)
    member_first: dict[str, int] = field(default_factory=dict)
    member_at_onset: dict[str, bool] = field(default_factory=dict)
    ever_member: set[str] = field(default_factory=set)
    retained_member_generations: int = 0
    gap_flags: dict[str, dict[str, object]] = field(default_factory=dict)
    generations: int = 0


def _onset_record(state: MoverState | None) -> dict[str, object]:
    """What the arm knew about a name at its onset: its latest row, ranked or not.

    Baseline availability is the arm's own normal at that offset existing and
    above zero, read from the row the engine computed, never from whether the
    name was ranked; a zero normal is unavailable (K3.5 (b), K3.6).
    """
    row = None if state is None else state.latest
    if row is None:
        return {
            "computable": False,
            "baseline_available": False,
            "baseline_reason": "no_row_at_onset",
            "unknown_reasons": ["no_row_at_onset"],
        }
    normal = row.observations.get("baseline_dollar_volume")
    available = normal is not None and normal > 0
    reason = None
    if not available:
        reason = "baseline_unknown" if normal is None else "baseline_zero_dollar_volume"
    return {
        "computable": row.score is not None and row.trades_accel is not None,
        "baseline_available": available,
        "baseline_reason": reason,
        "baseline_sessions": row.observations.get("baseline_sessions"),
        "unknown_reasons": [str(item) for item in row.observations.get("unknown_reasons", ())],
    }


def _replay_arm(
    *,
    arm_name: str,
    segment: Segment,
    symbols: Sequence[str],
    today: Mapping[str, Sequence[bars.Bar]],
    refs: Mapping[str, ReferencePrices],
    baseline_source: baseline.CurveBaseline,
    registry: Registry,
    onsets: Mapping[str, int],
    out_path: Path,
    covered: bool,
    gap_arm: arms.GapArm | None = None,
    keep: arms.KeepAlive | None = None,
    publish_interval_ns: int = NS,
) -> SegmentReplay:
    """Replay one segment and publish full K2 generations.

    Every generation ranks the latest computable row of every symbol in the
    segment, not only the symbols whose bar closed in that minute (K2 section
    5); a symbol with no bar in the minute keeps its previous row.  No print is
    synthesized: each state starts at its first real bar, and the segment's
    dollar-volume prefix is covered only when ``covered`` says the recording
    receipt spans the segment, for every symbol alike.  Ranks, membership and
    onset reads come from the latest published generation at or before the tick.
    """
    segment_bars = {
        symbol: tuple(
            bar for bar in today.get(symbol, ()) if segment.start_ns <= bar.ts_ns < segment.end_ns
        )
        for symbol in symbols
    }
    states = {
        symbol: MoverState(segment_covered=covered)
        for symbol in symbols
        if segment_bars[symbol] and symbol in refs
    }
    pointers = {symbol: 0 for symbol in states}
    out = SegmentReplay(covered=covered)
    rank_map: dict[str, int | None] = {}
    members: set[str] = set()
    universe = 0
    last_publish: int | None = None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as stream:
        for tick_ns in range(segment.start_ns + MINUTE_NS, segment.end_ns + 1, MINUTE_NS):
            for symbol, state in states.items():
                pointer = pointers[symbol]
                blist = segment_bars[symbol]
                while pointer < len(blist) and blist[pointer].close_ns <= tick_ns:
                    if blist[pointer].close_ns == tick_ns:
                        bar = blist[pointer]
                        if gap_arm is not None:
                            flag = gap_arm.observe(bar, refs[symbol].prior_close)
                            if flag is not None and symbol not in out.gap_flags:
                                out.gap_flags[symbol] = {
                                    "flag_ts": flag.ts_ns,
                                    "price": flag.price,
                                    "gap": flag.gap,
                                    "reason": flag.reason,
                                }
                        state, _ = advance_mover(
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
            if last_publish is None or tick_ns - last_publish >= publish_interval_ns:
                ranked = rank_movers(
                    state.latest for state in states.values() if state.latest is not None
                )
                last_publish = tick_ns
                out.generations += 1
                rank_map = {row.symbol: row.rank for row in ranked}
                universe = len(ranked)
                retained: frozenset[str] = frozenset()
                if keep is not None:
                    members = keep.update(ranked, qualifies=qualifies)
                    keep.note_admission(members, tick_ns)
                    retained = keep.retained
                    out.retained_member_generations += len(retained)
                    out.ever_member |= members
                for row in ranked:
                    if row.rank is not None and row.rank <= 30:
                        out.first30.setdefault(row.symbol, tick_ns)
                    if row.rank is not None and row.rank <= 100:
                        out.first100.setdefault(row.symbol, tick_ns)
                for symbol in members:
                    out.member_first.setdefault(symbol, tick_ns)
                stream.write(
                    json.dumps(
                        {
                            "ts_ns": tick_ns,
                            "segment": segment.name,
                            "arm": arm_name,
                            "universe": universe,
                            "top30": [row.symbol for row in ranked[:30]],
                            "top100": [row.symbol for row in ranked[:100]],
                            "members": sorted(members),
                            "retained": sorted(retained),
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                )
            for symbol, onset in onsets.items():
                if onset != tick_ns:
                    continue
                out.rank_at_onset[symbol] = rank_map.get(symbol)
                out.universe_at_onset[symbol] = universe
                out.member_at_onset[symbol] = symbol in members
                out.onset_state[symbol] = _onset_record(states.get(symbol))
    return out


def _coverage_hours(
    today: Mapping[str, Sequence[bars.Bar]], symbols: Sequence[str], segments: Sequence[Segment]
) -> dict[str, Decimal]:
    """Each symbol's row hours: from its first replayed bar close to each segment end.

    A row exists from the first bar the replay processes in a segment (closed
    by the segment's last tick) until the segment ends; a symbol with no such
    bar has no row there and contributes no hours (K2 section 6 counts no-row
    names apart).
    """
    hours: dict[str, Decimal] = {}
    for symbol in symbols:
        total = ZERO
        for segment in segments:
            closes = [
                bar.close_ns
                for bar in today.get(symbol, ())
                if segment.start_ns <= bar.ts_ns and bar.close_ns < segment.end_ns
            ]
            if closes:
                total += Decimal(segment.end_ns - 1 - min(closes)) / NS / 3600
        hours[symbol] = total
    return hours


def _strata(
    onsets: Mapping[str, int], segments: Mapping[str, str], session: date
) -> dict[str, list[str]]:
    """Opening-minute strata inside each onset's own segment.

    A PRE onset is in its first 30 minutes (onset before 04:30) or the rest of
    PRE (through its 09:30 close); an RTH onset in its first 30 minutes (before
    10:00) or the rest of the replay (through 11:35).  Every onset in the
    replay window falls in exactly one stratum.
    """
    out: dict[str, list[str]] = {
        "pre_open_30": [],
        "pre_rest": [],
        "rth_open_30": [],
        "rth_rest": [],
    }
    for symbol, onset in onsets.items():
        if segments[symbol] == "PRE":
            name = "pre_open_30" if onset < _at(session, 4, 30) else "pre_rest"
        else:
            name = "rth_open_30" if onset < _at(session, 10, 0) else "rth_rest"
        out[name].append(symbol)
    return out


def _stratum_metrics(
    onsets: Mapping[str, int],
    segments: Mapping[str, str],
    k2_rank: Mapping[str, int | None],
    mean_rank: Mapping[str, int | None],
    gap_flags: Mapping[str, Mapping[str, object]],
    session: date,
    *,
    ranking_estimable: bool,
) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for name, members in _strata(onsets, segments, session).items():
        total = len(members)

        def recall(
            rank_map: Mapping[str, int | None],
            members: Sequence[str] = members,
            total: int = total,
        ) -> dict[int, str | None] | str:
            if not ranking_estimable:
                return "NOT_ESTIMABLE"
            out_k: dict[int, str | None] = {}
            for k in (30, 100):
                hits = sum(
                    1
                    for symbol in members
                    if (place := rank_map.get(symbol)) is not None and place <= k
                )
                out_k[k] = str(Decimal(hits) / total) if total else None
            return out_k

        flagged = [symbol for symbol in members if symbol in gap_flags]
        out[name] = {
            "truth": total,
            "k2_recall": recall(k2_rank),
            "mean_recall": recall(mean_rank),
            "gap_sub_arm_at_onset": sum(
                1
                for symbol in flagged
                if int(cast(int, gap_flags[symbol]["flag_ts"])) <= onsets[symbol]
            ),
            "gap_sub_arm_ever": len(flagged),
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
    prefix_receipt: Path | None = None,
) -> SessionResult:
    sealed = cohort.load_cohort(Path(cohort_path))
    registry = load_registry(Path(reg_path))
    receipt = None
    if verify_protocol:
        doc = Path(protocol_doc or ROOT / "docs" / "research" / "2026-11-06-ranking.md")
        receipt = protocol.verify_protocol(doc)
        if protocol_required:
            receipt.require_frozen()
    # The report binds the head it ran; a verified run from a dirty tree would
    # bind bytes no commit holds (round-2 provenance finding), so it is refused.
    dirty = _git_status()
    if receipt is not None and dirty.strip():
        raise RuntimeError(
            "refusing a verified run from a dirty tree: commit first so the report binds "
            "the head it ran (git status --porcelain is not empty)"
        )
    git_head = _git_head()
    prefix = (
        load_prefix_receipt(Path(prefix_receipt), session=sealed.session, bars_root=Path(bars_root))
        if prefix_receipt is not None
        else None
    )
    symbols = sealed.symbols
    prior = sealed.prior_sessions
    today = bars.load_raw_day(Path(bars_root), sealed.session, symbols=set(symbols))
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
    # Price-path labels read only the replayed path: bars from 04:00 that have
    # closed by 11:35 (K3.4's window).  The recording runs to 11:40, but a later
    # bar is never replayed, so it can neither set an onset nor move a control.
    replayed = {
        symbol: tuple(
            bar for bar in rows if pre.start_ns <= bar.ts_ns and bar.close_ns < rth.end_ns
        )
        for symbol, rows in today.items()
    }
    # An onset keeps its bar's own segment: the 09:29 bar is a PRE bar whose
    # close at 09:30 is judged by PRE's 09:30 generation, never by RTH, whose
    # first generation is 09:31 (K2 section 5: rank in the onset's segment).
    onsets: dict[str, int] = {}
    onset_segment: dict[str, str] = {}
    for candidate in sealed.truth:
        if candidate.prior_close is None:
            continue
        threshold = candidate.prior_close * (1 + HALF_DECADE)
        for bar in replayed.get(candidate.symbol, ()):
            if bar.close >= threshold:
                onsets[candidate.symbol] = bar.close_ns
                onset_segment[candidate.symbol] = pre.name if bar.ts_ns < rth.start_ns else rth.name
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
    if prefix is not None:
        for segment in (pre, rth):
            if not prefix.covers(segment):
                raise ValueError(
                    f"prefix receipt window {prefix.window_et} does not cover {segment.name}"
                )
    covered = prefix is not None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    gap_arm = arms.GapArm(
        window_start_ns=_at(sealed.session, 4, 0),
        window_end_ns=_at(sealed.session, 4, 5),
    )
    keep = arms.KeepAlive(top_n=int(registry.top_n))
    publish_interval_ns = int(registry.publish_min_interval_s) * NS
    k2: dict[str, SegmentReplay] = {}
    mean: dict[str, SegmentReplay] = {}
    for segment, median_base, mean_base, tag in (
        (pre, median_pre, mean_pre, "pre"),
        (rth, median_rth, mean_rth, "rth"),
    ):
        k2[segment.name] = _replay_arm(
            arm_name="k2",
            segment=segment,
            symbols=list(refs),
            today=today,
            refs=refs,
            baseline_source=median_base,
            registry=registry,
            onsets=onsets,
            out_path=out_dir / f"generations-k2-{tag}.jsonl",
            covered=covered,
            gap_arm=gap_arm,
            keep=keep,
            publish_interval_ns=publish_interval_ns,
        )
        mean[segment.name] = _replay_arm(
            arm_name="mean",
            segment=segment,
            symbols=list(refs),
            today=today,
            refs=refs,
            baseline_source=mean_base,
            registry=registry,
            onsets=onsets,
            out_path=out_dir / f"generations-mean-{tag}.jsonl",
            covered=covered,
            publish_interval_ns=publish_interval_ns,
        )
    gap_flags: dict[str, dict[str, object]] = {}
    for replay in k2.values():
        for symbol, flag in replay.gap_flags.items():
            gap_flags.setdefault(symbol, flag)

    # One K2 generation stream for readers that want the frozen comparator as a
    # single time-ordered file; per-arm and per-segment streams stay beside it.
    merged = out_dir / "generations.jsonl"
    with merged.open("wb") as dst:
        for tag in ("pre", "rth"):
            part = out_dir / f"generations-k2-{tag}.jsonl"
            if part.exists():
                dst.write(part.read_bytes())

    truth_symbols = {c.symbol for c in sealed.truth}
    truth_onsets = {symbol: ts for symbol, ts in onsets.items() if symbol in truth_symbols}

    def own(replays: Mapping[str, SegmentReplay], symbol: str) -> SegmentReplay:
        return replays[onset_segment[symbol]]

    no_row = _onset_record(None)
    k2_rank = {s: own(k2, s).rank_at_onset.get(s) for s in truth_onsets}
    k2_first100 = {s: own(k2, s).first100.get(s) for s in truth_onsets}
    k2_universe = {s: own(k2, s).universe_at_onset.get(s) for s in truth_onsets}
    k2_state = {s: own(k2, s).onset_state.get(s, no_row) for s in truth_onsets}
    mean_rank = {s: own(mean, s).rank_at_onset.get(s) for s in truth_onsets}
    mean_first100 = {s: own(mean, s).first100.get(s) for s in truth_onsets}
    mean_universe = {s: own(mean, s).universe_at_onset.get(s) for s in truth_onsets}
    mean_state = {s: own(mean, s).onset_state.get(s, no_row) for s in truth_onsets}
    # One admission clock for the whole session: a PRE admit is not reset by
    # RTH's first generation (only the 20:00 reset clears it).
    ka_first = {s: keep.first_member.get(s) for s in truth_onsets}
    ka_members = {s: own(k2, s).member_at_onset.get(s, False) for s in truth_onsets}
    # A control is never-crossed when no bar-close on the replayed path reaches
    # +5% over its prior close.  The cohort's close move alone cannot answer
    # this, so read the sealed intraday bars of the window rather than imputing.
    never_crossed: list[str] = []
    for control in sealed.controls:
        if control.prior_close is None:
            continue
        control_bars = replayed.get(control.symbol, ())
        if not control_bars:
            continue
        peak = max(bar.close / control.prior_close - 1 for bar in control_bars)
        if peak < HALF_DECADE:
            never_crossed.append(control.symbol)
    controls = [c.symbol for c in sealed.controls]
    coverage = _coverage_hours(today, controls, (pre, rth))

    def flag_table(flagged: set[str], endpoint: str) -> dict[str, object]:
        return metrics.false_flag_table(
            flagged,
            controls=controls,
            never_crossed=never_crossed,
            session_hours=SESSION_HOURS,
            coverage_hours=coverage,
            endpoint=endpoint,
        )

    top100_endpoint = (
        "control ever in the top 100 of a published PRE or RTH generation, 04:00-11:35 ET "
        "(development endpoint; K2 section 6 matched-cell occupancy is not computed here)"
    )
    k2_flags = flag_table({s for r in k2.values() for s in r.first100}, top100_endpoint)
    mean_flags = flag_table({s for r in mean.values() for s in r.first100}, top100_endpoint)
    keep_flags = flag_table(
        {s for r in k2.values() for s in r.ever_member},
        "control ever a keep-alive member of a published PRE or RTH generation, 04:00-11:35 ET",
    )
    k2_rm = metrics.ranking_metrics(
        truth_onsets,
        k2_rank,
        k2_first100,
        arm="k2",
        universe_at_onset={s: u for s, u in k2_universe.items() if u is not None},
    )
    mean_rm = metrics.ranking_metrics(
        truth_onsets,
        mean_rank,
        mean_first100,
        arm="mean",
        universe_at_onset={s: u for s, u in mean_universe.items() if u is not None},
    )
    gap_dm = metrics.detection_metrics(
        truth_onsets,
        {symbol: int(cast(int, row["flag_ts"])) for symbol, row in gap_flags.items()},
        arm=arms.GAP_SUB_ARM,
        controls=controls,
        session_hours=SESSION_HOURS,
        never_crossed=never_crossed,
        coverage_hours=coverage,
        endpoint="control with a first-open gap flag in the 04:00-04:05 ET window",
    )
    k2_available = metrics.baseline_availability(truth_onsets, k2_state)
    mean_available = metrics.baseline_availability(truth_onsets, mean_state)

    def ranking_arm(
        rm: metrics.RankingMetrics,
        flags: dict[str, object],
        available: dict[str, object],
        **extra: object,
    ) -> dict[str, object]:
        if not covered:
            return {
                "status": "NOT_ESTIMABLE",
                "reason": NOT_ESTIMABLE,
                "baseline_available_at_onset": available,
            }
        all_controls = cast(dict[str, object], flags["all_controls"])
        return {
            "status": "MODELED",
            "fidelity": "BAR_CLOSE_U10_SENSITIVITY",
            "metrics": asdict(rm),
            "baseline_available_at_onset": available,
            "false_flags": flags,
            "false_flags_per_symbol_hour": all_controls["per_symbol_hour_session"],
            **extra,
        }

    keep_report: dict[str, object] = (
        {
            "status": "MODELED",
            **metrics.persistence(truth_onsets, ka_first, ka_members),
            "first_entry": ka_first,
            "retained_member_generations": sum(r.retained_member_generations for r in k2.values()),
            "false_flags": keep_flags,
            "note": (
                "qualified top-N fresh admits; an uncomputable member is retained while its "
                "last computable row qualified; fresh first, then retained in K2 order up to "
                "top_n; first admission shared by PRE and RTH until the 20:00 reset; first "
                "entry strictly before tau; 20:00 reset not reached at 11:35"
            ),
        }
        if covered
        else {"status": "NOT_ESTIMABLE", "reason": NOT_ESTIMABLE}
    )
    arms_report: dict[str, dict[str, object]] = {
        "k2": ranking_arm(k2_rm, k2_flags, k2_available),
        "mean": ranking_arm(
            mean_rm,
            mean_flags,
            mean_available,
            paired_k2=metrics.paired_recall(truth_onsets, k2_rank, mean_rank),
        ),
        "keepalive": keep_report,
        "gap": arms.gap_rule_status(),
        arms.GAP_SUB_ARM: {
            "status": "DEVELOPMENT_SUB_ARM",
            "frozen_arm": "a: NOT_RUN as recorded (arms.gap)",
            "definition": (
                "first open in the fixed 04:00-04:05 ET window at least 1% over the official "
                "prior close; no ADV20, candidate-ADV, unknown-ADV or prior-post exclusion"
            ),
            "fidelity": "BAR_CLOSE_U10_SENSITIVITY",
            "flag_clock": "bar start of the first in-window bar; onset tau is a bar close",
            "metrics": asdict(gap_dm),
            "flags": gap_flags,
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
            "onset_ts": tau,
            "onset_segment": onset_segment[symbol],
            "prefix_covered": covered,
            "k2_rank_at_onset": k2_rank.get(symbol),
            "k2_first_top100": k2_first100.get(symbol),
            "k2_universe_at_onset": k2_universe.get(symbol),
            "k2_computable_at_onset": k2_state[symbol]["computable"],
            "k2_baseline_available": k2_state[symbol]["baseline_available"],
            "k2_baseline_sessions": k2_state[symbol].get("baseline_sessions"),
            "k2_unknown_reasons": k2_state[symbol]["unknown_reasons"],
            "mean_rank_at_onset": mean_rank.get(symbol),
            "mean_first_top100": mean_first100.get(symbol),
            "mean_universe_at_onset": mean_universe.get(symbol),
            "mean_computable_at_onset": mean_state[symbol]["computable"],
            "mean_baseline_available": mean_state[symbol]["baseline_available"],
            "mean_baseline_sessions": mean_state[symbol].get("baseline_sessions"),
            "mean_unknown_reasons": mean_state[symbol]["unknown_reasons"],
            "keepalive_first": ka_first.get(symbol),
            "keepalive_member_at_onset": ka_members.get(symbol),
            "gap_sub_arm_flag_ts": gap_flags.get(symbol, {}).get("flag_ts"),
        }
        for symbol, tau in truth_onsets.items()
    }
    session_sha = cohort.session_list_hash([sealed.session, *prior])
    implementation: dict[str, object] = {
        "git_head": git_head,
        "tree_clean": not dirty.strip(),
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
        implementation={key: str(value) for key, value in implementation.items()},
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
        "implementation": implementation,
        "registry": {
            "sha256": _sha256(Path(reg_path)),
            "params_hash": registry.params_hash,
            "rows": [row.name for row in registry.rows],
        },
        "bars": {"root_name": Path(bars_root).name, "receipts": receipts},
        "prefix": (
            {
                "status": "RECEIPTED",
                "sha256": prefix.sha256,
                "window_et": list(prefix.window_et),
                "data_sha256": prefix.data_sha256,
                "source": prefix.source,
                "rule": (
                    "the recording requested every symbol over this window, so every symbol "
                    "with recorded bars is covered from each segment start alike; no "
                    "synthetic print"
                ),
            }
            if prefix is not None
            else {"status": "ABSENT", "reason": NOT_ESTIMABLE}
        ),
        "fidelity": {
            "primary_estimand": (
                "NOT_RUN (K3.4 trade-tape primary; this table is the bar-close U10 sensitivity)"
            ),
            "table_label": "BAR_CLOSE_U10_SENSITIVITY_NOT_PRIMARY",
            "data": "Alpaca SIP raw 1-minute bars, 04:00-11:35 ET",
            "tick": "one synthetic tick per non-zero-volume minute at bar close; no anchor tick",
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
            "rankable_at_onset_k2": k2_rm.rankable if covered else None,
            "rankable_at_onset_mean": mean_rm.rankable if covered else None,
            "never_crossed_controls": len(never_crossed),
            "baseline_available_at_onset": k2_available["available"],
            "baseline_available_at_onset_mean": mean_available["available"],
        },
        "controls": {
            "never_crossed": never_crossed,
            "coverage_hours": {symbol: str(hours) for symbol, hours in coverage.items()},
            "denominator_status": metrics.DENOMINATOR_STATUS,
        },
        "strata": {
            name: len(members)
            for name, members in _strata(truth_onsets, onset_segment, sealed.session).items()
        },
        "strata_metrics": _stratum_metrics(
            truth_onsets,
            onset_segment,
            k2_rank,
            mean_rank,
            gap_flags,
            sealed.session,
            ranking_estimable=covered,
        ),
        "arms": arms_report,
        "rows": rows_out,
        "entry_protection": {
            "status": "NOT_RUN",
            "reason": (
                "#83 on gate carries the N1 first-leg picks and B's protection replay; wiring "
                "these arms into it is a separate successor task under its own frozen, costed "
                "protocol citing the K3 hash (K3.7), so this detection harness builds no entry leg"
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
        "--prefix-receipt",
        type=Path,
        default=None,
        help=(
            "the recording's prefix receipt (window and day hash); without it every segment "
            "prefix stays unknown and the ranking arms are NOT_ESTIMABLE"
        ),
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
        prefix_receipt=args.prefix_receipt,
    )
    found = result.arms
    summary = {
        "session": result.session.isoformat(),
        "label": result.report["label"],
        "prefix": result.report["prefix"]["status"],
        "counts": result.report["counts"],
        "k2": found["k2"]["status"],
        "k2_recall": found["k2"].get("metrics", {}).get("recall"),
        "k2_false_flags_per_symbol_hour": found["k2"].get("false_flags_per_symbol_hour"),
        "mean_recall": found["mean"].get("metrics", {}).get("recall"),
        "keepalive_persistence": found["keepalive"].get("persistence_rate"),
        "arm_a": found["gap"]["status"],
        "gap_sub_arm_recall_at_onset": found[arms.GAP_SUB_ARM]["metrics"]["recall_at_onset"],
        "page": found["page"]["status"],
        "ofi": found["ofi"]["status"],
        "trial_status": result.trial_status,
        "out": str(args.out),
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
