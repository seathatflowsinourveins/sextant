# ADR-0018: Every outcome feeds one sourced, append-only learning loop

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-lanes@00203275944a:docs/adr/0009-evidence-and-learning-loop.md
- **Harvested from:** northstar-lanes@00203275944a:docs/handbook/rule-template.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0013-north-star-compounding-loop.md
- **Harvested from:** northstar-trading@8256c16c31dc:src/northstar_trading/reflection/ and src/northstar_trading/research/handbook/
- **Harvested from:** sextant@db326993b58b:docs/research/2026-11-05-foundations-convergence.md

## Context

Trading must retain what each exit, refusal, incident and missed mover taught it, including negative and inconclusive evidence.
Use one source → hypothesis → arm/result → lesson → ADR → sanctioned stage → outcome chain. Index existing artifacts; never duplicate their numbers or journals.

## Decision

- Each owner or strategy exit records hold-to-now, matched hold-flat to its segment's flat boundary, managed policy, managed policy plus re-entry, and each shadow arm's modeled exit. Keep n, censoring, actual/modeled labels and costs at 1× and `cost_stress_multiple`. [L1]
- Append `northstar.handbook.lesson/1` through the canonical handbook appender; the Alpaca lane is its single writer. Corrections are new records with `supersedes`. Deduplicate by `(area, subject, session_date, sha256(lesson))`; retain superseded negatives. Null sample size means unknown, never zero. [L2]
- Link sample size, intervals, limitations, strategy, exit, catalyst, symbol class, source hypothesis and ADR to canonical performance/learning evidence. Narrative memory never authorizes orders or deployments. A new `contradicts_adr` opens an immediate revisit; the appender returns a receipt, not delivered notification. [L2, C]
- Each lesson/reflection outcome has decision/resolution time, sample count and state; as-of consumers use only resolved outcomes. Preserve the closed lesson schema's 15 required fields and named optional links; this harvest adds no timestamp fields to it. [L2, S]
- Every tunable number has one registry row: name, unit, value, source, calibration state and last change. The consuming runtime owns it; reviewed changes occur between sessions. Outputs carry `params_hash`. Missing evidence is labelled starting value (cited), never measured success. [L3]
- Nightly reflection and tuning write proposals only. The tuner never writes the registry, even through the reviewed-change path. Whole-market labels, missed-mover reports and counterfactuals feed replay; labels or one-day anecdotes never adopt a change. Selection filters need measured twins; sim grids are uncapped. Adoption follows [ADR-0019](0019-validation-and-merit.md). [L4–L8]
- One cumulative `TrialLog` counts every arm/run across MODELED, SIMULATED and BROKER-PAPER, including rejected alternatives. Never pool tiers or block sets. Bind implementation SHA, factor mask, arm-run/config/weights identity, funding uncertainty and inference-time effective-N snapshot. Replay → sandbox → broker-paper promotion uses each tier's own frozen evidence; first broker-paper admission uses prospective sandbox holdout and broker/session/order-shape calibration, never nonexistent broker-paper results. Paper operations remain ungated. [L9]
- The 24/7 loop uses per-date XNYS/`America/New_York`: eligible supported live sessions for sandbox/paper, recorded replay always; closed markets run replay, stress, reflection and proposal research. Qlib/RD-Agent are closed-market proposal arms only. No learning tier reaches a live endpoint or deploys. [L10]
- Source scanner history is never deleted: compress completed session days with SHA-256 manifests. Hot storage holds today plus up to 7 completed days, fewer at the 25% floor, but never less than today plus the last completed session day; 7 is UNCALIBRATED. Copy/verify the cold day and its second copy before freeing hot bytes; repoint readers first. Derived mirrors retain required current/reference evidence and need byte-identical source or verified regeneration before pruning. [L11]
- Canonical qualitative lessons remain repo-native and generated views deterministic. A handbook practice links its pillar, decision, registry, sessions, witness, installation state, lesson and revisit. A sourced keep/no-change disposition can close a lesson; activity alone is not learning efficacy. [C, T]

