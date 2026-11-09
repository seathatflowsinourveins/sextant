# ADR-0026: Synchronize TradingView membership and keep Pine and ticket presets distinct

- **Status:** accepted. Harvested; the decision is unchanged unless “Changes for Sextant” says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0014-tradingview-automation-lane.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0012-agentic-research-mcp-and-tradingview.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/research/2026-10-29-tv-lane-acceptance-run.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/tradingview/README.md
- **Harvested from:** northstar-trading@8256c16c31dc:docs/tradingview/brokers.md
- **Harvested from:** northstar-trading@8256c16c31dc:src/northstar_trading/tradingview/sync.py
- **Harvested from:** northstar-trading@8256c16c31dc:docs/tradingview/presets/ema_cross.pine
- **Harvested from:** northstar-trading@8256c16c31dc:docs/tradingview/presets/exit_levels.pine
- **Harvested from:** northstar-trading@8256c16c31dc:docs/tradingview/presets/hurst_vpin.pine
- **Harvested from:** northstar-trading@8256c16c31dc:docs/tradingview/presets/quote_imbalance.pine

## Context
TradingView shows the lanes' current research and deployment context. [ADR-0021](0021-tradingview-display.md) owns display-only admission, controller restrictions and credential rules; this record carries synchronization and the two different meanings of “presets”.

## Decision
- **Research membership:** carry the recorded scanner → exporter → mirror → `top100/latest` → sync chain. `--research` owns `NS focus` and `NS movers`; the four deployment lists use their authoritative manifest union separately. Rank stays in the producer: add missing members and remove obsolete ones, without re-adding members to simulate ordering. The display's short list never narrows the lanes' ranked universe.
- **Current verification:** the research mode defaults to batch membership/readback, not per-symbol search. It uses exact producer mappings, tolerates at most five unmapped input names, and omits them; stale, invalid or mixed-generation input refuses. Each list is read back; rejected additions are not retried that cycle, extra symbols get one corrective removal and re-read, and more than five rejected names or a remaining mismatch fails. Ordinary manifest sync still confirms mappings through exact symbol search. These modes must not be conflated.
- **Freshness and operations:** ranking freshness defaults to 1,200 seconds (configurable 1–3,600), with snapshot lag at most 600 seconds; notifications use 300-second expiry. Missing/stale position input leaves its notifications untouched; valid fresh empty input permits cleanup. Preflight all operations, serialize writes and check expiry after pacing; an ambiguous write may have succeeded, so re-inventory before another plan. A dry-run or refusal does not advance successful-sync time.
- **Measured scale:** the source reports 100/100 `NS movers` names stored, 0 rejected/corrective removals, 7 calls in a supervised apply; later 88 successful cycles used 5 calls in 80 cycles and at most 8. The November 5 correction confirms approximately 100 requests/minute/user in official documentation. Focus-priority back-off/top-20 fallback responds to measured caps; these observations are not a throughput or account-capacity guarantee.
- **Pine roster:** carry four v6 `indicator()` files. EMA uses 10/30 first-close-seeded confirmed closes. Hurst/VPIN is a chart-bar/close-location proxy, with 128-return Hurst and 50-bar flow windows. Quote imbalance is a manual last-bar size table (`larger > 100`, `smaller/larger < 0.2`), not a historical book. Exit levels display separate completed C5 (5-minute Wilder ATR22 × 3), R and cost breakeven; the first-five-minute RTH range begins drawing at 09:35. Pine feed, float, seed and session differences prevent execution parity claims.
- **Pine acceptance:** preserve the failed initial install, later two-run JostQQ new-ID/reopen/compile/study-binding pass, tvcontrol layout pass and indicator-preset failure with manual fallback. Later source attribution records four production-file installations, not full persistence, input, chart or fill parity. JostQQ's adopted release is v1.0.0, commit `89317db92b3b962fd8e89f3ec20462da6e4f2733`; its tested Pine code is unchanged from the older post-release pin.
- **Order presets mean paper ticket defaults, not Pine:** owner-manual `NS ALPACA DAY LIMIT MANAGED` (LIMIT, 0 relative ticks, DAY, no TP/SL bracket, confirmation on) for managed-paper entries; the `NS ALPACA DAY LIMIT BRACKET` / `NS IBKR DAY LIMIT BRACKET` pair is for owner-managed positions only (LIMIT, 0 relative entry ticks, DAY, confirmation on, TP/SL set before execution). TV presets can place brackets without confirmation, so managed-paper entries stay plain LIMIT, never a bracket. Alpaca's illustrative 2% TP / 1% SL are placeholders for owner replacement, not the extreme-mover exit policy. DAY expiry does not flatten inventory; Alpaca brackets exclude extended hours/trailing legs, and IBKR children can be added only before the parent executes. Saved fields, quantity/risk persistence, account translation and same-paper-account fill visibility remain **unverified**.

