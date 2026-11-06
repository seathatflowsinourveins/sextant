# Sextant #54 — DeepSeek leg — JOB 1: AGENT MEMORY
Date of research: 2026-11-06. Scope: job 1 only (automatic capture + recall across Claude Code, Codex, dsh; GitHub as sole cross-device transport; no glue layer). Retrieval/compounding deliberately not decided.

## 0. Harness verification (as read from my own session)
- `dsh --version` → 0.2.2-rc.1 (read 2026-11-06). Launcher "dsh" = DeepSeek Harness, package tree under ~/.local/share/sextant-agents/node_modules/@deepseek-ai/dsh-*.
- Patch /tmp/sextant-research-54/blind-max.yml: provider `deepseek-official`, model `deepseek-v4-pro`, `reasoningEffort: max`; subagent/fork/workflow tools disabled (I worked alone).
- Installed upstream schema @deepseek-ai/dsh-llm-deepseek README.md (installed copy, read 2026-11-06): effort enum is `off | low | high | max`, documented "in increasing effort order"; config.d.ts declares `'off'|'low'|'high'|'max'`. ⇒ max IS the highest supported effort; I am at it.
- Own session log /tmp/sextant-research-54/memory/events.jsonl carries `deepseek-v4-pro` and `deepseek-official`; diagnostics.log shows model listing from api.deepseek.com. No env values printed anywhere; names only via `compgen -e`.
- Relevance for this job: dsh ships @deepseek-ai/dsh-mcp-client (stdio + streamable-http, one entry per server) — dsh can reach any MCP memory server without custom glue.

## 1. Verdict, job 1 (agent memory)
- PICK: zilliztech/memsearch v0.4.23 — the only maintained upstream with first-party automatic capture AND recall for all three runtimes and markdown-in-repo as the native GitHub transport.
- RUNNER-UP: akitaonrails/ai-memory v3.4.2 — first-party for all three too, but cross-device rides its own server (GitHub only as backup mirror) and its DSH wiring is hand-merged patch fragments with no auto recall injection for dsh.
- NONE fully meets the strictest reading ("what a session learned reaches the next session with zero invocation") — memsearch's capture is fully automatic; recall is automatic for Claude Code (cold-start injection) and a recall hint + skill for Codex/dsh. Closest upstream that exists.

## 2. PICK details — zilliztech/memsearch
- Release/SHA: v0.4.23 (published 2026-10-27), commit 65d8b220d4265f70441785aa22203f0e85ea3ec6. Plugin versions: Claude Code 0.4.22, DSH 0.1.8; Codex uses current installer. PyPI memsearch==0.4.23, Python >=3.10. MIT. Org zilliztech (Milvus vendor); repo created 2026-02-09, pushed 2026-11-06, 2824 stars, 259 open issues.
- Install: `uv tool install "memsearch[onnx]"` (or pip/pipx); Claude Code: `/plugin marketplace add zilliztech/memsearch` then `/plugin install memsearch`; Codex: clone repo, `bash plugins/codex/scripts/install.sh` (writes ~/.codex/hooks.json, preserves other hooks); dsh: `dsh plugin --profile <profile> add @zilliz/memsearch-dsh` + restart profile.
- What it adds: every completed turn is summarized into `.memsearch/memory/YYYY-MM-DD.md` (session/turn anchors); Claude Code SessionStart cold-injects up to 40 lines from each of the 2 latest daily logs (automatic recall); Codex SessionStart injects memory-file count/date-range + recall hint; dsh adds a memory-recall reminder before the first model step and registers a native `memory-recall` skill (search → expand → transcript). Optional off-by-default PROJECT.md/USER.md maintenance and skill distillation (not my job to rule on).
- How each runtime reaches it: Claude Code = 4 lifecycle hooks (SessionStart sync 10s, UserPromptSubmit sync 15s, Stop ASYNC 120s — capture does not block the next prompt, SessionEnd async 10s) + memory-recall skill (forked subagent); Codex = 3 hooks (SessionStart sync 30s, UserPromptSubmit sync 10s, Stop ASYNC 30s, no SessionEnd) + skill; dsh = native plugin on session/event notifications, summarization "without blocking the active conversation", serialized capture jobs.
- Storage: memory = markdown in `<project>/.memsearch/memory/` ("Git-friendly. Commit your memory files to version control"); index = derived, rebuildable Milvus Lite file `~/.memsearch/milvus.db` (per device); config `~/.memsearch/config.toml`. L3 transcript anchors hold device-local paths — cross-device L1/L2 recall works from markdown alone; exact transcript drill-down only where the transcript exists.
- GitHub transport: clone → `.memsearch/memory/*.md` present → `memsearch index` rebuilds search. No server, no export step. This is the deciding criterion.
- Footprint: Python CLI + hooks; per-turn LLM summarization by default (Claude Code: `claude -p --model haiku`; Codex: `codex exec -m gpt-5.1-codex-mini`; dsh: one-shot headless agent) = ongoing background LLM cost, disableable (`plugins.<x>.summarize.enabled false`); ONNX bge-m3 ~558 MB one-time download (no API key); Codex needs `codex --yolo` for ONNX network access; no background service in Lite mode. Hook stalling: Stop hooks async; SessionStart/UserPromptSubmit are sync with 10–30 s budgets (can stall startup, bounded); cold index runs backgrounded.
- Portability: pip/uv on Linux/WSL2 (WSL2 explicitly recommended for Milvus Lite) and macOS (macOS Codex temp-file fix in v0.4.23); native Windows best-effort only.
- Risks: young (v0.4.x, Feb 2026); per-turn summarizer spend; per-device index rebuild on clone; user prompts summarized (tool calls/outputs excluded from summarization input, but no redaction layer documented) — memory files contain repo work, must not capture secrets.

