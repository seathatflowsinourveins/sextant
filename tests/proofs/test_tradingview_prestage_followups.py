"""Witnesses for the publication clock: it is read after the replay, not at its start."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from test_tradingview_prestage import (
    NS,
    PRIOR,
    SYMBOLS,
    RecordedSource,
    at,
    bounds,
    current_bars,
    prior_bars,
    registry,
    segment,
)

D = Decimal
MINUTE_NS = 60 * NS


def test_the_publication_clock_is_resampled_after_the_replay(tmp_path: Path) -> None:
    """The tick is stamped with the clock read after the fetch, not its start."""
    from sextant.tradingview.prestage import publish_tick
    from sextant.tradingview.producer import reserve_stream

    section = segment("RTH")
    source = RecordedSource(prior_bars("RTH", PRIOR) + current_bars("RTH"))
    baseline = _baseline(source, "RTH")
    with reserve_stream(
        tmp_path / "leases", paper_slot=2, existing_streams=0, source="fixture"
    ) as lease:
        receipt = publish_tick(
            lease=lease,
            source=source,
            segment=section,
            baseline=baseline,
            symbols=SYMBOLS,
            prior_closes={name: D("10.00") for name in SYMBOLS},
            prior_close_ns=at(PRIOR[-1], 16),
            symbol_map={name: f"NASDAQ:{name}" for name in SYMBOLS},
            registry=registry(),
            epoch="tv-producer-fixture-clock",
            universe_source="fixture directory; NOT PIT",
            now_ns=section.start_ns + 8 * MINUTE_NS,
            unit_dir=tmp_path / "unit",
            j5_path=tmp_path / "j5.json",
            bounds=bounds(),
            clock=lambda: section.start_ns + 9 * MINUTE_NS,
        )
    assert receipt["publish_clock_ns"] == section.start_ns + 9 * MINUTE_NS


def test_a_tick_that_finishes_after_the_segment_closes_is_refused(tmp_path: Path) -> None:
    """A tick whose fetch outlives the segment publishes nothing."""
    from sextant.tradingview.prestage import PrestageError, publish_tick
    from sextant.tradingview.producer import reserve_stream

    section = segment("PRE")
    source = RecordedSource(prior_bars("PRE", PRIOR) + current_bars("PRE"))
    baseline = _baseline(source, "PRE")
    with (
        reserve_stream(
            tmp_path / "leases", paper_slot=2, existing_streams=0, source="fixture"
        ) as lease,
        pytest.raises(PrestageError, match="closed before"),
    ):
        publish_tick(
            lease=lease,
            source=source,
            segment=section,
            baseline=baseline,
            symbols=SYMBOLS,
            prior_closes={name: D("10.00") for name in SYMBOLS},
            prior_close_ns=at(PRIOR[-1], 16),
            symbol_map={name: f"NASDAQ:{name}" for name in SYMBOLS},
            registry=registry(),
            epoch="tv-producer-fixture-closed",
            universe_source="fixture directory; NOT PIT",
            now_ns=section.end_ns - 30 * NS,
            unit_dir=tmp_path / "unit",
            j5_path=tmp_path / "j5.json",
            bounds=bounds(),
            clock=lambda: section.end_ns + 30 * NS,
        )
    assert not (tmp_path / "unit").exists()
    assert not (tmp_path / "j5.json").exists()


def _baseline(source: RecordedSource, name: str) -> Any:
    from sextant.tradingview.prestage import build_segment_baseline

    return build_segment_baseline(
        source,
        segment=segment(name),
        symbols=SYMBOLS,
        sessions=PRIOR,
        known_at=at(PRIOR[-1], 20),
        provenance="fixture five prior sessions",
    )
