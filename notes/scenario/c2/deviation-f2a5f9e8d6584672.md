# C2 fill-mechanism note: trade-triggered fills at the print

Attempt: lane scenario, issue #130, attempt c2, trials 201–224, 24 COMPLETE MODELED rows.
Outcome annotated: ledger commit `a7e980d3b16d55d532af50a516e73ef5c691e36d`; outcome rows SHA-256 `080533b955ee1cd4d8ea04c7ff564a1252818466147ce846bac54d194de65cbe`; manifest SHA-256 `8d23a8a23f6e61d0da28196d75c35d88602dd9153766b0878c988d44ddc2d40c`.
Protocol: `7acb54804f87f9b6d32aa0ec7258544c70a79ae2791972833c9dae0e00e23dd3`, §1 (fills).
Status: disclosed mechanism, ruled by the lead; no row changes.

## 1. Mechanism

`src/sextant/research/c2_run.py:466-479` at `a6e5b932b7ea34b5ab1debb19243562ad8e33044` builds the venue on NautilusTrader's defaults, `book_type=L1_MBP` and `trade_execution=True` (neither is passed explicitly). The pinned docs — `nautechsystems/nautilus_trader@v2.0.0rc8` commit `d53849b216e20f2c122ca01b4dd0da377638b186`, `docs/concepts/backtesting/trade-execution.md:3` and `:49` — say that trade ticks trigger matching and that "L1 trades update both simulated top-of-book levels to the trade price and size". So every market order submitted from `on_trade` filled at the triggering print, not at the ask or bid in force.

## 2. Per-case gaps

Entries (first print vs the ask in force at that print):

- A: entry `3.725` vs ask `3.73` (−13.4 bps).
- B: entry `4.46` vs ask `4.99` (−10.62%).
- C: entry `160.583` vs ask `160.59` (−0.44 bps).

Fixed-trail MARKET exits (fill vs the last bid at or before the trigger):

| case | arm | trigger (ET) | fill | bid in force | fill − bid |
|---|---|---|---|---|---|
| A | trail-0.1 | 2026-11-03 09:30:00.052 | 3.72 | 3.72 | 0 bps |
| A | trail-0.25 | 2026-11-03 09:30:00.052 | 3.72 | 3.72 | 0 bps |
| A | trail-0.5 | 2026-11-03 09:30:00.057 | 3.72 | 3.72 | 0 bps |
| A | trail-2.5 | 2026-11-03 09:30:02.230 | 3.8375 | 3.86 | −58.3 bps |
| B | trail-0.1 | 2026-10-27 09:30:14.178 | 4.31 | 3.40 | +2676.5 bps |
| B | trail-0.25 | 2026-10-27 09:30:14.178 | 4.31 | 3.40 | +2676.5 bps |
| B | trail-0.5 | 2026-10-27 09:30:14.178 | 4.31 | 3.40 | +2676.5 bps |
| B | trail-2.5 | 2026-10-27 09:30:14.178 | 4.31 | 3.40 | +2676.5 bps |
| C | trail-0.1 | 2026-10-21 09:30:00.202 | 160.42 | 160.42 | 0 bps |
| C | trail-0.25 | 2026-10-21 09:30:00.355 | 160.18 | 160.18 | 0 bps |
| C | trail-0.5 | 2026-10-21 09:30:01.711 | 159.78 | 159.80 | −1.3 bps |
| C | trail-2.5 | 2026-10-21 09:37:13.860 | 158.72 | 158.71 | +0.6 bps |

Inputs, the trades and quotes parquet read for these timestamps (SHA-256):

- A: trades `data/trades/PARA.ALPACA/2026-11-03T09-00-00-046382000Z_2026-11-03T14-45-17-713547000Z.parquet` `bed3b6b9fc92eb41a700b2ee706498437f09ff93365dd0defd22d5f2dcf8cd94`; quotes `data/quotes/PARA.ALPACA/2026-11-03T09-00-00-013619000Z_2026-11-04T00-59-50-854260000Z.parquet` `0916c29b574c391416fba33cb3d873b280075c2dab02efc989cd288444fc1501`.
- B: trades `data/trades/PARA.ALPACA/2026-10-27T13-04-17-470232000Z_2026-10-27T23-59-54-291207000Z.parquet` `7d8ad5a4d257b558829b08d7d9020dcdd539001e36d22e00f044c1dc2296e8a2`; quotes `data/quotes/PARA.ALPACA/2026-10-27T13-00-00-001392000Z_2026-10-27T23-59-34-429884000Z.parquet` `86e2c5b5fc115c948ce25bd4981e62b1d78de5330ccfa41725f2a0332bb30335`.
- C: trades `data/trades/SPCX.ALPACA/2026-10-21T08-00-00-014636000Z_2026-10-21T12-45-28-309637000Z.parquet` `7ee971b941eeabe1b9b513774545cb17a3f37bc98682855e069788e9ecedb9ac`; quotes `data/quotes/SPCX.ALPACA/2026-10-21T08-00-00-004701000Z_2026-10-21T13-41-31-208685000Z.parquet` `3b5f9b8d75b2ee168e80740452564b074d9e13669d00d9bae5b7bfedc3df02c3`.

## 3. Effect

In B, the entry print (`4.46`) is 10.6% below the ask in force (`4.99`), and the four fixed-trail exits (`4.31`) are 26.8% above the last bid in force (`3.40`). Every holding arm's return against hold-flat on B is therefore inflated by the entry gap, and the fixed trails' returns are inflated further by their exit gap. C2's arm 1 on case B (`+1.96%`) differs from C1's trial 162 (`−32.72%`) through this fill mechanism, not through the arming rule: C1 entered at the ask `4.99` and exited at the wide bid `3.36`; C2 entered at the print `4.46` and exited at `4.55`, the bid in force from the 11:34:12.311 quote (`4.55` / `4.74`); no trade printed at that moment. No counterfactual P&L is computed here.

## 4. Storage format, not a deviation

`daily_net_returns` and `condition_returns` follow the adopted TrialLog's float64 schema (`src/sextant/validation/trials.py:71`); they are ratios, not money. `result` keeps the exact Decimal strings, money stays Decimal, and `result` satisfies the protocol's "Decimal strings only".

This note changes no row and adds no trial; N is unchanged by it.
