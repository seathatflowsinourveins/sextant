# Extreme-mover evidence carried from the pinned campaign

Date: 2026-11-06. These are recorded results, not reruns. Tables are copied from the named records; original case/precision, negative results and censoring remain. No new trading experiment or decision is introduced.
| ID | Pinned source |
|---|---|
| M27 | northstar-trading@8256c16c31dc:docs/research/2026-10-27-missed-movers.md |
| J27 | northstar-trading@8256c16c31dc:docs/research/2026-10-27-missed-movers.json |
| S27 | northstar-trading@8256c16c31dc:docs/research/2026-10-27-scanner-recall.md |
| C28 | northstar-trading@8256c16c31dc:docs/research/2026-10-28-premarket-gap-calibration.md |
| I01 | northstar-trading@8256c16c31dc:docs/research/2026-11-01-scanner-early-mover-integration.md |
| XR29 | northstar-trading@8256c16c31dc:docs/research/2026-10-29-b-exit-replay.md |
| B03 | northstar-trading@8256c16c31dc:docs/research/2026-11-03-b-gain-protection-replay.md |
| P03 | northstar-trading@8256c16c31dc:docs/research/2026-11-02-pmg-trail-c5-r3.md |
| TV29 | northstar-trading@8256c16c31dc:docs/research/2026-10-29-tv-lane-acceptance-run.md |
| TV14 | northstar-trading@8256c16c31dc:docs/adr/0014-tradingview-automation-lane.md |
| TVR | northstar-trading@8256c16c31dc:docs/tradingview/README.md |
| O05 | northstar-trading@8256c16c31dc:docs/research/2026-11-05-extreme-movers-onset.md |
| M2 | northstar-lanes@00203275944a:docs/m2-mover-surge.md |

