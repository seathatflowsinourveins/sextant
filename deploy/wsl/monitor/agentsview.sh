#!/usr/bin/env bash
# AgentsView v0.46.1 with every egress switch off, at the pin in agentsview-pins.json.
# Opt-outs are upstream's own: AGENTSVIEW_TELEMETRY_ENABLED / DO_NOT_TRACK
# (internal/telemetry/telemetry.go:16,54-55; docs/configuration.md:2382),
# AGENTSVIEW_DISABLE_UPDATE_CHECK (docs/configuration.md:2395) and
# AGENTSVIEW_NO_DAEMON (docs/configuration.md:46-47), so no invocation starts a
# background process or leaves this host. The archive keeps usage values only
# (docs/configuration.md:69,80-85); prompt and response logging stays unset.
set -euo pipefail
set +x
export AGENTSVIEW_TELEMETRY_ENABLED=0
export DO_NOT_TRACK=1
export AGENTSVIEW_DISABLE_UPDATE_CHECK=1
export AGENTSVIEW_NO_DAEMON=1
export AGENTSVIEW_ARCHIVE_CONTENT=usage
export AGENTSVIEW_DATA_DIR="${AGENTSVIEW_DATA_DIR:-$HOME/.local/share/sextant/monitor/agentsview-data}"
unset OTEL_LOG_USER_PROMPTS OTEL_LOG_ASSISTANT_RESPONSES OTEL_LOG_RAW_API_BODIES OTEL_LOG_TOOL_CONTENT
prefix=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
version=$(jq -r .agentsview.version "$prefix/agentsview-pins.json")
real="$prefix/agentsview-$version/agentsview"
if [[ ! -x "$real" ]]; then
  echo "agentsview: pinned binary missing at $real; run install-agentsview.sh from main" >&2
  exit 3
fi
exec "$real" "$@"
