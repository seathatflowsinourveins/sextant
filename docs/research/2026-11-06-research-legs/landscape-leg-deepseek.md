# Sextant landscape screen — DeepSeek leg (blind), 2026-11-06

Read dates below are 2026-11-06 unless noted. Local Sextant facts read from /home/sextant/orca/workspaces/sextant/lane-research docs/manifest.md, docs/adr/*, src/ (facts only). The historical /home/choreo and /mnt/wsl inputs were not accessed (unavailable per task). `/tmp/sextant-research-54/owner-stars.tsv` and `/tmp/sextant-research-54/blind-max.yml` are **absent**; stars refreshed from GitHub via `gh api user/starred --paginate` (387 rows, 2026-11-06) and the effort check was done from the installed launcher package schema (section 8).

## 0. Screen accounting
Screened: all 387 refreshed owner stars against all 11 jobs. Rated relevant (USE/REF/WATCH): 94 rows in §2. Rejected as not relevant to this focus: 293 (UI/design skills, iOS, browser tools, LLM inference, speech, photo/media, general awesome lists, misc). No delta versus the 2026-11-05 snapshot is computable: the given TSV file was not delivered; the fresh list is the only inventory.

## 1. Jobs

### Job 1 — Whole-market live scan
- **Pick: Alpaca Algo Trader Plus (ATP), already owned.** Verified upstream (docs.alpaca.markets/us/docs/about-market-data-api): CTA+UTP-fed SIP, "all US stock exchanges" (vs Basic: IEX only), unlimited WebSocket symbol subscriptions, 10,000 historical calls/min, history since 2016, $99/month list; owner dashboard says $0 billed (house fact, ADR-0013). Sessions verified (docs.alpaca.markets/us/docs/245-trading-for-trading-api): pre 04:00–09:30, RTH 09:30–16:00, after-hours 16:00–20:00 ET; overnight 20:00–04:00 ET runs on BOATS (Blue Ocean ATS) for all NMS securities, ATP live overnight data via `feed=boats` (bars/quotes/trades/snapshots; free plan is 15-min delayed overnight); overnight orders limit-only, day/gtc. Options: OPRA feed on ATP, WS limit 1000 quotes. Latency: not published by vendor; house target is ~1 s full-market discovery (ADR-0003 K7). ATP connection-count limits remain unverified.
- **Runner-up: Massive (formerly Polygon.io).** massive.com/landing/free-stock-data (read today): free tier 5 req/min no card; 32K+ active AND delisted US tickers, 23+ yrs nanosecond ticks, 55+ venues, 100% volume; flat files via S3 on paid plans; remote MCP (mcp.massive.com). Good as a second-source/validation feed; paid-plan prices not read this run.
- **Rejected:** IEX Cloud (single venue, not whole-market); TradingView screeners (deepentropy/tvscreener, shner-elmo/TradingView-Screener, Mathieu2301/TradingView-API: unofficial scraping of TV's private endpoints, ToS risk, no latency claim); Benzinga (news, not a trade feed; direct price is sales-quoted, $99/mo per dataset only via Massive reseller per aifinhub.io 2026-10); dxFeed (multi-ATS/depth, unselected need-scoped per ADR-0013); IBKR market data (50 req/s cap shared with orders, ADR-0009).
- **Buy/sign up:** nothing new; keep ATP. Optional free Massive API key for cross-checks.

### Job 2 — Historical extreme movers
- **House seed (start point only):** owner's extreme-gainer package, release seed-research-2026-10-09 (SHA-256 f581ca7f…, local src/sextant/research/candidate_history.py): 957 gainers / 215 selected losers, 2021–2026, weekly leaders 2021–23 vs daily 2024–2026-09; grand-rank top100 (test AUC 0.986/0.989, top-100 T+20 −6.22% on 55 obs); NOT whole-market PIT; survivorship/missingness audited, `survivor_only: true` until a delisted master is bought (ADR-0027, ADR-0013).
- **Pick for delisted-inclusive multi-year daily: Norgate Data US Stocks Platinum** (norgatedata.com/stockmarketpackages.php, read today): delisted securities and historical index constituents back to 1990, active-listed back to 1950 (Diamond), daily bars + fundamentals; 12-month USD 630 (Platinum) / 787.50 (Diamond). Intraday for US stocks not claimed on that page.
- **Runner-up: Massive flat files** (free-tier API is rate-limited; flat-file browser on paid plans; includes delisted, nanosecond ticks since 2003) or owned **Sharadar** ($199/yr per ADR-0013, delisted included in Equity Prices; vendor price page not re-read).
- **Rejected:** Alpaca historical (since 2016; delisted-symbol availability unverified — does not meet "delisted names" need); Databento equities (Nautilus adapter stable, but equities dataset start dates/cost unread this run — unverified); CRSP (academic licensing/price, overkill); Kaggle/unofficial dumps (licence/quality).
- **Buy:** Norgate Platinum $630/yr (or Diamond $787.50/yr) to end survivorship-only; else Massive paid plan for flat files.

### Job 3 — Ranking and early detection
- **Pick: house K2 score (owner ruling), no upstream equivalent exists.** ADR-0003: `move × dvol_ratio` vs own time-matched segment baseline, ties by trades-acceleration; K3 onset (short-window dollar volume + prints + move-off-quiet + rising); K3b accumulation (abnormal blocks, condition-F sweeps at/above ask, exchange-D TRF prints, buy-sell classified flow, time-at/above VWAP). ADR-0003's source record explicitly says "none exists" upstream for a mover-times-volume scorer; my screen agrees — every repo found is infra or a qualitative agent, not a ranked early-mover detector.
- **Runner-up: vectorbt** (research engine; licence Apache-2.0 + Commons Clause, NOASSERTION — non-commercial reuse inside the owner's private research is fine, but selling vectorbt-derived services is barred) for hypothesis tests; **qlib v0.9.8** (MIT) for factor/ML pipelines.
- **Evidence papers:** Zarattini–Barbon–Aziz 2024 "A Profitable Day Trading Strategy for the U.S. Equity Market" (SSRN 4729284; opening-range intraday momentum — house uses it as the RTH reference, premarket adaptation explicitly unvalidated, ADR-0024); Cont–Kukanov–Stoikov 2014 (OFI); Avellaneda–Lee 2010; Lee–Ready 1991 (trade classification, DOI verified); Pan–Poteshman 2006 (option volume informs prices, verified; effect reverses in 1–2 days); McLean–Pontiff 2016 (post-publication decay — house prior). Stated limits: all are academic samples, none delivers a pre-move whole-market ranker with after-cost OOS edge.
- **Rejected:** TradingAgents/AI agents (thesis generation, not ranking); ai-hedge-fund (LLM workflow, no measured edge); FinRL-Trading (RL infra); MiroFish (unsubstantiated "predict anything"); Kronos/timesfm (references only; no mover-task evidence); Hikyuu/abu/rqalpha (China-market orientation).

### Job 4 — Exits and gain protection
- **Negative evidence first (house replays, harvested ADR-0025):** on 1,025 paired entries, hold-to-15:55 beat **all 96 active exit variants** (+76.44 vs +54.78 bps/trade at 3 bps/side; +70.42 vs +48.76 at 6; the momentum/VWAP overlay lost 38.09 bps/trade); Nov-3 study: zero qualified cost-calibrated tick opportunities, all six minute-approximations (C5, 100-bp ratchet, Wilder SAR, halt-aware C5, published tiers) tie negatively; no winner supported. I did not re-run these; they are pinned in northstar-trading@8256c16c31dc research records.
- **Published evidence:** Kaminski–Lo 2014 "When do stop-loss rules stop losses?" (DOI verified via Crossref: stop-losses can reduce strategy-level returns at the security level but improve risk-adjusted performance at the portfolio level — not an extreme-mover proof); Han–Zhou–Zhu 2014 "Taming Momentum Crashes: A Simple Stop-Loss Strategy" (SSRN 2407199, verified); Clare et al 2013 (DOI verified). No paper demonstrates an after-cost optimal tight trail for extreme movers.
- **Maintained code:** NautilusTrader v2 (rc8) order emulation — trailing stops that activate at market and price from first update (rc8/1.231 release notes), OCO/OUO/OTO contingency, modify-on-the-fly; vectorbt trailing-stop studies; backtesting.py (AGPL-3.0, maintained). House X2–X6 policy (buffer/gain-lock/never-loosen trigger, persisted-breach X4, dynamic chased LIMIT X5, native backstop X6) is a house ruling with every parameter UNCALIBRATED (ADR-0005).
- **Pick:** Nautilus emulation/native bracket as mechanism + house X2–X6 as policy, tested against hold-flat as control. **Runner-up:** Chandelier (StockCharts definition; kept as counterfactual arm). **Rejected:** Wilder SAR (tied negatively), published "optimal stop" heuristics (no OOS after-cost winner), fixed-at-entry targets (counterfactual only).
- **Buy:** nothing; keep the 1,025-entry replay discipline.

### Job 5 — NautilusTrader engine
Latest prerelease **v2.0.0rc8** (2026-10-29); latest stable **v1.231.0** (2026-08-02, final 1.x; develop is v2-only). House pin is v2.0.0rc7 @55c0e820 (manifest). Verified at the rc8 tag tree and README@develop.
- **Adapters (rc8 crates/adapters):** architect_ax, betfair, binance, blockchain, bybit, coinapi, coinbase, databento, deribit, derive, dydx, hyperliquid, interactive_brokers, kraken, lighter, okx, polymarket, sandbox, tardis. **No Alpaca adapter exists in v2** (0 alpaca paths at rc8; README integration table lists none) — house pairing of rc7 + alpaca-py v0.44.0 (now v0.45.0, Apache-2.0) is the correct shape.
- **Order types:** TIF IOC/FOK/GTC/GTD/DAY/AT_THE_OPEN/AT_THE_CLOSE, contingency OCO/OUO/OTO, post-only/reduce-only/iceberg (README). **Emulation:** OrderEmulator with activate-at-market trailing stops (1.231/rc8 notes). **Exec algorithms:** TWAP (crates/trading/src/algorithm/twap.rs) + Python-subclassable execution algorithms with deny_order (rc8). **Fill models:** Default/BestPrice/OneTickSlippage/Probabilistic/TwoTier/ThreeTier/LimitOrderPartialFill/SizeAware/CompetitionAware/VolumeSensitive/MarketHours (crates/execution/src/models/fill.rs). **Latency models:** LatencyModel trait + StaticLatencyModel etc.; Python-subclassable latency models in rc8. **Data:** Parquet data catalog, SQL (Postgres) schemas, Redis message bus, batched historical requests + `DataActor::request_group` + on_data_response (rc8); order-event schema changed at 1.231 (activation_price, fill info) — old catalogs must be migrated/regenerated. **Sandbox:** crates/adapters/sandbox execution client; rc8 adds custom fee/fill/margin models there and in backtest venues. **Risk:** crates/risk engine (configs incl. bypass — Sextant's thin slice uses bypass). **Portfolio/tearsheets:** portfolio statistics incl. skew/kurtosis, up/down capture, Ulcer, Omega, VaR, ES, tail ratio (1.231 notes); tearsheets accept BacktestResult (1.231 notes). rc7→rc8 headline adds: batched subs/requests, request_group, embedded Python strategies/algorithms, custom Python latency/fill/margin models, IBKR base currency + max_reconnect_attempts, Decimal money round-trips, sandbox custom fee models.
- **Usage table (searched code counts are on northstar-trading's default branch index, not the pinned commit — flagged):** see §4.
- **Replaces local code:** rc8 request_group/on_data_response and batched historical requests replace the house pagination loops (alpaca_history.py 293 lines); OrderEmulator/trailing-stop activation replaces the house outside-RTH trailing emulation; TWAP replaces any hand-rolled slicing; RiskEngine replaces house pacing risk layers (not the lane pacer itself).
- **Other engines worth a role:** QuantConnect/Lean (Apache-2.0; C#/Python, broad US broker/data coverage, cloud or self-host) as the second engine for parity-of-results; vectorbt for vectorized research. **"Parity/sweeps":** no sweep feature exists in Nautilus v2 (tree grep = 0); paritytrading/parity (498★) is a dead (last push 2022-02) NASDAQ matching-engine concept repo, not an engine candidate; sweep detection is covered as a house accumulation input (ADR-0003 K3b condition-F sweeps), not by any upstream engine.

### Job 6 — Research lane
- **Pick: edgartools v5.62.1** (MIT; verified tag) as ADOPT-PART for EDGAR documents/parsers behind raw bytes (ADR-0003 K4) + **TradingAgents v0.7.1** (Apache-2.0; tag and commit c4544913 verified) as forward-only qualitative thesis generator, never signal/order path (ADR-0015).
- **Runner-up: gpt-researcher** (Apache-2.0) / **alphaXiv/OpenResearch** (MIT) for autonomous research loops; **virattt/dexter** (deep financial research agent; no licence file — flagged).
- **Rejected:** ai-hedge-fund (MIT; typed direction/strength contract only, no measured edge); HKUDS Vibe-Trading/AI-Trader (no evidence, agent-native marketing); OpenAlice; FinRL-Trading (RL infra, not research lane); MiroThinker (stale since 2026-07); daily_stock_analysis (Chinese multi-market); FinceptTerminal (no licence); ai-berkshire (value-investing framing, wrong focus). News/catalyst: Alpaca news WS (no Benzinga) stays primary per ADR-0013; Benzinga direct remains the owner's first timed trial (sales-quoted).
- **Buy/sign up:** Exa key (already shelf), optional Firecrawl/Context7 keys; nothing mandatory.

### Job 7 — Jev and typed trading judgments
- **Pick: typesafe-sdk-python v0.7.5 (MIT, latest release verified) against Jev 1.14** (`jev-1.14.0`, current since 2026-10-14; also jev-1.13.0). Verified at docs.typesafe.ai/models: question types Choice, Score, Noul (+Box in 1.14), POST /v1/systemone, $42 per billion input tokens (output free), 64k request / 32k per-question context. House scope (ADR-0017): paired ON/OFF sim arm, entry-screen-only authority, paper-only inference key, defaults OFF; six catalyst thresholds UNCALIBRATED.
- **Runner-up: typesafe-ai/skills v0.6.2** (verified tag) as the agent skill for Jev questions.
- **Comparable (all lack trading evidence):** TradingAgents v0.7.1 post_screen Noul/Choice screen (house adapted to an event-polarity question, ADR-0017 J3); ai-hedge-fund typed direction/strength; dexter claim rubric.
- **Rejected:** jarrodwatts/jev-trader (crypto Monad/Kuru bot, mock latency, no house authority); Jevinik, bot-derby (evaluated in the northstar Jev sweep, not adopted).
- **Negative evidence:** the owner package's Jev Stage-0 replay: 1,172 events, ECE 0.275, fade ratio 1.80× (<2.0×), NOT CLEARED (2/4 bars), advisory-only (ADR-0027). Training cutoff, real-service latency, calibrated thresholds, after-cost lift: unverified.

### Job 8 — Skills
- **Pick: tradermonty/claude-trading-skills @d8e71ce2f0b069eb5b6fca352857c168c35e6c46** (verified commit, 2026-11-02): backtest-expert, edge-strategy-designer, edge-strategy-reviewer, pre-trade-discipline-gate, trader-memory-core, signal-postmortem, options-strategy-advisor → research, validation, ranking, exit, options lanes.
- **Runner-ups:** typesafe-ai/skills v0.6.2 (Jev lane); EveryInc/compound-engineering-plugin @7dc50943 (verified) ce-compound + ce-bakeoff (memory/compounding + research method); obra/superpowers v7.0.2 @22f0b463 (verified, general methodology).
- **Catalogues to harvest from (never install wholesale — never-bloat rule):** VoltAgent/awesome-agent-skills, sickn33/agentic-awesome-skills, VoltAgent/awesome-codex-subagents, ComposioHQ/awesome-claude-skills, K-Dense-AI/scientific-agent-skills, Imbad0202/academic-research-skills, uditgoenka/autoresearch, wanshuiyin/ARIS (house J4 dissent: ARIS-Code v0.4.28), mvanhorn/last30days-skill, cloudflare/security-audit-skill, promptfoo (validation/red-team), agentskills/agentskills (spec), modelcontextprotocol/servers.
- **Rejected:** affaan-m/ECC v2.2.3 (68 agents/293 skills/94 commands — conflicts with never-bloat; house WATCH), revfactory/harness, agency-agents, phuryn/pm-skills, hallmark/taste/ui skills (off-focus).

### Job 9 — Memory, RAG, compounding
- **Pick: OpenViking v0.5.3** (AGPL-3.0; verified tag; viking:// context DB with L0/L1/L2 summaries; vendor benchmark claims LoCoMo 80–83% vs 24–57% native and tau2-bench +6.87/+11.87pp; MCP + hooks) as local, disposable-copy research retrieval only, per ADR-0022: write-capable, synthesis opt-in only, never blind-leg default, no automatic capture. Canonical records stay in git + GitHub Issues; paper fills/trial ledger/merit on the ledger branch.
- **Runner-up: mem0** (Apache-2.0) or **cognee** (Apache-2.0) if a separate agent-memory layer is ever proven needed.
- **Rejected:** beads (MIT; old baseline, superseded by the approved plan), RAGFlow (heavy platform), WeKnora (retrieve-only service, scoped), RAG-Anything/Graphify/PageIndex/GitNexus (vector/RAG re-inventions overlapping OpenViking), claude-mem/supermemory/hindsight/EverOS/obsidian-* (agent-session memory, not trading-record authority; hindsight WATCH), TencentDB-Agent-Memory (team hub), supabase/turso (only if SQL serving need is proven; DuckDB serves the catalog per ADR-0013).
- **Compounding:** EveryInc ce-compound (skill) + issue-tracked lessons + ADR harvests; OpenViking index rebuilt from the repo.

### Job 10 — Engines and hosting
- **Pick (current house stack, verified pins):** trailofbits/claude-code-devcontainer @062e9e77 (Apache-2.0) devcontainer on WSL + Orca v1.4.251 (verified release) worktrees + gh actions (scoreboard/review) + systemd units + Docker Compose; just/mise task runners. This matches "Windows workstation with WSL now, Mac later" — both run the same devcontainer.
- **Runner-up additions:** Prefect (workflow orchestration, research pipelines) or flyte; n8n for owner-facing automations; SigNoz (OTel-native) or PostHog for observability if Grafana-style dashboards become needed; restic for backups.
- **VPS justified when:** 24/5 paper (later live) needs an always-on node with a stable clock/NTP, no workstation sleep, and a private network for broker connections — the house trigger row is exactly that (self-hosted actions/runner @v2.338.2 on "a machine with no other campaign", manifest). Research/sim 24/7 can run on the workstation + WSL + GitHub Actions until then.
- **Rejected:** Kubernetes (solo-owner overhead), OpenHands/Archon/deer-flow/ruflo/hermes-agent/OpenHarness/omnigent/open-multi-agent (agent-harness bloat duplicating dsh/Claude/Codex runtimes), GPU self-hosting stacks (TensorFold/ktransformers/unsloth/spark-vllm) unless a local model need is proven (Ollama preferred per ADR-0022).

### Job 11 — Beyond
- **Options:** ATP OPRA live + historical trades/bars since 2024-02, no historical quotes (ADR-0013); options stay a zero-weight research factor with sim only; rc7 option expiry lacks early exercise/assignment and buying-power checks (ADR-0016). Massive options flat files are the OOS dataset candidate when options leave zero weight.
- **MCP inventory already on the shelf (manifest):** Context7 4.5.0, Exa 3.4.3, DeepWiki (keyless), paper-search, Playwright 0.0.84, CodeGraph 1.6.2; plus Massive remote MCP (mcp.massive.com) and alpaca-mcp v2 as read-only candidates — broker-touching MCPs must stay out of agent lanes per the no-order-tools rule (ADR-0015).
- **Corporate actions/security master:** Databento corporate-actions + security master endpoints; Massive ticker universe (32k+ incl. delisted) as the dated master candidate that ends survivor-only.
- **Not found anywhere upstream:** a whole-market mover ranker, a sweeps engine, or an exit policy with OOS after-cost evidence — the house must keep its policies as owner rulings + measurements (the NEVER-SELF-INVENT rule is satisfied by citing what does not exist).

## 2. Owner-star relevance table (94 of 387)
Verdicts: USE (in stack/plan), REF (reference/candidate), WATCH (house watching), NO (rejected — included only where the screen made a call). Job = primary job.

| Repo | Job | Verdict | Reason (one line) |
|---|---|---|---|
| alpacahq/alpaca-py | 1,5 | USE | Official SDK, Apache-2.0, v0.45.0; feed+execution client beside Nautilus (no Alpaca adapter in Nautilus v2). |
| deepentropy/tvscreener | 1,8 | REF | TradingView screener API wrapper (unofficial); candidate research/display tool, not a data feed. |
| shner-elmo/TradingView-Screener | 1,3 | REF | Python TV screener package; same unofficial caveat. |
| Mathieu2301/TradingView-API | 1 | REF | TV data scraping; ToS risk. |
| atilaahmettaner/tradingview-mcp | 1,8 | REF | TV MCP (screeners, multi-timeframe); display/research lane only. |
| tradesdontlie/tradingview-mcp | 8 | REF | TV chart analysis MCP for Claude; lane-tradingview candidate. |
| Open-Dev-Society/OpenStock | 1,6 | NO | Free data alternative; redundant with ATP, no edge evidence. |
| akfamily/akshare | 2 | NO | China-market data lib; wrong region. |
| nautechsystems/nautilus_trader | 5 | USE | House engine pin rc7; rc8 read this run (LGPL-3.0). |
| QuantConnect/Lean | 5 | REF | Second engine for parity-of-results; Apache-2.0, broad broker/data coverage. |
| polakowo/vectorbt | 3,4 | REF | Vectorized research engine; Apache-2.0 + Commons Clause. |
| microsoft/qlib | 3 | REF | MIT factor/ML pipeline; v0.9.8 reference (ADR-0015). |
| kernc/backtesting.py | 4 | REF | AGPL-3.0 event backtester; small, maintained. |
| StockSharp/StockSharp | 5 | NO | C#/.NET platform; wrong stack for this repo. |
| Lumiwealth/lumibot | 5 | NO | GPL-3.0; broker facade, weaker replay than Nautilus. |
| coding-kitties/investing-algorithm-framework | 5 | NO | Unmaintained-style framework; superseded. |
| fasiondog/hikyuu | 3,5 | NO | C++/China-oriented; heavy, no mover evidence. |
| ricequant/rqalpha | 5 | NO | China-market framework. |
| bbfamily/abu | 3 | NO | Legacy China quant. |
| whchien/ai-trader | 5 | NO | Backtrader wrapper; stale. |
| asavinov/intelligent-trading-bot | 6 | NO | Signal-gen sketches; no evidence. |
| AI4Finance-Foundation/FinRL-Trading | 3 | REF | RL infra for later experiments; no mover result. |
| stefan-jansen/machine-learning-for-trading | 3,6 | REF | MIT book code; data/microstructure recipes. |
| paperswithbacktest/awesome-systematic-trading | 3,4 | REF | Curated list for method hunting. |
| wangzhe3224/awesome-systematic-trading | 3 | REF | Second curated list. |
| wilsonfreitas/awesome-quant | 3,6 | REF | Third curated list. |
| TauricResearch/TradingAgents | 6,7 | USE | Apache-2.0 v0.7.1; forward-only thesis generator + post_screen Noul/Choice (house adaptation). |
| virattt/ai-hedge-fund | 6,7 | REF | MIT; typed direction/strength contract, no measured edge. |
| virattt/dexter | 6,7 | REF | Deep financial research agent; no licence file (flagged). |
| dgunning/edgartools | 6 | USE | MIT v5.62.1; ADOPT-PART SEC documents/parsers (ADR-0003). |
| jarrodwatts/jev-trader | 7 | NO | Crypto Monad Jev bot; no house authority. |
| HKUDS/Vibe-Trading | 6,7 | NO | Agent-native marketing, no evidence. |
| HKUDS/AI-Trader | 6 | NO | Same, no evidence. |
| TraderAlice/OpenAlice | 6 | NO | "One-person Wall Street" narrative; no measured merit. |
| NoFxAiOS/nofx | 6 | NO | AI terminal assistant; no edge evidence. |
| ZhuLinsen/daily_stock_analysis | 6 | NO | Chinese multi-market dashboard. |
| Fincept-Corporation/FinceptTerminal | 11 | NO | C++ terminal, no licence. |
| tradermonty/claude-trading-skills | 8 | USE | 7 skills @d8e71ce verbatim on the Claude shelf. |
| typesafe-ai/skills | 7,8 | USE | v0.6.2 skill for Jev judgments. |
| EveryInc/compound-engineering-plugin | 8,9 | USE | ce-compound + ce-bakeoff @7dc50943. |
| obra/superpowers | 8 | USE | v7.0.2 @22f0b463 general methodology. |
| agentskills/agentskills | 8 | USE | Agent Skills spec. |
| VoltAgent/awesome-agent-skills | 8 | REF | 1000+ skills catalogue (harvest only). |
| sickn33/agentic-awesome-skills | 8 | REF | 2,926+ skills catalogue. |
| VoltAgent/awesome-codex-subagents | 8 | REF | 130+ subagent catalogue. |
| ComposioHQ/awesome-claude-skills | 8 | REF | Skills catalogue. |
| K-Dense-AI/scientific-agent-skills | 6,8 | REF | AI-scientist skills. |
| Imbad0202/academic-research-skills | 6,8 | REF | Research→write→review skills. |
| uditgoenka/autoresearch | 6,8 | REF | Autonomous research skill. |
| wanshuiyin/Auto-claude-code-research-in-sleep | 6,8 | REF | ARIS (house J4 dissent, dsh support unevidenced). |
| karpathy/autoresearch | 6 | REF | Research loops reference. |
| mvanhorn/last30days-skill | 6,8 | REF | Reddit/X/HN research skill. |
| cloudflare/security-audit-skill | 8 | REF | Validation/security audits. |
| promptfoo/promptfoo | 8 | REF | Prompt/agent/RAG evals for validation lane. |
| affaan-m/ECC | 8 | WATCH | 68 agents/293 skills/94 commands — conflicts with never-bloat. |
| volcengine/OpenViking | 9 | USE | v0.5.3 AGPL-3.0; disposable-copy research retrieval. |
| mem0ai/mem0 | 9 | REF | Apache-2.0 memory layer if proven needed. |
| topoteretes/cognee | 9 | REF | Apache-2.0 memory platform. |
| vectorize-io/hindsight | 9 | WATCH | Agent memory that learns; house trigger. |
| Tencent/WeKnora | 9 | REF | Retrieve-only knowledge service (scoped). |
| infiniflow/ragflow | 9 | NO | Heavy platform; overlaps OpenViking. |
| HKUDS/RAG-Anything | 9 | NO | Another RAG framework; bloat. |
| gastownhall/beads | 9 | NO | Superseded old baseline. |
| colbymchenry/codegraph | 9 | USE | CodeGraph 1.6.2 MCP on shelf. |
| oraios/serena | 9 | REF | Semantic code toolkit alternative. |
| yamadashy/repomix | 9 | REF | Repo packing for retrieval. |
| stablyai/orca | 10 | USE | v1.4.251; worktrees + agent fleet. |
| deepseek-ai/deepseek-harness | 10 | USE | dsh 0.2.2-rc.1 runtime. |
| PrefectHQ/prefect | 10 | REF | Research pipeline orchestration. |
| flyteorg/flyte | 10 | REF | Type-safe orchestration alternative. |
| n8n-io/n8n | 10 | REF | Owner automations. |
| SigNoz/signoz | 10 | REF | OTel observability if needed. |
| PostHog/posthog | 10 | REF | Product analytics alternative. |
| restic/restic | 10 | REF | Backups. |
| ollama/ollama | 9,10 | REF | Preferred local LLM per ADR-0022. |
| browser-use/browser-use | 6 | REF | Browser research agent. |
| firecrawl/firecrawl-mcp-server | 6 | USE | On shelf; web research fetch. |
| unclecode/crawl4ai | 6 | REF | Scraping fallback. |
| assafelovic/gpt-researcher | 6 | REF | Deep-research agent. |
| alphaXiv/OpenResearch | 6 | REF | MIT; research agents. |
| LearningCircuit/local-deep-research | 6 | REF | Local research agent. |
| MiroMindAI/MiroThinker | 6 | REF | Deep research agent (stale 2026-07). |
| koala73/worldmonitor | 6 | REF | AGPL-3.0 news dashboard (news is Alpaca-primary). |
| microsoft/markitdown | 6 | REF | Doc→Markdown for filings/news. |
| xerj-org/xerj | 6 | REF | AI search MCP. |
| modelcontextprotocol/modelcontextprotocol | 8,10 | USE | MCP specification (harness fabric). |
| modelcontextprotocol/servers | 8 | USE | MCP reference servers. |
| pola-rs/polars | 2,10 | USE | DataFrame layer (house stack). |
| ClickHouse/ClickHouse | 2,10 | REF | Only if scan-I/O needs prove it; heavy. |
| comet-ml/opik | 11 | REF | LLM eval/observability. |
| shiyu-coder/Kronos | 3 | REF | Financial-market foundation model (reference only). |
| google-research/timesfm | 3 | REF | Time-series foundation model (reference only). |
| jarrodwatts/claude-hud | 10 | WATCH | House trigger: measured need only. |
| mksglu/context-mode | 10 | WATCH | House trigger: measured need only. |

## 3. NautilusTrader feature table
Now = lane-research src (thin_slice.py/ema_cross.py per manifest row 26); Old = northstar-trading@8256c16c31dc (code-search counts on default-branch index, flagged; ADR-0013/0009 rows).

| Feature | Sextant now | Old code | Unused | This focus needs it |
|---|---|---|---|---|
| BacktestEngine (multi-venue, tick/bar/book) | USE (thin slice) | USE (via BacktestNode) | — | Yes: replay core |
| BacktestNode (batched windows) | no | USE | yes | Yes in Phase 4 (windows/repeats) |
| RiskEngine | USE (bypass) | USE (58 hits) | — | Yes: pre-trade limits at paper |
| MakerTakerFeeModel | USE | USE | — | Yes: cost honesty |
| Tearsheets (BacktestResult) | USE (create_tearsheet) | 0 hits | — | Yes: merit pages |
| OrderMatchingEngine (deterministic fills) | implicit via BacktestEngine | USE | — | Yes |
| OrderEmulator / trailing stops | no | USE (15 hits) | — | Yes: outside-RTH protection (X5/B) |
| TWAP + Python exec algorithms | no | no | yes | Marginal now; useful for size scaling |
| Fill models (Probabilistic/CompetitionAware/…) | no | no | yes | Yes for realism in Phase 4 sim |
| Latency models (Static/Python) | no | no | yes | Yes: replay timing fidelity |
| ParquetDataCatalog | no | USE (52 hits) | — | Yes (ADR-0013 one-catalog) |
| SQL persistence/Postgres | no | no | yes | Only if catalog consumer needs it; DuckDB preferred |
| Redis message bus / external streams | no | USE (StreamingConfig 10) | — | Yes at paper/live fan-out |
| DataActor (in-node ranking) | no | USE (10 hits) | — | Yes (ADR-0013 selected in-node) |
| Sandbox adapter (custom fee/fill/margin) | no | no | yes | Yes: 24/7 sim venue |
| Contingency OCO/OUO/OTO | no | no | yes | Yes: venue backstops (X6) |
| Portfolio analytics/statistics | via tearsheet | no | yes | Yes for ledger/merit |
| IBKR adapter (v2, stable) | no | yes (own IB layer) | — | Yes when IBKR paper/live resumes |
| Databento adapter (stable) | no | no | yes | Only if Databento data is bought |
| Alpaca adapter | — | — | does not exist in v2 | Keep alpaca-py beside the engine |

## 4. Claim ledger (load-bearing claims, pinned source, read date 2026-11-06)
1. ATP plan: $99/mo, all US exchanges, unlimited WS symbols, 10k/min, since 2016, CTA+UTP; Basic: IEX only, 30 symbols, 200/min — docs.alpaca.markets/us/docs/about-market-data-api.
2. Alpaca 24/5 sessions 20:00–04:00 BOATS overnight; overnight limit-only day/gtc; ATP `feed=boats` live overnight, free plan 15-min delayed — docs.alpaca.markets/us/docs/245-trading-for-trading-api.
3. Nautilus latest prerelease v2.0.0rc8 (2026-10-29), latest stable v1.231.0 (2026-08-02, final 1.x) — gh api releases.
4. Nautilus v2 has no Alpaca adapter; adapter list at rc8 tree — gh api trees/v2.0.0rc8 (0 alpaca paths).
5. Nautilus features/order types/adapters — README@develop + rc8 release notes (TIF set, OCO/OUO/OTO, post-only/reduce-only/iceberg; TWAP; fill/latency model names from crates/execution/src/models/fill.rs|latency.rs).
6. rc8 adds request_group/batched historical/custom Python latency+fill+margin models — rc8 release notes, Enhancements.
7. vectorbt licence Apache-2.0 + Commons Clause — vectorbt LICENSE.md.
8. Norgate US Platinum: delisted + historical constituents back to 1990, USD 630/12mo — norgatedata.com/stockmarketpackages.php.
9. Massive free tier 5 req/min; 32k+ active+delisted tickers; 23+ yrs nanosecond; flat files on paid plans — massive.com/landing/free-stock-data.
10. Benzinga: no self-serve price; $99/mo per dataset via Massive reseller; 130–160 articles + 600–900 headlines/day, Wilshire 5000 + TSX — aifinhub.io (third-party, 2026-10 verified by them) + benzinga.com product page (via that article).
11. Jev 1.14/1.13, Choice/Score/Noul/Box, $42/Btok input, 64k/32k context, /v1/systemone — docs.typesafe.ai/models.
12. typesafe-sdk-python v0.7.5 (MIT) latest release — gh api releases; typesafe-ai/skills v0.6.2 tag.
13. Papers verified via Crossref DOIs: Kaminski–Lo 2014 (10.1016/j.finmar.2013.07.001); Han–Zhou–Zhu 2014 (SSRN 2407199); Clare et al 2013 (10.1057/jam.2013.11); Lee–Ready 1991 (10.1111/j.1540-6261.1991.tb02683.x); Pan–Poteshman 2006 (10.1093/rfs/hhj024).
14. Zarattini et al 2024 SSRN 4729284 "A Profitable Day Trading Strategy for the U.S. Equity Market" — alexandria.unisg.ch record.
15. OpenViking v0.5.3 AGPL-3.0; LoCoMo 80–83% claim; viking:// + MCP — OpenViking README/tags.
16. Pinned commits exist upstream: northstar b384d298, northstar-trading 8256c16c, northstar-lanes 002032759, tradermonty d8e71ce, superpowers 22f0b463, compound-plugin 7dc50943, trailofbits devcontainer 062e9e77, Orca v1.4.251, TradingAgents c4544913 + v0.7.1, qlib v0.9.8, edgartools v5.62.1 — gh api commit/tag checks.
17. Owner package seed: 957 gainers/215 losers; grand-rank AUC 0.986/0.989; top-100 T+20 −6.22% (55 obs); Jev Stage-0 ECE 0.275, fade 1.80×, NOT CLEARED — ADR-0027 (house archive; I could not open the zip, it is not delivered here).
18. Negative exit replay: hold-15:55 beat all 96 variants, 76.44 vs 54.78 (3bps) and 70.42 vs 48.76 (6bps) bps/trade; overlay −38.09 — ADR-0025 (harvested from northstar-trading@8256c16c31dc; not re-run).
19. paritytrading/parity: 498★, last push 2022-02-09 — gh api.
20. Order-rate limits (owner): Alpaca live 1000/min, paper 200/min, IBKR 3000/min — ADR-0009 (owner ruling; account entitlements unverified).

## 5. Disagreements with start-point records
1. **Owner-stars input missing.** The commissioned fresh inventory /tmp/sextant-research-54/owner-stars.tsv does not exist here; I refreshed via gh api (387 rows) and therefore cannot state what changed vs 2026-11-05 — recorded honestly instead of faking a delta.
2. **Nautilus "latest":** house pin is rc7; the landscape question asks for latest — rc8 (2026-10-29) is the newest prerelease and 1.231.0 the newest stable. House ADR-0013 already flags "bounded synthetic rc8 report, not operational completeness" — rc8's order-event schema changes require catalog migration, so the rc7 pin is defensible for now, but rc8's batched requests + custom Python fill/latency/margin models are exactly what the research lane needs.
3. **Alpaca adapter absence.** The historical brief implies Nautilus + Alpaca connectivity; v2 has no Alpaca adapter (verified at rc8 tree). The house already runs alpaca-py beside the engine — correct and should stay.
4. **"Nautilus feature table vs old code":** my code-search counts (ParquetDataCatalog 52, RiskEngine 58, LiveNode 45, OrderEmulator 15, BacktestNode 12, DataActor 10, StreamingConfig 10, TearsheetModule 0) are from GitHub's default-branch index, not the pinned commit 8256c16c — treat as presence evidence only, not exact-pin inventory.
5. **ATP price vs bill:** vendor lists $99/mo; the owner's dashboard shows $0 billed (ADR-0013 house fact). Both recorded; no contradiction resolved by me.
6. **Jev price/context:** ADR-0017 pins jev-1.14.0 + sdk 0.7.5 (verified); upstream now also documents $42/Btok input pricing and Box question type (1.14) — new facts to carry into the Jev ADR.
7. **Research-package reach:** ADR-0024 says "no committed multi-year daily-candidate dataset" and ADR-0027 says the package IS a multi-year (selected) movers list; the correct reading is the package is multi-year but selected/survivorship-incomplete, not whole-market PIT — my Job 2 pick addresses the gap with Norgate/Massive rather than treating the zip as the dataset.
8. **ADRs 0013/0009 "unverified" marks:** ATP connection limits, Alpaca live 1000/min entitlement, overnight wildcard semantics remain unverified — I confirm no public vendor page settles them this run.

## 6. Unverified / could not verify
- /tmp/sextant-research-54/blind-max.yml (absent; effort verified from installed package schema instead — §7).
- The owner-stars.tsv delta vs 2026-11-05 (file absent).
- Alpaca: ATP WS connection limits; per-account live 1000/min (Pro Line) entitlement; SIP history premarket coverage since 2016; feed latency (vendor publishes none).
- Massive: paid-plan prices; flat-file cost.
- Databento: equities dataset names/start dates/cost (page JS-rendered; only Nautilus adapter stability verified).
- Benzinga direct pricing (sales-quoted; reseller price is third-party).
- TradingView unofficial APIs' ToS status.
- Norgate: whether US-stock intraday bars exist (page shows daily extent).
- Northstar code-search counts are default-branch index, not the pin.
- The owner package zip itself is not delivered here; package facts are from ADR-0027/local src only.
- House exit/ranking replays were not re-run; negative results are harvested claims.
- OpenViking benchmark numbers (vendor's own report, not independently reproduced).

## 7. Harness, version, model, effort (as read from this session)
- Launcher: dsh **0.2.2-rc.1** (@deepseek-ai/dsh, version read from installed package.json at /home/sextant/.local/share/sextant-agents/node_modules/@deepseek-ai/dsh/package.json; `dsh --version` = 0.2.2-rc.1).
- Model: **deepseek-v4-pro** (session runtime context), DeepSeek API-key provider (session diagnostics.log: "[llm-deepseek-api-key] model listing from https://api.deepseek.com/models loaded 2 model(s)").
- Effort: **max** — installed provider schema @deepseek-ai/dsh-llm-deepseek-api-key/lib/types/config.d.ts declares `reasoningEffort: z<"low" | "off" | "high" | "max", …>`; `max` is the schema's highest value. The commissioned patch file /tmp/sextant-research-54/blind-max.yml was absent, so the patch itself is unverified; the schema ceiling and the session's stated max effort are what I can attest.
- No credential/config store was read (DSH_HOME profile files untouched); environment variable **names** only via `compgen -e`: BROWSER, CODEX_*, DSH_HOME, DSH_PROFILE, DSH_PROFILE_DIR, DSH_SESSION_ID, DSH_SHELL, GH_PAGER, GIT_*, HOME, ORCA_*, PATH, TERM, USER, XDG_* etc.
- Work style: single process, no subagents, no subprocess model calls; evidence gathered from gh api, Crossref, vendor docs, and the local manifest/ADRs/src only.
