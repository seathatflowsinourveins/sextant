"""Predeclared metrics: recall at onset, censoring, latency and false flags.

Percentile convention: linear interpolation between closest ranks (Hyndman-
Fan type 7), named here because the K3 seal (item 6) requires the convention
to be stated before a trial.  No interval method was predeclared for the pair
contrasts, so inference stays UNAVAILABLE rather than invented.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

NS = 1_000_000_000
ZERO = Decimal(0)


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


def _seconds(value_ns: int) -> Decimal:
    return Decimal(value_ns) / NS


@dataclass(frozen=True, slots=True)
class DetectionMetrics:
    arm: str
    total: int
    detected: int
    censored: int
    recall: Decimal
    p50_latency_s: Decimal | None
    p90_latency_s: Decimal | None
    false_flags: int
    false_flags_per_symbol_hour: Decimal
    control_count: int
    never_crossed_false_flags: int | None = None
    never_crossed_per_symbol_hour: Decimal | None = None


def detection_metrics(
    onsets: Mapping[str, int],
    flags: Mapping[str, int],
    *,
    controls: Sequence[str],
    session_hours: Decimal,
    arm: str = "unknown",
    never_crossed: Sequence[str] | None = None,
) -> DetectionMetrics:
    if session_hours <= 0:
        raise ValueError("positive session hours required")
    hits = 0
    latencies: list[int] = []
    for symbol, onset in onsets.items():
        flag = flags.get(symbol)
        if flag is not None and flag <= onset:
            hits += 1
            latencies.append(onset - flag)
    total = len(onsets)
    false_flags = sum(1 for symbol in controls if symbol in flags)
    per_hour = Decimal(false_flags) / (Decimal(len(controls)) * session_hours) if controls else ZERO
    never = None
    never_per_hour = None
    if never_crossed is not None:
        never = sum(1 for symbol in never_crossed if symbol in flags)
        never_per_hour = (
            Decimal(never) / (Decimal(len(never_crossed)) * session_hours)
            if never_crossed
            else ZERO
        )
    return DetectionMetrics(
        arm,
        total,
        hits,
        total - hits,
        Decimal(hits) / total if total else ZERO,
        percentile(latencies, 50),
        percentile(latencies, 90),
        false_flags,
        per_hour,
        len(controls),
        never,
        never_per_hour,
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


def ranking_metrics(
    onsets: Mapping[str, int],
    rank_at_onset: Mapping[str, int | None],
    first_entry: Mapping[str, int | None],
    *,
    arm: str,
    ks: Sequence[int] = (30, 100),
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
        percentile(leads, 50),
        percentile(leads, 90),
        sum(1 for lead in leads if lead < 0),
    )


def ranking_false_flags(
    first_entry: Mapping[str, int | None],
    *,
    controls: Sequence[str],
    session_hours: Decimal,
) -> Decimal:
    if not controls:
        return ZERO
    flagged = sum(1 for symbol in controls if first_entry.get(symbol) is not None)
    return Decimal(flagged) / (Decimal(len(controls)) * session_hours)
