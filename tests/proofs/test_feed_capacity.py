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


def _lag(
    *,
    count: int,
    p50: int,
    p99: int | None = None,
    p999: int | None = None,
    max_ns: int | None = None,
    hist: dict[str, int] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "count": count,
        "p50": p50,
        "p95": p99 if p99 is not None else p50,
        "p99": p99 if p99 is not None else p50,
        "p999": p999 if p999 is not None else p50,
        "max": max_ns if max_ns is not None else p50,
    }
    if hist is not None:
        record["hist_ms"] = hist
    return record


def _second(
    second: int,
    *,
    trades: int = 1,
    quotes: int = 1,
    messages: int | None = None,
    p50: int = 10 * _MS,
    p99: int | None = None,
    p999: int | None = None,
    max_ns: int | None = None,
    service_max: int = 2 * _MS,
    service_p99: int | None = None,
    utilization: float = 0.01,
    hist: dict[str, int] | None = None,
    failures: int = 0,
) -> dict[str, Any]:
    count = messages if messages is not None else trades + quotes
    entry = _lag(
        count=count,
        p50=p50,
        p99=p99,
        p999=p999,
        max_ns=max_ns if max_ns is not None else max(p50, p99 if p99 is not None else p50),
        hist=hist if hist is not None else {"10": count},
    )
    return {
        "kind": "second",
        "second": second,
        "partial": False,
        "trades": trades,
        "quotes": quotes,
        "messages": count,
        "symbols_seen": 3,
        "rate_mps": float(count),
        "lag_entry_ns": entry,
        "lag_init_ns": _lag(
            count=count,
            p50=p50,
            p99=p99,
            p999=p999,
            max_ns=max_ns if max_ns is not None else p50,
        ),
        "service_ns": {
            "count": count,
            "sum": int(utilization * _S),
            "p99": service_p99 if service_p99 is not None else service_max,
            "max": service_max,
        },
        "utilization": utilization,
        "gap_max_ns": 0,
        "gap_samples": 0,
        "failures": failures,
        "dropped_quotes": 0,
    }


def _symbols(flows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"kind": "symbols", "symbols_seen": len(flows), "gap_max_ns": 0, "symbols": flows}


def _write(tmp_path: Path, *records: dict[str, Any]) -> Path:
    path = tmp_path / "feed-tap.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return path


def _flat(seconds: int, *, p50: int = 10 * _MS) -> list[dict[str, Any]]:
    return [
        _second(_OPEN + index, p50=p50 + (5 * _MS if index % 2 else 0)) for index in range(seconds)
    ]


def _report(tmp_path: Path, records: list[dict[str, Any]], *, bound_s: float = 5.0) -> Any:
    flows = {"AAA": {"trades": 3, "quotes": 3, "messages": 6, "max_gap_ns": _MS}}
    sidecar = load(_write(tmp_path, _symbols(flows), *records))
    return evaluate(sidecar, entry_input_max_age_s=bound_s)


def test_load_skips_a_torn_line_and_keeps_the_richer_duplicate_second(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _second(_OPEN, messages=2),
        _second(_OPEN + 1, messages=5),
        _second(_OPEN, messages=7),
        _symbols({"AAA": {"trades": 1, "quotes": 1, "messages": 2, "max_gap_ns": 0}}),
    )
    path.write_text(path.read_text() + '{"kind": "second", "sec')

    sidecar = load(path)

    assert [second.second for second in sidecar.seconds] == [_OPEN, _OPEN + 1]
    assert sidecar.seconds[0].messages == 7
    assert sidecar.symbols["AAA"].trades == 1
    assert sidecar.malformed_lines == 1


def test_load_tolerates_a_missing_symbols_line(tmp_path: Path) -> None:
    sidecar = load(_write(tmp_path, _second(_OPEN)))

    assert len(sidecar.seconds) == 1
    assert sidecar.symbols == {}


def test_criterion_one_passes_a_receipt_lag_inside_both_bounds(tmp_path: Path) -> None:
    records = [_second(_OPEN + index, hist={"100": 1000}) for index in range(10)]

    report = evaluate(load(_write(tmp_path, *records)), entry_input_max_age_s=5.0)
    check = report.checks[0]

    assert check.verdict == "PASS"
    assert "101" in check.detail  # the bin's upper edge, in ms
    assert "5.0 s" in check.detail


def test_criterion_one_fails_when_the_tail_lag_crosses_one_second(tmp_path: Path) -> None:
    records = [_second(_OPEN + index, hist={"100": 995, "1500": 5}) for index in range(10)]

    report = evaluate(load(_write(tmp_path, *records)), entry_input_max_age_s=5.0)

    assert report.checks[0].verdict == "FAIL"
    assert "1501" in report.checks[0].detail
    assert report.overall == "FAIL"


def test_criterion_one_is_unknown_without_a_histogram(tmp_path: Path) -> None:
    record = _second(_OPEN, hist={})
    record["lag_entry_ns"].pop("hist_ms")

    report = evaluate(load(_write(tmp_path, record)), entry_input_max_age_s=5.0)

    assert report.checks[0].verdict == "UNKNOWN"


def test_criterion_two_passes_service_under_fifty_ms_and_utilization_under_one(
    tmp_path: Path,
) -> None:
    records = [_second(_OPEN + index, service_max=10 * _MS, utilization=0.2) for index in range(10)]

    report = evaluate(load(_write(tmp_path, *records)), entry_input_max_age_s=5.0)

    assert report.checks[1].verdict == "PASS"
    assert "10.0 ms" in report.checks[1].detail
    assert "0.20" in report.checks[1].detail


