"""ADR-0003 exact-head veto witnesses carried from the LRC4 gate review."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from test_ranking_host import GOOD, NS, REFS, SCOPE, START, UNIVERSE, tick, warm, wired

from sextant.ranking.engine import ReferencePrices
from sextant.ranking.generation import Coverage, CoverageState
from sextant.ranking.host import RankingHost


READY = Coverage(CoverageState.READY, True, 3, 3, 0, 0, 0)
AT = START + 360 * NS
TIMES = ("before_warm", "after_warm", "between_read_and_entry")


def asset_setter(asset: object) -> Callable[[RankingHost], None]:
    def setter(host: RankingHost) -> None:
        host.set_symbol("PENNY", references=REFS, asset=asset)

    return setter


def coverage_setter(coverage: object) -> Callable[[RankingHost], None]:
    def setter(host: RankingHost) -> None:
        host.set_coverage(coverage)

    return setter


VETOES = {
    f"coverage_{state.name.lower()}": coverage_setter(replace(READY, state=state))
    for state in CoverageState
    if state is not CoverageState.READY
}
VETOES["coverage_incomplete_with_good_counts"] = coverage_setter(replace(READY, complete=False))
VETOES["coverage_all_counts_unknown"] = coverage_setter(Coverage(CoverageState.READY, True))
for field in (
    "expected_symbols",
    "observed_symbols",
    "missing_symbols",
    "late_symbols",
    "invalid_symbols",
):
    VETOES[f"coverage_{field}_null"] = coverage_setter(replace(READY, **{field: None}))
    wrong = 2 if field in {"expected_symbols", "observed_symbols"} else 1
    VETOES[f"coverage_{field}_wrong"] = coverage_setter(replace(READY, **{field: wrong}))

VETOES["asset_none"] = asset_setter(None)
for name, asset in {
    "halted": replace(GOOD, halted=True),
    "halt_unknown": replace(GOOD, halted=None),
    "type_ineligible": replace(GOOD, security_type="etf"),
    "type_missing": replace(GOOD, security_type=""),
    "expired": replace(GOOD, expires_at=AT),
    "future": replace(GOOD, known_at=SCOPE.end_ns),
    "negative_known_at": replace(GOOD, known_at=-1),
    "negative_expiry": replace(GOOD, expires_at=-1),
    "no_source": replace(GOOD, source=""),
}.items():
    VETOES[f"asset_{name}"] = asset_setter(asset)


def prepare(tmp_path: Path, when: str):
    host, now, beats = wired(tmp_path)
    if when != "before_warm":
        warm(host, now)
        if when == "between_read_and_entry":
            assert host.entry_rank("PENNY", now=AT) == 1
    return host, now, beats


def withdrawn(host: RankingHost, at: int = AT) -> None:
    ranks = {name: host.entry_rank(name, now=at) for name in UNIVERSE}
    assert all(rank is None for rank in ranks.values()), ranks
    assert host.ranked_names(now=at) == ()


@pytest.mark.parametrize("when", TIMES)
@pytest.mark.parametrize("veto", sorted(VETOES))
def test_veto_publication_error_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, veto: str, when: str
) -> None:
    host, now, _ = prepare(tmp_path, when)

    def raising_publication(*, now: int):
        raise ValueError("publication unavailable")

    monkeypatch.setattr(host.publisher, "publish", raising_publication)
    VETOES[veto](host)
    if when == "before_warm":
        warm(host, now)
    assert host.publish_errors >= 1
    withdrawn(host)
    host.close()


def test_raising_veto_preserves_ready_and_heartbeat_witness(tmp_path: Path) -> None:
    host, now, beats = wired(tmp_path)
    warm(host, now)
    before_beats = len(beats)
    try:
        host.set_symbol("PENNY", references=REFS, asset=replace(GOOD, known_at=None, halted=True))
    except TypeError:
        pass
    withdrawn(host)
    assert len(beats) == before_beats
    host.close()


def test_reference_veto_renews_ready_and_heartbeat_witness(tmp_path: Path) -> None:
    host, now, beats = wired(tmp_path)
    warm(host, now)
    before_beats = len(beats)
    now[0] = AT + NS
    host.set_symbol("PENNY", references=ReferencePrices(None, START - NS, REFS.source), asset=GOOD)
    withdrawn(host, at=now[0])
    assert len(beats) == before_beats
    host.close()


def test_missing_reference_publication_regression(tmp_path: Path) -> None:
    host, now, beats = wired(tmp_path)
    warm(host, now)
    before_beats = len(beats)
    now[0] = AT + NS
    host.set_symbol("PENNY", references=ReferencePrices(None, START - NS, REFS.source), asset=GOOD)
    host.on_trade(tick(now[0], "0.56"))
    assert host.publisher.states["PENNY"].latest.score is None
    withdrawn(host, at=now[0])
    assert len(beats) == before_beats
    host.close()
