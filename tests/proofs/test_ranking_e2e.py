"""Proofs for the early-entry ranking e2e harness (research/ranking_e2e).

These pin the harness's protocol identity, cohort/onset arithmetic, baseline
statistics, arm mechanisms and the refusal paths. They do not claim an edge:
the frozen K3 section is detection-only (K3.7), and a trial needs the eight
seal receipts (K3.8), which this session does not have.

The witness tests marked ``WITNESS`` fail on the prior harness at 5a2167c:
missing prior close derivation, minute-active ranking, the 07:30 gap
substitute, unqualified keep-alive membership, unsigned latency, missing
labels, a detection-only TrialLog row and a CLI that skips protocol
verification by default.
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
    """rows: symbol -> [(start_hh, start_mm, open, close, volume)]."""
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


def _prior_rows() -> dict[str, list[tuple[int, int, str, str, int]]]:
    return {
        "OMH": [(4, m, "7.36", "7.36", 1000) for m in range(11)],
        "M2": [(4, m, "19.50", "19.50", 1000) for m in range(11)],
        "CTRL": [(4, m, "10.00", "10.00", 1000) for m in range(11)],
    }


def _synthetic_tree(tmp_path: Path) -> Path:
    root = tmp_path / "raw"
    for day in ("2026-11-05", "2026-11-06"):
        _write_day(root, day, _prior_rows())
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


def _inactive_tree(tmp_path: Path) -> Path:
    """OMH's last row is 04:01; M2 prints at 04:02.  The 04:03 generation must
    still rank OMH's carried row (WITNESS for full K2 section 5 generations)."""
    root = tmp_path / "inactive"
    for day in ("2026-11-05", "2026-11-06"):
        _write_day(root, day, _prior_rows())
    _write_day(
        root,
        "2026-11-09",
        {
            "OMH": [(4, m, "7.40", f"7.{40 + m:02d}", 1000) for m in range(6)],
            "M2": [(4, 0, "20.00", "20.00", 1000), (4, 5, "20.50", "21.00", 1000)],
            "CTRL": [(4, 0, "10.00", "10.00", 1000)],
        },
    )
    return root