## Candidate history and actual first detection
No committed multi-year daily-candidate/extreme-mover dataset was found by the required searches at these pins. J27 is 3,268,669 bytes, 18 symbols, one 2026-10-27 pre-market session [04:00,09:30) ET. M27 retains five supplied prior daily bars, not an ADV20 history. O05 R06/Y9 explicitly leaves actual premarket coverage since 2016 and the recorded archive's start **unverified**; the historical-data entitlement is not a candidate dataset. Search commands: `git -C /home/choreo/Developer/northstar-trading grep -il 'extreme\|mover' 8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa -- docs reports configs src`; `git -C /home/choreo/Developer/northstar-trading ls-tree -r --name-only 8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa -- reports`. Both commands were also run for northstar-lanes at `00203275944a22655b3e14b221cfde9a265d549a` and northstar at `b384d298d217d3f8d9aa83356994629536a34795`. No fetch or working-tree source was used.
M27 table (all 18 nominated candidates, ET): first/threshold times are minute starts, known only at minute end; dollars are raw VWAP×volume. Neither a rank nor a high proves an executable entry.
| Symbol | Prior close | First trade | +5% | +10% | Max pre % | V <05 | V <07 | V <09:30 | $V <05 | $V <07 | $V <09:30 | Rank/tier 05 / 07 / 09:30 | First top30 / top100 | WHY |
|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| AEYE | 7.42 | 07:00 | 07:00 | — | 6.60 | 0 | 0 | 1,800 | 0.00 | 0.00 | 14,130.50 | 467/D / 662/D / 733/D | — / — | tier_or_liquidity_excluded |
| AIOK | 9.16 | 04:01 | 04:30 | 04:30 | 50.00 | 779,851 | 1,653,116 | 6,928,294 | 8,491,525.41 | 18,105,687.42 | 84,205,541.18 | 8767/D / 8804/D / 8974/D | — / — | not_ranked_in_time |
| BA | 188.31 | 04:01 | — | — | 1.43 | 12,540 | 30,045 | 1,549,563 | 2,358,369.42 | 5,667,340.57 | 287,485,459.91 | 248/A / 23/A / 61/A | 04:53 / 04:53 | rth_mover_not_premarket |
| BE | 203.92 | 04:00 | 09:28 | — | 5.84 | 121,253 | 226,544 | 1,989,399 | 24,733,686.75 | 46,805,710.23 | 420,407,393.44 | 137/A / 45/A / 20/A | 09:28 / 04:49 | no_premarket_carrier |
| BRAI | 2.12 | 04:00 | 04:00 | 04:00 | 60.38 | 2,064,010 | 3,515,960 | 5,913,947 | 6,382,251.64 | 10,880,935.18 | 18,414,402.52 | 164/B / 250/B / 459/B | — / 05:38 | not_ranked_in_time |
| CLRO | 4.97 | 04:00 | 04:01 | 07:09 | 35.01 | 245,158 | 312,595 | 14,088,864 | 1,161,713.93 | 1,484,072.61 | 84,284,372.94 | 10143/B / 8814/B / 8930/D | — / — | not_ranked_in_time |
| CRWV | 55.19 | 04:00 | — | — | 4.87 | 382,309 | 680,823 | 2,290,312 | 21,130,867.66 | 37,897,682.25 | 129,986,936.75 | 3/A / 17/A / 44/A | 04:58 / 04:49 | rth_mover_not_premarket |
| DELL | 467.09 | 04:00 | — | — | 2.26 | 7,281 | 9,328 | 39,943 | 3,396,540.09 | 4,367,754.52 | 18,933,146.58 | 179/A / 449/A / 1139/A | — / — | rth_mover_not_premarket |
| ENVX | 2.68 | 04:00 | — | — | 3.36 | 512 | 2,932 | 42,094 | 1,362.54 | 7,825.83 | 115,329.97 | 2685/B / 2839/B / 3337/B | — / 06:33 | rth_mover_not_premarket |
| KNSA | 72.98 | 04:50 | 07:19 | 07:40 | 19.37 | 562 | 5,946 | 61,470 | 41,329.48 | 444,708.78 | 5,104,677.97 | 4722/A / 4838/A / 117/A | — / 07:53 | not_ranked_in_time |
| LITE | 818.1 | 04:00 | — | — | 3.65 | 47,763 | 75,168 | 179,706 | 38,792,459.45 | 61,516,926.15 | 149,511,137.50 | 4893/A / 32/A / 135/A | 04:49 / 04:49 | rth_mover_not_premarket |
| MFIC | 8.36 | 05:30 | 05:30 | 05:31 | 25.00 | 0 | 440,147 | 776,454 | 0.00 | 4,331,044.37 | 7,739,855.89 | 5144/D / 62/D / 71/D | 06:23 / 05:43 | tier_or_liquidity_excluded |
| NAUT | 2.44 | 04:00 | 07:01 | — | 8.20 | 22,806 | 157,493 | 696,059 | 54,228.87 | 372,288.70 | 1,671,132.02 | 5440/B / 359/B / 123/B | 06:33 / 04:53 | tier_or_liquidity_excluded |
| NBIS | 153.27 | 04:00 | — | — | 4.87 | 238,720 | 385,221 | 1,073,373 | 36,683,806.53 | 59,549,352.05 | 169,018,095.17 | 20/A / 27/A / 89/A | 04:49 / 04:49 | rth_mover_not_premarket |
| NUWE | 3.097 | 09:00 | 09:01 | 09:01 | 10.06 | 0 | 0 | 16,304 | 0.00 | 0.00 | 51,346.56 | 9187/C / 9230/C / 8910/B | — / — | tier_or_liquidity_excluded |
| PRME | 3.61 | 04:37 | — | — | 3.05 | 261 | 461 | 22,391 | 935.69 | 1,667.61 | 82,335.39 | 6261/B / 6345/B / 6623/B | — / — | rth_mover_not_premarket |
| SOFI | 14.46 | 04:00 | 07:02 | 07:55 | 13.50 | 284,486 | 905,598 | 20,709,526 | 4,090,476.86 | 13,036,664.31 | 325,856,633.86 | 58/A / 48/A / 119/A | 05:48 / 04:49 | no_premarket_carrier |
| ZURA | 3.56 | 04:00 | 08:44 | — | 5.56 | 1,036 | 1,166 | 70,162 | 3,833.20 | 4,288.20 | 260,288.22 | 8754/B / 8786/B / 766/B | 08:53 / 08:53 | tier_or_liquidity_excluded |
M27/J27: 11 observed +5% movers, 9 manifest-only no-arm misses, 5 activity-unresolved candidates; `universe_complete=false`, `activity_complete=false`, `coverage_complete=false`. Primary WHY across 18 candidates: RTH-not-premarket 7, tier/liquidity 5, not-ranked-in-time 4, no-premarket-carrier 2. Native fills/manual/carry activity, pre-04:49 ranks, executable quotes, signal replay and missed P&L are **unverified**. Original M27 command: `python scripts/missed_movers_day.py --session-date 2026-10-27 --market "$S/inputs/market" --snapshots "$S/snapshots" --owner-list "$S/inputs/owner.md" --ref 297b94d66eb75a8edef2a8f4c82b8dff8b936d75 --incident ibkr-paper,2026-10-27T09:33:00Z,2026-10-27T13:40:00Z --incident alpaca-paper,2026-10-27T12:47:42Z,2026-10-27T13:44:33Z --incident alpaca-paper,2026-10-27T15:49:00Z,open --output docs/research/2026-10-27-missed-movers.json --markdown docs/research/2026-10-27-missed-movers.md`; S is the source's `missed-movers-20261027.vDNtDL` scratch root. Raw bar hash `c0629f20704c9884cf47ffad2a022f32febaf015c29918faa9d57953c7f6347a`; daily hash `a3e2d8054333274c2fab8d6730893e64a328b2151f036455c138b3b2c0f3cf59`. S27's single-day saved-input recall is coverage conditional: 52 snapshots/marks/picks, 51 outcomes; 13,213 ranked rows, with extensive missing close/dollar inputs. Truth is up to 50 positive prior-close movers with >$1m observed pre-market dollars and exact own marks.
| Checkpoint ET | Saved decision ET | Observed truth size | Baseline @30 | Partial replay @30 | Baseline @100 | Partial replay @100 |
|---|---|---:|---:|---:|---:|---:|
| 04:30 | none published | unavailable | — | — | — | — |
| Earliest, 04:49:39 publication | 04:49:37.960584 | 41 | 6/41 = 14.6341% | 6/41 = 14.6341% | 25/41 = 60.9756% | 25/41 = 60.9756% |
| 07:00 | 06:58:09.990692 | 50 | 10/50 = 20% | 10/50 = 20% | 28/50 = 56% | 28/50 = 56% |
| 09:00 | 08:58:13.037708 | 50 | 4/50 = 8% | 4/50 = 8% | 15/50 = 30% | 15/50 = 30% |
Recall delta is zero percentage points. Original S27 command: `.venv/bin/python scripts/scanner_recall.py --scanner-dir "$S/scanner" --date 2026-10-27 --include-earliest --replay-session-relative`; S is the source's `scanner-recall-16ptau61` scratch root. I01's later synthetic 34-case/11,098-row comparison leaves all 30 volume scenarios unchanged; it withdraws complete-history absolute-dollar credit and UPC's old rank-1 uplift. M2 uses native replay of the 2026-10-30 INO/ONEG/SNDK/CLRO/CHOW captures, with disclosed interpolated normal anchors, not qualified full-history normals or measured operational arrivals. Selected rows copied below:
| Witness | Measured result (UTC) | Status/qualification |
|---|---|---|
| INO `surge30` | first flag 20:32:29.142767Z, price 0.637, quiet 0.6167 (+3.2917139614%); 11 prints, $2,278.55190 / $217.6942675159 = 10.4667519545x | Replay assertion passes using disclosed interpolated normal. This is **before**, not after, the brief's 20:38 narrative. |
| INO latency | first moved print 20:32:29.142568Z; known-at equals flag event time; difference 199,000ns | Event-time replay only; arrivals absent. |
| INO `minute_snapshot` | first flag 20:33:30.097733Z, price 0.7924, quiet 0.7816; 429 prints, $128,047.523 / $2,000 = 64.0237615x; difference 29.839016s | Parameter comparison replay passes. Pre-20:30 minute history was not captured. |
| SNDK with INO/ONEG | 503 overlapping published-second row pairs after the elapsed-interval fix (old UTC buckets: 677; difference 174); partial totals give `None` ratios/scores, SNDK's first-price-relative move stays <3% | **Full ranking witness UNVERIFIED:** this old witness has no official SNDK close, SNDK normal or segment prefixes. New G0 receipts await canonical M1 integration. This verifies no invented rankings, not a qualifying-mover comparison. |
| CLRO | old capture starts 21:00:00.124207Z at 4.46; captured minimum 4.45 | **UNVERIFIED:** old witness misses ~3.60 early stage; the new full-session receipt has not been replayed here. |
| Closing auction | synthetic `6`, `M`, `9` leave no mover/surge accumulation | Synthetic regression passes; **BRKR capture BLOCKED** (absent). |
| CHOW captured geometry | 33,874 descriptive price checks 14:40–14:56Z; minimum 900s range/last 31.02445%; 0 flags with uncovered windows | Native volume/price views plus aligned M1 facts. **Not a coverage-qualified detector witness**; own-normal and completion receipt are absent from this control. |
| CHOW earliest ignition | bounded opening 120s replay emits none with unknown own-normal | **UNVERIFIED:** own normal is absent from this witness; new G0 baseline receipts await canonical M1 integration. Not conflated with the no-base measurement. |
M2's original overlap/unknown-ranking command is `uv run --no-sync pytest tests/m2/test_witnesses.py::test_partial_tapes_leave_segment_ratios_unknown_and_sndk_flat -o addopts= -q -s`; four evidence-gap xfails remain. No validated “first second” trading advantage is established. The IBKR convergence (northstar-trading@8256c16c31dc:docs/research/2026-11-02-ibkr-advanced-movers/convergence.md, §3) separately keeps no ADOPT: de Groot's liquid-stock cost result does not transfer automatically; its extreme-quintile constructions returned −66.1 and −103.7 bps/week.

