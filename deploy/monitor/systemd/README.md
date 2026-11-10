# Monitor bridge scheduler

The `scripts/` bridges are one-shot; a timer must run them. This directory
adds checked-in per-user units.

- `sextant-monitor.service` — `Type=oneshot`; two `ExecStart` lines:
  `monitor_l3_l4.py --otlp --dsh-home %h/.dsh-full` and
  `monitor_evidence.py --otlp`. Each starts with `-`, so one bridge's failure
  is recorded but the next still runs.
- `sextant-monitor.timer` — `OnStartupSec=60s`, `OnUnitActiveSec=60s`,
  `AccuracySec=1s`; `OnStartupSec` is relative to the user manager's start.
- `parameters.json` — the period row: 60 s, `UNCALIBRATED`, sourced to the
  OpenTelemetry SDK's `OTEL_METRIC_EXPORT_INTERVAL` default of 60000 ms and
  bounded by `monitor_staleness_seconds_max` (900 s). A period change touches
  this row, the timer and the Grafana group interval.
- `install.sh` — substitutes `%h/sextant` for the checkout
  (`SEXTANT_REPO` overrides), installs into `~/.config/systemd/user`, then
  `daemon-reload` and `enable --now`.

The dsh home is `~/.dsh-full`, named by `docs/start.md:47`
(`DSH_HOME=~/.dsh-full`) and `scripts/dsh_profile_doctor.py`'s
`DEFAULT_PROFILE`; the proof reads both and fails if the unit drifts.
Roster ops owns the `%h/sextant` checkout and updates it in its apply-after-merge
step, then reruns `install.sh`. Both scheduled bridges emit
`sextant_monitor_last_success_timestamp_seconds`; the Grafana rule keys on it.

```sh
bash deploy/monitor/systemd/install.sh
systemctl --user list-timers sextant-monitor.timer
```