def _cohort_json(tmp_path: Path) -> Path:
    path = tmp_path / "cohort.json"
    labels = {
        "survivor_only": True,
        "pit_verified": False,
        "inference_eligible": False,
    }
    path.write_text(
        json.dumps(
            {
                "schema": "ranking-e2e.cohort/1",
                "session": "2026-11-09",
                "prior_sessions": ["2026-11-05", "2026-11-06"],
                "labels": labels,
                "candidates": [
                    {
                        "symbol": "OMH",
                        "move": "0.06",
                        "premarket_dollar_volume": "1000",
                        "full_dollar_volume": "1000",
                        "prior_close": "7.36",
                        "prior_close_source": "official_prior_daily_close",
                    },
                    {
                        "symbol": "M2",
                        "move": "0.06",
                        "premarket_dollar_volume": "1000",
                        "full_dollar_volume": "1000",
                        "prior_close": "19.50",
                        "prior_close_source": "official_prior_daily_close",
                    },
                    {
                        "symbol": "CTRL",
                        "move": "0.01",
                        "premarket_dollar_volume": "1000",
                        "full_dollar_volume": "1000",
                        "prior_close": "10.00",
                        "prior_close_source": "official_prior_daily_close",
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
def test_cohort_loads_truth_controls_hash_and_labels(tmp_path: Path) -> None:
    c = cohort.load_cohort(_cohort_json(tmp_path))
    assert c.session == date(2026, 11, 9)
    assert [r.symbol for r in c.truth] == ["OMH", "M2"]
    assert [r.symbol for r in c.controls] == ["CTRL"]
    assert c.truth[0].prior_close == D("7.36")
    assert c.truth[0].prior_close_source == "official_prior_daily_close"
    assert c.by_symbol["OMH"].move == D("0.06")
    assert len(c.cohort_hash) == 64
    assert c.labels["pit_verified"] is False


def test_cohort_requires_pit_labels(tmp_path: Path) -> None:  # WITNESS (P1 labels)
    path = _cohort_json(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["labels"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="labels"):
        cohort.load_cohort(path)


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
def test_gap_arm_uses_only_the_fixed_opening_window() -> None:  # WITNESS (P1 gap)
    start = _ns("2026-11-09", 4, 0)
    end = _ns("2026-11-09", 4, 5)
    arm = arms.GapArm(window_start_ns=start, window_end_ns=end)
    later = bars.Bar(
        "OMH",
        _ns("2026-11-09", 7, 30),
        D("8.00"),
        D("8.00"),
        D("8.00"),
        D("8.00"),
        100,
        1,
        D("8.00"),
    )
    assert arm.observe(later, D("7.36")) is None  # 07:30 cannot substitute
    first = bars.Bar("OMH", start, D("7.50"), D("7.50"), D("7.50"), D("7.50"), 100, 1, D("7.50"))
    flag = arm.observe(first, D("7.36"))
    assert flag is not None and flag.ts_ns == start
    assert flag.price == D("7.50") and flag.gap == D("7.50") / D("7.36") - 1
    assert arm.observe(first, D("7.36")) is None
    assert arms.GapArm(window_start_ns=start, window_end_ns=end).observe(first, D("7.50")) is None


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


def test_keep_alive_requires_current_qualification_and_quota() -> None:  # WITNESS (P1)
    ka = arms.KeepAlive(top_n=2)
    assert ka.update(rank={"A": 1}, qualified=set()) == set()
    assert ka.update(rank={"A": 1, "B": 2, "C": 3}, qualified={"A", "B"}) == {"A", "B"}
    assert ka.update(rank={"A": 1}, qualified={"A", "B"}) == {"A", "B"}
    ka.reset()
    assert ka.update(rank={"A": 1}, qualified={"A"}) == {"A"}


# ---------------------------------------------------------------- metrics
def test_percentile_is_named_linear_interpolation() -> None:
    assert metrics.percentile([1, 2, 3, 4], 50) == D("2.5")
    assert metrics.percentile([1, 2, 3, 4], 90) == D("3.7")
    assert metrics.percentile([], 50) is None


def test_signed_latency_late_flag_and_windows() -> None:  # WITNESS (P1 metrics)
    onsets = {"OMH": 100 * NS, "M2": 200 * NS}
    flags = {"OMH": 90 * NS, "M2": 210 * NS, "CTRL": 50 * NS}
    rec = metrics.detection_metrics(onsets, flags, controls=["CTRL"], session_hours=D("2"))
    assert rec.detected == 2 and rec.late == 1 and rec.censored == 0
    assert rec.recall == D("1")
    assert rec.p50_latency_s == D("0")  # signed: -10 and +10
    assert rec.p90_latency_s == D("8")
    assert rec.windows[60]["count"] == 2
    assert rec.per_name_flags == {"OMH": 1, "M2": 1}
    assert rec.false_flags == 1 and rec.false_flags_per_symbol_hour == D("0.5")


def test_censored_only_when_no_flag_at_all() -> None:
    rec = metrics.detection_metrics(
        {"A": 100 * NS, "B": 200 * NS}, {"A": 90 * NS}, controls=[], session_hours=D("1")
    )
    assert rec.detected == 1 and rec.censored == 1 and rec.late == 0
    assert rec.p50_latency_s == D("-10")


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
    assert result.report["label"] == "SYNTHETIC_NOT_VERIFIED"
    assert result.report["protocol"]["verified"] is False
    assert result.rows["OMH"]["k2_rank_at_onset"] is not None
    assert result.arms["gap"]["OMH"]["flag_ts"] == _ns("2026-11-09", 4, 0)
    assert result.arms["mean"]["status"] == "MODELED"
    assert result.arms["page"]["status"] == "NOT_RUN"
    assert result.arms["ofi"]["status"] == "NOT_IN_FROZEN_PROTOCOL"
    assert result.trial_status == "NOT_RUN"
    assert result.trial_row is None
    assert result.report["trial"]["row"] is None


def test_full_generation_ranks_carried_rows(tmp_path: Path) -> None:  # WITNESS (P0-2)
    root = _inactive_tree(tmp_path)
    out = tmp_path / "inactive-out"
    result = runner.run_session(
        cohort_path=_cohort_json(tmp_path),
        bars_root=root,
        reg_path=ROOT / "lanes" / "tradingview" / "k2-ranking.params.json",
        out_dir=out,
        verify_protocol=False,
    )
    lines = [
        json.loads(line)
        for line in (out / "generations-k2-pre.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    at_generation = next(line for line in lines if line["ts_ns"] == _ns("2026-11-09", 4, 6))
    assert at_generation["universe"] == 2
    assert result.rows["M2"]["k2_universe_at_onset"] == 2


def test_runner_cli_verifies_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # WITNESS (P1 CLI)
    root = _synthetic_tree(tmp_path)
    cpath = _cohort_json(tmp_path)
    out = tmp_path / "cli-default"
    # Pin the checkout root at a doc without K3 so this proof still means
    # "verify by default" after the K3 section lands on the branch.
    (tmp_path / "docs" / "research").mkdir(parents=True)
    (tmp_path / "docs" / "research" / "2026-11-06-ranking.md").write_text(
        "# K2 historical\nnot the frozen doc\n", encoding="utf-8"
    )
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "_git_head", lambda: "a" * 40)
    with pytest.raises(protocol.ProtocolError):
        runner.main(
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


def test_runner_cli_writes_the_report_with_the_explicit_override(tmp_path: Path) -> None:
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
            "--no-verify-protocol",
        ]
    )
    assert code == 0
    assert (out / "session.json").exists()


def test_ledger_refuses_every_detection_only_row() -> None:  # WITNESS (custodian ruling)
    with pytest.raises(ledger.LedgerRefused):
        ledger.detection_row(
            arm_id="page_cusum",
            arm_run_id="run",
            implementation_sha="a" * 40,
            block_set_id="blocks",
            session_list_sha256="c" * 64,
        )
    with pytest.raises(ledger.LedgerRefused):
        ledger.append({}, path=None, custodian_ruling="allow")


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
    doc = build_cohort(
        metrics,
        daily,
        session=date(2026, 11, 9),
        prior_sessions=(date(2026, 11, 6),),
    )
    assert [row["symbol"] for row in doc["candidates"]] == ["AAA", "BBB", "CCC"]
    assert doc["truth"] == ["AAA"]
    assert doc["controls"] == ["BBB"]
    assert doc["candidates"][0]["prior_close"] == "10.00"
    assert doc["candidates"][0]["prior_close_source"] == "official_prior_daily_close"
    assert doc["candidates"][2]["prior_close"] is None  # WITNESS (P0-1): no derivation
    assert doc["candidates"][2]["prior_close_source"] == "missing_official_prior_close"
    assert doc["excluded"] == [{"symbol": "CCC", "reason": "missing_official_prior_close"}]
    assert doc["counts"] == {
        "candidates": 3,
        "planned_truth": 1,
        "observed_truth": 1,
        "excluded": 1,
    }
    assert doc["labels"]["pit_verified"] is False
