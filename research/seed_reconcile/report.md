# Seed reconciliation: selected extreme-gainer package

Date: 2026-11-09. Branch: `research/seed-reconcile`, audited script commit `5decd2a`
on checkout head `695bc7c`. Research-only metadata audit; no feed, strategy, order,
broker key or TrialLog.

## Authority and scope

Wave W1 asks for the owner's grand package to be reconciled: reproduce 957 gainers
and 215 losers, the 2021-2023 weekly leaders and 2024-2026 daily leader collections,
coverage per year, the 417-vs-416 date note, per-session manifests with data hashes
and bias labels, each with its knowable-at clock, and a scanner-archive inventory
by reference only ([W1 brief](file:///home/sextant/sextant-data/handoffs/wave-all-lanes/W1/BRIEF.md),
sha256 `c5362281bdbe76c24f9d4c82b153921b7ab9e10ea5cc93226d876015c316ea5f`;
[wave plan](file:///home/sextant/sextant-data/handoffs/wave-all-lanes/WAVE.md),
sha256 `1874aa6d9b8089fcd7e6c53164f862a64fe5cae1ce87a7cc55aa70f3d8e2b944`).

The package is `/home/sextant/sextant-data/sharadar-42/seed/extreme-gainer-grand-package.zip`,
5,485,433 bytes, sha256 `f581ca7f771bf20ef05e212ce88aaaacda7325c640500d63926b23a0516d0577`,
prefix-matched against `docs/design.md:62` and row 4 (`docs/design.md:141`). The
release is `seed-research-2026-10-09` ([ADR-0027](../../docs/adr/0027-extreme-gainer-research-package.md)).
The package was read in place; nothing was extracted into the repository.

This report closes W1's acceptance: **a reproducible script on `research/seed-reconcile`
whose counts match the package, with `survivor_only` still true.** It does not clear
row 4's remaining work: dated membership, delisted identities, ordinary non-mover
controls, pre-ignition labels and actual event clocks remain absent, and are recorded
as blockers rather than filled ([ADR-0013](../../docs/adr/0013-us-equity-data-stack.md),
[ADR-0019](../../docs/adr/0019-validation-and-merit.md),
[package evidence](../../docs/research/2026-11-06-extreme-gainer-package.md)).

## Reproduce

```sh
uv run --frozen --offline python research/seed_reconcile/manifest.py \
  /home/sextant/sextant-data/sharadar-42/seed/extreme-gainer-grand-package.zip \
  /home/sextant/sextant-data/handoffs/wave-all-lanes/W1/scratch/seed-reconcile
```

Observed output:

```json
{"artifacts": 1438, "artifacts_sha256": "672723696827a4a1ca2c6f81ad6c418659ef06bb76f8e4e0aba35b2c7f032d0b", "events": {"selected_gainer": 957, "selected_loser": 215}, "sessions": 1436, "survivor_only": true}
```

The script refuses any archive whose SHA-256 differs (verified with a non-package
input: exit 1, `Seed archive SHA-256 differs from ADR-0027`). A second run against
the same output is byte-identical; `publish_once` fails on conflicting bytes and
accepts only identical reruns.

## Counts

| Year | SPX sessions | Gainer selection | Gainer events | Gainer dates | Share | Loser selection | Loser events | Loser dates | Share |
| --- | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| 2021 | 252 | weekly_leader | 52 | 52 | 20.6% | weekly_selected_collapse | 52 | 52 | 20.6% |
| 2022 | 251 | weekly_leader | 52 | 52 | 20.7% | weekly_selected_collapse | 52 | 52 | 20.7% |
| 2023 | 250 | weekly_leader | 51 | 51 | 20.4% | weekly_selected_collapse | 52 | 52 | 20.8% |
| 2024 | 252 | daily_leader_collection | 279 | 235 | 93.3% | selected_collapse | 24 | 23 | 9.1% |
| 2025 | 250 | daily_leader_collection | 281 | 241 | 96.4% | selected_collapse | 26 | 24 | 9.6% |
| 2026 | 181 | daily_leader_collection | 242 | 176 | 97.2% | selected_collapse | 9 | 9 | 5.0% |
| **Total** | **1,436** | | **957** | **807** | | | **215** | **212** | |

Gainers run 2021-01-06 through 2026-09-22; losers run 2021-01-08 through 2026-09-03.
Of the 1,436 observed sessions, 940 contain at least one seed event and 496 contain
none. Absence is labelled `not_selected_or_unobserved; never no_movers`, not a
negative sample.

Shares are dates divided by the package's observed SPX session list, not all-stock
coverage and not pre-move recall. The 2023 list has 250 sessions, matching the
package's `E173` note; the calendar is not exchange-verified (`exchange_verified:
false`), so every share inherits that uncertainty.

### The 417-vs-416 note

The recent gainer CSV has **417** distinct dates from 2025-01-01 through 2026-09-22.
The package README says "2025–26 covers 416 trading dates". The difference of one is
preserved in `recent_dates_disagreement`, not reconciled by dropping a row. Neither
number is all-stock coverage; both describe the selected-event file.

## Forward overlay

| Status | Rows |
| --- | ---: |
| OK | 686 |
| NO_DATA | 265 |
| EVENT_BAR_MISSING | 6 |
| **Total** | **957** |

Eight OK rows carry an `EXCLUDE` discrepancy flag, leaving 678 analysis rows. Only
671, 662 and 646 of those contain non-blank T+1, T+5 and T+20 returns respectively.
The overlay retains every gainer key, including missing returns; missing bytes stay
blank. Zero rows were imputed.

## Identities and corrections

The alias map covers 265 gainer keys: 122 acquired, 91 renamed, 22 active-unknown, 19
bankrupt and 11 delisted. The recovered supplement adds 77 annotation rows; 188
gainer keys remain unrecovered. The corrections file has 26 rows. An alias annotation
is research evidence, not a dated share-class identity match, so every event keeps
`security_id: null` and `ticker_identity_unresolved: true`.

## Receipts

The run publishes 1,438 artifacts: `events.jsonl` with 1,172 event rows (957 gainers
+ 215 losers), `corrections-source.csv` with 26 rows, and 1,436 session manifests.
`summary.json` is the index and is excluded from the root digest. The root digest is
the SHA-256 of the sorted `{name: sha256(bytes)}` map:

- `artifacts_sha256` `672723696827a4a1ca2c6f81ad6c418659ef06bb76f8e4e0aba35b2c7f032d0b`
- script sha256 `f423410e95b1ebffad8f9cc04ff2e2d20ad383ec9a8e763473142320ab3fb651`

Each session manifest carries `session_date`, `archive_sha256`, `script_sha256`,
`survivor_only`, `pit_verified: false`, `inference_eligible: false`, the bias object,
event counts by cohort, the selection labels observed that day, an
`event_rows_sha256` over that day's event lines, all 11 input member hashes, the
knowledge block, `absence_semantics`, both null control counts, the trial accounting
and the blockers. Each event keeps its raw source fields, source member and CSV
record, overlay rows, null `security_id`, null `known_at`, null `first_print_ts`,
null `flag_ts` and null `pre_ignition_label`, plus
`selection_knowable_at` = the archive-level clock (not an event clock).

Receipts live at
`/home/sextant/sextant-data/handoffs/wave-all-lanes/W1/scratch/seed-reconcile/` and
are not committed. The script is committed at
`research/seed_reconcile/manifest.py`; the repository gains no extracted package
bytes.

## Bias labels

Every event and session carries the same object:

```json
{
  "selected_event": true,
  "survivor_only": true,
  "retrospective_selection": true,
  "weekly_daily_mixed": true,
  "ordinary_non_mover_controls": false,
  "selected_loser_is_selected_collapse": true,
  "absence_is_not_no_mover": true,
  "ticker_identity_unresolved": true
}
```

The 2021-2023 losers are labelled `weekly_selected_collapse`, not `weekly_leader`.
The earlier implementation's `_selection` used `weekly_leader` for both cohorts that
early; that reads a selected loser as a leader and is corrected here while preserving
the weekly/daily boundary. The 2024+ losers stay `selected_collapse`; gainers stay
`weekly_leader` then `daily_leader_collection`.

`survivor_only` stays `true`. The package supplies no dated whole-universe master, no
delisting/recycled-ticker receipts and no 10-exit/95% acceptance sample, so the flag
cannot be cleared ([ADR-0013](../../docs/adr/0013-us-equity-data-stack.md),
[ADR-0019](../../docs/adr/0019-validation-and-merit.md)).

## Knowable-at clock

`knowable_at` is **2026-10-09T12:45:00Z**, with precision "~15 minutes". Derivation:

1. `GRAND-MANIFEST.md` (grand revision 11) declares "Built 2026-10-09 ~08:45 ET".
   2026-10-09 is EDT (UTC-4), so the declared build is 12:45Z.
2. The latest ZIP member mtime is 2026-10-09T12:33:38Z (`GRAND-MANIFEST.md`), so the
   declared 12:45Z is the later and controlling bound.
3. `release_published_at` is **null**: the release page was not fetched, so an
   earlier actual publication cannot be ruled out.

This is a clock for **when the package existed**, not for when any event was
knowable. Per-event `first_print_ts`, `flag_ts`, `publication_ts` and `known_at`
remain null, and `decision_clock` is null. Inventing clocks from event dates would
violate ADR-0019's knowable-by-decision rule and the handbook's clock separation.
The archive clock is the only clock the bytes can support; it is recorded, not
promoted into per-event knowledge.

## What this does not establish (UNKNOWN)

1. **UNKNOWN 1: dated PIT membership.** No dated share-class master, corporate-action
   receipt or recycled-ticker check; `survivor_only` cannot be cleared.
2. **UNKNOWN 2: delisted identities and the acceptance sample.** No all-10-exit proof,
   no independent delisted sample and no 95% reconciliation, so delisting bias is
   unresolved.
3. **UNKNOWN 3: ordinary non-mover controls.** The package has selected events only;
   `ordinary_control_count` is null and no all-stock stock-day cohort exists.
4. **UNKNOWN 4: pre-ignition labels.** No causal onset protocol or source-backed
   frozen label; `pre_ignition_label_count` is null.
5. **UNKNOWN 5: event clocks.** No first-print, detector-flag, publication or receipt
   clock for any event; `event_clocks` are all null.
6. **UNKNOWN 6: exchange-verified calendar.** The 1,436-session list comes from the
   package's SPX harness file; it is not an exchange receipt, and 2023 uses 250
   sessions.
7. **UNKNOWN 7: release publication time.** The release page was not read; only the
   archive's own build declaration and member mtimes are known.
8. **UNKNOWN 8: cumulative trial accounting.** No TrialLog custody was available;
   `historical_seed_trials`, `cumulative_n`, `effective_n` and `ledger_binding` are
   null. This run adds zero strategy trials; it is a metadata reconciliation, not an
   arm.

Scanner archive inventory is **by reference only**, as required: this distro does not
mount `/mnt/wsl/research-data/scanner-mac-history` or `/mnt/wsl/ns-scanner/scanner`
(both absent). [ADR-0024](../../docs/adr/0024-extreme-mover-ranking-and-early-entry.md):32 records
the checked-in replay reference `docs/research/2026-10-27-missed-movers.json` (one
2026-10-27 premarket session, 18 symbols, coverage incomplete); that path is absent
from this checkout at `695bc7c` and was not opened. Attaching the scanner archive
remains the owner's step (`docs/design.md:64`).

## Sources

1. [W1 brief](file:///home/sextant/sextant-data/handoffs/wave-all-lanes/W1/BRIEF.md), sha256 `c5362281...c316ea5f`, read 2026-11-09.
2. [Wave plan](file:///home/sextant/sextant-data/handoffs/wave-all-lanes/WAVE.md), sha256 `1874aa6d...d8e2b944`, dispatched 01:22:11 EST 2026-11-09.
3. Owner package `extreme-gainer-grand-package.zip`, sha256 `f581ca7f...6d0577`, read 2026-11-09.
4. `docs/design.md:62` and row 4 at `docs/design.md:141`, read 2026-11-09.
5. [Package evidence](../../docs/research/2026-11-06-extreme-gainer-package.md), read 2026-11-09.
6. [Candidate-history lesson](../../docs/handbook/candidate-history.md), read 2026-11-09.
7. [ADR-0013](../../docs/adr/0013-us-equity-data-stack.md), [ADR-0019](../../docs/adr/0019-validation-and-merit.md), [ADR-0027](../../docs/adr/0027-extreme-gainer-research-package.md), read 2026-11-09.
8. `docs/manifest.md` row 54 and [the 2026-11-06 inventory](../../docs/research/2026-11-06-candidate-history.md), read 2026-11-09.
9. Package `GRAND-MANIFEST.md` and `extreme-gainer-research-package/README.md` members, read 2026-11-09.
10. northstar-trading@`8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`:`src/northstar_trading/data/alpaca_history.py:publish_once`, the hard-link publication shape.
11. Python 3.13 `csv`, `zipfile`, `hashlib` and `json` documentation, read 2026-11-09.

No push, no tag, no GitHub write. The branch carries the script and this report only.
