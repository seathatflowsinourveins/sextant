# NautilusTrader rc8 feature and migration checklist

Read date: **2026-11-06**. rc7 is
`55c0e82053142bce3a5cba4de4221d3929c2d3bc`; rc8 is
`d53849b216e20f2c122ca01b4dd0da377638b186` (tag dereferenced through GitHub).
The [upstream release](https://github.com/nautechsystems/nautilus_trader/releases/tag/v2.0.0rc8)
describes October 28; GitHub's publication clock is **2026-10-29T04:55:25Z**.
These are distinct clocks. This PR changes no engine pin or trading code.

## What the focus uses and still needs

This is **static source inspection**, not deployment evidence. Sextant means
the dispatched base `4ba1291e7992ed083256669f2e8e47f32f8afb57`, principally
`src/sextant/backtest/thin_slice.py` and the verbatim EMA strategy. Old means
`northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`; paths below are
within `src/northstar_trading/`. Presence of a config does not prove a service
is running or a venue supports the feature.

| Native feature | Sextant base | Old source evidence | Role / remaining work |
|---|---|---|---|
| Strategy, cache, event clock, MessageBus | EMA strategy/cache | Strategies and nodes | Keep the native execution/replay core; do not add a second event engine |
| BacktestEngine, run windows and reset | Used by thin slice | `backtest/runner.py`, `catalog_runner.py` | Retain the native runner; later catalog campaigns need separate evidence |
| BacktestNode and typed historical requests | Not used in thin slice | Source inventory/landscape leg reports catalog runners | Batch/catalog runs and native completion replace equivalent local coordination; no new runner installed here |
| Trade/quote ticks and aggregation; L1/L2/L3 books | Trade ticks become 250-tick bars | Tick replay and recorded-snapshot fill bridge | Trades/quotes serve onset and fills; depth requires a named input-backed consumer |
| DataActor/custom data, subscriptions | Not used for a scanner | `scanner/s2_tap.py`, catalyst actors in source inventory | In-node ranking/catalysts; no scanner/feed-owner transfer performed |
| Data/execution adapters | Binance constant and test data only | `nodes/ibkr.py`, separate Alpaca integration | IBKR/Databento roles are relevant; Alpaca is not a bundled rc8 adapter |
| MARKET, LIMIT, MARKET_TO_LIMIT, STOP_MARKET, STOP_LIMIT, MARKET_IF_TOUCHED, LIMIT_IF_TOUCHED, TRAILING_STOP_MARKET, TRAILING_STOP_LIMIT | EMA market orders only | Exit manager/protection orders | Source capability is not venue/session qualification or authority to use a type |
| TIF, reduce-only, post-only, OTO/OCO/OUO | No advanced use | Exit protection and custody code | Native contingency semantics can replace equivalent mechanics, not ownership policy |
| OrderEmulator and BID_ASK/LAST_PRICE triggers | Not used | `backtest/catalog_runner.py`, `strategies/exit_manager/protection.py` | Reuse native trailing/release; node/feed availability and acknowledged residual protection remain necessary |
| ExecutionAlgorithm and TWAP | Not used | Earlier leg found no substantive registration; not independently exhaustive here | Optional sourced size slicing; no urgent-exit delay or custom algorithm selected |
| RiskEngine states, validation, rate limits | Explicit **bypass=True** in isolated demonstration | `backtest/runner.py` uses RiskEngineConfig | No production admission inferred from the demo; native risk checks do not replace custody or the account-wide pacer |
| Fill, latency, fee and margin models | Default matching; MakerTakerFeeModel and CASH/Decimal | `backtest/runner.py`: DefaultFillModel, static **1 ms** latency, IbkrFixedFeeModel, StandardMarginModel; `catalog_runner.py`: SnapshotFillModel | These are configured assumptions; no measured 1 ms latency or calibrated slippage is claimed |
| ParquetDataCatalog/typed queries/DataFusion | Not used by thin slice | `data/catalog.py`, catalog runner | One native catalog remains the storage target; preserve raw source/coverage/receipt evidence |
| StreamingConfig, rotation and catalog promotion | Not used | `nodes/ibkr.py` streaming configuration | Capture candidate; staging/promotion is not an atomic historical snapshot or proof of complete fills |
| SandboxExecutionClient/native matching | Not used | `sim_lanes/sandbox.py` in source inventory | Selected sim role; qualification remains separate from broker execution fidelity |
| Reconciliation, order/fill/position reports | Not used | IBKR node and protection handovers | Reuse native mechanisms while retaining adapter/custody gaps and ACK lineage |
| Portfolio/accounting, statistics, tearsheets | Position checks, realized report and native tearsheet | Portfolio/cache reads; source inventory's snapshot actor | Prefer native accounting/reporting where semantics agree; retain cumulative trials and independent statistical gates |
| Options models/chains/Greeks/settlement | Not used | Earlier leg found no substantive native-chain use | Research/sim only; early exercise, DNE, assignment/capacity and adapter support remain unverified |

The rc8 [integration index](https://github.com/nautechsystems/nautilus_trader/blob/d53849b216e20f2c122ca01b4dd0da377638b186/docs/integrations/index.md)
lists AX, Betfair, Binance, Blockchain, Bybit, Coinbase, Databento, Deribit,
Derive, dYdX, Hyperliquid, IBKR, Kraken, Lighter/Robinhood, OKX, Polymarket and
Tardis as stable, CoinAPI as beta, and FinFeed/Kalshi as building. This inventory
does not justify deploying unrelated venues.

## rc8 changes that require a migration review

| Upstream change | Required disposition before an engine bump | Status here |
|---|---|---|
| Batched subscriptions, historical instrument/quote/trade requests, request groups/join, completion callbacks, catalog write-back | Reconcile actor/adapter response shapes, partial failure and coverage completion using upstream contracts | **Pending**; no migration |
| `BacktestDataConfig.catalog=DataCatalogConfig(...)`; typed batches/envelopes; fallible ReplaySource/DataIterator frontier states | Review all catalog/runner consumers and rerun upstream-compatible persistence/replay regressions | **Pending** |
| Parquet row-loss/promotion fixes, replay/statistics/timer fixes | Validate data round trips and deterministic replay at the candidate pin; a release note is not an artifact receipt | **Pending** |
| Emulated releases go through RiskEngine | Protective release can be **DENIED** in HALTED and has no automatic retry; REDUCING permits only qualifying reduce-only submissions with an identified position | **Verified source behavior; integration pending**; do not bypass risk |
| Python-subclassable command/time-aware latency and custom fill/margin models; sandbox custom fees | Review keyword/API changes and measured cost inputs; preserve Decimal/engine money | **Pending**; no default model calibrated |
| Exact fractional Money construction/persistence and commission accumulation | Check money/balance/fee round trips across actual consumer boundaries | **Pending** |
| Embedded Python strategies/execution algorithms, external MessageBus data requests/replies | Use only where a named lane consumer benefits; not required merely because the API exists | **Not selected here** |
| IBKR base currency, reconnect controls, quote-size/price-magnifier and runtime instrument fixes | Candidate-pin adapter regression and later authorized venue qualification | **Pending**, no broker probe |

Primary sources at the rc8 SHA: [orders](https://github.com/nautechsystems/nautilus_trader/blob/d53849b216e20f2c122ca01b4dd0da377638b186/docs/concepts/orders/index.md),
[emulated orders](https://github.com/nautechsystems/nautilus_trader/blob/d53849b216e20f2c122ca01b4dd0da377638b186/docs/concepts/orders/emulated.md),
[catalog](https://github.com/nautechsystems/nautilus_trader/blob/d53849b216e20f2c122ca01b4dd0da377638b186/docs/concepts/data/catalog.md),
[fill models](https://github.com/nautechsystems/nautilus_trader/blob/d53849b216e20f2c122ca01b4dd0da377638b186/docs/concepts/backtesting/fill-models.md)
and the release above. The eleven documented fill-model choices include default,
best-price, slippage, probabilistic, tiered, partial-fill, size/competition/volume
and market-hours variants. Synthetic liquidity and software defaults are not
measured executable liquidity; some Python model state setters are unavailable.

**Disposition:** retain the existing engine and pin; carry this checklist into
the engine owner's separately sourced upgrade PR. Native mechanics do not
supply an extreme-mover predictor, first-non-noise classifier, gain-lock
economics, raw-data provenance or trading merit. No engine migration,
installed rc8 run, paper handover, new order type or live admission is claimed.
