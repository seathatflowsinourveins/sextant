# GPT blind research leg: foundations for a local trading agent harness

- **Harness:** Codex App native surface; local executable reports **codex-cli 0.166.0**.
- **Model:** GPT family; system identity says GPT-6. Exact served model variant/revision: **UNVERIFIED**.
- **Effort:** highest supported effort requested. This surface exposes no active-session model/effort receipt; the configured effort and its maximum-level attestation are **UNVERIFIED**. An installed CLI version or a requested model is not proof of the model/effort serving this session. This leg must not be counted as session-attested maximum-effort evidence without that receipt.
- **Read date:** 2026-11-05, America/New_York. GitHub timestamps below are UTC, so some show November 6.
- **Independence:** used the supplied brief and stars snapshot, public primary sources, and runtime help/version output. Read no other research leg, synthesis, decision ruling for this choice, seathatflowsinourveins repository, or other material in the forbidden local trees.

## Decision

Choose the following composition. These are independent recommendations, not a claim that cross-family convergence has already happened.

| Job | Pick | Coverage boundary |
|---|---|---|
| J1 PR automation | GitHub Agentic Workflows, native Claude/Codex engines, GitHub required checks and native auto-merge | Documented components cover the path; the composed policy has not been deployed or tested here. |
| J2 Lifecycle | Self-hosted Renovate OSS plus gh-aw's upstream workflow updater | Version upkeep and update PRs; semantic skill/framework replacement and retirement remain incomplete. |
| J3 Learning | Compound Engineering's ce-compound plus selected Claude Trading Skills journal/postmortem components | Repository lessons and trade feedback; no verified universal dsh/transcript/fill ingestion bridge. |
| J4 Research convergence | Compound Engineering's ce-bakeoff and its independent judging/verification references | Fresh independent contexts and source reconciliation; require the named families explicitly rather than accepting its same-family fallback. |
| J5 Trading skills | Selected tradermonty skills plus the fixed NautilusTrader's own examples | Strategy research and validation guidance; advisory pre-trade checks do not enforce broker isolation. |
| J6 Options / Jev | tradermonty options-strategy-advisor plus TypeSafe's official skill and published cookbooks | Local options analysis; fresh Jev judgments require an external API. |

The ranking follows the registered order: fit, recent maintenance and documented installation, evidence, footprint, then licence as a recorded fact. Stars did not decide quality. I verified no comparative evaluation across these finalists that names the complete harness, model **and effort**; these choices rest on upstream behaviour, implementation and tests inspected, not a claimed benchmark win.

“No cloud service” needs a precise boundary: GitHub itself is fixed in the brief, and the named models normally require inference services. The proposed execution and learning stores stay local; GitHub remains the control plane and model/API dependencies are disclosed. If the requirement means no external inference whatsoever, J1's API-authenticated engines and fresh Jev inference do not meet it.

## Owner-stars screen

Screened the supplied owner-stars.tsv for each job. Line numbers refer to that supplied snapshot, not a fresh authenticated stars export. Its push dates are discovery signals; I checked actual public commits/releases for the finalists.

| Job | Relevant starred candidates screened |
|---|---|
| J1 | anthropics/claude-code-action (37), alibaba/open-code-review (65), OpenHands/OpenHands (310), openai/codex-plugin-cc (295), deepseek-ai/deepseek-harness (34). |
| J2 | dependabot/dependabot-core (143), OpenHands/OpenHands (310), uditgoenka/autoresearch (157), EveryInc/compound-engineering-plugin (303), NousResearch/hermes-agent (373). |
| J3 | Compound Engineering (303), ECC (387), claude-mem (342), Hindsight (367), OpenViking (129), Hermes (373), Storybloq (54), agentic-stack (250). |
| J4 | ARIS (368), academic-research-skills (317), scientific-agent-skills (268), AI-Research-SKILLs (290), GPT Researcher (291), DeerFlow (292), OpenResearch (64), autoresearch (364/157), Superpowers (380). |
| J5 | tradermonty (44), NautilusTrader (285), TradingAgents (354), Vibe-Trading (209), Lean (51), machine-learning-for-trading (50). |
| J6 | tradermonty (44), jarrodwatts/jev-trader (43), anthropics/financial-services (38), Vibe-Trading (209). TypeSafe's official organisation was also searched directly. |

The snapshot was the brief's designated stars source. I did not query the owner's account or inspect any private repository.

## J1 — PR automation

**Pick:** GitHub Agentic Workflows plus native GitHub auto-merge.

- github/gh-aw @ v1.0.1; commit 0627fdbe4beb5f3b71aa569f8d97150b87f2111a — stable v1.0.1 release published 2026-10-27; MIT.
- cli/cli @ v2.103.3; commit 63837fb778d6a39f02be0ce76ff89f2bc8d74bdc — release published 2026-10-26; MIT ([licence][L08]).
- GitHub feature documentation pinned at github/docs commit 17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493; the SaaS feature itself has no installable tag.

upstream checked: github/gh-aw@v1.0.1:README.md, .github/aw/pr-reviewer.md, reference/self-hosted-runners.md, engine references, create_check_run.cjs and its tests; cli/cli@v2.103.3:pkg/cmd/pr/merge/merge.go.

**Why this composition:** gh-aw already compiles repository Markdown into Actions, has native Claude/Codex engine adapters and validated publishing operations. It adds a documented semantic-result check API, which is a better fit than assuming a successfully completed review process means an acceptable PR. [Compiler and permissions][G01], [reviewer pattern][G02], [check-run contract][G07].

Use two separately configured review workflows, one Claude and one Codex, on opened, synchronize, reopened and ready_for_review. With the fixed Claude/GPT/DeepSeek author roster, this supplies at least one different-family review without inventing an author-routing service. Each workflow publishes its own uniquely named result check and review evidence. Requiring those checks, plus ordinary CI, allows GitHub to land on checks without a mandatory human approval. This is a **proposed configuration of upstream primitives**, not an existing turnkey cross-family template. [Triggers][G02], [typed results][G07], [native auto-merge][G11].

Keep the check target override **omitted** for a pull_request-triggered review. The pinned handler then uses the triggering event's PR head SHA. The explicitly configured “triggering” target instead fetches the latest head when publishing; that does not establish that the latest head was reviewed. The event-head path has a corresponding upstream test. [Target semantics][G07], [implementation][G08], [test][G09].

Private personal repositories on GitHub Pro support native auto-merge. The documented CLI entry point can enable it with an expected PR head, for example gh pr merge PR --auto --squash --match-head-commit SHA. This command is an installation/deployment reference and was **not executed**. [Plan availability][G12], [CLI flags][G13].

**Install path and proof:** upstream's README installs the gh extension. Its installed CLI supports pinning binary extensions by release tag:

~~~sh
gh extension install github/gh-aw --pin v1.0.1
~~~

Then use the documented workflow initialization/compilation path and engine configuration. Proof command, after configuration:

~~~sh
gh aw compile --require-self-hosted-runners
~~~

Set all generated jobs to the local runner, including slim/framework, output and maintenance jobs; setting only the main agent's runs-on is insufficient. gh-aw's supported self-hosted target is **Linux with Docker**. Native macOS/Windows runner execution is unsupported; deployment inside a Linux VM/container on those devices is **UNVERIFIED** here. [Runner contract][G05], [other generated jobs][G06].

The Claude adapter uses an API key or WIF, not subscription OAuth. The Codex adapter uses API keys; its pinned default CLI is 0.164.0 and supports engine.version overrides. Do not mistake that default for the locally observed 0.166.0 or a session model receipt. [Claude authentication][G04], [Codex authentication/version][G03].

**Parts not used:** Copilot cloud agent/session outputs, hosted review services, arbitrary direct GitHub writes from the reviewing agent, and gh-aw's experimental merge-pull-request operation. The latter explicitly refuses the default branch, so native GitHub auto-merge supplies that part of the composition. [Merge limitation][G14]. Broker credentials are outside the runner's agent inputs by requirement; this research did not verify a deployed credential boundary.

