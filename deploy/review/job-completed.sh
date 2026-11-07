#!/usr/bin/env bash
set -euo pipefail
checkout_sha=${GITHUB_SHA:?}
if git -C "${GITHUB_WORKSPACE:?}" rev-parse --verify HEAD >/dev/null 2>&1; then
  checkout_sha=$(git -C "$GITHUB_WORKSPACE" rev-parse --verify HEAD)
fi
{
  echo '### Ephemeral runner receipt'
  printf -- '- Runner image content digest: `%s`\n' "${SEXTANT_RUNNER_IMAGE:?}"
  printf -- '- Checkout SHA (event SHA if no checkout): `%s`\n' "$checkout_sha"
  printf -- '- Started (UTC): %s\n' "$(cat "${SEXTANT_JIT_ROOT:?}/.job-started")"
  printf -- '- Ended (UTC): %s\n' "$(date -u +%FT%TZ)"
} >> "${GITHUB_STEP_SUMMARY:?}"
