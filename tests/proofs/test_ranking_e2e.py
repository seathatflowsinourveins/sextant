"""Proofs for the early-entry ranking e2e harness (research/ranking_e2e).

These pin the harness's protocol identity, cohort/onset arithmetic, baseline
statistics, arm mechanisms and the refusal paths. They do not claim an edge:
the frozen K3 section is detection-only (K3.7), and a trial needs the eight
seal receipts (K3.8), which this session does not have.

Tests marked ``WITNESS`` fail on an earlier harness. Round 1 (fail at
5a2167c): missing prior close derivation, minute-active ranking, the 07:30 gap
substitute, unsigned latency, missing labels, a detection-only TrialLog row and
a CLI that skips protocol verification by default. Round 2 (fail at 53b9e8a,
rebased as e80f6ee): keep-alive that never retains, a structural-zero ranking
false-flag rate, baseline availability read from the rank, late flags counted
as recall, segment coverage conferred by a synthetic opening tick, arm (a)
wearing the full rule's name, and a verified run from a dirty tree. Hosted
review (fail at 1e95678): an onset from the 09:29 PRE bar judged in RTH, and
price-path labels read past the replay window's last close.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.ranking_e2e import arms, bars, baseline, cohort, ledger, metrics, protocol, runner  # noqa: E402

NS = 1_000_000_000
ET = timezone(timedelta(hours=-5), "EST")
REGISTRY = ROOT / "lanes" / "tradingview" / "k2-ranking.params.json"


def _ns(day: str, hh: int, mm: int) -> int:
    return int(
        datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00").replace(tzinfo=ET).timestamp() * NS
    )


def _write_day(
    root: Path,
    day: str,
    rows: dict[str, list[tuple[int, int, str, str, int]]],
    *,
    requested: set[str] | None = None,
) -> None:
    """rows: symbol -> [(start_hh, start_mm, open, close, volume)].

    ``requested`` adds symbols the recording asked for but that did not trade
    (no bars); the batch metadata's ``symbols`` list is the recording's
    coverage declaration.
    """
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
    declared = set(payload) | set(requested or ())
    pages = [json.dumps({"bars": payload})] if payload else []
    (d / "batch-000.json").write_text(
        json.dumps({"symbols": sorted(declared), "pages": pages}),
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
    """M2 prints at 04:08 and OMH does not; the 04:09 generation must still rank
    OMH's carried 04:08 row (WITNESS for full K2 section 5 generations)."""
    root = tmp_path / "inactive"
    for day in ("2026-11-05", "2026-11-06"):
        _write_day(root, day, _prior_rows())
    _write_day(
        root,
        "2026-11-09",
        {
            "OMH": [(4, m, "7.40", f"7.{40 + m:02d}", 1000) for m in range(8)],
            "M2": [(4, m, "20.00", "20.00", 1000) for m in range(8)]
            + [(4, 8, "20.50", "21.00", 1000)],
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


def _receipt(
    tmp_path: Path, root: Path, *, day: str = "2026-11-09", data_sha256: str | None = None
) -> Path:
    """The recording's prefix receipt: its window and the recorded day's hash."""
    path = tmp_path / f"prefix-receipt-{root.name}-{day}.json"
    path.write_text(
        json.dumps(
            {
                "schema": "ranking-e2e.prefix-receipt/1",
                "session": day,
                "feed": "sip",
                "timeframe": "1Min",
                "window_et": {"start": "04:00", "end": "11:40"},
                "data_sha256": data_sha256 or runner._day_receipt(root, date.fromisoformat(day)),
                "source": "test fixture: every requested symbol recorded 04:00-11:40 ET",
            }
        ),
        encoding="utf-8",
    )
    return path


def _run(
    tmp_path: Path,
    root: Path,
    cohort_path: Path,
    *,
    out: str,
    registry: Path = REGISTRY,
    receipt: bool = True,
    **kwargs: Any,
) -> runner.SessionResult:
    """Run one synthetic session.  The witnesses also run against the pre-fix
    harness, which has no prefix-receipt input, so the receipt is passed only
    when the code under test accepts it and the witness then fails on a value."""
    extra: dict[str, Any] = {}
    if receipt and "prefix_receipt" in inspect.signature(runner.run_session).parameters:
        extra["prefix_receipt"] = _receipt(tmp_path, root)
    return runner.run_session(
        cohort_path=cohort_path,
        bars_root=root,
        reg_path=registry,
        out_dir=tmp_path / out,
        verify_protocol=kwargs.pop("verify_protocol", False),
        **extra,
        **kwargs,
    )


def _generations(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --------------------------------------------- round-2 witness tree (keep-alive)
KEEP_DAY = "2026-11-09"
KEEP_PRIOR = ("2026-11-04", "2026-11-05", "2026-11-06")


def _fixture_registry(tmp_path: Path) -> Path:
    """Fixture-only gate values so a bar-fidelity name can qualify; never operating values."""
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for row in data["rows"]:
        value = {
            "mover_min_move": "0.01",
            "mover_min_trades_accel": "1",
            "mover_min_dvol_ratio": "1",
        }.get(row["name"])
        if value is not None:
            row["value"] = value
            row["source"] = (
                "test fixture only (tests/proofs/test_ranking_e2e.py); not an operating value"
            )
    path = tmp_path / "fixture-registry.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _keep_tree(tmp_path: Path) -> Path:
    """Six names, three prior sessions, prior close 10.00 for all.

    KEEP qualifies at 04:07, is silent 04:08-04:20, then its 04:20 bar finds no
    trade in the prior acceleration window, so its 04:21 row is not computable
    (``prior_window_zero_trades``) while it crosses +5% (onset 04:21).  SAME and
    LATE are first admitted exactly at their onset.  CTRL is a flat control.
    FAST crosses +5% in its first bar (onset 04:01, not yet computable).  THIN
    traded on one of three prior sessions, so its median normal is zero and its
    mean normal is not.  LATE's first bar starts at 04:02, not at the boundary.
    """
    root = tmp_path / "keep"
    prior = {
        symbol: [(4, m, "10.00", "10.00", 1000) for m in range(11)]
        for symbol in ("KEEP", "SAME", "CTRL", "FAST", "LATE")
    }
    for day in KEEP_PRIOR[:2]:
        # THIN is declared on every prior session; it simply never traded on
        # the first two.  A covered silent session is a zero, not an unknown.
        _write_day(root, day, prior, requested={"THIN"})
    _write_day(
        root, KEEP_PRIOR[2], {**prior, "THIN": [(4, m, "10.00", "10.00", 1000) for m in range(11)]}
    )
    keep_closes = ("10.12", "10.15", "10.18", "10.21", "10.24", "10.27", "10.30", "10.33")
    _write_day(
        root,
        KEEP_DAY,
        {
            "KEEP": [(4, m, close, close, 3000) for m, close in enumerate(keep_closes)]
            + [(4, 20, "10.40", "10.60", 3000)],
            "SAME": [(4, m, "10.00", "10.00", 3000) for m in range(9)]
            + [(4, 9, "10.00", "10.60", 3000)],
            "CTRL": [(4, m, "10.00", "10.00", 1000) for m in range(10)],
            "FAST": [(4, 0, "10.50", "10.60", 3000)]
            + [(4, m, "10.60", "10.60", 3000) for m in range(1, 10)],
            "THIN": [(4, m, "10.00", "10.00", 3000) for m in range(9)]
            + [(4, 9, "10.00", "10.60", 3000)],
            "LATE": [(4, m, "10.00", "10.10", 3000) for m in range(2, 11)]
            + [(4, 11, "10.10", "10.60", 3000)],
        },
    )
    return root


def _keep_cohort(tmp_path: Path) -> Path:
    path = tmp_path / "keep-cohort.json"

    def candidate(symbol: str, move: str) -> dict[str, str]:
        return {
            "symbol": symbol,
            "move": move,
            "premarket_dollar_volume": "1000000",
            "full_dollar_volume": "1000000",
            "prior_close": "10.00",
            "prior_close_source": "official_prior_daily_close",
        }

    truth = ["KEEP", "SAME", "FAST", "THIN", "LATE"]
    path.write_text(
        json.dumps(
            {
                "schema": "ranking-e2e.cohort/1",
                "session": KEEP_DAY,
                "prior_sessions": list(KEEP_PRIOR),
                "labels": {
                    "survivor_only": True,
                    "pit_verified": False,
                    "inference_eligible": False,
                },
                "candidates": [candidate(s, "0.06") for s in truth] + [candidate("CTRL", "0.00")],
                "truth": truth,
                "controls": ["CTRL"],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture(scope="module")
def keep_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, runner.SessionResult]:
    tmp_path = tmp_path_factory.mktemp("keep")
    result = _run(
        tmp_path,
        _keep_tree(tmp_path),
        _keep_cohort(tmp_path),
        out="keep-out",
        registry=_fixture_registry(tmp_path),
    )
    return tmp_path / "keep-out", result


# ---------------------------------------------------------------- protocol
def test_protocol_hashes_reproduce_the_frozen_bytes() -> None:
    doc = ROOT / "docs" / "research" / "2026-11-06-ranking.md"
    raw = doc.read_bytes()
    k2 = protocol.extract_section(raw, b"# K2 historical")
    assert hashlib.sha256(k2).hexdigest() == protocol.K2_SECTION_SHA256
    k3 = protocol.extract_section(raw, b"# K3 ", stop=b"## K2 preregistration")
    assert hashlib.sha256(k3).hexdigest() == protocol.K3_SECTION_SHA256
    assert protocol.verify_protocol(doc).k3_present


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


class _Row:
    """The four fields keep-alive reads from a ranked K2 row."""

    def __init__(self, symbol: str, rank: int, score: str, accel: str = "1", ok: bool = True):
        self.symbol, self.rank = symbol, rank
        self.score, self.trades_accel = D(score), D(accel)
        self.ok = ok


def _ok(row: _Row) -> bool:
    return row.ok


def test_keep_alive_retains_only_an_uncomputable_member_that_last_qualified() -> None:
    ka = arms.KeepAlive(top_n=2)
    # A and B are fresh admits; C is outside the top 2.
    first = ka.update([_Row("A", 1, "9"), _Row("B", 2, "8"), _Row("C", 3, "7")], qualifies=_ok)
    assert first == {"A", "B"} and ka.retained == set()
    # B has no computable row (absent from the ranking): its last computable row
    # qualified, so it is retained through the incomplete input.
    assert ka.update([_Row("A", 1, "9"), _Row("C", 2, "7", ok=False)], qualifies=_ok) == {"A", "B"}
    assert ka.retained == {"B"}
    # B is computable again but no longer qualifies: judged afresh and dropped.
    assert ka.update([_Row("A", 1, "9"), _Row("B", 2, "8", ok=False)], qualifies=_ok) == {"A"}
    # B loses its row again, but it is no longer a member: nothing to keep alive.
    assert ka.update([_Row("A", 1, "9")], qualifies=_ok) == {"A"} and ka.retained == set()
    ka.reset()
    assert ka.update([_Row("C", 1, "7")], qualifies=_ok) == {"C"} and ka.retained == set()


def test_keep_alive_quota_fills_fresh_first_then_k2_order() -> None:  # WITNESS (P1 keep-alive)
    ka = arms.KeepAlive(top_n=3)
    ka.update([_Row("ZED", 1, "9"), _Row("MID", 2, "7"), _Row("ABE", 3, "5")], qualifies=_ok)
    # All three lose their computable rows; one fresh name takes a slot.  Quotas
    # win, so two of the three are retained in K2's own order on their last
    # computable rows (score desc, then trades_accel desc, then symbol), not in
    # alphabetical order, which would keep ABE.
    members = ka.update([_Row("NEW", 1, "1")], qualifies=_ok)
    assert members == {"NEW", "ZED", "MID"}
    assert ka.retained == {"ZED", "MID"}


# ---------------------------------------------------------------- metrics
def test_percentile_is_named_linear_interpolation() -> None:
    assert metrics.percentile([1, 2, 3, 4], 50) == D("2.5")
    assert metrics.percentile([1, 2, 3, 4], 90) == D("3.7")
    assert metrics.percentile([], 50) is None


def test_signed_latency_late_flag_and_windows() -> None:  # WITNESS (P1 recall at onset)
    onsets = {"OMH": 100 * NS, "M2": 200 * NS}
    flags = {"OMH": 90 * NS, "M2": 210 * NS, "CTRL": 50 * NS}
    rec = metrics.detection_metrics(onsets, flags, controls=["CTRL"], session_hours=D("2"))
    assert rec.detected == 2 and rec.late == 1 and rec.censored == 0
    # K3.2 (ii): recall at onset counts a first flag at or before tau only.
    assert rec.detected_at_onset == 1 and rec.recall_at_onset == D("0.5")
    assert rec.ever_detected == D("1")
    assert rec.p50_latency_s == D("0")  # signed: -10 and +10
    assert rec.p90_latency_s == D("8")
    assert rec.windows[60]["count"] == 2
    assert rec.per_name_flags == {"OMH": 1, "M2": 1}
    table = rec.false_flags["all_controls"]
    assert table["flagged"] == 1 and table["per_symbol_hour_session"] == "0.5"
    assert table["per_symbol_hour_coverage"] is None  # no coverage hours supplied
    assert rec.false_flags["denominator_status"] == "DEVELOPMENT_CHOICE_PENDING_U4_SEAL"


def test_censored_only_when_no_flag_at_all() -> None:
    rec = metrics.detection_metrics(
        {"A": 100 * NS, "B": 200 * NS}, {"A": 90 * NS}, controls=[], session_hours=D("1")
    )
    assert rec.detected == 1 and rec.censored == 1 and rec.late == 0
    assert rec.p50_latency_s == D("-10")
    empty = metrics.detection_metrics({}, {}, controls=[], session_hours=D("1"))
    assert empty.recall_at_onset is None and empty.ever_detected is None


def test_false_flag_table_carries_coverage_hours_and_separate_rates() -> None:
    table = metrics.false_flag_table(
        {"C1"},
        controls=["C1", "C2", "C3"],
        never_crossed=["C2", "C3"],
        session_hours=D("2"),
        coverage_hours={"C1": D("1"), "C2": D("0.5"), "C3": D("0")},
        endpoint="test",
    )
    assert table["all_controls"]["flagged"] == 1
    assert table["all_controls"]["per_symbol_hour_session"] == str(D(1) / D(6))
    assert table["all_controls"]["per_symbol_hour_coverage"] == str(D(1) / D("1.5"))
    assert table["all_controls"]["without_rows"] == 1
    assert table["never_crossed"]["flagged"] == 0
    assert table["never_crossed"]["per_symbol_hour_coverage"] == "0"


# ----------------------------------------------------------------- runner
def test_synthetic_runner_emits_generations_and_refuses_a_trial(tmp_path: Path) -> None:
    root = _synthetic_tree(tmp_path)
    result = _run(tmp_path, root, _cohort_json(tmp_path), out="out")
    out = tmp_path / "out"
    assert result.session == date(2026, 11, 9)
    assert result.onsets["OMH"] == _ns("2026-11-09", 4, 7)
    assert result.onsets["M2"] == _ns("2026-11-09", 4, 7)
    assert result.truth_count == 2 and result.control_count == 1
    assert (out / "generations.jsonl").exists() and (out / "session.json").exists()
    assert result.report["label"] == "SYNTHETIC_NOT_VERIFIED"
    assert result.report["protocol"]["verified"] is False
    assert result.report["prefix"]["status"] == "RECEIPTED"
    assert result.rows["OMH"]["k2_rank_at_onset"] is not None
    sub_arm = result.arms["gap_fixed_open_sub_arm"]
    assert sub_arm["flags"]["OMH"]["flag_ts"] == _ns("2026-11-09", 4, 0)
    assert result.arms["mean"]["status"] == "MODELED"
    assert result.arms["page"]["status"] == "NOT_RUN"
    assert result.arms["ofi"]["status"] == "NOT_IN_FROZEN_PROTOCOL"
    assert result.report["entry_protection"]["status"] == "NOT_RUN"
    assert "not on gate" not in result.report["entry_protection"]["reason"]
    assert result.trial_status == "NOT_RUN"
    assert result.trial_row is None
    assert result.report["trial"]["row"] is None


def test_full_generation_ranks_carried_rows(tmp_path: Path) -> None:  # WITNESS (P0-2)
    root = _inactive_tree(tmp_path)
    result = _run(tmp_path, root, _cohort_json(tmp_path), out="inactive-out")
    lines = _generations(tmp_path / "inactive-out" / "generations-k2-pre.jsonl")
    at_generation = next(line for line in lines if line["ts_ns"] == _ns("2026-11-09", 4, 9))
    assert at_generation["universe"] == 2  # M2's new row and OMH's carried row
    assert result.rows["M2"]["k2_universe_at_onset"] == 2


def test_runner_cli_verifies_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # WITNESS (P1 CLI)
    root = _synthetic_tree(tmp_path)
    cpath = _cohort_json(tmp_path)
    out = tmp_path / "cli-default"
    # Pin the checkout root at a doc without K3 so this proof still means
    # "verify by default" now that the K3 section is on the branch.
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
                str(REGISTRY),
                "--out",
                str(out),
            ]
        )


def test_runner_cli_writes_the_report_with_the_explicit_override(tmp_path: Path) -> None:
    root = _synthetic_tree(tmp_path)
    cpath = _cohort_json(tmp_path)
    common = ["--cohort", str(cpath), "--bars-root", str(root), "--registry", str(REGISTRY)]
    out = tmp_path / "cli"
    assert runner.main([*common, "--out", str(out), "--no-verify-protocol"]) == 0
    assert (out / "session.json").exists()
    out2 = tmp_path / "cli-receipt"
    receipt = _receipt(tmp_path, root)
    code = runner.main(
        [*common, "--out", str(out2), "--no-verify-protocol", "--prefix-receipt", str(receipt)]
    )
    report = json.loads((out2 / "session.json").read_text(encoding="utf-8"))
    assert code == 0 and report["prefix"]["status"] == "RECEIPTED"


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


# ------------------------------------------------- round-2 witnesses (run_session)
def test_keep_alive_retains_a_member_whose_row_turns_uncomputable(
    keep_run: tuple[Path, runner.SessionResult],
) -> None:  # WITNESS (P1 keep-alive retention)
    out, result = keep_run
    lines = _generations(out / "generations-k2-pre.jsonl")
    at_0421 = next(line for line in lines if line["ts_ns"] == _ns(KEEP_DAY, 4, 21))
    # KEEP's 04:21 row has no trade in its prior window, so it is not ranked;
    # its last computable row qualified, so keep-alive holds it.
    assert "KEEP" in at_0421["members"] and "KEEP" not in at_0421["top100"]
    assert result.rows["KEEP"]["k2_rank_at_onset"] is None
    assert result.rows["KEEP"]["keepalive_member_at_onset"] is True
    assert "prior_window_zero_trades" in result.rows["KEEP"]["k2_unknown_reasons"]
    assert result.arms["keepalive"]["retained_member_generations"] > 0


def test_keep_alive_persistence_needs_first_entry_strictly_before_onset(
    keep_run: tuple[Path, runner.SessionResult],
) -> None:  # WITNESS (P1 keep-alive denominator)
    _, result = keep_run
    keep = result.arms["keepalive"]
    # Only KEEP entered strictly before its onset; SAME and LATE entered at it.
    assert keep["persistence_denominator"] == 1
    assert result.rows["SAME"]["keepalive_first"] == result.rows["SAME"]["onset_ts"]
    assert result.rows["LATE"]["keepalive_first"] == result.rows["LATE"]["onset_ts"]
    assert keep["persistence_at_onset"] == 1
    assert keep["persistence_rate"] == "1"
    assert keep["entered_at_onset_excluded"] == 2


def test_ranking_false_flags_count_controls_that_enter_the_top_100(
    keep_run: tuple[Path, runner.SessionResult],
) -> None:  # WITNESS (P1 structural-zero false flags)
    _, result = keep_run
    k2 = result.arms["k2"]
    assert D(str(k2["false_flags_per_symbol_hour"])) > 0
    table = k2["false_flags"]
    assert table["all_controls"]["flagged"] == 1 and table["never_crossed"]["flagged"] == 1
    assert table["denominator_status"] == "DEVELOPMENT_CHOICE_PENDING_U4_SEAL"
    # CTRL's row hours: first bar close 04:01 to the 09:30 PRE end, no RTH bars.
    hours = D(str(result.report["controls"]["coverage_hours"]["CTRL"]))
    assert hours == D(329) / 60
    assert D(table["all_controls"]["per_symbol_hour_coverage"]) == 1 / hours
    assert result.arms["mean"]["false_flags"]["all_controls"]["flagged"] == 1
    assert result.arms["keepalive"]["false_flags"]["all_controls"]["flagged"] == 0


def test_baseline_availability_reads_the_latest_state_per_arm(
    keep_run: tuple[Path, runner.SessionResult],
) -> None:  # WITNESS (P1 baseline availability)
    _, result = keep_run
    fast, thin = result.rows["FAST"], result.rows["THIN"]
    # FAST is unranked at onset (no acceleration yet) but its normal exists.
    assert fast["k2_rank_at_onset"] is None and fast["k2_baseline_available"] is True
    assert "prior_window_uncovered" in fast["k2_unknown_reasons"]
    # THIN traded on one of three prior sessions: zero median, positive mean.
    assert thin["k2_baseline_available"] is False
    assert "baseline_zero_dollar_volume" in thin["k2_unknown_reasons"]
    assert thin["mean_baseline_available"] is True and thin["mean_rank_at_onset"] is not None
    k2_share = result.arms["k2"]["baseline_available_at_onset"]
    mean_share = result.arms["mean"]["baseline_available_at_onset"]
    assert k2_share["available"] == 4 and k2_share["total"] == 5
    assert k2_share["unavailable"] == {"baseline_zero_dollar_volume": 1}
    assert mean_share["available"] == 5
    assert result.report["counts"]["baseline_available_at_onset"] == 4


def test_prefix_receipt_covers_every_recorded_symbol_without_a_synthetic_print(
    keep_run: tuple[Path, runner.SessionResult],
) -> None:  # WITNESS (P1 synthetic-tick coverage)
    out, result = keep_run
    # LATE's first bar starts at 04:02, so no opening tick could cover it; the
    # recording receipt covers every recorded symbol from the segment start.
    assert result.rows["LATE"]["k2_rank_at_onset"] is not None
    # No anchor print: CTRL's prior acceleration window is first covered by its
    # own 04:01 trade, so it first ranks at 04:07, not at 04:06.
    lines = _generations(out / "generations-k2-pre.jsonl")
    first_ctrl = next(line["ts_ns"] for line in lines if "CTRL" in line["top100"])
    assert first_ctrl == _ns(KEEP_DAY, 4, 7)
    assert result.rows["LATE"]["prefix_covered"] is True
    assert result.report["prefix"]["status"] == "RECEIPTED"


def test_no_prefix_receipt_leaves_ranking_not_estimable_with_reasons(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _keep_tree(tmp_path),
        _keep_cohort(tmp_path),
        out="no-receipt",
        registry=_fixture_registry(tmp_path),
        receipt=False,
    )
    for arm in ("k2", "mean", "keepalive"):
        assert result.arms[arm]["status"] == "NOT_ESTIMABLE"
        assert "segment_prefix_unknown" in result.arms[arm]["reason"]
    assert result.report["prefix"]["status"] == "ABSENT"
    assert "segment_prefix_unknown" in result.rows["LATE"]["k2_unknown_reasons"]
    assert result.rows["FAST"]["k2_baseline_available"] is True
    assert result.arms["gap_fixed_open_sub_arm"]["metrics"]["detected"] == 2


def test_prefix_receipt_for_other_bytes_is_refused(tmp_path: Path) -> None:
    root = _keep_tree(tmp_path)
    bad = _receipt(tmp_path, root, data_sha256="0" * 64)
    with pytest.raises(ValueError, match="prefix receipt"):
        runner.run_session(
            cohort_path=_keep_cohort(tmp_path),
            bars_root=root,
            reg_path=REGISTRY,
            out_dir=tmp_path / "bad",
            verify_protocol=False,
            prefix_receipt=bad,
        )


def test_arm_a_stays_not_run_and_the_gap_sub_arm_carries_its_own_name(
    keep_run: tuple[Path, runner.SessionResult],
) -> None:  # WITNESS (P1 arm (a) identity)
    _, result = keep_run
    arm_a = result.arms["gap"]
    assert arm_a["status"] == "NOT_RUN"
    assert "ADV20" in arm_a["missing"]["adv20"]
    assert "post-market" in arm_a["missing"]["prior_post_turnover"]
    assert "UNCALIBRATED" in arm_a["trigger_mode"]["reason"]
    sub = result.arms["gap_fixed_open_sub_arm"]
    assert sub["status"] == "DEVELOPMENT_SUB_ARM"
    assert sorted(sub["flags"]) == ["FAST", "KEEP"]
    assert sub["metrics"]["detected_at_onset"] == 2
    assert result.rows["FAST"]["gap_sub_arm_flag_ts"] == _ns(KEEP_DAY, 4, 0)


def test_verified_run_refuses_a_dirty_tree_and_binds_a_clean_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # WITNESS (P1 provenance)
    root = _synthetic_tree(tmp_path)
    monkeypatch.setattr(
        runner, "_git_status", lambda: " M research/ranking_e2e/runner.py\n", raising=False
    )
    with pytest.raises(RuntimeError, match="dirty"):
        _run(tmp_path, root, _cohort_json(tmp_path), out="dirty", verify_protocol=True)
    assert not (tmp_path / "dirty" / "session.json").exists()
    monkeypatch.setattr(runner, "_git_status", lambda: "")
    monkeypatch.setattr(runner, "_git_head", lambda: "b" * 40)
    result = _run(tmp_path, root, _cohort_json(tmp_path), out="clean", verify_protocol=True)
    implementation = result.report["implementation"]
    assert implementation["git_head"] == "b" * 40 and implementation["tree_clean"] is True
    assert implementation["harness_sha256"] == runner._tree_sha(
        list((ROOT / "research" / "ranking_e2e").glob("*.py"))
    )
    assert result.report["label"] == "DEVELOPMENT_TABLE_NOT_A_TRIAL"


# ------------------------------------- hosted-review witnesses (fail at 1e95678)
EDGE_DAY = "2026-11-09"
EDGE_PRIOR = ("2026-11-05", "2026-11-06")


def _edge_tree(tmp_path: Path) -> Path:
    """The replay window's edges; prior close 10.00 for every name.

    BOUND first closes at +5% in the 09:29 bar, a PRE bar, so its onset is
    09:30 and PRE's 09:30 generation judges it. WEND first crosses in the
    11:34 bar, the replay's last close (onset 11:35). WLATE (truth) and WCTRL
    (control) cross only in the 11:35 bar, which closes at 11:36, after the
    replay window ends.
    """
    root = tmp_path / "edge"
    prior = {
        "BOUND": [(9, m, "10.00", "10.00", 1000) for m in range(20, 30)],
        **{
            symbol: [(11, m, "10.00", "10.00", 1000) for m in range(28, 35)]
            for symbol in ("WEND", "WLATE", "WCTRL")
        },
    }
    for day in EDGE_PRIOR:
        _write_day(root, day, prior)
    flat = [(11, m, "10.00", "10.10", 3000) for m in range(28, 34)]
    late = [(11, 34, "10.10", "10.10", 3000), (11, 35, "10.10", "10.60", 3000)]
    _write_day(
        root,
        EDGE_DAY,
        {
            "BOUND": [(9, m, "10.00", "10.10", 3000) for m in range(20, 29)]
            + [(9, 29, "10.10", "10.60", 3000)],
            "WEND": [*flat, (11, 34, "10.10", "10.60", 3000)],
            "WLATE": [*flat, *late],
            "WCTRL": [*flat, *late],
        },
    )
    return root


def _edge_cohort(tmp_path: Path) -> Path:
    path = tmp_path / "edge-cohort.json"

    def candidate(symbol: str, move: str) -> dict[str, str]:
        return {
            "symbol": symbol,
            "move": move,
            "premarket_dollar_volume": "1000000",
            "full_dollar_volume": "1000000",
            "prior_close": "10.00",
            "prior_close_source": "official_prior_daily_close",
        }

    truth = ["BOUND", "WEND", "WLATE"]
    path.write_text(
        json.dumps(
            {
                "schema": "ranking-e2e.cohort/1",
                "session": EDGE_DAY,
                "prior_sessions": list(EDGE_PRIOR),
                "labels": {
                    "survivor_only": True,
                    "pit_verified": False,
                    "inference_eligible": False,
                },
                "candidates": [candidate(s, "0.06") for s in truth] + [candidate("WCTRL", "0.01")],
                "truth": truth,
                "controls": ["WCTRL"],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture(scope="module")
def edge_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, runner.SessionResult]:
    tmp_path = tmp_path_factory.mktemp("edge")
    result = _run(tmp_path, _edge_tree(tmp_path), _edge_cohort(tmp_path), out="edge-out")
    return tmp_path / "edge-out", result


def test_a_boundary_bar_onset_keeps_its_pre_segment(
    edge_run: tuple[Path, runner.SessionResult],
) -> None:  # WITNESS (hosted P1: onset segment)
    _, result = edge_run
    bound = result.rows["BOUND"]
    # The 09:29 bar is a PRE bar: PRE publishes at its 09:30 close and ranks
    # BOUND first there; RTH has no generation before 09:31 (K2 section 5).
    assert bound["k2_rank_at_onset"] == 1 and bound["mean_rank_at_onset"] == 1
    assert bound["onset_ts"] == _ns(EDGE_DAY, 9, 30) and bound["onset_segment"] == "PRE"
    assert bound["k2_baseline_available"] is True and bound["k2_universe_at_onset"] == 1
    assert result.report["strata"]["pre_rest"] == 1
    assert result.report["strata"]["rth_open_30"] == 0


def test_price_path_labels_stay_inside_the_replay_window(
    edge_run: tuple[Path, runner.SessionResult],
) -> None:  # WITNESS (hosted P1: replay window)
    _, result = edge_run
    counts = result.report["counts"]
    # WCTRL and WLATE cross only in the bar closing at 11:36, after the
    # 04:00-11:35 window (K3.4); neither crossing is part of the replayed path.
    assert counts["never_crossed_controls"] == 1
    assert "WLATE" not in result.onsets and counts["unobserved_truth"] == 1
    assert result.onsets["WEND"] == _ns(EDGE_DAY, 11, 35)
    assert result.rows["WEND"]["onset_segment"] == "RTH"
    assert result.arms["k2"]["false_flags"]["never_crossed"]["controls"] == 1
    # Every onset in the window falls in exactly one stratum.
    assert counts["onsets"] == sum(result.report["strata"].values()) == 2


# ------------------------------- round-3 fix witnesses (fail at 81f64bb)
COVER_DAY = "2026-11-09"
COVER_PRIOR = ("2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06")


def _coverage_tree(tmp_path: Path) -> Path:
    """Two prior sessions requested OMH; three did not record it.

    Sessions 1-2 carry a full OMH/CTRL path, sessions 3-4 declare only OTHER,
    and session 5 has no recorded page at all.  Today OMH first closes above
    +5% in its 04:06 bar, so its onset is 04:07.  Padding the three uncovered
    sessions with zero curves makes the median normal zero; the covered two
    are positive.
    """
    root = tmp_path / "coverage"
    flat = [(4, m, "10.10", "10.10", 1000) for m in range(11)]
    path = {"OMH": flat, "CTRL": list(flat)}
    other = {"OTHER": [(4, m, "10.10", "10.10", 1000) for m in range(11)]}
    for day in COVER_PRIOR[:2]:
        _write_day(root, day, {**path, **other}, requested={"OMH", "CTRL", "OTHER"})
    for day in COVER_PRIOR[2:4]:
        _write_day(root, day, other)
    _write_day(root, COVER_PRIOR[4], {})
    _write_day(
        root,
        COVER_DAY,
        {
            "OMH": [(4, m, "10.10", "10.10", 3000) for m in range(6)]
            + [(4, 6, "10.10", "10.60", 3000)],
            "CTRL": [(4, m, "10.00", "10.00", 1000) for m in range(7)],
        },
    )
    return root


def _coverage_cohort(tmp_path: Path) -> Path:
    path = tmp_path / "coverage-cohort.json"

    def candidate(symbol: str, move: str) -> dict[str, str]:
        return {
            "symbol": symbol,
            "move": move,
            "premarket_dollar_volume": "1000000",
            "full_dollar_volume": "1000000",
            "prior_close": "10.00",
            "prior_close_source": "official_prior_daily_close",
        }

    path.write_text(
        json.dumps(
            {
                "schema": "ranking-e2e.cohort/1",
                "session": COVER_DAY,
                "prior_sessions": list(COVER_PRIOR),
                "labels": {
                    "survivor_only": True,
                    "pit_verified": False,
                    "inference_eligible": False,
                },
                "candidates": [candidate("OMH", "0.06"), candidate("CTRL", "0.00")],
                "truth": ["OMH"],
                "controls": ["CTRL"],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture(scope="module")
def coverage_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, runner.SessionResult]:
    tmp_path = tmp_path_factory.mktemp("coverage")
    result = _run(
        tmp_path,
        _coverage_tree(tmp_path),
        _coverage_cohort(tmp_path),
        out="coverage-out",
        registry=_fixture_registry(tmp_path),
    )
    return tmp_path / "coverage-out", result


def test_uncovered_prior_sessions_do_not_supply_zero_baselines(
    coverage_run: tuple[Path, runner.SessionResult],
) -> None:  # WITNESS (P1 historical coverage)
    _, result = coverage_run
    omh = result.rows["OMH"]
    # Only the two sessions whose recording declared OMH may contribute; an
    # absent prior bar is an unknown session, not a zero-dollar one.
    assert omh["k2_baseline_available"] is True
    assert omh["k2_rank_at_onset"] == 1
    assert omh["k2_baseline_sessions"] == 2
    assert omh["mean_baseline_sessions"] == 2
    assert result.arms["k2"]["baseline_available_at_onset"]["available"] == 1
    assert "baseline_zero_dollar_volume" not in omh["k2_unknown_reasons"]


CROSS_DAY = "2026-11-09"
CROSS_PRIOR = ("2026-11-04", "2026-11-05", "2026-11-06")


def _cross_tree(tmp_path: Path) -> Path:
    """KEEP is admitted in PRE, then crosses +5% only in an RTH bar.

    Its first above-threshold close is the 09:30 bar, so the onset is 09:31 in
    RTH, after PRE's last generation; membership began at its PRE rise.  CTRL
    is a flat control.
    """
    root = tmp_path / "cross"
    flat = [(4, m, "10.00", "10.00", 1000) for m in range(11)]
    prior = {"KEEP": flat, "CTRL": list(flat)}
    for day in CROSS_PRIOR:
        _write_day(root, day, prior)
    closes = ("10.12", "10.15", "10.18", "10.21", "10.24", "10.27", "10.30", "10.33")
    _write_day(
        root,
        CROSS_DAY,
        {
            "KEEP": [(4, m, close, close, 3000) for m, close in enumerate(closes)]
            + [(9, 30, "10.40", "10.60", 3000)],
            "CTRL": [(4, m, "10.00", "10.00", 1000) for m in range(10)],
        },
    )
    return root


def _cross_cohort(tmp_path: Path) -> Path:
    path = tmp_path / "cross-cohort.json"

    def candidate(symbol: str, move: str) -> dict[str, str]:
        return {
            "symbol": symbol,
            "move": move,
            "premarket_dollar_volume": "1000000",
            "full_dollar_volume": "1000000",
            "prior_close": "10.00",
            "prior_close_source": "official_prior_daily_close",
        }

    path.write_text(
        json.dumps(
            {
                "schema": "ranking-e2e.cohort/1",
                "session": CROSS_DAY,
                "prior_sessions": list(CROSS_PRIOR),
                "labels": {
                    "survivor_only": True,
                    "pit_verified": False,
                    "inference_eligible": False,
                },
                "candidates": [candidate("KEEP", "0.06"), candidate("CTRL", "0.00")],
                "truth": ["KEEP"],
                "controls": ["CTRL"],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture(scope="module")
def cross_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, runner.SessionResult]:
    tmp_path = tmp_path_factory.mktemp("cross")
    result = _run(
        tmp_path,
        _cross_tree(tmp_path),
        _cross_cohort(tmp_path),
        out="cross-out",
        registry=_fixture_registry(tmp_path),
    )
    return tmp_path / "cross-out", result


def test_keep_alive_keeps_the_first_admission_across_pre_and_rth(
    cross_run: tuple[Path, runner.SessionResult],
) -> None:  # WITNESS (P1 cross-segment keep-alive admission)
    _, result = cross_run
    keep_row = result.rows["KEEP"]
    assert keep_row["onset_segment"] == "RTH"
    assert keep_row["onset_ts"] == _ns(CROSS_DAY, 9, 31)
    assert keep_row["keepalive_member_at_onset"] is True
    # Membership began during PRE; RTH's first generation must not overwrite
    # the admission timestamp with the onset itself.
    assert keep_row["keepalive_first"] < keep_row["onset_ts"]
    keep = result.arms["keepalive"]
    assert keep["persistence_denominator"] == 1
    assert keep["persistence_at_onset"] == 1
    assert keep["persistence_rate"] == "1"
    assert keep["entered_at_onset_excluded"] == 0


def test_ranking_metrics_leaves_recall_undefined_with_no_onsets() -> None:
    # WITNESS (P2 empty recall denominator)
    result = metrics.ranking_metrics({}, {}, {}, arm="k2")
    assert result.total == 0 and result.rankable == 0
    # No name could be recalled, so the rate is undefined, never a numeric zero.
    assert result.recall == {30: None, 100: None}


def test_paired_recall_leaves_recall_undefined_with_no_common_name() -> None:
    # WITNESS (P2 empty paired denominator)
    result = metrics.paired_recall({"X": 0}, {"X": None}, {"X": 1})
    assert result["common"] == 0
    # One arm ranks X and the other does not, so neither arm has a paired
    # denominator; both rates are undefined, not "0".
    assert result["recall_a"] == {30: None, 100: None}
    assert result["recall_b"] == {30: None, 100: None}
