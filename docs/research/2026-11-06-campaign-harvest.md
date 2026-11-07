# Campaign harvest, 2026-11-06 (#61)

**Decision informed:** which practices from the old campaigns are truly SOTA-aligned and not yet in Sextant. The owner, relayed on #58: "make sure it harvest all the sota practice of our campaigns that is truly sotaaligned … the practice can be sota in legacy also aslong as the upstream sota repos resolution and conbvergneced researhc".

**The test.** A practice passes only if the upstream resolves it **and** its research converged: a finalized record with its convergence record, at its SHA. Process weight (receipts, landing trains, the one-lander hold, the `srt` worker jail, beads, the old routers and dashboards) stays behind unless its record shows it is SOTA. What #33's harvest and `docs/manifest.md` already carry counts as done.

**Pins, read-only through `gh`, 2026-11-06:**

| Repo | This read | #33's pin | Delta since #33 |
|---|---|---|---|
| seathatflowsinourveins/northstar `main` | `6957af5d6f06b0a1be82b97a8246dea51c9dce3f` | `b384d298d217d3f8d9aa83356994629536a34795` | 206 commits; 20 records amended, 0077 and 0078 added |
| seathatflowsinourveins/northstar-trading `paper` | `18a803ddf312ca23acaf6419cbb5dd3adbe4314c` | `8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa` | 12 commits; Status lines and four unreviewed practice notes |
| seathatflowsinourveins/northstar-lanes `main` | `a5c8a27128339bb18ac43e5d1bc31c294291cad5` | `00203275944a22655b3e14b221cfde9a265d549a` | 16 commits; dsh second-family verdicts on 0002–0009, owner words, the Jev-fit outcome |

**Indexes read:** harness ADR-0064's amendment 2026-11-05 (3), the binding 16-layer table; `docs/research/foundation-stack.json` (asOf 2026-10-28, 16 `layerMap` rows) and its `foundation-verdicts.json` (649 records: 86 ADOPT, 34 BUILD-UPON, 158 WATCH, 330 DOCUMENTED-NON-USE, 35 NO-VERDICT, 6 REFERRED; sha256 `9d6f798d22257c08…`); the convergence ledger `docs/research/2026-11-06-convergence-ledger/README.md` (99 live records: harness 68, trading 20, lanes 11; DeepSeek verdicts on 95).

## Result

- **Adopted: three corrections,** each from a finalized record's second-family verdict and each re-measured at the upstream today. They go into [ADR-0029](../adr/0029-second-family-corrections.md) and amend the carried lines in ADR-0003, ADR-0004 and ADR-0010.
- **Of 104 records: 3 adopted, 65 carried, 36 left behind.** Every trading record (20 of 20) and every lanes record but 0002's layout rule is carried or adopted, as are the trading-facing harness records. The newer amendments add no other rule. The Jev-fit outcome (lanes 0009, 2026-11-06: no new arm until a treatment runs) matches [ADR-0017](../adr/0017-jev-judgments.md)'s OFF default.
- **Left behind: the old harness machinery.** Sextant's own two-family convergence of 2026-11-05 ([ADR-0001](../adr/0001-sextant-foundation.md), [foundations convergence](2026-11-05-foundations-convergence.md)) picked its harness afresh. Where the old pick agrees, the manifest carries it, usually at a newer pin. Where it differs, the newer convergence and the owner's "clean … never bloat" rule govern.

## The 16 layers (harness ADR-0064, amendment 2026-11-05 (3))