## Premarket block calibration and its negative evidence
C28: 11 observed October 27 +5% movers; exactly five consecutive positive-volume minutes, bullish +5% block close, completed before 09:15. Dollars below are `sum(close×volume)`, not scanner VWAP dollars. ADV is the contemporaneous replay input, not the five cached daily bars.
| Symbol | ADV20 $ | First bullish +5% block ET | Block proxy $ | Block / ADV20 | Old floor $ | New floor $ | New floor first passed ET |
|---|---:|---|---:|---:|---:|---:|---|
| AEYE | 660,963.65 | none | — | — | 100,000.00 | 50,000.00 | none |
| AIOK | **unknown** | 04:30–04:35 | 1,133,217.62 | **unknown** | **unknown** | **unknown** | unknown ADV |
| BE | 3,834,289,289.32 | none | — | — | 19,171,446.45 | 3,834,289.29 | none |
| BRAI | 1,595,603.05 | 04:00–04:05 | 2,371,082.49 | 148.6010% | 100,000.00 | 50,000.00 | 04:05 |
| CLRO | **unknown** | 07:05–07:10 | 1,477,440.71 | **unknown** | **unknown** | **unknown** | unknown ADV |
| KNSA | 51,258,504.25 | 07:45–07:50 | 237,146.30 | 0.4626% | 256,292.52 | 51,258.50 | 07:50 |
| MFIC | 4,670,365.54 | 05:55–06:00 | 262,229.80 | 5.6148% | 100,000.00 | 50,000.00 | 06:00 |
| NAUT | 26,568,084.66 | 07:00–07:05 | 53,264.93 | 0.2005% | 132,840.42 | 50,000.00 | 07:05 |
| NUWE | 112,512.73 | 09:00–09:05 | 11,581.98 | 10.2939% | 100,000.00 | 50,000.00 | none |
| SOFI | 675,184,784.19 | 07:00–07:05 | 23,166,975.47 | 3.4312% | 3,375,923.92 | 675,184.78 | 07:05 |
| ZURA | 19,260,319.76 | none | — | — | 100,000.00 | 50,000.00 | none |
KNSA/NAUT clear the new trigger where the old floor did not; SOFI clears both. BRAI/MFIC still fail $5m candidate ADV; AIOK/CLRO ADV is **unknown**. Block sealing is not candidate selection, quote breakout or a fill. Original C28 command: `.venv/bin/python "$S/replay_calibration.py" "$S"`, with the source's `premarket-calibration-20261028.y3va6d8j` scratch root; helper SHA-256 `8ae927831dd7e588706cf627daf00adb1bc43af3ce8edd13b2555b197783a8ac`, inputs B/D/M as recorded there. The actual old archive/helper is not rerun here.
C28's prior-post filter excludes four of eight thin names, not all eight. PPG/MANH/UCTT/ICLR passed prior-post liquidity yet were thin at 04:00: a weak predictor of early earnings tape. Its amended window starts at prior XNYS close+1 minute and removes flat-at-prior-close bars before close+15 minutes. The attributed 09:54 ET run had 91 pre-gated names, one request, 12 candidates; it was not a historical 03:15 or post-amendment-2 run.

