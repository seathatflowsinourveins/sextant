"""L5 GitHub monitor: gh-aw usage, local runners and PR-quality rounds.

Sources: github/gh-aw@v1.0.1 (`0627fdbe4beb5f3b71aa569f8d97150b87f2111a`,
`pkg/cli/logs_report.go`, `pkg/cli/audit.go`, `pkg/cli/forecast_types.go`);
github/issue-metrics@v5.0.3 (`671528652402b9b8a33da44b5c693b3161bc090f` for the
scoreboard contract); `.github/workflows/shared/review-rules.md:16-19` and
`.github/review/rubric.md:56-58` for the round and P0-P3 semantics.

Read-only: it only runs `gh api graphql`, `gh api ...`, and `gh aw` reads. It never
mutates a GitHub resource and never uploads an artifact. The only sinks are local
JSONL and loopback OTLP/HTTP. Every `gh` subprocess runs with
`GH_TELEMETRY=false` and `DO_NOT_TRACK=1`; the CLI's default is telemetry on.
AIC (`0.01` USD each) and router invoice USD are separate series and are never
summed: AIC is a provider credit unit, not a dollar amount.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import subprocess
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import urlsplit

OTLP_ENDPOINT = "http://127.0.0.1:4318"
AIC_USD = Decimal("0.01")
DEFAULT_REPO = "seathatflowsinourveins/sextant"
DEFAULT_LIMIT = 20
GH_TELEMETRY_ENV = {
    "GH_TELEMETRY": "false",
    "DO_NOT_TRACK": "1",
    "GH_SPINNER_DISABLED": "1",
}
REVIEW_MARKER = re.compile(r"^Review of ([0-9a-f]{40})(?:\s|$)")
FINDING_MARKER = re.compile(r"^\[(P[0-3])\](?:\s|$)")
FAILED_CHECKS = frozenset({"FAILURE", "TIMED_OUT", "CANCELLED", "ERROR", "STARTUP_FAILURE"})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

PR_QUERY = """
query($owner: String!, $name: String!, $limit: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequests(last: $limit, states: [MERGED], orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number
        title
        url
        createdAt
        mergedAt
        headRefOid
        reviews(first: 50) {
          nodes { submittedAt body state author { login } }
        }
        reviewThreads(first: 100) {
          nodes {
            isResolved
            comments(first: 20) {
              nodes { body createdAt path originalCommit { oid } author { login } }
            }
          }
        }
        commits(last: 20) {
          nodes { commit { oid committedDate messageHeadline } }
        }
        statusCheckRollup {
          contexts(first: 50) {
            nodes {
              __typename
              ... on CheckRun { name conclusion startedAt completedAt }
              ... on StatusContext { context state createdAt }
            }
          }
        }
      }
    }
    ref(qualifiedName: "refs/heads/main") {
      target {
        ... on Commit {
          history(first: 50) {
            nodes { oid committedDate messageHeadline }
          }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class Metric:
    """One OTLP gauge. Unit is mandatory so AIC and USD cannot be confused."""

    name: str
    unit: str
    value: Decimal | int | float
    attributes: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewRound:
    number: int
    sha: str
    submitted_at: str


@dataclass(frozen=True)
class Finding:
    priority: str
    finding_class: str
    round_number: int | None
    sha: str | None
    path: str
    resolved: bool


def gh_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The gh child environment; telemetry off wins over the user's defaults."""
    env = dict(os.environ if base is None else base)
    env.update(GH_TELEMETRY_ENV)
    return env


def run_gh(args: Sequence[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    """Run one read-only gh command with telemetry disabled."""
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=gh_environment(),
    )


def is_loopback_url(value: str) -> bool:
    """True only for an http URL whose host is a loopback name."""
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return (
        parts.scheme == "http"
        and parts.hostname in LOOPBACK_HOSTS
        and parts.username is None
        and parts.password is None
    )


def _timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _nodes(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        return []
    nodes = value.get("nodes")
    return [node for node in nodes if isinstance(node, Mapping)] if isinstance(nodes, list) else []


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def review_rounds(reviews: Iterable[Mapping[str, Any]]) -> list[ReviewRound]:
    """One round per review body beginning `Review of <40-hex>`, in time order."""
    found: list[tuple[str, str]] = []
    for review in reviews:
        body = _text(review.get("body")).lstrip()
        match = REVIEW_MARKER.match(body)
        if not match:
            continue
        submitted = _text(review.get("submittedAt"))
        found.append((match.group(1), submitted))
    found.sort(key=lambda item: item[1])
    return [
        ReviewRound(number=index, sha=sha, submitted_at=submitted)
        for index, (sha, submitted) in enumerate(found, start=1)
    ]


def finding_priority(body: str) -> str | None:
    match = FINDING_MARKER.match(body.lstrip())
    return match.group(1) if match else None


def classify_finding(round_number: int | None, priority: str) -> str:
    """BLOCKING-CLASS is P0 always, P1 only in rounds 1-2; the rest is FOLLOW-UP."""
    if priority == "P0":
        return "BLOCKING-CLASS"
    if priority == "P1" and (round_number is None or round_number <= 2):
        return "BLOCKING-CLASS"
    return "FOLLOW-UP"


def _round_for_comment(
    rounds: Sequence[ReviewRound], sha: str, created_at: str
) -> ReviewRound | None:
    if sha:
        matching = [round_ for round_ in rounds if round_.sha == sha]
        if matching:
            return matching[-1]
    created = _timestamp(created_at)
    if created is not None:
        before = [
            round_ for round_ in rounds if (_timestamp(round_.submitted_at) or created) <= created
        ]
        if before:
            return before[-1]
    return rounds[0] if rounds else None


def parse_findings(
    threads: Iterable[Mapping[str, Any]], rounds: Sequence[ReviewRound]
) -> list[Finding]:
    findings: list[Finding] = []
    for thread in threads:
        resolved = bool(thread.get("isResolved"))
        for comment in _nodes(thread.get("comments")):
            priority = finding_priority(_text(comment.get("body")))
            if priority is None:
                continue
            commit = comment.get("originalCommit")
            sha = _text(commit.get("oid")) if isinstance(commit, Mapping) else ""
            round_ = _round_for_comment(rounds, sha, _text(comment.get("createdAt")))
            findings.append(
                Finding(
                    priority=priority,
                    finding_class=classify_finding(round_.number if round_ else None, priority),
                    round_number=round_.number if round_ else None,
                    sha=round_.sha if round_ else (sha or None),
                    path=_text(comment.get("path")),
                    resolved=resolved,
                )
            )
    return findings


def _check_failures(pr: Mapping[str, Any]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    rollup = pr.get("statusCheckRollup")
    for check in _nodes(rollup.get("contexts") if isinstance(rollup, Mapping) else None):
        name = _text(check.get("name")) or _text(check.get("context")) or "check"
        conclusion = _text(check.get("conclusion")) or _text(check.get("state"))
        if conclusion.upper() in FAILED_CHECKS:
            failures.append({"name": name, "conclusion": conclusion})
    return failures


def _review_latency(rounds: Sequence[ReviewRound], pr: Mapping[str, Any]) -> float | None:
    if not rounds:
        return None
    created = _timestamp(_text(pr.get("createdAt")))
    commit_times: dict[str, datetime] = {}
    for node in _nodes(pr.get("commits")):
        commit = node.get("commit")
        if isinstance(commit, Mapping):
            parsed = _timestamp(_text(commit.get("committedDate")))
            if parsed is not None:
                commit_times[_text(commit.get("oid"))] = parsed
    latencies: list[float] = []
    previous = created
    for round_ in rounds:
        submitted = _timestamp(round_.submitted_at)
        if submitted is None:
            continue
        start = commit_times.get(round_.sha, previous)
        if start is not None and submitted >= start:
            latencies.append((submitted - start).total_seconds())
        previous = submitted
    return float(median(latencies)) if latencies else None


def pr_quality(pr: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize one merged PR without storing any review or comment body."""
    rounds = review_rounds(_nodes(pr.get("reviews")))
    findings = parse_findings(_nodes(pr.get("reviewThreads")), rounds)
    blocking = sum(1 for finding in findings if finding.finding_class == "BLOCKING-CLASS")
    follow_up = sum(1 for finding in findings if finding.finding_class == "FOLLOW-UP")
    unresolved_blocking = sum(
        1
        for finding in findings
        if not finding.resolved and finding.finding_class == "BLOCKING-CLASS"
    )
    unresolved_follow_up = sum(
        1 for finding in findings if not finding.resolved and finding.finding_class == "FOLLOW-UP"
    )
    merged = _timestamp(_text(pr.get("mergedAt")))
    created = _timestamp(_text(pr.get("createdAt")))
    title = _text(pr.get("title"))
    reverted = title.lower().startswith("revert ")
    reverted = reverted or any(
        _text(node.get("commit", {}).get("messageHeadline")).lower().startswith("revert ")
        for node in _nodes(pr.get("commits"))
        if isinstance(node.get("commit"), Mapping)
    )
    return {
        "number": pr.get("number"),
        "title": title,
        "url": _text(pr.get("url")),
        "merged": merged is not None,
        "rounds": [
            {"number": round_.number, "sha": round_.sha, "submitted_at": round_.submitted_at}
            for round_ in rounds
        ],
        "findings": [
            {
                "priority": finding.priority,
                "class": finding.finding_class,
                "round": finding.round_number,
                "sha": finding.sha,
                "path": finding.path,
                "resolved": finding.resolved,
            }
            for finding in findings
        ],
        "blocking_findings": blocking,
        "follow_up_findings": follow_up,
        "unresolved_blocking_at_merge": unresolved_blocking,
        "unresolved_follow_up_at_merge": unresolved_follow_up,
        "review_latency_seconds": _review_latency(rounds, pr),
        "time_to_merge_seconds": (
            (merged - created).total_seconds()
            if merged is not None and created is not None
            else None
        ),
        "check_failures": _check_failures(pr),
        "reverted": reverted,
    }


def quality_metrics(quality: Mapping[str, Any], repository: str) -> list[Metric]:
    attrs = {"repository": repository, "pr": str(quality.get("number", ""))}
    metrics = [
        Metric("sextant_pr_review_rounds", "rounds", len(quality.get("rounds", [])), attrs),
        Metric(
            "sextant_pr_findings_blocking_class",
            "findings",
            int(quality.get("blocking_findings", 0)),
            attrs,
        ),
        Metric(
            "sextant_pr_findings_follow_up",
            "findings",
            int(quality.get("follow_up_findings", 0)),
            attrs,
        ),
        Metric(
            "sextant_pr_unresolved_blocking_at_merge",
            "threads",
            int(quality.get("unresolved_blocking_at_merge", 0)),
            attrs,
        ),
        Metric(
            "sextant_pr_check_failures",
            "checks",
            len(quality.get("check_failures", [])),
            attrs,
        ),
        Metric("sextant_pr_reverted", "bool", int(bool(quality.get("reverted"))), attrs),
    ]
    latency = quality.get("review_latency_seconds")
    if latency is not None:
        metrics.append(Metric("sextant_pr_review_latency_seconds", "seconds", latency, attrs))
    merge = quality.get("time_to_merge_seconds")
    if merge is not None:
        metrics.append(Metric("sextant_pr_time_to_merge_seconds", "seconds", merge, attrs))
    return metrics


def cost_metrics(
    aic: Decimal | int | float | None, router_notional_usd: Decimal | int | float | None
) -> list[Metric]:
    """AIC and router USD as two series. Never add, convert or merge them here.

    One AIC equals 0.01 USD of provider credits, but the router's invoice is a
    different measurement with a different authority; collapsing them would
    double-count and hide which ledger moved.
    """
    metrics: list[Metric] = []
    if aic is not None:
        metrics.append(Metric("sextant_gh_aw_aic", "AIC", Decimal(str(aic))))
    if router_notional_usd is not None:
        metrics.append(
            Metric("sextant_router_cost_notional_usd", "USD", Decimal(str(router_notional_usd)))
        )
    return metrics


def sum_same_unit(metrics: Sequence[Metric]) -> Decimal:
    """Sum only one unit; mixed AIC/USD is a programming error, not a total."""
    units = {metric.unit for metric in metrics}
    if len(units) > 1:
        raise ValueError(f"refusing to sum mixed units: {sorted(units)}")
    return sum((Decimal(str(metric.value)) for metric in metrics), start=Decimal(0))


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def run_metrics(run: Mapping[str, Any]) -> list[Metric]:
    """Normalize one gh-aw run; absent telemetry stays absent, never zero."""
    attrs = {
        "workflow": _text(run.get("workflow_name")) or _text(run.get("workflow")) or "unknown",
        "run": str(run.get("run_id") or run.get("database_id") or "unknown"),
        "model": _text(run.get("model")) or "unknown",
    }
    metrics: list[Metric] = []
    tokens = _number(run.get("token_usage"))
    if tokens is not None:
        metrics.append(Metric("sextant_gh_aw_tokens", "tokens", tokens, attrs))
    aic = _number(run.get("aic"))
    if aic is not None:
        metrics.append(Metric("sextant_gh_aw_aic_total", "AIC", Decimal(str(aic)), attrs))
    working_set = run.get("working_set")
    if isinstance(working_set, Mapping):
        rebuild = _number(working_set.get("rebuild_factor"))
        if rebuild is not None:
            metrics.append(Metric("sextant_gh_aw_rebuild_factor", "ratio", rebuild, attrs))
        peak = _number(working_set.get("peak_tokens"))
        if peak is not None:
            metrics.append(Metric("sextant_gh_aw_working_set_peak_tokens", "tokens", peak, attrs))
    friction = run.get("friction")
    if isinstance(friction, list):
        metrics.append(Metric("sextant_gh_aw_friction_events", "events", len(friction), attrs))
    mcp = run.get("mcp_tool_usage")
    if isinstance(mcp, Mapping) and mcp:
        total = sum(value for value in mcp.values() if isinstance(value, int) and value >= 0)
        metrics.append(Metric("sextant_gh_aw_mcp_calls", "calls", total, attrs))
    return metrics


def forecast_metrics(forecast: Mapping[str, Any]) -> list[Metric]:
    """Read the ForecastResult wrapper: each workflow owns its AIC fields.

    `gh aw forecast --json` marshals `ForecastResult{period, as_of, eval_mode,
    workflows}`; the per-run and projected AIC values live on each
    `ForecastWorkflowResult` inside `workflows` (gh-aw v1.0.1
    `pkg/cli/forecast_types.go:19-67,129-134`, `pkg/cli/forecast_render.go:17-24`).
    Tag every series with its workflow so two workflows never collapse into one.
    """
    metrics: list[Metric] = []
    workflows = forecast.get("workflows")
    if not isinstance(workflows, list):
        return metrics
    for workflow in workflows:
        if not isinstance(workflow, Mapping):
            continue
        attrs = {"workflow": _text(workflow.get("workflow_id")) or "unknown"}
        path = _text(workflow.get("workflow_path"))
        if path:
            attrs["workflow_path"] = path
        for field_name, metric_name in (
            ("avg_aic", "sextant_gh_aw_aic_average"),
            ("p50_aic_per_run", "sextant_gh_aw_aic_p50"),
            ("p95_aic_per_run", "sextant_gh_aw_aic_p95"),
            ("projected_aic", "sextant_gh_aw_aic_projected"),
            ("weekly_projected_aic", "sextant_gh_aw_aic_weekly_projected"),
            ("monthly_projected_aic", "sextant_gh_aw_aic_monthly_projected"),
        ):
            value = _number(workflow.get(field_name))
            if value is not None:
                metrics.append(Metric(metric_name, "AIC", Decimal(str(value)), dict(attrs)))
    return metrics


def runner_metrics(runners: Iterable[Mapping[str, Any]]) -> list[Metric]:
    metrics: list[Metric] = []
    for runner in runners:
        name = _text(runner.get("name")) or "unknown"
        attrs = {"runner": name}
        online = int(runner.get("status") == "online")
        metrics.append(Metric("sextant_runner_online", "bool", online, attrs))
        metrics.append(Metric("sextant_runner_busy", "bool", int(bool(runner.get("busy"))), attrs))
    return metrics


def _json_from_output(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return None
    for index, character in enumerate(stripped):
        if character in "[{":
            try:
                return json.loads(stripped[index:])
            except json.JSONDecodeError:
                return None
    return None


def _command_record(kind: str, args: Sequence[str], *, timeout: int, parser: str) -> dict[str, Any]:
    try:
        completed = run_gh(args, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"kind": "error", "payload": {"source": kind, "error": str(error)[:500]}}
    if completed.returncode != 0:
        return {
            "kind": "error",
            "payload": {
                "source": kind,
                "error": (completed.stderr or completed.stdout).strip()[:500],
            },
        }
    if parser == "json":
        payload = _json_from_output(completed.stdout)
        if payload is None:
            return {
                "kind": "error",
                "payload": {"source": kind, "error": "response was not JSON"},
            }
        return {"kind": kind, "payload": payload}
    return {"kind": kind, "payload": {"text": completed.stdout.strip()[:4000]}}


def _systemd_state() -> dict[str, str]:
    states: dict[str, str] = {}
    for unit in ("sextant-jit@sealed", "sextant-jit@docker-1"):
        try:
            completed = subprocess.run(
                ["systemctl", "--user", "-M", "sextant-runner@", "is-active", unit],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            states[unit] = "unknown"
            continue
        states[unit] = completed.stdout.strip() or "unknown"
    return states


def collect_once(
    repository: str,
    *,
    limit: int = DEFAULT_LIMIT,
    timeout: int = 180,
    audit_run: str | None = None,
) -> list[dict[str, Any]]:
    """Collect L5 reads once. Every source failure is a record, not an exception."""
    records: list[dict[str, Any]] = [
        {"kind": "schema", "payload": {"version": 1, "repository": repository}}
    ]
    owner, _, name = repository.partition("/")
    records.append(
        _command_record(
            "pull_requests",
            [
                "api",
                "graphql",
                "-f",
                f"query={PR_QUERY}",
                "-f",
                f"owner={owner}",
                "-f",
                f"name={name}",
                "-F",
                f"limit={limit}",
            ],
            timeout=timeout,
            parser="json",
        )
    )
    records.append(
        _command_record(
            "gh_aw_logs",
            ["aw", "logs", "review", "--json"],
            timeout=timeout,
            parser="json",
        )
    )
    records.append(
        _command_record(
            "gh_aw_forecast", ["aw", "forecast", "--json"], timeout=timeout, parser="json"
        )
    )
    records.append(
        _command_record("gh_aw_health", ["aw", "health"], timeout=timeout, parser="text")
    )
    if audit_run:
        records.append(
            _command_record(
                "gh_aw_audit",
                ["aw", "audit", audit_run, "--parse", "--json"],
                timeout=timeout,
                parser="json",
            )
        )
    records.append(
        _command_record(
            "runners",
            ["api", f"repos/{repository}/actions/runners"],
            timeout=timeout,
            parser="json",
        )
    )
    for record in records:
        if record["kind"] == "runners" and isinstance(record.get("payload"), dict):
            record["payload"]["systemd"] = _systemd_state()
    return records


def metrics_from_records(records: Iterable[Mapping[str, Any]], repository: str) -> list[Metric]:
    metrics: list[Metric] = []
    errors = 0
    for record in records:
        kind = record.get("kind")
        payload = record.get("payload")
        if kind == "error":
            errors += 1
            continue
        if kind == "pull_requests" and isinstance(payload, Mapping):
            data = payload.get("data")
            repo = data.get("repository") if isinstance(data, Mapping) else None
            for pr in _nodes(repo.get("pullRequests") if isinstance(repo, Mapping) else None):
                metrics.extend(quality_metrics(pr_quality(pr), repository))
        elif kind == "gh_aw_logs" and isinstance(payload, Mapping):
            runs = payload.get("runs")
            for run in runs if isinstance(runs, list) else []:
                if isinstance(run, Mapping):
                    metrics.extend(run_metrics(run))
        elif kind == "gh_aw_forecast" and isinstance(payload, Mapping):
            metrics.extend(forecast_metrics(payload))
        elif kind == "runners" and isinstance(payload, Mapping):
            metrics.extend(runner_metrics(payload.get("runners", [])))
    metrics.append(Metric("sextant_monitor_collector_errors", "errors", errors))
    return metrics


def _otlp_value(value: Decimal | int | float) -> dict[str, float]:
    return {"doubleValue": float(value)}


def _attribute(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}


def otlp_payload(metrics: Sequence[Metric], service: str) -> dict[str, Any]:
    now = str(time.time_ns())
    points = [
        {
            "asDouble": float(metric.value),
            "timeUnixNano": now,
            "attributes": [
                _attribute(key, str(value)) for key, value in sorted(metric.attributes.items())
            ],
        }
        for metric in metrics
    ]
    gauges = [
        {
            "name": metric.name,
            "unit": metric.unit,
            "gauge": {"dataPoints": [point]},
        }
        for metric, point in zip(metrics, points, strict=True)
    ]
    return {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        _attribute("service.name", service),
                        _attribute("telemetry.sdk.language", "python"),
                    ]
                },
                "scopeMetrics": [{"scope": {"name": "sextant.monitor.github"}, "metrics": gauges}],
            }
        ]
    }


def post_otlp(endpoint: str, payload: Mapping[str, Any]) -> int:
    """POST JSON to a loopback OTLP/HTTP endpoint; any other host is refused."""
    if not is_loopback_url(endpoint):
        raise ValueError(f"OTLP endpoint must be loopback http, got {endpoint!r}")
    parts = urlsplit(endpoint)
    connection = http.client.HTTPConnection(
        parts.hostname or "127.0.0.1", parts.port or 4318, timeout=3
    )
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    connection.request(
        "POST",
        parts.path or "/v1/metrics",
        body=body,
        headers={"Content-Type": "application/json"},
    )
    response = connection.getresponse()
    response.read()
    status = response.status
    connection.close()
    if status >= 300:
        raise RuntimeError(f"OTLP endpoint returned HTTP {status}")
    return status


def default_output() -> Path:
    state = os.environ.get("XDG_STATE_HOME")
    base = Path(state) if state else Path.home() / ".local" / "state"
    return base / "sextant" / "monitor" / "github.jsonl"


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect L5 GitHub quality metrics once.")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--no-otlp", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--audit-run", default=None)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)

    records = collect_once(
        args.repo,
        limit=args.limit,
        timeout=args.timeout,
        audit_run=args.audit_run,
    )
    metrics = metrics_from_records(records, args.repo)
    if not args.no_otlp:
        try:
            post_otlp(OTLP_ENDPOINT, otlp_payload(metrics, "sextant-monitor-l5"))
        except (OSError, RuntimeError, ValueError) as error:
            records.append(
                {"kind": "error", "payload": {"source": "otlp", "error": str(error)[:500]}}
            )
    if args.dry_run:
        print(json.dumps({"records": records, "metrics": [metric.name for metric in metrics]}))
        return 0
    output = args.out or default_output()
    write_jsonl(output, records)
    print(f"{output}: {len(records)} records, {len(metrics)} metrics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
