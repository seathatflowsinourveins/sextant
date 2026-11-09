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
  or the installed `~/.local/share/sextant-lane-runtimes/claude-launch.sh`.
  It execs native `claude`, retaining its authentication. `.claude/settings.json`
  supplies the same project defaults; use the wrapper to clear inherited content
  flags and per-signal destinations. Keep user/managed settings consistent with
  the contract: a process environment cannot override managed policy.
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

Sources: [Claude monitoring](https://code.claude.com/docs/en/monitoring-usage) and
[operational telemetry](https://code.claude.com/docs/en/data-usage#telemetry-services),
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