## Exit search: holding won
XR29 is an offline minute-bar exit-rule study, **not a Nautilus backtest**. Dataset: 117,486 split-adjusted SIP 1m bars, 54 symbols, 2026-10-26 08:00Z through October 29 17:25Z opens (last completion 17:26Z); 11,256 fill activities plus the MU owner entry. Primary identical complete-horizon cohort: 1,025 strategy entries on October 26–28, no owner entries; October 29 is partial/censored. Correlated partial fills are not independent replications.
96 combinations = 2 bar sizes × 2 ATR periods × 3 multipliers × 4 trigger sets × 2 overlay states. Completed-close signals use next 1m open; 3 and 6 bps/side are assumptions, not measured commission. R=Chandelier only; M=momentum; V=VWAP; ON/OFF=market overlay.
| Variant | Trades | Mean/expectancy bps (3) | Median bps (3) | Win % (3) | Worst MAE bps | P&L units (3) | Before flat % | Mean/expectancy bps (6) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **C5-n22-k3-R-OFF** | 1025 | **54.78** | -7.68 | 42.15 | -2261.00 | 5.6149 | 58.63 | **48.76** |
| C5-n22-k3-V-OFF | 1025 | 50.02 | -8.95 | 38.73 | -2261.00 | 5.1270 | 69.85 | 44.00 |
| C5-n22-k3-R-ON | 1025 | 16.69 | -11.94 | 37.46 | -2261.00 | 1.7107 | 69.76 | 10.68 |
| C5-n22-k2.5-R-OFF | 1025 | 16.24 | -12.66 | 37.46 | -2261.00 | 1.6644 | 70.93 | 10.23 |
| C5-n22-k3-V-ON | 1025 | 11.97 | -11.26 | 35.22 | -2261.00 | 1.2268 | 75.32 | 5.96 |
| **Hold 15:55** | 1025 | **76.44** | 10.49 | 57.07 | -2321.70 | 7.8353 | 0.00 | **70.42** |
| Actual FIFO realized | 1025 | -21.00 | -19.63 | 22.54 | -857.58 | -2.1523 | 96.10 | -26.99 |
**Hold-flat beats every active variant.** Only 2/96 active candidates passed the exploratory screen; 87 had nonpositive stressed expectancy and seven failed day stability. The overlay loses 38.09/38.08 bps at base/stress. No WF/CPCV/DSR/PBO or significance result; RCT/XXII dominate the selected gain. The owner's tested-tight-exit requirement remains, alongside this negative result.
| Primary day | n | Selected mean bps (3 / 6) | Selected median bps (3) | Win % (3) | Hold mean bps (3 / 6) | Overlay ON mean bps (3 / 6) |
|---|---:|---:|---:|---:|---:|---:|
| 10/26 | 9 | -24.11 / -30.10 | -48.73 | 44.44 | -11.85 / -17.85 | -18.03 / -24.02 |
| 10/27 | 316 | 65.82 / 59.80 | 3.50 | 52.22 | 23.29 / 17.28 | 0.15 / -5.85 |
| 10/28 | 700 | 50.81 / 44.79 | -13.09 | 37.57 | 101.57 / 95.54 | 24.60 / 18.59 |
| 10/29 **unpaired resolved-only** | 285 of 393 | 1900.72 / 1894.15 | 134.76 | 61.75 | censored | not used in selection |
Frozen execution sensitivity, same 1,025 entries; PATCH/cancel→market assume another 1 bp half-spread and cannot price subsecond differences. Resting stops fill at `min(stop, triggering-bar open)`; crossed new stops use active PATCH.
| Frozen setting, execution sensitivity | Same trades | Mean bps (3 / 6) | Median bps (3 / 6) | Win % (3 / 6) | Worst MAE bps | P&L units (3 / 6) | Before flat % |
|---|---:|---:|---:|---:|---:|---:|---:|
| Active PATCH | 1025 | 54.17 / 48.15 | -8.61 / -14.61 | 41.95 / 39.12 | -2261.00 | 5.5524 / 4.9355 | 58.63 |
| Cancel→market | 1025 | 54.17 / 48.15 | -8.61 / -14.61 | 41.95 / 39.12 | -2261.00 | 5.5524 / 4.9355 | 58.63 |
| Resting stop | 1025 | 41.00 / 34.99 | -11.05 / -17.05 | 37.85 / 35.71 | -2131.12 | 4.2026 / 3.5862 | 71.61 |
Two SCHD paper probes measured PATCH request 27/40 ms, PATCH-to-terminal 376/802 ms, cancel→market gaps 880/642 ms. These are two probes, not execution guarantees. Proxy rotation stays OFF: no trustworthy positive full-path result. MU's selected exit and hold are censored at 17:26Z, not fabricated realized returns.
Spread study: 428 snapshots, October 27 08:49:39.639672Z–October 29 18:20:09.353779Z; 1,016/1,025 matched primary opportunities, only two complete days; fresh ≤10m subset n=933. f and m were tested separately, not as a cross-product:
| f | Retained / 1016 | Refused | Retained mean bps 3 / 6 | Cash-policy mean bps 3 / 6 | 10/27 cash-policy bps 3 / 6 | 10/28 cash-policy bps 3 / 6 | P&L units 3 / 6 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0.1 | 859 | 157 | 62.05 / 56.02 | 52.46 / 47.37 | 61.84 / 56.37 | 48.22 / 43.30 | 5.3297 / 4.8125 |
| 0.25 | 1007 | 9 | 56.26 / 50.24 | 55.76 / 49.80 | 65.82 / 59.80 | 51.23 / 45.29 | 5.6657 / 5.0596 |
| 0.5 | 1012 | 4 | 55.92 / 49.90 | 55.70 / 49.71 | 65.82 / 59.80 | 51.14 / 45.15 | 5.6594 / 5.0503 |
| OFF | 1016 | 0 | 55.48 / 49.46 | 55.48 / 49.46 | 65.82 / 59.80 | 50.81 / 44.79 | 5.6366 / 5.0251 |