| Layer | Old pick | Verdict | Sextant home or reason |
|---|---|---|---|
| L0 Host base | mise + Homebrew + OrbStack | Left behind | One clean WSL distro from cloud-init and uv ([start](../start.md)); mise solves a multi-host Mac/Windows need Sextant doesn't have |
| L1 Lead | Claude Code 2.1.318 | Carried | Manifest "Runtimes" row |
| L2 Method | Superpowers 7.0.1 + skills CLI | Carried | Manifest "Superpowers" row at 7.0.2 |
| L3 Orchestration | Gas City + beads | Left behind | Orca orchestration and saved Workflows; beads are removed process weight ([ADR-0023](../adr/0023-harness-rules-carried.md)) |
| L4 Workers | Pi, Codex, OpenCode, OMP | Partly carried | Codex and dsh in "Runtimes"; Pi, OpenCode and OMP add runtimes Sextant's roster doesn't use |
| L5 Router | OmniRoute | Left behind | Waits for a local runner ([ADR-0001](../adr/0001-sextant-foundation.md), "GPT review waits") |
| L6 Code intelligence | CodeGraph + LSP + ast-grep | Carried | "CodeGraph MCP" and the LSP plugin rows; ast-grep in [ADR-0022](../adr/0022-memory-rag-and-enhanced-dsh.md) |
| L7 Docs and research | Context7, Exa, paper-search, DeepWiki | Carried | The four MCP rows |
| L8 Memory | beads + qmd + CodeGraph | Partly carried | [ADR-0022](../adr/0022-memory-rag-and-enhanced-dsh.md); beads removed |
| L9 Token efficiency | native caching | Carried | [ADR-0023](../adr/0023-harness-rules-carried.md) Q; host settings are runtime defaults, not a practice |
| L10 Verification | Superpowers + Harbor | Partly carried | Superpowers and the `review` check; Harbor measures agents, while merit here is replay, sim and paper ([ADR-0019](../adr/0019-validation-and-merit.md)) |
| L11 Safety | dcg + Betterleaks | Left behind | "Boundaries, not hooks": dev container, rulesets, gitleaks ([ADR-0001](../adr/0001-sextant-foundation.md)); the owner ruled out security over-engineering |
| L12 Observability | Alloy → SigNoz, AgentsView, claude-hud | Partly carried | "Claude HUD" row; the telemetry stack has no measured need |
| L13 Cockpit | Orca + cmux | Carried | Orca ([start](../start.md)); cmux unused |
| L14 CI and PR | OpenHands Automation | Left behind | Both Sextant legs picked gh-aw (J1); OpenHands needs a service stack |
| L15 Trading | NautilusTrader 2.0.0rc7, alpaca-py, IB gateway | Carried | Manifest trading-engine row; [ADR-0008](../adr/0008-broker-roles.md), [ADR-0013](../adr/0013-us-equity-data-stack.md) |

## Inventory

`harness` is northstar `docs/decisions/`, `trading` and `lanes` are those repos' `docs/adr/`. Home names the Sextant record that carries it.

