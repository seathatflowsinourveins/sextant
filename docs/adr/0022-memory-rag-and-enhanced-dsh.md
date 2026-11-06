# ADR-0022: Keep memory canonical and enhance dsh with disposable research retrieval

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** `M = northstar@b384d298d217:docs/decisions/0069-memory-and-code-intelligence.md`.
- **Harvested from:** `D = northstar@b384d298d217:docs/decisions/0070-agent-runtimes-and-harnesses.md`.
- **Harvested from:** `P = northstar@b384d298d217:docs/decisions/0071-platform-and-observability.md`.
- **Harvested from:** `N = northstar@b384d298d217:config/dsh/native-overlays.json`.
- **Harvested from:** `O = northstar@b384d298d217:config/dsh/overlays/openviking.cordis.yml`.
- **Harvested from:** `K = northstar@b384d298d217:config/dsh/knowledge.lock.json`.

## Context

Trading research needs retrievable, citable records. Runtime memory, curated narrative and recorded trading evidence have different authority; a derived retrieval index is rebuildable.

## Decision

- The old finalized baseline is BUILD-UPON: Markdown in git and beads, qmd retrieval, native memory/compaction within each runtime and lead-curated experience. Rerank and expansion are OFF; automatic capture and automatic consolidation remain gaps. Codex memories remain OFF in that record.
- Canonical records have one home. Native auto memory assists its runtime; curated narrative preserves decisions and experience. Neither replaces the recorded paper fills, trial ledger or merit manifest as trading source truth.
- The old code-intelligence pick is CodeGraph 1.6.2, official LSP plugins and ast-grep 0.51.0. The approved Sextant plan carries CodeGraph and official LSP plugins.
- dsh uses its native profiles and ordered overlays. Blind research legs receive no house memory or corpus; synthesis may retrieve it. The old overlay inventory is Context7, Exa, DeepWiki, paper-search, Brooks review, reference-checker and session-search.
- The archived Exa selection permits web_search_exa and web_fetch_exa. DeepWiki permits read_wiki_structure and read_wiki_contents; its hosted question tool is masked through dsh's native tool restrictions.
- The old knowledge inventory is billion-context, OpenResearch, WeKnora and OpenViking. OpenResearch's dsh integration is BLOCKED; WeKnora is a scoped retrieval service. These inventories do not select every entry for Sextant.
- OpenViking is write-capable: explicit synthesis opt-in only, never a blind-leg default. Its comments are not an enforced read-only boundary. Use a disposable corpus COPY in an isolated loopback workspace; re-import a fresh copy if changed. No automatic conversation capture, session.commit, memory or external URL ingestion. Use find, then read the returned viking:// URI for citations.

## Evidence

| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| Finalized baseline and separate memory roles | M:986–997, 1250–1263 | Finalized 2026-11-01; beads 1.3.2, qmd 2.8.3 and per-runtime upstreams; retained role convergence and lead rulings. No measured composition winner is claimed. |
| Code intelligence | M:990, 1384–1386; approved plan:143–144 | CodeGraph 1.6.2, official LSP plugins and ast-grep 0.51.0 at the source's pins; approved plan carries the first two. |
| dsh composition and blind/synthesis boundary | D:1848–1861, 1926–1931; N:3–10 | deepseek-ai/deepseek-harness 0.2.1-rc.5 native MCP/profile practice; per-tool restrictions recorded for Exa and DeepWiki. |
| Knowledge roles | K:8–78; P:1051–1062; N:7–10 | Pinned WeKnora 0.9.0, OpenViking 0.5.3, OpenResearch 0.2.23, billion-context 0.1.212 and llama.cpp; WeKnora's native retrieve-only capability. |
| OpenViking's old hold and residual | M:1534–1543; N:10; O:1–14; D:2499–2506 | Interactive dsh-tui admission superseded its hold; web/headless/worker/ws HOLD remains. Claude's OpenViking plugin stays WATCH. OpenViking 0.5.3 MCP and dsh MCP client expose write-capable tools without a documented per-tool allowlist. |
| New Sextant scope and canonical trading records | approved plan:29, 107, 142–167, 183; BRIEF-D:0022 row | Owner-approved GitHub Issues, Claude auto memory, local disposable OpenViking research index, CodeGraph/LSP and the selected MCP set. |
| Newest owner requirements | COMMON: “The owner's words today (2026-11-05 and 06)” | Owner quotations reproduced below verbatim. |
| Revisit events | M:1339–1374, 1542–1543; D:2530–2549 | Source event register: upstream/model changes, measured failures, changed memory roles and next-version verdicts; read-only-mode hardening does not gate admission. |

