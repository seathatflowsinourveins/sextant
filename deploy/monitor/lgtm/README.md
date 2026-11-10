# Local OTLP LGTM store (PR-M1)

One rootless container (`grafana/docker-otel-lgtm@v0.38.0`, pinned by digest
in `compose.yaml`) holding Prometheus, Loki, Tempo, Pyroscope, the OTel
Collector and Grafana for the cross-runtime live layer. Everything else is
read in its own upstream UI — see `../upstream-ui-map.md`.

- Start (clean distro, rootless Docker, between B bursts): `./start.sh`,
  then open `http://127.0.0.1:3000`. Stop: `docker compose down`.
- Passwordless: anonymous Viewer access, no login form, basic auth off;
  `start.sh` feeds Grafana a throwaway random admin password that is never
  stored or printed. There is no keys.sh step.
- Loopback only: `127.0.0.1:3000` (Grafana), `127.0.0.1:4317` (OTLP gRPC),
  `127.0.0.1:4318` (OTLP HTTP). Grafana analytics/update checks are off,
  plugin preinstall is disabled (`GF_PLUGINS_PREINSTALL_DISABLED=true`,
  including Grafana's built-in default set), and the `run-grafana.sh`
  override removes the forced `grafana-llm-app` download, so no start
  downloads a plugin or reports usage. Never run upstream `run-lgtm.sh`.
- `alerting/` is mounted read-only over Grafana's
  `conf/provisioning/alerting` directory; it carries the single
  monitor-staleness rule (see `alerting/README.md`). Grafana creates the
  `Sextant` folder on load. There is no Alertmanager or contact point.
- `otelcol-config.yaml` strips content-bearing tool fields and masks
  secret-shaped values before anything persists; `genai-mapping.md` pins
  the vendor -> `gen_ai.*` schema. Runtime feeds land in PR-M2, so until
  then the store receives only its own collector self-metrics.
- Tunables (retention, memory cap, host floors) are `parameters.json`
  registry rows, UNCALIBRATED until baselined (ADR-0018). Data persists in
  the `sextant-lgtm-data` volume (`/data`); Tempo retention keeps its
  in-image default (no upstream extra-args row at the pin) — UNKNOWN until
  measured in the first run week.
