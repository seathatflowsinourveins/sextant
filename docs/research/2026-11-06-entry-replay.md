# Entry replay: build-order row 6

Issue [#51](https://github.com/seathatflowsinourveins/sextant/issues/51), ADR-0004 and ADR-0011. This is a synthetic mechanism proof in NautilusTrader replay, labelled MODELED and fixture-only. It is not an economic experiment, calibration, broker-capability receipt or operational-latency measurement.

## Minimal carry

Sources were read on 2026-11-06 through GitHub at immutable commits, and against the installed rc7 API. No old lane or service was contacted.

| Source | Carried behavior |
|---|---|
| `northstar-lanes@00203275944a22655b3e14b221cfde9a265d549a:docs/adr/0005-entry.md` N1/N2/N4/N5 | The accepted house first-leg, extension, held-reclaim and order policy. The source explicitly says no vendor first-leg/extension/reclaim policy exists; this carries that accepted decision, not a new setup. |
| `northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:src/northstar_trading/strategies/premarket_gap/first_leg.py` `_run`, `breakout` | Non-decreasing run, lower-trade restart, quiet-price and ask cap, causal/duplicate/stale-trade checks and non-renewing surge anchor. |
| Same pin, `entry_sizing.py` `size_entry`, `refresh`; `src/northstar_trading/persist.py` | Frozen account/segment buying-power basis; labelled first read; native FixedRiskSizer, honest stop plus one chase allowance, confidence/stop-out multipliers, funding/flow caps, whole-share refusal; atomic file/fsync/rename/directory-fsync persistence. |
| `nautilus_trader@55c0e82053142bce3a5cba4de4221d3929c2d3bc:crates/indicators/src/volatility/atr.rs`, `average/rma.rs` | True range against previous close, SMA seed over `atr_period` bars and the default Wilder recurrence. The same formulas use Decimal on native Bar prices. The installed floating indicator gives `0.1999999999999993` for the fixture's exact $0.20 range, which otherwise misclassifies equality at the extension boundary. |
| Same Nautilus pin, native Strategy/OrderFactory/BacktestEngine/clock/cache/risk APIs and `crates/risk/src/sizing.rs` | One native plain LIMIT, DAY, at the rounded ask; serialized price changes, initial-price chase cap, setup cap recheck, TTL cancellation and late-acknowledgement continuation. RiskEngine remains `bypass=False`. |

## Inputs and authority

`lanes/sim/entry-parameters.json` is the row-6 registry inventory: every row has units, source, calibration state and last-change date, with an unavailable value. It supplies no deployment defaults. In particular the six missing first-leg/extension/chase/TTL starts remain unavailable. A registry with absent authority, values or metadata is refused. Test rows explicitly say FIXTURE_ONLY and require the fixture opt-in; outputs retain their parameter hash.

The boundary consumes native eligible trades/quotes/completed bars for one instrument, an explicit segment identity, a causal source-labelled surge, a source-labelled complete flow interval for reclaim, an explicit protection buffer, and an explicit fee model. A producer's coverage assertion is an input, not verified data acquisition. ATR initializes only from that symbol's configured completed bars. VWAP, surge and reclaim reset explicitly at the segment boundary; ATR history may span segments.

The replay entry basis comes from the native simulated account, is persisted with account/segment/parameter identity and a `node_start` label, and survives a restart without a new buying-power read. Corrupt or mismatched state is not replaced. Fresh free cash and recent eligible dollar volume bound each initial order and reprice. A first-leg intent is unscored; scored reclaim requires explicit confidence. This one-entry process has no previous stop-outs; the sizing boundary also tests explicit stop-out histories.

## Witnesses

Run under the host memory floor, one process at a time:

```sh
timeout 180 uv run --frozen pytest tests/proofs/entry
```

- A lower third trade prevents entry until three trades after the restart; the real native replay submits once at the fifth trade.
- Missing ATR stays UNKNOWN, cannot create an extension episode and fails the not-extended admission predicate. Only the symbol's completed bars warm it; wrong symbol/timeframe and future/duplicate/stale trades cannot supply authority. Equality at the ATR extension threshold remains NOT_EXTENDED.
- A reclaim needs this episode's later VWAP touch, three reclaim trades, a pullback, a higher low, a hold and the first subsequent rising trade within the ask cap. A lower trough restarts the hold; a new high before it completes needs a new pullback. No causal complete flow receipt means no native reclaim order.
- That first eligible trade consumes the held retest even when entry is refused. The missed-first-chance witness rejects later fresh highs and requires a new pullback and hold before another event; native replay covers the late-fill scenario from review #5803215352.
- Native sizing counts chase once and respects fresh funding/flow bounds, rejects missing terms and sub-share quantities, applies scored confidence, and never assigns confidence 1 to an unscored setup.
- After a partial fill, reprice risk and flow caps apply to the full order; fresh buying power funds only its leaves. The native `LimitOrderPartialFillModel` supplies an explicit synthetic partial-fill book for these witnesses, including a funded remainder that may still reprice. This is not a liquidity estimate.
- Native order events prove one fill or a terminal cancel. Reprices retain the initial chase bound and the setup cap. TTL during an unacknowledged submit stays pending until acceptance, then cancels that entry. Extended-hours intent remains a plain LIMIT with no contingency.

## Boundaries still open

This is one explicit segment/entry episode, with synthetic source and coverage assertions. Production ranking freshness, surge detection, eligibility/catalyst producers, calendar segmentation, negative-catalyst admission, accumulation/breakout allocation, account reconciliation and stop-out lifecycle wiring belong to their later integrations. It creates no broker client, market-data stream, retry/rotation allocator, trial ledger or automation. Economic arm runs must await canonical TrialLog custody; regression proofs claim no edge or trial count.

Historical INO ATR pre-roll, VRDN/BURU skipped-entry tapes, executable-cost calibration and the after-cost first-leg edge remain unavailable. Zero fees in order-lifecycle fixtures are explicit test inputs, never a cost estimate. Outside-RTH flags are recorded submission intent; Alpaca serialization and session acceptance remain unverified until row 8's minimal bridge slice is identified and tested. Row 8's custody/pacer/guard/halt drills are not implemented here. Lessons are proposed in this PR body for the lead's single-writer handbook update.
