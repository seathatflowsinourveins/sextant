# Research card: EMA cross on ETHUSDT trade ticks

**Status:** thin-slice seed. It proves the trading path, not an edge.

**Source:** nautechsystems/nautilus_trader@v2.0.0rc7 (`55c0e82053142bce3a5cba4de4221d3929c2d3bc`, LGPL-3.0)
- Strategy: `docs/tutorials/ema_cross.py`, verbatim in `src/sextant/strategies/ema_cross.py`.
- Run: `examples/backtest/crypto_ema_cross_ethusdt_trade_ticks.py`, adapted in `src/sextant/backtest/thin_slice.py`.
- Data: `test_data/binance/ethusdt-trades.csv` at that tag, read by the engine's own `TestDataProvider`.

**Method, and where each part comes from:**
- The upstream example's parameters are unchanged: 250-tick bars, EMA 10 and 20, trade size 0.10.
- Two windows of the file's time span, with the engine's own `run(start, end)`, and repeat runs on the loaded data with its `reset()`: `docs/concepts/backtesting/apis-and-runs.md` at the tag above. The example itself runs the whole file once.
- The second window is the plan's sim replay over a later stretch of the same file. It is not an out-of-sample test, because nothing is fitted and it is one file.
- The control is hold-flat, the same engine with no strategy: northstar-lanes@`00203275944a22655b3e14b221cfde9a265d549a`, `docs/adr/0003-philosophy-and-operating-principles.md`, P7 and P8, and the owner-approved plan's Phase 2.
- The ledger row is the engine's own `BacktestResult`, plus the window and the source. The trial ledger and its gates arrive in Phase 4.

**Measured (`just slice`, 2026-11-06):**

| Window | Fills | Realized P&L (USDT) | Hold-flat (USDT) |
|---|---|---|---|
| Backtest | 16 | -0.48822178 | 0 |
| Replay | 12 | -0.29792230 | 0 |

**Reading:** it loses to hold-flat on both windows, over five hours of one day in 2020. That is too little data to say anything about the strategy, so it earns no merit and stays in sim. Walk-forward, CPCV, DSR and PBO are Phase 4, and no edge is claimed before them.
