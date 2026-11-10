"""Proofs for the read-only capacity analyzer; it reads a sidecar file and prints numbers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from sextant.paper.feed_capacity import evaluate, load, main

_ET = ZoneInfo("America/New_York")
_OPEN = int(datetime(2026, 11, 9, 9, 30, tzinfo=_ET).timestamp())
_MS = 1_000_000
_S = 1_000_000_000


def _second(
    second: int,
    *,
    trades: int = 2,
    quotes: int = 2,
    extra_trades: int = 0,
    extra_quotes: int = 0,
    p99: int = 10 * _MS,
    p999: int | None = None,
    max_ns: int | None = None,
    service_sum: int | None = None,
    service_max: int | None = 2 * _MS,
    failures: int = 0,
    partial: bool = False,
) -> dict[str, Any]:
    own = trades + quotes
    longest = p99 if max_ns is None else max_ns
    return {
        "kind": "second",
        "second": second,
        "partial": partial,
        "trades": trades,
        "quotes": quotes,
        "extra_trades": extra_trades,
        "extra_quotes": extra_quotes,
        "symbols_seen": 3,
        "lag_ns": {
            "count": own,
            "p99": p99,
            "p999": p99 if p999 is None else p999,
            "max": longest,
        },
        "service_ns": {
            "sum": own * 1_000 if service_sum is None else service_sum,
            "max": service_max,
        },
        "failures": failures,
    }


def _symbols(
    *,
    seen: int = 2,
    with_gap: int = 2,
    max_gap: int | None = _MS,
    reconnects: int | None = 0,
    dropped: int = 0,
    write_errors: int = 0,
    init_errors: int = 0,
) -> dict[str, Any]:
    return {
        "kind": "symbols",
        "symbols_seen": seen,
        "symbols_with_gap": with_gap,
        "max_gap_ns": max_gap,
        "reconnects": reconnects,
        "dropped_buckets": dropped,
        "write_errors": write_errors,
        "init_errors": init_errors,
    }


def _write(tmp_path: Path, *records: dict[str, Any]) -> Path:
    path = tmp_path / "feed-tap.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return path


def _flat(seconds: int, *, p99: int = 10 * _MS) -> list[dict[str, Any]]:
    return [
        _second(_OPEN + index, p99=p99 + (5 * _MS if index % 2 else 0)) for index in range(seconds)
    ]


def _set_p99(record: dict[str, Any], p99: int) -> None:
    record["lag_ns"]["p99"] = p99
    record["lag_ns"]["p999"] = p99
    record["lag_ns"]["max"] = p99


def _report(
    tmp_path: Path,
    records: list[dict[str, Any]],
    *,
    bound_s: float = 5.0,
    aggregate: dict[str, Any] | None = None,
) -> Any:
    sidecar = load(_write(tmp_path, _symbols() if aggregate is None else aggregate, *records))
    return evaluate(sidecar, entry_input_max_age_s=bound_s)


def test_load_merges_fragments_of_one_second_instead_of_dropping_one(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _second(_OPEN, trades=1, quotes=1),
        _second(_OPEN + 1, trades=1, quotes=1),
        _second(_OPEN, trades=3, quotes=4, failures=1, service_max=7 * _MS, service_sum=900),
        _symbols(),
    )
    path.write_text(path.read_text() + '{"kind": "second", "sec')

    sidecar = load(path)

    assert [second.second for second in sidecar.seconds] == [_OPEN, _OPEN + 1]
    merged = sidecar.seconds[0]
    assert merged.messages == 9
    assert merged.failures == 1
    assert merged.service_max_ns == 7 * _MS
    assert merged.service_sum_ns == 2_900
    assert merged.lag_count == 9
    assert sidecar.symbols_seen == 2
    assert sidecar.reconnects == 0
    assert sidecar.malformed_lines == 1


def test_load_merges_the_extra_measurement_counts_of_one_second(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _second(_OPEN, trades=1, quotes=1, extra_trades=2, extra_quotes=3),
        _second(_OPEN, trades=3, quotes=4, extra_trades=5, extra_quotes=6),
    )

    second = load(path).seconds[0]

    assert second.own_messages == 9
    assert second.extra_messages == 16
    assert second.messages == 25
    assert second.lag_count == 9


def test_a_second_with_one_own_and_two_hundred_extra_messages_counts_201(
    tmp_path: Path,
) -> None:
    record = _second(_OPEN, trades=1, quotes=0, extra_trades=100, extra_quotes=100)

    sidecar = load(_write(tmp_path, _symbols(), record))
    second = sidecar.seconds[0]
    assert second.own_messages == 1
    assert second.extra_messages == 200
    assert second.messages == 201

    report = evaluate(sidecar, entry_input_max_age_s=5.0)
    assert report.peak.own_mps == 1.0
    assert report.peak.extra_mps == 200.0
    assert report.peak.total_mps == 201.0
    assert report.sustained.total_mps == pytest.approx(201 / 60)
    # The lag histogram covers C's own messages only, so the extras must not make it UNKNOWN.
    assert report.checks[0].verdict == "PASS"
    text = "\n".join(report.lines())
    assert "own 1.0" in text
    assert "extra 200.0" in text
    assert "total 201.0" in text


def test_an_old_format_second_without_extra_fields_counts_zero_extras(tmp_path: Path) -> None:
    old = _second(_OPEN, trades=3, quotes=5)
    del old["extra_trades"]
    del old["extra_quotes"]
    new = _second(_OPEN, trades=3, quotes=5, extra_trades=0, extra_quotes=0)

    old_second = load(_write(tmp_path, old)).seconds[0]
    new_second = load(_write(tmp_path, new)).seconds[0]

    assert old_second == new_second
    assert old_second.extra_messages == 0
    assert old_second.messages == 8

    report = evaluate(load(_write(tmp_path, old)), entry_input_max_age_s=5.0)
    assert report.peak.own_mps == 8.0
    assert report.peak.extra_mps == 0.0
    assert report.peak.total_mps == 8.0
    assert report.sustained.total_mps == pytest.approx(8 / 60)


def test_an_extras_only_second_does_not_degrade_the_own_symbol_safety_checks(
    tmp_path: Path,
) -> None:
    records = [_second(_OPEN + index, trades=1, quotes=1) for index in range(3)]
    extras_only = _second(_OPEN + 3, trades=0, quotes=0, extra_trades=10, extra_quotes=20)
    extras_only["lag_ns"] = {"count": 0, "p99": None, "p999": None, "max": None}
    extras_only["service_ns"] = {"sum": 0, "max": None}

    report = _report(tmp_path, [*records, extras_only])

    assert report.checks[0].verdict == "PASS"
    assert "over 3 measured seconds" in report.checks[0].detail
    assert report.checks[1].verdict == "PASS"
    assert "over 3 measured seconds" in report.checks[1].detail
    assert report.peak.extra_mps == 30.0


def test_load_tolerates_a_missing_symbols_line(tmp_path: Path) -> None:
    sidecar = load(_write(tmp_path, _second(_OPEN)))

    assert len(sidecar.seconds) == 1
    assert sidecar.symbols_seen is None
    assert sidecar.reconnects is None


def test_criterion_one_passes_a_receipt_lag_inside_both_bounds(tmp_path: Path) -> None:
    report = _report(tmp_path, _flat(10))

    check = report.checks[0]
    assert check.verdict == "PASS"
    assert "15.0 ms" in check.detail
    assert "5.0 s" in check.detail


def test_criterion_one_fails_when_the_tail_lag_crosses_one_second(tmp_path: Path) -> None:
    records = _flat(10)
    records[3]["lag_ns"]["p999"] = 1500 * _MS

    report = _report(tmp_path, records)

    assert report.checks[0].verdict == "FAIL"
    assert "1500.0 ms" in report.checks[0].detail
    assert report.overall == "FAIL"


@pytest.mark.parametrize(("p999", "verdict"), [(999 * _MS, "PASS"), (1000 * _MS, "FAIL")])
def test_criterion_one_compares_the_lower_edge_never_the_exclusive_edge(
    tmp_path: Path, p999: int, verdict: str
) -> None:
    records = _flat(10)
    records[3]["lag_ns"]["p999"] = p999

    assert _report(tmp_path, records).checks[0].verdict == verdict


def test_criterion_one_is_unknown_when_a_measured_second_has_no_lag(tmp_path: Path) -> None:
    records = _flat(3)
    records[1]["lag_ns"] = {"count": 0, "p99": None, "p999": None, "max": None}

    report = _report(tmp_path, records)

    assert report.checks[0].verdict == "UNKNOWN"
    assert "lack a receipt lag" in report.checks[0].detail


def test_criterion_one_is_unknown_when_the_lag_covers_fewer_messages(tmp_path: Path) -> None:
    records = _flat(3)
    records[1]["lag_ns"]["count"] = 1

    report = _report(tmp_path, records)

    assert report.checks[0].verdict == "UNKNOWN"


def test_a_partial_second_is_never_measured(tmp_path: Path) -> None:
    records = [*_flat(3), _second(_OPEN + 3, p999=2 * _S, partial=True)]

    report = _report(tmp_path, records)

    assert report.checks[0].verdict == "PASS"


def test_criterion_two_passes_service_under_fifty_ms_and_utilization_under_one(
    tmp_path: Path,
) -> None:
    records = [_second(_OPEN + index, service_sum=_S // 5) for index in range(10)]

    report = _report(tmp_path, records)

    assert report.checks[1].verdict == "PASS"
    assert "2.0 ms" in report.checks[1].detail
    assert "0.20" in report.checks[1].detail


@pytest.mark.parametrize(
    ("service_max", "service_sum"),
    [(60 * _MS, _S // 5), (10 * _MS, _S), (10 * _MS, int(1.2 * _S))],
)
def test_criterion_two_fails_a_breached_service_or_utilization_bound(
    tmp_path: Path, service_max: int, service_sum: int
) -> None:
    record = _second(_OPEN, service_max=service_max, service_sum=service_sum)

    report = _report(tmp_path, [record])

    assert report.checks[1].verdict == "FAIL"


def test_criterion_two_is_unknown_without_a_service_sample(tmp_path: Path) -> None:
    record = _second(_OPEN, service_max=None)
    record["service_ns"]["sum"] = None

    report = _report(tmp_path, [record])

    assert report.checks[1].verdict == "UNKNOWN"
    assert "no service sample" in report.checks[1].detail


def test_criterion_three_passes_a_fully_observed_flat_first_hour(tmp_path: Path) -> None:
    report = _report(tmp_path, _flat(3600))

    assert report.checks[2].verdict == "PASS"
    assert "09:30-09:35" in report.checks[2].detail
    assert "first hour" in report.checks[2].detail


def test_criterion_three_fails_a_monotone_rise_across_the_five_minute_window(
    tmp_path: Path,
) -> None:
    records = _flat(3600)
    for index in range(300):
        _set_p99(records[index], (index + 1) * _MS)

    report = _report(tmp_path, records)

    assert report.checks[2].verdict == "FAIL"


def test_criterion_three_can_fail_only_the_first_hour_window(tmp_path: Path) -> None:
    records = [
        _second(_OPEN + index, p99=10 * _MS if index < 300 else 12 * _MS) for index in range(3600)
    ]

    report = _report(tmp_path, records)

    detail = report.checks[2].detail
    assert report.checks[2].verdict == "FAIL"
    assert "09:30-09:35: PASS" in detail
    assert "first hour: FAIL" in detail


def test_criterion_three_is_unknown_when_the_window_is_not_fully_observed(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path, _flat(300))

    check = report.checks[2]
    assert check.verdict == "UNKNOWN"
    assert "covered 300/3600 seconds" in check.detail


def test_criterion_four_passes_when_every_symbol_carried_a_measurable_gap(tmp_path: Path) -> None:
    report = _report(tmp_path, [_second(_OPEN)])

    check = report.checks[3]
    assert check.verdict == "PASS"
    assert "2/2" in check.detail
    assert "0.001 s" in check.detail


def test_criterion_four_fails_a_symbol_over_the_bound(tmp_path: Path) -> None:
    report = _report(tmp_path, [_second(_OPEN)], aggregate=_symbols(max_gap=6 * _S))

    assert report.checks[3].verdict == "FAIL"
    assert "6.000 s" in report.checks[3].detail


def test_criterion_four_is_unknown_when_the_gap_census_is_partial(tmp_path: Path) -> None:
    report = _report(tmp_path, [_second(_OPEN)], aggregate=_symbols(seen=2, with_gap=1))

    check = report.checks[3]
    assert check.verdict == "UNKNOWN"
    assert "missing, not zero" in check.detail


def test_criterion_four_is_unknown_when_the_sidecar_saw_no_symbol(tmp_path: Path) -> None:
    report = _report(
        tmp_path, [_second(_OPEN)], aggregate=_symbols(seen=0, with_gap=0, max_gap=None)
    )

    assert report.checks[3].verdict == "UNKNOWN"


def test_criterion_four_is_unknown_without_the_symbols_line(tmp_path: Path) -> None:
    sidecar = load(_write(tmp_path, _second(_OPEN)))

    assert evaluate(sidecar, entry_input_max_age_s=5.0).checks[3].verdict == "UNKNOWN"


def test_criterion_five_fails_on_a_feed_failure(tmp_path: Path) -> None:
    records = [_second(_OPEN + index) for index in range(5)]
    records[2]["failures"] = 1

    report = _report(tmp_path, records)

    assert report.checks[4].verdict == "FAIL"
    assert "1" in report.checks[4].detail


def test_criterion_five_fails_on_a_reconnect(tmp_path: Path) -> None:
    report = _report(tmp_path, [_second(_OPEN)], aggregate=_symbols(reconnects=2))

    assert report.checks[4].verdict == "FAIL"
    assert "2" in report.checks[4].detail


def test_criterion_five_is_unknown_when_reconnects_were_not_observable(tmp_path: Path) -> None:
    report = _report(tmp_path, [_second(_OPEN)], aggregate=_symbols(reconnects=None))

    check = report.checks[4]
    assert check.verdict == "UNKNOWN"
    assert "reconnect" in check.detail


def test_criterion_five_is_unknown_on_a_whole_socket_silence(tmp_path: Path) -> None:
    records = [_second(_OPEN + index) for index in range(3)]
    records += [_second(_OPEN + 20 + index) for index in range(3)]

    report = _report(tmp_path, records)

    assert report.checks[4].verdict == "UNKNOWN"
    assert "17" in report.checks[4].detail


def test_criterion_five_is_unknown_when_the_queue_dropped_seconds(tmp_path: Path) -> None:
    report = _report(tmp_path, [_second(_OPEN)], aggregate=_symbols(dropped=1))

    assert report.checks[4].verdict == "UNKNOWN"
    assert "dropped 1" in report.checks[4].detail


def test_criterion_five_is_unknown_when_the_sidecar_failed_to_write(tmp_path: Path) -> None:
    report = _report(tmp_path, [_second(_OPEN)], aggregate=_symbols(write_errors=1))

    assert report.checks[4].verdict == "UNKNOWN"


def test_criterion_five_is_unknown_without_a_failure_counter(tmp_path: Path) -> None:
    record = _second(_OPEN)
    del record["failures"]

    report = _report(tmp_path, [record])

    assert report.checks[4].verdict == "UNKNOWN"
    assert "failure counter" in report.checks[4].detail


def test_a_fully_observed_passing_sidecar_passes_every_criterion(tmp_path: Path) -> None:
    report = _report(tmp_path, _flat(3600))

    assert report.overall == "PASS"
    assert report.checks[5].verdict == "NOT-APPLICABLE"
    assert report.overload is False


def test_a_sustained_rise_after_the_first_hour_is_an_overload(tmp_path: Path) -> None:
    ramp = [_second(_OPEN + 5400 + index, p99=(index + 1) * _MS) for index in range(180)]

    report = _report(tmp_path, [*_flat(3600), *ramp])

    # The pre-registered first-hour windows stay flat; the three-minute rule still fires.
    assert report.checks[2].verdict == "PASS"
    assert report.overload is True
    assert any("3-minute" in reason or "sustained" in reason for reason in report.overload_reasons)


def test_three_stale_seconds_after_a_stall_are_an_overload(tmp_path: Path) -> None:
    records = _flat(30)
    records += [_second(_OPEN + 60 + index, p99=6 * _S) for index in range(3)]
    records += [_second(_OPEN + 70 + index) for index in range(10)]

    report = _report(tmp_path, records)

    assert report.overload is True
    assert any("stale" in reason for reason in report.overload_reasons)


def test_the_bound_is_required_and_must_be_positive(tmp_path: Path) -> None:
    sidecar = load(_write(tmp_path, _second(_OPEN)))

    with pytest.raises(TypeError):
        evaluate(sidecar)  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="positive"):
        evaluate(sidecar, entry_input_max_age_s=0.0)


def test_main_prints_each_criterion_and_the_aggregate_symbol_census(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, _symbols(), *_flat(3600))

    code = main([str(path), "--entry-input-max-age-s", "5"])

    out = capsys.readouterr().out
    assert code == 0
    assert "criterion 1" in out
    assert "NOT-APPLICABLE" in out
    assert "2 symbols (2 with a measured gap)" in out
    assert "overall: PASS" in out


def test_main_returns_one_on_a_failed_criterion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, _symbols(), _second(_OPEN, service_max=60 * _MS))

    code = main([str(path), "--entry-input-max-age-s", "5"])

    assert code == 1
    assert "FAIL" in capsys.readouterr().out


def test_main_returns_two_on_an_unknown_criterion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, _symbols(), _second(_OPEN))

    code = main([str(path), "--entry-input-max-age-s", "5"])

    assert code == 2
    assert "UNKNOWN" in capsys.readouterr().out


def test_main_requires_the_entry_bound(tmp_path: Path) -> None:
    path = _write(tmp_path, _second(_OPEN))

    with pytest.raises(SystemExit) as exit_info:
        main([str(path)])

    assert exit_info.value.code == 2
