# Known-defect review receipts

This is receipt-only measurement of reviews against **20 real historical defects and three clean, bounded controls**. It does not run models, repair code, place orders, or certify a reviewer. Cases cite the faulty commit and file line plus the actual fixing commit or review comment. Earlier `sextant` history is retained alongside `sextant-next` history; PR numbers always have a repository-qualified URL.

The measurement follows [CR-Bench](https://arxiv.org/abs/2603.11078v1) and [CR-Bench-v2](https://arxiv.org/abs/2611.02566v2): judge whether a review identifies a labeled root cause, rather than matching words or rewarding tool calls. Sources read 2026-11-09. This adapts the defect-centric method to this repo, with curated severities and bounded source excerpts; it is not the published CR-Bench dataset or a reproduction of its results. The version string `schema_version: "1.1"` follows this repo's native skill-routing cases; the `input` and `expected` fields are a review-specific contract, not a Claude tool-use grader.

## Run offline

```bash
python3 scripts/review_eval.py --check
python3 scripts/review_eval.py --check --json-output review-eval.json --markdown-output review-eval.md
uv run --frozen pytest tests/proofs/test_review_eval.py
```

Both scoring and `--check` always validate the corpus and every committed receipt; neither calls a model or needs an API key. Invalid counts, missing citations, changed excerpt hashes, stale receipts, incomplete semantic judgments and duplicate cohort/case IDs fail validation. JSON and Markdown reports still describe a validation failure. A corpus with no receipt files has unavailable rates, not a passing evaluation.

## Record a receipt

1. Choose a fresh run/cohort ID and preserve every attempted case, including errors and timeouts. One receipt JSON file represents one reviewer configuration, one adjudicator and at most one attempt per case. Retests use a new file and never replace a failed attempt. Record the actual family, runtime version, model and effort; use `unavailable` where the evidence does not attest them.
2. Give the reviewer only `python3 scripts/review_eval.py --review-input CASE_ID` output, plus necessary source context at the pinned faulty commit. This projection omits `expected`, fix commits, control labels and ground-truth citations. Do not show the complete case or later fixes. Bounded inputs measure focused detection; a separate full-PR experiment needs separately recorded input and context. Run any reviewer manually outside CI through its authorized native runtime; this PR supplies no executor.
3. Retain the full review text and its durable reference in the receipt. Obtain its case binding with `python3 scripts/review_eval.py --case-hash CASE_ID`. Copy the structure of a committed receipt into `receipts/NEW_ID.json`, change `kind` to `evaluation`, and populate the actual run metadata and every attempt. `findings` contains stable IDs and the review's claims. `status` is `completed`, `error` or `timeout`; incomplete attempts need an `error` string and empty `judgments`. `blocked` is the observed blocking decision, or `null` when unrecorded; a finding alone does not prove a gate blocked.
4. Separately adjudicate every expected defect against the completed review. Record `adjudicator.name`, `method: "semantic-manual"` and a reference documenting the adjudication. The curator can be an engineer or an explicitly identified agent; the scorer itself performs no semantic inference. Each judgment needs `defect_id`, boolean `detected`, `finding_ids` and a one-line `reason`. A hit needs a cited finding that identifies the same faulty mechanism and consequence; a warning about size, style, source coverage or a different bug is not a hit. A miss has empty `finding_ids`. Clean controls have no known defects or judgments.
5. Run `--check`, review the raw evidence and judgments, then commit through an ordinary sourced PR. Do not edit old receipts to improve a score. A corrected label requires an explicit correction record and new cohort, preserving the superseded evidence in Git.

The two initial receipt files are **retrospective source-review matches**: dsh's actual P1 relative-link finding in #79 and Codex's two findings in #55. The original reviews saw wider PR context, not these isolated excerpts. Their runtime versions, models and effort are unavailable; the receipt metadata says so. The corpus curator's semantic matches are recorded, not independently validated judgments. These examples demonstrate ingestion and provenance, not blind performance or a reviewer comparison.

## Rates and uncertainty

For each receipt cohort, the report lists every case and every defect's detection. Unattempted cases have null detections and remain explicitly unavailable. Completed misses and attempted errors/timeouts contribute zero hits. Cohorts, reviewer configurations and retries are never pooled.

| Metric | Numerator / denominator |
|---|---|
| KDDR | Detected labeled defects / labeled defects in attempted cases; failures remain misses |
| False-block rate | Controls with an observed block / attempted controls with a recorded boolean block decision |
| Coverage-failure rate | Case attempts with reviewer error or timeout / all attempted cases |

Unknown block decisions are counted separately and excluded from the false-block denominator. A coverage failure that explicitly blocked a clean control counts in both rates. Missing attempts are not called reviewer errors or successes. The local multi-defect extension uses defect opportunities rather than the paper's one-defect-per-instance convention; the initial corpus has one defect per defective case.

Every rate includes a two-sided Wilson 95% interval; a zero denominator produces null rate and interval. The stdlib implementation follows [statsmodels `proportion_confint(method="wilson")`](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportion_confint.html), citing Brown, Cai and DasGupta (2001), DOI [10.1214/ss/1009213286](https://doi.org/10.1214/ss/1009213286), read 2026-11-09. Related defects from one PR and projections of one original review are correlated: these descriptive binomial intervals do not establish independent samples or transferable performance. Use the same adjudicator and a complete, independent cohort before comparing reviewers.

## Stop conditions and operational registry

Stop interpreting performance if the corpus has fewer than 20 cases, or **any reported Wilson half-width exceeds 15 percentage points**. Also stop for missing cases, zero-denominator metrics, unknown run metadata or retrospective-only evidence. These are reporting limits; they do not fail a PR on its review score. Twenty defects and three controls are only the seed corpus: three control outcomes cannot produce a sufficiently narrow Wilson interval, even with zero false blocks. More independent controls and full receipts are needed.

| Value | Authority and use |
|---|---|
| At least 20 cases, at least 20 defect cases, at least 3 controls | Lead PR2 plan/dispatch, 2026-11-09; validated from `parameters.json` |
| Confidence 0.95; maximum half-width 0.15 | Lead PR2 plan and Wilson source above; explicit sourced reporting bounds, not calibrated success thresholds |
| Weekly `23 7 * * 1`; job timeout 15 minutes | Reuses `.github/workflows/consolidation.yml`'s scheduled trusted-code receipt shape; weekly frequency is the lead PR2 request |

No missing registry row has a fallback authority. Reviewed changes to these bounds happen between runs; no automatic tuning or promotion exists.

## The #55 incident and why this does not block

[The actual dsh review of #55](https://github.com/seathatflowsinourveins/sextant-next/pull/55#pullrequestreview-5829693820) reported `review-coverage` after a capped 60,492-character diff. That is an incomplete review, not a discovered code defect. Its unchanged public review is preserved under `incidents/`, outside scored receipts. Another reviewer found real defects elsewhere at that same head, so the whole head is not labeled clean. The #55 clean control is only the cited default-branch guard/runner/permissions stanza. The other controls use corrected parsers with committed regression proofs; no claim extends beyond their excerpts.

`.github/workflows/review-eval.yml` has only manual and weekly triggers, runs trusted default-branch code on GitHub-hosted compute with contents-read/issues-write, and updates one receipt issue. It consumes committed receipts; model execution stays outside CI. It does not publish a status to a PR, join a required check, or change a review verdict or ruleset. The offline proof is ordinary validation of this implementation; no detection score, false-block rate or interval becomes a merge gate. The historical examples remain stopped for interpretation until real coverage and precision exist.