@pytest.mark.parametrize(
    ("service_max", "utilization"),
    [(60 * _MS, 0.2), (10 * _MS, 1.0), (10 * _MS, 1.2)],
)
def test_criterion_two_fails_a_breached_service_or_utilization_bound(
    tmp_path: Path, service_max: int, utilization: float
) -> None:
    record = _second(_OPEN, service_max=service_max, utilization=utilization)

    report = evaluate(load(_write(tmp_path, record)), entry_input_max_age_s=5.0)

    assert report.checks[1].verdict == "FAIL"


def test_criterion_three_passes_a_flat_first_hour(tmp_path: Path) -> None:
    report = _report(tmp_path, _flat(300))

    assert report.checks[2].verdict == "PASS"
    assert "09:30-09:35" in report.checks[2].detail
    assert "first hour" in report.checks[2].detail


def test_criterion_three_fails_a_monotone_rise_across_the_five_minute_window(
    tmp_path: Path,
) -> None:
    records = [_second(_OPEN + index, p50=(index + 1) * _MS) for index in range(300)]

    report = _report(tmp_path, records)

    assert report.checks[2].verdict == "FAIL"
    assert report.overall == "FAIL"


def test_criterion_three_can_fail_only_the_first_hour_window(tmp_path: Path) -> None:
    flat = _flat(300)
    late_rise = [_second(_OPEN + 1800 + index, p50=(index + 1) * _MS) for index in range(300)]

    report = _report(tmp_path, flat + late_rise)

    detail = report.checks[2].detail
    assert report.checks[2].verdict == "FAIL"
    assert "09:30-09:35: PASS" in detail
    assert "first hour: FAIL" in detail


def test_criterion_three_is_unknown_with_too_few_seconds(tmp_path: Path) -> None:
    report = _report(tmp_path, _flat(10))

    assert report.checks[2].verdict == "UNKNOWN"


def test_criterion_four_excludes_symbols_that_did_not_trade(tmp_path: Path) -> None:
    flows = {
        "AAA": {"trades": 2, "quotes": 5, "messages": 7, "max_gap_ns": 2 * _S},
        "BBB": {"trades": 0, "quotes": 3, "messages": 3, "max_gap_ns": 600 * _S},
    }

    report = evaluate(
        load(_write(tmp_path, _second(_OPEN), _symbols(flows))), entry_input_max_age_s=5.0
    )

    check = report.checks[3]
    assert check.verdict == "PASS"
    assert "1/2" in check.detail
    assert "AAA" not in check.detail
    assert "BBB" not in check.detail


def test_criterion_four_fails_a_traded_symbol_over_the_bound(tmp_path: Path) -> None:
    flows = {"AAA": {"trades": 2, "quotes": 5, "messages": 7, "max_gap_ns": 6 * _S}}

    report = evaluate(
        load(_write(tmp_path, _second(_OPEN), _symbols(flows))), entry_input_max_age_s=5.0
    )

    assert report.checks[3].verdict == "FAIL"
    assert "6.0 s" in report.checks[3].detail


def test_criterion_four_is_unknown_without_the_symbols_line(tmp_path: Path) -> None:
    report = evaluate(load(_write(tmp_path, _second(_OPEN))), entry_input_max_age_s=5.0)

    assert report.checks[3].verdict == "UNKNOWN"


def test_criterion_five_fails_on_a_feed_failure(tmp_path: Path) -> None:
    records = [_second(_OPEN + index) for index in range(5)]
    records[2]["failures"] = 1

    report = evaluate(load(_write(tmp_path, *records)), entry_input_max_age_s=5.0)

    assert report.checks[4].verdict == "FAIL"
    assert "1" in report.checks[4].detail


def test_criterion_five_is_unknown_on_a_whole_socket_silence(tmp_path: Path) -> None:
    records = [_second(_OPEN + index) for index in range(3)]
    records += [_second(_OPEN + 20 + index) for index in range(3)]

    report = evaluate(load(_write(tmp_path, *records)), entry_input_max_age_s=5.0)

    assert report.checks[4].verdict == "UNKNOWN"
    assert "17" in report.checks[4].detail  # 17 silent seconds between the two runs


def test_criterion_six_is_not_applicable_and_does_not_fail_the_report(tmp_path: Path) -> None:
    report = _report(tmp_path, _flat(300))

    assert report.checks[5].verdict == "NOT-APPLICABLE"
    assert report.overall == "PASS"


def test_a_sustained_rise_after_the_first_hour_is_an_overload(tmp_path: Path) -> None:
    flat = _flat(300)
    ramp = [_second(_OPEN + 5400 + index, p50=(index + 1) * _MS) for index in range(180)]

    report = _report(tmp_path, flat + ramp)

    # The pre-registered first-hour windows stay flat; the three-minute rule still fires.
    assert report.checks[2].verdict == "PASS"
    assert report.overload is True
    assert any("3-minute" in reason or "sustained" in reason for reason in report.overload_reasons)


def test_three_stale_seconds_after_a_stall_are_an_overload(tmp_path: Path) -> None:
    records = _flat(30)
    records += [_second(_OPEN + 60 + index, p50=6 * _S) for index in range(3)]
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
    flows = {"SECRETSYMBOL": {"trades": 1, "quotes": 1, "messages": 2, "max_gap_ns": 0}}
    path = _write(tmp_path, *_flat(300), _symbols(flows))

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
