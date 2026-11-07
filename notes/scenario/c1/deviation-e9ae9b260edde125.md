# C1 execution deviation note: fill model and entry arming

- **Attempt:** lane `scenario`, issue #130, attempt `c1`; trials 154–171 (18 reserved MODELED rows).
- **Outcome annotated:** ledger commit `18750311299755a54948e60e87502ac439f6552d`; outcome rows `8ea6e10298fa76d4a39c3dd0048895f2673ec9d40f781e10688db341af41ef97` (`manifest_sha256` `7414bcf26486a3bc16687f724bc693383defdfff37bedb9427b67216f225a9cd`).
- **Protocol:** `904747d4b928cae4af890597ef2c403f8c90fb86dfbe189a1b36a09c104e2110`, §4 and §5.
- **Status:** disclosed execution deviation, accepted by the lead; no row changes.

## 1. Rows the deviation touches

Six of the nine COMPLETE rows used a fill: exit 156, 162 and 168, and hold-to-15:55 158, 164 and 170. The other three COMPLETE rows (157, 163 and 169, hold-flat) hold no position (`position: "none"`, `kind: "no-position"`, returns 0), so no fill touched them. The nine PRUNED rows never reached a fill and are not touched.

| trial | arm_run_id | case | arm |
| --- | --- | --- | --- |
| 156 | `/home/sextant/sextant-data/c1-scenario/run/arms/case-a/exit` | a | exit-engine-p2 |
| 158 | `/home/sextant/sextant-data/c1-scenario/run/arms/case-a/control-hold-1555` | a | hold-to-1555 |
| 162 | `/home/sextant/sextant-data/c1-scenario/run/arms/case-b/exit` | b | exit-engine-p2 |
| 164 | `/home/sextant/sextant-data/c1-scenario/run/arms/case-b/control-hold-1555` | b | hold-to-1555 |
| 168 | `/home/sextant/sextant-data/c1-scenario/run/arms/case-c/exit` | c | exit-engine-p2 |
| 170 | `/home/sextant/sextant-data/c1-scenario/run/arms/case-c/control-hold-1555` | c | hold-to-1555 |

## 2. Registered fill versus what ran

Protocol §4 registers the `minute-bar-approximate` fill (`src/sextant/research/exit_econ_98.py:69`, `MODEL = "minute-bar-approximate"`): a one-share witness entry, then each held minute's quote proxied from that minute's low, and the sell priced off the same minute bar.

What ran: the pinned `ExitEngine` (`09e579fa27b4af5ae458e5b6e899196fd681d430`) composed on the **pulled SIP tick and quote tape** by `c1_run.py` at committed SHA `83d0ec9d67fd9b9b2c722bebc6e7b2d93aa564e2` (file blob `bb06c3f0d3410d789386a33182d20e0ff8e38ac6`, SHA-256 `37ed1475d0b411856098e350adf016bb90d540a5676aeb4c8dd4a15f70663f5f`). Same engine, `ExitParams.starts()`, costs (3 and 6 bps per side) and controls; the difference is the tape: the §4 proxy fills at each minute's derived low, the replay at the actual print or quote.

Cross-check with §4's own tape (`run_entry`, `range_estimable=False`, same minutes, bars and entry):

| case | §4 minute-bar-approximate | native tick/quote composition |
| --- | --- | --- |
| a | sell 4.380 at 10:36 (`breach_sell_gain_lock`) | sell 4.27 at 09:30:36.5 |
| b | sell 4.230 | sell 3.36 |
| c | sell 158.520 (158.470 at 2×) | sell 158.83 |

The ledger rows carry the native-tape numbers because relay 6 froze all but the 24 numeric types; the §4-tape numbers are not reserved and appear only as this cross-check.

## 3. Entry arming versus §5

Protocol `904747d4b928cae4af890597ef2c403f8c90fb86dfbe189a1b36a09c104e2110` §5 (protocol.md lines 98–99) registers the witness buy "at the first SIP trade print at or after 09:30:00 ET".

What ran: `c1_run.py` at `83d0ec9` submits the market buy on the first **quote** with `ts_event ≥ 09:30:00` — the docstring at lines 3–4 ("market buy at the first quote at or after 09:30:00 ET"), the exit arm's `on_quote` at lines 95–108, and the hold control's `on_quote` at lines 129–142. It touches the same six fill rows above, and their entry times and prices are what ran: 3.73 at 09:30:00.032 (a), 4.99 at 09:30:00.099 (b) and 160.59 at 09:30:00.020 (c), each the arming quote's ask. In every case the first SIP print precedes the quote that armed the run by 1–12 ms.

Landed tape, per case:

| case | armed quote (ET) | bid / ask (size) | first SIP print (ET) | print (size) | quote in force at the print |
| --- | --- | --- | --- | --- | --- |
| a | 09:30:00.032 | 3.72 / 3.73 (100/300) | 09:30:00.030 | 3.725 (1) | 09:29:59.992: 3.72 / 3.73 |
| b | 09:30:00.099 | 3.41 / 4.99 (100/100) | 09:30:00.098 | 4.46 (400) | 09:29:57.330: 3.43 / 4.99 |
| c | 09:30:00.020 | 160.52 / 160.59 (500/100) | 09:30:00.008 | 160.583 (57) | 09:29:59.823: 160.52 / 160.59 |

Receipts, SHA-256 of the raw parquet the tape was decoded from:

| case | quotes parquet | trades parquet |
| --- | --- | --- |
| a | `076b2fdcfbfdac040ef59e1313f5b1d8471475bf664b22896f658b2de93e499c` | `a6628c942c1915368801d23f5a044693b7e677db1057f606086d024f5d54239e` |
| b | `c2cc4ae667619a1bdc793e6e0378dbcdda2b5b7fb2b6f3945acb5050763a9f6e` | `f61ec952bfb09b946d962267d0de5bcac430abbaeb68ec81363c2ecee95ba95a` |
| c | `573b546ccb4839fca4ad46b215cbd6ab82779046fdee973c63511b2cebbcc106` | `c8ae936eda8139c3ba92b05623a04d2f1143d73e6134a04117c6072ed137b73f` |

No counterfactual P&L is offered.

## 4. Acceptance

The deviation was disclosed in the C1 report, #130 issuecomment-6712471446, line 65. The lead accepted the ledger lane's deviation-note design by ruling relayed 2026-11-07; this note is that design's record for attempt `c1`.

This note changes no row and adds no trial; N is unchanged by it.
