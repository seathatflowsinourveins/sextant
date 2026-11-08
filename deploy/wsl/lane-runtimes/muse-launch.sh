#!/usr/bin/env bash
# Muse Code lane launch: Muse Wonder Full at max with contributor mode off (model-policy.json meta, pins.json muse).
# Every flag is the 1.4.6-R6000.1 build's own: `muse --help` root --model, --reasoning-effort and --contributor-mode
# for the TUI, a prompt and resume ("Root options ... may appear on either side of `resume`"); `muse exec --help`
# takes its own copies after the subcommand; `muse serve --help` takes --model and --contributor-mode, its effort
# being chosen on the wire. Contributor mode is "this run only; never persisted", so every session launch sets it.
set -euo pipefail
set +x
prefix=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
real="$HOME/.local/share/muse-code/muse-$(jq -r .muse.version "$prefix/pins.json")"
model=$(jq -r .meta.model "$prefix/model-policy.json")
effort=$(jq -r .meta.effort "$prefix/model-policy.json")
refuse() {
  echo 'muse-launch: contributor mode and -contributor models may use session content for product improvement; refused' >&2
  exit 2
}
caller_model=0 caller_effort=0 caller_contributor=0 previous=
for arg in "$@"; do
  [[ "$arg" == -- ]] && break # the rest is literal prompt text
  case "$arg" in
    --contributor-mode=on | --model=*-contributor*) refuse ;;
    --contributor-mode=*) caller_contributor=1 ;;
    --model=*) caller_model=1 ;;
    --reasoning-effort=* | --effort=*) caller_effort=1 ;;
  esac
  case "$previous" in
    --contributor-mode)
      if [[ "$arg" == on ]]; then refuse; fi
      caller_contributor=1
      ;;
    --model)
      if [[ "$arg" == *-contributor* ]]; then refuse; fi
      caller_model=1
      ;;
    --reasoning-effort | --effort) caller_effort=1 ;;
  esac
  previous=$arg
done
# The reminder roster's agents run below max (skill-reminder low, goal- and verify-reminder high, in every session
# log), and no documented setting pins them: run.reminder_roster refuses an agents list, and an effort-only roster
# empties it. Each turns off per run through its runtime capability, the key path the bundled manage-settings skill
# names (`runtime_capabilities["plugin:tbh-reminders:reminder:skill-reminder"].enabled`); ADR-0030 keeps no model
# surface below max.
quiet=()
for reminder in skill-reminder goal-reminder verify-reminder; do
  quiet+=(-c "runtime_capabilities.plugin:tbh-reminders:reminder:$reminder.enabled=false")
done
pins=()
((caller_model)) || pins+=(--model "$model")
((caller_effort)) || pins+=(--reasoning-effort "$effort")
((caller_contributor)) || pins+=(--contributor-mode off)
case "${1:-}" in
  -V | --version | -h | --help | help | config | export | trace | model-profile | skills | voice | plugins | \
    sandbox | schema | session-message | mcp | auth | login | logout | init)
    exec "$real" "$@"
    ;;
  exec)
    shift
    exec "$real" exec "${pins[@]}" "${quiet[@]}" "$@"
    ;;
  serve)
    shift
    serve=()
    ((caller_model)) || serve+=(--model "$model")
    ((caller_contributor)) || serve+=(--contributor-mode off)
    exec "$real" serve "${serve[@]}" "${quiet[@]}" "$@"
    ;;
  *) exec "$real" "${pins[@]}" "${quiet[@]}" "$@" ;;
esac
