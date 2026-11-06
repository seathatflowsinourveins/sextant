# Sextant convergence — DeepSeek leg

- **Harness:** DeepSeek Harness (dsh) `0.2.1-rc.5` (`/home/choreo/.northstar/dsh/0.2.1-rc.5/node_modules/.bin/dsh`)
- **Model:** `deepseek-flash` (as reported by this session's system prompt; not independently verified against the serving endpoint)
- **Effort:** highest reasoning effort supported by this session; no numeric effort knob is exposed in-session
- **Date of work:** 2026-11-05 (America/New_York), pins read 2026-11-05
- **Blind leg:** I read only `BRIEF-deepseek.md`, `owner-stars.tsv`, and public upstream sources. I did not read any other leg, synthesis, lead ruling, `seathatflowsinourveins/*`, `~/Developer/northstar`, or any other `~/.northstar` path.
- **Evidence rule applied:** a claim is only in the ledger if I read it at the pinned ref today; negative claims say where I looked.

## Bottom line

| Job | Pick | Pin | One-line fit |
|---|---|---|---|
| J1 PR automation | `github/gh-aw` + GitHub native auto-merge | tag `v1.2.0`, commit `18928ba35b7e374d394be6406c7213ed3f0d9454` | Two engines review the PR, each submits a review and a check-run; branch protection + native auto-merge land on green. |
| J2 self-maintaining lifecycle | `renovatebot/renovate` + scheduled `github/gh-aw` | `44.221.1`, `9bfa4c49b91f9d17f592c2cef9a14ac4c3dda2ec`; gh-aw pin above | Renovate keeps deps/pins current; a scheduled gh-aw agent researches skills/framework picks and opens evidence PRs. No upstream retires unused items. |
| J3 compounding learning | `vectorize-io/hindsight` + `EveryInc/compound-engineering-plugin` (+ trade lane from J5) | `v1.2.0`, `34a138684a899b6ec34175f7a2b633860466d289`; `compound-engineering-v3.36.0`, `7dc50943bbf959dbe6a93a175e41e5fff8395e00` | Hindsight captures sessions across Claude/Codex/dsh; `/ce-compound` distills into `docs/solutions/` that the next plan reads. |
| J4 research convergence | `wanshuiyin/Auto-claude-code-research-in-sleep` (ARIS-Code) | `v0.4.28`, `299cd76633f66657487f617c25f86e55ed89b50a` | Executor + independent reviewer, cross-family receipts, 83 plain-Markdown research skills, no hooks/DB/daemon. |
| J5 trading skills | `tradermonty/claude-trading-skills` | main HEAD `d8e71ce2f0b069eb5b6fca352857c168c35e6c46` (no release/tag) | Strategy design/review, backtest validation, pre-trade discipline, drawdown/position limits, trade memory — all native `SKILL.md` packages. |
| J6 options + Jev | `typesafe-ai/skills` + `tradermonty/claude-trading-skills` | `v0.6.2`, `302eea662c54bca6730873fe245bec1d69ebc23d`; tradermonty pin above | Official Jev skill for typed judgments; `options-strategy-advisor` for structure/Greeks/P&L design. |

The hard gaps are stated per job, not papered over: no OSS project lands a PR on checks alone; no project retires unused skills; no project rewrites skills/rules/handbook automatically; ARIS is not a plugin at its tag and does not support dsh at its tag; no Nautilus-native Agent Skills exist; no TypeSafe options skill exists.

---

## J1 — PR automation

**Job, verbatim:** “what triggers on a PR, runs the cross-family review, reports it and lands the PR on checks alone.”

**Pick:** `github/gh-aw` `v1.2.0` (`18928ba35b7e374d394be6406c7213ed3f0d9454`, MIT), composed with **GitHub native auto-merge + branch protection**. gh-aw is the trigger/review/report/check layer; GitHub is the lander. This is a stated composition, not a hidden extra tool.

**Why this one.** gh-aw is a compiler for Markdown-defined agentic workflows. It supports `on: pull_request`, a self-hosted `runs-on`, built-in Claude and Codex engines, and scoped `safe-outputs`. Two workflows — one `engine: claude`, one `engine: codex` — review the same PR independently, submit a consolidated review (`submit-pull-request-review`) and create a check-run (`create-check-run`). Branch protection requires those two check names; native auto-merge merges when both are green. That is the whole loop, with no custom server, no hosted bot and no webhook service.

**Install path (read at `v1.2.0`).**

```bash
gh extension install github/gh-aw --pin v1.2.0
```

`gh extension install --help` documents `--pin` as a tag for a binary extension and a commit for a script extension. gh-aw ships release binaries, so the tag is the install pin; the immutable commit is `18928ba35b7e374d394be6406c7213ed3f0d9454`. The upstream install line itself is unpinned (`README.md:42`, `gh extension install github/gh-aw`).

Workflow shape (frontmatter only; the body is the review prompt):

```yaml
on: pull_request
runs-on: self-hosted          # docs/src/content/docs/reference/self-hosted-runners.md:8
engine: claude                # second file: engine: codex
safe-outputs:
  submit-pull-request-review:
    max: 1
    allowed-events: [COMMENT, REQUEST_CHANGES]
  create-check-run:
    name: review-claude       # review-codex in the second file
```

Branch protection requires `review-claude` and `review-codex`; enable “Allow auto-merge” and “Automatically delete head branches”. A failing check-run blocks the merge; a green pair lets GitHub's auto-merge land it without a human click.

**Proof command (one line).**

```bash
gh aw compile .github/workflows/review-claude.md && gh aw --help >/dev/null && echo ok
```

**Evidence.** No public benchmark of gh-aw review quality was found; the evidence is the documented safe-output contract and the engine/runner behavior above, not a score. Stars (5.5k) are adoption, not quality. The `create-check-run` contract is explicit about the conclusion enum (`success`, `failure`, `neutral`, `cancelled`, `skipped`, `timed_out`, `action_required`), the check name and the PR target (`safe-outputs.md:1179–1216`); the review output is a real consolidated PR review with `APPROVE`/`REQUEST_CHANGES`/`COMMENT` (`safe-outputs.md:1119–1150`).

**Parts not used, and why.**

- `merge-pull-request` safe output — experimental, and it **always refuses merges to the repository default branch** (`safe-outputs-pull-requests.md:259,287`). It cannot be the lander.
- Copilot, Gemini and Pi engines — Copilot pulls in a hosted-agent dependency; Gemini/Pi add nothing to the two-family requirement. Claude + Codex is the smallest cross-family pair.
- The DeepSeek Harness engine sample — explicitly an **unsupported** sample that pins dsh `v0.2.0-rc.2`, uses headless stdin and CLI-proxy tools rather than native MCP, rejects per-command bash restrictions, and carries no compatibility commitment (`third-party-agent.md:56`). I did not wire dsh into the gate; doing so would be relying on an unsupported path.
- The gh-aw `create-pull-request` output — not needed for J1; it is used in J2.

**Runner-up:** `alibaba/open-code-review` `v1.13.6` (`891df1b63f380845d882a289a67a6e36c331120c`, Apache-2.0). It is the strongest reviewer on evidence: AACR-Bench (50 repos, 200 real PRs, 10 languages, 1,505 ground-truth issues, 80+ senior engineers), with higher precision/F1 than Claude Code at the same model and about one-ninth the tokens, and a deliberate recall trade-off (`README.md:59`, `:114`, `:191`, `:206`). It is CLI-first (`ocr review --format json`), has CI docs for GitHub Actions, and plugins for Claude Code/Codex.

**Flip evidence.** OCR is review-only: its CI doc tells you to parse the JSON and post comments yourself (`https://open-codereview.ai/docs/cicd`, GitHub Actions section), it has no `--fail-on`/exit gate, and its action docs say an over-budget review still exits 0 (`action.yml:110–111`). It has no trigger, no cross-family check-run pair and no lander. Adopting it would mean writing the exact glue the job asks a project to own. If review precision is later shown to dominate everything else, OCR becomes the reviewer inside the gh-aw workflow; the orchestration stays gh-aw.

**Cannot do / none exists.**

- **Cannot do:** no upstream reviewed here both runs the review and lands on checks alone. gh-aw is forbidden from merging to the default branch; GitHub's auto-merge is the only compliant lander and it is a platform feature, not an OSS repo. I looked at gh-aw, open-code-review, pr-agent, claude-code-action, codex-action and OpenHands automation.
- **Cannot do:** dsh cannot be a supported reviewer engine at this pin; the only upstream dsh path is the unsupported sample above.
- **Cannot do:** there is no deterministic review gate. The check-run conclusion is the reviewing agent's verdict; branch protection enforces the verdict, not an independent oracle. Every reviewer candidate shares this property.
- **None exists:** an OSS “trigger + cross-family review + report + land on checks alone” project. The lander is GitHub native auto-merge, not a repo.

---

## J2 — Self-maintaining lifecycle

**Job, verbatim:** “scheduled upkeep that keeps dependencies, skills and framework picks current, opens PRs with evidence, and retires what is no longer used.”

**Pick:** composition — `renovatebot/renovate` `44.221.1` (`9bfa4c49b91f9d17f592c2cef9a14ac4c3dda2ec`, AGPL-3.0) for dependency and pin updates, plus a scheduled `github/gh-aw` workflow (pin above) for skills/framework-pick research and evidence PRs.

**Install path (Renovate, read at `44.221.1`).** Self-hosted is the documented mode: the OSS CLI is the npm package `renovate`, runnable with `npx` or in any Node environment; Docker images are `renovate/renovate` and `ghcr.io/renovatebot/renovate` (`docs/usage/getting-started/running.md:26–37`). A self-hoster provides infra, global config and the schedule (`:11`), and a cron-like capability is required (`:147`).

```bash
npx renovate@44.221.1 --version
# runner form:
docker run --rm -e RENOVATE_TOKEN \
  -v "$PWD/renovate-config.js:/usr/src/app/config.js" \
  renovate/renovate:44.221.1
```

`renovate-config.js` pins `rangeStrategy: "pin"`, a weekly schedule, and custom regex managers for the skill/framework pins that are not package-manager ecosystems. Renovate's GitHub token is used for changelogs (`running.md:249`); the token value is never printed here.

The scheduled gh-aw workflow uses the documented `schedule:` trigger (`ghaw-triggers.md:79–101`) and the `create-pull-request` safe output (`safe-outputs-pull-requests.md:12–147`). Its prompt compares each pinned pick against upstream releases/tags, writes the evidence (URL, tag, full SHA, release date) into the PR body, and changes one pin per PR.

**Proof command (one line).**

```bash
npx renovate@44.221.1 --version && gh aw compile .github/workflows/maintenance.md && echo ok
```

**Evidence.** Renovate's documented behavior (dependency dashboard, changelog/release-note PRs, regex managers) is the evidence; I found no public benchmark and do not claim one. Renovate is AGPL-3.0 (`license:1`), which is a fact the owner must accept for a self-hosted internal tool. The gh-aw scheduled workflow has no quality benchmark; its evidence is the documented trigger and PR output.

**Parts not used, and why.**

- Renovate hosted app / Mend — cloud service, excluded by the fixed context.
- Renovate's `-full` image — preinstalls toolchains; the default image plus the runner's Docker is enough and smaller.
- gh-aw's `merge-pull-request` — same default-branch refusal as J1; Renovate PRs are merged by the same native auto-merge path after checks.
- Dependabot — native and zero-infra, but it only covers package ecosystems, cannot research a new framework pick, cannot write an evidence narrative, and has no retirement concept.

**Runner-up:** GitHub Dependabot. **Flip evidence:** if the requirement were only “bump package versions with zero infrastructure”, Dependabot wins on footprint. J2 also requires skills/framework picks and evidence PRs, which Dependabot does not do; Renovate's custom managers at least keep pinned skill refs current.

**Cannot do / none exists.**

- **None exists:** an upstream that **retires what is no longer used**. I looked at Renovate's docs (no usage/retirement manager; it updates declared dependencies only), Dependabot's docs (same), gh-aw's safe outputs (create/update/close PR, no usage analysis) and OpenHands automation (cloud scheduler). Retirement remains a reviewed human/agent decision; no pick is claimed for it.
- **Cannot do:** Renovate cannot discover a *new* SOTA framework pick; the scheduled gh-aw agent can research one, but its output is model judgment, not a benchmark. The PR review remains the evidence gate.
- **Cannot do:** Renovate is AGPL-3.0; if the owner's licence policy forbids AGPL even for self-hosted internal use, this pick must be replaced (Dependabot is the fallback, with the gaps above).

---

## J3 — Compounding learning

**Job, verbatim:** “capturing lessons from sessions, reviews and trades across runtimes, and feeding them back into skills, rules and the handbook so that each run improves the next.”

**Pick:** composition — `vectorize-io/hindsight` `v1.2.0` (`34a138684a899b6ec34175f7a2b633860466d289`, MIT) for capture, `EveryInc/compound-engineering-plugin` `compound-engineering-v3.36.0` (`7dc50943bbf959dbe6a93a175e41e5fff8395e00`, MIT) for distillation, and the J5 trade lane (`trader-memory-core` + `signal-postmortem`) for trade lessons.

**Install path (read at the pins).**

```bash
# capture; explicit target, local daemon, no cloud
npx @vectorize-io/hindsight-coding-agents install dsh --server daemon
npx @vectorize-io/hindsight-coding-agents install claude-code --server daemon
npx @vectorize-io/hindsight-coding-agents install codex --server daemon

# distillation
claude plugin marketplace add EveryInc/compound-engineering-plugin
claude plugin install compound-engineering
```

Hindsight's installer takes an explicit target and a bare `install` changes nothing; `uninstall all` removes exactly what install added; `update` refreshes the runtime without rewiring (`README.md:255–259`; coding-agents docs, install section). The dsh route is a native Cordis plugin row in `$DSH_HOME/cordis.patch.yml`, with native tools and **no MCP**; one dsh process serves several repos, so the bank is resolved per session workspace (coding-agents docs, DeepSeek Harness section). Claude Code and Codex each get three hooks plus MCP/companion skill; that is the footprint cost on those two hosts.

Compound installs on Claude Code (`README.md:28–29`) and Codex (`README.md:83–89`); `/ce-compound` writes the learning into `docs/solutions/`, and the next `/ce-brainstorm` and `/ce-plan` read it (`README.md:137–139`). `docs_root` relocates those directories (`README.md:147`). The package has no production hooks — only test fixtures under `tests/fixtures/*hooks` — so it adds no hook friction.

**Proof command (one line).**

```bash
npx @vectorize-io/hindsight-coding-agents stats && claude plugin list | grep -q compound-engineering && echo ok
```

**How each run improves the next.** Hindsight ingests a repo's git history and conversations automatically and injects the project bank at session start (coding-agents docs, intro). Compound turns the session's lesson into a durable `docs/solutions/` entry that the next plan reads; Compound Packs can pin prescriptive rule folders by git ref and cite the rule file back. The trade lane writes a local YAML journal (`trader-memory-core`) and reviews each signal (`signal-postmortem`), with a monthly performance-review workflow (`README.md:48–49`).

**Evidence.** Hindsight reports AMB `sdebench`: 61 real repository tasks, three runs each, with and without memory; every run solves 60–61/61 either way, so the claim is cost/correction reduction, not accuracy. The chart reports corrections/task Claude Code 0.85→0.36, Codex 1.34→0.47, opencode 1.20→0.80, and cost/task Claude $0.445→$0.338, Codex $0.577→$0.276 (coding-agents docs, “Does it work?”). The docs name the harnesses but **not the model or effort**; the chart values were read from the page, not from a raw result file. Compound has no public benchmark; its evidence is the documented artifact flow, not a score.

**Parts not used, and why.**

- Hindsight Cloud — cloud, excluded. The local daemon/self-hosted server is the mode used.
- Hindsight's Claude/Codex hooks — kept only if capture on those hosts is wanted; the dsh route alone is hook-free. To keep the hooks off, install only `dsh`; to capture Claude/Codex, accept the three lifecycle hooks per host (`SessionStart`, `UserPromptSubmit`, `Stop`). Their blocking behavior was not separately verified; they are still hooks.
- Compound's `/lfg` — it pushes/opens a PR and watches CI with bounded repair, but “does not merge unless you grant that” (`README.md:173`); the merge authority stays with J1.
- Compound's 14 host manifests — only Claude Code and Codex are used; the rest are dead weight here.
- The other memory candidates — see runner-up.

**Runner-up:** `thedotmack/claude-mem` `v15.10.0` (Apache-2.0). It has an explicit DeepSeek Harness install (`npx claude-mem install --ide dsh --dsh-profile tui`), automatic capture, a local SQLite/Chroma store and a compression worker. **Flip evidence:** claude-mem is the smaller one-install capture path, but it is hook/worker-centric, its observer can fall back to a hosted service, and it has no `docs/solutions`-style distillation loop. If the owner values “one install, automatic capture” over the compounding artifact, claude-mem wins capture; compound still has to be added for distillation.

**Cannot do / none exists.**

- **Cannot do:** no upstream here automatically **rewrites skills, rules or the handbook**. Compound writes `docs/solutions/`; the promotion of a lesson into a skill/rule is a reviewed edit. I looked at Hindsight, claude-mem, OpenViking, compound, ECC, superpowers, hermes-agent and claude-octopus.
- **Cannot do:** compound is not documented on dsh; the dsh lane captures into Hindsight, but distillation runs on Claude Code/Codex.
- **Cannot do:** Hindsight's benchmark does not name model/effort; its numbers are not a like-for-like eval of this harness.
- **None exists:** a single cross-runtime capture-and-rewrite system. This is a stated three-part composition, with the rewrite step left as a reviewed action.

---

## J4 — Research convergence method

**Job, verbatim:** “the multi-source, multi-model research practice itself, as an adopted skill or framework.”

**Pick:** `wanshuiyin/Auto-claude-code-research-in-sleep` (ARIS-Code) `v0.4.28` (`299cd76633f66657487f617c25f86e55ed89b50a`, MIT).

**Why this one.** ARIS is the closest encoded version of the practice: an executor produces, an **independent reviewer** critiques via `LlmReview`, and the loop repeats; cross-family reviews produce receipts, same-family reviews are marked provisional (`README.md:119–120`). It is “methodology, not a platform”: the skill layer is plain Markdown, with no DB, Docker or daemon, and 83 bundled research skills (`README.md:123`). That is the cleanest fit with the owner's “no endless hooks / no unneeded friction” rule.

**Install path (read at `v0.4.28`).** The documented install at this tag is the ARIS-Code release binary, not a plugin:

```bash
curl -fsSL https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/releases/download/v0.4.28/aris-code-linux-x64.tar.gz | tar xz
sudo mv aris /usr/local/bin/aris
aris          # first-run setup wizard: executor + reviewer provider/key
```

The README lists macOS arm64/x64, Linux x64 and Windows assets and the same `mv` step (`README.md:127–160`). It also documents `~/.claude/skills/` as a compatible layer (`README.md:248`), so the Markdown skills can be read by Claude-style hosts.

**Proof command (one line).**

```bash
aris --help >/dev/null && echo ok
```

(This is the documented binary; `--help` was not executed in this leg.)

**Parts not used, and why.**

- The 70+ ML/paper skills (literature survey, paper writing, figure generation, formal proof) — J4 needs the convergence/review loop, not the paper pipeline. The reviewer, research-wiki, citation-audit, kill-argument and proof-orchestrator skills are the relevant subset.
- ARIS-Code as the daily driver for all work — it is a fourth CLI. It is used for convergence runs only; Claude Code/Codex/dsh remain the work runtimes.
- The `dsh-aris` branch — older than the tag (`e08fd4c83305e31bd87291645137c9a59ad61aeb`, 2026-09-16) and not part of the release; using it would be an unpinned branch, so it is excluded.
- The plugin note — the README says ARIS became a Claude Code plugin on 2026-09-16 (`README.md:263`), but the `v0.4.28` tree has **no** `.claude-plugin`, `.codex-plugin` or marketplace manifest; those exist on `main`. The tag's documented install is the binary. I did not use an unpinned `main` plugin path.

**Runner-up:** `nyldn/claude-octopus` `v11.17.1` (`448dd5e563d345e5784af031946e8731cda9fc35`, MIT). It is a native Claude Code/Codex plugin with 12 providers, `/octo:council` (3/5/7 personas, 75% consensus, quorum + critical veto) and `/octo:research` with attributed multi-provider output (`README.md:3`, `:67`, `:430`; install `:116`). **Flip evidence:** if the requirement is “native in-host invocation with no second binary”, octopus wins. But it carries ~30 hook scripts, a research skill with a HARD-GATE and a blocking `AskUserQuestion`, and no dsh/native DeepSeek provider (`README.md:192–196`); that is exactly the friction the owner rejects. ARIS stays the pick.

**Evidence.** ARIS claims a paper and an HF #1; I did not verify the paper's harness/model/effort, so that claim is **UNVERIFIED** for quality. The documented mechanism (executor + independent reviewer, cross-family receipts, same-family provisional) is the evidence used here. Octopus's plugin behavior is documented but has no public review-quality benchmark.

**Cannot do / none exists.**

- **Cannot do:** ARIS at `v0.4.28` is not a Claude/Codex plugin and has no dsh integration at the tag; dsh is only on an older branch. A separate `aris` binary is required.
- **Cannot do:** no exact blind-leg / registered-criteria / claim-ledger protocol. ARIS gives executor/reviewer and receipts, not this specific convergence format; the method still has to be composed from its skills.
- **None exists:** an upstream skill that encodes this exact multi-source, blind-leg, criteria-first, ledgered convergence practice. I looked at ARIS, claude-octopus, OpenResearch, gpt-researcher, deer-flow, AI-Research-SKILLs, academic-research-skills and both `autoresearch` projects.

---

## J5 — Trading skills

**Job, verbatim:** “strategy, backtest validation and broker-safety skills as natively invoked Agent Skills.”

**Pick:** `tradermonty/claude-trading-skills` at main HEAD `d8e71ce2f0b069eb5b6fca352857c168c35e6c46` (2026-11-02, MIT). There is **no GitHub release and no tag** (API 404; no tags visible), so the commit is the pin.

**Why this one.** It is the only public set I found that packages all three requested behaviors as native `SKILL.md` skills, with no runtime, no DB and no hooks:

- strategy lane — `edge-strategy-designer`, `edge-strategy-reviewer`, `trade-hypothesis-ideator`, `strategy-pivot-designer`: turn an edge concept into draft strategies, review them for overfitting/sample-size/execution realism with PASS/REVISE/REJECT, generate falsifiable hypotheses, and propose structural pivots when tuning stalls (`skills/edge-strategy-designer/SKILL.md:3`; `skills/edge-strategy-reviewer/SKILL.md:3–6`; `skills/trade-hypothesis-ideator/SKILL.md:3–5`; `skills/strategy-pivot-designer/SKILL.md:3`).
- `backtest-expert` — a validation methodology: hypothesis, zero-discretion rules, robustness, bias and slippage checks; it takes user-provided metrics and has no external data dependency (`skills/backtest-expert/SKILL.md:31`).
- `pre-trade-discipline-gate` — an **offline** checklist that “does not place orders, cancel orders, call a broker API, or fetch market data”; it journals the decision (`skills/pre-trade-discipline-gate/SKILL.md:12`).
- `drawdown-circuit-breaker`, `position-sizer`, `trader-memory-core`, `signal-postmortem` — risk limits and a local YAML trade journal (`skills/trader-memory-core/SKILL.md:317–333`).
- `options-strategy-advisor` — reused in J6.

**Install path (read at HEAD).** The README documents copying `skills/<name>/` into `~/.claude/skills/` (personal) or `.claude/skills/` (project) (`README.md:117–123`). The repo's skills index is canonical (`skills-index.yaml`; categories at `README.md:157–160`).

```bash
git clone https://github.com/tradermonty/claude-trading-skills.git
git -C claude-trading-skills checkout d8e71ce2f0b069eb5b6fca352857c168c35e6c46
mkdir -p .claude/skills
cp -r claude-trading-skills/skills/{backtest-expert,edge-strategy-designer,edge-strategy-reviewer,trade-hypothesis-ideator,strategy-pivot-designer,pre-trade-discipline-gate,drawdown-circuit-breaker,position-sizer,trader-memory-core,signal-postmortem} .claude/skills/
```

**Proof command (one line).**

```bash
gh api 'repos/tradermonty/claude-trading-skills/contents/skills/backtest-expert/SKILL.md?ref=d8e71ce2f0b069eb5b6fca352857c168c35e6c46' --jq .name
```

**Evidence.** No public backtest-quality eval; the evidence is the documented methodology and the safety behavior (the gate never calls a broker). That is appropriate for a skill that is deliberately not an execution engine. Stars (3.6k) are adoption, not quality.

**Parts not used, and why.**

- The 60+ other skills (screening, macro, earnings and the remaining edge-pipeline wrappers) — not needed for the three requested behaviors.
- `manifoldbt-backtester` — beta and requires the separate ManifoldBT Rust engine; not needed to validate a Nautilus backtest.
- Alpaca/FMP integrations — the options skill's FMP lookup is optional (`skills/options-strategy-advisor/SKILL.md:30–32`); no broker credentials are used. Broker keys never enter the sandbox, consistent with the fixed context.
- Execution — deliberately absent. The skills produce decisions/journals, not orders.

**Runner-up:** `nautechsystems/nautilus_trader` `v1.231.0` (`27a8e54e7ac3c57d6cbf8891f0283dfbaee97317`, LGPL-3.0) as the engine/examples source, or `HKUDS/Vibe-Trading` `v0.1.19` as a full local trading platform. **Flip evidence:** Nautilus is the right engine but has **no** `SKILL.md`/`.claude`/`.agents` skill files at the tag or on `develop`; it cannot satisfy “natively invoked Agent Skills” without writing new skills (which the brief forbids). Vibe-Trading has native options/backtest machinery but is a platform with 19 broker connectors and broker keys in its own environment; it conflicts with the broker-keys rule. Neither beats tradermonty for the stated job.

**Cannot do / none exists.**

- **Cannot do:** none of these skills is Nautilus-specific. `backtest-expert` validates a backtest's *method*, not Nautilus strategy code; the Nautilus strategy/backtest code remains upstream examples, not a skill.
- **Cannot do:** no broker execution, by design. This is a feature for the owner's rule, not a gap to fill.
- **Cannot do:** the options skill is educational and simulates without real-time data by default; it is not a live options desk.
- **None exists:** Nautilus-native Agent Skills. I looked at the `nautilus_trader` tree at `v1.231.0` and `develop`, Vibe-Trading, TradingAgents, Lean and tradermonty.

---

## J6 — Options + TypeSafe Jev

**Job, verbatim:** “options strategy design, and TypeSafe Jev judgments, as natively invoked Agent Skills.”

**Pick:** composition — `typesafe-ai/skills` `v0.6.2` (`302eea662c54bca6730873fe245bec1d69ebc23d`, MIT) for Jev, plus `tradermonty/claude-trading-skills` at the J5 pin for `options-strategy-advisor`.

**Why this one.** The TypeSafe repo is the official skill for Jev, “the first public System One model”: it answers typed `Choice`/`Noul`/`Score`/`Box` questions about supplied state with calibrated probabilities, and the skill's doctrine is that Jev makes judgments while code makes decisions (`skills/typesafe-ai/SKILL.md:15–19`). The options skill is a native `SKILL.md` that designs and simulates structures — covered calls, protective puts, spreads, iron condors, earnings plays — with Black-Scholes, Greeks and P&L (`skills/options-strategy-advisor/SKILL.md:3`), using simulation rather than live data (`skills/options-strategy-advisor/SKILL.md:10`), with optional FMP enrichment (`skills/options-strategy-advisor/SKILL.md:30–32`). Together: the options skill proposes and simulates structures; Jev judges regime/fit as a typed probability; code applies the threshold.

**Install path (read at the pins).**

```bash
claude plugin marketplace add typesafe-ai/skills
claude plugin install typesafe@typesafe-ai
# non-Claude hosts:
npx skills add typesafe-ai/skills --skill typesafe-ai
```

(`README.md:14–21`; one skill, `typesafe-ai`, MIT at `README.md:42`.) Then copy `options-strategy-advisor` from the J5 pin into `.claude/skills/` (same copy pattern as J5).

**Proof command (one line).**

```bash
claude plugin list | grep -q typesafe && test -f .claude/skills/options-strategy-advisor/SKILL.md && echo ok
```

**Parts not used, and why.**

- The TypeSafe Python/JS SDKs, the `system-one-adapter-python` LLM-backed adapter and the n8n node — not needed for a skill; direct API calls stay server-side.
- The 24 cookbooks — useful examples, but no options cookbook; the `function_calling/trader.py` cookbook is a trading-shaped example (`jev-1.12`, `TypeSafeClient`, cache) and is not a strategy skill.
- `jev-trader` — a third-party live bot on Kuru (MON-USDC) that takes `PRIVATE_KEY` and makes one decision per block. It is evidence that Jev can drive a bot, not a skill; it violates the broker-keys rule and is excluded.
- Jev as the decision-maker — the skill explicitly warns not to ask Jev to make decisions; code must decide (`SKILL.md` guidance). The design keeps the threshold in code.

**Runner-up:** `jev-trader` (third-party) for a worked end-to-end bot. **Flip evidence:** if the goal were a live on-chain bot, it is the shortest path; it is not a native skill, it holds a private key, and it is single-venue. It loses on fit and safety.

**Evidence.** No public eval of the TypeSafe skill; the evidence is the official skill's documented contract and the typed-question semantics. The options skill is educational, with no performance claim. The `typesafe-public-examples` repo (MIT, HEAD `262a1f1362a3764028051056c272388027a5a06e`, 2026-11-03) has 24 cookbooks; none is an options strategy. That absence is stated below, not hidden.

**Cannot do / none exists.**

- **None exists:** an official TypeSafe **options** skill or cookbook. I looked at `typesafe-ai/skills` (one skill), `typesafe-ai/typesafe-public-examples` (24 cookbooks, no options entry) and the third-party `jev-trader` (a bot, not a skill). The options half is therefore the tradermonty skill, a stated composition.
- **Cannot do:** the TypeSafe skill needs a TypeSafe API key, kept server-side; no key is placed in the repo or the agent sandbox. Jev is a hosted API, so “no cloud” is satisfied only in the sense that the *harness* is local; the judgment call itself is a remote API by design. If the owner requires zero remote calls, Jev cannot be used at all.
- **Cannot do:** no dsh-native packaging for the TypeSafe skill; it is a Claude plugin/`npx skills` package. dsh can read Markdown skills only if pointed at them, which is not an upstream-documented path here.

---

## Claim ledger

Every row is a load-bearing claim. “API” means the GitHub REST response for that repo/tag/commit, read 2026-11-05; it has no file line. “Tree” means the git tree listing at the pinned ref, read 2026-11-05. Web docs have sections rather than line numbers; that is marked.

| # | Claim | Pinned source (path:line) | Read |
|---|---|---|---|
| 1 | gh-aw v1.2.0 is commit `18928ba…d9454` | GitHub API `repos/github/gh-aw/git/ref/tags/v1.2.0` → commit | 2026-11-05 |
| 2 | gh-aw is MIT | `LICENSE:1` | 2026-11-05 |
| 3 | gh-aw install is `gh extension install github/gh-aw` | `README.md:42` | 2026-11-05 |
| 4 | Built-in engines include Copilot/Claude/Codex/Gemini/Pi | `README.md:20` | 2026-11-05 |
| 5 | Self-hosted runners must be Linux with Docker; `runs-on` selects them | `docs/src/content/docs/reference/self-hosted-runners.md:8–12` | 2026-11-05 |
| 6 | gh-aw's merge output always refuses default-branch merges | `docs/src/content/docs/reference/safe-outputs-pull-requests.md:259,287` | 2026-11-05 |
| 7 | `create-check-run` exists, with the named conclusion enum and PR target | `docs/src/content/docs/reference/safe-outputs.md:181,1179–1216` | 2026-11-05 |
| 8 | `submit-pull-request-review` submits APPROVE/REQUEST_CHANGES/COMMENT with `allowed-events` | `docs/src/content/docs/reference/safe-outputs.md:1119–1150` | 2026-11-05 |
| 9 | `create-pull-request` exists with protected-files/base-branch policy | `docs/src/content/docs/reference/safe-outputs-pull-requests.md:12–147` | 2026-11-05 |
| 10 | gh-aw schedules support `daily` and cron with timezone | `docs/src/content/docs/reference/triggers.md:79–101` | 2026-11-05 |
| 11 | dsh engine is an unsupported sample, pins dsh 0.2.0-rc.2, CLI-proxy not native MCP | `docs/src/content/docs/reference/third-party-agent.md:56` | 2026-11-05 |
| 12 | GitHub native auto-merge lands when required checks pass | GitHub Docs, “Automatically merging a pull request” (`https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request`) and “About protected branches → Require status checks before merging” (sections; no line) | 2026-11-05 |
| 13 | open-code-review v1.13.6 commit is `891df1b…120c` | `git ls-remote` tag dereference | 2026-11-05 |
| 14 | OCR installs from npm and is Apache-2.0 | `README.md:114`, `:206` | 2026-11-05 |
| 15 | OCR CI docs tell the user to parse JSON and post comments | `https://open-codereview.ai/docs/cicd` (GitHub Actions section; web doc, no line) | 2026-11-05 |
| 16 | OCR has no fail-on exit gate; over-budget review exits 0 | `action.yml:110–111`; CLI reference flag list has no `--fail-on` | 2026-11-05 |
| 17 | Renovate 44.221.1 is commit `9bfa4c4…da2ec` | GitHub API `repos/renovatebot/renovate/git/ref/tags/44.221.1` | 2026-11-05 |
| 18 | Renovate is AGPL-3.0 | `license:1` (lowercase filename) | 2026-11-05 |
| 19 | Renovate self-host is npm `renovate` or Docker `renovate/renovate` | `docs/usage/getting-started/running.md:26–37` | 2026-11-05 |
| 20 | Renovate requires an external cron-like schedule | `docs/usage/getting-started/running.md:147` | 2026-11-05 |
| 21 | Renovate uses a GitHub token for changelogs | `docs/usage/getting-started/running.md:249` | 2026-11-05 |
| 22 | compound-engineering v3.36.0 is commit `7dc5094…95e00` | GitHub API tag ref | 2026-11-05 |
| 23 | compound plugin is MIT, name `compound-engineering`, version 3.36.0 | `.claude-plugin/plugin.json` (license/name/version fields) | 2026-11-05 |
| 24 | compound installs on Claude and Codex with the documented marketplace commands | `README.md:28–29`, `:83–89` | 2026-11-05 |
| 25 | `/ce-compound` writes `docs/solutions/`; next plan reads it | `README.md:137–139` | 2026-11-05 |
| 26 | compound package has no production hooks | Tree at tag; hooks only under `tests/fixtures/` | 2026-11-05 |
| 27 | ARIS v0.4.28 is commit `299cd76…9b50a` | GitHub API tag ref | 2026-11-05 |
| 28 | ARIS is MIT | `LICENSE:1` | 2026-11-05 |
| 29 | ARIS install at tag is the release binary + `mv` | `README.md:127–160` | 2026-11-05 |
| 30 | ARIS bundles 83 skills | `README.md:123` | 2026-11-05 |
| 31 | ARIS executor + independent reviewer via LlmReview | `README.md:119–120` | 2026-11-05 |
| 32 | ARIS tag has no plugin manifest; `main` does | Tree at `v0.4.28`; README plugin note `:263` | 2026-11-05 |
| 33 | ARIS dsh branch is `e08fd4c…1aeb`, 2026-09-16, older than tag | `git ls-remote` branch | 2026-11-05 |
| 34 | octopus v11.17.1 is commit `448dd5e…9fc35` | GitHub API tag ref | 2026-11-05 |
| 35 | octopus install is `claude plugin install octo@nyldn-plugins` | `README.md:116` | 2026-11-05 |
| 36 | octopus `core` profile keeps optional context hooks off; safety/lifecycle remain | `README.md:192–196` | 2026-11-05 |
| 37 | Hindsight v1.2.0 is commit `34a1386…6d289` | GitHub API tag ref | 2026-11-05 |
| 38 | Hindsight is MIT | `README.md:436` | 2026-11-05 |
| 39 | Hindsight installer is `npx @vectorize-io/hindsight-coding-agents install …` | `README.md:255–259` | 2026-11-05 |
| 40 | Hindsight supports 25+ providers incl local Ollama/LM Studio/llama.cpp | `README.md:82` | 2026-11-05 |
| 41 | Hindsight supports dsh natively via a Cordis plugin row, no MCP | `hindsight-docs/docs-integrations/coding-agents.md`, “DeepSeek Harness” section (web doc; no line) | 2026-11-05 |
| 42 | Hindsight AMB sdebench: 61 tasks ×3 runs, 60–61/61 either way; correction/cost chart | `hindsight-docs/docs-integrations/coding-agents.md`, “Does it work?” section (chart values, no line) | 2026-11-05 |
| 43 | tradermonty main HEAD is `d8e71ce…e6c46`; no release/tag | GitHub API commits/refs; releases 404 | 2026-11-05 |
| 44 | tradermonty is MIT | `README.md:25` | 2026-11-05 |
| 45 | tradermonty install is copying `skills/<name>/` | `README.md:117–123` | 2026-11-05 |
| 46 | `pre-trade-discipline-gate` is offline, never places orders/calls broker | `skills/pre-trade-discipline-gate/SKILL.md:12` | 2026-11-05 |
| 47 | `backtest-expert` takes user metrics, no external data deps | `skills/backtest-expert/SKILL.md:31` | 2026-11-05 |
| 48 | `trader-memory-core` uses a local YAML journal | `skills/trader-memory-core/SKILL.md:317–333` | 2026-11-05 |
| 49 | `options-strategy-advisor` covers Black-Scholes/Greeks/structures/P&L | `skills/options-strategy-advisor/SKILL.md:3` | 2026-11-05 |
| 50 | options skill simulates without real-time data by default | `skills/options-strategy-advisor/SKILL.md:10` | 2026-11-05 |
| 51 | options skill's FMP lookup is optional | `skills/options-strategy-advisor/SKILL.md:30–32` | 2026-11-05 |
| 52 | TypeSafe skills v0.6.2 is commit `302eea6…ebc23d` | GitHub API tag ref | 2026-11-05 |
| 53 | TypeSafe skills is MIT | `README.md:42` | 2026-11-05 |
| 54 | TypeSafe install is marketplace plugin or `npx skills add` | `README.md:14–21` | 2026-11-05 |
| 55 | Jev is a System One model answering Choice/Noul/Score/Box with calibrated probabilities | `skills/typesafe-ai/SKILL.md:15–19` | 2026-11-05 |
| 56 | Jev skill's null case uses a companion Noul; thresholds 0.7/0.3 | `skills/typesafe-ai/SKILL.md:148–151`, `:202–208` | 2026-11-05 |
| 57 | TypeSafe has one skill and no options cookbook | `typesafe-ai/skills` tree; `typesafe-public-examples` cookbook listing (24 entries) | 2026-11-05 |
| 58 | NautilusTrader v1.231.0 is commit `27a8e54…97317` | GitHub API tag ref | 2026-11-05 |
| 59 | Nautilus has no SKILL.md/.claude/.agents at the tag or develop | Tree listings at both refs | 2026-11-05 |
| 60 | Nautilus is LGPL-3.0 | GitHub API license field / `LICENSE` | 2026-11-05 |
| 61 | tradermonty has native strategy design/review skills | `skills/edge-strategy-designer/SKILL.md:3`, `skills/edge-strategy-reviewer/SKILL.md:3–6` | 2026-11-05 |
| 62 | tradermonty has hypothesis and pivot skills | `skills/trade-hypothesis-ideator/SKILL.md:3–5`, `skills/strategy-pivot-designer/SKILL.md:3` | 2026-11-05 |

**Negative findings (where I looked).** No retirement manager: Renovate docs, Dependabot docs, gh-aw safe outputs. No Nautilus-native skills: `nautilus_trader` tree at `v1.231.0` and `develop`. No TypeSafe options skill/cookbook: `typesafe-ai/skills`, `typesafe-public-examples`. No OSS PR lander: gh-aw merge docs, OCR docs, pr-agent docs, OpenHands automation. No automatic skill/rule rewrite: Hindsight, claude-mem, OpenViking, compound, ECC, superpowers, octopus. No exact blind-leg convergence skill: ARIS, octopus, OpenResearch, gpt-researcher, deer-flow, AI-Research-SKILLs, academic-research-skills, autoresearch.

**Unverified or not executed.** I did not install or run any pick; every “proof command” is a one-line check derived from the pinned docs, not an executed result. The Hindsight benchmark is a self-reported page, and its model/effort are not named; the chart values are page reads, not raw data. ARIS's paper/HF claim was not verified for harness/model/effort. GitHub's auto-merge/protected-branch behavior is platform documentation, not a repo pin. No environment-variable values were read or printed.
