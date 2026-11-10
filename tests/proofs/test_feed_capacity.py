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
    p99: int = 10 * _MS,
    p999: int | None = None,
    max_ns: int | None = None,
    service_sum: int | None = None,
    service_max: int = 2 * _MS,
    failures: int = 0,
    partial: bool = False,
) -> dict[str, Any]:
    messages = trades + quotes
    longest = p99 if max_ns is None else max_ns
    return {
        "kind": "second",
        "second": second,
        "partial": partial,
        "trades": trades,
        "quotes": quotes,
        "symbols_seen": 3,
        "lag_ns": {
            "count": messages,
            "p99": p99,
            "p999": p99 if p999 is None else p999,
            "max": longest,
        },
        "service_ns": {
            "sum": messages * 1_000 if service_sum is None else service_sum,
            "max": service_max,
        },
        "failures": failures,
    }


def _symbols(flows: dict[str, dict[str, Any]], *, reconnects: int | None = 0) -> dict[str, Any]:
    return {
        "kind": "symbols",
        "symbols_seen": len(flows),
        "reconnects": reconnects,
        "symbols": flows,
    }


def _write(tmp_path: Path, *records: dict[str, Any]) -> Path:
    path = tmp_path / "feed-tap.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return path


def _flat(seconds: int, *, p99: int = 10 * _MS) -> list[dict[str, Any]]:
    return [
        _second(_OPEN + index, p99=p99 + (5 * _MS if index % 2 else 0)) for index in range(seconds)
    ]


def _flows(gap_ns: int | None = _MS) -> dict[str, dict[str, Any]]:
    return {
        "AAA": {"last_ts_event_ns": _OPEN * _S, "max_gap_ns": gap_ns},
        "BBB": {"last_ts_event_ns": _OPEN * _S, "max_gap_ns": None},
    }


def _report(tmp_path: Path, records: list[dict[str, Any]], *, bound_s: float = 5.0) -> Any:
    sidecar = load(_write(tmp_path, _symbols(_flows()), *records))
    return evaluate(sidecar, entry_input_max_age_s=bound_s)


def test_load_skips_a_torn_line_and_keeps_the_richer_duplicate_second(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _second(_OPEN, trades=1, quotes=1),
        _second(_OPEN + 1, trades=1, quotes=1),
        _second(_OPEN, trades=3, quotes=4),
        _symbols(_flows()),
    )
    path.write_text(path.read_text() + '{"kind": "second", "sec')

    sidecar = load(path)

    assert [second.second for second in sidecar.seconds] == [_OPEN, _OPEN + 1]
    assert sidecar.seconds[0].messages == 7
    assert sidecar.symbols["AAA"].max_gap_ns == _MS
    assert sidecar.reconnects == 0
    assert sidecar.malformed_lines == 1


def test_load_tolerates_a_missing_symbols_line(tmp_path: Path) -> None:
    sidecar = load(_write(tmp_path, _second(_OPEN)))

    assert len(sidecar.seconds) == 1
    assert sidecar.symbols == {}
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


def test_criterion_one_is_unknown_when_a_measured_second_has_no_lag(tmp_path: Path) -> None:
    records = _flat(3)
    records[1]["lag_ns"] = {"count": 0, "p99": None, "p999": None, "max": None}

    report = _report(tmp_path, records)

    assert report.checks[0].verdict == "UNKNOWN"
    assert "no receipt lag" in report.checks[0].detail


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
    record = _second(_OPEN)
    record["service_ns"] = {"sum": 0, "max": None}

    report = _report(tmp_path, [record])

    assert report.checks[1].verdict == "UNKNOWN"
    assert "no service sample" in report.checks[1].detail


def test_criterion_three_passes_a_flat_first_hour(tmp_path: Path) -> None:
    report = _report(tmp_path, _flat(300))

    assert report.checks[2].verdict == "PASS"
    assert "09:30-09:35" in report.checks[2].detail
    assert "first hour" in report.checks[2].detail


def test_criterion_three_fails_a_monotone_rise_across_the_five_minute_window(
    tmp_path: Path,
) -> None:
    records = [_second(_OPEN + index, p99=(index + 1) * _MS) for index in range(300)]

    report = _report(tmp_path, records)

    assert report.checks[2].verdict == "FAIL"


def test_criterion_three_can_fail_only_the_first_hour_window(tmp_path: Path) -> None:
    late_rise = [_second(_OPEN + 1800 + index, p99=(index + 1) * _MS) for index in range(300)]

    report = _report(tmp_path, [*_flat(300), *late_rise])

    detail = report.checks[2].detail
    assert report.checks[2].verdict == "FAIL"
    assert "09:30-09:35: PASS" in detail
    assert "first hour: FAIL" in detail


