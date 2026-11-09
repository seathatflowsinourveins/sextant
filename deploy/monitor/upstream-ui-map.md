# Monitor: upstream-built UIs first

One upstream-built UI per layer; Grafana holds only the cross-runtime live
layer. Heavyweight all-in-one trace platforms (Langfuse, Phoenix, Opik,
OpenLIT, Laminar, SigNoz as the default store) stay rejected: multi-container
stacks, non-OSI or split licences, telemetry on by default, traces-only OTLP.
All local URLs are loopback and **to verify at start**; PR-M1 starts nothing.

| Layer | Upstream UI | Reached at | Landed by |
|---|---|---|---|
| Sessions, tokens, tools, cost (archive) | `kenn-io/agentsview`'s own UI (passwordless, local) | `http://127.0.0.1:8080` | PR-M3 |
| Router, quotas, per-account windows | OmniRoute's own dashboard (already running; read-only for the monitor) | `http://127.0.0.1:20128` (B's router) / `http://127.0.0.1:22128` (clean distro) | existing |
| Workers, fix loops, PR loops | AO's own UI (`OrchestratorInc/agent-orchestrator`) | `http://127.0.0.1:3001` | existing |
| Live worktrees, terminals, subagents | Orca's agent view (in the Orca app; `orca worktree ps --json` is the CLI twin) | Orca app sidebar | existing |
| PRs, checks, review rounds | GitHub's PR and Actions UI, plus `gh aw audit` reports | github.com (the repo) | existing / PR-M5 |
| Cross-runtime live layer only: token speed, cost, skill and MCP calls per runtime and model | Grafana in `grafana/docker-otel-lgtm` (this folder's `lgtm/`) | `http://127.0.0.1:3000` | PR-M1 (this PR) |

## Grafana contents: what is provisioned as code

- **Datasources and dashboards already in the pinned image** (Apache-2.0,
  `grafana/docker-otel-lgtm@9c57b1400ccdb8920e1a2b6083134cc5ef244a8f`):
  `docker/grafana-datasources.yaml` provisions Prometheus, Tempo, Loki and
  Pyroscope on container loopback; `docker/grafana-dashboards.yaml`
  provisions the upstream RED Metrics (classic + native histogram) and JVM
  Metrics dashboard JSON. No UI edits are needed; anonymous access is
  Viewer-only, so nobody can edit them live either.
- **Upstream GenAI dashboard JSON: searched, none licensed exists.** The
  pinned LGTM repo ships only the RED/JVM JSON above, and
  `anthropics/claude-code-monitoring-guide` carries no licence
  (`license: null`) and is unmaintained, so its dashboards are not reused.
  Sextant's live-layer panels are therefore built later, as provisioned
  JSON, from the metric and event names in `lgtm/genai-mapping.md` once
  PR-M2's feeds make the series observable — inventing queries against
  unobserved series in PR-M1 would ship unproven panels.
