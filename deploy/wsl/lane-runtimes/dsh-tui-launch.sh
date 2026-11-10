#!/usr/bin/env bash
# dsh-tui with-keys wrapper, so Orca's default `dsh-tui` launch gets its keys: dsh-launch.sh's pattern beside it (the lead's
# ruling 2026-11-07, option (i), carried from northstar@b384d298d217d3f8d9aa83356994629536a34795 scripts/ns-native.sh).
# One strict with-keys hop injects the DeepSeek key and the lane MCP set's Context7 and Exa keys into this one process;
# there is no key file. Linked as ~/.local/bin/dsh-tui (the lead's dsh-tui wrapper ruling, 2026-11-10).
# DSH_HOME defaults to ~/.dsh-full, the enhanced home every new non-B dsh launch uses (lead ruling 2026-11-08 21:58);
# a caller's DSH_HOME wins, so explicit launches are unchanged.
set -euo pipefail
set +x
# dsh-launch.sh's telemetry opt-out; dsh-tui 0.19.0 reads both (guide/dsh-tui-guide/configuration.en.md:86-89).
export DSH_TELEMETRY_DISABLED=1 DSH_TELEMETRY_MODE=DISABLED
export DSH_HOME="${DSH_HOME:-$HOME/.dsh-full}"
real="$DSH_HOME/profiles/dsh-tui/node_modules/@deepseek-harness-tui/dsh-tui/bin/dsh-tui.js"
prefix=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
# Version probes do not require a credential.
if [[ $# == 1 && ("$1" == --version || "$1" == -v || "$1" == -V) ]]; then exec "$real" "$@"; fi
IFS= read -r repository < "$prefix/repository-path"
exec "$repository/scripts/with-keys.sh" --strict -k DEEPSEEK_API_KEY -k CONTEXT7_API_KEY -k EXA_API_KEY \
  -- "$real" "$@"
