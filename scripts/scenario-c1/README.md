# Scenario C1 run scripts (archived)

Byte-identical copies of the scripts that produced the C1 rows on this branch (issue #130,
report comment 6712471446). They are archived for reproduction, not imported by the package.
Like `src/sextant/research/b_exit_replay.py`, they are excluded from ruff as frozen research
artifacts.

| file | SHA-256 | produced |
| --- | --- | --- |
| `c1_pull.py` | `d1a42d4b193b6a2abbe07879e421d3594ed7042ecfdd3d91640da0245b834abf` | corporate action (14:32:55) and news (14:33:01) |
| `reserve_c1.py` | `1120c8f243e6f9d1e0f5deceabaf030ba19aab9f375d3189e9d0b371f03f9734` | 18 reserved rows (14:15:08) |
| `lib/handoff.py` | `5154bdfaacc7faff5095fb0bf520e4f81a352a5797d546a9e1d8a9ae4fc296d2` | reserve and outcome batches |
| `c1_run.py` | `37ed1475d0b411856098e350adf016bb90d540a5676aeb4c8dd4a15f70663f5f` | Case C exit, Case B hold-flat, and reruns of A/B exit |
| `c1_detect.py` | `3259df8819c29c709d97334d8e51bab8699f1a4fccfa00c859e4b070bcb7ede6` | Case A/B detection, and rerun of Case C detection |
| `c1_marks.py` | `258dbd33fb6f30344f6b6b43908a6c7ea819981e7c94e3bdea550c1ca76b4ff9` | `run/marks.json` |
| `build_outcome.py` | `a9bd273cd284c6b3b0bdfdf1ac5432bf2486cc79e44b14139cb7b8a14ffc2f2e` | final outcome batch `8ea6e10298fa76d4…` |

## Version caveats

`c1_pull.py` was edited in place during the pull. The committed build (mtime 14:32:51) made the
corporate-action and news calls only. Bars, the quote probe, trades and quotes (14:20–14:32)
came from earlier builds; the 14:17 build (13,403 B) was overwritten and its hash was not
recorded. `raw/SHA256SUMS` (SHA-256 `7f81e4eeeaf3be5cb646085278038ce56b335c709bc723a6d5cc355e81c35c69`,
43 files) pins every raw receipt, so the pulled data stays verifiable.

`c1_run.py` (mtime 14:53:24, adds the `--end` truncation) post-dates the Case A/B receipts
(14:36–14:40). Reruns with this build at 2026-11-07 20:28–20:31Z reproduced `run/a/exit.json`
and `run/b/exit.json` exactly. Case C used this build.

`c1_detect.py` (mtime 14:51:56) post-dates Case C's receipt (14:51:48). A rerun with this build
at 20:28:24Z reproduced it exactly (rvol `2.831653074946684445571975017`). Case A/B used this
build.

`c1_marks.py` (14:52:44) produced `run/marks.json` at 14:56:50. `build_outcome.py` (15:10:53)
produced the accepted batch; the two earlier batches (`dc67f44e…`, `31bdeae9…`) were refused by
the ledger and are not kept.
