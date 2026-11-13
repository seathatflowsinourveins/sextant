#!/usr/bin/env bash
# Google CLI troubleshooting, read 2026-11-06: keep reviewed release pins from self-updating.
# Sessions get Context7's and Exa's keys in one strict with-keys hop, for the pinned mcp-remote bridge their
# mcp_config.json entries run (parity.py; Antigravity 1.4.6 sends header placeholders literally). Version, help,
# model, MCP and plugin management stay keyless.
set -euo pipefail
set +x
export AGY_CLI_DISABLE_AUTO_UPDATE=true
prefix=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
case "${1:-}" in
  --version | --help | models | help | mcp | plugin | plugins) exec "$prefix/bin/antigravity/antigravity" "$@" ;;
esac
model=$(jq -r '.google.antigravity' "$prefix/model-policy.json")
IFS= read -r repository < "$prefix/repository-path"
exec "$repository/scripts/with-keys.sh" --strict -k CONTEXT7_API_KEY -k EXA_API_KEY \
  -- "$prefix/bin/antigravity/antigravity" --model "$model" --effort xhigh "$@"
