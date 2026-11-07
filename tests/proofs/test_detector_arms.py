"""#130: offline component proofs, not market trials, study results or admission.

All data and explicit parameter overrides are fabricated software fixtures.
No fixture row authorizes a market series, threshold, hazard, boundary or model.
"""

import ast
import hashlib
import inspect
import random
import socket
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from nautilus_trader.model import Bar, BarType, InstrumentId, Price, Quantity
from river import base, stats
from river.drift import PageHinkley

from sextant.research.detectors import bocpd
from sextant.research.detectors import page_hinkley as ph
from sextant.research.detectors import stocks_in_play as sip
from sextant.research.detectors.common import Observation, Parameter

D = Decimal
ID = InstrumentId.from_str("FIXTURE.XNAS")
DAY = date(2026, 11, 6)
NY = ZoneInfo("America/New_York")
NS = 1_000_000_000
ONE = D(1)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*_args, **_kwargs):
        pytest.fail("detector proof attempted a socket")

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def observation(i: int, value: Decimal | None = ONE) -> Observation:
    return Observation(ID, i * NS, i * NS + 1, value)


def ph_rows(mode: str = "both") -> tuple[Parameter, ...]:
    # Parameters exercise drift/reset/warmup. These are NOT strategy starting values.
    values = {
        "min_instances": 3,
        "delta": D("0.01"),
        "threshold": D(2),
        "alpha": D("0.99"),
        "mode": mode,
    }
    return tuple(
        replace(r, value=values[r.name], source="fixture only", calibration_state="UNCALIBRATED")
        for r in ph.PARAMETERS
    )


def bocpd_rows() -> tuple[Parameter, ...]:
    return tuple(
        replace(r, value="fixture only", calibration_state="UNCALIBRATED")
        for r in bocpd.PARAMETERS
        if r.name != "alarm_rule"
    )


def test_river_installation_matches_the_pinned_upstream_sources() -> None:
    assert version("river") == "0.26.1"
    for obj, expected in (
        (PageHinkley, "ad9b8209b24d786f267175097694e6640080beafb89b86b806fc76e28e71056f"),
        (stats.Mean, "aac63673e4dda4a96e8380466fa80cf9fa631aef37ae3775896bf53ce3858c32"),
        (base.DriftDetector, "0747f5410fe3998075fd572f85f1677d37ca0e4d0d8503d133c6023ac1c87995"),
    ):
        path = inspect.getsourcefile(obj)
        assert path is not None and hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("mode", ["up", "down", "both"])
def test_page_hinkley_matches_upstream_on_each_sample_and_reset(mode) -> None:
    arm = ph.PageHinkleyArm(ph_rows(mode), observation_source="fabricated dimensionless samples")
    reference = PageHinkley(min_instances=3, delta=0.01, threshold=2.0, alpha=0.99, mode=mode)
    rng = random.Random(130)  # noqa: S311 - repeatable fabricated samples, not a secret.
    values = [D(str(rng.uniform(-1, 1) + shift)) for shift in (0, 8, -8, 0) for _ in range(40)]
    detected = 0
    count = 0
    for i, x in enumerate(values, 1):
        count = 0 if reference.drift_detected else count
        reference.update(float(x))
        count += 1
        result = arm.update(observation(i, x), as_of_ns=i * NS + 1)
        assert result.detected == (reference.drift_detected if count >= 3 else None)
        assert result.reason == ("updated" if count >= 3 else "warmup")
        detected += result.detected is True
    assert detected > 1  # Both changes and the post-detection reset were actually exercised.


