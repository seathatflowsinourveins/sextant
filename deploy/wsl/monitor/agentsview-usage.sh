#!/usr/bin/env bash
# The L1/L2 usage query: daily totals as JSON from the committed archive, with no
# source refresh and no pricing fetch (--offline, --no-sync and --json are upstream
# flags, docs/token-usage.md:756-769). Read-only, at the lowest scheduling priority,
# through the wrapper so its telemetry and update switches apply.
set -euo pipefail
set +x
prefix=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
exec nice -n 19 ionice -c 3 "$prefix/agentsview.sh" usage daily --offline --no-sync --json "$@"