## Evidence
| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| Prime display, chain and limits | northstar-trading@8256c16c31dc:docs/adr/0014-tradingview-automation-lane.md, November 3/5 amendments | Owner 2026-11-03; measured cycle log; DeepSeek primary-source correction, read 2026-11-05 |
| Batch/readback supersedes research search | northstar-trading@8256c16c31dc:docs/tradingview/README.md:144–243 | Official MCP batch contract; supervised apply 2026-11-02; explicit default-change witnesses, not a new experiment |
| Manifest/notification synchronization | northstar-trading@8256c16c31dc:src/northstar_trading/tradingview/sync.py, plan_sync/apply_plan; docs/tradingview/README.md, snapshot/alert contract | MCP Python SDK 2.3.0 session API and official schemas; observed response contracts |
| Pine formulas and limitations | northstar-trading@8256c16c31dc:docs/tradingview/presets/exit_levels.pine; ema_cross.pine; hurst_vpin.pine; quote_imbalance.pine | Embedded official Pine v6 references read 2026-10-23/29; NautilusTrader 2.0.0rc7 examples and the recorded C5 replay |
| Acceptance negatives and later bounded passes | northstar-trading@8256c16c31dc:docs/research/2026-10-29-tv-lane-acceptance-run.md, Outcome/Presets; docs/adr/0012-agentic-research-mcp-and-tradingview.md, amendment (5) | Windows operational receipt; later source-bound J1/J2 jobs; exact scope retained |
| Ticket presets and account visibility | northstar-trading@8256c16c31dc:docs/adr/0014-tradingview-automation-lane.md, Owner DAY presets/Kept corrections; docs/tradingview/brokers.md | TradingView order-preset help; Alpaca orders; corrected IBKR TradingView FAQ; owner/account readback absent |
| Order-preset roster, guard and session hazards | [TradingView Order presets](https://www.tradingview.com/blog/en/optimize-trading-with-order-presets-48237/) (published 2024-11-13) and Help Center Order presets (article 43000742711); [Alpaca orders](https://docs.alpaca.markets/docs/orders-at-alpaca) and [Alpaca 24/5](https://docs.alpaca.markets/us/docs/245-trading); [IBKR TradingView FAQ](https://www.interactivebrokers.com/docs/third-party-integrations/trading-view/faq.md); all read 2026-11-09 | Official docs: a preset saves order type, relative ticks, brackets and TIF (10 per broker account); without-confirmation mode can place brackets; Alpaca overnight is 20:00–04:00 ET limit-only, DAY carries to 20:00 ET, brackets exclude extended hours; IBKR children only before the parent executes |

## Changes for Sextant
The approved plan's Phase 6 carries Pine and visibility; it does not authorize account handover or transplant the old host setup. COMMON.md's newest owner rulings (2026-11-05/06), verbatim:
> "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"
> "FOCUING ON US EQUALITY, OPTION,STOCKS ETC, AND ALL THE LANES PREVIOSU STATED, PHILOSOPY PREVIOUS STATED, JEV TRADE RELATED RPEOS ETC ,RESEARCH LANE ,AUTO LEVERAGE, PROTFOLIO MANGEMENT AND BEYOND"
> "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"
> "we need to using full sota harness framework.dsh that is fully enhanced with openviking etc"

## Code and config to carry
- northstar-trading@8256c16c31dc:src/northstar_trading/tradingview — 12 files, 3,094 lines; `sync.py` 383, `research.py` 760 and `__main__.py` 551. Token/admission policy stays in ADR-0021.
- northstar-trading@8256c16c31dc:docs/tradingview/presets — 4 files, 409 lines: `ema_cross.pine` 50, `exit_levels.pine` 215, `hurst_vpin.pine` 109, `quote_imbalance.pine` 35. Copy no code.

## Disagreements
- The initial receipt's four `pine_check` results were not Desktop installs or saved IDs; later J1 and the attributed production installation supersede that state only within their stated scope. J2's indicator-preset failure remains. The old 102-line exit overlay was revised; the pinned file is 215 lines.
- The old “press-only/unverified” ~100/minute statement and dead IBKR bracketing link are explicitly corrected on November 5. Keep the confirmed rule and the live `https://www.interactivebrokers.com/docs/third-party-integrations/trading-view/faq.md` reference; no fresh vendor inquiry was made by this harvest.
- Structural 2%/1% ticket placeholders are not the owner's uncapped-runner policy or evidence of tested gain protection. [ADR-0025](0025-gain-protection-and-fast-exit.md) owns the exit decisions and their negative economics.

## Revisit when
- A relevant controller, Desktop, SDK or official contract changes, or production-preset/readback/persistence or source/fill-fidelity evidence arrives: the display owner rechecks that job and amends it.
- A 429/list cap, overlap display result, owner-triggered terminal comparison or “multi-model verdict, next version” arrives: the display owner/research and lead resolve the named item without inventing a second sync path.