def test_no_river_defaults_or_fixture_authority_become_market_parameters() -> None:
    obs = observation(1)
    for rows, source in ((ph.PARAMETERS, "series"), (ph_rows(), None)):
        result = ph.PageHinkleyArm(rows, observation_source=source).update(
            obs, as_of_ns=obs.ts_init
        )
        assert result.detected is None and "authority_missing" in result.reason
    for rows in (ph.PARAMETERS[:-1], (ph.PARAMETERS[0],) * 5):
        with pytest.raises(ValueError, match="exactly once"):
            ph.PageHinkleyArm(rows, observation_source=None)
    assert all(r.value is None and r.calibration_state == "UNAVAILABLE" for r in ph.PARAMETERS)
    assert all(r.value is None and r.calibration_state == "UNAVAILABLE" for r in bocpd.PARAMETERS)
    original = ph_rows()
    changed = tuple(replace(r, source="changed citation") for r in original)

    def identity(rows, source):
        return ph.PageHinkleyArm(rows, observation_source=source).params_hash

    assert identity(original, "series") != identity(changed, "series")
    assert identity(changed, "series") != identity(changed, "other series")
    assert identity(original, "series") == identity(tuple(reversed(original)), "series")


@pytest.mark.parametrize("bad", [True, 0.01, D("NaN"), D("Infinity")])
def test_parameters_reject_non_decimal_and_nonfinite_numeric_authority(bad) -> None:
    with pytest.raises(ValueError):
        replace(ph_rows()[1], value=bad)


def test_river_does_not_mutate_on_future_missing_duplicate_or_mixed_series() -> None:
    arm = ph.PageHinkleyArm(ph_rows(), observation_source="fixture")
    obs = observation(1)
    assert arm.update(obs, as_of_ns=obs.ts_event).reason == "not_yet_available"
    assert (
        arm.update(replace(obs, value=None), as_of_ns=obs.ts_init).reason == "missing_observation"
    )
    assert arm.update(obs, as_of_ns=obs.ts_init).reason == "warmup"
    with pytest.raises(ValueError, match="duplicate"):
        arm.update(obs, as_of_ns=obs.ts_init)
    with pytest.raises(ValueError, match="one instrument"):
        arm.update(
            replace(observation(2), instrument_id=InstrumentId.from_str("OTHER.XNAS")),
            as_of_ns=3 * NS,
        )
    assert arm.update(observation(2), as_of_ns=3 * NS).reason == "warmup"
    assert arm.update(observation(3), as_of_ns=4 * NS).detected is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("min_instances", 0),
        ("min_instances", D(3)),
        ("delta", D(-1)),
        ("threshold", D(0)),
        ("alpha", D("1.01")),
        ("mode", "bullish"),
        ("threshold", D("1e400")),
        ("threshold", D("1e-400")),
    ],
)
def test_river_rejects_invalid_or_unrepresentable_parameters(field, value) -> None:
    rows = tuple(replace(r, value=value) if r.name == field else r for r in ph_rows())
    with pytest.raises(ValueError):
        ph.PageHinkleyArm(rows, observation_source="fixture")


@pytest.mark.parametrize("bad", [D("1e400"), D("1e-400")])
def test_river_numeric_range_failure_does_not_consume_a_sample(bad) -> None:
    arm = ph.PageHinkleyArm(ph_rows(), observation_source="fixture")
    with pytest.raises(ValueError, match="numeric range"):
        arm.update(observation(1, bad), as_of_ns=2 * NS)
    assert arm.update(observation(1), as_of_ns=2 * NS).reason == "warmup"


def test_observation_clocks_reject_nonfinite_and_reversed_inputs() -> None:
    for changes in ({"ts_init": 0}, {"ts_event": True}, {"value": D("NaN")}):
        with pytest.raises(ValueError):
            replace(observation(1), **changes)
    arm = ph.PageHinkleyArm(ph_rows(), observation_source="fixture")
    arm.update(replace(observation(2), ts_init=4 * NS), as_of_ns=5 * NS)
    for obs in (
        observation(1),
        observation(3),
        # Same completion with a different value/later receipt is not a new scalar sample.
        replace(observation(2, D(2)), ts_init=5 * NS),
    ):
        with pytest.raises(ValueError, match="out-of-order"):
            arm.update(obs, as_of_ns=5 * NS)
    with pytest.raises(ValueError, match="as-of"):
        arm.update(observation(5), as_of_ns=-1)
    assert arm.update(observation(5), as_of_ns=6 * NS).reason == "warmup"


