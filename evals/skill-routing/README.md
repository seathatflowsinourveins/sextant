# Native skill activation checks

The owner's #29 step 4/#53 request: natural lane requests should activate the appropriate skill without naming it. This uses Claude Code's **own `claude plugin eval`**, schema 1.1, on the owner's native sign-in. Cases are JSON documents, a YAML subset, in the documented `case.yaml` format. There is no API bridge, custom grader, model router or model run in CI.

| Case | Lane | Expected skill (hidden grader, absent from the prompt) |
|---|---|---|
| research-draft | Research | edge-strategy-designer |
| sim-backtest | Sim | backtest-expert |
| paper-entry | Paper | pre-trade-discipline-gate |
| live-draft-review | Live | edge-strategy-reviewer |
| options-research | Options | options-strategy-advisor |
| tradingview-ticket | TradingView | pre-trade-discipline-gate |
| paper-journal | Paper | trader-memory-core |
| sim-postmortem | Sim | signal-postmortem |
| support-pr | Cross-lane publication text | ce-commit-push-pr |

Each target also has a plain word-sorting request that must call no skill. Positive graders match the exact `Skill` tool input, including its native namespace. The case definitions are hidden from the agent by the native evaluator. Every case grants only Read/Glob/Grep/Skill; there are no shell grants, writes, real MCP servers, scaffolds or external actions. These are routing requests, not trading experiments, calibration or permission to promote a lane.

## Stage and run locally

Use the clean distro's installed first-party Claude Code, signed in through claude.ai. The staged/full-run runtime is the repository's **2.1.318** pin, `anthropics/claude-code@v2.1.318` `646b74189c735abbccf78ef5cb7ddd38a07a36eb`. An earlier preflight/pilot used 2.1.319 (`0ed94698aa0aeee471465fc9c867c2e8434c4d68`); the executable changed before later staging. Preserve each attempt's captured version and do not pool the two cohorts. Native `claude auth status` can report the sign-in method without reading a credential store. No API key is injected.

```bash
bash evals/skill-routing/stage.sh /tmp/sextant-skill-routing-NEW
CLAUDE_CODE_EFFORT_LEVEL=max claude plugin eval /tmp/sextant-skill-routing-NEW/trading --model claude-opus-5-5 --judge-model claude-opus-5-5 --ablation with-without --concurrency 3 --no-publish --trust-plugin --output-dir /tmp/sextant-skill-routing-results-NEW/trading
CLAUDE_CODE_EFFORT_LEVEL=max claude plugin eval /tmp/sextant-skill-routing-NEW/compound --model claude-opus-5-5 --judge-model claude-opus-5-5 --ablation with-without --concurrency 3 --no-publish --trust-plugin --output-dir /tmp/sextant-skill-routing-results-NEW/compound
```

Use a new destination/results directory for every attempt and retain failed attempts. The native default is three runs per arm and concurrency one. The operator can use the documented `--case`/`--runs 1`/`--ablation none` for an initial pilot, then confirm at the default three runs. Every run requests Opus 5.5 and max effort; no lower-effort or cheaper fallback. `CLAUDE_CODE_EFFORT_LEVEL` is inherited by native eval children and takes precedence over skill effort settings. Runtime model receipts and the requested effort are separate evidence.

The staging helper snapshots exactly the committed seven-skill shelf, with a minimal native plugin manifest, following Anthropic's conversion of an existing skill directory to a plugin. It copies the installed compound-engineering 3.36.0 plugin and adds only these case files. It does not modify or install a plugin, change its descriptions, or copy project/private settings into the trading snapshot. `source-sha.txt`, `shelf.lock.json` and the actual CLI version accompany it. The installed compound code is trusted under the existing shelf decision; its hooks, if any, remain outside the evaluator's tool sandbox, so scores are advisory as Anthropic documents.

**Scope:** the native evaluator deliberately excludes personal/project settings, other plugins and normal workspace skills. This checks the unchanged skill bodies in isolated native plugin sessions; it does not certify routing in the full interactive shelf or end-to-end execution of the skills' scripts. Real trading work retains the repository's source, clock, Decimal, custody and promotion rules.

## Read the actual evidence

`aggregate-result.json` and the local HTML report are native outputs. `--no-publish` keeps the evaluation off the hosted eval dashboard. This row commits the small, unchanged native JSON reports and captured shelf lock under `receipts/2026-11-06`; HTML reports and native temporary homes/traces stay outside Git. For each case/arm record the run count, exact skill calls, grader verdicts, runtime model/version and errors. These graders measure activation only; an artificial no-plugin contrast is not an answer-quality or trading-merit gain.

**A high score or exit 0 is insufficient.** Native evals can award a firing grader 1.0 when the skill was called but the run later timed out. Acceptance needs a non-partial suite, no error/abort/skipped grader in any run, the expected skill in every positive with-run, and no skill in the controls. Preserve without-arm results too. The native report's `cases[].arms.with[].error` is authoritative even when the score is 1.0; apply the same check to `without`.

