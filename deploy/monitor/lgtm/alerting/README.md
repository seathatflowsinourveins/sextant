# Grafana staleness rule

`sextant-monitor-staleness.yaml` is the single definition; the LGTM compose
file mounts this directory read-only over `/otel-lgtm/grafana/conf/provisioning/alerting`,
and `deploy/monitor/l7/rules.yaml` has no duplicate.

Sources (read 2026-11-10): [Grafana file provisioning](https://grafana.com/docs/grafana/v13.2/alerting/set-up/provision-alerting-resources/file-provisioning/);
[Grafana alerting provisioning API](https://grafana.com/docs/grafana/v13.2/developers/http_api/alerting_provisioning/);
[No Data and error states](https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rule-evaluation/nodata-and-error-states/);
[Prometheus operators](https://prometheus.io/docs/prometheus/latest/querying/operators/);
`grafana/grafana@v13.2.4` `af4a33e3786594ad72f72d97e6744010330c2977`,
`pkg/services/provisioning/alerting/rules_provisioner.go`.

Absent or older than 900 s yields 1; fresh yields the fallback 0. The 900 mirrors
`monitor_staleness_seconds_max`; change both together. Without the fallback a
healthy empty result would be No Data and would alert.

`for: 60s` is the file-provisioning example's value. The alerting provisioning
API example carries `relativeTimeRange: {from: 600, to: 0}` for its Prometheus
query A, so A keeps that range; B and C are `__expr__`. Both values are
registered in `deploy/monitor/l7/parameters.json` as
`monitor_alert_hold_seconds` and `monitor_alert_query_from_seconds`
(UNCALIBRATED; read 2026-11-10). Both bridges emit the heartbeat;
`monitor_github.py` is not scheduled.

Runbook: `GET /api/v1/provisioning/alert-rules` on loopback Grafana, then
`systemctl --user status sextant-monitor.timer`.