For PRs opened by automation, use the documented self-hosted GitHub App identity for the publisher. Do not assume ordinary GITHUB_TOKEN-created PRs start unattended CI: current GitHub docs describe general event suppression and an approval-required PR-event exception. [Current event behaviour][G21], [Renovate's native App path][R06].

**Footprint:** workflow Markdown plus generated lock YAML, gh-aw configuration/action pins, and job-lifetime Docker/gateway processes on the existing runner. No desktop Stop/UserPromptSubmit continuation hook is required. Exact generated file count, idle resource usage and review latency are **UNVERIFIED**.

**Runner-up:** the official action pair:

- openai/codex-action @ v1.13; commit bdf19a4a223ec2549a3e2274a0cf61556bc07675 — Apache-2.0.
- anthropics/claude-code-action @ v1.0.268; commit c0949c50a78c1ec8ce2647db36629b870e715d0c — MIT.

Their examples already trigger reviews and publish feedback; Codex also supports a result schema. What was not established is a documented, complete result-to-required-check policy for this exact composition. Also, Codex action's default drop-sudo changes can survive on a reused self-hosted runner; its pre-created unprivileged-user path is documented. [Codex example][G15], [schema inputs][G16], [runner behaviour][G17], [Claude example][G18]. **Flip event:** these upstreams publish a complete same-head semantic-check/auto-merge example meeting the local-runner requirements with less framework footprint.

**Cannot do:** validate review truth, attest model-family independence merely from requested engine names, or guarantee that a model never emits an inappropriate success/neutral/skipped result. The check schema deliberately accepts those conclusions; successful workflow execution is not proof of defect-free code. [Conclusion tests][G10]. The composed workflow, missing-result behaviour and merge race handling are **UNVERIFIED end to end**.

none exists: a turnkey policy for the exact Claude/Codex/dsh author roster, source-foundation review requirements and checks-only landing was not found in the inspected gh-aw, official-action, OpenHands PR-review, PR-Agent or OCR entry points. Use their documented composition surfaces; this report designs no replacement reviewer, verdict parser or dispatcher.

## J2 — Self-maintaining lifecycle

**Pick:** self-hosted Renovate OSS for declared dependencies and source pins, plus gh-aw's own workflow-updater practice.

- renovatebot/renovate @ 44.221.1; commit 9bfa4c49b91f9d17f592c2cef9a14ac4c3dda2ec — release published 2026-11-05; AGPL-3.0-only.
- github/gh-aw @ v1.0.1; commit 0627fdbe4beb5f3b71aa569f8d97150b87f2111a — stable release published 2026-10-27; MIT.

upstream checked: renovatebot/renovate@44.221.1:docs/usage/getting-started/running.md, examples/self-hosting.md, git-submodules and custom/regex managers; github/gh-aw@v1.0.1:.github/workflows/daily-workflow-updater.md.

Renovate OSS already supports local CLI/container/CI execution. Its documented managers can update declared packages, actions, containers and Git-submodule references; its configurable regex manager covers otherwise undeclared version strings. Those are adopted update mechanisms, not a reason to build a dependency scanner. It still needs an external scheduler. [Distributions][R01], [installation][R02], [submodules][R04], [custom manager][R05], [scheduling][R03].

For gh-aw itself, the upstream scheduled updater runs gh aw update, updates action locks/workflow sources and proposes a PR. Adapt its documented engine/runner configuration to the local Claude/Codex setup. The upstream template expressly permits the workflow-file edits it needs; do not bypass protected-file handling in a separate script. [Updater behaviour][R07], [upstream file policy][R08].

**Install path:**

~~~sh
npm install -g renovate@44.221.1
~~~

This is the upstream npm installation path with an exact release selected. A documented Docker distribution is also available. One-line proof:

~~~sh
renovate --version
~~~

Expected version: 44.221.1. The public registry returned that version and integrity sha512-bAb10OMxQbpViR7hF79b/sQ4s9mfWQbK1nXXRsu6HXMargteXA5+Di5AiH4zdAhuX7uzYgHXOiv+FmNqS5bGJw==. No package was installed here; package provenance attestations, a deployment lockfile and container image digest remain **UNVERIFIED**.

**Footprint and parts not used:** one updater configuration and scheduled runner job, transient dependency workspaces/cache, and update PRs. No agent continuation hook or continuously running Renovate service is needed for the CLI path. Exclude Mend's hosted service, the closed-source self-hosted product, duplicate Dependabot PR generation, automatic adoption of major framework changes, and updates to opaque user plugin caches. A skill must be represented by a tracked upstream reference before Renovate can update that reference. [Distribution boundaries][R01], [declared-reference manager][R04].

**Runner-up:** dependabot/dependabot-core @ v0.403.0; commit 9ac98a409855e01424e00469efb87377a173334d, v0.403.0 published 2026-11-03; MIT. Its README documents an official CLI and self-hosted CI use. [Upstream CLI path][A01]. **Flip event:** its official self-hosted product covers this repository's skill/framework Git-reference updates and evidence PR needs more directly than Renovate, or those needs disappear. This is a coverage comparison, not an asserted quality ranking.

**Cannot do:** decide whether a new framework is architecturally better, prove a strategy's edge, infer that an unused skill should be deleted, or keep untracked native plugin installations pinned. “Latest version” and “best foundation” are different judgments.

none exists: a complete evidence-driven lifecycle that refreshes picks, revises skills/rules and retires unused framework components under this exact three-runtime/GitHub-Issues-only scope was not found in the inspected Renovate, Dependabot, gh-aw updater, Compound Engineering refresh, Hermes, ECC or autoresearch entry points. CE refresh explicitly excludes edits to skills, runbooks and instruction files. [Refresh boundary][C04]. Do not present dependency updates as a completed semantic lifecycle, and do not build a replacement in this research leg.

## J3 — Compounding learning

**Pick:** a repository learning workflow plus a separate upstream trade journal.

- EveryInc/compound-engineering-plugin @ compound-engineering-v3.36.0; commit 7dc50943bbf959dbe6a93a175e41e5fff8395e00 — release published 2026-11-05; MIT.
- tradermonty/claude-trading-skills @ none; commit d8e71ce2f0b069eb5b6fca352857c168c35e6c46 — no tag/releases returned by the queried endpoints; pinned default-branch commit dated 2026-11-02; MIT.

upstream checked: EveryInc/compound-engineering-plugin@compound-engineering-v3.36.0:skills/ce-compound and its form/session-history/refresh references; tradermonty/claude-trading-skills@d8e71ce2f0b069eb5b6fca352857c168c35e6c46:trader-memory-core, signal-postmortem and monthly-performance-review example.

CE's capture workflow has an unusually useful restraint: retain a verified lesson only when the final code/tests/existing docs do not already carry it. It can update an existing learning, use an existing check or coding standard, or write a repository solution record. Its explicit non-interactive mode asks no questions. That matches repo portability and avoids turning every session into more permanent prompt context. [Capture contract][C02], [form selection][C03].

Use the trading kit's thesis lifecycle and postmortem records for trade-side facts. Signal Postmortem already produces outcome classifications and feedback proposals. Its example monthly workflow links decisions to evidence IDs and explicitly leaves rule activation unperformed. This is a usable learning input, not permission to tune or trade autonomously. [Thesis store][C06], [feedback][C07], [evidence-linked teaching workflow][C08].

**Install path:** CE documents native Claude and Codex marketplace installs. To preserve the researched revision, use a checkout at the SHA above as the Claude marketplace source; the installed Claude help explicitly accepts local paths. For Codex, the locally verified native command supports:

~~~sh
codex plugin marketplace add EveryInc/compound-engineering-plugin --ref 7dc50943bbf959dbe6a93a175e41e5fff8395e00
codex plugin add compound-engineering@compound-engineering-plugin
~~~

Native invocation is /ce-compound in Claude, $ce-compound in Codex; include mode:non-interactive for an unattended capture. Install the selected trading skill folders by their documented source-folder path, preserving scripts and references. [CE install/invocation][C01], [trading install][T01].

One-line CE installation proof:

~~~sh
codex plugin list --marketplace compound-engineering-plugin --json
~~~

One-line journal CLI proof from a pinned trading-kit checkout:

~~~sh
uv run python skills/trader-memory-core/scripts/trader_memory_cli.py --help
~~~

These are proposed smoke commands, not claims that capture/retrieval has been exercised here.

**Footprint:** a CE plugin catalog, on-demand instructions/scripts and repository learning files; trade state/postmortem files from the trading kit. No additional vector database or memory daemon. The full native plugin still registers its broader skill catalog even if only these workflows are used: exact injected context/tokens are **UNVERIFIED**. Its inspected native manifests declare no lifecycle hook entry. [Native manifest][H01].

**Parts not used:** auto-promoting learned trade parameters, treating generated summaries as fills, adding a second issue tracker, and the trading kit's local skill-generation backlog pipeline. GitHub Issues remains the work tracker. CE's documented transcript discovery covers Claude/Codex and other named formats, but does not list dsh; native skill readability does not establish transcript-ingestion support. [Discovery scope][C05].

**Runner-up:** vectorize-io/hindsight @ v1.2.0; commit 34a138684a899b6ec34175f7a2b633860466d289, v1.2.0 published 2026-11-03; MIT reported by repository metadata. It has documented self-hosted Docker/embedded deployment and retain/recall/reflect operations. Its external memory store is a stronger retrieval surface when file-based learning is no longer sufficient, but brings another store/service and integration surface. Do not use its optional Claude subscription provider under this brief's restriction. [Local deployment and API][H07]. **Flip event:** repeated, evidenced misses of existing lessons make retrieval a real requirement, and upstream provides the needed native connectors and portable export; no locally invented benchmark is a prerequisite.

**Cannot do:** automatically ingest every runtime's session, reconcile broker fills with lessons, prove a universal append-only ledger, or consistently turn every lesson into a handbook/rule change. The two selected stores have different schemas.

none exists: an upstream end-to-end bridge from dsh transcripts and Nautilus fill events into this exact CE/trade-journal/handbook composition was not found in the inspected CE history adapter, trade skills, Hindsight, Claude-mem or OpenViking entry points. Do not invent that bridge or claim continuous learning is already wired.

## J4 — Research convergence method

**Pick:** EveryInc/compound-engineering-plugin @ compound-engineering-v3.36.0; commit 7dc50943bbf959dbe6a93a175e41e5fff8395e00, specifically ce-bakeoff with its candidate, judging and verification references; MIT; release published 2026-11-05.

upstream checked: EveryInc/compound-engineering-plugin@compound-engineering-v3.36.0:skills/ce-bakeoff/SKILL.md and references/candidates.md, judging.md, verification.md.

This is an adopted method rather than a newly named panel protocol. The upstream skill frames common requirements and comparison criteria, develops independent approach artifacts, obtains a fresh independent assessment, reconciles disagreements and verifies the final selection against inspected evidence. Architecture/approach briefs are explicitly within its scope. [Method][B01], [evidence floor][B05].

Its candidates must have fresh contexts, receive neither the coordinator's preferred outcome nor siblings' outputs, and may use authorized native model CLIs. A reused context is not another independent leg. The judge receives completed neutral-labelled artifacts without the coordinator's ranking; reconciliation follows source evidence rather than vote count. [Candidate contract][B02], [judge contract][B04].

**Necessary configuration:** explicitly require Claude, GPT and DeepSeek families, each at its verified maximum supported effort, in the common brief. Upstream normally treats model diversity as a preference and allows a disclosed same-family fallback; that fallback does **not** meet this research requirement. Its prohibition on silently substituting an explicitly required model provides the needed boundary. Missing identity/completion receipts remain unverified, including this leg's own effort receipt. [Model restrictions][B02], [completion receipts][B03].

**Install path:** reuse J3's pinned CE installation; do not add another orchestrator. Native invocation is /ce-bakeoff in Claude or $ce-bakeoff in Codex. One-line installation proof:

~~~sh
codex plugin list --marketplace compound-engineering-plugin --json
~~~

**Footprint:** no additional installed framework beyond J3; fresh worker contexts, private run scratch and a final decision artifact. It does not require Stop/UserPromptSubmit continuation hooks. Do not import a second persistent task database; GitHub Issues remains the tracker.

**Parts not used:** executable implementation bake-offs for a research-only choice, same-family fallbacks counted as cross-family evidence, unbounded repair panels, or a home-grown orchestration wrapper. The native CLI route is documented, but compatibility with the particular installed dsh version and its model/effort receipts is **UNVERIFIED** here.

**Runner-up:** wanshuiyin/Auto-claude-code-research-in-sleep @ v0.4.28; commit 299cd76633f66657487f617c25f86e55ed89b50a, v0.4.28 published 2026-09-28; MIT reported by repository metadata. At this pinned release its actual README documents **ARIS-Code, a standalone CLI**, with an executor/reviewer iteration loop and binary installation. Treating this release as just a Markdown skill collection would be inaccurate. Sequential reviewer critique is also not the same guarantee as blind candidate research. [Pinned release behaviour/install][B06]. **Flip event:** ARIS ships a documented native-skill-only blind multi-family mode with the required provenance, without adding a runtime or a continuation loop.

**Cannot do:** guarantee factual correctness from consensus, supply model attestations that the host does not expose, enforce isolation merely by assigning different paths, or replace source inspection with judge approval. Its cooperative read boundaries are explicit in the candidate reference. [Boundaries][B02], [verification][B05].

none exists: a turnkey, fully attested protocol covering this exact three-runtime roster, highest-effort receipts, two-family synthesis reconciliation and an automatic pinned claim ledger was not verified in the inspected CE, ARIS, Academic Research Skills, GPT Researcher or DeerFlow sources. CE supplies the closest method; do not claim every local research requirement is an already implemented feature.

## J5 — Trading skills

**Pick:** selected Claude Trading Skills, with NautilusTrader's own implementation references.

- tradermonty/claude-trading-skills @ none; commit d8e71ce2f0b069eb5b6fca352857c168c35e6c46 — no published tag returned; commit dated 2026-11-02; MIT.
- nautechsystems/nautilus_trader @ v1.231.0; commit 27a8e54e7ac3c57d6cbf8891f0283dfbaee97317 — latest stable release returned by the release API, published 2026-08-02; LGPL v3. This pins the **reference examples**, not an instruction to migrate an existing engine.

The Nautilus stable tag is older than 60 days, but the repository is actively maintained: the inspected default-branch commit e5f28c0660cc6a523e50f385d1c429ace450e4ba is dated 2026-11-06T00:43:52Z. Recent prereleases also exist. Thus repository maintenance passes the registered test; recent changes being included in the stable reference is **not** claimed.

upstream checked: tradermonty/claude-trading-skills@d8e71ce2f0b069eb5b6fca352857c168c35e6c46:backtest-expert, edge-strategy-designer, pre-trade-discipline-gate; nautechsystems/nautilus_trader@v1.231.0:docs/getting_started/installation.md and examples/backtest/example_01_load_bars_from_custom_csv/.

Use backtest-expert for hypothesis definition, friction/stress tests and walk-forward review; it needs no API key. Use edge-strategy-designer for clearly labelled research drafts, with its preset assumptions visible. Use pre-trade-discipline-gate only for its explicit offline checklist. [Validation workflow][T02], [draft generator][T04], [offline boundary][T05].

Implementation must remain in Nautilus's paradigm. The inspected example builds BacktestEngine using engine Money and Decimal objects; its paired Strategy simply counts bars. It is a foundation/example, not an evidenced trading strategy. [Engine setup][T07], [demo scope][T08].

**Install path:** from the pinned trading-kit checkout, copy complete selected skill folders into project .claude/skills, as the maintainer documents. For Codex use .agents/skills and its native $backtest-expert invocation; dsh's upstream filesystem provider reads the same SKILL.md bundle format from .agents/skills and loads it through its native skill tool. This is file-format/discovery compatibility, not a certification of every helper script on every runtime. [Maintainer install][T01], [Codex discovery][N01], [dsh discovery][T09], [dsh invocation][T10].

For an engine install, upstream explicitly documents uv pip install nautilus_trader; selecting the referenced stable version gives:

~~~sh
uv pip install nautilus_trader==1.231.0
~~~

Use the existing project environment/lockfile when integrating, rather than installing into system Python. [Engine install][T06]. One-line skill-helper proof, run from the pinned kit checkout:

~~~sh
uv run python skills/backtest-expert/scripts/evaluate_backtest.py --help
~~~

**Footprint and parts not used:** selected instruction folders and their on-demand Python helpers; no research daemon or continuation hook. Exclude portfolio-manager/broker integrations, alternate backtest engines, and “DEPLOY” as a promotion authority. The evaluator's score/labels are upstream heuristics, not proof of a strategy's merit or authorization for a live order. [Evaluator limits][T03]. The five-year and other preset thresholds must not silently become universal policy.

**Runner-up:** TauricResearch/TradingAgents @ v0.7.1; commit c4544913a14ed3df5f1ed7b9e8483270ce20682a, v0.7.1 published 2026-10-27; Apache-2.0 reported by repository metadata. It supplies a separate LangGraph research runtime ([framework][A02]); no independently installable Nautilus strategy/validation/safety Agent Skills package was verified. **Flip event:** upstream releases that package with directly applicable point-in-time validation and the fixed engine integration, rather than requiring a second trading runtime.

**Cannot do:** enforce that broker keys never enter an agent sandbox, prevent another process placing an order, attest execution fidelity from user-supplied summary metrics, or establish trading profitability. No complete CPCV/PBO/deflated-Sharpe protocol was found in the inspected backtest-expert skill and methodology reference ([inspected methodology][T11]). Runtime isolation and broker access remain separate constraints.

none exists: a complete native Agent Skills package for Nautilus strategy design, the full required validation suite and enforced broker-key separation was not found in the inspected Nautilus examples, selected tradermonty skills, TradingAgents, Vibe-Trading, Lean, or the general security/scientific skill catalogs. The offline checklist is not that enforcement mechanism; do not design a new one here.

## J6 — Options and TypeSafe Jev skills

**Pick:** a stated composition of local options analysis and the publisher's own Jev integration skill.

- tradermonty/claude-trading-skills @ none; commit d8e71ce2f0b069eb5b6fca352857c168c35e6c46, options-strategy-advisor; MIT; commit dated 2026-11-02; no tag returned.
- typesafe-ai/skills @ v0.6.2; commit 302eea662c54bca6730873fe245bec1d69ebc23d, typesafe-ai; tag v0.6.2, commit dated 2026-10-23; MIT.
- typesafe-ai/typesafe-public-examples @ none; commit 262a1f1362a3764028051056c272388027a5a06e, cookbook implementation references; no tag asserted; commit dated 2026-11-03. Example code is MIT; third-party data retains separate notices.

upstream checked: tradermonty/claude-trading-skills@d8e71ce2f0b069eb5b6fca352857c168c35e6c46:skills/options-strategy-advisor; typesafe-ai/skills@v0.6.2:README.md and skills/typesafe-ai/SKILL.md; typesafe-ai/typesafe-public-examples@262a1f1362a3764028051056c272388027a5a06e:cookbooks/function_calling/dispatch.py and trader.py. Also read the publisher's live function-calling, citation-check and skill-suggestion cookbooks and current model documentation.

The options skill provides local theoretical pricing, Greeks and payoff simulation from manual inputs; its FMP data key is optional. Keep inputs explicit. It contains a 2025 rate example and expressly qualifies European pricing versus American early exercise, so do not carry that example rate or a simplified model into an executable trading decision. [Local capabilities][O01], [input/model caveats][O02], [stated limitations][O03].

TypeSafe's official skill assigns narrow judgments to Jev while application code retains decision logic. It directs the agent to current schemas/cookbooks and cautions against treating confidence as correctness. That is more suitable than inventing a “Jev trading agent.” [Official guidance][J02], [live documentation contract][J03], [uncertainty guidance][J04].

**Install path:** install options-strategy-advisor as the complete source folder using J5's path. TypeSafe documents:

~~~sh
claude plugin marketplace add typesafe-ai/skills
claude plugin install typesafe@typesafe-ai
~~~

For a frozen local source, point the documented local-marketplace facility at the checkout SHA above. Its official manual alternative copies the entire skills/typesafe-ai directory into the host's skill directory. Other-agent installation through npx skills add typesafe-ai/skills --skill typesafe-ai is also documented, but that unqualified remote command alone does not prove the researched SHA was installed. Choose one install method. [Publisher install][J01], [manual-install live page][J09].

Native invocation is /typesafe:typesafe-ai in the Claude plugin, $typesafe-ai in Codex, or dsh's native skill loader for a local bundle. [Publisher invocation][J01], [Codex][N01], [dsh][T10].

One-line options proof, from the pinned trading-kit checkout:

~~~sh
uv run python skills/options-strategy-advisor/scripts/black_scholes.py --help
~~~

One-line local Jev-skill presence proof:

~~~sh
test -f .agents/skills/typesafe-ai/SKILL.md
~~~

That checks installation presence; it does not prove a fresh model judgment.

**Parts not used:** the options skill's broker-facing workflows, a frozen historical interest-rate assumption, copied API keys or key command-line arguments, and the examples' historical cached model selector as today's model policy. The function-calling example uses mock bars; its cache can replay without a live key and leaves the model out of the cache key. That is not a locally deployed Jev model or evidence of a new answer from today's model. [Dispatcher scope][J05], [mock/cache implementation][J06].

**Footprint:** two skill bundles, on-demand numerical dependencies for options, and an HTTP client only if live Jev calls are enabled. No Stop/UserPromptSubmit continuation hook or additional agent service is required by these selected skills. Dataset licences are separate from the skill/code licence. [Example licensing][J07].

**Runner-up:** for options, HKUDS/Vibe-Trading @ v0.1.19; commit cb99dca528695ffe78429483a90399a89f61d614, v0.1.19 published 2026-11-05; MIT reported by repository metadata. Its Options Lab is documented adjacent functionality ([capability table][A03]), but adding its application/trading runtime does not meet the native-skill/fixed-engine preference. **Flip event:** upstream publishes an independently installable options Agent Skill with stronger exercise/assignment treatment and direct Nautilus compatibility. For Jev, retain the publisher's skill over third-party wrappers unless TypeSafe itself adopts an alternative or its official integration ceases to cover the needed API.

**Cannot do:** provide fresh offline Jev inference, make theoretical option values executable quotes, or provide validated Jev-based strategy edge. The current live model page names Jev 1.14.0 and an API endpoint; model access, request schemas and actual responses were not tested. [Current models][J08].

none exists: a documented self-hostable Jev distribution, weights or offline inference installation was not found in TypeSafe's public organisation listing, official skill, model documentation or public examples. Therefore fresh Jev judgments do **not** satisfy a literal zero-cloud-service requirement. An old response cache is not a substitute, and no replacement model is proposed.

## Footprint, hooks and alternative-screen findings

The selection reuses CE across J3/J4, gh-aw across J1/J2 and the trading kit across J3/J5/J6. This reduces distinct frameworks without pretending their full installed catalogs have zero context cost.

| Candidate | Finding and disposition |
|---|---|
| OpenHands OpenHands / SDK / extensions / automation | Public sources now separate Canvas, SDK execution, extension catalog and an automation service. They can support local execution, but add a control-center/service stack to an already fixed runtime roster. [Repository boundaries][A04]. The PR-review plugin's multi-model A/B list randomly selects **one** model per review; it is not concurrent cross-family review. Keep Laminar/cloud paths out. [A/B semantics][G19]. |
| PR-Agent | Local CLI/GitHub Action/Docker routes exist; useful review infrastructure, but the exact requested semantic checks-only landing policy was not verified. No hosted review bot selected. [Deployment paths][A05]. |
| Alibaba OCR | Maintained local review CLI/action with a published benchmark. [Benchmark description][A06]. Its budget cap can produce partial results and exit zero, so process success cannot stand for complete review coverage. I did not verify a complete model/effort disclosure for its benchmark comparison. [Budget semantics][G20]. |
| Superpowers / mattpocock / addyosmani / anthropics skills / Trail of Bits | Catalog-level screening only: no applicable complete broker-enforcement/lifecycle package was verified; those capabilities remain UNVERIFIED. No quality ranking is asserted. |
| ECC | Broad hooks/rules/instinct system adds more harness surface. [Scope][A07]. Its documented install can keep hooks off with ./install.sh --profile core --no-hooks --target claude (also --without baseline:hooks). This is an upstream installation choice, not a recommendation to disable guards in an existing deployment. [No-hook path][H03]. |
| oh-my-claudecode | Its Stop persistent-mode hook enforces continuation and its prompt hook routes keywords. Upstream documents DISABLE_OMC=1 for all hooks and OMC_SKIP_HOOKS for selected hooks. For this new composition, leave the hook bundle uninstalled; no current host setting was changed. [Continuation/off controls][H02]. |
| uditgoenka/autoresearch | Its metric-iteration workflow is not semantic framework convergence. [Upstream scope][A08]. UserPromptSubmit context injection can be kept off with AR_DISABLE_ITERATION_CONTEXT=1 and AR_DISABLE_DEV_RULES_REMINDER=1; its Stop notifier separately supports AR_DISABLE_STOP_NOTIFY=1. Those are documented controls; no security hook was disabled. [Prompt controls][H04], [Stop notifier][H05]. |
| claude-mem / OpenViking / Hindsight | Memory services/providers can be relevant later, but add storage/integration state beyond a repo learning workflow. Claude-mem has lifecycle hooks including prompt initialization; that alone is not evidence of a continuation loop. Keep its plugin uninstalled in this composition. [Hook manifest][H06]. Hindsight remains J3's runner-up. |
| Hermes | A maintained learning-capable harness ([upstream description][A09]), but replacing/adding a fourth runtime is a poorer fit to the fixed roster than adopting native skills. No claim that its internals are portable to dsh by copying a prompt. |
| Academic Research Skills / K-Dense / Orchestra | Academic/scientific workflows are adjacent, not native trading-engine safety. Academic Research Skills has a CC-BY-NC-4.0 licence, recorded as a fact. [Actual licence][L07]. Orchestra's default-branch commit is dated 2026-06-16 despite a later push timestamp, so it fails the registered 60-day maintenance test on the inspected history. |
| karpathy/autoresearch / codex-plugin-cc | Inspected default-branch commits are 2026-03-26 and 2026-07-08 respectively; neither meets the registered 60-day test. Their popularity does not cure that. |
| GPT Researcher / DeerFlow / OpenResearch | GPT Researcher and OpenResearch document local application paths ([server install][A12], [workspace][A11]); adding them duplicates runtime/workspace infrastructure. DeerFlow received metadata-level screening only. No complete blind maximum-effort provenance contract was verified for this exact roster. |
| Lean / TradingAgents / Vibe-Trading / anthropics financial-services / jev-trader | Relevant trading, research or finance applications, but a second engine, hosted-agent route or directly trading demo is not an independently installable broker-safe Nautilus Agent Skill. Anthropic's finance repo explicitly includes a managed-agent path ([scope][A10]). The starred jev-trader is not evidence of TypeSafe-supported trading edge or offline Jev. |

Licences of the selected foundations are MIT (gh-aw, CE, trading skills, TypeSafe skill), AGPL-3.0-only (Renovate) and LGPL v3 (Nautilus reference). This records the upstream facts, without turning licence labels into a quality ranking. [gh-aw][L01], [CE][L03], [trading][L04], [TypeSafe][L05], [Renovate][L02], [Nautilus][L06].

## Verification and remaining uncertainty

Executed read-only verification included:

- codex --version → codex-cli 0.166.0.
- gh API repository, tags, releases and commit queries → exact references/dates recorded above; raw GitHub source fetched at the full SHAs.
- gh api repos/EveryInc/compound-engineering-plugin/commits/compound-engineering-v3.36.0 → 7dc50943bbf959dbe6a93a175e41e5fff8395e00.
- gh api repos/nautechsystems/nautilus_trader/releases/latest → v1.231.0, prerelease false; the tag's commit query returned 27a8e54e7ac3c57d6cbf8891f0283dfbaee97317.
- npm view renovate@44.221.1 version dist.integrity --json → version and integrity recorded in J2.
- gh extension install --help → documented --pin; gh pr merge --help → --auto and --match-head-commit.
- codex plugin marketplace add --help → --ref and local-path source support; codex plugin list --help → --marketplace and --json.
- claude plugin marketplace add --help → local path/URL/repository sources.
- Public documentation fetched with uv run --no-project python using urllib; no candidate code was executed.

The repeated source-query forms were gh api repos/OWNER/REPO/commits?per_page=1, gh api repos/OWNER/REPO/tags?per_page=5, gh api repos/OWNER/REPO/releases?per_page=3, and raw.githubusercontent.com/OWNER/REPO/FULL_SHA/PATH. Metadata-only screens above must not be read as full implementation audits.

Not verified: active-session model/effort attestation; installed candidate behaviour; compiled cross-family workflows; actual required-check/auto-merge behaviour; all-device portability; live API authentication/inference; trading results; broker isolation; memory retrieval quality; or semantic lifecycle retirement. The source-link audit fetched 78 distinct pinned files and confirmed all 91 GitHub citation ranges exist; this checks HTTP availability and line bounds, not the proposed composition's behaviour. The proof commands are deliberately labelled future installation smokes. No PR, deployment, credential flow, trading node, order or memory-store write was performed.

## Claim ledger

Each GitHub source below is pinned by its complete commit in the link, with path and line. All were read 2026-11-05 America/New_York. Interpret selection/flip conditions as this leg's judgments; source links establish the component behaviour, not a measured result of the proposed composition.

| ID | Load-bearing claim | Pinned source path and line | Read date |
|---|---|---|---|
| G01 | gh-aw compiles Markdown workflows to Actions and separates agent reads from scoped output writes. | [github/gh-aw/README.md:16-53][G01] | 2026-11-05 |
| G02 | The upstream PR reviewer pattern documents automatic PR triggers and review outputs. | [github/gh-aw/.github/aw/pr-reviewer.md:5-31][G02] | 2026-11-05 |
| G03 | Codex engine supports API-key authentication, engine.version override; its default CLI pin is 0.164.0. | [github/gh-aw/docs/src/content/docs/reference/engines/codex.md:8-10][G03] | 2026-11-05 |
| G04 | Claude engine supports API keys/WIF and does not support subscription OAuth. | [github/gh-aw/docs/src/content/docs/reference/engines/claude.md:8-10][G04] | 2026-11-05 |
| G05 | Self-hosted gh-aw requires Linux and Docker; all generated jobs can be constrained to self-hosted execution. | [github/gh-aw/docs/src/content/docs/reference/self-hosted-runners.md:8-20][G05] | 2026-11-05 |
| G06 | Slim/framework/maintenance jobs also need their documented self-hosted runner settings. | [github/gh-aw/docs/src/content/docs/reference/self-hosted-runners.md:145-191][G06] | 2026-11-05 |
| G07 | create-check-run has a configured name, typed conclusions, and documented target/SHA behavior. | [github/gh-aw/docs/src/content/docs/reference/safe-outputs.md:1081-1129][G07] | 2026-11-05 |
| G08 | With no target override, the handler attaches the result to the triggering PR head and sends that SHA to checks.create. | [github/gh-aw/actions/setup/js/create_check_run.cjs:173-226][G08] | 2026-11-05 |
| G09 | Upstream tests cover PR-head SHA selection and invalid/missing conclusions; they also accept neutral/skipped. | [github/gh-aw/actions/setup/js/create_check_run.test.cjs:86-111][G09] | 2026-11-05 |
| G10 | The validation tests accept all seven conclusion values; a workflow's success alone is not a semantic review verdict. | [github/gh-aw/actions/setup/js/create_check_run.test.cjs:287-335][G10] | 2026-11-05 |
| G11 | GitHub native auto-merge waits for required reviews/checks, and must be enabled for the repository. | [github/docs/content/pull-requests/how-tos/merge-and-close-pull-requests/automatically-merging-a-pull-request.md:19-37][G11] | 2026-11-05 |
| G12 | Native auto-merge is available for a private repository on GitHub Pro. | [github/docs/data/reusables/gated-features/auto-merge.md:1][G12] | 2026-11-05 |
| G13 | GitHub CLI implements --auto, --squash and --match-head-commit. | [cli/cli/pkg/cmd/pr/merge/merge.go:174-184][G13] | 2026-11-05 |
| G14 | gh-aw's experimental merge-pull-request output refuses the repository default branch. | [github/gh-aw/docs/src/content/docs/reference/safe-outputs-pull-requests.md:260-269][G14] | 2026-11-05 |
| G15 | The official Codex action example runs review and posts the returned text as a comment. | [openai/codex-action/README.md:11-16][G15] | 2026-11-05 |
| G16 | Codex action supports structured output schemas, model and effort inputs. | [openai/codex-action/action.yml:54-69][G16] | 2026-11-05 |
| G17 | Codex action's default drop-sudo changes can persist on reused self-hosted runners; another supported mode uses a pre-created unprivileged account. | [openai/codex-action/README.md:168-181][G17] | 2026-11-05 |
| G18 | Claude Code Action's review example runs on PR events, uses an API key and publishes comments. | [anthropics/claude-code-action/examples/pr-review-comprehensive.yml:6-65][G18] | 2026-11-05 |
| G19 | OpenHands PR-review multi-model A/B mode randomly selects one model per review. | [OpenHands/extensions/plugins/pr-review/README.md:258-266][G19] | 2026-11-05 |
| G20 | OCR's token-budget exhaustion can publish partial results and exit zero. | [alibaba/open-code-review/action.yml:100-111][G20] | 2026-11-05 |
| G21 | GITHUB_TOKEN events are generally suppressed; the documented PR exception requires approval, while dispatch events are exceptions. | [github/docs/data/reusables/actions/actions-do-not-trigger-workflows.md:1-6][G21] | 2026-11-05 |
| R01 | Renovate provides OSS CLI, Docker and CI self-hosting distributions, distinct from hosted Mend services. | [renovatebot/renovate/docs/usage/getting-started/running.md:11-81][R01] | 2026-11-05 |
| R02 | Upstream documents npm and Docker installation paths. | [renovatebot/renovate/docs/usage/examples/self-hosting.md:12-49][R02] | 2026-11-05 |
| R03 | Self-hosted CLI/container runs need an external cron-like scheduler. | [renovatebot/renovate/docs/usage/getting-started/running.md:140-150][R03] | 2026-11-05 |
| R04 | Renovate can update Git submodule commit/version references. | [renovatebot/renovate/lib/modules/manager/git-submodules/readme.md:1-27][R04] | 2026-11-05 |
| R05 | Renovate's documented custom regex manager covers dependencies absent from built-in managers. | [renovatebot/renovate/lib/modules/manager/custom/regex/readme.md:1-43][R05] | 2026-11-05 |
| R06 | Self-hosted Renovate supports a GitHub App and installation-token authentication. | [renovatebot/renovate/lib/modules/platform/github/readme.md:68-103][R06] | 2026-11-05 |
| R07 | gh-aw's own scheduled updater invokes gh aw update and proposes action/workflow-source updates. | [github/gh-aw/.github/workflows/daily-workflow-updater.md:65-87][R07] | 2026-11-05 |
| R08 | The updater template explicitly permits its protected workflow-file edits. | [github/gh-aw/.github/workflows/daily-workflow-updater.md:34-43][R08] | 2026-11-05 |
| C01 | Compound Engineering has native Claude Code/Codex install paths and host-specific skill invocation. | [EveryInc/compound-engineering-plugin/README.md:23-114][C01] | 2026-11-05 |
| C02 | ce-compound captures only qualifying verified lessons, updates existing learnings, and has a non-interactive mode. | [EveryInc/compound-engineering-plugin/skills/ce-compound/SKILL.md:19-64][C02] | 2026-11-05 |
| C03 | The adopted learning workflow chooses existing checks, coding standards or a learning record rather than automatically adding duplicate prose. | [EveryInc/compound-engineering-plugin/skills/ce-compound/references/form.md:7-21][C03] | 2026-11-05 |
| C04 | Refresh audits solutions, classifies keep/update/consolidate/replace/delete, and must not edit skills, runbooks or instruction files. | [EveryInc/compound-engineering-plugin/skills/ce-compound/references/refresh/overview.md:20-42][C04] | 2026-11-05 |
| C05 | The documented session-history discovery lists supported transcript families, including Claude and Codex; dsh is not listed. | [EveryInc/compound-engineering-plugin/skills/ce-compound/references/session-history.md:36-52][C05] | 2026-11-05 |
| C06 | Trader Memory Core stores thesis lifecycle and postmortem information across conversations. | [tradermonty/claude-trading-skills/skills/trader-memory-core/SKILL.md:1-39][C06] | 2026-11-05 |
| C07 | Signal Postmortem generates outcome classifications and feedback/backlog proposals. | [tradermonty/claude-trading-skills/skills/signal-postmortem/SKILL.md:80-108][C07] | 2026-11-05 |
| C08 | The monthly teaching workflow links evidence IDs, stages rule decisions and does not activate broker rules. | [tradermonty/claude-trading-skills/examples/workflows/monthly-performance-review/README.md:13-41][C08] | 2026-11-05 |
| B01 | ce-bakeoff defines competing approach artifacts, common criteria, independent judgment and reconciliation. | [EveryInc/compound-engineering-plugin/skills/ce-bakeoff/SKILL.md:8-40][B01] | 2026-11-05 |
| B02 | Candidates use fresh contexts, may use native hosts or authorized CLIs, cannot read siblings, and must not silently violate explicit model restrictions. | [EveryInc/compound-engineering-plugin/skills/ce-bakeoff/references/candidates.md:3-17][B02] | 2026-11-05 |
| B03 | Only observed completion/identity receipts count; missing model receipts remain unverified. | [EveryInc/compound-engineering-plugin/skills/ce-bakeoff/references/candidates.md:35-37][B03] | 2026-11-05 |
| B04 | The judge receives completed neutral-labeled artifacts without the coordinator's ranking; disagreements are reconciled at source. | [EveryInc/compound-engineering-plugin/skills/ce-bakeoff/references/judging.md:3-17][B04] | 2026-11-05 |
| B05 | Decision-critical premises require inspected authoritative evidence; uncertainty cannot preserve a failed guarantee. | [EveryInc/compound-engineering-plugin/skills/ce-bakeoff/references/verification.md:7-15][B05] | 2026-11-05 |
| B06 | At the named ARIS release, upstream documents a standalone research CLI with an executor/reviewer loop. | [wanshuiyin/Auto-claude-code-research-in-sleep/README.md:115-150][B06] | 2026-11-05 |
| T01 | Trading Skills' documented local install copies complete selected skill folders; its shared environment supports Python 3.11-3.13. | [tradermonty/claude-trading-skills/README.md:121-130][T01] | 2026-11-05 |
| T02 | Backtest Expert requires no API key and documents stress testing, friction and walk-forward validation. | [tradermonty/claude-trading-skills/skills/backtest-expert/SKILL.md:27-99][T02] | 2026-11-05 |
| T03 | Its evaluator has heuristic promotion-like labels and explicit blocking conditions; those labels are not broker authorization. | [tradermonty/claude-trading-skills/skills/backtest-expert/SKILL.md:113-132][T03] | 2026-11-05 |
| T04 | Edge Strategy Designer produces draft YAML variants with preset risk/exit constraints. | [tradermonty/claude-trading-skills/skills/edge-strategy-designer/SKILL.md:10-38][T04] | 2026-11-05 |
| T05 | Pre-Trade Discipline Gate is explicitly offline and neither calls broker APIs nor places/cancels orders. | [tradermonty/claude-trading-skills/skills/pre-trade-discipline-gate/SKILL.md:8-12][T05] | 2026-11-05 |
| T06 | Nautilus upstream documents uv installation and the supported runtime/platform matrix. | [nautechsystems/nautilus_trader/docs/getting_started/installation.md:3-48][T06] | 2026-11-05 |
| T07 | Nautilus's CSV example constructs a BacktestEngine with engine Money/Decimal types and runs/disposes it. | [nautechsystems/nautilus_trader/examples/backtest/example_01_load_bars_from_custom_csv/run_example.py:17-55][T07] | 2026-11-05 |
| T08 | The paired Strategy example is a bar-counting demo, not evidence of a trading edge. | [nautechsystems/nautilus_trader/examples/backtest/example_01_load_bars_from_custom_csv/strategy.py:21-25][T08] | 2026-11-05 |
| T09 | DSH's filesystem provider accepts SKILL.md bundles, preserves symlink resource paths, and scans project .agents/skills. | [deepseek-ai/deepseek-harness/packages/skill/skill-filesystem/README.md:34-56][T09] | 2026-11-05 |
| T10 | DSH uses a native skill({name}) loading tool and a progressively loaded catalog. | [deepseek-ai/deepseek-harness/docs/subsystems/skills.md:227-237][T10] | 2026-11-05 |
| O01 | Options Strategy Advisor offers local Black-Scholes/Greeks/payoff analysis with manual inputs and an optional FMP key. | [tradermonty/claude-trading-skills/skills/options-strategy-advisor/SKILL.md:8-48][O01] | 2026-11-05 |
| O02 | The option skill contains a 2025 interest-rate example and explicitly qualifies American versus European pricing. | [tradermonty/claude-trading-skills/skills/options-strategy-advisor/SKILL.md:106-183][O02] | 2026-11-05 |
| O03 | The option skill separately documents model assumptions and American early-exercise limitations. | [tradermonty/claude-trading-skills/skills/options-strategy-advisor/SKILL.md:800-815][O03] | 2026-11-05 |
| J01 | TypeSafe provides an official locally installable Agent Skill and native Claude invocation. | [typesafe-ai/skills/README.md:7-35][J01] | 2026-11-05 |
| J02 | The official skill separates Jev judgments from deterministic decision logic in application code. | [typesafe-ai/skills/skills/typesafe-ai/SKILL.md:15-37][J02] | 2026-11-05 |
| J03 | The skill directs implementers to current docs and official cookbooks instead of remembered API syntax. | [typesafe-ai/skills/skills/typesafe-ai/SKILL.md:39-62][J03] | 2026-11-05 |
| J04 | The official skill cautions against treating confidence as correctness and calls for an explicit uncertainty outcome. | [typesafe-ai/skills/skills/typesafe-ai/SKILL.md:148-206][J04] | 2026-11-05 |
| J05 | The function-calling cookbook's pinned dispatcher works with closed-set signatures, not a broker-safe execution policy. | [typesafe-ai/typesafe-public-examples/cookbooks/function_calling/dispatch.py:1-12][J05] | 2026-11-05 |
| J06 | The cookbook uses mock bars and an older cached model selector; replay is not new local inference. | [typesafe-ai/typesafe-public-examples/cookbooks/function_calling/trader.py:1-60][J06] | 2026-11-05 |
| J07 | TypeSafe example code is MIT; third-party datasets retain their own notices. | [typesafe-ai/typesafe-public-examples/README.md:5-9][J07] | 2026-11-05 |
| H01 | The selected CE native manifest declares skills and no lifecycle hook entry. | [EveryInc/compound-engineering-plugin/.codex-plugin/plugin.json:1-45][H01] | 2026-11-05 |
| H02 | OMC documents Stop continuation, prompt-trigger injection, and all/specific-hook opt-outs. | [Yeachan-Heo/oh-my-claudecode/docs/HOOKS.md:43-104][H02] | 2026-11-05 |
| H03 | ECC documents a core install without hooks. | [affaan-m/ECC/README.md:449-459][H03] | 2026-11-05 |
| H04 | Udit Autoresearch documents opt-outs for prompt context injection. | [uditgoenka/autoresearch/guide/hooks.md:71-105][H04] | 2026-11-05 |
| H05 | Its Stop notification has a separate opt-out; that notifier is not proof of a continuation loop. | [uditgoenka/autoresearch/guide/hooks.md:136-156][H05] | 2026-11-05 |
| H06 | Claude-mem registers lifecycle hooks, including session initialization at prompt submission. | [thedotmack/claude-mem/plugin/hooks/hooks.json:17-75][H06] | 2026-11-05 |
| H07 | Hindsight supports local Docker/embedded deployment and retained/recall/reflect APIs; cloud and subscription routes are optional alternatives. | [vectorize-io/hindsight/README.md:64-143][H07] | 2026-11-05 |
| L01 | GitHub Agentic Workflows is MIT. | [github/gh-aw/LICENSE:1-12][L01] | 2026-11-05 |
| L02 | Renovate declares AGPL-3.0-only. | [renovatebot/renovate/package.json:138][L02] | 2026-11-05 |
| L03 | Compound Engineering is MIT. | [EveryInc/compound-engineering-plugin/LICENSE:1-12][L03] | 2026-11-05 |
| L04 | Claude Trading Skills is MIT. | [tradermonty/claude-trading-skills/LICENSE:1-12][L04] | 2026-11-05 |
| L05 | The TypeSafe skill is MIT. | [typesafe-ai/skills/LICENSE:1-12][L05] | 2026-11-05 |
| L06 | The referenced Nautilus release carries LGPL v3. | [nautechsystems/nautilus_trader/LICENSE:1-16][L06] | 2026-11-05 |
| L07 | Academic Research Skills' license is CC-BY-NC-4.0, not an assumed MIT license. | [Imbad0202/academic-research-skills/LICENSE:1-10][L07] | 2026-11-05 |
| N01 | Codex supports repository .agents/skills, symlinked folders and explicit dollar-prefixed skill invocation; official live documentation. **Live document content pinned by SHA-256 in the following table; no public Git commit verified.** | [OpenAI documentation/docs/build-skills.md:94-149][N01] | 2026-11-05 |
| A01 | Dependabot documents its maintained CLI and self-hosted CI use. | [dependabot/dependabot-core/README.md:42-62][A01] | 2026-11-05 |
| A02 | TradingAgents is built with LangGraph and supports multiple model providers. | [TauricResearch/TradingAgents/README.md:248-252][A02] | 2026-11-05 |
| A03 | Vibe-Trading documents Options Lab in its application capability table. | [HKUDS/Vibe-Trading/README.md:149-155][A03] | 2026-11-05 |
| A04 | OpenHands documents separate Canvas, Agent Server/SDK and automation repository boundaries. | [OpenHands/OpenHands/README.md:166-176][A04] | 2026-11-05 |
| A05 | PR-Agent documents GitHub Actions, local CLI and self-hosted deployment. | [The-PR-Agent/pr-agent/README.md:64-123][A05] | 2026-11-05 |
| A06 | OCR publishes its own code-review benchmark description; no complete effort-controlled comparison is claimed here. | [alibaba/open-code-review/README.md:53-69][A06] | 2026-11-05 |
| A07 | ECC describes hooks, memory and continuous learning as part of its broader installation. | [affaan-m/ECC/README.md:128-151][A07] | 2026-11-05 |
| A08 | Udit Autoresearch presents autonomous metric-driven iteration. | [uditgoenka/autoresearch/README.md:1-70][A08] | 2026-11-05 |
| A09 | Hermes describes a learning-capable harness and separate terminal backends. | [NousResearch/hermes-agent/README.md:20-33][A09] | 2026-11-05 |
| A10 | Anthropic's financial-services repository includes Cowork and managed-agent installation paths. | [anthropics/financial-services/README.md:1-13][A10] | 2026-11-05 |
| A11 | OpenResearch documents a local research workspace with experiment storage. | [alphaXiv/OpenResearch/README.md:68-98][A11] | 2026-11-05 |
| A12 | GPT Researcher documents local server installation and provider/search dependencies. | [assafelovic/gpt-researcher/README.md:95-140][A12] | 2026-11-05 |
| T11 | The backtest methodology covers walk-forward and common data biases; the scoped search found no CPCV/PBO/deflated-Sharpe protocol. | [tradermonty/claude-trading-skills/skills/backtest-expert/references/methodology.md:83-99][T11] | 2026-11-05 |
| L08 | GitHub CLI is MIT. | [cli/cli/LICENSE:1-12][L08] | 2026-11-05 |
| J08 | The live model page reports Jev 1.14.0 and the System One API endpoint; fresh self-hosted inference is not documented. **Content fingerprint below; immutable Git-source pin UNVERIFIED.** | [TypeSafe live documentation/models.md:7-19][J08] | 2026-11-05 |
| J09 | The publisher documents manual installation by copying the complete skill directory and choosing one install method. **Content fingerprint below; immutable Git-source pin UNVERIFIED.** | [TypeSafe live documentation/agent-skill.md:30-40][J09] | 2026-11-05 |

### Live-document content fingerprints

These publisher pages were read today and their returned UTF-8 content was hashed in memory. The hashes pin what was fetched; a public immutable Git revision for these pages is **UNVERIFIED**. Their live URLs may change. They are not replayed model evaluations.

| Source / Markdown lines | SHA-256 of fetched content | Read date |
|---|---|---|
| [cookbooks/function_calling.md](https://docs.typesafe.ai/cookbooks/function_calling.md) — 7-12, 49-84: typed function dispatch, mock data/setup and the historical example selector. | 181ab970c1dd70332952148705205fdc65d710588fd892fe9a597a1649579786 | 2026-11-05 |
| [cookbooks/citation_check.md](https://docs.typesafe.ai/cookbooks/citation_check.md) — 7-18, 53-65: source/citation checking recipe, with historical example-model results. | 952615ff6a20fc063e02a793818de2f91579f1c6838a989f9f111b3729752838 | 2026-11-05 |
| [cookbooks/skill_suggestion.md](https://docs.typesafe.ai/cookbooks/skill_suggestion.md) — 7-39: two-request skill suggestion recipe and the stated experiment harness/model; not a fresh result from this leg. | 5d96d3c5a19d8c47ffa2f13bfdb6fdcec3f02e4efa9d93ad286e2a82ce88149b | 2026-11-05 |
| [models.md](https://docs.typesafe.ai/models.md) — 7-19, 68-75: endpoint, currently documented model and aliases. | 09ff62cff4c56b2d4d1827541e2af06f1d15c21f0ef8879dd488e72a373b34ca | 2026-11-05 |
| [docs/build-skills.md](https://learn.chatgpt.com/docs/build-skills.md) — 94-103, 136-149: explicit invocation and repository/symlink discovery. | 95b5ef4d0581d9eeeee342ef4718e77ed7574fe9c61ae28e1c2bffa4c6bdb411 | 2026-11-05 |
| [agent-skill.md](https://docs.typesafe.ai/agent-skill.md) — 11-40: native plugin, other-agent and manual-copy installation. | 5858202f260f8d441e7c0ab99a97533828f3488add5cecd09d6fa8efbdd7b47a | 2026-11-05 |

### Immutable metadata and measured-command records

| Claim | Pinned metadata source / command and observed result | Read date |
|---|---|---|
| Orchestra's inspected default-branch commit is older than the registered 60-day window. | [Commit 773a52944ba4747a18bd4ae9ade53fff041adcbc](https://github.com/Orchestra-Research/AI-Research-SKILLs/commit/773a52944ba4747a18bd4ae9ade53fff041adcbc); gh api repos/Orchestra-Research/AI-Research-SKILLs/commits?per_page=1 returned commit.committer.date = 2026-06-16T01:36:40Z. | 2026-11-05 |
| Karpathy autoresearch's inspected commit is outside the window. | [Commit 228791fb499afffb54b46200aca536f79142f117](https://github.com/karpathy/autoresearch/commit/228791fb499afffb54b46200aca536f79142f117); the same commit query returned 2026-03-26T00:07:37Z. | 2026-11-05 |
| codex-plugin-cc's inspected commit is outside the window. | [Commit db52e28f4d9ded852ab3942cea316258ae4ef346](https://github.com/openai/codex-plugin-cc/commit/db52e28f4d9ded852ab3942cea316258ae4ef346); the same commit query returned 2026-07-08T00:17:00Z. | 2026-11-05 |
| Exact source pins, tag names and release dates in J1-J6. | gh api repos/OWNER/REPO/tags?per_page=5 and releases?per_page=3; resolve missing tag SHAs with commits/TAG. Each component's complete commit is recorded beside its pick; sources above are fetched at that commit. GitHub API observations are dated evidence, not a promise that a mutable tag can never move. | 2026-11-05 |
| CLI version and supported installation/merge flags. | codex --version, codex plugin marketplace add --help, codex plugin list --help, gh extension install --help, gh pr merge --help, claude plugin marketplace add --help: all exited 0, with the results listed in Verification. The App build, served model and active effort remain UNVERIFIED. | 2026-11-05 |
| Renovate registry pin. | npm view renovate@44.221.1 version dist.integrity --json exited 0; version/integrity recorded in J2. Registry provenance and installed binary execution remain UNVERIFIED. | 2026-11-05 |
| Pinned citation availability and line bounds. | Read-only urllib source audit: 78 unique pinned files, 91 source ranges, zero HTTP/range failures. This is a source-reference check, not an upstream test-suite run. | 2026-11-05 |

[G01]: https://github.com/github/gh-aw/blob/0627fdbe4beb5f3b71aa569f8d97150b87f2111a/README.md#L16-L53
[G02]: https://github.com/github/gh-aw/blob/0627fdbe4beb5f3b71aa569f8d97150b87f2111a/.github/aw/pr-reviewer.md#L5-L31
[G03]: https://github.com/github/gh-aw/blob/0627fdbe4beb5f3b71aa569f8d97150b87f2111a/docs/src/content/docs/reference/engines/codex.md#L8-L10
[G04]: https://github.com/github/gh-aw/blob/0627fdbe4beb5f3b71aa569f8d97150b87f2111a/docs/src/content/docs/reference/engines/claude.md#L8-L10
[G05]: https://github.com/github/gh-aw/blob/0627fdbe4beb5f3b71aa569f8d97150b87f2111a/docs/src/content/docs/reference/self-hosted-runners.md#L8-L20
[G06]: https://github.com/github/gh-aw/blob/0627fdbe4beb5f3b71aa569f8d97150b87f2111a/docs/src/content/docs/reference/self-hosted-runners.md#L145-L191
[G07]: https://github.com/github/gh-aw/blob/0627fdbe4beb5f3b71aa569f8d97150b87f2111a/docs/src/content/docs/reference/safe-outputs.md#L1081-L1129
[G08]: https://github.com/github/gh-aw/blob/0627fdbe4beb5f3b71aa569f8d97150b87f2111a/actions/setup/js/create_check_run.cjs#L173-L226
[G09]: https://github.com/github/gh-aw/blob/0627fdbe4beb5f3b71aa569f8d97150b87f2111a/actions/setup/js/create_check_run.test.cjs#L86-L111
[G10]: https://github.com/github/gh-aw/blob/0627fdbe4beb5f3b71aa569f8d97150b87f2111a/actions/setup/js/create_check_run.test.cjs#L287-L335
[G11]: https://github.com/github/docs/blob/17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493/content/pull-requests/how-tos/merge-and-close-pull-requests/automatically-merging-a-pull-request.md#L19-L37
[G12]: https://github.com/github/docs/blob/17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493/data/reusables/gated-features/auto-merge.md#L1
[G13]: https://github.com/cli/cli/blob/63837fb778d6a39f02be0ce76ff89f2bc8d74bdc/pkg/cmd/pr/merge/merge.go#L174-L184
[G14]: https://github.com/github/gh-aw/blob/0627fdbe4beb5f3b71aa569f8d97150b87f2111a/docs/src/content/docs/reference/safe-outputs-pull-requests.md#L260-L269
[G15]: https://github.com/openai/codex-action/blob/bdf19a4a223ec2549a3e2274a0cf61556bc07675/README.md#L11-L16
[G16]: https://github.com/openai/codex-action/blob/bdf19a4a223ec2549a3e2274a0cf61556bc07675/action.yml#L54-L69
[G17]: https://github.com/openai/codex-action/blob/bdf19a4a223ec2549a3e2274a0cf61556bc07675/README.md#L168-L181
[G18]: https://github.com/anthropics/claude-code-action/blob/c0949c50a78c1ec8ce2647db36629b870e715d0c/examples/pr-review-comprehensive.yml#L6-L65
[G19]: https://github.com/OpenHands/extensions/blob/b3d7c6abb62b775e2187929694fcadce4e358789/plugins/pr-review/README.md#L258-L266
[G20]: https://github.com/alibaba/open-code-review/blob/891df1b63f380845d882a289a67a6e36c331120c/action.yml#L100-L111
[G21]: https://github.com/github/docs/blob/17d6ee52f965e7c46f74b4339d5fa1ad6f4f4493/data/reusables/actions/actions-do-not-trigger-workflows.md#L1-L6
[R01]: https://github.com/renovatebot/renovate/blob/9bfa4c49b91f9d17f592c2cef9a14ac4c3dda2ec/docs/usage/getting-started/running.md#L11-L81
[R02]: https://github.com/renovatebot/renovate/blob/9bfa4c49b91f9d17f592c2cef9a14ac4c3dda2ec/docs/usage/examples/self-hosting.md#L12-L49
[R03]: https://github.com/renovatebot/renovate/blob/9bfa4c49b91f9d17f592c2cef9a14ac4c3dda2ec/docs/usage/getting-started/running.md#L140-L150
[R04]: https://github.com/renovatebot/renovate/blob/9bfa4c49b91f9d17f592c2cef9a14ac4c3dda2ec/lib/modules/manager/git-submodules/readme.md#L1-L27
[R05]: https://github.com/renovatebot/renovate/blob/9bfa4c49b91f9d17f592c2cef9a14ac4c3dda2ec/lib/modules/manager/custom/regex/readme.md#L1-L43
[R06]: https://github.com/renovatebot/renovate/blob/9bfa4c49b91f9d17f592c2cef9a14ac4c3dda2ec/lib/modules/platform/github/readme.md#L68-L103
[R07]: https://github.com/github/gh-aw/blob/0627fdbe4beb5f3b71aa569f8d97150b87f2111a/.github/workflows/daily-workflow-updater.md#L65-L87
[R08]: https://github.com/github/gh-aw/blob/0627fdbe4beb5f3b71aa569f8d97150b87f2111a/.github/workflows/daily-workflow-updater.md#L34-L43
[C01]: https://github.com/EveryInc/compound-engineering-plugin/blob/7dc50943bbf959dbe6a93a175e41e5fff8395e00/README.md#L23-L114
[C02]: https://github.com/EveryInc/compound-engineering-plugin/blob/7dc50943bbf959dbe6a93a175e41e5fff8395e00/skills/ce-compound/SKILL.md#L19-L64
[C03]: https://github.com/EveryInc/compound-engineering-plugin/blob/7dc50943bbf959dbe6a93a175e41e5fff8395e00/skills/ce-compound/references/form.md#L7-L21
[C04]: https://github.com/EveryInc/compound-engineering-plugin/blob/7dc50943bbf959dbe6a93a175e41e5fff8395e00/skills/ce-compound/references/refresh/overview.md#L20-L42
[C05]: https://github.com/EveryInc/compound-engineering-plugin/blob/7dc50943bbf959dbe6a93a175e41e5fff8395e00/skills/ce-compound/references/session-history.md#L36-L52
[C06]: https://github.com/tradermonty/claude-trading-skills/blob/d8e71ce2f0b069eb5b6fca352857c168c35e6c46/skills/trader-memory-core/SKILL.md#L1-L39
[C07]: https://github.com/tradermonty/claude-trading-skills/blob/d8e71ce2f0b069eb5b6fca352857c168c35e6c46/skills/signal-postmortem/SKILL.md#L80-L108
[C08]: https://github.com/tradermonty/claude-trading-skills/blob/d8e71ce2f0b069eb5b6fca352857c168c35e6c46/examples/workflows/monthly-performance-review/README.md#L13-L41
[B01]: https://github.com/EveryInc/compound-engineering-plugin/blob/7dc50943bbf959dbe6a93a175e41e5fff8395e00/skills/ce-bakeoff/SKILL.md#L8-L40
[B02]: https://github.com/EveryInc/compound-engineering-plugin/blob/7dc50943bbf959dbe6a93a175e41e5fff8395e00/skills/ce-bakeoff/references/candidates.md#L3-L17
[B03]: https://github.com/EveryInc/compound-engineering-plugin/blob/7dc50943bbf959dbe6a93a175e41e5fff8395e00/skills/ce-bakeoff/references/candidates.md#L35-L37
[B04]: https://github.com/EveryInc/compound-engineering-plugin/blob/7dc50943bbf959dbe6a93a175e41e5fff8395e00/skills/ce-bakeoff/references/judging.md#L3-L17
[B05]: https://github.com/EveryInc/compound-engineering-plugin/blob/7dc50943bbf959dbe6a93a175e41e5fff8395e00/skills/ce-bakeoff/references/verification.md#L7-L15
[B06]: https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/blob/299cd76633f66657487f617c25f86e55ed89b50a/README.md#L115-L150
[T01]: https://github.com/tradermonty/claude-trading-skills/blob/d8e71ce2f0b069eb5b6fca352857c168c35e6c46/README.md#L121-L130
[T02]: https://github.com/tradermonty/claude-trading-skills/blob/d8e71ce2f0b069eb5b6fca352857c168c35e6c46/skills/backtest-expert/SKILL.md#L27-L99
[T03]: https://github.com/tradermonty/claude-trading-skills/blob/d8e71ce2f0b069eb5b6fca352857c168c35e6c46/skills/backtest-expert/SKILL.md#L113-L132
[T04]: https://github.com/tradermonty/claude-trading-skills/blob/d8e71ce2f0b069eb5b6fca352857c168c35e6c46/skills/edge-strategy-designer/SKILL.md#L10-L38
[T05]: https://github.com/tradermonty/claude-trading-skills/blob/d8e71ce2f0b069eb5b6fca352857c168c35e6c46/skills/pre-trade-discipline-gate/SKILL.md#L8-L12
[T06]: https://github.com/nautechsystems/nautilus_trader/blob/27a8e54e7ac3c57d6cbf8891f0283dfbaee97317/docs/getting_started/installation.md#L3-L48
[T07]: https://github.com/nautechsystems/nautilus_trader/blob/27a8e54e7ac3c57d6cbf8891f0283dfbaee97317/examples/backtest/example_01_load_bars_from_custom_csv/run_example.py#L17-L55
[T08]: https://github.com/nautechsystems/nautilus_trader/blob/27a8e54e7ac3c57d6cbf8891f0283dfbaee97317/examples/backtest/example_01_load_bars_from_custom_csv/strategy.py#L21-L25
[T09]: https://github.com/deepseek-ai/deepseek-harness/blob/66491b05e3f05ad35bcdd4f6cd7ed26041d9e3db/packages/skill/skill-filesystem/README.md#L34-L56
[T10]: https://github.com/deepseek-ai/deepseek-harness/blob/66491b05e3f05ad35bcdd4f6cd7ed26041d9e3db/docs/subsystems/skills.md#L227-L237
[O01]: https://github.com/tradermonty/claude-trading-skills/blob/d8e71ce2f0b069eb5b6fca352857c168c35e6c46/skills/options-strategy-advisor/SKILL.md#L8-L48
[O02]: https://github.com/tradermonty/claude-trading-skills/blob/d8e71ce2f0b069eb5b6fca352857c168c35e6c46/skills/options-strategy-advisor/SKILL.md#L106-L183
[O03]: https://github.com/tradermonty/claude-trading-skills/blob/d8e71ce2f0b069eb5b6fca352857c168c35e6c46/skills/options-strategy-advisor/SKILL.md#L800-L815
[J01]: https://github.com/typesafe-ai/skills/blob/302eea662c54bca6730873fe245bec1d69ebc23d/README.md#L7-L35
[J02]: https://github.com/typesafe-ai/skills/blob/302eea662c54bca6730873fe245bec1d69ebc23d/skills/typesafe-ai/SKILL.md#L15-L37
[J03]: https://github.com/typesafe-ai/skills/blob/302eea662c54bca6730873fe245bec1d69ebc23d/skills/typesafe-ai/SKILL.md#L39-L62
[J04]: https://github.com/typesafe-ai/skills/blob/302eea662c54bca6730873fe245bec1d69ebc23d/skills/typesafe-ai/SKILL.md#L148-L206
[J05]: https://github.com/typesafe-ai/typesafe-public-examples/blob/262a1f1362a3764028051056c272388027a5a06e/cookbooks/function_calling/dispatch.py#L1-L12
[J06]: https://github.com/typesafe-ai/typesafe-public-examples/blob/262a1f1362a3764028051056c272388027a5a06e/cookbooks/function_calling/trader.py#L1-L60
[J07]: https://github.com/typesafe-ai/typesafe-public-examples/blob/262a1f1362a3764028051056c272388027a5a06e/README.md#L5-L9
[H01]: https://github.com/EveryInc/compound-engineering-plugin/blob/7dc50943bbf959dbe6a93a175e41e5fff8395e00/.codex-plugin/plugin.json#L1-L45
[H02]: https://github.com/Yeachan-Heo/oh-my-claudecode/blob/14cd0fe92fbe376fab6c89b333b7896811986d2d/docs/HOOKS.md#L43-L104
[H03]: https://github.com/affaan-m/ECC/blob/c05b2d6614f62f6db0047669aa4eefb223d478f9/README.md#L449-L459
[H04]: https://github.com/uditgoenka/autoresearch/blob/7bddd056dfd0b0ded8360588d8101b1ecb5c0baa/guide/hooks.md#L71-L105
[H05]: https://github.com/uditgoenka/autoresearch/blob/7bddd056dfd0b0ded8360588d8101b1ecb5c0baa/guide/hooks.md#L136-L156
[H06]: https://github.com/thedotmack/claude-mem/blob/c2bca506d853e867cfa02341672869354b85e18a/plugin/hooks/hooks.json#L17-L75
[H07]: https://github.com/vectorize-io/hindsight/blob/34a138684a899b6ec34175f7a2b633860466d289/README.md#L64-L143
[L01]: https://github.com/github/gh-aw/blob/0627fdbe4beb5f3b71aa569f8d97150b87f2111a/LICENSE#L1-L12
[L02]: https://github.com/renovatebot/renovate/blob/9bfa4c49b91f9d17f592c2cef9a14ac4c3dda2ec/package.json#L138
[L03]: https://github.com/EveryInc/compound-engineering-plugin/blob/7dc50943bbf959dbe6a93a175e41e5fff8395e00/LICENSE#L1-L12
[L04]: https://github.com/tradermonty/claude-trading-skills/blob/d8e71ce2f0b069eb5b6fca352857c168c35e6c46/LICENSE#L1-L12
[L05]: https://github.com/typesafe-ai/skills/blob/302eea662c54bca6730873fe245bec1d69ebc23d/LICENSE#L1-L12
[L06]: https://github.com/nautechsystems/nautilus_trader/blob/27a8e54e7ac3c57d6cbf8891f0283dfbaee97317/LICENSE#L1-L16
[L07]: https://github.com/Imbad0202/academic-research-skills/blob/bcbcac39e874744cda98d6ddaaf765cfd00b0e40/LICENSE#L1-L10
[N01]: https://learn.chatgpt.com/docs/build-skills
[A01]: https://github.com/dependabot/dependabot-core/blob/9ac98a409855e01424e00469efb87377a173334d/README.md#L42-L62
[A02]: https://github.com/TauricResearch/TradingAgents/blob/c4544913a14ed3df5f1ed7b9e8483270ce20682a/README.md#L248-L252
[A03]: https://github.com/HKUDS/Vibe-Trading/blob/cb99dca528695ffe78429483a90399a89f61d614/README.md#L149-L155
[A04]: https://github.com/OpenHands/OpenHands/blob/d30f1e45bbb67558ec2bfcd639b907ae525f162c/README.md#L166-L176
[A05]: https://github.com/The-PR-Agent/pr-agent/blob/efdde4afe14aa401a3889012c7f3e9ef3081a430/README.md#L64-L123
[A06]: https://github.com/alibaba/open-code-review/blob/891df1b63f380845d882a289a67a6e36c331120c/README.md#L53-L69
[A07]: https://github.com/affaan-m/ECC/blob/c05b2d6614f62f6db0047669aa4eefb223d478f9/README.md#L128-L151
[A08]: https://github.com/uditgoenka/autoresearch/blob/7bddd056dfd0b0ded8360588d8101b1ecb5c0baa/README.md#L1-L70
[A09]: https://github.com/NousResearch/hermes-agent/blob/2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19/README.md#L20-L33
[A10]: https://github.com/anthropics/financial-services/blob/60565064557ca77b12f62aa7877f365d111c129d/README.md#L1-L13
[A11]: https://github.com/alphaXiv/OpenResearch/blob/23a4d67bb5ce3cf9051f8d62b2cd52e93116e16d/README.md#L68-L98
[A12]: https://github.com/assafelovic/gpt-researcher/blob/0957c301ed06c2a5857b834358c7227c739041d4/README.md#L95-L140
[T11]: https://github.com/tradermonty/claude-trading-skills/blob/d8e71ce2f0b069eb5b6fca352857c168c35e6c46/skills/backtest-expert/references/methodology.md#L83-L99
[L08]: https://github.com/cli/cli/blob/63837fb778d6a39f02be0ce76ff89f2bc8d74bdc/LICENSE#L1-L12
[J08]: https://docs.typesafe.ai/models.md
[J09]: https://docs.typesafe.ai/agent-skill.md