| Record | Verdict | Sextant home or reason |
|---|---|---|
| `harness:0001` native-first, one owner per job | Carried | [ADR-0023](../adr/0023-harness-rules-carried.md) U; AGENTS Rule 1 |
| `harness:0002` L0 macOS base | Left behind | Mac host; see L0 |
| `harness:0003` L1 lead runtime | Carried | Manifest "Runtimes"; the Max-20x routing is account machinery |
| `harness:0004` L2 Superpowers | Carried | Manifest "Superpowers" |
| `harness:0005` L3 native Workflows | Carried | Manifest "Saved lead Workflows", "OMC, session opt-in" |
| `harness:0006` L4 workers (superseded by 0070) | Left behind | Superseded |
| `harness:0007` L5 OmniRoute | Left behind | See L5 |
| `harness:0008` L6 code intelligence (superseded by 0069) | Left behind | Superseded |
| `harness:0009` L7 docs research | Carried | The MCP rows |
| `harness:0010` L8 memory (superseded by 0069) | Left behind | Superseded |
| `harness:0011` L9 token efficiency | Carried | [ADR-0023](../adr/0023-harness-rules-carried.md) Q |
| `harness:0012` L10 verification | Carried | Superpowers; `review` check |
| `harness:0013` L11 safety | Left behind | See L11 |
| `harness:0014` L12 observability | Left behind | See L12 |
| `harness:0015` L13 cockpit (superseded by 0066) | Left behind | Superseded |
| `harness:0016` L15 trading stack | Carried | [ADR-0008](../adr/0008-broker-roles.md), [ADR-0012](../adr/0012-portfolio-management.md); its 2026-11-06 TRADE LEAD note is a role, not a practice |
| `harness:0017` L14 CI and cloud | Left behind | gh-aw (J1) |
| `harness:0018` paper never gated | Carried | [ADR-0002](../adr/0002-philosophy-and-lanes.md) |
| `harness:0019` execution topology, throughput | Carried | [ADR-0009](../adr/0009-order-rate-limits.md), `lanes/limits.yaml` |
| `harness:0020` strategy sourcing | Carried | [ADR-0015](../adr/0015-research-lane-and-strategy-sourcing.md) |
| `harness:0021` US-equity data | Carried | [ADR-0013](../adr/0013-us-equity-data-stack.md) |
| `harness:0022` 24/5, auto-leverage, throughput | Carried | [ADR-0002](../adr/0002-philosophy-and-lanes.md), [ADR-0011](../adr/0011-sizing-and-auto-leverage.md) |
| `harness:0023` A/B testing, fine-tuning | Carried | [ADR-0015](../adr/0015-research-lane-and-strategy-sourcing.md), [ADR-0019](../adr/0019-validation-and-merit.md) |
| `harness:0024` bypassPermissions, guard containment | Carried | No-prompt tabs on the clean distro, the dev container for unattended agents ([start](../start.md)); the guards stay behind (L11) |
| `harness:0025` session launch, bead as brief | Left behind | GitHub Issues are the brief; beads removed |
| `harness:0026` OMC command center (superseded by 0041) | Left behind | Superseded |
| `harness:0027` Squid egress proxy | Left behind | Manifest "Open web, private ranges blocked", the owner's choice |
| `harness:0029` PR automation, lander | Left behind | gh-aw and squash auto-merge ([ADR-0001](../adr/0001-sextant-foundation.md)); the lander is process weight |
| `harness:0031` research runtime lane | Carried | [ADR-0015](../adr/0015-research-lane-and-strategy-sourcing.md) |
| `harness:0032` quality-only evaluation | Carried | [ADR-0001](../adr/0001-sextant-foundation.md) admits OpenViking (AGPL-3.0); licences stay recorded in the manifest |
| `harness:0033` OmniRoute login | Left behind | See L5 |
| `harness:0034` cmux command center | Left behind | Orca |
| `harness:0035` OpenCode/OMO `srt` sandbox | Left behind | The `srt` worker jail; the dev container is the sandbox |
| `harness:0036` runtime fabric | Left behind | Same |
| `harness:0037` multi-runtime bus | Left behind | Orca orchestration |
| `harness:0038` tmux lane views | Left behind | Orca native tabs |
| `harness:0039` model lock, local benchmark gate | Left behind | A self-built bench never gates a pick ([ADR-0023](../adr/0023-harness-rules-carried.md)); latest-only models carried there as P |
| `harness:0040` paper nodes in containers | Left behind | Paper waits for the owner's handover (AGENTS, First steps); reopen then |
| `harness:0041` foundation v1 trial closures | Left behind | Old campaign definition of done; OMC overridden by [ADR-0001](../adr/0001-sextant-foundation.md) |
| `harness:0042` memory layer v2 | Left behind | Superseded in its own repo by 0069 |
| `harness:0044` multi-runtime launch | Left behind | Orca tabs run `claude`, `codex`, `dsh` |
| `harness:0045` harness first, upstream first | Carried | [ADR-0023](../adr/0023-harness-rules-carried.md); its 2026-11-06 research-leg notes are unreviewed |
| `harness:0046` proportionate rigor | Carried | [ADR-0023](../adr/0023-harness-rules-carried.md); the new amendment only quotes owner words |
| `harness:0048` quality first | Carried | [ADR-0023](../adr/0023-harness-rules-carried.md); its effort-route note is a draft with REQUEST CHANGES |
| `harness:0049` paid finalize listener | Left behind | Router machinery |
| `harness:0050` multi-runtime harness | Left behind | One other-family reviewer ([ADR-0001](../adr/0001-sextant-foundation.md)) |
| `harness:0051` god view | Left behind | Monitor layer; Orca |
| `harness:0052` enhanced profiles | Carried | [ADR-0022](../adr/0022-memory-rag-and-enhanced-dsh.md) |
| `harness:0053` live lane | Carried | [ADR-0020](../adr/0020-live-lane.md) |
| `harness:0054` OmniRoute provenance | Left behind | See L5 |
| `harness:0055` lanes | Carried | [ADR-0002](../adr/0002-philosophy-and-lanes.md) |
| `harness:0056` ecosystem convergence 2026-10 | Left behind | Replaced by Sextant's 2026-11-05 convergence |
| `harness:0057` one enrichment manifest | Carried | `docs/manifest.md` |
| `harness:0058` OMC reopen | Carried | Manifest "OMC, session opt-in" |
| `harness:0059` Yeachan-Heo ecosystem | Carried | OMC only; its other trials stay behind |
| `harness:0060` evolved by evidence | Carried | AGENTS Rule 2 |
| `harness:0062` two-host execution | Left behind | One clean distro |
| `harness:0063` Linux secrets | Carried | [ADR-0028](../adr/0028-local-keys.md) |
| `harness:0064` MADR 4.0.0, catalog, ledger, radar | Left behind | Sextant keeps one-page records under a size budget; the wrapper, generated catalog, ledger and radar are process weight |
| `harness:0065` Gas City | Left behind | See L3 |
| `harness:0066` Orca | Carried | [start](../start.md) |
| `harness:0067` MCP tools | Carried | The MCP rows |
| `harness:0068` agent skills | Carried | Skill shelf rows; `alpacahq/alpaca-skills` was only BUILD-UPON, reference-only, ring Trial, so it stays behind |
| `harness:0069` memory and code intelligence | Carried | See L6 and L8 |
| `harness:0070` runtimes | Carried | See L4 |
| `harness:0071` platform, observability | Left behind | See L0 and L12; claude-hud carried |
| `harness:0072` evaluation lab | Left behind | See L10 |
| `harness:0073` router, guards, review | Left behind | See L5, L11, L14; actionlint, zizmor and gitleaks are carried |
| `harness:0074` host baseline | Carried | "Latest stable defaults", [ADR-0023](../adr/0023-harness-rules-carried.md) L |
| `harness:0075` agent context files | Carried | Manifest "Short always-loaded instructions" |
| `harness:0076` host lifecycle | Carried | Manifest "Leave no worktree or branch behind"; old-host retirement is the old lanes' |
| `harness:0077` 24/7 sim lane | Carried | [sim lane](../../lanes/sim/README.md), [ADR-0019](../adr/0019-validation-and-merit.md); its own DeepSeek leg was REQUEST CHANGES with no class |
| `harness:0078` paper strategy philosophy | Carried | [ADR-0002](../adr/0002-philosophy-and-lanes.md), [philosophy](../handbook/philosophy.md); same second-family status |
| `trading:0001` record decisions | Carried | `docs/adr/` |
| `trading:0002` Alpaca native brackets | Carried | [ADR-0005](../adr/0005-exit-engine.md) |
| `trading:0002` data API stack | Carried | [ADR-0013](../adr/0013-us-equity-data-stack.md) |
| `trading:0003` data stack final | Carried | [ADR-0013](../adr/0013-us-equity-data-stack.md) |
| `trading:0004` paper capacity | Carried | [ADR-0009](../adr/0009-order-rate-limits.md) |
| `trading:0005` paper safeguards | Carried | [ADR-0010](../adr/0010-risk-guard-pacing-and-halt.md); its 2026-11-06 full-window journal note is unreviewed |
| `trading:0006` risk guard, pacing | Carried | [ADR-0010](../adr/0010-risk-guard-pacing-and-halt.md) |
| `trading:0007` storage, catalog | Carried | [ADR-0013](../adr/0013-us-equity-data-stack.md) |
| `trading:0008` features, microstructure | Carried | [ADR-0014](../adr/0014-features-and-regime-models.md) |
| `trading:0009` models | Carried | [ADR-0014](../adr/0014-features-and-regime-models.md) |
| `trading:0010` portfolio, leverage | Carried | [ADR-0011](../adr/0011-sizing-and-auto-leverage.md), [ADR-0012](../adr/0012-portfolio-management.md) |
| `trading:0011` exits, re-entry | Carried | [ADR-0005](../adr/0005-exit-engine.md) |
| `trading:0012` agentic research, TradingView | Carried | [ADR-0015](../adr/0015-research-lane-and-strategy-sourcing.md), [ADR-0021](../adr/0021-tradingview-display.md) |
| `trading:0013` compounding loop | Carried | [ADR-0018](../adr/0018-evidence-and-learning-loop.md) |
| `trading:0014` TradingView lane | Carried | [ADR-0021](../adr/0021-tradingview-display.md), [ADR-0026](../adr/0026-tradingview-sync-and-order-presets.md) |
| `trading:0015` owner-entry exit manager | Carried | [ADR-0007](../adr/0007-custody-and-order-writing.md), [ADR-0025](../adr/0025-gain-protection-and-fast-exit.md) |
| `trading:0016` momentum rotation | Carried | [ADR-0002](../adr/0002-philosophy-and-lanes.md); its 2026-11-06 scorecard note is below |
| `trading:0017` order reducer | Carried | [ADR-0007](../adr/0007-custody-and-order-writing.md) |
| `trading:0018` A/C data supply | Carried | [ADR-0013](../adr/0013-us-equity-data-stack.md) |
| `trading:0019` managed exits, ranked re-entry | Carried | [ADR-0005](../adr/0005-exit-engine.md), [ADR-0006](../adr/0006-reentry-and-rotation.md), [ADR-0025](../adr/0025-gain-protection-and-fast-exit.md) |
| `lanes:0001` record decisions | Carried | `docs/adr/` |
| `lanes:0002` layout, move not copy | Left behind | Sextant cites at a pin and copies no code |
| `lanes:0003` philosophy | Carried | [ADR-0002](../adr/0002-philosophy-and-lanes.md); DeepSeek's correction was only line numbers |
| `lanes:0004` ranking, feeds | Adopted | Halt-feed correction: [ADR-0029](../adr/0029-second-family-corrections.md) C1; else [ADR-0003](../adr/0003-ranking-and-feeds.md) |
| `lanes:0005` entry | Adopted | Extended-hours TIF: [ADR-0029](../adr/0029-second-family-corrections.md) C2; else [ADR-0004](../adr/0004-entry.md) |
| `lanes:0006` exit engine | Adopted | rc8 release risk check: [ADR-0029](../adr/0029-second-family-corrections.md) C3; else [ADR-0005](../adr/0005-exit-engine.md) |
| `lanes:0007` re-entry, rotation | Carried | [ADR-0006](../adr/0006-reentry-and-rotation.md) |
| `lanes:0008` custody, order writing | Carried | [ADR-0007](../adr/0007-custody-and-order-writing.md); the IB order-list post-only correction touches no Sextant line |
| `lanes:0009` evidence, learning loop | Carried | [ADR-0018](../adr/0018-evidence-and-learning-loop.md), [ADR-0019](../adr/0019-validation-and-merit.md) |
| `lanes:0010` broker roles | Carried | [ADR-0008](../adr/0008-broker-roles.md) |
| `lanes:0011` sizing, leverage | Carried | [ADR-0011](../adr/0011-sizing-and-auto-leverage.md) |

