#!/usr/bin/env bash
# The verified reflection's precheck. Orca runs the reflection only when this exits 0
# (stablyai/orca@a162e08b29b2883b02d8a0dfcc99e26c80b2cfe7:docs/site/content/docs/cli/automations.mdx),
# and #91 asks for a run only when a session ended or a PR merged since the last one.
#   - A Claude session ended: its transcript, `projects/<project>/<session>.jsonl`, changed since the last
#     pass, and `sessions/` no longer holds the file Claude Code keeps "per running session" and removes
#     "when its session exits" (code.claude.com/docs/en/claude-directory, Application data, read 2026-11-06).
#     A transcript whose first prompt opens with the reflection prompt's marker is a reflection run, so a
#     reflection never schedules the next. Codex and dsh keep no such running-session record; their
#     work counts once its PR merges.
#   - A PR merged: `gh pr list --state merged` with GitHub's `merged:>=` search qualifier.
set -uo pipefail
claude_home=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
state=${XDG_STATE_HOME:-$HOME/.local/state}/sextant
stamp=$state/reflection-precheck
marker="sextant-verified-reflection"
start=$(date +%s.%N)

mkdir -p "$state" || exit 1
# The first pass looks back one day; the prompt's own seven-day read covers anything older.
[ -f "$stamp" ] || touch -d "@$(( ${start%.*} - 86400 ))" "$stamp" || exit 1
since=$(date -u -d "@$(stat -c %Y "$stamp")" +%Y-%m-%dT%H:%M:%SZ)

pass() {
  touch -d "@$start" "$stamp"
  exit 0
}

running=$(cat "$claude_home"/sessions/*.json 2>/dev/null | jq -r '.sessionId // empty' 2>/dev/null)
while IFS= read -r -d '' transcript; do
  id=$(basename "$transcript" .jsonl)
  grep -qxF "$id" <<< "$running" && continue
  first=$(jq -r 'select(.type == "user") | .message.content
    | if type == "string" then . else (map(.text? // "") | join(" ")) end' "$transcript" 2>/dev/null | head -n 1)
  [[ "$first" == "$marker"* ]] && continue
  pass
done < <(find "$claude_home/projects" -mindepth 2 -maxdepth 2 -name '*.jsonl' -newer "$stamp" -print0 2>/dev/null)

merged=$(gh pr list --state merged --search "merged:>=$since" --limit 1 --json number --jq length) || exit 1
[ "${merged:-0}" -gt 0 ] && pass
exit 1
