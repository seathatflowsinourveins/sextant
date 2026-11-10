# L7 monitor rules

Informational, proposal-only alerting for the agent/LLM monitor. The rules are
Prometheus recording and alerting rules for the local
[grafana/docker-otel-lgtm](https://github.com/grafana/docker-otel-lgtm) backend
at v0.38.0 (`9c57b1400ccdb8920e1a2b6083134cc5ef244a8f`). They normalize to the
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

- `rules.yaml`: twelve recording rules and eleven alert rules covering the
  eight converged signals: cache efficiency and waste, context pressure and
  rebuild churn, a rolling five-minute retry loop, error and friction SLOs,
  quota burn and time-to-exhaustion, cost anomaly against the trailing p95,
  and ADR-0030 model/effort compliance. Three normalization records map the
  pinned OTel GenAI counters (and L5's run error ratio) onto the ten
  `sextant_llm_*`/`sextant_agent_*` contract series; the other nine records
  derive the signal vector. Monitor staleness is the separate Grafana rule in
  `deploy/monitor/lgtm/alerting/`, so there is one definition.
- `parameters.json`: the registry. Each alert carries `threshold_ref` and
  `threshold_value`; the referenced row holds the value and its source.
- `producers.json`: the producer map. Each of the eleven alert series names
  either the script or recording rule that writes it, or a pending owner and
  the reason the source does not exist yet.

## Wiring

Point the local Prometheus at `rules.yaml` (`rule_files`) for the signal
alerts. Monitor staleness is not in this file: it is the Grafana-provisioned
rule in `deploy/monitor/lgtm/alerting/`, mounted into the existing store. The
backend is loopback only: Grafana 3000, OTLP/gRPC 4317, OTLP/HTTP 4318 on
`127.0.0.1`. Do not publish those ports on another interface.

The metric contract comes from the other monitor writers. L5
(`scripts/monitor_github.py`, manual only) emits the `sextant_gh_aw_*`,
`sextant_pr_*` and `sextant_runner_*` families; scheduled L3/L4 and L6 emit
the `sextant_monitor_last_success_timestamp_seconds` heartbeat, and L6 also
emits `sextant_manifest_*`, `sextant_budget_utilization`, `sextant_doc_age_days`
and `sextant_trial_ledger_rows`. M1's pinned GenAI counters feed the three
normalization records once PR-M2 lands the runtime feed.

Six series have no writer in this tree yet: context pressure, consecutive tool
failures, cost in USD, quota remaining, quota burn and review model/effort
compliance. `producers.json` records each one as `PENDING` with its owner and
the reason a source does not exist; `rules.yaml` labels those alerts
`producer_status: pending`, so they stay dormant instead of reading a
fabricated zero. The five produced alerts here are cache hit, cache waste,
rebuild churn, run error ratio and friction; monitor staleness is the Grafana
rule in `deploy/monitor/lgtm/alerting/`. A series that has not arrived is
stale/unknown, not zero. The Grafana rule `MonitorEvidenceStale` fires on an
absent timestamp as well as an old one, so a quiet monitor cannot look healthy.

## Privacy

L5 parses the GraphQL payload into derived per-PR quality summaries inside
`collect_once`; review bodies, comment bodies and diff paths never leave that
function, so `--dry-run` output and the local JSONL contain no prompt or
response text, tool arguments, command lines or file paths. L6 reads only the
manifest, test names, git timestamps and local budget counts. Nothing in this
directory uploads to a third party.