## Changes for Sextant

> "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"

> "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"

> "we need to using full sota harness framework.dsh that is fully enhanced with openviking etc"

- **Amended 2026-11-06 (#54 blind-leg convergence):** repo-document retrieval is [tobi/qmd](https://github.com/tobi/qmd)@v2.8.3 `facd35e01359e59d938bc9418e93fb9318addee3` (MIT), lexical `qmd search` (BM25, no model) over the committed project-local `.qmd/index.yml` (`./docs`, `./lanes`); the derived `.qmd/index.sqlite` stays untracked. Rerank, expansion and `qmd embed` stay OFF (an MCP `query` also needs lexical subqueries and `rerank=false`), as the finalized baseline M had them. All three runtimes call it from the shell. Measured on the clean distro: installed, indexed and found this record with no model download; retrieval quality on this corpus is not measured. [Convergence](../research/2026-11-06-legs-convergence.md), superseding the earlier pass in [2026-11-06-research-convergence](../research/2026-11-06-research-convergence.md).
- The rest of the research set is Context7 4.5.0, DeepWiki, Exa and paper-search. OpenViking 0.5.3 leaves the default repo-retrieval role, because self-hosting needs an embedding model and a VLM; it keeps the owner's enhanced-dsh synthesis role under the write-capable, disposable-copy residual above.
- GitHub Issues replaces beads; repository records retain narrative authority, and the ledger branch holds irreplaceable paper fills, the trial ledger and merit manifest. Claude auto memory remains a separate native facility. The #54 convergence restores qmd for repo retrieval; old installers and host orchestration are left behind. Automatic three-runtime capture with GitHub transport stays a gap: memsearch v0.4.23 captures locally but never pushes, and no sync glue is built.
- **Unverified:** provider fit, installation, runtime behavior and retrieval quality. This harvest verifies source records and paths; it establishes no implementation or quality result.

## Code and config to carry

Use these source configs as references for the selected entries; no code is copied by this ADR. Counts are from `git show <pin>:<path> | wc -l`.

- `northstar@b384d298d217:config/dsh/native-overlays.json` — 12 lines.
- `northstar@b384d298d217:config/dsh/overlays/openviking.cordis.yml` — 23 lines.
- `northstar@b384d298d217:config/dsh/knowledge.lock.json` — 80 lines.

## Disagreements

- ADR-0069 keeps OpenViking out of the canonical memory role and its Claude plugin at WATCH; later dsh interactive admission leaves the headless hold intact. The newer owner ruling and approved plan choose local research retrieval for Sextant. This changes that scope without claiming the old headless deployment was admitted.
- The approved plan swapped qmd for OpenViking; the #54 memory legs (GPT ultra, Claude) both pick qmd back, while the landscape legs (GPT ultra, DeepSeek) kept OpenViking only by deferring to this record. The reconciliation follows the legs that judged the job on its criteria.
- The old syntheses disagreed whether priming and handoff filled automatic capture; the accepted ruling keeps capture a gap. Priming, handoff and native memory do not establish automatic consolidation.

## Revisit when

- OpenViking tools, URI/storage migrations or provider fit change; DeepWiki's read tools change; an upstream read-only mode becomes available; or a retrieval, citation, handoff or supersession failure is measured. The memory/code and dsh leads recheck the cited upstream and amend this record; a read-only-mode improvement is hardening, not an admission gate.
- Automatic capture, extraction, consolidation or a new canonical home is requested: reopen that role explicitly. A new model, advisory, owner ruling or multi-model verdict, next version, triggers the source record's evidence-led revisit.
