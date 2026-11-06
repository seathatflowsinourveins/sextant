#!/bin/bash
# Pre-job hook, using GitHub's documented ACTIONS_RUNNER_HOOK_JOB_STARTED. Selected-workflow
# restrictions are organization features, and on a personal repo a label only routes a job, so
# without this any branch's workflow could run on this host. Only main's workflows run here.
set -euo pipefail
allowed='^seathatflowsinourveins/sextant/\.github/workflows/[A-Za-z0-9_-]+\.ya?ml@refs/heads/main$'
if [[ ! "${GITHUB_WORKFLOW_REF:-}" =~ $allowed ]]; then
  echo "::error::job-guard refused workflow ref '${GITHUB_WORKFLOW_REF:-}': only main's workflows run on this runner."
  exit 1
fi
