"""Proofs for the early-entry ranking e2e harness (research/ranking_e2e).

These pin the harness's protocol identity, cohort/onset arithmetic, baseline
statistics, arm mechanisms and the refusal paths. They do not claim an edge:
the frozen K3 section is detection-only (K3.7), and a trial needs the eight
seal receipts (K3.8), which this session does not have.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.ranking_e2e import arms, bars, baseline, cohort, ledger, metrics, protocol, runner  # noqa: E402

NS = 1_000_000_000
ET = timezone(timedelta(hours=-5), "EST")


def _ns(day: str, hh: int, mm: int) -> int:
    return int(
        datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00").replace(tzinfo=ET).timestamp() * NS
    )


def _write_day(root: Path, day: str, rows: dict[str, list[tuple[int, int, str, str, int]]]) -> None:
    """rows: symbol -> [(minute_of_day_hhmm, open, close, volume)]."""
    payload = {}
    for symbol, bars_ in rows.items():
        payload[symbol] = [
            {
                "t": datetime.fromtimestamp(_ns(day, hh, mm) // NS, tz=UTC).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "o": float(open_),
                "h": float(close),
                "l": float(open_),
                "c": float(close),
                "v": volume,
                "n": 2,
                "vw": float(close),
            }
            for hh, mm, open_, close, volume in bars_
        ]
    d = root / "1min" / day
    d.mkdir(parents=True, exist_ok=True)
    (d / "batch-000.json").write_text(
        json.dumps({"symbols": sorted(payload), "pages": [json.dumps({"bars": payload})]}),
        encoding="utf-8",
    )


def _synthetic_tree(tmp_path: Path) -> Path:
    root = tmp_path / "raw"
    prior = ["2026-11-05", "2026-11-06"]
    for day in prior:
        rows = {
            "OMH": [(4, m, "7.36", "7.36", 1000) for m in range(11)],
            "M2": [(4, m, "19.50", "19.50", 1000) for m in range(11)],
            "CTRL": [(4, m, "10.00", "10.00", 1000) for m in range(11)],
        }
        _write_day(root, day, rows)
    today = {
        "OMH": [
            (4, 0, "7.50", "7.45", 1000),
            (4, 1, "7.46", "7.55", 1000),
            (4, 2, "7.56", "7.60", 1000),
            (4, 3, "7.61", "7.62", 1000),
            (4, 4, "7.63", "7.70", 1000),
            (4, 5, "7.71", "7.72", 1000),
            (4, 6, "7.73", "7.80", 1000),
            (4, 7, "7.81", "7.82", 1000),
        ],
        "M2": [
            (4, 0, "20.00", "20.00", 1000),
            (4, 1, "20.01", "20.02", 1000),
            (4, 2, "20.03", "20.04", 1000),
            (4, 3, "20.05", "20.06", 1000),
            (4, 4, "20.07", "20.08", 1000),
            (4, 5, "20.09", "20.10", 1000),
            (4, 6, "20.11", "21.00", 1000),
            (4, 7, "21.01", "21.02", 1000),
        ],
        "CTRL": [(4, m, "10.00", f"10.{m:02d}", 1000) for m in range(8)],
    }
    _write_day(root, "2026-11-09", today)
    return root


def _cohort_json(tmp_path: Path) -> Path:
    path = tmp_path / "cohort.json"
    path.write_text(
        json.dumps(
            {
                "schema": "ranking-e2e.cohort/1",
                "session": "2026-11-09",
                "prior_sessions": ["2026-11-05", "2026-11-06"],
                "candidates": [
                    {
                        "symbol": "OMH",
                        "move": "0.06",
                        "premarket_dollar_volume": "1000",
                        "full_dollar_volume": "1000",
                        "prior_close": "7.36",
                    },
                    {
                        "symbol": "M2",
                        "move": "0.06",
                        "premarket_dollar_volume": "1000",
                        "full_dollar_volume": "1000",
                        "prior_close": "19.50",
                    },
                    {
                        "symbol": "CTRL",
                        "move": "0.01",
                        "premarket_dollar_volume": "1000",
                        "full_dollar_volume": "1000",
                        "prior_close": "10.00",
                    },
                ],
                "truth": ["OMH", "M2"],
                "controls": ["CTRL"],
            }
        ),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------- protocol
def test_protocol_hashes_reproduce_the_frozen_bytes() -> None:
    doc = ROOT / "docs" / "research" / "2026-11-06-ranking.md"
    raw = doc.read_bytes()
    k2 = protocol.extract_section(raw, b"# K2 historical")
    assert hashlib.sha256(k2).hexdigest() == protocol.K2_SECTION_SHA256
    if b"# K3 " in raw:
        k3 = protocol.extract_section(raw, b"# K3 ", stop=b"## K2 preregistration")
        assert hashlib.sha256(k3).hexdigest() == protocol.K3_SECTION_SHA256


def test_protocol_extracts_the_k3_section_up_to_the_k2_fold() -> None:
    raw = (
        b"preamble\n# K3 test\nbody\n\n## K2 preregistration, frozen\nold\n# K2 historical\nrest\n"
    )
    assert protocol.extract_section(raw, b"# K3 ", stop=b"## K2 preregistration") == (
        b"# K3 test\nbody\n\n"
    )
    with pytest.raises(protocol.ProtocolError):
        protocol.extract_section(raw, b"# K3 absent")


# ------------------------------------------------------------------ cohort
def test_cohort_loads_truth_controls_and_hash(tmp_path: Path) -> None:
    c = cohort.load_cohort(_cohort_json(tmp_path))
    assert c.session == date(2026, 11, 9)
    assert [r.symbol for r in c.truth] == ["OMH", "M2"]
    assert [r.symbol for r in c.controls] == ["CTRL"]
    assert c.truth[0].prior_close == D("7.36")
    assert c.by_symbol["OMH"].move == D("0.06")
    assert len(c.cohort_hash) == 64


def test_session_list_hash_is_order_independent() -> None:
    a = cohort.session_list_hash([date(2026, 11, 5), date(2026, 11, 6)])
    b = cohort.session_list_hash([date(2026, 11, 6), date(2026, 11, 5)])
    assert a == b and len(a) == 64


# ---------------------------------------------------------------- baseline
def test_mean_and_median_include_zero_sessions() -> None:
    curves = {"OMH": ((0, 100, 300), (0, 0, 100), (0, 200, 500))}
    mean = baseline.MeanCurveBaseline(curves, feed="sip", known_at=0, provenance="test")
    med = baseline.MedianCurveBaseline(curves, feed="sip", known_at=0, provenance="test")
    mean_60 = mean.cumulative("OMH", "PRE", 60)
    med_60 = med.cumulative("OMH", "PRE", 60)
    mean_120 = mean.cumulative("OMH", "PRE", 120)
    med_120 = med.cumulative("OMH", "PRE", 120)
    assert mean_60 is not None and mean_60.dollar_volume == D("100")
    assert med_60 is not None and med_60.dollar_volume == D("100")
    assert mean_120 is not None and mean_120.dollar_volume == D("300")
    assert med_120 is not None and med_120.dollar_volume == D("300")
    assert mean.cumulative("OMH", "PRE", 240) is None
    zero = baseline.MeanCurveBaseline(
        {"Z": ((0, 0), (0, 0), (0, 0))}, feed="sip", known_at=0, provenance="t"
    )
    zero_60 = zero.cumulative("Z", "PRE", 60)
    assert zero_60 is not None and zero_60.dollar_volume == D("0")


# ------------------------------------------------------------------- arms
def test_gap_arm_uses_the_first_open_once() -> None:
    arm = arms.GapArm()
    first = bars.Bar("OMH", 0, D("7.50"), D("7.50"), D("7.50"), D("7.50"), 100, 1, D("7.50"))
    later = bars.Bar("OMH", 60 * NS, D("8.00"), D("8.00"), D("8.00"), D("8.00"), 100, 1, D("8.00"))
    flag = arm.observe(first, D("7.36"))
    assert flag is not None and flag.price == D("7.50") and flag.gap == D("7.50") / D("7.36") - 1
    assert arm.observe(first, D("7.36")) is None
    assert arm.observe(later, D("7.36")) is None
    assert arms.GapArm().observe(first, D("7.50")) is None


def test_page_cusum_recurrence_and_alarm() -> None:
    c = arms.PageCusum(k=D("0.1"), h=D("0.5"))
    assert c.update(D("0.1")) is False
    assert c.update(D("0.1")) is False  # S=0.0
    assert c.update(D("1.0")) is True  # S=0.9 > 0.5
    assert c.update(D("0.0")) is False  # alarm is latched once


def test_keep_alive_retains_only_through_incomplete_inputs() -> None:
    ka = arms.KeepAlive(top_n=2)
    first = ka.update(rank={"A": 1, "B": 2, "C": 3}, qualified={"A", "B", "C"})
    assert first == {"A", "B"}
    # B's row disappears (incomplete input) and B stays qualified -> retained.
    second = ka.update(rank={"A": 1, "C": 3}, qualified={"A", "B", "C"})
    assert second == {"A", "B"}
    # B's row is computable but rank 3, no longer entry-qualified -> dropped.
    third = ka.update(rank={"A": 1, "B": 3, "C": 3}, qualified={"A", "C"})
    assert third == {"A"}


def test_keep_alive_membership_does_not_require_entry_qualification() -> None:
    ka = arms.KeepAlive(top_n=2)
    members = ka.update(rank={"A": 1}, qualified=set())
    assert members == {"A"}


# ---------------------------------------------------------------- metrics
def test_percentile_is_named_linear_interpolation() -> None:
    assert metrics.percentile([1, 2, 3, 4], 50) == D("2.5")
    assert metrics.percentile([1, 2, 3, 4], 90) == D("3.7")
    assert metrics.percentile([], 50) is None


def test_recall_latency_and_false_flags() -> None:
    onsets = {"OMH": 100, "M2": 200}
    flags = {"OMH": 90, "M2": 210, "CTRL": 50}
    rec = metrics.detection_metrics(onsets, flags, controls=["CTRL"], session_hours=D("2"))
    assert rec.detected == 1 and rec.censored == 1
    assert rec.recall == D("0.5")
    assert rec.p50_latency_s == D("10") and rec.p90_latency_s == D("10")
    assert rec.false_flags == 1 and rec.false_flags_per_symbol_hour == D("0.5")


# ----------------------------------------------------------------- runner
def test_synthetic_runner_emits_generations_and_refuses_a_trial(tmp_path: Path) -> None:
    root = _synthetic_tree(tmp_path)
    cpath = _cohort_json(tmp_path)
    out = tmp_path / "out"
    result = runner.run_session(
        cohort_path=cpath,
        bars_root=root,
        reg_path=ROOT / "lanes" / "tradingview" / "k2-ranking.params.json",
        out_dir=out,
        verify_protocol=False,
    )
    assert result.session == date(2026, 11, 9)
    assert result.onsets["OMH"] == _ns("2026-11-09", 4, 7)
    assert result.onsets["M2"] == _ns("2026-11-09", 4, 7)
    assert result.truth_count == 2 and result.control_count == 1
    assert (out / "generations.jsonl").exists() and (out / "session.json").exists()
    assert result.rows["OMH"]["k2_rank_at_onset"] is not None
    assert result.arms["gap"]["OMH"]["flag_ts"] == _ns("2026-11-09", 4, 1)
    assert result.arms["mean"]["status"] == "MODELED"
    assert result.arms["page"]["status"] == "NOT_RUN"
    assert result.arms["ofi"]["status"] == "NOT_IN_FROZEN_PROTOCOL"
    assert result.trial_status == "NOT_RUN"
    assert result.trial_row["days"] == [] and result.trial_row["objective"] is None


def test_ledger_append_requires_a_custodian_ruling() -> None:
    row = ledger.detection_row(
        arm_id="page_cusum",
        arm_run_id="run",
        implementation_sha="a" * 40,
        block_set_id="blocks",
        session_list_sha256="c" * 64,
    )
    assert row["tier"] == "MODELED" and row["objective"] is None
    with pytest.raises(ledger.LedgerRefused):
        ledger.append(row, path=None, custodian_ruling=None)


def test_build_cohort_from_metrics_and_daily_closes() -> None:
    from research.ranking_e2e.build_cohort import build_cohort

    metrics = {
        "candidates": [
            {
                "symbol": "AAA",
                "move": "0.10",
                "last_close": "11.00",
                "premarket_dollar_volume": "2000000.00",
                "full_dollar_volume": "3000000.00",
            },
            {
                "symbol": "BBB",
                "move": "0.01",
                "last_close": "20.20",
                "premarket_dollar_volume": "1500000.00",
                "full_dollar_volume": "2500000.00",
            },
            {
                "symbol": "CCC",
                "move": "0.20",
                "last_close": "12.00",
                "premarket_dollar_volume": "100.00",
                "full_dollar_volume": "200.00",
            },
        ],
        "primary": {"cohort": 1},
        "secondary": {"cohort": 1},
    }
    daily = {"AAA": D("10.00"), "BBB": D("20.00")}
    cohort = build_cohort(
        metrics,
        daily,
        session=date(2026, 11, 9),
        prior_sessions=(date(2026, 11, 6),),
    )
    assert [row["symbol"] for row in cohort["candidates"]] == ["AAA", "BBB", "CCC"]
    assert cohort["truth"] == ["AAA"]
    assert cohort["controls"] == ["BBB"]
    assert cohort["candidates"][0]["prior_close"] == "10.00"
    assert cohort["candidates"][2]["prior_close"] == "10.0000"  # 12.00 / 1.20


def test_runner_cli_writes_the_report(tmp_path: Path) -> None:
    root = _synthetic_tree(tmp_path)
    cpath = _cohort_json(tmp_path)
    out = tmp_path / "cli"
    code = runner.main(
        [
            "--cohort",
            str(cpath),
            "--bars-root",
            str(root),
            "--registry",
            str(ROOT / "lanes" / "tradingview" / "k2-ranking.params.json"),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert (out / "session.json").exists()
