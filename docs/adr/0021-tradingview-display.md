# ADR-0021: TradingView displays our trading state and never drives execution

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0012-agentic-research-mcp-and-tradingview.md, whole, including amendments.
- **Harvested from:** northstar-trading@8256c16c31dc:docs/adr/0014-tradingview-automation-lane.md, whole, including amendments.
- **Harvested from:** northstar-trading@8256c16c31dc:docs/tradingview/README.md and src/northstar_trading/tradingview/.

## Context

TradingView is the owner's prime display of the live incentive ranking, charts and notifications. The display is never the trading universe.
Broker/Nautilus data supplies execution, protection, inventory and TCA truth. Acceptance of display policy does not certify deployment, custody, economics or live readiness.

## Decision

- No agent or MCP gets order tools. No TradingView data feeds machine signals, ranking, sizing or risk. No alert, webhook or panel workaround places an order, including paper. Pine/Strategy Tester fills are not execution evidence.
- Use official cloud MCP for named-list membership and simple price notifications. Its dated beta contract is OAuth 2.1, Streamable HTTP, non-trial Essential+, delayed market data and approximately 100 requests/minute/user. List limits are 1,000 symbols on Essential+ and 30 on Basic. The recorded sync used about 1–2 calls/minute; build the top-20/focus-priority fallback only after a measured 429 or cap.
- `NS movers` and `NS focus` display the research ranking; membership sync does not reorder it. Paper trading retains the full ranked universe. Stale or invalid research input is unavailable, never an empty desired list or a `last_valid` fallback.
- RAM-only OAuth is the default. Explicit owner browser consent and `--persist-auth` permit only the official SDK sync process to store/read/rotate its official tokens and registration in macOS login Keychain service `northstar.tradingview-mcp`, account `oauth`. No file fallback, broker credential, Desktop-session grant, agent token read/copy or same-UID isolation claim follows. Revoke the TradingView grant and delete that item; local deletion alone is not server revocation.
- Desktop jobs stay Windows-native, sequential, on loopback `127.0.0.1:29222`, with each exact pin and job allowlist. The owner accepted unauthenticated local CDP exposure, including WSL reachability with paper/live brokers connected, contained by a pinned controller on a dedicated port, a Windows-native client with a tool deny list, and agents never connecting to it (`docs/handbook/lessons.jsonl:42`). This is historical host-specific acceptance, not portable account or execution authority.
- Keep iliaal 1.4.0 (`233f29e180031291dacac4c4cc2736a8dde161be`) for accepted navigation only; its five Pine writes/switches and drawing remain denied. Use JostQQ v1.0.0 (`89317db92b3b962fd8e89f3ec20462da6e4f2733`) for NEW immutable display scripts only, never overwrite/rename/delete. Use tvcontrol v2.5.3 (`85200201f92967db9e4b63a9251d51fcdfe1f3a8`) for dedicated layouts and own-ID level drawing/removal. Raw UI, launch/evaluation, broker/order tools and bulk deletion remain excluded. Its indicator-preset path failed; retain owner-manual application and Pine fallback.
- Require health/target/capacity and clean editor; reviewed source/hash and new dated `NS <YYYY-MM-DD> · <preset_stem>` ID; binding/compiler/study/input readback; non-destructive persistence and unchanged unrelated inventories. Confirm switches and restore the owner layout by numeric ID. Ambiguity, unsaved owner work or missing persistence stops acceptance. Keep independent receipt review, TCA→manifest→handbook and weekly regression/review obligations.
- Carry v6 `indicator()` presets: EMA 10/30; Hurst 128, R/S lags 4/8/16/32, flow-proxy window 50, thresholds 0.55/0.50/0.30; manual quote sizes with strict larger >100 and smaller/larger <0.2. These are formulas/proxies, never fills, order-book history or bot parity. No `strategy()`, `alert()` or `alertcondition()` execution path.
- The exit display uses an owner-entered long entry and completed 5-minute Wilder ATR22 ×3, tightening only; R = max(entry − opening-range low, 10% prior daily ATR14, 3×spread), initial stop = entry − R; unset spread leaves R provisional. Cost breakeven defaults to 6 bps total round trip, locking only when the candidate strictly exceeds it. The first-five-minute RTH range starts drawing at 09:35. These are separate levels on a standard 1-minute chart, not combined protection; feed/session/seed/Pine-float differences remain.
- TradingView paper tickets and broker presets remain owner-manual. Managed-paper default is LIMIT with no bracket, extended hours outside RTH subject to broker/session rules, and custodian protection from first fill. Brackets are labelled for owner-managed positions only; they reserve shares the custodian cannot also protect. Owner orders remain untouched and custody decisions use provenance. Ticket numbers use engine money types or Decimal; missing inputs stay unavailable. Live remains under the separate live mandate.
- Position snapshots are cache-only, with exact decimal strings and explicit mapped symbols. Missing, invalid, unmapped, future or stale input leaves that lane's alerts untouched; only fresh empty positions permits cleanup. Default expiry is 300 seconds, configurable 1–3600, checked again before paced writes. Reserved alerts must have `has_webhook=false`. Unknown schemas/envelopes or ambiguous writes stop without automatic tool-call replay or rollback; earlier writes may have succeeded. Remote expiry remains **unverified**.
- Select Lightweight Charts v5.2.1 (`b2ce010e4ad59f6556c9ed60e2b2b30feccdd2d1`) for licensed broker/Nautilus execution/TCA display, retaining NOTICE and attribution/link obligations. Selection is not an installed connected view. Full OAuth, production persistence/capacity, hook enforcement, custody/TCA, producer/indication delivery and live acceptance remain **unverified** here.

