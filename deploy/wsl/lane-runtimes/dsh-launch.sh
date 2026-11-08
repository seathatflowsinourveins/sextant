#!/usr/bin/env bash
# dsh with-keys wrapper (the lead's ruling, 2026-11-07, option (i)), carried from northstar@b384d298d217d3f8d9aa83356994629536a34795
# scripts/ns-native.sh: with-keys -> exec, as api-launch.sh does. One strict hop injects the DeepSeek key and the two
# keys the lane MCP set's Context7 and Exa headers read (config/dsh/mcp), into this one process; there is no key file.
# with-keys exports into the current environment and execs (scripts/key-systemd.sh ns_systemd_inject), so a caller's
# keys survive a nested call. dsh-tui's locator (cli/adapters/dsh/locate.mjs) takes the first quoted, $-free .js path
# below and resolves it beside this file, so locator launches keep their direct backend. Linked as sextant-dsh, the
# name every Sextant launch (headless legs, scripts) calls, and as dsh for AO 0.14.10's deepseek-harness adapter
# (backend/internal/adapters/agent/deepseekharness/deepseekharness.go:228-246 resolves only "dsh"), whose
# `dsh --profile acp` and dsh-tui's `dsh --version` probe reach it through ~/.local/bin coming first on PATH.
set -euo pipefail
set +x
entry="../sextant-agents/node_modules/@deepseek-ai/dsh/lib/bin.js"
prefix=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
real=$(readlink -f "$prefix/$entry")
# Version probes do not require a credential.
if [[ $# == 1 && ("$1" == --version || "$1" == -v || "$1" == -V) ]]; then exec "$real" "$@"; fi
IFS= read -r repository < "$prefix/repository-path"
exec "$repository/scripts/with-keys.sh" --strict -k DEEPSEEK_API_KEY -k CONTEXT7_API_KEY -k EXA_API_KEY \
  -- "$real" "$@"
