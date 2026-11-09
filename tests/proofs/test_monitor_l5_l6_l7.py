"""Proof for L5 GitHub quality, L6 evidence integrity and L7 monitor rules.

Sources: github/gh-aw@v1.0.1
(`0627fdbe4beb5f3b71aa569f8d97150b87f2111a`) for the metric names and PR-quality
rounds; `.github/workflows/shared/review-rules.md:16-19` and
`.github/review/rubric.md:56-58` for the `Review of <sha>` and P0-P3 semantics;
github/issue-metrics@v5.0.3
(`671528652402b9b8a33da44b5c693b3161bc090f`) for the scoreboard contract;
grafana/docker-otel-lgtm@v0.38.0
(`9c57b1400ccdb8920e1a2b6083134cc5ef244a8f`) for the local rules backend; and
ADR-0018 for every threshold's `UNCALIBRATED` status.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
FIXTURE = Path(__file__).parent / "fixtures" / "monitor_pr_quality.json"
RULES = ROOT / "deploy" / "monitor" / "l7" / "rules.yaml"
PARAMETERS = ROOT / "deploy" / "monitor" / "l7" / "parameters.json"


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


github = _load("_monitor_github_proof", "scripts/monitor_github.py")
evidence = _load("_monitor_evidence_proof", "scripts/monitor_evidence.py")


def test_parametrize_parser_skips_an_empty_parameter_set() -> None:
    tree = ast.parse(
        "import pytest\n@pytest.mark.parametrize('value', [()])\ndef test_empty(value):\n    pass\n"
    )
    node = tree.body[1]
    assert isinstance(node, ast.FunctionDef)
    decorator = node.decorator_list[0]
    assert evidence._parametrize_ids(decorator, tree) == []


def _fixture() -> dict[int, dict]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {pr["number"]: pr for pr in data["pull_requests"]}


def _parameters() -> dict[str, dict]:
    return {row["name"]: row for row in json.loads(PARAMETERS.read_text())["rows"]}


def test_review_rounds_only_count_review_of_markers_in_time_order() -> None:
    reviews = [
        {"body": "Review of " + "b" * 40, "submittedAt": "2026-11-01T12:00:00Z"},
        {"body": "Looks fine to me", "submittedAt": "2026-11-01T09:00:00Z"},
        {"body": "Review of abc123", "submittedAt": "2026-11-01T10:00:00Z"},
        {"body": "Review of " + "a" * 40, "submittedAt": "2026-11-01T10:00:00Z"},
        {
            "body": "Review of " + "a" * 40 + "\nsecond pass",
            "submittedAt": "2026-11-01T11:00:00Z",
        },
    ]
    rounds = github.review_rounds(reviews)
    assert [round_.sha for round_ in rounds] == ["a" * 40, "b" * 40]
    assert [round_.number for round_ in rounds] == [1, 2]


def test_p0_to_p3_classification_and_round_three_mapping() -> None:
    assert github.classify_finding(1, "P0") == "BLOCKING-CLASS"
    assert github.classify_finding(3, "P0") == "BLOCKING-CLASS"
    assert github.classify_finding(1, "P1") == "BLOCKING-CLASS"
    assert github.classify_finding(2, "P1") == "BLOCKING-CLASS"
    assert github.classify_finding(3, "P1") == "FOLLOW-UP"
    assert github.classify_finding(1, "P2") == "FOLLOW-UP"
    assert github.classify_finding(3, "P3") == "FOLLOW-UP"

    quality = github.pr_quality(_fixture()[102])
    assert [round_["number"] for round_ in quality["rounds"]] == [1, 2, 3]
    assert quality["blocking_findings"] == 1
    assert quality["follow_up_findings"] == 2
    classes = {
        (finding["priority"], finding["round"]): finding["class"] for finding in quality["findings"]
    }
    assert classes[("P1", 3)] == "FOLLOW-UP"
    assert classes[("P3", 2)] == "FOLLOW-UP"
    assert classes[("P0", 3)] == "BLOCKING-CLASS"


def test_unresolved_threads_are_counted_by_class_at_merge() -> None:
    quality = github.pr_quality(_fixture()[101])
    assert [round_["number"] for round_ in quality["rounds"]] == [1, 2]
    assert quality["blocking_findings"] == 2
    assert quality["follow_up_findings"] == 2
    assert quality["unresolved_blocking_at_merge"] == 2
    assert quality["unresolved_follow_up_at_merge"] == 1
    assert quality["check_failures"] == [{"name": "ci", "conclusion": "FAILURE"}]
    assert quality["review_latency_seconds"] == 1800.0
    assert quality["time_to_merge_seconds"] == 4 * 3600
    assert quality["reverted"] is False

    assert github.pr_quality(_fixture()[103])["rounds"] == []
    assert github.pr_quality(_fixture()[104])["reverted"] is True


def test_pr_quality_keeps_review_and_comment_bodies_out_of_its_output() -> None:
    quality = github.pr_quality(_fixture()[101])
    encoded = json.dumps(quality)
    assert "bypasses the required check" not in encoded
    assert "races the writer" not in encoded
    assert "path" not in encoded
    assert set(quality["findings"][0]) == {"priority", "class", "round", "sha", "resolved"}


def test_aic_and_router_usd_stay_separate_and_never_summed() -> None:
    metrics = github.cost_metrics(Decimal("2.5"), Decimal("0.42"))
    assert {metric.name for metric in metrics} == {
        "sextant_gh_aw_aic",
        "sextant_router_cost_notional_usd",
    }
    assert {metric.unit for metric in metrics} == {"AIC", "USD"}
    assert github.AIC_USD == Decimal("0.01")
    aic_only = [metric for metric in metrics if metric.unit == "AIC"]
    assert github.sum_same_unit(aic_only) == Decimal("2.5")
    with pytest.raises(ValueError, match="refusing to sum mixed units"):
        github.sum_same_unit(list(metrics))
    payload = github.otlp_payload(metrics, "proof")
    scope = payload["resourceMetrics"][0]["scopeMetrics"][0]
    names = [metric["name"] for metric in scope["metrics"]]
    assert "sextant_gh_aw_aic" in names
    assert "sextant_router_cost_notional_usd" in names
    assert not any("total" in name and "aic" in name.lower() for name in names)


def test_forecast_metrics_reads_each_workflow_from_the_result_wrapper() -> None:
    forecast = {
        "period": "week",
        "as_of": "2026-11-08T00:00:00Z",
        "eval_mode": False,
        "workflows": [
            {
                "workflow_id": "review",
                "workflow_path": ".github/workflows/review.lock.yml",
                "period": "week",
                "avg_aic": 1.25,
                "p50_aic_per_run": 1.0,
                "p95_aic_per_run": 2.0,
                "projected_aic": 3.5,
                "weekly_projected_aic": 7.0,
                "monthly_projected_aic": 30.0,
            },
            {
                "workflow_id": "scoreboard",
                "period": "week",
                "avg_aic": 0.5,
                "p50_aic_per_run": 0.4,
                "p95_aic_per_run": 0.9,
                "projected_aic": 1.5,
                "weekly_projected_aic": 3.0,
                "monthly_projected_aic": 12.0,
            },
        ],
    }
    metrics = github.forecast_metrics(forecast)
    assert len(metrics) == 12
    assert {metric.unit for metric in metrics} == {"AIC"}
    assert {metric.attributes["workflow"] for metric in metrics} == {"review", "scoreboard"}
    review = [
        metric
        for metric in metrics
        if metric.name == "sextant_gh_aw_aic_p95" and metric.attributes["workflow"] == "review"
    ]
    assert len(review) == 1
    assert Decimal(str(review[0].value)) == Decimal("2.0")
    assert review[0].attributes["workflow_path"] == ".github/workflows/review.lock.yml"
    assert not any(metric.name.startswith("sextant_router_cost") for metric in metrics)
    assert github.forecast_metrics({"avg_aic": 9.0, "workflows": []}) == []


def test_gh_children_disable_telemetry_and_leave_prompt_logging_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args, 0, "{}", "")

    monkeypatch.setattr(github.subprocess, "run", fake_run)
    monkeypatch.setattr(
        github.os,
        "environ",
        {
            "PATH": "/usr/bin",
            "OTEL_LOG_USER_PROMPTS": "1",
            "OTEL_LOG_ASSISTANT_RESPONSES": "1",
            "OTEL_LOG_RAW_API_BODIES": "1",
            "OTEL_LOG_TOOL_CONTENT": "1",
        },
    )
    github.run_gh(["api", "graphql"])
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["GH_TELEMETRY"] == "false"
    assert env["DO_NOT_TRACK"] == "1"
    for unset in (
        "OTEL_LOG_USER_PROMPTS",
        "OTEL_LOG_ASSISTANT_RESPONSES",
        "OTEL_LOG_RAW_API_BODIES",
        "OTEL_LOG_TOOL_CONTENT",
    ):
        assert unset not in env
    assert captured["args"] == ["gh", "api", "graphql"]


def test_every_manifest_proof_reference_resolves() -> None:
    summary = evidence.resolve(ROOT / "docs" / "manifest.md", ROOT / "tests")
    # Every PR may add a manifest row; only the starting floor is ours to pin.
    assert summary["rows"] >= 119
    assert summary["unparsed"] == 0
    assert summary["missing_functions"] == 0
    assert summary["missing_modules"] == 0
    assert summary["problems"] == []
    assert set(summary["by_suite"]) == {"proofs", "repo", "host"}


def test_resolve_rejects_an_unknown_parametrize_id(tmp_path: Path) -> None:
    tests = tmp_path / "tests" / "proofs"
    tests.mkdir(parents=True)
    (tests / "test_param.py").write_text(
        "import pytest\n"
        "\n"
        "@pytest.mark.parametrize('value', ['good'])\n"
        "def test_param(value):\n"
        "    assert value\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "docs" / "manifest.md"
    manifest.parent.mkdir()
    manifest.write_text(
        "| Row | Source | Applied | Proof |\n"
        "| --- | --- | --- | --- |\n"
        "| row | source | applied | `test_param.py::test_param[bogus]` |\n",
        encoding="utf-8",
    )
    summary = evidence.resolve(manifest, tmp_path / "tests")
    assert summary["missing_functions"] == 1
    assert "[bogus]" in summary["problems"][0]["ref"]


def test_manifest_antigravity_row_names_the_retained_runtime_proof() -> None:
    rows = evidence.parse_manifest(ROOT / "docs" / "manifest.md")
    row = next(row for row in rows if row.name.startswith("Antigravity CLI"))
    assert "test_retained_runtime_has_an_eligible_pinned_artifact[antigravity]" in row.proof
    stale = "test_runtime_has_an_eligible_pinned_artifact_and_an_honest_launch_scope"
    assert stale not in row.proof


def test_agent_error_ratio_weights_runs_by_turns() -> None:
    rules = RULES.read_text(encoding="utf-8")
    assert "sum(sextant_gh_aw_errors) / clamp_min(sum(sextant_gh_aw_turns), 1)" in rules


def test_alert_thresholds_are_registered_uncalibrated_and_informational() -> None:
    rules = RULES.read_text(encoding="utf-8")
    pairs = re.findall(
        r"threshold_ref:\s*([A-Za-z0-9_]+)\s*\n\s*threshold_value:\s*\"([^\"]+)\"",
        rules,
    )
    assert len(pairs) == 12
    parameters = _parameters()
    assert len(parameters) == 15
    assert all(row["status"] == "UNCALIBRATED" for row in parameters.values())
    for name, value in pairs:
        assert name in parameters
        assert parameters[name]["status"] == "UNCALIBRATED"
        assert Decimal(str(parameters[name]["value"])) == Decimal(value)
    assert rules.count("delivery: informational") == 12
    assert rules.count("action: proposal-only") == 12
    assert "action: kill" not in rules
    assert "action: gate" not in rules


def test_l7_rules_cover_the_converged_signals_and_staleness_is_not_zero() -> None:
    rules = RULES.read_text(encoding="utf-8")
    alerts = re.findall(r"^\s+- alert:\s*(\w+)", rules, re.MULTILINE)
    records = re.findall(r"^\s+- record:\s*(\w+)", rules, re.MULTILINE)
    assert len(alerts) == 12
    assert len(records) == 13
    assert "sextant_llm_cache_hit_ratio" in records
    assert "sextant_llm_cache_write_waste_ratio" in records
    assert "sextant_agent_error_ratio" in records
    assert "MonitorRetryLoop" in alerts
    assert "MonitorCostAnomaly" in alerts
    assert "MonitorModelEffortDrift" in alerts
    assert "MonitorEvidenceStale" in alerts
    stale = rules.split("alert: MonitorEvidenceStale", 1)[1]
    assert "absent(" in stale
    assert "time()" in stale
    assert "time() - sextant_monitor_last_success_timestamp_seconds" in rules
    assert all("for:" in block for block in rules.split("- alert:")[1:])


def test_all_endpoints_are_loopback_and_l6_is_offline_by_default() -> None:
    assert github.OTLP_ENDPOINT == "http://127.0.0.1:4318"
    assert evidence.OTLP_ENDPOINT == "http://127.0.0.1:4318"
    assert github.is_loopback_url("http://127.0.0.1:4318")
    assert github.is_loopback_url("http://localhost:4318")
    assert github.is_loopback_url("http://[::1]:4318")
    assert not github.is_loopback_url("http://0.0.0.0:4318")
    assert not github.is_loopback_url("https://127.0.0.1:4318")
    assert not github.is_loopback_url("http://user:pass@127.0.0.1:4318")
    with pytest.raises(ValueError, match="loopback"):
        evidence.post_otlp("http://192.0.2.10:4318", {})
    summary = evidence.build_summary(ROOT)
    assert summary["network"] == "disabled"
    for relative in (
        "scripts/monitor_github.py",
        "scripts/monitor_evidence.py",
        "deploy/monitor/l7/rules.yaml",
    ):
        assert "0.0.0.0" not in (ROOT / relative).read_text(encoding="utf-8")  # noqa: S104


def test_l5_commands_are_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_command(args, *, timeout: int = 180):
        commands.append(tuple(args))
        return subprocess.CompletedProcess(["gh", *args], 0, "{}", "")

    monkeypatch.setattr(github, "run_gh", fake_command)
    monkeypatch.setattr(github, "_systemd_state", lambda: {})
    records = github.collect_once("seathatflowsinourveins/sextant")
    assert records[0]["kind"] == "schema"
    joined = " ".join(part for command in commands for part in command)
    for mutation in ("DELETE", "PATCH", "PUT", "POST", "--method", "upload"):
        assert mutation not in joined
    assert any("graphql" in command for command in commands)


def test_pr_query_selects_newest_merged_prs(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "pullRequests(first: $limit" in github.PR_QUERY
    assert "pullRequests(last:" not in github.PR_QUERY
    assert "orderBy: {field: UPDATED_AT, direction: DESC}" in github.PR_QUERY

    queries: list[str] = []

    def fake_run(args, **kwargs):
        for arg in args:
            if isinstance(arg, str) and arg.startswith("query="):
                queries.append(arg.removeprefix("query="))
        return subprocess.CompletedProcess(["gh", *args], 0, "{}", "")

    monkeypatch.setattr(github, "run_gh", fake_run)
    monkeypatch.setattr(github, "_systemd_state", lambda: {})
    github.collect_once("seathatflowsinourveins/sextant")
    assert len(queries) == 1
    assert "pullRequests(first: $limit" in queries[0]
    assert "states: [MERGED]" in queries[0]
    assert "pullRequests(last:" not in queries[0]


def test_l6_missing_trial_witness_is_unavailable_not_zero() -> None:
    witness = ROOT / "reports" / "research" / "trials.parquet"
    summary = evidence.trial_ledger(ROOT)
    if witness.exists():
        assert summary["status"] == "OK"
    else:
        assert summary["status"] == "UNAVAILABLE"
        assert "rows" not in summary
    budgets = evidence.budget_utilization(ROOT)
    assert budgets["src_lines"]["limit"] == 26_500
    assert budgets["src_lines"]["value"] < 26_500
    assert budgets["justfile_lines"]["limit"] == 105
    source = sum(
        len(path.read_text(encoding="utf-8").splitlines()) for path in (ROOT / "src").rglob("*.py")
    )
    assert budgets["src_lines"]["value"] == source
    ages = evidence.doc_ages(ROOT)
    assert ages["status"] == "OK"
    assert ages["files"] > 0


def test_l6_src_budget_sums_the_tree_not_its_longest_file(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a\nb\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("c\n", encoding="utf-8")
    budgets = evidence.budget_utilization(tmp_path)
    assert budgets["src_lines"]["value"] == 3


PRODUCERS = ROOT / "deploy" / "monitor" / "l7" / "producers.json"


def test_l5_collector_output_never_contains_review_bodies_or_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {
        "data": {"repository": {"pullRequests": {"nodes": [_fixture()[101]]}}},
    }

    def fake_run(args, **kwargs):
        if "graphql" in args:
            return subprocess.CompletedProcess(["gh", *args], 0, json.dumps(payload), "")
        if "runners" in args:
            return subprocess.CompletedProcess(["gh", *args], 0, json.dumps({"runners": []}), "")
        return subprocess.CompletedProcess(["gh", *args], 0, "{}", "")

    monkeypatch.setattr(github, "run_gh", fake_run)
    monkeypatch.setattr(github, "_systemd_state", lambda: {})
    records = github.collect_once("seathatflowsinourveins/sextant")
    encoded = json.dumps(records)
    assert "bypasses the required check" not in encoded
    assert "races the writer" not in encoded
    assert "src/gate.py" not in encoded
    assert '"body"' not in encoded
    assert '"path"' not in encoded
    metrics = github.metrics_from_records(records, "seathatflowsinourveins/sextant")
    assert any(metric.name == "sextant_pr_findings_blocking_class" for metric in metrics)

    out = tmp_path / "github.jsonl"
    github.write_jsonl(out, records)
    stored = out.read_text(encoding="utf-8")
    assert "bypasses the required check" not in stored
    assert "src/gate.py" not in stored

    monkeypatch.setattr(github, "collect_once", lambda *args, **kwargs: records)
    assert github.main(["--dry-run", "--no-otlp"]) == 0
    assert "bypasses the required check" not in capsys.readouterr().out


def test_l5_emits_heartbeat_and_run_error_ratio() -> None:
    metrics = github.metrics_from_records(
        [{"kind": "schema", "payload": {"version": 1}}], "seathatflowsinourveins/sextant"
    )
    by_name = {metric.name: metric for metric in metrics}
    heartbeat = by_name["sextant_monitor_last_success_timestamp_seconds"]
    assert heartbeat.unit == "seconds"
    assert float(heartbeat.value) > 0

    failed = github.metrics_from_records([{"kind": "error", "payload": {}}], "repo")
    assert not any(
        metric.name == "sextant_monitor_last_success_timestamp_seconds" for metric in failed
    )

    run = github.run_metrics(
        {"workflow_name": "review", "run_id": 7, "turns": 10, "error_count": 2}
    )
    ratios = [metric for metric in run if metric.name == "sextant_gh_aw_error_ratio"]
    assert len(ratios) == 1
    assert Decimal(str(ratios[0].value)) == Decimal("0.2")
    run_by_name = {metric.name: metric for metric in run}
    assert Decimal(str(run_by_name["sextant_gh_aw_errors"].value)) == 2
    assert Decimal(str(run_by_name["sextant_gh_aw_turns"].value)) == 10


def test_every_l7_alert_series_has_a_registered_producer() -> None:
    data = json.loads(PRODUCERS.read_text(encoding="utf-8"))
    rows = {row["series"]: row for row in data["rows"]}
    required = {
        "sextant_llm_cache_hit_ratio",
        "sextant_llm_cache_write_waste_ratio",
        "sextant_agent_context_pressure_ratio",
        "sextant_agent_tool_failures_consecutive",
        "sextant_agent_error_ratio",
        "sextant_llm_cost_usd",
        "sextant_llm_quota_remaining_ratio",
        "sextant_llm_quota_burn_ratio_per_hour",
        "sextant_review_model_effort_compliance_ratio",
        "sextant_monitor_last_success_timestamp_seconds",
    }
    assert required <= set(rows)

    rules = RULES.read_text(encoding="utf-8")
    alerts = rules.split("- alert:")[1:]
    assert len(alerts) == 12
    for alert in alerts:
        series = re.search(r"source_series:\s*([a-z0-9_]+)", alert)
        status = re.search(r"producer_status:\s*(produced|pending)", alert)
        assert series is not None
        assert status is not None
        row = rows[series.group(1)]
        assert row["status"].lower() == status.group(1)
        if row["status"] == "PENDING":
            assert row.get("owner")
            assert row.get("reason")
        elif row["producer"].startswith("recording-rule:"):
            record = row["producer"].split(":", 1)[1]
            assert f"- record: {record}" in rules

    source = (ROOT / "scripts" / "monitor_github.py").read_text(encoding="utf-8")
    for row in rows.values():
        if row["status"] == "PRODUCED" and row["producer"].startswith("scripts/"):
            assert row["series"] in source
    assert "gen_ai_client_inference_usage_cache_read_input_tokens_total" in rules
    assert "gen_ai_client_inference_usage_cache_write_input_tokens_total" in rules
