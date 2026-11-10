"""Predeclared metrics: recall at onset, censoring, latency and false flags.

Percentile convention: linear interpolation between closest ranks (Hyndman-
Fan type 7), named here because the K3 seal (item 6) requires the convention
to be stated before a trial.  No interval method was predeclared for the pair
contrasts, so inference stays UNAVAILABLE rather than invented.

K3.2 timing is signed as ``flag - onset``: a negative value is an early flag.
``censored`` counts only a name with no flag at all; a flag after onset is a
detected-late name and is reported beside the latency, never folded into
censoring.  Recall at onset (K3.2 (ii)) counts only a first flag at or before
``tau``; ``ever_detected`` is the separate share flagged at any time.  The
+/-60/120/300 s windows are K3.9's predeclared counts.  An empty denominator
is undefined (``None``), never a zero.

False flags per symbol-hour (K3.2 (iii)) are reported over two denominators,
both development-table choices until the U4 seal binds the one shared control
denominator (K3.3): every control charged the replay window, and each
control's own row hours (first bar close to each segment's end).  All-control
and never-crossed rates stay separate (K3.9).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

NS = 1_000_000_000
ZERO = Decimal(0)
WINDOWS_S = (60, 120, 300)
DENOMINATOR_STATUS = "DEVELOPMENT_CHOICE_PENDING_U4_SEAL"
DENOMINATORS = (
    "session: every control charged the whole replay window; coverage: each control's own "
    "row hours, from its first bar close to each segment's end; both are development-table "
    "choices until the U4 seal binds the one shared symbol-hour denominator (K3.3)"
)


def _seconds(value: Decimal | None) -> Decimal | None:
    """Convert a nanosecond difference to the seconds named by the metric."""
    return None if value is None else value / Decimal(NS)


def _share(count: int, total: int) -> Decimal | None:
    return Decimal(count) / total if total else None


def _rate(count: int, denominator: Decimal) -> str | None:
    """A per-symbol-hour rate as text; zero prints as ``0``, never ``0E+27``."""
    if not denominator:
        return None
    value = Decimal(count) / denominator
    return "0" if value == 0 else str(value)


def percentile(values: Sequence[int | Decimal], q: int | Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(Decimal(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * Decimal(q) / 100
    lower = int(position)
    fraction = position - lower
    if lower + 1 >= len(ordered):
        return ordered[-1]
    return ordered[lower] + fraction * (ordered[lower + 1] - ordered[lower])


def false_flag_table(
    flagged: Set[str],
    *,
    controls: Sequence[str],
    never_crossed: Sequence[str],
    session_hours: Decimal,
    coverage_hours: Mapping[str, Decimal] | None,
    endpoint: str,
) -> dict[str, Any]:
    """False flags over the sealed controls, all-control and never-crossed apart."""

    def block(names: Sequence[str]) -> dict[str, Any]:
        hits = sum(1 for symbol in names if symbol in flagged)
        session = Decimal(len(names)) * session_hours
        covered = (
            None
            if coverage_hours is None
            else sum((coverage_hours.get(symbol, ZERO) for symbol in names), ZERO)
        )
        return {
            "flagged": hits,
            "controls": len(names),
            "session_symbol_hours": str(session),
            "per_symbol_hour_session": _rate(hits, session),
            "coverage_symbol_hours": None if covered is None else str(covered),
            "per_symbol_hour_coverage": None if covered is None else _rate(hits, covered),
            "without_rows": None
            if coverage_hours is None
            else sum(1 for symbol in names if not coverage_hours.get(symbol, ZERO)),
        }

    return {
        "endpoint": endpoint,
        "denominator_status": DENOMINATOR_STATUS,
        "denominators": DENOMINATORS,
        "all_controls": block(controls),
        "never_crossed": block(never_crossed),
    }


@dataclass(frozen=True, slots=True)
class DetectionMetrics:
    arm: str
    total: int
    detected: int
    detected_at_onset: int
    late: int
    censored: int
    recall_at_onset: Decimal | None
    ever_detected: Decimal | None
    p50_latency_s: Decimal | None
    p90_latency_s: Decimal | None
    false_flags: Mapping[str, Any]
    windows: Mapping[int, Mapping[str, object]] = field(default_factory=dict)
    per_name_flags: Mapping[str, int] = field(default_factory=dict)


def detection_metrics(
    onsets: Mapping[str, int],
    flags: Mapping[str, int],
    *,
    controls: Sequence[str],
    session_hours: Decimal,
    arm: str = "unknown",
    never_crossed: Sequence[str] = (),
    coverage_hours: Mapping[str, Decimal] | None = None,
    endpoint: str = "control with a first flag in the replay window",
) -> DetectionMetrics:
    if session_hours <= 0:
        raise ValueError("positive session hours required")
    detected = at_onset = late = censored = 0
    latencies: list[int] = []
    windows: dict[int, dict[str, object]] = {}
    for width in WINDOWS_S:
        inside = 0
        for symbol, onset in onsets.items():
            flag = flags.get(symbol)
            if flag is not None and abs(flag - onset) <= width * NS:
                inside += 1
        windows[width] = {"count": inside, "recall": _share(inside, len(onsets))}
    for symbol, onset in onsets.items():
        flag = flags.get(symbol)
        if flag is None:
            censored += 1
            continue
        detected += 1
        latencies.append(flag - onset)
        if flag <= onset:
            at_onset += 1
        else:
            late += 1
    total = len(onsets)
    return DetectionMetrics(
        arm,
        total,
        detected,
        at_onset,
        late,
        censored,
        _share(at_onset, total),
        _share(detected, total),
        _seconds(percentile(latencies, 50)),
        _seconds(percentile(latencies, 90)),
        false_flag_table(
            set(flags),
            controls=controls,
            never_crossed=never_crossed,
            session_hours=session_hours,
            coverage_hours=coverage_hours,
            endpoint=endpoint,
        ),
        windows,
        {symbol: 1 if symbol in flags else 0 for symbol in onsets},
    )


@dataclass(frozen=True, slots=True)
class RankingMetrics:
    arm: str
    total: int
    rankable: int
    no_rank: int
    recall: Mapping[int, Decimal]
    first_entry_before_onset: int
    p50_signed_lead_s: Decimal | None
    p90_signed_lead_s: Decimal | None
    late_entries: int
    universe_at_onset: Mapping[str, int] = field(default_factory=dict)


def ranking_metrics(
    onsets: Mapping[str, int],
    rank_at_onset: Mapping[str, int | None],
    first_entry: Mapping[str, int | None],
    *,
    arm: str,
    ks: Sequence[int] = (30, 100),
    universe_at_onset: Mapping[str, int] | None = None,
) -> RankingMetrics:
    total = len(onsets)
    rankable = sum(1 for symbol in onsets if rank_at_onset.get(symbol) is not None)
    recall = {
        k: Decimal(
            sum(1 for s in onsets if (rank := rank_at_onset.get(s)) is not None and rank <= k)
        )
        / total
        if total
        else ZERO
        for k in ks
    }
    leads = [
        onsets[symbol] - entry
        for symbol, entry in first_entry.items()
        if symbol in onsets and entry is not None
    ]
    before = sum(
        1
        for symbol in onsets
        if (entry := first_entry.get(symbol)) is not None and entry <= onsets[symbol]
    )
    return RankingMetrics(
        arm,
        total,
        rankable,
        total - rankable,
        recall,
        before,
        _seconds(percentile(leads, 50)),
        _seconds(percentile(leads, 90)),
        sum(1 for lead in leads if lead < 0),
        dict(universe_at_onset or {}),
    )


def paired_recall(
    onsets: Mapping[str, int],
    rank_a: Mapping[str, int | None],
    rank_b: Mapping[str, int | None],
    *,
    ks: Sequence[int] = (30, 100),
) -> dict[str, object]:
    """Both arms on the identical available names (K3.9 paired contrast)."""
    common = [
        symbol
        for symbol in onsets
        if rank_a.get(symbol) is not None and rank_b.get(symbol) is not None
    ]
    return {
        "common": len(common),
        "only_a": sum(1 for s in onsets if rank_a.get(s) is not None and rank_b.get(s) is None),
        "only_b": sum(1 for s in onsets if rank_b.get(s) is not None and rank_a.get(s) is None),
        "recall_a": {
            k: str(
                Decimal(sum(1 for s in common if (r := rank_a.get(s)) is not None and r <= k))
                / len(common)
            )
            if common
            else "0"
            for k in ks
        },
        "recall_b": {
            k: str(
                Decimal(sum(1 for s in common if (r := rank_b.get(s)) is not None and r <= k))
                / len(common)
            )
            if common
            else "0"
            for k in ks
        },
    }


def persistence(
    onsets: Mapping[str, int],
    first_member: Mapping[str, int | None],
    member_at_onset: Mapping[str, bool],
) -> dict[str, object]:
    """Arm (c): member at ``tau`` among names first admitted strictly before ``tau``.

    K3.2 reads arm (c) on top-100 membership at ``tau`` given first entry
    before ``tau``; K3.9 calls it persistence "among names that entered before
    onset".  A name first admitted exactly at ``tau`` did not enter before it.
    """
    entered = [
        symbol
        for symbol, tau in onsets.items()
        if (first := first_member.get(symbol)) is not None and first < tau
    ]
    persisted = sum(1 for symbol in entered if member_at_onset.get(symbol, False))
    rate = _share(persisted, len(entered))
    return {
        "persistence_at_onset": persisted,
        "persistence_denominator": len(entered),
        "persistence_rate": None if rate is None else str(rate),
        "undefined_reason": None if entered else "no name entered membership before its onset",
        "entered_at_onset_excluded": sum(
            1 for symbol, tau in onsets.items() if first_member.get(symbol) == tau
        ),
        "unconditional_members_at_onset": sum(
            1 for symbol in onsets if member_at_onset.get(symbol, False)
        ),
    }


def baseline_availability(
    onsets: Mapping[str, int], onset_state: Mapping[str, Mapping[str, object]]
) -> dict[str, object]:
    """K3.2 secondary: the share of names whose arm normal exists and is > 0 at ``tau``."""
    unavailable: dict[str, int] = {}
    available = 0
    for symbol in onsets:
        state = onset_state.get(symbol, {})
        if state.get("baseline_available") is True:
            available += 1
            continue
        reason = str(state.get("baseline_reason") or "no_row_at_onset")
        unavailable[reason] = unavailable.get(reason, 0) + 1
    share = _share(available, len(onsets))
    return {
        "available": available,
        "total": len(onsets),
        "share": None if share is None else str(share),
        "unavailable": dict(sorted(unavailable.items())),
    }