For example, inspect native completion before reading the firing grades:

```bash
jq -e '(.partial == false) and all(.cases[].arms | .with[]?, .without[]?; .error == null and .aborted == null and (.skippedPaidGraders | not))' /path/to/aggregate-result.json
```

Then read every grader in both arms, check the nine trading/two compound cases and three replicates per arm, and record failed/missing cases explicitly. Positive `skill-fired` failures in the without-arm are expected; unrelated-request controls must pass in both arms. The absence of a result is not a zero or a success.

The original pilot used the documented default 300-second cap. Both arms timed out; the with-arm did call `backtest-expert` once and the without-arm called none. That is observed activation, **not a passing pilot**. Cases now allow the documented maximum 3,600 seconds to leave room for requested max-effort reasoning; this is an uncalibrated operational bound, not a measured latency target. The default three runs/arm and threshold 1.0 come from the native evaluator, not a house score.

| Operational setting | Value and authority | Evidence limit |
|---|---|---|
| Model/effort | Opus 5.5/max; owner's current model rule, native model/effort docs | Requested max; backend effort is not independently attested |
| Replicates/threshold | 3 per arm / 1.0; native defaults | Activation only, no quality/merit inference |
| Per-run timeout | 3,600 seconds; native documented cap, after the default 300-second pilot timed out | Starting operational bound, not calibrated latency |
| Turn limit | Native default 10; paper-journal retest/current case 200, the documented supported cap, after its first batch exhausted 10 | Operational bound, not a calibrated quality/latency target; other cases retain the default |
| Concurrency | 3; native supported 1–8, keeping native child contexts independent and the host above #53's 20 GiB available floor | 33 GiB available before the full batch; account throughput remains shared |

The revised single-case pilot completed error-free in 311 seconds and called `backtest-expert` once. Its stage version and native aggregate both report 2.1.318; the earlier failed pilot reports 2.1.319. These are separate attempts, not a same-run metadata discrepancy. One run is a pilot, not the default three-run acceptance.

## Recorded results, 2026-11-06

| Native attempt | CLI | Actual child runs | Completion and use |
|---|---|---:|---|
| Original 300-second pilot | 2.1.319 | 2 | Both timed out, despite the with-arm firing grade; retained as failed evidence |
| Revised sim-backtest pilot | 2.1.318 | 1 | Complete in 311 seconds, activation observed; pilot only |
| Full trading suite | 2.1.318 | 54 | All expected skills fired; one paper-journal with-run exhausted 10 turns. Retain all results; accept the other eight whole cases |
| Full compound suite | 2.1.318 | 12 | Both cases, all three runs per arm complete; expected PR skill fired and unrelated control stayed quiet |
| Whole paper-journal retest | 2.1.318 | 6 | Same prompt, grader and skill bytes; native 200-turn cap. All three runs per arm complete; expected skill fired with-plugin only |

`attempts.json` records all **75 actual runs**, source-snapshot identity where captured, version, result hash and disposition. The accepted 66-run coverage uses eight original trading cases, the whole paper-journal retest and both compound cases: all nine positive routes fire in all three with-plugin runs (27/27), all positive baselines call none (27/27), and the two unrelated controls call none in either arm (12/12). No errors, aborts or skipped graders occur in those accepted whole-case cohorts. The rejected journal attempt remains visible; no grader, skill body, model or effort was changed to obtain the retest. A full future rerun uses the current paper-journal turn cap directly.

Native aggregates do not attest the backend effort or retain every passing model trace; Opus 5.5/max are the explicit requested settings. The failed pilot's inspected native trace identified Opus 5.5 only for that run. These results establish isolated automatic activation for these requests and pins, not full interactive shelf routing, task quality, runtime-script execution or trading merit.

`uv run --frozen pytest tests/proofs/test_skill_evals.py` checks the offline case contract and captured native evidence: all six lanes/selected skills have name-free prompts, read-only grants and exact graders, unrelated controls exist, accepted runs have no completion errors, and failed attempts remain hashed and visible. It does not start Claude or rerun models in CI; activation comes from the signed-in native receipts, bound to the captured shelf and current case prompts/graders.

Sources read 2026-11-06: [native eval format, isolation and result/error fields](https://code.claude.com/docs/en/plugin-evals.md), [plugin creation/conversion](https://code.claude.com/docs/en/plugins/create.md), [plugin loading](https://code.claude.com/docs/en/plugins/loading.md), [model/effort configuration](https://code.claude.com/docs/en/model-config.md), and the installed CLI's `plugin eval --help`/`init --bare` output. Skill bytes stay pinned by `.claude/shelf.lock.json`: tradermonty/claude-trading-skills `d8e71ce2f0b069eb5b6fca352857c168c35e6c46`, EveryInc/compound-engineering-plugin v3.36.0 `7dc50943bbf959dbe6a93a175e41e5fff8395e00`.