def test_bocpd_matches_hand_computed_nonconstant_hazard_recursion() -> None:
    # Hand calculation from eq. (3) / Algorithm 1, not a second library port.
    prior = (D("0.25"), D("0.75"))
    predictive = (D("0.2"), D("0.8"))
    hazard = (D("0.1"), D("0.3"))  # H(1), H(2), not an unreviewed fixed lambda.
    actual = bocpd.run_length_step(prior, predictive, hazard)
    mass = (D("0.185"), D("0.045"), D("0.42"))
    assert actual == tuple(v / D("0.65") for v in mass)
    assert bocpd.run_length_step((D(1),), (D("0.2"),), (D("0.1"),)) == (D("0.1"), D("0.9"))


def test_bocpd_evaluates_nonconstant_elapsed_duration_hazard_at_r_plus_one():
    from sextant.research.detectors.common import digest

    durations = []

    def hazard(tau):
        durations.append(tau)
        return {0: D("0.9"), 1: D("0.1"), 2: D("0.5")}[tau]

    prior = (D("0.25"), D("0.75"))
    arm = bocpd.BocpdArm(bocpd_rows(), initial=prior)
    obs = observation(1)
    actual = arm.update(obs, as_of_ns=obs.ts_init, predictive=(D("0.2"), D("0.8")), hazard=hazard)
    assert durations == [1, 2]  # Eq.(4), not Algorithm 1's printed H(r).
    assert bocpd.HAZARD_CONVENTION.value == "equation (4): H(r+1)"
    assert actual.params_hash == arm.params_hash
    assert actual.probabilities == tuple(v / D("0.65") for v in (D("0.305"), D("0.045"), D("0.30")))
    assert arm.params_hash == digest(
        {
            "rows": [r.identity for r in sorted(bocpd_rows(), key=lambda r: r.name)],
            "initial": prior,
            "hazard_convention": bocpd.HAZARD_CONVENTION.identity,
        }
    )


def test_bocpd_constant_hazard_is_not_a_changepoint_alarm_probability() -> None:
    prior = (D(1),)
    for i in range(1, 20):
        predictive = tuple(D(1 + (r + i) % 7) / 10 for r in range(len(prior)))
        prior = bocpd.run_length_step(prior, predictive, (D("0.2"),) * len(prior))
        assert abs(prior[0] - D("0.2")) < D("1e-26")
        assert len(prior) == i + 1  # No invented tail pruning or run-length cap.
    assert not hasattr(bocpd.Posterior, "detected")


@pytest.mark.parametrize(
    "prior,predictive,hazards",
    [
        ((D(1),), (), (D("0.1"),)),
        ((D(1),), (D(0),), (D("0.1"),)),
        ((D(-1),), (D(1),), (D("0.1"),)),
        ((D(1),), (D("NaN"),), (D("0.1"),)),
        ((D(1),), (D(1),), (D("1.1"),)),
    ],
)
def test_bocpd_refuses_bad_vectors_and_impossible_evidence(prior, predictive, hazards) -> None:
    with pytest.raises(ValueError):
        bocpd.run_length_step(prior, predictive, hazards)


