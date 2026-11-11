"""ADR-0003 exact-head veto witnesses carried from the LRC4 gate review."""

from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from test_ranking_host import GOOD, NS, REFS, SCOPE, START, UNIVERSE, tick, warm, wired

from sextant.ranking.engine import ReferencePrices
from sextant.ranking.generation import Coverage, CoverageState
from sextant.ranking.host import RankingHost
from sextant.ranking.publisher import AssetState

READY = Coverage(CoverageState.READY, True, 3, 3, 0, 0, 0)
AT = START + 360 * NS
TIMES = ("before_warm", "after_warm", "between_read_and_entry")


def asset_setter(asset: AssetState | None) -> Callable[[RankingHost], None]:
    def setter(host: RankingHost) -> None:
        host.set_symbol("PENNY", references=REFS, asset=asset)

    return setter


def coverage_setter(coverage: Coverage) -> Callable[[RankingHost], None]:
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
    latest = host.publisher.states["PENNY"].latest
    assert latest is not None and latest.score is None
    withdrawn(host, at=now[0])
    assert len(beats) == before_beats
    host.close()


@pytest.mark.parametrize("operation", ["symbol", "coverage", "trade", "publish"])
def test_authority_is_revoked_before_every_mutation_and_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    host, now, _ = wired(tmp_path)
    warm(host, now)
    assert host.entry_rank("PENNY", now=AT) == 1

    def check_revoked(*_args, **_kwargs):
        # Reentrant admission observes the real consumer, not just a host wrapper.
        assert host.consumer.entry_rank("PENNY", now=AT) is None
        assert host.consumer.ranked_names(now=AT) == ()
        raise RuntimeError("boundary unavailable")

    method = {"symbol": "set_symbol", "coverage": "set_coverage", "trade": "on_trade"}.get(
        operation, "publish"
    )
    monkeypatch.setattr(host.publisher, method, check_revoked)
    call = {
        "symbol": lambda: host.set_symbol("PENNY", references=REFS, asset=GOOD),
        "coverage": lambda: host.set_coverage(READY),
        "trade": lambda: host.on_trade(tick(AT, "0.56")),
        "publish": host._publish,
    }[operation]
    call()
    withdrawn(host)
    assert host.last_error == "RuntimeError"
    host.close()


@pytest.mark.parametrize("stage", ["readiness", "publisher", "after_delivery"])
@pytest.mark.parametrize("error", [TypeError, ValueError, RuntimeError, OSError])
def test_every_readiness_and_publish_exception_counts_pages_and_revokes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str, error: type[Exception]
) -> None:
    host, now, beats = wired(tmp_path)
    warm(host, now)
    pages: list[tuple[str, str | None]] = []
    host._alarm = lambda reason, symbol: pages.append((reason, symbol))
    before_errors, before_beats = host.publish_errors, len(beats)
    now[0] = AT + NS
    publish = host.publisher.publish

    def fail(*_args, **_kwargs):
        if stage == "after_delivery":
            publish(now=now[0])
            assert host.consumer.reader.generation is not None
        raise error("unavailable")

    if stage == "readiness":
        monkeypatch.setattr(type(GOOD), "eligible", fail)
    else:
        monkeypatch.setattr(host.publisher, "publish", fail)
    host.set_coverage(READY)
    withdrawn(host, at=now[0])
    assert host.publish_errors == before_errors + 1
    assert host.last_error == error.__name__
    assert pages and pages[-1][1] is None
    assert len(beats) == before_beats
    host.close()


@pytest.mark.parametrize(
    "reference",
    [
        ReferencePrices(None, START - NS, REFS.source),
        replace(REFS, known_at=SCOPE.end_ns),
        replace(REFS, prior_close=Decimal("1.00")),
    ],
)
def test_reference_changes_require_recomputed_evidence(tmp_path: Path, reference) -> None:
    host, now, beats = wired(tmp_path)
    warm(host, now)
    before_beats = len(beats)
    now[0] = AT + NS
    host.set_symbol("PENNY", references=reference, asset=GOOD)
    withdrawn(host, at=now[0])
    assert len(beats) == before_beats
    host.set_coverage(READY)
    withdrawn(host, at=now[0])
    assert len(beats) == before_beats
    host.close()


def test_a_throttled_trade_cannot_regrant_rank_but_a_fresh_publish_can(tmp_path: Path) -> None:
    host, now, _ = wired(tmp_path)
    warm(host, now)
    assert host.entry_rank("PENNY", now=AT) == 1
    now[0] = AT + NS // 2
    assert host.on_trade(tick(now[0], "0.56")) is None
    withdrawn(host, at=now[0])
    now[0] = AT + NS
    assert host.on_trade(tick(now[0], "0.57")) is not None
    assert host.entry_rank("PENNY", now=now[0]) == 1
    assert host.ranked_names(now=now[0]) == ("PENNY",)
    host.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_symbols", Decimal(3)),
        ("observed_symbols", Decimal(3)),
        ("missing_symbols", False),
        ("invalid_symbols", Decimal(0)),
        ("late_symbols", False),
    ],
)
def test_invalid_coverage_count_types_cannot_regrant_authority(
    tmp_path: Path, field: str, value
) -> None:
    host, now, beats = wired(tmp_path)
    warm(host, now)
    before_beats = len(beats)
    now[0] = AT + NS
    host.set_coverage(replace(READY, **{field: value}))
    withdrawn(host, at=now[0])
    assert len(beats) == before_beats
    host.close()


@pytest.mark.parametrize(
    "asset",
    [
        replace(GOOD, known_at=True),
        replace(GOOD, source=["fixture"]),
    ],
)
def test_invalid_asset_fields_cannot_regrant_authority(tmp_path: Path, asset) -> None:
    host, now, beats = wired(tmp_path)
    warm(host, now)
    before_beats = len(beats)
    now[0] = AT + NS
    host.set_symbol("PENNY", references=REFS, asset=asset)
    withdrawn(host, at=now[0])
    assert len(beats) == before_beats
    host.close()