def test_criterion_three_is_unknown_with_too_few_seconds(tmp_path: Path) -> None:
    report = _report(tmp_path, _flat(10))

    assert report.checks[2].verdict == "UNKNOWN"


def test_criterion_four_needs_a_measurable_gap(tmp_path: Path) -> None:
    report = _report(tmp_path, [_second(_OPEN)])

    check = report.checks[3]
    assert check.verdict == "PASS"
    assert "1/2" in check.detail
    assert "AAA" not in check.detail
    assert "BBB" not in check.detail


def test_criterion_four_fails_a_symbol_over_the_bound(tmp_path: Path) -> None:
    sidecar = load(_write(tmp_path, _second(_OPEN), _symbols(_flows(6 * _S))))

    report = evaluate(sidecar, entry_input_max_age_s=5.0)

    assert report.checks[3].verdict == "FAIL"
    assert "6.0 s" in report.checks[3].detail


def test_criterion_four_is_unknown_without_the_symbols_line(tmp_path: Path) -> None:
    report = evaluate(load(_write(tmp_path, _second(_OPEN))), entry_input_max_age_s=5.0)

    assert report.checks[3].verdict == "UNKNOWN"


def test_criterion_five_fails_on_a_feed_failure(tmp_path: Path) -> None:
    records = [_second(_OPEN + index) for index in range(5)]
    records[2]["failures"] = 1

    report = _report(tmp_path, records)

    assert report.checks[4].verdict == "FAIL"
    assert "1" in report.checks[4].detail


def test_criterion_five_fails_on_a_reconnect(tmp_path: Path) -> None:
    sidecar = load(_write(tmp_path, _second(_OPEN), _symbols(_flows(), reconnects=2)))

    report = evaluate(sidecar, entry_input_max_age_s=5.0)

    assert report.checks[4].verdict == "FAIL"
    assert "2" in report.checks[4].detail


def test_criterion_five_is_unknown_on_a_whole_socket_silence(tmp_path: Path) -> None:
    records = [_second(_OPEN + index) for index in range(3)]
    records += [_second(_OPEN + 20 + index) for index in range(3)]

    report = _report(tmp_path, records)

    assert report.checks[4].verdict == "UNKNOWN"
    assert "17" in report.checks[4].detail  # 17 silent seconds between the two runs


def test_criterion_five_is_unknown_when_reconnects_were_not_observable(tmp_path: Path) -> None:
    sidecar = load(_write(tmp_path, *[_second(_OPEN)], _symbols(_flows(), reconnects=None)))

    report = evaluate(sidecar, entry_input_max_age_s=5.0)

    assert report.checks[4].verdict == "UNKNOWN"
    assert "reconnect" in report.checks[4].detail


def test_criterion_six_is_not_applicable_and_does_not_fail_the_report(tmp_path: Path) -> None:
    report = _report(tmp_path, _flat(300))

    assert report.checks[5].verdict == "NOT-APPLICABLE"
    assert report.overall == "PASS"


def test_a_sustained_rise_after_the_first_hour_is_an_overload(tmp_path: Path) -> None:
    ramp = [_second(_OPEN + 5400 + index, p99=(index + 1) * _MS) for index in range(180)]

    report = _report(tmp_path, [*_flat(300), *ramp])

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


def test_main_prints_each_criterion_without_a_symbol_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(
        tmp_path,
        *_flat(300),
        _symbols({"SECRETSYMBOL": {"last_ts_event_ns": 0, "max_gap_ns": _MS}}),
    )

    code = main([str(path), "--entry-input-max-age-s", "5"])

    out = capsys.readouterr().out
    assert code == 0
    assert "criterion 1" in out
    assert "NOT-APPLICABLE" in out
    assert "SECRETSYMBOL" not in out


def test_main_returns_one_on_a_failed_criterion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, _second(_OPEN, service_max=60 * _MS))

    code = main([str(path), "--entry-input-max-age-s", "5"])

    assert code == 1
    assert "FAIL" in capsys.readouterr().out


def test_main_returns_two_on_an_unknown_criterion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, _second(_OPEN))

    code = main([str(path), "--entry-input-max-age-s", "5"])

    assert code == 2
    assert "UNKNOWN" in capsys.readouterr().out


def test_main_requires_the_entry_bound(tmp_path: Path) -> None:
    path = _write(tmp_path, _second(_OPEN))

    with pytest.raises(SystemExit) as exit_info:
        main([str(path)])

    assert exit_info.value.code == 2