def test_bocpd_missing_authority_or_model_output_does_not_advance_inference() -> None:
    missing = bocpd.BocpdArm(
        tuple(r for r in bocpd.PARAMETERS if r.name != "alarm_rule"), initial=(D(1),)
    )
    obs = observation(1)
    assert (
        "unavailable"
        in missing.update(
            obs, as_of_ns=obs.ts_init, predictive=(D(1),), hazard=lambda _: D("0.1")
        ).reason
    )
    arm = bocpd.BocpdArm(bocpd_rows(), initial=(D(1),))
    assert (
        arm.update(
            obs, as_of_ns=obs.ts_event, predictive=(D(1),), hazard=lambda _: D("0.1")
        ).probabilities
        is None
    )
    assert arm.update(obs, as_of_ns=obs.ts_init, predictive=None, hazard=None).probabilities is None
    result = arm.update(obs, as_of_ns=obs.ts_init, predictive=(D(1),), hazard=lambda _: D("0.1"))
    assert result.probabilities == (D("0.1"), D("0.9"))
    assert result.reason == "inference_only_no_alarm_rule"
    with pytest.raises(ValueError, match="duplicate"):
        arm.update(obs, as_of_ns=obs.ts_init, predictive=(D(1),), hazard=lambda _: D("0.1"))


def test_bocpd_boundary_identity_extreme_hazards_and_retry_after_zero_evidence() -> None:
    rows = bocpd_rows()
    unavailable = bocpd.BocpdArm(rows, initial=None)
    obs = observation(1)
    assert (
        unavailable.update(
            obs, as_of_ns=2 * NS, predictive=(ONE,), hazard=lambda _: ONE
        ).probabilities
        is None
    )
    first = bocpd.BocpdArm(rows, initial=(ONE,))
    other = bocpd.BocpdArm(rows, initial=(ONE, ONE))
    assert first.params_hash != other.params_hash
    assert first.params_hash == bocpd.BocpdArm(tuple(reversed(rows)), initial=(ONE,)).params_hash
    with pytest.raises(ValueError, match="zero predictive evidence"):
        first.update(obs, as_of_ns=2 * NS, predictive=(D(0),), hazard=lambda _: D(0))
    assert first.update(
        obs, as_of_ns=2 * NS, predictive=(D(2),), hazard=lambda _: D(0)
    ).probabilities == (D(0), ONE)
    assert bocpd.run_length_step((D("0.4"), D("0.6")), (ONE, ONE), (ONE, ONE)) == (ONE, D(0), D(0))
    assert bocpd.run_length_step((D("0.4"), D("0.6")), (D(2), D(2)), (D(0), D(0))) == (
        D(0),
        D("0.4"),
        D("0.6"),
    )
    for invalid in ((), (D(0),), (D("Infinity"),)):
        with pytest.raises(ValueError):
            bocpd.BocpdArm(rows, initial=invalid)
    with pytest.raises(ValueError, match="rows required"):
        bocpd.BocpdArm(bocpd.PARAMETERS, initial=(ONE,))


def opened(day: date = DAY) -> int:
    return int(datetime.combine(day, time(9, 30), NY).timestamp()) * NS


def bar(
    day: date = DAY, *, step: int = 1, i: int = 1, delay: int = 0, internal: bool = False
) -> Bar:
    at = opened(day) + step * i * 60 * NS
    kind = BarType.from_str(f"{ID}-{step}-MINUTE-LAST-{'INTERNAL' if internal else 'EXTERNAL'}")
    return Bar(
        kind,
        Price.from_str("6.00"),
        Price.from_str("7.00"),
        Price.from_str("5.00"),
        Price.from_str("6.50"),
        Quantity.from_int(100),
        at,
        at + delay,
    )


def windows(spec=None) -> tuple[sip.OpeningWindow, tuple[sip.OpeningWindow, ...], sip.DailyFacts]:
    active = spec if spec is not None else sip.StocksInPlaySpec(sip.PARAMETERS)
    lookback = active.integer("lookback")
    days = tuple(
        DAY - timedelta(days=i)
        for i in range(lookback * 2, 0, -1)
        if (DAY - timedelta(days=i)).weekday() < 5
    )[-lookback:]

    def fixture(day):
        return sip.OpeningWindow(
            ID,
            day,
            D(6),
            D("6.5"),
            D(100),
            opened(day) + active.integer("opening_window") * 60 * NS,
            coverage_complete=True,
            params_hash=active.params_hash,
            composite_type=active.composite_type(ID),
        )

    current = fixture(DAY)
    prior = tuple(fixture(d) for d in days)
    facts = sip.DailyFacts(ID, days, D(1_000_000), D("0.51"), opened() - 1)
    return current, prior, facts