## Evidence

| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| L1–L3: counterfactual, lesson and registry | northstar-lanes@00203275944a:docs/adr/0009-evidence-and-learning-loop.md:39–58,363–469,1060–1089 | Owner/lead rulings; lesson/1 contract; JSON Schema 2020-12 and jsonschema v4.26.0, read 2026-10-29. |
| L4–L8: proposals and adoption boundary | northstar-lanes@00203275944a:docs/adr/0009-evidence-and-learning-loop.md:60–104,1031–1058 | GPT/Google capital-focus, GPT/Claude sim and three-family factor-assignment convergence; owner refusal/twin rulings. |
| L9: one ledger and custodian | northstar-lanes@00203275944a:docs/adr/0009-evidence-and-learning-loop.md:106–121,1114–1144; northstar-trading@8256c16c31dc:src/northstar_trading/validation/trials.py:140–186,622–714 | Owner one-ledger ruling; existing TrialLog, not a replacement; source presence does not prove operation. |
| L10–L11: continuous learning and retention | northstar-lanes@00203275944a:docs/adr/0009-evidence-and-learning-loop.md:123–138,281–336 | NautilusTrader rc7 replay; exchange_calendars 4.13.2; scanner-owner proposal and ARCH LEAD retention ruling. |
| C: source-to-stage chain and limits | northstar-trading@8256c16c31dc:docs/adr/0013-north-star-compounding-loop.md:3–44,88–114,137–146 | Owner 2026-10-29; thin-index design; GPT register and DeepSeek WATCH, not measured end-to-end efficacy. |
| S: canonical schema, append and missing wiring | northstar-trading@8256c16c31dc:docs/handbook/lesson-v1.schema.json:5–24,99–132; northstar-trading@8256c16c31dc:src/northstar_trading/research/handbook/append.py:1–8,53–88 | Existing closed contract, idempotent appender and contradiction output; no session-runner wiring claimed. |
| T: handbook links and proposal producer | northstar-lanes@00203275944a:docs/handbook/rule-template.md; northstar-trading@8256c16c31dc:src/northstar_trading/reflection/learning.py:542–565,764–790; northstar-trading@8256c16c31dc:src/northstar_trading/reflection/tuning_runner.py:404–435 | Existing native-attribution join and candidate-only adapter; no new emitter or decision engine. |
| Legacy code limits | northstar-trading@8256c16c31dc:src/northstar_trading/reflection/tuning.py:713–748,779–804,1063–1072,1177–1251; northstar-trading@8256c16c31dc:src/northstar_trading/reflection/lifecycle.py:81–208 | Source-only proposal/lifecycle policy; not proof of L5 adoption or a canonical lesson emitter. |
| Sextant compounding pick | sextant@db326993b58b:docs/research/2026-11-05-foundations-convergence.md, J3 and disagreement 2 | Blind GPT/DeepSeek legs: Compound Engineering `ce-compound`, `trader-memory-core`, `signal-postmortem`; Hindsight disagreement retained. |

## Changes for Sextant

The approved plan's Harvest and durable-data sections carry this loop and lesson schema/appender. Irreplaceable fills, trials and merit records live on `ledger`; handbook lessons and skill/rule improvements travel through PRs. GitHub Issues replace beads. J3 chooses repo-native `docs/solutions/` capture; OpenViking retrieval is [ADR-0022](0022-memory-rag-and-enhanced-dsh.md). No second canonical lesson or numerical store is introduced.
Newest owner wording, verbatim from COMMON.md (2026-11-05 and 06):

> "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"
> "FOCUING ON US EQUALITY, OPTION,STOCKS ETC, AND ALL THE LANES PREVIOSU STATED, PHILOSOPY PREVIOUS STATED, JEV TRADE RELATED RPEOS ETC ,RESEARCH LANE ,AUTO LEVERAGE, PROTFOLIO MANGEMENT AND BEYOND"
> "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"

