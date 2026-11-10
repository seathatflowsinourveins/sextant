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
# The main checkout, which git lists first (git-worktree(1)), so the sweep never points at a worktree it removes.
cd "$(git worktree list --porcelain | sed -n '1s/^worktree //p')"

git config fetch.prune true
git maintenance start

name="Lifecycle sweep"
# An existing sweep takes this checkout's repository, current prompt and precheck, by Orca's own
# `automations edit` (same pin, src/cli/specs/automations.ts), so a merged change to either, or a moved
# checkout, reaches the scheduled run. Omitting the workspace mode keeps the stored one, so it still
# runs in place and never creates a worktree of its own.
id=$(orca-ide automations list --json | jq -r --arg name "$name" '.result.automations[] | select(.name == $name) | .id' | head -n 1)
if [ -n "$id" ]; then
  orca-ide automations edit "$id" --repo "path:$PWD" \
    --precheck "bash $PWD/deploy/wsl/lifecycle-precheck.sh" --precheck-timeout 120 \
    --prompt "$(cat deploy/wsl/lifecycle-prompt.md)" --json > /dev/null
  echo "Orca automation \"$name\" is set, with this checkout's repository, prompt and precheck."
  exit 0
fi
orca-ide automations create --name "$name" --trigger daily --time 05:00 --timezone America/New_York \
  --provider codex --workspace "path:$PWD" \
  --precheck "bash $PWD/deploy/wsl/lifecycle-precheck.sh" --precheck-timeout 120 \
  --prompt "$(cat deploy/wsl/lifecycle-prompt.md)" --json > /dev/null
echo "Orca automation \"$name\" set: daily at 05:00 New York time, in this checkout."