@pytest.mark.parametrize(
    "name,value",
    [
        ("open_above", D(7)),
        ("adv_at_least", D(2_000_000)),
        ("atr_above", D("0.60")),
        ("rvol_at_least", D("1.1")),
    ],
)
def test_registry_mutation_changes_applied_filter_and_result_hash(monkeypatch, name, value):
    def result():
        current, prior, facts = windows()
        return sip.screen(
            current,
            prior,
            facts=facts,
            expected_sessions=facts.sessions,
            as_of_ns=current.known_at_ns,
        )

    original = result()
    assert original.passes_local_filters is True
    rows = tuple(
        replace(row, value=value, source="fixture mutation only", calibration_state="UNCALIBRATED")
        if row.name == name
        else row
        for row in sip.PARAMETERS
    )
    monkeypatch.setattr(sip, "PARAMETERS", rows)
    changed = result()
    assert changed.passes_local_filters is False
    assert changed.params_hash != original.params_hash


@pytest.mark.parametrize("coverage", [None, False])
def test_screen_refuses_current_and_prior_windows_without_coverage_evidence(coverage):
    current, prior, facts = windows()
    for c, p in [
        (replace(current, coverage_complete=coverage), prior),
        (current, (*prior[:-1], replace(prior[-1], coverage_complete=coverage))),
    ]:
        result = sip.screen(
            c, p, facts=facts, expected_sessions=facts.sessions, as_of_ns=current.known_at_ns
        )
        assert result.rvol is None and result.passes_local_filters is None
        assert result.reason == "opening_coverage_unavailable"


def test_screen_rejects_mismatched_parameter_identity():
    current, prior, facts = windows()
    with pytest.raises(ValueError, match="parameter identity"):
        sip.screen(
            replace(current, params_hash="f" * 64),
            prior,
            facts=facts,
            expected_sessions=facts.sessions,
            as_of_ns=current.known_at_ns,
        )


def test_window_duration_and_lookback_rows_govern_construction_and_readiness():
    rows = tuple(
        replace(
            row,
            value={"opening_window": 10, "lookback": 3}[row.name],
            source="fixture override",
            calibration_state="UNCALIBRATED",
        )
        if row.name in {"opening_window", "lookback"}
        else row
        for row in sip.PARAMETERS
    )
    active = sip.StocksInPlaySpec(rows)
    current, prior, facts = windows(active)
    assert len(prior) == 3 and current.known_at_ns == opened() + 600 * NS
    composite = active.composite_type(ID)
    completed = (bar(step=10, internal=True),)
    window = sip.opening_window(
        completed,
        session_open_ns=opened(),
        as_of_ns=current.known_at_ns,
        coverage_complete=True,
        composite_type=composite,
        spec=active,
    )
    assert window is not None and window.params_hash == active.params_hash
    assert (
        sip.screen(
            current,
            prior,
            facts=facts,
            expected_sessions=facts.sessions,
            as_of_ns=current.known_at_ns,
            spec=active,
        ).passes_local_filters
        is True
    )
    assert (
        sip.screen(
            current,
            prior[:-1],
            facts=facts,
            expected_sessions=facts.sessions,
            as_of_ns=current.known_at_ns,
            spec=active,
        ).rvol
        is None
    )
    with pytest.raises(ValueError, match="native composite"):
        sip.opening_window(
            (bar(step=5, internal=True),),
            session_open_ns=opened(),
            as_of_ns=current.known_at_ns,
            coverage_complete=True,
            composite_type=composite,
            spec=active,
        )