| m | Baseline trail exits too tight / 621 | Initial opportunities too tight / 1016 | Changed exit time/price | Mean bps 3 / 6 | 10/27 mean bps 3 / 6 | 10/28 mean bps 3 / 6 | P&L units 3 / 6 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2 | 4 | 4 | 3 | 55.46 / 49.45 | 65.82 / 59.80 | 50.79 / 44.77 | 5.6351 / 5.0236 |
| 3 | 7 | 7 | 6 | 55.71 / 49.69 | 65.82 / 59.80 | 51.14 / 45.13 | 5.6599 / 5.0484 |
| 5 | 26 | 34 | 16 | 55.59 / 49.58 | 65.92 / 59.90 | 50.93 / 44.92 | 5.6484 / 5.0369 |
| OFF | — | — | 0 | 55.48 / 49.46 | 65.82 / 59.80 | 50.81 / 44.79 | 5.6366 / 5.0251 |
f=0.25 gains only 0.2866/0.3397 bps; m=3 only 0.2300/0.2299, entirely from October 28. No Part-3 arm qualifies; f=0.25+m=3 was not tested. Existing values are provisional heuristics, not calibrated optima. Original XR29 command: `.venv/bin/python scripts/research/b_exit_replay.py --bars /Users/choreo/.northstar/persist/2026-10-29/alpaca-lane/minute-bars-2026-10-26_29.jsonl --fills /Users/choreo/.northstar/persist/2026-10-29/alpaca-lane/fills-2026-10-26_29.jsonl --owner /Users/choreo/.northstar/persist/2026-10-29/alpaca-lane/b-owner-first-orders.json --snapshots /Users/choreo/.northstar/paper/state/scanner/snapshots --output /private/tmp/exit-replay-r2/replay.json`; original 8GB wrapper, Python 3.13.16, replay `b-exit-replay/3`. Bar SHA-256 `105caeee0645455aa0e1de23a1720639347062061944ea3d49eedb6d99a86a69`; fill SHA-256 `55eee2b64506c19e23d4c421c803be687daf06ebb39a2b84f621ea2a90618c0f`.

