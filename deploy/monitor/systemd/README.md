# Monitor bridge scheduler

The `scripts/` bridges are one-shot: collect once, exit. Nothing scheduled
them, so the OTLP store stopped advancing on 2026-11-09 while the container
stayed healthy. This directory adds checked-in per-user units.

- `sextant-monitor.service` — `Type=oneshot`; three `ExecStart` lines:
  `monitor_l3_l4.py --otlp --dsh-home %h/.dsh`, `monitor_github.py` (OTLP by
  default; no `--otlp` flag), `monitor_evidence.py --otlp`. Each starts with
  `-`, so one bridge's failure is recorded but the next still runs; the 5 min
  timeout leaves room for `monitor_github.py`'s own 180 s timeout.
- `sextant-monitor.timer` — `OnStartupSec=60s`, `OnUnitActiveSec=60s`,
  `AccuracySec=1s`; `OnStartupSec` is relative to the user manager's start.
- `parameters.json` — the period row: 60 s, `UNCALIBRATED`, sourced to the
  OpenTelemetry SDK's `OTEL_METRIC_EXPORT_INTERVAL` default of 60000 ms and
  bounded by `monitor_staleness_seconds_max` (900 s). A period change touches
  this row, the timer and the Grafana group interval; the proof fails if they
  diverge.
- `install.sh` — substitutes `%h/sextant` for the checkout
  (`SEXTANT_REPO` overrides), installs into `~/.config/systemd/user`, then
  `daemon-reload` and `enable --now`.

```sh
bash deploy/monitor/systemd/install.sh
systemctl --user list-timers sextant-monitor.timer
systemctl --user disable --now sextant-monitor.timer
rm ~/.config/systemd/user/sextant-monitor.{service,timer}
systemctl --user daemon-reload
```

Only loopback OTLP metrics are written. The staleness alert is
`deploy/monitor/lgtm/alerting/sextant-monitor-staleness.yaml`; the lead
recreates the container after the B bursts. This is the single definition.
