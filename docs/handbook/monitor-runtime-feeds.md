# Runtime OTel launch contract (PR-M2)

The lead adopted monitor RECONCILE §7 PR-M2 on 2026-11-08, including beta Claude
traces with redaction defaults retained and detailed beta tracing off. This is
configuration for the existing runtime pins; it installs no new runtime, collector,
backend or UI. Every exporter goes to `http://127.0.0.1:4317` over OTLP gRPC.

Activate after merge, with PR-M1's loopback redaction collector ready. Non-B homes
may adopt then; B's shared and lane homes wait until **after B**, between sessions.
This PR does not write any live home or change an active session. Deployment uses
the existing lane installer/parity path; never run the installer against B early.

- Claude: run `bash deploy/wsl/lane-runtimes/claude-launch.sh` from the checkout,
  or the installed `~/.local/share/sextant-lane-runtimes/claude-launch.sh`;
  `python3 scripts/role_launch.py <role>` takes it for every role and worker.
  It execs native `claude` with its authentication. Metrics export cumulatively for
  the store's Prometheus. The wrapper alone sets the exporter variables: Claude Code
  ignores them in a repository's project settings, so `.claude/settings.json` keeps
  only the page's opt-outs. User/managed settings must match the contract: managed
  policy beats a process environment.
- Codex: `sextant-codex` and `sextant-codex-review` send explicit `-c` overrides
  even when an existing lane config is kept. `parity.py` renders the same settings
  into a new lane `CODEX_HOME/config.toml`; project `.codex/config.toml` cannot
  supply OTel settings. Existing edited files remain refused and preserved.
  Managed/account homes keep their own authentication and are never copied into
  the lane home. Their owner applies the same config blocks after the timing gate.
- dsh: `sextant-dsh`/`dsh` set `DSH_TELEMETRY_DISABLED=1` and
  `DSH_TELEMETRY_MODE=DISABLED` before the strict `scripts/with-keys.sh` hop.
  Direct JS launches (including a TUI locator that bypasses the shell wrapper)
  must inherit these two variables from their launcher as well.

Claude emits metrics, logs and enhanced beta traces with `OTEL_LOG_TOOL_DETAILS=1`.
`ENABLE_BETA_TRACING_DETAILED=0` and an unset `BETA_TRACING_ENDPOINT` retain the
ordinary loopback OTLP path. `OTEL_LOG_USER_PROMPTS`, `OTEL_LOG_ASSISTANT_RESPONSES`,
`OTEL_LOG_RAW_API_BODIES` and `OTEL_LOG_TOOL_CONTENT` stay **unset**. Operational
telemetry, error reports and feedback surveys stay disabled. Optional
`SEXTANT_LANE` and `SEXTANT_PR` label Claude resources and Codex span attributes;
omit unavailable joins. Never put a credential in metadata, argv or a config.

Lesson from the pinned source: prompt opt-out alone is insufficient. Codex SSE
deltas default to true, its metrics default to Statsig, and tool-result logs still
contain arguments/output. We explicitly override all three exporters and set
`analytics.enabled`, `feedback.enabled`, `log_user_prompt`, `log_agent_responses`,
`log_guardian_assessments` and `log_sse_deltas` false. PR-M1 must delete Claude
`tool_input`, `tool_parameters` command/path content and Codex `arguments`/`output`,
then redact secret matches before persistence, retaining invocation names. This
proof establishes the launch flags, not live collector redaction or delivery.

Sources: [Claude monitoring](https://code.claude.com/docs/en/monitoring-usage),
read 2026-11-08 and 2026-11-10; [settings reference](https://code.claude.com/docs/en/settings-reference#variables-claude-code-ignores-in-env),
read 2026-11-10; [operational telemetry](https://code.claude.com/docs/en/data-usage#telemetry-services),
read 2026-11-08; `openai/codex@rust-v0.167.0`
`086ccc833bc9cf01024ad2dd6af7dbd421b6bf9a` (`codex-rs/config/src/types.rs:250-261,640-672`,
`otel/src/config.rs:9-35`, `otel/src/tool_result.rs:54-81`);
`deepseek-ai/deepseek-harness@dsh-v0.2.2-rc.1`
`66491b05e3f05ad35bcdd4f6cd7ed26041d9e3db` (`packages/boot/app-boot/src/profile-context.ts:28`,
`packages/bundle/base/cordis.patch.yml:205-225`). RECONCILE §3 exempts these existing
runtime pins from the ≥14-day rule for new supply-chain picks; no pin is changed.
`tests/proofs/test_monitor_runtime_feeds.py` runs via `just prove`. ADR-0018 keeps
absent data unknown and existing ledgers authoritative; ADR-0030's model, effort
and quota policy is unchanged. Revert the launch/config changes to disable feeds.

## L3/L4 aggregation lesson

PR #18's review at `109d1d2951c92f7d8f446622163ceb065dabadae` identified three
deterministic aggregation defects. Bind each assistant message's model and effort
before summing usage or timing samples: a later selection alone must change neither
historical attribution nor DeepSeek cost. Missing output usage remains unavailable
through session/model totals and cost estimation; retain independent TTFT samples
and measured zero outputs. Export router counts with joint provider/status
attributes, not overlapping marginal series under one metric name.

The regression witnesses in `tests/proofs/test_monitor_l3_l4.py` append a selection
without a call, mix models/efforts, remove output usage versus recording zero, and
sum the actual OTLP count points (two fixture calls must sum to two, not four).
Sources: `deepseek-ai/deepseek-harness@66491b05e3f05ad35bcdd4f6cd7ed26041d9e3db`,
`packages/core/agent/src/model-selection.ts:68-84`,
`packages/core/session/src/types.ts:339-357` and
`packages/llm/token-meter/src/turn-usage.ts:77-88`;
[OpenTelemetry metrics data model](https://opentelemetry.io/docs/specs/otel/metrics/data-model/),
spatial reaggregation, read 2026-11-09. This adds no deployment or new source reads.

## dsh collection is opt-in

PR #18's final-turn ruling on 2026-11-09 ships dsh session collection **OFF by
default** after review of `d82b6a863c434f9c624a1dde59a00b979ca35043` found that
automatic discovery guessed the wrong runtime home. Do not substitute another
guessed default: `snapshot()` and a CLI invocation without `--dsh-home PATH`
perform no dsh session reads, even when `DSH_HOME` is inherited or valid logs exist
in either `~/.dsh` or `~/.dsh-enhanced`. The source reports disabled/unavailable;
no dsh token, timing or cost metric is exported. Other bridge feeds are unchanged.

An operator can opt in with `python3 -I scripts/monitor_l3_l4.py --dsh-home ~/.dsh-full`
or a caller can supply an explicit API `paths["dsh_root"]`. Neither path changes
runtime configuration or starts a service. The regression proofs
`test_dsh_collection_is_off_by_default` and
`test_dsh_collection_requires_an_explicit_home` exercise both CLI and API defaults,
forbid the collector from being invoked without opt-in, and retain explicit-home
collection. Existing non-blocking review findings remain follow-ups, not fixes here.

Sources: [Python 3.13 argparse](https://docs.python.org/3.13/library/argparse.html#default)
(`None` for an absent optional argument) and
[Release Toggles](https://martinfowler.com/articles/feature-toggles.html#ReleaseToggles),
both read 2026-11-09; PR #18's final-turn ruling.
