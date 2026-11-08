---
name: Review with Claude
description: Review a dsh-written pull request with Claude against the upstream rubric and pass or fail its required check.
on:
  pull_request_target:
    types: [opened, synchronize, reopened, ready_for_review]
    acknowledge-risk: true
  bots: ["dependabot[bot]", "sextant-lanes-seathatflows[bot]"]
if: ${{ contains(github.event.pull_request.body, 'Agent-Family dsh') }}
permissions:
  contents: read
  pull-requests: read
environment: review
checkout: {}
runs-on: [self-hosted, linux, x64, sextant-jit-docker]
runs-on-slim: [self-hosted, linux, x64, sextant-jit-sealed]
runner:
  topology: arc-dind
engine:
  id: claude
  env:
    # Claude Code's documented effort setting; gh-aw's ?effort= applies only in routed mode.
    CLAUDE_CODE_EFFORT_LEVEL: max
model: opus
network:
  allowed:
    - defaults
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
timeout-minutes: 30
---

# Review this pull request

Review pull request #${{ github.event.pull_request.number }} of ${{ github.repository }} at its head commit `${{ github.event.pull_request.head.sha }}`. Read the diff and any file at that commit through the GitHub tools. Your checkout is the base branch, so `AGENTS.md` there is the rule set this PR is reviewed under.

{{#runtime-import .github/workflows/shared/review-rules.md}}
