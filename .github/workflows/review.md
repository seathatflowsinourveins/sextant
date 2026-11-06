---
name: Review with dsh
description: Review a pull request with dsh against the upstream rubric and pass or fail its required check.
if: "contains(github.event.pull_request.body, 'Agent-Family dsh') == false"
on:
  pull_request_target:
    types: [opened, synchronize, reopened, ready_for_review]
    acknowledge-risk: true
  bots: ["dependabot[bot]", "sextant-lanes-seathatflows[bot]"]
permissions:
  contents: read
  pull-requests: read
environment: review
checkout: {}
strict: false
engine:
  id: deepseek-harness
  env:
    ANTHROPIC_BASE_URL: https://api.deepseek.com/anthropic
    ANTHROPIC_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
model: anthropic/deepseek-v4-pro
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
timeout-minutes: 30
---

# Review this pull request

Review pull request #${{ github.event.pull_request.number }} of ${{ github.repository }} at its head commit `${{ github.event.pull_request.head.sha }}`. Read the diff and any file at that commit through the GitHub tools. Your checkout is the base branch, so `AGENTS.md` there is the rule set this PR is reviewed under.

{{#runtime-import .github/workflows/shared/review-rules.md}}
