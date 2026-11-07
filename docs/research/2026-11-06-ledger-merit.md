# Row 10: TrialLog writer slice and native statistics

Refs #72, #110 and #147; sources read 2026-11-06. The owner's reduced ledger scope removes the custom merit calculator, inference, lesson appender and registry runtime from this PR. No code moves into documentation or another directory to evade the cap. This is a local software witness, with no broker or deployment authority.

## Retained contract

northstar-trading@paper `8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa`, relative to `src/northstar_trading/`:

- `validation/trials.py`: all 13 SCHEMA columns retain their names, types and order for the existing ledger. `append(strategy, params, config, seed, state="RUNNING")`, identity/hash/tier checks, `finish_arm_run`, writer/checkpoint and `_no_floats` remain. The latter moves within src from deferred merit.py into the slice.
- `sim_lanes/runner.py:writer_lock`, lines 51-80, and `canonical_trial_log`: sourced reentrant full-run flock. A live owner blocks concurrent raw writers. A known same-host/path abandoned RUNNING row becomes FAIL on the next owner acquisition. Legacy/foreign RUNNING liveness is never guessed; it requires owner resolution. Partial registration failure closes already registered attempts.
- `persist.py`: original full_fsync, fsync_dir and atomic JSON writer remain for #110. Append rewrites the Parquet file atomically, preserves all earlier rows and schema metadata, and never resets history. New n_trials values are immutable append-time counts; effective_n stays null with inference deferred.

PyArrow remains 26.0.0 at `446167169a0dc547e00e1bc29f417a40c0ca267a`. Both existing witness runners share `reports/research/trials.parquet`; raw JSONL outcome writers are deleted. Each arm enters before engine work, including failed execution, and reruns have distinct arm-run IDs/native report directories. Native returns do not become invented daily session returns.

## R98 and R100

Audit N7 is Nautilus rc7 `55c0e82053142bce3a5cba4de4221d3929c2d3bc`; main #87 adopted rc8 N8 `d53849b216e20f2c122ca01b4dd0da377638b186`. Main #174 supplies R98: the fee/P&L path calls Portfolio.realized_pnls with native Money/Decimal and no display-string sum. This branch takes that implementation.

R100 uses the rc8 `docs/concepts/portfolio.md` statistics section and documented TradeCount(PortfolioStatistic) registration. Native realized-close inputs include NETTING snapshots: 8 backtest cycles and 6 replay cycles, rather than one reused position ID. Native tearsheets provide portfolio analytics. There is no parallel house performance estimator.

DSR, PBO, PSR, MinTRL, CPCV, inference and custom decision-2a validation are absent pending #147's source verdict. Their former false-PASS/report-hash and unchecked-inference paths leave with the deferred code. The native interface rejects paper_measurements, inference and merit_id inputs. New records have UNVERIFIED code binding, including dependency/dirty-tree uncertainty. Legacy metadata remains historical data, without validation or promotion. Native artifacts grant no admission or session qualification. Both synthetic exit arms are MODELED with a separate execution label.

## Size and landing

Main `2cb2089fab1c39a53aa79e12e70b985fa8b822ac` has 13,306 src lines. After #178 raised the strict cap to 17,500, the lead authorized this landing turn. Net `src/` is **+385**: 304 lines in validation/trials.py, 53 in the required persist.py, and +28 net in the native witness integrations. Total src is 13,691. Reusing the locked Arrow schema and removing duplicate hash-selection/hex-validation code sheds 10 lines from the held b6d9ff8 candidate while preserving the full identity/API/schema/fsync/recovery contract. This contributes 10 of the roughly 85 lines the ledger and #139 need to trim together. No implementation moves outside src.

Auto-merge remains off until #88's delta review and breadth legs gate this head.

This note keeps its exact path for #110. Retire the superseded standalone 2026-11-06-research-convergence.md to remain at 30 notes. Its receipts/source cards survive and its earlier bytes are available at the pinned main revision in Git. Do not edit the published qualifying-leg convergence: its hash is an input to the claim ledger.

## Custody and writer decisions still required

The protected ledger ref/path and production handoff remain #110's contract. No protected ref or broker account is touched here. The full-run lease is local-host custody, not permission to seize a foreign/legacy RUNNING run. Appender/registry runtime work is deferred to #147; no canonical journal writer is introduced by this slice.

## Verification

The [native replay receipt](2026-11-06-ledger-merit/native-replay.json) compares current-main and candidate economics on rc8 with zero economic and native-statistic differences. Both paths use the documented native TradeCount; all baseline/candidate arms enter the same retained local TrialLog. The receipt records the intended count/tier corrections separately.

Focused proofs cover the exact legacy schema/API, identity and float refusals, immutable counts/metadata, source fsync rollback, SIGKILL recovery, active-owner refusal, unknown-owner refusal, second-registration failure, unique rerun artifacts, and rejection of removed merit inputs. `just ci` passes: 612 tests, 28 skipped and seven deselected under main's unchanged marker policy; Ruff, formatting, Pyright, zizmor, actionlint and gitleaks pass. No unfiltered container/admin proof run is claimed. The PR body and push comment record final CI, net src and numbered dsh-TUI/#88 responses.