## Later strict protection: no supported winner
B03: 162 order summaries, 31 symbols, 73 buys/89 sells, October 29 02:36:48.401546Z–November 3 15:48:12.528314Z (first fill is October 28 ET); 97 matched FIFO lots/85 exit orders. Recorded gross −$15,372.014069821952; schedule-estimated net −$15,440.83565452057754577876003. These are descriptive, not paired performance. PARA sensitivity uses 371 minute rows and two 50-share counterfactual entries; PARA was not B-claimed. Qualified, cost-calibrated tick n=0; no measured halt-aware effect or winner.
| Arm | Minute opportunities | Calibrated tick n | Modeled gross | Modeled net, 100 bp | Approx. gain giveback upper bound | Modeled loss below entry | Modeled stop-outs | Research state |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 3% deployed reference | 2 | 0 | −$55.14 | −$62.67 | $34.36 | $55.14 | 2 | REFERENCE_ONLY; OFF; cap exception |
| 2.5% C5 | 2 | 0 | −$55.14 | −$62.67 | $34.36 | $55.14 | 2 | NEGATIVE_MODEL_OFF |
| 100 bp ratchet | 2 | 0 | −$55.14 | −$62.67 | $34.36 | $55.14 | 2 | NEGATIVE_MODEL_OFF |
| Wilder SAR overlay | 2 | 0 | −$55.14 | −$62.67 | $34.36 | $55.14 | 2 | NEGATIVE_MODEL_OFF |
| Halt-aware C5 | 2 | 0 | −$55.14 | −$62.67 | $34.36 | $55.14 | 2 | NEGATIVE_MODEL_OFF |
| Secondary vendor tiers | 2 | 0 | −$55.14 | −$62.67 | $34.36 | $55.14 | 2 | NEGATIVE_MODEL_OFF |
B03 cost stress is 100 bp additional exit notional plus estimated SEC/CAT/TAF schedule fees; TAF is zero during the recorded pause. This is a declared adverse low-first minute approximation, not rc7 `bar_execution` equivalence, executable NBBO or a halt replay. No hold-flat control or qualified confirmatory protocol exists for this later six-arm run. Original B03 command: `.venv/bin/python -m northstar_trading.research_e2e.backtests.b_gain_protection --orders /var/tmp/ns-worker-1000/task_229ca7273d0c/b-trades.jsonl --minute-bars /var/tmp/ns-alpaca-briefs/para-2026-11-03/sip-1min-bars.json --counterfactual-symbol PARA --out "$TMPDIR/reproduce-b-gain" --implementation-sha aa64f59bd7e0b00c16e812c08290398a8ddef007 --slippage-stress-bps 100 --enabled`; TMPDIR is `/var/tmp/ns-worker-1000/task_1dddff54eef6`, under the source's nice/ionice/8GB prefix.
P03 mechanism benchmark: five repetitions/case on the shared Mac, actual C5 `on_quote`, 32 cached arrivals; fresh case 2,000 quotes/repetition, lag case 200 with 2,000ms SIP lead. It does not measure broker execution or trading merit:
| Workload | Before median µs/quote (range) | After median µs/quote (range) | Journal rows per repetition, before → after |
|---|---:|---:|---:|
| Fresh, 32 cached quotes | 294.1 (257.7–314.1) | 81.0 (80.3–98.5) | 0 → 0 |
| Sustained 2000 ms lag | 269.5 (237.3–306.5) | 57.4 (51.2–75.6) | 400 → 1 |
Original P03 command: `.venv/bin/python "$T/quote_bench.py" before`, then the same with `after`, using the source's `pmgfix-codex-r3` scratch root and 8GB prefix. qfk33's six native-stub activation cases likewise prove activation/release, not fills or persistent-cache crash recovery.

