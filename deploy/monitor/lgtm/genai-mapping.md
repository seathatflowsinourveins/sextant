# GenAI schema: pinned vendor -> `gen_ai.*` mapping

Pins (both on/before the 2026-10-25 fourteen-day cutoff, Apache-2.0):

- `open-telemetry/semantic-conventions-genai@9ffc7e00c639be7712e544e3e54331e885dccf84` (2026-10-21): `docs/gen-ai/gen-ai-token-metrics.md`, `docs/gen-ai/client-inference.md`. Status is **Development** throughout: this table is Sextant's internal normal form at this commit, not a stability promise; renames land by re-pinning this file.
- `open-telemetry/semantic-conventions@v1.44.0` (`e10a930844c6951757a43b849d364f7d056ac32b`, 2026-08-04) for the core resource/log attributes the GenAI document builds on.

Vendor-native series are kept lossless in the store (`claude_code.*`,
`codex.*`); nothing is renamed in the collector. The `gen_ai.*` series are
derived from this table (collector attribute aliases in
`otelcol-config.yaml` today; metric derivation once PR-M2 feeds make the
series observable). Token counters at the pin (all `{token}` counters):
`gen_ai.client.inference.usage.input_tokens` (**including** cached),
`.output_tokens` (**including** reasoning), `.cache_read.input_tokens`,
`.cache_write.input_tokens` (subsets of input) and
`.reasoning.output_tokens` (subset of output). Timing: CLI-observed
`gen_ai.client.inference.time_to_first_chunk` and server-side
`gen_ai.server.time_to_first_token` / `time_per_output_token` are different
views; never sum or substitute one for the other.

| Vendor source | `gen_ai.*` target | Rule |
|---|---|---|
| Claude `claude_code.token.usage{type=input}` + `{type=cacheRead}` + `{type=cacheCreation}` | `gen_ai.client.inference.usage.input_tokens` | **Add, never rename:** Claude `input` excludes cache, GenAI input includes it |
| Claude `{type=cacheRead}` / `{type=cacheCreation}` | `.cache_read.input_tokens` / `.cache_write.input_tokens` | Direct subsets of the input sum above |
| Claude `{type=output}` | `gen_ai.client.inference.usage.output_tokens` | Direct; any reasoning split inside Claude output is `no source` today, never `0` |
| Claude `claude_code.cost.usage` (USD) | — (kept vendor-native) | No GenAI cost counter at the pin; never summed with notional router USD or AIC |
| Codex span `gen_ai.usage.input_tokens` / `cache_read` / `cache_write` | Same-named usage counters | Codex already emits `gen_ai.usage.*` attributes; keep per-turn grain, never present as Claude's per-request grain |
| Codex `codex.turn.ttft.duration_ms` | `gen_ai.client.inference.time_to_first_chunk` (s) | CLI-observed view; convert ms -> s, keep percentiles, never averaged rates |
| Router per-call `ttft_ms` (OmniRoute, PR-M4) | `gen_ai.server.time_to_first_token` (s) | Server view only; kept separate from CLI-observed TTFT |
| `skill.name`, `mcp_server.name`, `mcp_tool.name` attributes | `skill_name`, `mcp_server_name`, `mcp_tool_name` | Copied by the collector transform; the dotted originals are kept |

Unknown stays unknown (ADR-0018): a runtime with no native signal for a row
renders `no source` / `null`, never `0`. Speed is shown as p50/p95 of TTFT
and decode `tok/s = output_tokens / (duration - ttft)`, never as an averaged
rate.