def test_varying_opening_volumes_use_the_bound_previous_windows_mean_interpretation():
    current, prior, facts = windows()
    current = replace(current, volume=D(1000))
    prior = tuple(replace(w, volume=D(i * 100)) for i, w in enumerate(prior, 1))
    result = sip.screen(
        current, prior, facts=facts, expected_sessions=facts.sessions, as_of_ns=current.known_at_ns
    )
    assert result.rvol == D(1000) / D(750) and result.passes_local_filters is True
    assert current.volume / prior[-1].volume < 1  # Literal p.14 would fail this case.
    active = sip.StocksInPlaySpec(sip.PARAMETERS)
    row = active.mapping["denominator"]
    assert row.value == "mean_prior_opening_windows" and row.calibration_state == "UNCALIBRATED"
    assert "section 5 p.19" in row.source and "9423012e9f0199e3" in row.source
    assert result.params_hash == active.params_hash
    # A different interpretation cannot silently run as the supported mean.
    with pytest.raises(ValueError, match="denominator"):
        sip.StocksInPlaySpec(
            tuple(
                replace(r, value="previous_day") if r.name == "denominator" else r
                for r in sip.PARAMETERS
            )
        )


def test_spec_identity_is_the_validated_active_mapping_including_source_and_interpretation():
    from sextant.research.detectors.common import digest

    active = sip.StocksInPlaySpec(sip.PARAMETERS)
    assert active.params_hash == digest(
        {name: row.identity for name, row in active.mapping.items()}
    )
    assert sip.StocksInPlaySpec(tuple(reversed(sip.PARAMETERS))).params_hash == active.params_hash
    with pytest.raises(TypeError):
        # Deliberately test runtime refusal as well as Mapping's static prohibition.
        cast(Any, active.mapping)["lookback"] = active.mapping["lookback"]
    changed = sip.StocksInPlaySpec(
        tuple(
            replace(r, source=r.source + "; fixture annotation") if r.name == "denominator" else r
            for r in sip.PARAMETERS
        )
    )
    assert changed.params_hash != active.params_hash
    unavailable = sip.screen(None, (), expected_sessions=(), facts=None, as_of_ns=0, spec=changed)
    assert unavailable.params_hash == changed.params_hash
    for rows in (
        sip.PARAMETERS[:-1],
        (*sip.PARAMETERS[:-1], sip.PARAMETERS[0]),
        tuple(replace(r, value=0) if r.name == "lookback" else r for r in sip.PARAMETERS),
        tuple(replace(r, unit="USD") if r.name == "lookback" else r for r in sip.PARAMETERS),
    ):
        with pytest.raises(ValueError):
            sip.StocksInPlaySpec(rows)


@pytest.mark.parametrize("day", [DAY, date(2026, 7, 6), date(2026, 3, 9), date(2026, 11, 27)])
def test_native_opening_bars_are_unavailable_until_completed_and_received(day) -> None:
    composite = sip.StocksInPlaySpec(sip.PARAMETERS).composite_type(ID)
    completed = (bar(day, step=5, internal=True),)
    end = opened(day) + 300 * NS
    assert (
        sip.opening_window(
            completed,
            session_open_ns=opened(day),
            as_of_ns=end - 1,
            coverage_complete=True,
            composite_type=composite,
        )
        is None
    )
    window = sip.opening_window(
        completed,
        session_open_ns=opened(day),
        as_of_ns=end,
        coverage_complete=True,
        composite_type=composite,
    )
    assert window is not None and window.volume == 100 and window.known_at_ns == end
    assert window.coverage_complete is True and window.composite_type == composite
    delayed = (bar(day, step=5, delay=10, internal=True),)
    assert (
        sip.opening_window(
            delayed,
            session_open_ns=opened(day),
            as_of_ns=end,
            coverage_complete=True,
            composite_type=composite,
        )
        is None
    )
    assert (
        sip.opening_window(
            delayed,
            session_open_ns=opened(day),
            as_of_ns=end + 10,
            coverage_complete=True,
            composite_type=composite,
        )
        is not None
    )
    with pytest.raises(ValueError, match="native composite"):
        sip.opening_window(
            (bar(day, step=5),),
            session_open_ns=opened(day),
            as_of_ns=end,
            coverage_complete=True,
            composite_type=composite,
        )


