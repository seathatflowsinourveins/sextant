# Native accounting: consume Money, not report display strings

[#129 R98](https://github.com/seathatflowsinourveins/sextant-archive/issues/129) replaces
the thin slice's report-string realized-P&L sum with native `Portfolio.realized_pnls`.
The API returns `dict[Currency, Money]`; the one-venue thin slice requests USDT,
reads that currency's Money as Decimal, and keeps the empty hold-flat result zero.
The adopted accounting rule is in [the manifest's engine row](../manifest.md).
The hash-bound EMA research card remains unchanged.

**Source:** NautilusTrader rc7 `55c0e82053142bce3a5cba4de4221d3929c2d3bc`,
`python/nautilus_trader/portfolio/__init__.pyi:60`,
`docs/concepts/accounting.md:276-282`, `docs/concepts/reports.md:224-275`.
After #87 advanced main, the same API and all replay comparisons were checked
again on rc8 `d53849b216e20f2c122ca01b4dd0da377638b186`: the same pyi at line 60,
`accounting.md:361-371` and `reports.md:224-275`; fixture bytes are unchanged.
Account scope and target currency belong to the native query. A display string
is presentation; converting it back to money invents an unnecessary accounting path.
NETTING reopens retain archived position cycles; partial closes realize P&L while
the live position stays open. Native accounting owns both cases.

**Witness:** `tests/proofs/test_native_realized_pnls.py` retains the removed sum
only as a test oracle from Sextant base `8e9e1d2c36d580de56da504b26c3f38715979d5c`.
The old collector fails when its display parser is forbidden; the native collector
passes. Compare before reset/disposal clears the engine's state. The pinned CSV
SHA-256 is `a90fd7b0a83d32190258651eca7ecb0ecdcaf3deb54f73a17ce028bfe49fdd74`;
local qualification reused cached bytes and denied sockets during replay.

Both rc7 and current-main rc8 give the following exact comparisons:

| Software witness | Old sum (USDT) | Native (USDT) | Difference |
|---|---:|---:|---:|
| EMA backtest | -0.48822178 | -0.48822178 | 0 |
| EMA later replay | -0.29792230 | -0.29792230 | 0 |
| Both hold-flat phases | 0 | 0 | 0 |
| Fabricated partial close, 6 left | 40 | 40 | 0 |
| Fabricated close/reopen, 7 left, one archived cycle | 130 | 130 | 0 |
| Fabricated two cycles, flat, one archived cycle | 270 | 270 | 0 |

These are accounting/software equivalence checks, not new strategy trials,
market data, calibration or trading merit. Acquisition HOLD and all size caps
remain unchanged. Revisit on a native accounting change, different currency/account
scope, or a recorded discrepancy; never restore a report parser as a fallback.