## Code and config to carry

Source inventory only; no code copied. All trading paths below are at northstar-trading@8256c16c31dc; counts use `git show <pin>:<file> | wc -l`.

- `src/northstar_trading/reflection/`: 35 files, 18,155 lines in the source inventory. Core loop pointers: `learning.py` 790; `session_runner.py` 531; `tuning.py` 1,622; `tuning_runner.py` 530; `ledger.py` 1,096; `merit.py` 663; `merit_thresholds.py` 64. The inventory is not a whole-tree port or a budget increase.
- `docs/handbook/lesson-v1.schema.json` 169; `src/northstar_trading/research/handbook/append.py` 357; `core.py` 387; `render.py` 136; `scripts/handbook.py` 95. Preserve the single appender and schema.

## Disagreements

- J3: DeepSeek adds Hindsight capture; GPT makes it runner-up because of a daemon and three lifecycle hooks per host. The recorded call is repo-native `docs/solutions/` now, with OpenViking as named RAG; the disagreement remains open to its named evidence event, not a new vote here.
- L9's November 5 pointer says canonical-path/writer enforcement is not yet in force. The supplied trading pin contains `TrialLog.canonical_path()` at `validation/trials.py:140–186`. Preserve both source states; actual custody/operation is **unverified**. ADR-0013's DeepSeek WATCH and unproved whole-chain joins, append wiring, reverse links, external-path portability and learning efficacy remain **unverified**.
- Legacy tuning still requires paired lanes, a registry window ≥20 and at most 9 neighbors, and embeds numeric deltas/intervals in lesson prose. L5's later frozen protocol replaces the old 20-session/paired-lane shorthand; L2 links numbers and the later owner residual leaves sim grids uncapped. Tuning is proposal-only, not an L5 adoption implementation; do not silently reconcile these scopes (lanes :62–82,1031–1075; tuning source above).
- Legacy lifecycle's `schema_version`/`lesson_id`/`action_status` shape is not the canonical closed lesson/1 schema. Its `20*j`-day retirement rule is not a general paper-permission or merit threshold. Adapter/runtime conformance remains **unverified** (lifecycle source above).

## Revisit when

- Calibration, first missed-mover report, a protocol's sealed holdout, StepM rejection or nonzero R0 A/A lift, changed validation upstream/evaluation, or contradictory lesson arrives: learning/research owner checks evidence and amends. Retention/manifest/regeneration/minimum-day failures stop the affected move/prune; scanner owner resolves before amending (L5, L11).
- A source/arm/lesson/ADR/stage link, append rerun, reverse link, contradiction delivery, writer, reference or authorized stage outcome succeeds or fails: its artifact owner records the evidence and amendment (ADR-0013 E1–E11). A mapped residual or independent-family verdict changes the record: lead amends.
- A measured need exceeds repo learning, or Hindsight ships hook-free Claude/Codex routes: revisit J3. Memory retrieval quality, the composed workflow and trading benefit remain **unverified** by this harvest.

## Amendment 2026-11-06: the lesson journal's writer until a paper lane operates

- **Authority:** the lead's ruling on [#72](https://github.com/seathatflowsinourveins/sextant/issues/72#issuecomment-6689961145), carried by [#102](https://github.com/seathatflowsinourveins/sextant/issues/102). L2 is otherwise unchanged.
- **Writer:** L2 names the Alpaca lane as the single writer, and no Sextant paper lane operates yet. Until one does, **the lead is the single writer**. The lead's PRs append through the one `lesson/1` appender (#96). When a paper lane operates, the writer passes to it: Paper B (#78) first, with a dated amendment. There is never a second writer, and other lanes hand their lessons to the current writer.
- **Revisit when:** a paper lane operates (handover, owner-confirmed), or a lesson lands outside the current writer.
