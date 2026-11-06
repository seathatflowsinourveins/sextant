# Foundations convergence, 2026-11-05

**Decision informed:** which maintained upstream fills each harness job, under the owner's rules "NEVER SELF INVENT" and "compounding learning and self maintancing lifecycle".

**Method:** the owner's convergence method, seathatflowsinourveins/northstar@`b384d298d217d3f8d9aa83356994629536a34795`:`docs/decisions/0045-harness-first-upstream-first.md`, amendment 2026-11-01 (2), "Convergence integrity". One neutral brief, registered before any result, with criteria in a fixed order: fit, maintenance and install path, evidence, footprint, licence. Two blind legs from two families, each screening the owner's 387 stars. Neither read the other, a synthesis or a ruling. Reconciled by the lead at primary sources. That method asks for two syntheses from two families; there was one, by the lead, which is recorded here as a shortfall.

| Input | sha256 | Harness, as each leg reports it |
|---|---|---|
| [BRIEF.md](2026-11-05-foundations-legs/BRIEF.md) | `d23f4a50620d6575…` | |
| [leg-gpt.md](2026-11-05-foundations-legs/leg-gpt.md) | `0895fa6fa6216fb3…` | Codex CLI 0.166.0; `gpt-6.1-sol` and max requested at launch. The leg marks served model and effort UNVERIFIED |
| [leg-deepseek.md](2026-11-05-foundations-legs/leg-deepseek.md) | `b2f87eddab630d0a…` | dsh 0.2.1-rc.5, `deepseek-flash`, max |

**Process notes:**
- My `codex exec -o` pointed at the leg's report path, so its final message overwrote the report when it exited. I restored it from the session log, and it matches the hash recorded before the overwrite.
- A Claude leg did not run. One family's disagreement is therefore not settled by a third, and each is reported below.
- The legs' claim ledgers hold every pinned source with its read date. Load-bearing facts get re-read when a pick is installed. Its PR cites them.

## Results

| Job | GPT leg | DeepSeek leg | Reconciled |
|---|---|---|---|
| J1 PR automation | `github/gh-aw` + native auto-merge | same | **Converged.** Version settled at source: `v1.0.1` (`0627fdbe4beb5f3b71aa569f8d97150b87f2111a`) is the latest stable release; the DeepSeek leg's `v1.2.0` is a prerelease |
| J2 Lifecycle | Renovate 44.221.1 + gh-aw's updater | Renovate 44.221.1 + a scheduled gh-aw agent | **Converged.** Neither found an upstream that retires unused items |
| J3 Learning | Compound Engineering `ce-compound` + `trader-memory-core`, `signal-postmortem` | same, plus Hindsight for capture | **Mostly converged.** See disagreement 2 |
| J4 Research method | Compound Engineering `ce-bakeoff` | ARIS-Code v0.4.28 | **Disagree.** See disagreement 1 |
| J5 Trading skills | `tradermonty/claude-trading-skills` at `d8e71ce2f0b069eb5b6fca352857c168c35e6c46`, with NautilusTrader's own examples | same skills | **Converged.** No tag exists, so the commit is the pin |
| J6 Options, Jev | `options-strategy-advisor` + `typesafe-ai/skills` v0.6.2 (`302eea662c54bca6730873fe245bec1d69ebc23d`) | same | **Converged** |

## Disagreements
1. **Research method.** GPT picks `ce-bakeoff`: a native skill, in a plugin J3 already installs, with fresh contexts and an independent judge, though it allows a same-family fallback unless the brief requires named families. DeepSeek picks ARIS: an executor and reviewer loop with cross-family receipts, but at its tag it is a separate binary and the leg found no dsh support there. **Call:** `ce-bakeoff`, because the owner asks for native invoke and a fourth CLI adds footprint. The brief names the families. Revisit when "ARIS ships a tagged plugin with dsh support, next version".
2. **Hindsight for capture.** DeepSeek adds it; GPT makes it the runner-up, because it adds a daemon. Its Claude and Codex routes use three lifecycle hooks per host (`SessionStart`, `UserPromptSubmit`, `Stop`), which conflicts with "no friction unneeded cause by hooks". **Call:** the repo-native `docs/solutions/` path now, which also travels through GitHub. OpenViking stays the owner's named RAG. Revisit when "a measured need for session capture beyond repo learning, or Hindsight ships hook-free Claude and Codex routes".

## J1 against what is running now
Both legs chose gh-aw with its supported Claude and Codex engines. The owner's later routing is dsh by default and Anthropic only when quality needs it. At `v1.0.1`, gh-aw lists its DeepSeek Harness engine as an unsupported sample with no compatibility commitment, pinned to dsh `0.2.0-rc.2`, and its routes are Copilot, Anthropic and OpenAI. So `review.yml` stays on upstream actions until the first landing proves the path, and then the owner chooses.

## Other findings
- **OpenHands, which the owner named:** both legs screened it. GPT: it adds a control-center and service stack to a fixed runtime roster. DeepSeek: its automation is a cloud scheduler. Neither picks it. Revisit when "OpenHands ships a local automation path that needs no service stack".
- **ECC:** broad hooks and rules, no pick. Its `--no-hooks` install exists if the owner wants part of it.
- **OMC:** GPT recommends leaving its hook bundle uninstalled. The owner asked for it by name, so it stays as ADR-0001 records: installed, off until a session turns it on.
- **Not verified by either leg:** the composed workflows end to end, review quality, memory retrieval quality and any trading result. Neither found a public evaluation of the finalists that names harness, model and effort.
