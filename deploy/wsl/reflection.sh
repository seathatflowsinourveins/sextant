#!/usr/bin/env bash
# Sets the verified reflection, #114's runner: an Orca automation in a fresh worktree per run, skipped by
# its precheck unless a session ended or a PR merged (stablyai/orca@a162e08b29b2883b02d8a0dfcc99e26c80b2cfe7:
# docs/site/content/docs/cli/automations.mdx). It proposes lessons in a PR body; the lead, the single
# writer under ADR-0018's amendment, appends them. Safe to run again. `just reflection` runs it.
# It never enables the automation: that is the lead's call, in Orca.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
# The main checkout, which git lists first (git-worktree(1)), so the precheck path outlives any worktree.
cd "$(git worktree list --porcelain | sed -n '1s/^worktree //p')"

name="Verified reflection"
precheck="bash $PWD/deploy/wsl/reflection-precheck.sh"
default_branch=$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name)
base_branch="origin/${default_branch}"
id=$(orca-ide automations list --json | jq -r --arg name "$name" '.result.automations[] | select(.name == $name) | .id' | head -n 1)
if [ -n "$id" ]; then
  orca-ide automations edit "$id" --precheck "$precheck" --precheck-timeout 120 \
    --repo "path:$PWD" --base-branch "$base_branch" \
    --prompt "$(cat deploy/wsl/reflection-prompt.md)" --json > /dev/null
  echo "Orca automation \"$name\" is set, with this checkout's prompt and precheck; its enabled state is unchanged."
  exit 0
fi
orca-ide automations create --name "$name" --trigger "26 3 * * *" --timezone UTC \
  --provider claude --extra-agent-args="--model claude-fable-5-2 --effort max" \
  --repo "path:$PWD" --workspace-mode new-per-run --base-branch "$base_branch" --setup skip \
  --precheck "$precheck" --precheck-timeout 120 --disabled \
  --prompt "$(cat deploy/wsl/reflection-prompt.md)" --json > /dev/null
echo "Orca automation \"$name\" set, disabled: daily at 03:26 UTC once the lead enables it."
