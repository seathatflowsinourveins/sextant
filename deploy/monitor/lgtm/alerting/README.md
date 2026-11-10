# Grafana staleness rule

`sextant-monitor-staleness.yaml` is the single definition of monitor staleness;
the LGTM compose file mounts this directory read-only over
`/otel-lgtm/grafana/conf/provisioning/alerting`, and `deploy/monitor/l7/rules.yaml`
has no duplicate alert or recording rule.

Sources (read 2026-11-10): [Grafana file provisioning](https://grafana.com/docs/grafana/latest/alerting/set-up/provision-alerting-resources/file-provisioning/);
[No Data and error states](https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rule-evaluation/nodata-and-error-states/);
[Prometheus operators](https://prometheus.io/docs/prometheus/latest/querying/operators/);
`grafana/grafana@v13.2.4` `af4a33e3786594ad72f72d97e6744010330c2977`,
`pkg/services/provisioning/alerting/rules_provisioner.go`.

Absent or older than 900 s yields 1; fresh yields the fallback 0. The 900 mirrors
`monitor_staleness_seconds_max`; change both together. Without the fallback a
healthy empty result would be No Data and would alert. Live read-only check
2026-11-10: absent 1, synthetic fresh 0.

`for: 5m` comes from the old `deploy/monitor/l7/rules.yaml` `MonitorEvidenceStale`
(parent `dcbdc15`). Its 600 s `relativeTimeRange` blocks had no source, so they
were removed (read 2026-11-10); the Grafana example sets no range, says data
comes from the API, and the old Prometheus file has no Grafana window. Both
scheduled bridges emit the heartbeat; `monitor_github.py` is not scheduled.

Runbook: `GET /api/v1/provisioning/alert-rules` on loopback Grafana, then
`systemctl --user status sextant-monitor.timer`.
