#!/usr/bin/env bash
# Installs the Claude shelf that .claude/settings.json declares, in this checkout. Safe to run again.
# A plugin only the tracked project file enables is never fetched; an untracked settings.local.json that
# enables it is (code.claude.com/docs/en/plugins/loading, read 2026-11-06). So: each marketplace at user
# scope, which the tracked pin outranks, and each enabled plugin at local scope
# (code.claude.com/docs/en/plugins/cli-reference and /settings-reference, read 2026-11-06).
# OMC stays off here: `just omc` is its switch.
# Always from the main checkout, which git lists first (git-worktree(1), list): from an Orca worktree, the
# user-scope directory marketplace and each install's recorded path would follow it and break once it goes.
# A worktree shares the main checkout's settings.local.json, measured 2026-11-06 with Claude Code 2.1.318.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
cd "$(git worktree list --porcelain | sed -n '1s/^worktree //p')"

settings=.claude/settings.json
mapfile -t sources < <(jq -r '.extraKnownMarketplaces[].source
  | if .source == "github" then "\(.repo)#\(.ref)" else .path end' "$settings")
mapfile -t plugins < <(jq -r '.enabledPlugins | to_entries[] | select(.value == true) | .key' "$settings")

for source in "${sources[@]}"; do
  claude plugin marketplace add "$source" --scope user
done
for plugin in "${plugins[@]}"; do
  claude plugin install "$plugin" --scope local
done
