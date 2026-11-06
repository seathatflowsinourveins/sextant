# Blind-leg convergence: landscape and memory (#54)

Read date for every source: **2026-11-06**. Reconciled by a Claude worker (Claude Code, Opus 5.5) so neither the GPT nor the DeepSeek family reconciles its own legs (ADR-0001's other-family rule). Every disagreement below was checked at its primary source, at a pinned SHA or a dated docs read. This record decides roles; it measures no trading merit.

## Inputs

All on release [`research-legs-2026-11-06`](https://github.com/seathatflowsinourveins/sextant/releases/tag/research-legs-2026-11-06), SHA-256 of the bytes reconciled:

| Leg | Runtime, effort | SHA-256 |
|---|---|---|
| `landscape-leg-gpt-ultra.md` | Codex 0.167.0, gpt-6.1-sol, **ultra** (its highest) | `38f12de72ff09d3e42004fb6f4488f8097e90e72b34413d2f2c0d478812793a9` |
| `landscape-leg-deepseek.md` | dsh 0.2.2-rc.1, deepseek-v4-pro, **max** (schema `off/low/high/max`) | `ae15a1b8e2a7c82fd0a5ae2f728bf676e387a8d608bcc7f17852dd86892a935e` |
| `memory-leg-gpt-ultra.md` | Codex 0.167.0, gpt-6.1-sol, **ultra** | `7b7a4532f64f53723471bc113d14213cc1edd726ec70927c512d284d111f4a0a` |
| `memory-leg-claude.md` | Claude Code 2.1.319, Opus 5.5, **max** | `5186fd984fdc6d3a44e228594eafdd7987a27e8362a0cb4ea2b25d5705cff14c` |
| `memory-leg-deepseek.md` (agent memory only) | dsh 0.2.2-rc.1, deepseek-v4-pro, **max** | `f47fdcf80002842749fafe3fa477af6d7aca4e1b6aa2dbd8d53e46025cce9f68` |

`landscape-leg-gpt.md` and `memory-leg-gpt.md` ran at max when ultra was offered and disqualify themselves; they are not read here. **No Claude landscape leg exists** on the release, so landscape converges on two families (GPT, DeepSeek). `data-leg-claude.md` covers a different brief and is not a landscape vote.

## Verdicts

**Adopt** = a new pick lands with a manifest row and proof in this PR. **Replace** = an incumbent changes. **Hold** = the incumbent stays; anything new waits for its named owner or trigger.

### Memory (three jobs)

| Job | Verdict | Reason, checked at source |
|---|---|---|
| 1. Agent memory across runtimes and devices | **Hold.** Native per-runtime memory only; no capture layer | GPT ultra: "none demonstrated". Claude and DeepSeek: memsearch v0.4.23 `65d8b220…`, but both concede the last mile is unsolved. At that SHA the only `git push` in the repo is `.github/workflows/release.yml`; plugins commit nothing. Its Claude README also says Milvus Lite "does not support concurrent access", a ~558 MB first-run model, and a per-turn `claude -p --model haiku` summary. Closing the gap needs sync glue (Rule 1 forbids it) or the owner's `memory/*` push exception, which is not granted. Runner-up stays ai-memory v3.4.2 `b9453c96…`, whose wikisync "never runs git" |
| 2. Research retrieval over this repo | **Replace → adopt qmd v2.8.3** `facd35e01359e59d938bc9418e93fb9318addee3` for repo documents; OpenViking keeps only the enhanced-dsh synthesis role | Both full memory legs pick qmd on the brief's criteria. Both landscape legs keep OpenViking, DeepSeek "per ADR-0022" and GPT ultra "do not replace the accepted architecture on benchmark marketing alone", so they defer to the record rather than judging it. Primary: OpenViking v0.5.3 `178a8cdf…` README, Quick start, "needs uv, Python 3.10+ and a model provider with an embedding model and a VLM", AGPL-3.0, and its benchmark is 0.3.22 on Doubao models. qmd README: `search` is "BM25 full-text search only"; a project-local `.qmd/index.yml` travels with a clone and in-project paths need no trust. npm `@tobilu/qmd@2.8.3` gitHead is `facd35e…`, MIT. The old finalized baseline (ADR-0022 M) already held qmd 2.8.3 with rerank and expansion off |
| 3. Compounding | **Hold.** Lessons stay in `docs/handbook/` and the changed rule or skill, through a PR; `ce-compound` is already on the shelf | All four legs that answer agree on repo records. Claude's scheduled gh-aw reflection (gh-aw v1.0.1 `0627fdbe…` `repo-memory` + `create-pull-request`) is a sourced shape. Scheduled gh-aw upkeep is already in the manifest's "Decided, not yet installed" list, so it lands there by its own PR, not here |

### Landscape (eleven jobs; job 9 is the memory table above)

| Job | Verdict | Disagreement and the primary-source check |
|---|---|---|
| 1. Whole-market live scan | **Hold** Alpaca SIP + BOATS (owned) | GPT ultra names dxFeed for qualification and DeepSeek names Alpaca. dxFeed's page says it "consolidates liquidity across key overnight venues, including Bruce ATS, Blue Ocean ATS, Moon ATS" and gives no price. Alpaca's 24/5 page names only BOATS for overnight executions and data (`feed=boats` on Plus). So the gap is real: Alpaca overnight is one ATS. A dxFeed quote is the owner's purchase question, not an adoption |
| 2. Historical extreme movers | **Hold**: audit the owned Sharadar first (#42) | GPT ultra picks Massive Advanced; DeepSeek picks Norgate Platinum. Massive's page: $199/month, "personal and non-professional use", delisted tickers kept, "4AM–8PM ET" with no overnight. Norgate's page: Platinum USD 630 a year from 1990, Diamond USD 787.50 from 1950, delisted included, no US intraday stated. One is intraday and the other daily, so they are not substitutes. Either is the owner's buy |
| 3. Ranking and onset | **Hold** the owner's K2 incumbent; ORB stays a reference card | GPT ultra wants the Zarattini–Barbon–Aziz ORB reproduced; DeepSeek says no upstream ranker exists. Both concede that no source certifies first-second whole-market onset after costs. The ORB card landed in #71 |
| 4. Exits | **Hold** Nautilus native mechanics; no economic pick | Agree. Both carry the negative result (hold-to-15:55 beat all 96 variants) and neither reran it. Its rerun has already landed (#67) |
| 5. NautilusTrader | **Hold** rc7; rc8 is a separate migration | Both name rc8 `d53849b216e20f2c122ca01b4dd0da377638b186` (prerelease, 2026-10-29). The adapter directory at rc8 lists architect_ax, betfair, binance, blockchain, bybit, coinapi, coinbase, databento, deribit, derive, dydx, hyperliquid, interactive_brokers, kraken, lighter, okx, polymarket, sandbox and tardis: **no Alpaca**, as both say. DeepSeek's "RiskEngine replaces the account pacer" and "request_group replaces pagination" claims are unpinned and stay declined, as in #71's checklist |
| 6. Research lane | **Hold**; EdgarTools stays the named candidate (#53) | Agree on EdgarTools. RD-Agent (GPT) and gpt-researcher (DeepSeek) are runner-ups with no named unmet need |
| 7. Jev | **Hold** typesafe-sdk-python v0.7.5 + `jev-1.14.0`, zero-weight sim arm | Agree. "$0.042 per million" and "$42 per billion" input tokens are the same price |
| 8. Skills | **Hold** the shelf. Bump `tradermonty/claude-trading-skills` by its own PR after cooldown | GPT ultra pins `ff8ca70d93f596caa216a61a183a66a1351ba138` against the shelf's `d8e71ce2…`. The compare is 3 ahead, 0 behind, committed 2026-11-06. It fixes `options-strategy-advisor/SKILL.md`, whose `--iv` flag "black_scholes.py silently ignores". FSI `catalyst-calendar`/`thesis-tracker` stay #53 candidates |
| 10. Hosting | **Hold** clean WSL + Orca + rootless Docker; VPS only on a measured trigger | Agree |
| 11. Beyond | **Hold**; record one fact | GPT ultra says arch 9.0 now studentizes SPA. At arch `87b697e4…` the docs say `versionchanged:: 9.0`, "Previously `studentize=True` had no effect". The latest release is v8.0.0, so 9.0 is **unreleased**. Any SPA p-value from ADR-0019's arch must name its version before it is compared |

## What this PR adopts

- **qmd v2.8.3** for repo-document retrieval: manifest row, `tests/proofs/test_qmd.py` and the ADR-0022 amendment. Measured on the clean distro (Node 24, npm 11): a locked install in its own tree, `qmd 2.8.3 (facd35e)`, `qmd update` indexed 50 documents into a 2 MB `.qmd/index.sqlite`, and `qmd search OpenViking` ranks ADR-0022 first. Nothing was written to `~/.config` or `~/.cache`, no model was fetched and no install script ran. Footprint: 854 MB on disk, 662 MB of it node-llama-cpp's prebuilt binaries, which `search` never loads. `--omit=optional` breaks `sqlite-vec`, so the documented install stays whole.
- **Two upstream facts the legs did not report:** qmd's peer `typescript ^5.9.3` conflicts with the agents tree's 7.0.2, so qmd gets its own tree, as upstream's global install does. qmd resolves `./` paths from `$PWD`, so run it from the checkout in a shell; a subprocess must pass a matching `PWD`.

## Not verified

- qmd's retrieval quality on this corpus (`qmd bench` fixture not written), its Mac install, and the sandbox image build. The proof's runtime test needs `qmd` on PATH, as `test_runtimes_match_their_pins` needs `codex`.
- dxFeed price, rights and latency; Alpaca `v2/sip` overnight behavior; the Sharadar audit (#42).
- memsearch capture quality and cost; any two-device handoff. Nothing was installed for job 1.
- PR #71 landed first with an earlier qmd selection and the "pending ultra" limitation. This record supersedes that pass for the qualifying legs. Its source cards, briefs and rc8 checklist stand.
