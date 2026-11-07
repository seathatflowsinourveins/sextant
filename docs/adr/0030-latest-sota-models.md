# ADR-0030: Every model surface runs its family's latest SOTA model

## Context
The owner, 2026-11-06 (relayed verbatim on sextant#58): "please always using the latest sota models as our main rule for always latest landsscape, for gpt using gpt 6.1sol for main workhourse, and other models family using the latest osta models https://artificialanalysis.ai/models". Also: "cc stay native gpt powered omni etc".

The old campaign's "never stale" rule (seathatflowsinourveins/northstar@b384d298d217d3f8d9aa83356994629536a34795: `docs/decisions/0039-model-freshness-and-memory-rag-layer.md`, with its 2026-10-21 amendment "freshness is a hard gate") rules out stale models and makes re-evaluation the gate.

## Decision
1. **Every model surface runs the highest-scoring model of its family's latest generation, at its runtime's highest supported effort.** The ranking comes from the vendor's own model list plus one public evaluation that names model and effort: [Artificial Analysis, Intelligence Index](https://artificialanalysis.ai/models). A gap under 3 points on that index doesn't move a pin. The 3-point band is carried from the old campaign's registered text, seathatflowsinourveins/northstar@6957af5d6f06b0a1be82b97a8246dea51c9dce3f: `docs/research/2026-11-05-token-efficiency-practice.md:106` ("Treat any gap under 3 points…") and `docs/research/2026-11-01-adr-0071-open-subdecisions.md:232` (RV-12, "clears the 3-point floor"). It is an uncalibrated starting value under Rule 2, a registry row, not a measured threshold.
2. **The owner's named exception:** GPT runtimes use `gpt-6.1-sol` as the workhorse. If Artificial Analysis rates another OpenAI model 3 or more points above it on the same index, the lead brings it to the owner and doesn't switch silently.
3. **Pins as read on 2026-11-06 by the lead** (https://artificialanalysis.ai/models, read 2026-11-06 at 13:22 EST; Intelligence Index top five: Gemini 4 Carbon (High) 60, Claude Opus 5.5 (Max) 59, Gemini 4 Carbon (Medium) 58, Claude Opus 5.5 (Xhigh) 57, GPT-6 Astra (Max) 57):

| Family | Model | Surfaces |
|---|---|---|
| Anthropic | Claude Opus 5.5, max effort | every Claude tab, native on the owner's sign-in; never through a router |
| OpenAI | `gpt-6.1-sol`, highest effort. The page lists GPT-6.1 Sol **without** an Intelligence Index score; the only scored OpenAI entry is GPT-6 Astra (Max), 57. Sol is the owner's named exception, not a score-based pick | native Codex; OmniRoute's GPT lanes (Pi, OMP, OpenCode v2, Hermes, OpenHands SDK) |
| Google | Gemini 4 Carbon (High), 60. Interim: Gemini 4 Argon High, the highest model the owner's Google account catalog exposes until Carbon appears there (#62). The owner dropped Gemini CLI, so the surface is Antigravity | Gemini CLI, Antigravity |
| DeepSeek | DeepSeek-V4.1-Flash-1017 (`deepseek-flash`), thinking enabled and `reasoning_effort=max`. DeepSeek's [model list](https://api-docs.deepseek.com/api/list-models/), [version list](https://api-docs.deepseek.com/quick_start/pricing/) and [effort contract](https://api-docs.deepseek.com/guides/thinking_mode/), read 2026-11-06, establish the latest listed generation and supported `max`; the default is only `high`. Artificial Analysis lists DeepSeek V4.1 Flash 1017 (Max), 33, among open weights | dsh |
| Meta | to be confirmed from Meta's list. The page lists Muse Wonder unscored | Muse via OmniRoute |

4. **The landscape stays current without anyone:** a daily Orca automation with a precheck reads the evaluation page and each vendor's list. When a family's top changes by 3 or more points, it opens a PR moving that pin, with the evidence. Built by the harness lane's tier 2 (#53).
5. **No quota hold (owner, 2026-11-06 16:14 EST, [#58](https://github.com/seathatflowsinourveins/sextant/issues/58#issuecomment-6695763286)):** "nevergated the usage , i will reset it when it hit the limit". Keep authorised runtime work moving without a quota hold; post a hit limit immediately as an owner step and continue on available connections.

## Consequences
- A pin without a dated read of both sources is unavailable, not a default (AGENTS.md Rule 2).
- The detector proposes, and the PR's review and the owner's exception decide. Nothing switches a model inside a running session.

## Revisit when
The owner names another evaluation, or Artificial Analysis stops scoring a family.
