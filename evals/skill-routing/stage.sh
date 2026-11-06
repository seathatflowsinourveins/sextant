#!/usr/bin/env bash
# Official plugin-evals/creation layout, read 2026-11-06. Only stages public code/cases.
# Actual model runs use `claude plugin eval` directly; see README.md.
set -Eeuo pipefail
root=$(git -C "${BASH_SOURCE[0]%/*}" rev-parse --show-toplevel)
destination=${1:?usage: stage.sh NEW_DIRECTORY}
mkdir -m 700 "$destination"
mkdir -p "$destination/trading/.claude-plugin" "$destination/trading/skills"
printf '%s\n' '{"name":"sextant-trading-shelf"}' > "$destination/trading/.claude-plugin/plugin.json"
# Exactly the committed shelf bytes: no ignored files or project/private settings.
git -C "$root" archive HEAD:.claude/skills | tar -x -C "$destination/trading/skills"
plugin=$(claude plugin list --json | jq -r \
  '[.[] | select(.id == "compound-engineering@compound-engineering-plugin")] | .[0].installPath')
expected=$(jq -r '.plugins["compound-engineering@compound-engineering-plugin"].ref // empty' \
  "$root/.claude/shelf.lock.json")
[[ -d "$plugin" && "$expected" == compound-engineering-v3.36.0 ]]
[[ $(jq -r .version "$plugin/.claude-plugin/plugin.json") == 3.36.0 ]]
cp -R "$plugin" "$destination/compound"
for target in trading compound; do
  mkdir -p "$destination/$target/evals"
  cp -R "$root/evals/skill-routing/cases/$target/." "$destination/$target/evals/"
done
git -C "$root" rev-parse HEAD > "$destination/source-sha.txt"
claude --version > "$destination/claude-version.txt"
cp "$root/.claude/shelf.lock.json" "$destination/shelf.lock.json"
echo "$destination"
