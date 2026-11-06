#!/usr/bin/env bash
# Google CLI troubleshooting, read 2026-11-06: keep reviewed release pins from self-updating.
set -euo pipefail
export AGY_CLI_DISABLE_AUTO_UPDATE=true
prefix=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
case "${1:-}" in
  --version|--help|models) exec "$prefix/bin/antigravity/antigravity" "$@" ;;
esac
model=$(jq -r '.google.antigravity' "$prefix/model-policy.json")
exec "$prefix/bin/antigravity/antigravity" --model "$model" --effort high "$@"
