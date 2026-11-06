# ADR-0015: Source strategies from cited methods and keep research point in time

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0012-agentic-research-mcp-and-tradingview.md (research only).
- **Harvested from:** northstar@b384d298d217:docs/decisions/0020-strategy-sourcing-pipeline.md.
- **Harvested from:** northstar@b384d298d217:docs/decisions/0023-ab-testing-and-fine-tuning.md.
- **Harvested from:** northstar@b384d298d217:docs/decisions/0031-research-runtime-lane.md.
- **Harvested from:** sextant@db326993b58b:docs/research/2026-11-05-foundations-convergence.md, J4/J5 and disagreement 1.

## Context

The research lane turns cited strategy ideas into explicit hypotheses and frozen artifacts for replay.
Source availability and an owner star establish discovery, never after-cost edge or trading authority.

## Decision

- Start with NautilusTrader's maintained examples or a cited published method. Keep `research/sources.yaml`: citation, URL, SPDX licence, data needs, publication date, status, full source pin, notes and attribution. Licences are informational within the accepted private experimental scope; the old blanket exclusions are historical.
- Before compute, check OSAP/JKP and the HXZ **t ≥ 3** screen. Use cost-adjusted, post-publication returns as the prior and assume about half the paper's edge. Unavailable fundamentals, membership and consensus inputs remain unavailable.
- Reproduce the paper's sample statistic, then test **post-publication only** with point-in-time inputs, NYSE breakpoints, value weighting and a price filter. Apply WF, CPCV, DSR counting trials, PBO, spread and impact costs. The path is Nautilus backtest → tournament → paper evidence → live candidate dossier; the owning live decision controls promotion.
- Before a research card enters the queue, record source, cutoff, model, data identity and explicit hypothesis. Only frozen factors/theses cross into Nautilus replay. Research output supplies no prices or sizing; no agent or MCP gets order tools.
- Keep native research with Exa, paper-search, Context7 and DeepWiki. Another research runtime needs a named unmet requirement; the old mandatory native A/B, quota-based drop, gateway and wrapper prescriptions are historical.
- Compare A/B offline on the same catalog, identical fill/fee/latency models and `random_seed`: Diebold–Mariano HAC on paired daily differences, Ledoit–Wolf Boot-TS, SPA/StepM/MCS for more than 2 variants, PSR and minimum track record. Offline screens: Boot-TS **p < 0.05**, SPA for more than 2 variants, **PSR ≥ 0.95**, sign retained at **2× costs**. Paper verifies fidelity; the old calendar/capital table is superseded.
- Count trials cumulatively and log every trial's daily net returns. Optuna **5.0.0** single-objective multivariate TPE explores **5–8 parameters, 100–300 trials**, scoring lower-quantile Sharpe across CPCV paths with purge/embargo; use `WilcoxonPruner` across folds. Specify estimator, folds, purge, embargo and trial dependence.
- Require **DSR > 0.95** with effective trial count from correlation or ONC clustering, and **PBO ≤ 0.05**, CSCV **S=16**; **0.20** is only a loose first screen. Finish with a one-shot **12–24-month** holdout. These are statistical sample specifications, not calendar deferrals or new live-admission rules.
- TradingAgents is a **forward-only qualitative thesis generator**, never historical thesis backfill, signal or order path. The retained source pin is **v0.7.0, e8f5503e9b86d5c2710b0c76b1f686703968c9df** pending exact-pin regression and paired forward comparison. Correct v0.7.1 is **c4544913a14ed3df5f1ed7b9e8483270ce20682a**, not its parent.
- A thesis records instruments, direction, horizon, invalidation, sources with `knowable_at`, generator and generation time; confidence is a Decimal string in **[0, 1]**. Latest source `knowable_at` must not exceed generation. Mode `live` requires `<review-run-id>:PASS` or `:PASS-WITH-NITS`; it grants no order authority. Notes are immutable; `ResearchNote` has `ts_event=latest source knowable_at`, `ts_init=max(generation, write time)`, and a catalog separate from backtests.
- Catalysts append revisions/retractions; consumers use only **`ts_init ≤ as_of`**, selecting the latest visible revision. Keep publication and wall receipt separately: SEC acceptance is not publication. Policy-timed backfills retain **`attrs["pit_verified"]="false"`**; their historical availability is **unverified**, and the exact timing policies stay in the pinned `pit.py`.
- J4's selected research method is native `ce-bakeoff`, with fresh contexts, an independent judge and **named families in the brief**. J5 selected `tradermonty/claude-trading-skills`, commit **d8e71ce2f0b069eb5b6fca352857c168c35e6c46** (no tag), with NautilusTrader's own examples.

## Evidence

| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| Registry, priors and replication | northstar@b384d298d217:docs/decisions/0020-strategy-sourcing-pipeline.md, Decision and 2026-10-24/11-01/11-05 amendments; northstar-trading@8256c16c31dc:src/northstar_trading/research/registry.py | McLean–Pontiff 2016; OSAP; JKP; NBER w23394 working-paper HXZ screen, with the published-version correction; GPT register and DeepSeek CORRECT. Chen–Velikov summary is **unverified**, non-operative. |
| Paired comparison and tuning | northstar@b384d298d217:docs/decisions/0023-ab-testing-and-fine-tuning.md, A/B, fine-tuning and amendments | Bailey/López de Prado DSR/Sharpe frontier; Bailey et al. PBO; Ledoit–Wolf 2008; arch 8.0; Optuna v5.0.0 `01ddd17ab9f36c3d2817aed9afe376e1cb047d35`; skfolio CPCV; DeepSeek CONFIRM. |
| Queue and research boundary | northstar@b384d298d217:docs/decisions/0031-research-runtime-lane.md, 2026-10-25 rule and 11-01 closed register | Pi/OMP research, Claude synthesis, Google review; later DeepSeek CONFIRM. Native tools retained; conditional domain roles are not installed-state receipts. |
| Forward-only TradingAgents and no orders | northstar-trading@8256c16c31dc:docs/adr/0012-agentic-research-mcp-and-tradingview.md, current register, pick 3/5 and 11-05 amendment | Owner-mandated forward theses; GPT/Gemini evidence and DeepSeek CONFIRM; corrected v0.7.1 tag identity, comparison still pending. |
| Thesis and catalyst visibility | northstar-trading@8256c16c31dc:src/northstar_trading/catalysts/thesis.py, schema.py, store.py and pit.py | NautilusTrader 2.0.0rc7 custom-data/catalog APIs cited in those files; PIT policies cite E10–E15 and N17 measurements, without verified historical availability. |
| Research method and trading skills | sextant@db326993b58b:docs/research/2026-11-05-foundations-convergence.md, J4/J5 and disagreement 1 | Blind GPT/Codex and DeepSeek/dsh legs; J5 converged; lead's J4 call preserves the disagreement below. |
| Sextant scope | Approved plan `/home/choreo/Developer/sextant/.superpowers/sdd/sextant-plan/plan.md`, strategy sources, skills, harvest and Phases 2/3/5 | Approved research-card → backtest → sim → ledger → merit thin slice; sim first; local research retrieval. |

## Changes for Sextant

- The approved plan starts with the thin slice and sim, then owner-confirmed paper handover with one writer. Qlib **0.9.8** and TradingAgents **0.7.1** are references. Phase 3 harvests the research skills/workflows and local OpenViking retrieval; Phase 5 carries theses/catalysts with knowable-at times. This record installs nothing.
- Newest owner rulings, verbatim (COMMON.md, 2026-11-05/06): "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"
- "FOCUING ON US EQUALITY, OPTION,STOCKS ETC, AND ALL THE LANES PREVIOSU STATED, PHILOSOPY PREVIOUS STATED, JEV TRADE RELATED RPEOS ETC ,RESEARCH LANE ,AUTO LEVERAGE, PROTFOLIO MANGEMENT AND BEYOND"
- "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"
- "we need to using full sota harness framework.dsh that is fully enhanced with openviking etc"

## Code and config to carry

Exact northstar-trading pin; counts from `git show <sha>:<path> | wc -l`. No code copied. The universe fixture is explicitly survivorship-biased; its membership is not historical membership.

| Path@sha | Lines |
|---|---:|
| research/sources.yaml@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa | 523 |
| src/northstar_trading/research/registry.py@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa | 210 |
| src/northstar_trading/research/__main__.py@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa | 34 |
| src/northstar_trading/catalysts/schema.py@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa | 185 |
| src/northstar_trading/catalysts/pit.py@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa | 183 |
| src/northstar_trading/catalysts/store.py@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa | 185 |
| src/northstar_trading/catalysts/thesis.py@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa | 370 |
| configs/backtest/templates/tradingagents.yaml@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa | 14 |
| configs/backtest/templates/template_ema_cross.yaml@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa | 8 |
| configs/backtest/templates/universe.yaml@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa | 46 |

## Disagreements

- J4: GPT chose `ce-bakeoff`; DeepSeek chose ARIS-Code **v0.4.28**, whose tagged binary had no evidenced dsh support. The recorded call chose native invoke and lower footprint; the brief requires named families because `ce-bakeoff` permits a same-family fallback. No re-decision here.
- The old TradingAgents generator retains v0.7.0 pending comparison; the approved plan names v0.7.1 as a reference. Neither proves an upgrade installed. Registry YAML still describes the historical licence gate; the amended ADR and validator make licences informational. Preserve the current rule when carrying the format. Candidate provenance and publication dates remain **unverified**.
- **Unverified:** composed workflows end to end, retrieval quality and trading results; the paired-test **12,466 × (1 − ρ)** constant, optional ranker **0.3–0.4%** R², Chronos LoRA and **48 GB** sufficiency remain source-record caveats, not admission evidence.

## Revisit when

- Source pins/APIs/licences/advisories/library location, registry/data/validation coverage, private-use scope, or independent post-publication/cost/method evidence changes: source/research/validation owner reconciles the evidence and amends the owning record. Material Nautilus/arch/Optuna/skfolio or named model contracts and promotion gates trigger their owners; missing inputs stay unavailable.
- Exact-pin TradingAgents regression and paired forward comparison reports, or a named unmet research need appears: research owner reviews that evidence. Further **"multi-model verdict, next version"**: lead commissions the other-family leg, then an amendment; recorded DeepSeek verdicts above already stand.
- **"ARIS ships a tagged plugin with dsh support, next version"**: lead reopens J4 at the new source.
