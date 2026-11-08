---
name: Review with Claude
description: Review a pull request outside its author's family with Claude and pass or fail its required check.
on:
  pull_request_target:
    types: [opened, synchronize]
    acknowledge-risk: true
  bots: ["dependabot[bot]", "sextant-lanes-seathatflows[bot]"]
if: "(!contains(github.event.pull_request.body, 'Review-Family') || contains(github.event.pull_request.body, 'Review-Family codex') || contains(github.event.pull_request.body, 'Review-Family claude') || contains(github.event.pull_request.body, 'Review-Family dsh')) && !contains(github.event.pull_request.body, 'Agent-Family claude') && (contains(github.event.pull_request.body, 'Agent-Family codex') || contains(github.event.pull_request.body, 'Agent-Family dsh')) && !(contains(github.event.pull_request.body, 'Agent-Family dsh') && contains(github.event.pull_request.body, 'Agent-Family codex')) && !contains(github.event.pull_request.body, 'Review-Family dsh') && !contains(github.event.pull_request.body, 'Review-Family codex') && (contains(github.event.pull_request.body, 'Review-Family claude') || (contains(github.event.pull_request.body, 'Agent-Family dsh') && !contains(github.event.pull_request.body, 'Agent-Family codex')))"
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
# ADR-0030 #5; gh-aw v1.0.1 frontmatter.md documents -1 as intentionally uncapped daily usage.
max-daily-ai-credits: -1
timeout-minutes: 30
---

# Review this pull request

Review pull request #${{ github.event.pull_request.number }} of ${{ github.repository }} at its head commit `${{ github.event.pull_request.head.sha }}`. Read the diff and any file at that commit through the GitHub tools. Your checkout is the base branch, so `AGENTS.md` there is the rule set this PR is reviewed under.

{{#runtime-import .github/workflows/shared/review-rules.md}}
