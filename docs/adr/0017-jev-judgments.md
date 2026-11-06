# ADR-0017: Keep TypeSafe Jev judgments paired, reproducible and outside order authority

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-10-31-jev-arm-a.md and `src/northstar_trading/judgments/`, whole records/files.
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-11-02-jev-question-set.md and `docs/research/2026-11-02-sim-family-registry.md`, whole records.
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-11-02-jev-paper-adapter-r6-ws.md, whole record including its exact-model amendment.
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0009-models-regime-anomaly-forecasting.md, 2026-11-03 Jev amendment; whole record read in this harvest.
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-10-31-jev-repos-gpt.md and `docs/research/2026-11-01-jev-repos-google.md`, whole records including corrections.
- **Harvested from:** northstar@b384d298d217:docs/research/2026-11-04-jev-fit-sweep-legs/jev-fit-sweep/leg-deepseek.md, whole record.
- **Harvested from:** sextant@db326993b58b:docs/research/2026-11-05-foundations-convergence.md, J6.
- **Other inputs:** approved Sextant plan, Jev row/Phase 5; read-only `bd show northstar-yae.51`; supplied `COMMON.md`; supplied 387-row `owner-stars.tsv` snapshot, all rows screened.

## Context
Jev supplies typed semantic judgments over captured evidence. Sextant starts with a paired with/without arm in sim; a typed probability is neither a financial fact nor earned trading merit [J1, J2].

## Decision
- In sim, pair Jev ON/OFF on the same inputs and sessions with the other policy fixed. Keep costs, controls, failures and every attempted variant in one trial ledger; use StepM, DSR at effective N and PBO by CSCV. No live authority until merit and the separate live gates [J1].
- A Jev overlay is adopted only on Nautilus-native replay, the 24/7 sim lanes and recorded paper fills, in the one ledger. A negative result turns it OFF and is recorded; the stack defaults OFF until evidence [J10].
- The historical paper client uses the official SDK in process with a paper inference-only key; the live runner and its units never receive that key. A missing key leaves paper running, Jev OFF and the absence journaled. Broker/data credentials retain their separate strict boundary [J10].
- Use the official SDK's Noul, Choice and Score semantics. Keep clocks, mapping, arithmetic, money, sizing, custody and orders deterministic; confidence measures distribution concentration, not truth or a price-move probability [J2].
- The historical implemented catalyst screen is entry-only: a negative answer may veto, a positive answer may give bounded priority inside the deterministic top-N. It cannot backfill a hole, cross the cut, re-allow a refusal, change quantity/leverage/caps, or touch protection [J3].
- Submit once per source revision on receipt workers, then consume the durable result without I/O on candidate ticks. Missing, LATE, ERROR, SKIPPED or unavailable means the unchanged incumbent with an explicit reason, never invented neutral. Preserve coverage and unavailable-block exclusions [J3, J4].
- The historical arm alternates whole calendar accounting blocks at 20:00 America/New_York, including DST/weekends/holidays, from an explicit anchor. Its pinned config anchor is null; source code is not an activation or deployment receipt. Keep originating treatment through closure and never pool alias-era and pinned-model evidence [J4].
- Carry `jev-1.14.0` and `typesafe-sdk==0.7.5` as the verified historical model/client contract. Exact returned model, source/version, request hash, typed answer, latency, usage and durable ledger join are retained; model changes start a new policy/arm/window [J2, J4].
- Preserve the six **UNCALIBRATED** catalyst starts: relevance 0.7, negative probability 0.8, positive probability 0.7, priority ceiling 1.25, request budget 200 ms and event visibility 86,400 s. They are not measured optimal thresholds or a latency SLA [J5].
- Keep `jev-rank` and `jev-exit` as distinct sim specifications: rank weights 0.10/0.20, never a gate; negative-direction probability ≥0.6/≥0.8 for the exit cells; each has 2 cells + 4 controls. Freeze questions before outcomes; pending question/ledger prerequisites confer no operating authority [J6].
- Replay recorded answers/failures without another API call. Keep `jev: live-ledgered` separate from `jev: recalled`; preserve actual answer availability and point-in-time inputs. Training cutoff, determinism and target-domain lift remain **unverified** [J6].

