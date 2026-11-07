# Research card: EMA cross on ETHUSDT trade ticks

**Status:** thin-slice seed. It proves the trading path, not an edge.

**Registry:** `nautilus-ema-cross` in `research/sources.yaml`. Source `knowable_at`:
`2026-11-06T15:28:06+00:00` (this audit's observed version, not a historical trading clock).
Historical input `knowable_at`: **unknown**. The 2020 fixture is neither a US-equity
universe nor evidence of pre-ignition availability. New compute admission: **false**;
OSAP/JKP and the HXZ screen have not been completed for a US-movers hypothesis.

**Source:** nautechsystems/nautilus_trader@v2.0.0rc7 (`55c0e82053142bce3a5cba4de4221d3929c2d3bc`, LGPL-3.0)
- Strategy: `docs/tutorials/ema_cross.py`, verbatim in `src/sextant/strategies/ema_cross.py`.
- Run: `examples/backtest/crypto_ema_cross_ethusdt_trade_ticks.py`, adapted in `src/sextant/backtest/thin_slice.py`.
- Data: `test_data/binance/ethusdt-trades.csv` at that tag, read by the engine's own `TestDataProvider`.

**Method, and where each part comes from:**
- The upstream example's parameters are unchanged: 250-tick bars, EMA 10 and 20, trade size 0.10.
- Two windows of the file's time span, with the engine's own `run(start, end)`, and repeat runs on the loaded data with its `reset()`: `docs/concepts/backtesting/apis-and-runs.md` at the tag above. The example itself runs the whole file once.
- The second window is the plan's sim replay over a later stretch of the same file. It is not an out-of-sample test, because nothing is fitted and it is one file.
- The control is hold-flat, the same engine with no strategy: northstar-lanes@`00203275944a22655b3e14b221cfde9a265d549a`, `docs/adr/0003-philosophy-and-operating-principles.md`, P7 and P8, and the owner-approved plan's Phase 2.
- Strategy and hold-flat attempts enter one `reports/research/trials.parquet`, with the original 13-column schema and explicit MODELED tier. Native PortfolioStatistic/TradeCount includes archived NETTING cycles (8 backtest, 6 replay). Native fills and tearsheets have distinct per-run directories.
- The custom merit calculator, inference, DSR/PBO/CPCV and paper/PIT gates are deferred to #147 under the owner's size ruling. Code binding remains UNVERIFIED. Native statistics confer no admission or session qualification. [Writer-slice evidence](../../docs/research/2026-11-06-ledger-merit.md).

**Measured (`just slice`, 2026-11-06):**

| Window | Fills | Realized P&L (USDT) | Hold-flat (USDT) |
|---|---|---|---|
| Backtest | 16 | -0.48822178 | 0 |
| Replay | 12 | -0.29792230 | 0 |

**Reading:** it loses to hold-flat on both windows, over five hours of one day in 2020. That is too little data to say anything about the strategy, so it earns no merit and stays in sim. Walk-forward, CPCV, DSR and PBO are Phase 4, and no edge is claimed before them.
