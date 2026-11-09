# TradingView lane

**Charter.** Display and owner-manual execution only. TradingView lists, alerts and Pine panes show what research and paper are doing; no TradingView data feeds a machine signal, and no alert, webhook, panel, MCP tool or agent path places an order on any lane, paper included. The owner may trade its tickets by hand; those orders stay the owner's and are never adopted. ([ADR-0021](../../docs/adr/0021-tradingview-display.md))

**Hours.** Display 24/5. Sync runs on a schedule, not on the trade clock; a stale or mixed-generation input is unavailable, never an empty or last-valid list.

**Limits.** About 100 requests/min per user on the official cloud MCP; 1,000 named-list symbols on Essential+ (30 on Basic). A recorded cycle uses 1–2 calls/min, 7 calls in a supervised apply, and 5 calls in 80 later cycles. A measured 429 or cap justifies the top-20 focus-priority fallback, never an assumed one. ([ADR-0026](../../docs/adr/0026-tradingview-sync-and-order-presets.md))

**What it runs.**
- `NS movers` and `NS focus` membership from the research producer, with read-back, at most five unmapped names omitted, one corrective removal for extras, and a refusal on more; the display list never narrows the lanes' ranked universe and never reorders it ([ADR-0026](../../docs/adr/0026-tradingview-sync-and-order-presets.md)).
- Four v6 `indicator()` presets — EMA 10/30, Hurst with R/S lags 4/8/16/32 and a 50-bar flow proxy, a quote-imbalance size table, and exit levels from a completed 5-minute Wilder ATR22 × 3 with R and a 6 bps cost breakeven. They are displays; Pine fills are not execution evidence ([ADR-0021](../../docs/adr/0021-tradingview-display.md)).
- Managed-paper entries, including the owner's TradingView entries intended for B's manager, use the owner-manual `NS ALPACA DAY LIMIT MANAGED` preset: LIMIT, 0 relative ticks, DAY, no attached bracket, confirmation on. "TV presets can place brackets without confirmation", so managed-paper entries stay plain LIMIT, never a bracket; outside RTH, apply the broker's extended-hours/session rules. The historical NS ALPACA DAY LIMIT BRACKET and NS IBKR DAY LIMIT BRACKET presets are for owner-managed positions only. Their 2%/1% placeholders are illustrative, not exit policy; DAY expiry does not flatten inventory ([ADR-0021](../../docs/adr/0021-tradingview-display.md), [ADR-0026](../../docs/adr/0026-tradingview-sync-and-order-presets.md), [paper](../paper/README.md), [preset card and dated sources](../../docs/tradingview.md#owner-manual-order-presets)).
- Lightweight Charts 5.2.1 (`b2ce010e4ad59f6556c9ed60e2b2b30feccdd2d1`) as the licensed display renderer for broker, Nautilus and TCA views, with the NOTICE and attribution obligations kept ([ADR-0021](../../docs/adr/0021-tradingview-display.md)).

Acceptance is bounded: the initial four pine_check replies were not Desktop installs or saved scripts. Later records support two-run new-script/binding/compile and layout passes, but indicator-preset installation failed and retains an owner-manual/Pine fallback. Attributed installation of four files is not full persistence, input, chart or fill parity ([ADR-0026](../../docs/adr/0026-tradingview-sync-and-order-presets.md)).

**Rules.**
- No `strategy()`, `alert()` or `alertcondition()` path may reach an order; only the owner's hands do.
- Writes are non-destructive: new immutable scripts, never overwrite, rename or bulk-delete; the owner's layout is restored by numeric id; ambiguity or unsaved owner work stops acceptance.
- OAuth is RAM-only in this slice, with no persistence option or Keychain/file fallback; ADR-0021's optional Keychain exception is not implemented. Every session needs owner browser consent.
- The Desktop controller and local CDP exposure are host-specific owner acceptances, not portable authority; a Linux move needs a new exception ([ADR-0021](../../docs/adr/0021-tradingview-display.md)).

**Sources.** Harvested northstar-trading TradingView ADR-0014/0012 and its acceptance records at `8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`; official MCP and Pine documentation read 2026-11-05.

**Clean-distro implementation (#52).** `src/sextant/tradingview/` consumes the
producer's complete display unit and uses only official MCP membership tools.
The SDK's in-memory server proves diff/readback and refusal behavior. Four
dated Pine sources and their original/packaged hashes live in `presets/`.
Run `uv run --frozen python -m sextant.tradingview --presets lanes/tradingview/presets`
for local receipts; it makes no session or installation claim. The
[operating notes](../../docs/tradingview.md) hold the parameter registry, exact
sources, owner commands and outstanding acceptance. Linux auth has no
persistence option; every owner session needs browser consent. No unattended
service or Desktop controller is installed. The operational K2 ranking
registry is [`k2-ranking.params.json`](k2-ranking.params.json): the twelve
ranking rows with pinned sources, all UNCALIBRATED; the DISPLAY deployment
ages take the display registry's freshness bounds (600/1200/1200), so an
operational display registry builds from the file, while the trading/entry
deployment's ages stay UNAVAILABLE until sourced.