## Evidence

| Claim | Source (repo@sha:path, section or line) | Recorded basis |
|---|---|---|
| Display-only admission and Terms | northstar-trading@8256c16c31dc:docs/adr/0012-agentic-research-mcp-and-tradingview.md:13–23,75–104,354–363 | TradingView Terms §3 and official MCP docs, read 2026-10-29/11-01; GPT/Google convergence; DeepSeek CONFIRM 2026-11-05. |
| Prime display, lists and limits | northstar-trading@8256c16c31dc:docs/adr/0014-tradingview-automation-lane.md:3–44,337–358 | Owner/lead rulings 2026-11-03; 88 attributed successful cycles; official docs correction, read 2026-11-05. |
| Consent and narrow persistence | northstar-trading@8256c16c31dc:docs/adr/0012-agentic-research-mcp-and-tradingview.md:327–339; northstar-trading@8256c16c31dc:docs/tradingview/README.md:22–50 | Owner exception 2026-10-29; MCP Python SDK 2.3.0 OAuth example and keyring 25.7.0 macOS backend. |
| Job boundaries and acceptance | northstar-trading@8256c16c31dc:docs/adr/0012-agentic-research-mcp-and-tradingview.md:147–168,271–342; northstar-trading@8256c16c31dc:docs/adr/0014-tradingview-automation-lane.md:186–210,317–322 | Attributed Windows measurements and GPT/Google convergence; 2026-11-02 release-pin ruling. |
| Presets and fidelity | northstar-trading@8256c16c31dc:docs/tradingview/README.md:452–463; northstar-trading@8256c16c31dc:docs/adr/0014-tradingview-automation-lane.md:175–195 | NautilusTrader rc7 example and local strategy/replay/design pins embedded in each Pine file; official Pine v6 docs read 2026-10-23/29. |
| Managed-paper preset precedence | northstar-trading@8256c16c31dc:docs/adr/0014-tradingview-automation-lane.md:162–173,310–315 | ARCH LEAD 2026-10-31 carry and G6c ruling; provenance-isolated custody; TradingView/Alpaca preset documentation. |
| Snapshot refusal and expiry | northstar-trading@8256c16c31dc:src/northstar_trading/tradingview/inputs.py:130–193; northstar-trading@8256c16c31dc:src/northstar_trading/tradingview/sync.py:30–67,151–201,271–383 | Source inspection; official MCP watchlist/alert APIs and SDK 2.3.0 session API, as recorded in README:367–450. |
| Local renderer and residuals | northstar-trading@8256c16c31dc:docs/adr/0014-tradingview-automation-lane.md:58–104,199–212 | Lightweight Charts v5.2.1 README/v5 API, read 2026-11-01; unsigned tag, not attestation. |

