#!/usr/bin/env bash
# The lifecycle sweep's precheck. Orca runs the sweep only when this exits 0, so a quiet day costs no
# agent run (stablyai/orca@a162e08b29b2883b02d8a0dfcc99e26c80b2cfe7:docs/site/content/docs/cli/automations.mdx).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 1

git fetch --prune --quiet origin || exit 1
# A worktree besides this checkout.
[ "$(git worktree list --porcelain | grep -c '^worktree ')" -gt 1 ] && exit 0
# A local branch whose branch on GitHub is gone.
git for-each-ref --format='%(upstream:track)' refs/heads | grep -q '\[gone\]' && exit 0
# A newer Orca release than the pin, out at least as long as Dependabot's cooldown here, 3 days.
pin=$(sed -n 's|.*/releases/download/\(v[0-9.]*\)/orca-ide_.*|\1|p' deploy/wsl/sextant.user-data)
release=$(gh release view -R stablyai/orca --json tagName,publishedAt --jq '.tagName + " " + .publishedAt') || exit 1
tag=${release%% *}
published=$(date -d "${release#* }" +%s) || exit 1
[ -n "$pin" ] && [ "$tag" != "$pin" ] && [ $(($(date +%s) - published)) -ge 259200 ] && exit 0
exit 1
