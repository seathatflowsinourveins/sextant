# Grafana staleness rule

`sextant-monitor-staleness.yaml` is the single definition of monitor staleness.
The LGTM compose file mounts this directory read-only over
`/otel-lgtm/grafana/conf/provisioning/alerting`; `deploy/monitor/l7/rules.yaml`
no longer carries a duplicate alert or recording rule.

Sources (read 2026-11-10): [Grafana file provisioning](https://grafana.com/docs/grafana/latest/alerting/set-up/provision-alerting-resources/file-provisioning/)
(`apiVersion: 1`, `folder: Sextant`, `interval: 60s`, `uid` under 40
characters); [No Data and error states](https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rule-evaluation/nodata-and-error-states/)
(`noDataState: Alerting` avoids a separate `DatasourceNoData` instance);
[Prometheus operators](https://prometheus.io/docs/prometheus/latest/querying/operators/)
(`or` + `on()`); `grafana/grafana@v13.2.4`
`af4a33e3786594ad72f72d97e6744010330c2977`,
`pkg/services/provisioning/alerting/rules_provisioner.go` (creates the missing
folder by title).

```promql
absent(sextant_monitor_last_success_timestamp_seconds)
  or (time() - sextant_monitor_last_success_timestamp_seconds > 900)
  or on() vector(0)
```

Absent or older than 900 s yields 1; a fresh heartbeat yields the fallback 0.
The `900` mirrors `monitor_staleness_seconds_max` in
`deploy/monitor/l7/parameters.json`; change both together. Without the fallback
a healthy empty result would be No Data and would alert. Live read-only check
on 2026-11-10: absent returned 1, synthetic fresh returned 0.

There is no Alertmanager, contact point or new delivery path. Grafana reloads
provisioned rules on restart; the lead recreates the container after the B
bursts. The proof is that the file parses and matches the schema.

Runbook: `GET /api/v1/provisioning/alert-rules` on loopback Grafana; if the
heartbeat is absent, check `systemctl --user status sextant-monitor.timer` and
the journal, then `systemctl --user start sextant-monitor.service`.