## 3. RUNNER-UP — akitaonrails/ai-memory
- v3.4.2 (published 2026-11-05), commit b9453c964e76b3e7591fe79b428048562bdf036c. MIT, Rust single binary, 15261 stars, pushed 2026-11-05. Install: checksum-verified install.sh + `ai-memory setup` (systemd user/launchd service; wires MCP+hooks+skills per agent).
- Strengths: zero-LLM default path (no per-turn cost); sanitized typed capture; git-versioned markdown wiki as source of truth; own LongMemEval-S benchmark (hit@5 0.951 zero-LLM FTS / 0.940 local embeddings, run by maintainers on pinned commit 7bb659ce + dataset sha256; docs/benchmarks/longmemeval-s-3.4.0-release.md).
- Why not pick for THIS criterion set: (a) transport — cross-device = one reachable server (homelab/LAN); its wiki git repo can be pushed to any remote but that path is documented as backup/mirror (docs/backup.md), not live GitHub sync; each device still needs the server + wiring. (b) dsh integration = "Hooks + MCP" but `install-mcp --client dsh` prints a Cordis patch fragment for hand-merge into $DSH_HOME/profiles/<p>/cordis.patch.yml (`--apply` refused), hooks ride a Claude-Code-bridge with only 7 events, SessionStart runs detached ⇒ no automatic handoff injection into dsh (MCP handoff recovery + `ai-memory finalize-session --agent dsh`), and no managed workstream for dsh (support-matrix.md). (c) local HTTP server = second always-on service.

## 4. Rejected (one line each; all repos read 2026-11-06)
- mem0ai/mem0 (Apache-2.0, 68.5k★): per-turn fact-extraction layer + MCP; no first-party auto capture/recall wiring for the three CLIs; no dsh.
- topoteretes/cognee (Apache-2.0, 33.1k★): ECL pipeline library for building memory; nothing automatic installed into Claude Code/Codex/dsh.
- getzep/graphiti (Apache-2.0, 32.6k★): temporal-KG framework, programmatic only; no lifecycle capture for the three CLIs.
- letta-ai/letta (Apache-2.0, 25.4k★): stateful-agent platform/server; not a capture layer for external coding CLIs.
- supermemoryai/supermemory (MIT, 31.6k★): context engine/app with dashboard + self-host; ingestion connectors, not CLI lifecycle capture; not repo-file-native.
- basicmachines-co/basic-memory (AGPL-3.0, 4.5k★): markdown notes via MCP; writes are agent-invoked (no automatic capture); no dsh plugin; AGPL.
- doobidoo/mcp-memory-service (Apache-2.0, 2.1k★): self-hosted REST/MCP knowledge-graph service for pipelines/Claude Desktop/OpenCode; agent-invoked, no capture for the three CLIs.
- rohitg00/agentmemory (Apache-2.0, 30.2k★): local memory server (API :3111, viewer :3113, ~/.agentmemory state) + "12 auto hooks" + MCP incl. a DSH claim; server-based state store, not GitHub-file transport; README-level claims not deeper-verified.
- volcengine/OpenViking (AGPL-3.0, 41.7k★): context database as virtual filesystem; needs server + VLM; own LoCoMo/tau2-bench benchmarks show OpenClaw/Hermes/Claude Code, no Codex/dsh; AGPL.
- vectorize-io/hindsight (MIT, 59.4k★): learning/observability API + MCP, Docker service on :8888; "works with Claude Code, Cursor, and other assistants"; no first-party Codex/dsh; server-based.
- openai/codex-mem → GitHub API 404 (removed). KeystoneScience/codex-mem fork: 11★, no license (NOASSERTION), pushed only 2026-03-07 ⇒ dead lineage. Rejected.
- claude-mem (thedotmack/claude-mem, Apache-2.0, npm 15.10.1): memory compression for Claude Code only.
- Also looked at: Liruns/context-sync-mcp (young, Cursor/CC/Windsurf), commonplace-agent-memory (PyPI), iflow-mcp repackages — none meets the bar. No "none exists" needed: memsearch exists.

