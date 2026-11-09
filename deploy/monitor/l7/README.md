# L7 monitor rules

Informational, proposal-only alerting for the agent/LLM monitor. The rules are
Prometheus recording and alerting rules for the local
[grafana/docker-otel-lgtm](https://github.com/grafana/docker-otel-lgtm) backend
at v0.38.0 (`9ffc7e00c639be7712e544e3e54331e885dccf84`). They normalize to the
OTel GenAI conventions and the signal set in Balusu (2026)
(`doi:10.1145/3805760.3814931`) and IBM XPerf (`arXiv:2608.20370v1`), read
2026-11-08.

## What this is not

- It is not a kill switch. No rule stops a lane, session, container or order.
- It is not a gate. `delivery: informational` and `action: proposal-only` are
  labels on every alert; a human decides what the next PR changes.
- It is not calibrated. Every value in `parameters.json` has
  `status: UNCALIBRATED` until 30 days of local evidence exist (ADR-0018).
  A tuned value arrives as a reviewed proposal with its evidence, never as a
  silent edit.

## Files

- `rules.yaml`: ten recording rules and twelve alert rules covering the eight
  converged signals: cache efficiency and waste, context pressure and rebuild
  churn, a rolling five-minute retry loop, error and friction SLOs, quota burn
  and time-to-exhaustion, cost anomaly against the trailing p95, ADR-0030
  model/effort compliance, and the monitor's own staleness.
- `parameters.json`: the registry. Each alert carries `threshold_ref` and
  `threshold_value`; the referenced row holds the value and its source.

## Wiring

Point the local Prometheus at `rules.yaml` (`rule_files`) or copy it into the
LGTM Grafana provisioning tree. The backend is loopback only: Grafana 3000,
OTLP/gRPC 4317, OTLP/HTTP 4318 on `127.0.0.1`. Do not publish those ports on
another interface.

The metric contract comes from the other monitor writers: M1's collector emits
the OTel GenAI series; L5 (`scripts/monitor_github.py`) emits
`sextant_gh_aw_*`, `sextant_pr_*` and `sextant_runner_*`; L6
(`scripts/monitor_evidence.py`) emits `sextant_manifest_*`,
`sextant_budget_utilization`, `sextant_doc_age_days` and
`sextant_trial_ledger_rows`. A series that has not arrived is stale/unknown,
not zero. `MonitorEvidenceStale` fires on an absent timestamp as well as an old
one, so a quiet monitor cannot look healthy.

## Privacy

The collector never stores prompts, responses, tool arguments, command lines or
file paths. L5 strips review and comment bodies after parsing; L6 reads only
the manifest, test names, git timestamps and local budget counts. Nothing in
this directory uploads to a third party.