## Evidence
| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| J1: paired sim and authority | Approved plan, lines 169, 196–198; northstar-yae.51, Description/Notes; northstar-trading@8256c16c31dc:docs/research/2026-11-02-sim-family-registry.md, Rules | Owner-approved sim-first paired arm; existing entry-only/fail-open ruling; no leakage-clean after-cost OOS edge in the bead. |
| J2: typed client and semantics | northstar-trading@8256c16c31dc:docs/research/2026-11-02-jev-paper-adapter-r6-ws.md, exact-model amendment; `docs/research/2026-10-31-jev-repos-gpt.md`, §5 | Official typesafe-sdk v0.7.5 async-client practice; TypeSafe models/primitive/confidence pages read 2026-10-31/11-02; exact-ID/mismatch offline tests, not real-service quality. |
| J3: entry screen boundary | northstar-trading@8256c16c31dc:docs/research/2026-10-31-jev-arm-a.md, shared contract/receipt implementation; `src/northstar_trading/judgments/catalyst_screen.py` | TradingAgents v0.7.1 (`c4544913a14ed3df5f1ed7b9e8483270ce20682a`), `tradingagents/agents/post_screen.py`; relevance/stance decomposition adapted to a separately versioned event-polarity question. |
| J4: blocks and durable identity | northstar-trading@8256c16c31dc:docs/research/2026-10-31-jev-arm-a.md, R2/R3; `src/northstar_trading/paper_entry.py`; `configs/lanes.yaml`, lines 26–29 | Source-version deduplication, fsynced evidence and policy-cohort comparison; exact-model cutover; null activation anchor. |
| J5: starting values | northstar-trading@8256c16c31dc:configs/paper/profiles.yaml, lines 82–87; `docs/research/2026-10-31-jev-arm-a.md`, policy table | Dated architecture rulings and K7 budget; every row explicitly UNCALIBRATED, not upstream numerical policy. |
| J6: proposed rank/exit and replay | northstar-trading@8256c16c31dc:docs/research/2026-11-02-jev-question-set.md, freeze status and consumption/replay rules; `src/northstar_trading/sim_lanes/grid_overlays.py`, `_jev`/`jev_rank`/`jev_exit` | TypeSafe Score/composite and Choice examples; candidate hash `5d608713e839b3ac349f43c05da6e4924d9c03bd29fb48a748450aac9fa2da96`; question/ledger bindings PENDING, not a completed run. |
| J7: skill | sextant@db326993b58b:docs/research/2026-11-05-foundations-convergence.md, J6 | GPT/DeepSeek converge on typesafe-ai/skills v0.6.2 (`302eea662c54bca6730873fe245bec1d69ebc23d`); no trading result verified. |
| J8: related starred references | northstar-trading@8256c16c31dc:docs/research/2026-10-31-jev-repos-gpt.md, §3–4; supplied owner-stars.tsv rows 43, 193, 198, 227, 354 | TradingAgents: Noul/Choice screen; EdgarTools: deterministic SEC substrate; ai-hedge-fund: typed direction/strength contract; Dexter: claim rubric; jev-trader: crypto order bot/mock latency, no house authority adopted. |
| J9: broader screening | northstar@b384d298d217:docs/research/2026-11-04-jev-fit-sweep-legs/jev-fit-sweep/leg-deepseek.md, §2/5 | Six evaluated repositories: SEC 8-K decision models, QuantDinger, ai-hedge-fund, TradingAgents, Jevinik and bot-derby; source fit is not adoption or economic merit. |
| J10: adoption and paper-key scope | northstar-trading@8256c16c31dc:docs/adr/0009-models-regime-anomaly-forecasting.md, 2026-11-03 amendment, lines 182–197 | LEAD's replay/sim/fills and negative-OFF ruling; typesafe-sdk-python v0.7.5 official async in-process client; paper-only inference-key ruling. |

## Changes for Sextant
The approved Jev row makes the arm sim-first; old paper code is a reuse reference. The newest owner rulings are verbatim from supplied `COMMON.md` (2026-11-05/06):
- "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"
- "FOCUING ON US EQUALITY, OPTION,STOCKS ETC, AND ALL THE LANES PREVIOSU STATED, PHILOSOPY PREVIOUS STATED, JEV TRADE RELATED RPEOS ETC ,RESEARCH LANE ,AUTO LEVERAGE, PROTFOLIO MANGEMENT AND BEYOND"
- "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"

## Code and config to carry
All counts below are `git show 8256c16c31dc:<path> | wc -l` in northstar-trading; these are source pointers for adaptation, with no activation or code copied here.
- `src/northstar_trading/judgments/__init__.py@8256c16c31dc` — 1 line.
- `src/northstar_trading/judgments/contract.py@8256c16c31dc` — 166 lines.
- `src/northstar_trading/judgments/jev.py@8256c16c31dc` — 1,093 lines.
- `src/northstar_trading/judgments/store.py@8256c16c31dc` — 463 lines.
- `src/northstar_trading/judgments/catalyst_screen.py@8256c16c31dc` — 680 lines.
- `src/northstar_trading/judgments/catalyst_reader.py@8256c16c31dc` — 48 lines.
- `src/northstar_trading/judgments/catalyst_receipts.py@8256c16c31dc` — 158 lines.
- `src/northstar_trading/paper_entry.py@8256c16c31dc` — 308 lines; `src/northstar_trading/strategies/orb_stocks_in_play/entry_overlay.py@8256c16c31dc` — 61 lines.
- `configs/lanes.yaml@8256c16c31dc` — 166 lines; `configs/paper/profiles.yaml@8256c16c31dc` — 202 lines. Carry Jev identity/registry fields, not superseded lane prose.
- `src/northstar_trading/sim_lanes/grid_overlays.py@8256c16c31dc` — 282 lines, registration-only specifications with pending prerequisites.

## Disagreements
The corrected Google repo report explicitly excludes its Medium-effort leg from convergence; its High rerun is **unverified** there. The later DeepSeek sweep reports effort not exposed and no adoption verdict. These do not turn their proposed calibrators, gates or repository rankings into accepted picks. The GPT report's TradingAgents stance/event-polarity difference is preserved as a declared adaptation [J3]. Training cutoff, real-service latency, deployment, calibrated thresholds and after-cost lift remain **unverified**.

## Revisit when
- Each arm's Nautilus-native replay, 24/7 sim and recorded paper-fill evidence lands: adopt only on that evidence, or record it OFF on a negative result, then amend the owning policy [J1, J6, J10].
- The TypeSafe SDK changes how it takes its key, or "multi-model verdict, next version" arrives: the owning lead re-reads the pinned SDK or commissions the second-family leg, then amends [J10].
- Model, question, semantic inputs or upstream contract changes, or a new reproducible screened artifact/contradictory source arrives; review at its pinned source and use the required new identity [J2, J6; GPT repo report §6].
- A named screened reference supplies a separated research annotation contract or matched real-model evidence; re-evaluate its documented seam without granting another engine or direct order authority [J8, J9].
