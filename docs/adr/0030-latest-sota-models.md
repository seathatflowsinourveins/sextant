# ADR-0030: Every model surface runs its family's latest SOTA model

## Context
The owner, 2026-11-06 (relayed verbatim on sextant#58): "please always using the latest sota models as our main rule for always latest landsscape, for gpt using gpt 6.1sol for main workhourse, and other models family using the latest osta models https://artificialanalysis.ai/models". Also: "cc stay native gpt powered omni etc".

The old campaign's "never stale" rule (seathatflowsinourveins/northstar@b384d298d217d3f8d9aa83356994629536a34795: `docs/decisions/0039-model-freshness-and-memory-rag-layer.md`, with its 2026-10-21 amendment "freshness is a hard gate") rules out stale models and makes re-evaluation the gate.

## Decision
1. **Every model surface runs the highest-scoring model of its family's latest generation, at its runtime's highest supported effort.** Native gh-aw Codex review uses direct API `max`, not CLI `ultra` automatic delegation; [ADR-0001's dated rationale](0001-sextant-foundation.md) and [the review guide](../../deploy/review/README.md#model-effort-and-daily-quota) cite the pinned implementation. Research-leg harness sessions retain their separate ultra requirement. The ranking comes from the vendor's own model list plus one public evaluation that names model and effort: [Artificial Analysis, Intelligence Index](https://artificialanalysis.ai/models). A gap under 3 points on that index doesn't move a pin. The 3-point band is carried from the old campaign's registered text, seathatflowsinourveins/northstar@6957af5d6f06b0a1be82b97a8246dea51c9dce3f: `docs/research/2026-11-05-token-efficiency-practice.md:106` ("Treat any gap under 3 points…") and `docs/research/2026-11-01-adr-0071-open-subdecisions.md:232` (RV-12, "clears the 3-point floor"). It is an uncalibrated starting value under Rule 2, a registry row, not a measured threshold.
2. **The owner's named exception:** GPT runtimes use `gpt-6.1-sol` as the workhorse. If Artificial Analysis rates another OpenAI model 3 or more points above it on the same index, the lead brings it to the owner and doesn't switch silently.
3. **Pins as read on 2026-11-06 by the lead** (https://artificialanalysis.ai/models, read 2026-11-06 at 13:22 EST; Intelligence Index top five: Gemini 4 Carbon (High) 60, Claude Opus 5.5 (Max) 59, Gemini 4 Carbon (Medium) 58, Claude Opus 5.5 (Xhigh) 57, GPT-6 Astra (Max) 57):

| Family | Model | Surfaces |
|---|---|---|
| Anthropic | Claude Opus 5.5, max effort | every Claude tab, native on the owner's sign-in; never through a router |
| OpenAI | `gpt-6.1-sol`, highest effort. Artificial Analysis scored it 54.6 on the 2026-11-07 re-read, 2.3 points under GPT-6 Astra (Max) 56.9 — inside the 3-point band, so the pin does not move; Sol remains the owner's named exception (see the 2026-11-07 amendment) | native Codex; OmniRoute's GPT lanes (Pi, OMP, OpenCode v2, Hermes, OpenHands SDK) |
| Google | Gemini 4 Carbon (High), 60. Interim: Gemini 4 Argon High, the highest model the owner's Google account catalog exposes until Carbon appears there (#62). The owner dropped Gemini CLI, so the surface is Antigravity | Gemini CLI, Antigravity |
| DeepSeek | DeepSeek-V4.1-Flash-1017 (`deepseek-flash`), thinking enabled and `reasoning_effort=max`. DeepSeek's [model list](https://api-docs.deepseek.com/api/list-models/), [version list](https://api-docs.deepseek.com/quick_start/pricing/) and [effort contract](https://api-docs.deepseek.com/guides/thinking_mode/), read 2026-11-06, establish the latest listed generation and supported `max`; the default is only `high`. Artificial Analysis lists DeepSeek V4.1 Flash 1017 (Max), 33, among open weights | dsh |
| Meta | to be confirmed from Meta's list. The page lists Muse Wonder unscored | Muse via OmniRoute |

2026-11-07, OpenAI row amendment: **Sol is scored now, and the gap stays inside the band.** [Artificial Analysis/models](https://artificialanalysis.ai/models), lead read 2026-11-07 at 20:44 EST: GPT-6.1 Sol (Max) 54.6, GPT-6 Astra (Max) 56.9, GPT-6.1 Terra 51.3. Astra's 2.3-point lead is under Decision 1's 3-point band, so no pin moves and Decision 2's owner referral is not triggered; `gpt-6.1-sol` stays the workhorse. This supersedes the 2026-11-06 cell that listed Sol unscored.

2026-11-07, DeepSeek row amendment: **V4 Pro is banned on every model surface.** Owner: "ban v4pro as it is supreceeded entirely"; [Artificial Analysis provider page](https://artificialanalysis.ai/providers/deepseek), lead read 2026-11-07: Flash max 33 / 13.7 min per task versus Pro max 23 / 23.8 min, at about one-quarter the price. The later worker read reports the same 33/23 scores and updated times 14.4/24.0 min. Historical research records retain what ran. In gh-aw review, Flash requests max through dsh 0.2.2-rc.1's documented patch keys (`reasoningEffort`, `reasoningEfforts`, `compat.forceAdaptiveThinking`); #201's probe recorded `reasoningEffort: max`. The Claude reviewer runs Opus at max effort through CLAUDE_CODE_EFFORT_LEVEL; gh-aw's `?effort=` suffix applies only in routed mode.

4. **The landscape stays current without anyone:** a daily Orca automation with a precheck reads the evaluation page and each vendor's list. When a family's top changes by 3 or more points, it opens a PR moving that pin, with the evidence. Built by the harness lane's tier 2 (#53).
5. **No quota hold (owner, 2026-11-06 16:14 EST, [#58](https://github.com/seathatflowsinourveins/sextant/issues/58#issuecomment-6695763286)):** "nevergated the usage , i will reset it when it hit the limit". Keep authorised runtime work moving without a quota hold; post a hit limit immediately as an owner step and continue on available connections. gh-aw review explicitly sets `max-daily-ai-credits: -1` on all three engines to remove the inherited daily-5000 activation gate, using v1.0.1's documented sentinel ([review guide and source](../../deploy/review/README.md#model-effort-and-daily-quota)); this leaves per-run execution bounds and provider limits intact.

## Consequences
- A pin without a dated read of both sources is unavailable, not a default (AGENTS.md Rule 2).
- The detector proposes, and the PR's review and the owner's exception decide. Nothing switches a model inside a running session.

## Revisit when
The owner names another evaluation, or Artificial Analysis stops scoring a family.
