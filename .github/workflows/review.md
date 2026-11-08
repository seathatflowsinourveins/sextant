---
name: Review with dsh
description: Review a pull request with dsh against the upstream rubric and pass or fail its required check.
if: "(!contains(github.event.pull_request.body, 'Review-Family') || contains(github.event.pull_request.body, 'Review-Family codex') || contains(github.event.pull_request.body, 'Review-Family claude') || contains(github.event.pull_request.body, 'Review-Family dsh')) && !contains(github.event.pull_request.body, 'Agent-Family dsh') && (contains(github.event.pull_request.body, 'Agent-Family codex') || contains(github.event.pull_request.body, 'Agent-Family claude') || (!contains(github.event.pull_request.body, 'Agent-Family') && !contains(github.event.pull_request.body, 'Review-Family dsh'))) && !(contains(github.event.pull_request.body, 'Agent-Family codex') && contains(github.event.pull_request.body, 'Agent-Family claude')) && !contains(github.event.pull_request.body, 'Review-Family claude') && !contains(github.event.pull_request.body, 'Review-Family codex')"
on:
  pull_request_target:
    types: [opened, synchronize]
    acknowledge-risk: true
  bots: ["dependabot[bot]", "sextant-lanes-seathatflows[bot]"]
permissions:
  contents: read
  pull-requests: read
environment: review
checkout: {}
runs-on: [self-hosted, linux, x64, sextant-jit-docker]
runs-on-slim: [self-hosted, linux, x64, sextant-jit-sealed]
runner:
  topology: arc-dind
strict: false
engine:
  id: deepseek-harness
  env:
    ANTHROPIC_BASE_URL: https://api.deepseek.com/anthropic
    ANTHROPIC_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
model: anthropic/deepseek-flash
# AWF's API proxy prices only models in its own tables, which lack DeepSeek's API name deepseek-flash
# (gh-aw reference/glossary.md "Missing Model AI Credits Pricing"). DeepSeek's published peak rates
# for it, in $/1M tokens (api-docs.deepseek.com/quick_start/pricing, read 2026-11-07), bound the guard.
models:
  default-ai-credits-pricing:
    input: 0.3
    output: 1.2
    cache_read: 0.006
imports:
  - shared/deepseek-harness.md
network:
  allowed:
    - defaults
    - api.deepseek.com
tools:
  github:
    mode: gh-proxy
    toolsets: [repos, pull_requests]
safe-outputs:
  runs-on: [self-hosted, linux, x64, sextant-jit-sealed]
  threat-detection: false
  create-check-run:
    name: review
  create-pull-request-review-comment:
    max: 20
  submit-pull-request-review:
    allowed-events: [COMMENT]
  create-issue:
    max: 1
    title-prefix: "Review follow-up: "
# ADR-0030 #5; gh-aw v1.0.1 frontmatter.md documents -1 as intentionally uncapped daily usage.
max-daily-ai-credits: -1
timeout-minutes: 30
---

# Review this pull request

Review pull request #${{ github.event.pull_request.number }} of ${{ github.repository }} at its head commit `${{ github.event.pull_request.head.sha }}`. Read the diff and any file at that commit through the GitHub tools. Your checkout is the base branch, so `AGENTS.md` there is the rule set this PR is reviewed under.

{{#runtime-import .github/workflows/shared/review-rules.md}}