Also read and left behind: `harness:proposed-memory-layer-v3` (superseded) and `harness:proposed-multi-runtime-platform-candidate` (rejected 2026-10-21). Neither was finalized.

## Final delta, 2026-11-07 (before archive)

Read-only, at the final heads before the owner archives the five repos: northstar `main` `d872b1f8b1062abc70a139ba3712fa61c34b416d` (24 commits since this note's pin), northstar-lanes `main` `5b80ddc02ccfd635d7c200a411a5300a97251db3` (2), northstar-trading `paper` `d820ee66ce28e1e7c30defb8102ca27c6ddab5f8` (62), and, never read before, northstar-ao-sandbox `641308150d28ffd179f036a52e7b0bac87874a3f` and north-star-research `cc542f5b82d68a01122dc76a692c84c0ccf93282`. Unmerged branches were read by head; one GraphQL call listed the 96 open PRs and 38 issues. Of 36 rows: 2 adopted, 5 carried, 29 left behind.

- **Adopted, each in its own PR.** (A1) At trading `d820ee66`, all 24 B rows start at `backstop_start_fraction` 0.025 with `hazard_enabled` false (`30f2db1160c56f07b609c5e8c6884cf2f568ddfc`, PR #548), so the conflict that [ADR-0025](../adr/0025-gain-protection-and-fast-exit.md):56, [design](../design.md):167 and the paper README record is resolved at its source; ADR-0025:60 names this trigger. (A2) Alpaca rejects with 403 an order that could cross the account's resting opposite order, on paper too; bracket, OCO and trailing stops are exempt ([User Protection](https://docs.alpaca.markets/docs/user-protection), updated 2026-09-16, read 2026-11-07). It converged STRONG at `northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:docs/research/2026-10-23-lane-api-convergence.md:33` and finalized trading ADR-0002 uses it, yet no Sextant record or test names it. It lands in [ADR-0007](../adr/0007-custody-and-order-writing.md) with a bridge witness: B never cancels an owner's resting buy, so its cancel-first LIMIT exit can be refused after the exempt trail is gone.
- **Carried:** the TradingView Desktop handover (trading 0012/0014 notes; [ADR-0021](../adr/0021-tradingview-display.md):51), the paper lanes' move to Sextant (trading 0016; [ADR-0007](../adr/0007-custody-and-order-writing.md):48), lanes 0004's FDA roles ([ADR-0013](../adr/0013-us-equity-data-stack.md):20), the EdgarTools bridge (manifest), and the research repo's 2026-10-01 historical baseline, whose 169 files all sit in `seed-research-2026-10-09`.
- **Left behind:** the six harness notes (all "Not reviewed yet": Mac host, router, installer and record machinery), the hourly-report and landing-route notes, the scanner cost, prewarm and roll work, the loop twins, W2/W3 and node-unit fixes, the AO sandbox, and north-star-research's decisions, reports and items (2026-10-02/03; 0 of 42 items finalized). Two are risks for B's custody witnesses, not practices: trading 0015's residual (an outside-RTH exit keeps repricing past 09:30 with no exclusive handoff) and the outside-PATCH successor fix `89b86b11e9ee6ff7d34ed256679cf15200be7916`.
- **Evidence the archive keeps, by SHA:** the 7 lessons of 2026-11-06 (`lessons.jsonl:131–137`, to append verbatim like the other 130), the W3 exit seed that lessons.jsonl:17 cites at an erased Mac path, the 2026-10-23 and 2026-11-02 Nasdaq symbol directories, the 9e4r and 3gy7 exit replays with their trial rows, the Mac's trial ledgers, the paper captures (B 9.3 MB, IBKR 777 MB), the K2 ∪ K3 corpus manifest (its tapes lie outside git), the 2026-10-29 gainers attribution and the TRADE LEAD's scorecards.

Not verified: the unopened branch contents, the corpus tapes' survival, and every claim that rests on a #968 comment.
- **Archived and kept locally.** The owner archived all five repos at 2026-11-07 17:16Z, after this read; the pins above still resolve. The fourteen evidence items are also copied, by commit and path, to `~/sextant-data/harvest-final/evidence/` (2,991 files, 894 MB; `SHA256SUMS` `20473155aa18b5c1…`, provenance in `PROVENANCE.tsv`).

## Recorded, not adopted

- **Practice notes of 2026-11-06** (harness 0045/0048/0016, trading 0005/0012/0014/0016). Each says "Not reviewed yet", so none has convergence. The research-leg lessons in harness 0045 ("read means read whole", "an absence needs its writer") are worth a reviewed handbook PR. The trading 0005 lesson, read a node's journal over the whole window and never a last-N tail, is too.
- **Old paper scorecard,** trading 0016's note: to 2026-11-05, A 200,000.00 → 136,229.34, B 1,000,000.00 → 866,069.38, C 238,225.19 → 212,879.38. 77% of the loss predates the first Alpaca rows, and no gate produced a number for `premarket_gap`. Negative evidence for the focus, kept as such; it validates no Sextant rule.

## Measured today

- Nasdaq trade-halt RSS, `https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts`, 2026-11-06 15:36Z: `<ttl>1</ttl>`; `ndaq:Market` NASDAQ 37, Non NASDAQ 4, NYSE 2, NYSE Arca 1. Guidance page `Trader.aspx?id=TradeHaltRSS`: "Data is updated, each trading day once a minute. Please do not query the data more than once a minute."
- Alpaca, [Orders at Alpaca](https://docs.alpaca.markets/docs/orders-at-alpaca), read 2026-11-06: "Only limit orders with time_in_force set to day or gtc orders are accepted as extended hours eligible. All other order types and TIF values will be rejected with an error."
- NautilusTrader `v2.0.0rc8` (tag object `5531cca5`, commit `d53849b216e20f2c122ca01b4dd0da377638b186`, prerelease, 2026-10-29) release notes: "Changed emulated releases to undergo risk checks; use `REDUCING` for eligible exits, as `HALTED` denies stops".

## Not verified

- The old records' own internal receipts (PR comments, beads, private tapes); quoted as their records state them.
- Whether every finalized-harness verdict still matches its upstream today; only the three adopted claims were re-measured.
- No old-lane service was contacted; no trading result was rerun.
