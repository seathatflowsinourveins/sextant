# Candidate history: seed reconciliation and the blocked PIT extension

Issue [#42](https://github.com/seathatflowsinourveins/sextant-archive/issues/42), design row 4. Research only; no orders, endpoint calls, streams or broker-key use. This completes the seed audit, **not** the all-stock candidate history. #42 stays open.

## Sources and minimal slice

Read 2026-11-06. The archive is an owner-supplied seed under [ADR-0027](../adr/0027-extreme-gainer-research-package.md), never an implementation upstream. The audit adapts the CSV recount already recorded in [the package evidence](2026-11-06-extreme-gainer-package.md#event-selection-and-trading-day-coverage). Parsing, exact strings, missing fields, ZIP member reads and SHA-256 use the runtime's documented APIs: [Python 3.13 CSV](https://docs.python.org/3.13/library/csv.html), [ZIP](https://docs.python.org/3.13/library/zipfile.html), [hashlib](https://docs.python.org/3.13/library/hashlib.html), [JSON](https://docs.python.org/3.13/library/json.html).

Pinned carry inventory: [northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa](https://github.com/seathatflowsinourveins/northstar-trading/tree/8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa):

| Source | Application here |
|---|---|
| `src/northstar_trading/data/alpaca_history.py:publish_once` | Adopt its temporary-file/hard-link publication for immutable research receipts; identical reruns are idempotent and different bytes refuse. No REST client copied. |
| `data/universe.py:UniverseMember,DatedUniverse`; `data/sharadar.py:SharadarUniverse` | Inspect only. Share-class identities, nonoverlapping dated ticker intervals and economic versus historical knowledge time remain prerequisites. No universe inferred from event rows or prices. |
| `validation/trials.py:TrialLog,canonical_trial_log,inference_view` | Inspect only. The cumulative ledger remains the upstream TrialLog, with frozen counts and separate tiers. No new ledger/writer introduced. |
| `docs/research/2026-11-05-extreme-movers-onset.md`, R03/R18/R22 | Onset clocks and hindsight outcomes are distinct. No upstream method/template meets the literal extreme-mover-at-onset job in the admitted stack. No detector or threshold is built here. |

The minimal implementation is `src/sextant/research/candidate_history.py` plus its package marker (322 measured lines). It uses only the standard library. No tunable, fitted value, strategy, membership provider or feed integration is added. The remaining upstream components are deliberately inventoried rather than copied without their data, dependencies and acceptance receipts.

## Reproduce

The archive stays outside git. Use a new output directory for a different implementation SHA; existing different bytes refuse. The CLI requires a committed, clean research implementation so receipts name the actual code, and also hashes its source bytes.

```sh
gh release download seed-research-2026-10-09 --pattern extreme-gainer-grand-package.zip --dir /tmp/sextant-seed
uv run --frozen python -m sextant.research.candidate_history /tmp/sextant-seed/extreme-gainer-grand-package.zip reports/candidate-history/seed-audit
uv run --frozen pytest tests/proofs/test_candidate_history.py
```

The archive must match full SHA-256 `f581ca7f771bf20ef05e212ce88aaaacda7325c640500d63926b23a0516d0577`; there is no CLI override. It is read without extracting or executing package files. Duplicate members/columns/event keys, ragged CSVs, missing forward-overlay keys, unmatched aliases and dates outside the observed calendar refuse. Raw CSV field strings, row identities, aliases and recovered overlays are retained without rewriting tickers or imputing returns. The original correction CSV is copied byte for byte as annotation evidence, without inferring joins from its prose.

`events.jsonl` retains all selected events. `summary.json` records input bytes/hashes, per-column blank counts, source periods, selection, biases, coverage and a digest of all artifacts. `sessions/<date>.json` exists for every observed SPX date, including dates without seed events; each binds the archive hash, implementation SHA/source hash, selected-row hash and input-member names. The root summary hashes every session receipt. The SPX dates are the archive's observed denominator, not newly exchange-verified sessions. These receipts are research metadata, outside the one Nautilus market-data catalog.

## Recount

| Year | Gainer events | Gainer dates / observed SPX dates | Selected-loser events / dates |
|---|---:|---:|---:|
| 2021 | 52 | 52 / 252 | 52 / 52 |
| 2022 | 52 | 52 / 251 | 52 / 52 |
| 2023 | 51 | 51 / 250 | 52 / 52 |
| 2024 | 279 | 235 / 252 | 24 / 23 |
| 2025 | 281 | 241 / 250 | 26 / 24 |
| 2026 through September 22 | 242 | 176 / 181 | 9 / 9 |

Total: **957 gainers on 807 dates; 215 selected losers; 1,436 observed calendar dates**. Weekly leaders remain separate from daily leader collections; recent losers remain selected collapses. The recent gainer CSV has **417** distinct dates, preserving its disagreement with the README's 416. These are coverage counts, not pre-move recall or predictive evidence.

Forward status remains **686 OK / 265 NO_DATA / 6 EVENT_BAR_MISSING**. Eight exclusion flags leave 678 OK analysis rows, with only **671 / 662 / 646** observed T+1 / T+5 / T+20 returns. All missing strings and exclusion prose survive; no returns are recomputed. The alias annotations cover the 265 missing events; the separate recovery supplement has 77 rows. Neither establishes dated identity or clears a delisting gate. [The earlier evidence note](2026-11-06-extreme-gainer-package.md) supplies the original interpretation and negative findings.

## Why the extension stops

The [issue progress/blocker record](https://github.com/seathatflowsinourveins/sextant-archive/issues/42#issuecomment-6687528843) records the source/input check. No master/actions export, transferred Sharadar scope/rights receipt, independent delisting-sample manifest, scanner-day archive or canonical TrialLog was found in this clean checkout. GitHub's `ledger` tree lookup returned 404 on 2026-11-06. This does not inspect or assume anything about the old lanes' disks/services.

[Alpaca's historical-bars API](https://docs.alpaca.markets/us/reference/stockbars), read 2026-11-06, exposes raw adjustments, pagination and a symbol `asof` date. It does not supply the non-Alpaca dated master required by [ADR-0013](../adr/0013-us-equity-data-stack.md). Price queries against today's symbols cannot settle the missing all-stock membership, delisted denominator or ordinary controls. No keyed REST call is useful for that missing prerequisite, so none was made. No vendor is selected or bought; the owner must resolve owned Sharadar scope/rights versus purchase under #29 §5.

The next implementation needs:

1. Source-labelled master/actions/identity exports and coverage/rights receipts; all 10 probed exits, at least 95% of the frozen independent delisted sample, recycled-ticker/asof checks and the first replacement backtest. `survivor_only: true` persists until recorded acceptance, even if a vendor name is present.
2. The source-backed, frozen ordinary-control and pre-ignition protocol, with actual first-print, flag, publication/receipt and decision clocks. A calendar date or retrospective outcome cannot fill `known_at`. The upstream onset convergence is REDESIGN-NEED; Rule 1 stops unsupported label/control construction.
3. The actual scanner archive and canonical cumulative TrialLog/custody. Bind source/data/code, controls, attempted alternatives and the frozen cumulative N/effective-N snapshot through that upstream, retaining separate MODELED/SIMULATED/BROKER-PAPER tiers and [ADR-0019](../adr/0019-validation-and-merit.md)'s stressed-cost gates.

Until then the receipts use null security IDs, availability clocks, ordinary-control counts, pre-ignition labels and ledger bindings; `pit_verified: false`, `inference_eligible: false`. **Zero new strategy trials** means this metadata audit ran no strategy; the seed's historical total and cumulative/effective N stay unknown, never zero. No statistical merit, backtest, survivorship-free universe or completed row 4 is claimed.

The [handbook lesson](../handbook/candidate-history.md) and its practice prevent unselected dates, selected losers and missing clocks from becoming invented negatives or PIT evidence. Offline proof cases cover mixed dialects, multiline/blank fields, selected-cohort separation, alias identity, refusal of corrupt inputs, immutable reruns and unselected-session receipts. The [real-archive receipt](2026-11-06-candidate-history-receipt.json) binds implementation `007c98736036aa145e87d1ab60b53ea603be6081`, its source bytes, input hashes and the complete artifact digest. It retains counts/hashes for unrepresented-date arrays; the complete arrays and artifact index remain in the refetchable `summary.json`. Its `verified_at` is this audit's clock, never historical feature availability.

## Verification

- `just ci`: passed, including 56 tests, Ruff/format, Pyright, zizmor, actionlint and gitleaks. The native distro lacked gitleaks/actionlint, so repository-pinned release binaries were hash-verified against `.devcontainer/Dockerfile` and used from temporary storage for this command; no host setup changed.
- New manifest proof: 10 passed offline, without a key or the release download.
- Real pinned archive: CLI passed and an identical rerun passed. Independently checked the expected yearly event/date counts, all 11 input-member hashes, all 1,438 artifact hashes and all 1,436 session selected-row hashes. All 1,172 events survive; 496 calendar dates have no seed event and remain unselected/unobserved. The full archive and generated event/session files stay outside git. No strategy trial or ledger write occurred.
- Full proof collection in the native distro: 59 passed, 3 failed. Two existing container assertions expect a private-route firewall and restricted sudo; this dedicated distro intentionally has native networking and passwordless sudo (`docs/start.md`). The third was gitleaks absent from that command's PATH; its focused rerun with the temporary pinned binary passed (1 passed). Required checks and proof assertions are unchanged. Container-only acceptance is not newly claimed here.