def test_partial_missing_uncovered_mixed_or_shifted_windows_do_not_become_opening_bars() -> None:
    minutes = tuple(bar(i=i) for i in range(1, 6))
    end = opened() + 300 * NS
    composite = sip.StocksInPlaySpec(sip.PARAMETERS).composite_type(ID)
    for bad in (minutes, minutes[:-1], minutes[1:], (minutes[0],) * 5, ()):
        assert (
            sip.opening_window(
                bad,
                session_open_ns=opened(),
                as_of_ns=end,
                coverage_complete=True,
                composite_type=composite,
            )
            is None
        )
    assert (
        sip.opening_window(
            (bar(step=5, internal=True),),
            session_open_ns=opened(),
            as_of_ns=end,
            coverage_complete=None,
            composite_type=composite,
        )
        is None
    )
    with pytest.raises(ValueError, match="09:30"):
        sip.opening_window(
            minutes,
            session_open_ns=opened() - 60 * NS,
            as_of_ns=end,
            coverage_complete=True,
            composite_type=composite,
        )
    with pytest.raises(ValueError, match="native composite"):
        other = Bar(
            BarType.from_str("OTHER.XNAS-5-MINUTE-LAST-INTERNAL"),
            Price.from_str("6"),
            Price.from_str("7"),
            Price.from_str("5"),
            Price.from_str("6.5"),
            Quantity.from_int(100),
            end,
            end,
        )
        sip.opening_window(
            (other,),
            session_open_ns=opened(),
            as_of_ns=end,
            coverage_complete=True,
            composite_type=composite,
        )


def test_published_local_screen_uses_share_volume_and_exact_inclusive_exclusive_bounds() -> None:
    current, prior, facts = windows()

    def check(c=current, p=prior, f=facts):
        return sip.screen(
            c, p, facts=f, expected_sessions=facts.sessions, as_of_ns=current.known_at_ns
        )

    result = check()
    assert result.rvol == 1 and result.passes_local_filters is True
    assert check(replace(current, open=D(5))).passes_local_filters is False
    assert check(f=replace(facts, atr=D("0.50"))).passes_local_filters is False
    assert check(f=replace(facts, adv=D(999_999))).passes_local_filters is False
    assert check(replace(current, volume=D(99))).passes_local_filters is False
    # A price increase cannot change share RVOL. No close*volume dollar substitution.
    assert check(replace(current, open=D(600), close=D(650))).rvol == result.rvol
    assert check(replace(current, close=D(4))).passes_local_filters is True  # No long-only filter.
    assert result.reason == "local_filters_only_top20_external"
    assert not hasattr(result, "rank") and not hasattr(result, "entry")


def test_unknown_baseline_native_atr_prior_dates_and_future_receipts_stay_unavailable() -> None:
    current, prior, facts = windows()

    def check(c=current, p=prior, f=facts):
        return sip.screen(
            c, p, facts=f, expected_sessions=facts.sessions, as_of_ns=current.known_at_ns
        )

    assert check(p=prior[:-1]).passes_local_filters is None
    assert check(p=tuple(replace(w, volume=D(0)) for w in prior)).rvol is None
    assert check(f=replace(facts, atr=None)).passes_local_filters is None
    assert check(f=replace(facts, known_at_ns=current.known_at_ns + 1)).passes_local_filters is None
    assert (
        check(p=(*prior[:-1], replace(prior[-1], known_at_ns=current.known_at_ns + 1))).rvol is None
    )
    assert check(f=replace(facts, sessions=facts.sessions[:-1])).passes_local_filters is None
    with pytest.raises(ValueError, match="configured completion"):
        replace(current, known_at_ns=opened() + 299 * NS)
    assert {r.name: r.value for r in sip.PARAMETERS} == {
        "opening_window": 5,
        "lookback": 14,
        "open_above": D(5),
        "adv_at_least": D(1_000_000),
        "atr_above": D("0.50"),
        "rvol_at_least": D(1),
        "top_n": 20,
        "denominator": sip.DENOMINATOR,
    }
    assert all(
        r.calibration_state == "PUBLISHED" for r in sip.PARAMETERS if r.name != "denominator"
    )
    assert (
        next(r for r in sip.PARAMETERS if r.name == "denominator").calibration_state
        == "UNCALIBRATED"
    )


