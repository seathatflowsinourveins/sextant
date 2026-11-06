#!/usr/bin/env bash
# Native CLI launch shape carried from northstar@b384d298d217d3f8d9aa83356994629536a34795:
# scripts/ns-native.sh (with-keys -> exec); bypasses are each runtime's documented flags.
# Installed once, with runtime-named symlinks. Profiles use OmniRoute; no srt.
set -euo pipefail
set +x
unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_AUTH_TOKEN
prefix=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
runtime=$(basename "$0")
case "$runtime" in
  pi)
    key=OMNIROUTE_KEY_PI
    export PI_CODING_AGENT_DIR="$prefix/profiles/pi"
    command=("$prefix/node_modules/.bin/pi" --provider omniroute --model sextant-gpt)
    ;;
  omp)
    key=OMNIROUTE_KEY_OMP
    export PI_CODING_AGENT_DIR="$prefix/profiles/omp" PI_CONFIG_FILES="$prefix/profiles/omp/config.yml"
    command=("$prefix/bin/omp" --model omniroute/sextant-gpt --yolo)
    ;;
  opencode|opencode2)
    key=OMNIROUTE_KEY_OPENCODE
    export OPENCODE_DISABLE_AUTOUPDATE=1
    export OPENCODE_CONFIG_CONTENT="$(cat "$prefix/profiles/opencode.json")"
    if [[ "${1:-}" == run ]]; then
      shift
      command=("$prefix/node_modules/.bin/$runtime" run --standalone --auto)
    else
      command=("$prefix/node_modules/.bin/$runtime" --standalone --auto)
    fi
    ;;
  hermes)
    key=OMNIROUTE_KEY_HERMES
    export HERMES_HOME="$prefix/hermes-home"
    export HERMES_MANAGED_DIR="$prefix/profiles/hermes"
    export CUSTOM_BASE_URL=http://127.0.0.1:22128/v1 OPENAI_BASE_URL=http://127.0.0.1:22128/v1
    command=("$prefix/hermes-source/.hermes/bin/hermes" --provider custom --model sextant-gpt --yolo)
    ;;
  openhands-sdk)
    key=OMNIROUTE_KEY_OPENHANDS
    command=("$prefix/openhands/bin/python" "$prefix/openhands-lane.py")
    ;;
  *) echo 'lane-runtime: unsupported identity' >&2; exit 2 ;;
esac
# Version probes do not require a credential. Normal launches get only Sextant's router key.
if [[ $# == 1 && "$1" == --version ]]; then exec "${command[@]}" "$@"; fi
IFS= read -r repository < "$prefix/repository-path"
exec "$repository/scripts/with-keys.sh" --strict -k "$key:OMNIROUTE_API_KEY" -- "${command[@]}" "$@"
