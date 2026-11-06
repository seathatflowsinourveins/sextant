#!/usr/bin/env bash
# Keeps this checkout and its Orca worktrees clean over a long run, by git's and Orca's own upkeep.
# Safe to run again. Setup runs it; `just lifecycle` does too.
#   - git: `fetch.prune` drops branches GitHub deleted at merge (git-config(1)), and `git maintenance
#     start` registers this repo with git's own scheduled upkeep, on systemd timers here (git-maintenance(1)).
#   - Orca: one daily automation in this checkout, never a new worktree, skipped by its precheck when there
#     is nothing to do: stablyai/orca@a162e08b29b2883b02d8a0dfcc99e26c80b2cfe7:
#     docs/site/content/docs/cli/automations.mdx. It removes merged work with `orca worktree rm
#     --delete-branch`, the last step of Orca's own lifecycle (docs/site/content/docs/model/worktrees.mdx).
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

git config fetch.prune true
git maintenance start

name="Lifecycle sweep"
if orca-ide automations list --json | jq -e --arg name "$name" '.result.automations[] | select(.name == $name)' > /dev/null; then
  echo "Orca automation \"$name\" is already set."
  exit 0
fi
orca-ide automations create --name "$name" --trigger daily --time 05:00 --timezone America/New_York \
  --provider codex --workspace "path:$PWD" \
  --precheck "bash $PWD/deploy/wsl/lifecycle-precheck.sh" --precheck-timeout 120 \
  --prompt "$(cat deploy/wsl/lifecycle-prompt.md)" --json > /dev/null
echo "Orca automation \"$name\" set: daily at 05:00 New York time, in this checkout."