def test_screen_refuses_future_current_missing_facts_and_mixed_prior_instruments() -> None:
    current, prior, facts = windows()
    end = current.known_at_ns
    assert (
        sip.screen(
            None, prior, facts=facts, expected_sessions=facts.sessions, as_of_ns=end
        ).passes_local_filters
        is None
    )
    assert (
        sip.screen(
            current, prior, facts=facts, expected_sessions=facts.sessions, as_of_ns=end - 1
        ).rvol
        is None
    )
    for missing in (None, replace(facts, adv=None)):
        result = sip.screen(
            current, prior, facts=missing, expected_sessions=facts.sessions, as_of_ns=end
        )
        assert result.rvol == 1 and result.passes_local_filters is None
    with pytest.raises(ValueError, match="mixed instruments"):
        sip.screen(
            current,
            (replace(prior[0], instrument_id=InstrumentId.from_str("OTHER.XNAS")), *prior[1:]),
            facts=facts,
            expected_sessions=facts.sessions,
            as_of_ns=end,
        )
    with pytest.raises(ValueError, match="completed prior sessions"):
        replace(facts, known_at_ns=opened(facts.sessions[-1]))
    for changes in ({"adv": D(-1)}, {"atr": D("NaN")}):
        with pytest.raises(ValueError):
            replace(facts, **changes)


def test_bars_must_be_close_stamped_last_prices_not_quote_volume() -> None:
    end = opened() + 300 * NS
    source = bar(step=5, internal=True)
    composite = sip.StocksInPlaySpec(sip.PARAMETERS).composite_type(ID)
    for kind in (f"{ID}-5-MINUTE-BID-EXTERNAL", f"{ID}-5-SECOND-LAST-EXTERNAL"):
        invalid = Bar(
            BarType.from_str(kind),
            source.open,
            source.high,
            source.low,
            source.close,
            source.volume,
            end,
            end,
        )
        with pytest.raises(ValueError):
            sip.opening_window(
                (invalid,),
                session_open_ns=opened(),
                as_of_ns=end,
                coverage_complete=True,
                composite_type=composite,
            )
    start_stamped = Bar(
        source.bar_type,
        source.open,
        source.high,
        source.low,
        source.close,
        source.volume,
        opened(),
        opened(),
    )
    assert (
        sip.opening_window(
            (start_stamped,),
            session_open_ns=opened(),
            as_of_ns=end,
            coverage_complete=True,
            composite_type=composite,
        )
        is None
    )


def test_adapter_package_has_no_acquisition_study_runner_or_writer() -> None:
    root = Path(__file__).parents[2] / "src/sextant/research/detectors"
    forbidden = {
        "requests",
        "httpx",
        "alpaca",
        "socket",
        "subprocess",
        "sextant.data",
        "sextant.ledger",
    }
    for path in root.glob("*.py"):
        text = path.read_text()
        assert "upstream checked:" in text
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                names = (
                    [n.name for n in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                assert not any(n == f or n.startswith(f + ".") for n in names for f in forbidden)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"submit_order", "write_text", "write_bytes", "mkdir"}