## TradingView: syntax checks, installation and sync are different observations
TV29's October 29 run used the exact four input texts; `pine_check` means only that no errors were parsed from a guest server reply. It did not compile in Desktop or install a script:
| Preset file | Intended script name | Desktop install | Desktop compile | `pine_check` of the exact file text | Saved script ID |
|---|---|---|---|---|---|
| `exit_levels.pine` | `NS 2026-10-29 · exit_levels` | Not run (blocked) | Not run (blocked) | `compiled:true`, 0 errors, 0 warnings | none (nothing saved) |
| `ema_cross.pine` | `NS 2026-10-29 · ema_cross` | Not run (blocked) | Not run (blocked) | `compiled:true`, 0 errors, 0 warnings | none |
| `hurst_vpin.pine` | `NS 2026-10-29 · hurst_vpin` | Not run (blocked) | Not run (blocked) | `compiled:true`, 0 errors, 0 warnings | none |
| `quote_imbalance.pine` | `NS 2026-10-29 · quote_imbalance` | Not run (blocked) | Not run (blocked) | `compiled:true`, 0 errors, 0 warnings | none |
TV29 independently read back six symbol/timeframe pairs (CMG/BHC/MYRG × D/5m). Later TV14/TV12 record J1's two-run new-script/binding/compile pass, J2's layout pass but indicator-preset FAIL/manual fallback, and attributed October 30 installation of four files; full persistence/inputs/chart/fill parity remains **unverified**. These came from controller tool-call receipts, not a shell replay. TVR: supervised `--research --apply` at 2026-11-02 15:41Z stored 100/100 movers, 0 rejected/corrective removals, 7 calls, exit 0. TV14's later 88 successful cycles used 5 calls in 80 cycles, maximum 8, about 1–2/minute. Its November 5 correction confirms the vendor's ~100 requests/minute/user statement and repairs the IBKR bracketing FAQ link.
**Unverified in this harvest:** operator-only raw archives and scratch helpers, original complete reproduction, measured fill/execution/cost/latency coverage, multi-year history, out-of-sample edge, later deployment/account acceptance and a new cross-family review. Accepted policies and historical observations are not new readiness claims.