## Changes for Sextant

The approved `/home/choreo/Developer/sextant/.superpowers/sdd/sextant-plan/plan.md`, “Harvest” and Phase 6, carries display-only rules/presets and the official MCP/Pine/Lightweight Charts roadmap. The existing grant exception is Mac-Keychain only; moving it requires a new owner exception. This harvest grants no rollout or portable credential authority.
COMMON.md's newest owner scope and limits remain verbatim; they do not turn the display into an execution path:

- "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"
- "FOCUING ON US EQUALITY, OPTION,STOCKS ETC, AND ALL THE LANES PREVIOSU STATED, PHILOSOPY PREVIOUS STATED, JEV TRADE RELATED RPEOS ETC ,RESEARCH LANE ,AUTO LEVERAGE, PROTFOLIO MANGEMENT AND BEYOND"
- "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"

## Code and config to carry

No code is copied. Counts are `git show <pin>:<path> | wc -l` at northstar-trading@8256c16c31dc.

- `src/northstar_trading/tradingview/`: 12 files, 3,094 lines: `__init__.py` 1; `__main__.py` 551; `auth.py` 415; `auth_safety.py` 245; `contracts.py` 43; `inputs.py` 193; `keychain.py` 202; `lock.py` 63; `research.py` 760; `research_cache.py` 111; `status.py` 127; `sync.py` 383.
- `docs/tradingview/presets/`: `ema_cross.pine` 50; `exit_levels.pine` 215; `hurst_vpin.pine` 109; `quote_imbalance.pine` 35. Four files, 409 lines.
- `docs/tradingview/`: `paper-positions.schema.json` 27; `paper-account.schema.json` 19; `tradingview-state-v1.schema.json` 87; `README.md` 482; `brokers.md` 35.

## Disagreements

- Later rulings supersede single-controller/all-Pine-denied shorthand, JostQQ's post-release pin, mandatory brackets and renderer-candidate wording. The later four-preset installation is attributed evidence, not proof of full persistence or execution parity. Sources: ADR-0012:276,318–337; ADR-0014:64,104,193,310–322 at the harvested pin.
- The 2026-11-05 correction withdraws “press-only/unverified” for ~100 calls/minute and replaces the dead IBKR bracketing link with `https://www.interactivebrokers.com/docs/third-party-integrations/trading-view/faq.md`. IBKR children may be added only while the parent is open and unexecuted. Source: ADR-0014:66,337–358 at the harvested pin.
- northstar-trading ADR-0014:31 says an unmapped research symbol refuses consent; the pinned consumer instead omits unmapped rows within its existing limit, and defaults to readback verification. This source mismatch is retained, not resolved into new policy: northstar-trading@8256c16c31dc:src/northstar_trading/tradingview/research.py:192–237,330–418; northstar-trading@8256c16c31dc:src/northstar_trading/tradingview/__main__.py:163–220.

## Revisit when

- A controller/Desktop/SDK/keyring/chart pin or official Terms, entitlement, rate, tools or OAuth contract changes; a supported preset/binding capability gains a scoped receipt; or persistence, custody, display-driven execution or CDP behavior contradicts the boundary. Owner: display/admission lead; repeat relevant acceptance and amend.
- New owner consent/host/revocation, producer/indication/private-view acceptance, a measured 429/list cap, overlap publication or the open-source-terminal verdict arrives. Owner: the relevant display/research lead; amend without assuming a switch. “Multi-model verdict, next version” remains a named revisit.
- Retain the source's Desktop/CDP review by 2026-11-12, OAuth-exception review by 2026-11-29, weekly regression/independent review, token lifetimes and immediate stop conditions. These safeguard clocks are not rollout permission. Sources: ADR-0012:27–48; ADR-0014:40–44,72–94 at the harvested pin.
