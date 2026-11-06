# Live gates, the promotion record and the halt gaps (#83)

The live lane's tracker. It lists every gate [ADR-0020](../adr/0020-live-lane.md) carries from northstar ADR-0053 and its two protective amendments, what evidence would meet each one and which lane produces it. **As of 2026-11-06, no gate is met.** Sextant has no live runner, no promotion, no `live` branch content and no live drill. This note places no order, opens no stream and calls no endpoint; it only reads pinned files.

## Sources read
| Ref | Pinned source | SHA-256 of the bytes read |
|---|---|---|
| A53 | seathatflowsinourveins/northstar@`b384d298d217d3f8d9aa83356994629536a34795`:`docs/decisions/0053-live-lane-automated-evidence-gated.md` (929 lines) | `d516978c7c54a35698022c1ac6de2f032db436389d5f8e57861ec70b1611a40e` |
| PX | same commit, `docs/decisions/amendments/0053-2026-10-31-protective-exits.md` | `c2ce2e1a86da529b6842433277aa5d5a7a96d700c49a81c7120379721df14711` |
| OC | same commit, `docs/decisions/amendments/0053-2026-10-31-protective-exits-owner-cover.md` | `5633060aec4956169a6347398d4b8a47007ecf4b7c032a9971b2817aa65a6344` |
| V | seathatflowsinourveins/northstar-trading@`dd1dc5cd0eb9f5b70d09e98876ca8652aab99ca6` (PX's "V" tree) and its `live` branch head `78da99ba8fe935e065bbbe1cd5c764d96263ef0a` (2026-11-01, 24 commits ahead, same schema bytes) | schemas below |

**Correction to ADR-0020's "Code and config to carry".** It says the allowed trading pin has neither `scripts/live.sh` nor `src/northstar_trading/live/`. That holds for `8256c16c`, the paper tree. PX's own V tree and the trading `live` branch have both: `scripts/live.sh`, 13 `live/*.py` modules, the two schemas carried here and four T1 drill receipts. Nothing is copied from them except the two schemas.

## 1. Gate tracker
Status words: **NOT MET** (no evidence exists), **NOT STARTED** (the producing code does not exist in Sextant). Lanes: R research, S sim, P paper, L live (sanctioned job only), H harness, O owner.

### Prerequisites before any Stage 0 (A53 §2a, §5, §6, §9; PX §2; ADR-0020 "Nonwaived gates")
| ID | Gate | Evidence that would meet it | Lane | Status |
|---|---|---|---|---|
| P1 | Offline validation | WF and CPCV pass; DSR > 0.95 with effective N; PBO ≤ 0.05 (CSCV S=16); PSR ≥ 0.95; sign kept at 2× costs; untouched 12–24-month holdout | R, S (row 10 merit page) | NOT MET: no merit page; the only rerun (#41) is MODELED and negative against hold |
| P2 | Paper merit | MinTRL in independent round trips; ≥ 30 paper round trips over ≥ 5 sessions covering every traded session type; replay correlation ≥ 0.9; slippage ≤ 1.5× modelled; no unexplained risk event; dossier | P | NOT MET: no Sextant paper fill (row 12) |
| P3 | Point-in-time history | Scan universe: dated/delisted membership, `asof` on every request, `survivor_only:false`; fixed list: selection date and survivorship named | R (rows 4, 11) | NOT MET: `survivor_only:true` stands |
| P4 | Live-feed fidelity | Data-stack §6: first/final revision share, `ts_init − ts_event` skew, scanner determinism, catalyst knowable-at audit | R, S | NOT MET |
| P5 | Exit plan hashed | One file per strategy: protective/time/holding/catalyst/re-entry rules, hashed in the record | S (row 7, 9) | NOT MET: `sextant.exits` exists, no strategy exit-plan file or hash |
| P6 | Exact-SHA review | Two-family review on the exact SHA the node runs (Sextant's only substitution for the old verdict) | H | NOT MET |
| P7 | Engine gate | Stages 0–1: rc7 with dated `engine_gate:owner_ack_rc`; Stage 2: NautilusTrader 2.0.0 final; rc8 only after its risk-release check | H, O | NOT MET: no record; 2.0.0 final not verified |
| P8 | Same-runner paper drills | Over-limit refusal; owner halt and each automatic halt with suspension effects; kill file; restart with positions; protective/time stops; flatten; audit; outage (C.6); supervisor; C.5 double exit | P (row 8) | NOT MET: see §4 |
| P9 | Runner chain T1–T7, guard | Boot/refusal gates, halt (T3), supervisor (T7), shadow sink (T4 r2c+ with no-submit mutant and `sink.failed` latch fix), audit (T5), promotion schema (T6), guard | H, L | NOT STARTED in Sextant |
| P10 | Host boundary (21a) | Target-host runner/socket/export, credential delivery, restart/rollback acceptance; `os_isolation=false` residual accepted | O, H | NOT MET |
| P11 | Limits applied | Owner-applied `configs/live/limits.yaml` and `instruments.yaml`, hash bound; missing file refuses boot (exit 4); `W_s` table, `N_s·W_s ≤ 0.5·daily-loss` | O, R | NOT MET: no file, no `W_s` table |
| P12 | Rate entitlement | Written 1,000/min confirmation before 870 configured; Stage 1 ≤ 30 actions/min, node ≤ 164 attempts/min, 36 reserved | O | NOT MET: 200/180 fallback stands (design "Rate entitlement") |
| P13 | Stage-0 admission record | Reviewed record on `live`: code/verdict, expected account identity, mandates, policy/config/exit-plan/limits hashes, dossier | L, H | NOT MET |

### Stages (A53 §3; PX §2)
| ID | Stage | Exit criteria | Lane | Status |
|---|---|---|---|---|
| S0 | 0 Shadow (read-only sink, no suspension, Q1 (b)) | ≥ 2 sessions of every traded type; ≥ 20 intended orders (≥ 20 counted exit decisions for an owner cohort); parity ≥ 0.95; timing p95 ≤ 2 s; zero risk events; clean reconciliation at every start; feed fidelity in bounds. A halt or fidelity breach restarts the clock | L | NOT MET |
| S1 | 1 Fill realism | ≥ 100 live fills, ≥ 30 round trips, ≥ 3 sessions, `n ≥ (1.96·σ_D/(0.25·E_model))²`; every paper signal paired (missed = 0, partial, unfinished); session-block-bootstrap CI; mean live P&L/signal > 0; `lower95(mean D) > −0.5·E_model`; `E_lower + mean D > 0`; cost ≤ 1.5× modelled; fill rate ≥ 0.9× paper; drawdown ≤ 1.5× backtest; zero unexplained halts; C.5 drill passed first | L, P | NOT MET |
| S2 | 2 Size step | Per doubling: ≥ 50 fills at the new size over ≥ 2 sessions; mean cost ≤ previous upper95; Stage-1 economics hold; drawdown ≤ 1.5×; no halt; NautilusTrader 2.0.0 final | L | NOT MET |
| S3 | 3 Target size | Stage-2 rules forever | L | NOT MET |
| D | Demotion | ≥ 30 live trips with cost > 1.5× or fill ratio < 0.75, or full-sample economic failure → paper, cost write-back, revalidate, re-enter at Stage 0; any halt steps back; missing/FAIL review or fidelity < 0.9 → Stage 0 | L | n/a (nothing promoted) |

### Owner-plan and owner-exit paths
- **2b `owner_plan`:** a recorded instruction naming instrument, size, entry and exit thesis replaces only P1–P2. P3–P13 and the stages remain. None recorded.
- **`owner_exit_policy`** (PX §2, §2.3): needs the paper-B o339 end-to-end acceptance, an exact-version protective-only B cohort with fixed `T_end`, TCA and custody, the kind-discriminated multi-position schema (the V schema admits only `paper_proven | owner_plan | drill`), cache-only `read-account`, the runner's structural refusal of every exposure-increasing intent with a killed mutant, and bounded handback before leg expiry. Owner-position adoption stays **REFUSED UP FRONT**. None exists.

## 2. Promotion record and `deployments/live.json` (drafts, no promotion)
- [`lanes/live/schema/promotion-record.schema.json`](../../lanes/live/schema/promotion-record.schema.json) and [`deployments.schema.json`](../../lanes/live/schema/deployments.schema.json) are V's files, byte for byte (`86bdd514…` and `e78e62f7…`, identical at the trading `live` head). Their `schema` constant still says `northstar.live.promotion/1`; T6 renames it with its reader and migration, not this draft.
- [`lanes/live/promotion-record.template.json`](../../lanes/live/promotion-record.template.json) lays out every A53 §7 field (gates, exit plan hash, verdict, engine gate, kind, stage history, per-stage fill-gap block, `limits_sha256`, approver, timestamps). Every value is `null`, so it fails the schema (`head_sha` pattern, `kind`, `stage`) and cannot pass as a promotion.
- `deployments/live.json` takes the V deployments shape: `{"deployments": [{"strategy", "lane", "params": {"instrument_id", …}, "record"}]}`, no other keys, where `record` names `reports/live/promotions/<strategy>-<date>.json`. It lives only on the `live` branch; the deployed head may differ from the verified commit V only in it and `reports/live/promotions/**` (A53 amendment 2026-10-22 A.1). Sextant's `main` has neither file, and this PR creates neither.

## 3. Gain protection at live
Live keeps its own sanctioned protective policy (ADR-0020 "Latest protective policy"): managed dynamic LIMIT primary, rolling TP above H, coupled plain-stop backstop, both legs resident, chase `max(bid, last·(1−cap))`, Chandelier counterfactual only. **Paper B's cancel-first option B is not promoted automatically**; it has two unbounded outage intervals (ADR-0025). A live protective promotion would need, at policy-version parity:

| Proof | Where it stands | What live adds |
|---|---|---|
| #45 X2–X6 pure witnesses (`test_exit_engine.py`: trigger never loosens, persisted breach, arming, chase never below bid, TP roll up only, backstop raised only, no float) | Merged; synthetic data, all parameters UNCALIBRATED | Same tests at the exact promoted SHA; calibrated registry rows; arming/normal-tick fill witness and killed breakeven-floor mutant (PX §2 C.5 row) |
| #45 sim witness, #41 rerun | Mechanism only; hold beat all 96 variants | Preregistered executable cohort with economics at 2× costs (design "Fast exit … versus holding") |
| #49 B owner-entry manager | Open, plan only | o339 paper-B e2e acceptance; measured option-B gap intervals; exact-version protective-only cohort; custody, add-pauses-symbol and one-exit witnesses |
| Row 8 custody, pacer, guard, halt (#51) | No code on `main` | Owner-order-untouched, one-writer, kill-to-flat and unknown-state drills; split entry/protective ledgers with protective-first priority; C.5 double-exit drill |

## 4. Halt and drills against what exists
| Required (A53 §5, T3/T7; ADR-0020 "Halt", "Unknowns stay halted") | Sextant | Trading `live` head `78da99ba` |
|---|---|---|
| `scripts/live.sh halt [--flatten]` | **absent** (no `scripts/live.sh`) | present but refuses: `halt|resume) die "$verb needs northstar-trading-2mv.3" 2` |
| `shadow`, `promote/stage/demote` verbs | absent | refuse, needing 2mv.4 and 2mv.6; `up --mode live` exits 5 |
| Boot-gate refusals (G2, G4, G6, G9) | absent | T1-D1…D4 receipts, `ibkr-paper`, 2026-10-25, PASS (exit 4) |
| Owner-halt sequence (kill file → cancel increasing → flatten → confirm → suspend LAST), node healthy/stopped/killed | absent | no receipt |
| Suspension-vs-closing-orders, extended-hours close, per-item 500 cancel-all, supervisor restart mid-halt | absent | no receipt |
| Outage drill (C.6), 30 s unreachable halt, 60 s stale heartbeat escalation | absent | no receipt |
| C.5 double-exit, single-exit-owner takeover with positive terminal proof | absent | no receipt |
| IB independent cancel-and-flatten | absent | not proved; IB live withheld |

**Gaps:** every halt drill and every runner component. Row 8 (custody, pacer, guard, halt) is the first Sextant code a drill could run against; the live wrapper follows only after it passes on paper. No live order code is built here.

## Revisit when
A row-8, #49 or merit PR lands; the owner applies limits or confirms entitlement; NautilusTrader 2.0.0 final ships; or the trading `live` branch moves. The live lane updates this table in the same PR.