## 5. ai-memory README comparison-table claim check (read at main, 2026-11-06)
- TRUE at source: basic-memory = markdown-on-disk ("Your knowledge lives as Markdown files", MCP-native); Graphiti = temporal KG (its own tagline); supermemory = hosted/managed memory API (dashboard + self-host); mcp-memory-service = typed-edge causal knowledge graph with autonomous consolidation (its README); DSH row "Hooks + MCP" (its support-matrix.md, with the hand-merge caveats of §3).
- FALSE: none found outright.
- COULD NOT CHECK: mcp-memory-service "SQLite fact rows / decay curves" specifics; mem0 "opaque fact rows" phrasing; Hindsight/OpenViking "living pages / background consolidation loop" cell details; "zero-LLM by default" beyond README text.

## 6. Claim ledger (claim → pinned source → read 2026-11-06)
- memsearch v0.4.23 latest, 2026-10-27 → api.github.com/repos/zilliztech/memsearch/releases/latest; SHA 65d8b220… → /commits/v0.4.23.
- memsearch MIT, 2824★, created 2026-02-09, pushed 2026-11-06, topics incl. dsh-plugin/deepseek-harness → api.github.com/repos/zilliztech/memsearch.
- memsearch PyPI 0.4.23, >=3.10 → pypi.org/pypi/memsearch/json.
- CC hooks: Start sync10s/UPS sync15s/Stop async120s/End async10s; Stop async non-blocking; cold-start 2×40 lines → zilliztech.github.io/memsearch/platforms/claude-code/how-it-works/.
- Codex hooks: Start sync30s/UPS sync10s/Stop async30s; summarizer gpt-5.1-codex-mini; --yolo for ONNX → …/platforms/codex/how-it-works/.
- DSH: capture from session/event notifications, non-blocking; recall hint pre-first-step; native memory-recall skill; .memsearch per project → …/platforms/dsh/how-it-works/.
- "Commit your memory files to version control", Milvus = rebuildable shadow, ~/.memsearch/milvus.db, WSL2 for Windows → …/claude-code/how-it-works/, getting-started/, faq/.
- ai-memory v3.4.2 latest 2026-11-05, MIT, Rust, 15261★ → api.github.com releases/latest, repo; SHA b9453c96… → /commits/v3.4.2.
- ai-memory DSH = Hooks+MCP, hand-merged cordis.patch.yml, --apply refused, detached SessionStart, finalize-session --agent dsh, no managed workstream → raw…/docs/support-matrix.md.
- ai-memory LongMemEval-S 3.4.0: hit@5 0.951 FTS / 0.940 local; self-run on commit 7bb659ce; dataset sha256 pinned → raw…/docs/benchmarks/longmemeval-s-3.4.0-release.md.
- ai-memory wiki is a git repo pushable to any remote; mirror = backup layer → raw…/docs/backup.md.
- Candidate licenses/stars/pushed_at → api.github.com/repos/{mem0ai/mem0, topoteretes/cognee, letta-ai/letta, getzep/graphiti, doobidoo/mcp-memory-service, basicmachines-co/basic-memory, supermemoryai/supermemory, rohitg00/agentmemory, volcengine/OpenViking, vectorize-io/hindsight, KeystoneScience/codex-mem}; openai/codex-mem → 404.
- claude-mem npm 15.10.1, repo thedotmack/claude-mem, Apache-2.0 → registry.npmjs.org/claude-mem.
- dsh 0.2.2-rc.1 → `dsh --version`; effort enum off|low|high|max, increasing order, max highest → installed @deepseek-ai/dsh-llm-deepseek README.md + lib/types/config.d.ts; patch values → /tmp/sextant-research-54/blind-max.yml; session model/provider → /tmp/sextant-research-54/memory/events.jsonl (grep only); dsh MCP client stdio/streamable-http → installed @deepseek-ai/dsh-mcp-client README.md.

## 7. Unverified / risks
- No install or end-to-end run by me (task forbids local installation and runtime changes; all facts are documentation-level).
- memsearch: no third-party benchmark found; own evaluations (embedding/reranking) not read in full; per-turn summarizer token cost unmeasured; sync-hook stall risk at cold index unmeasured; two devices writing the same date file via git = merge conflicts (no documented conflict handling).
- Sextant fit: memsearch capture omits tool calls/outputs from summarization input but user prompts are summarized verbatim-ish — secrets must be excluded by discipline or config; ai-memory claims sanitizer + ignore_paths (not source-verified here).
- agentmemory's DSH/MCP depth and ai-memory's exact hook blocking behavior: README-level only.
