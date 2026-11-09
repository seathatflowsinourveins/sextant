#!/usr/bin/env bash
# Installs the hard-line rules into the user layer of each runtime whose project layer does not reach
# every session. Safe to run again; run it from the main checkout. Claude Code needs no step: its
# project deny rules apply in every mode and before workspace trust (code.claude.com/docs/en/permissions.md,
# read 2026-11-08).
# - Codex: a regular-file copy of .codex/rules/default.rules, as ~/.codex/rules/sextant-hard-lines.rules.
#   Codex reads each regular *.rules file in each layer's rules/, skips an untrusted project's, and appends
#   its own approvals to default.rules (openai/codex@rust-v0.167.0 086ccc83: codex-rs/core/src/
#   exec_policy.rs:490-504, :688-712, :904-906, :1177-1213). Orca copies each regular .rules file from
#   ~/.codex/rules into the Codex homes it manages at launch (stablyai/orca@v1.4.251 a162e08b:
#   src/main/codex/configuration/homes/codex-managed-home-rules.ts, codex-home-paths.ts:88-95).
# - Antigravity: antigravity.json's deny rules joined to settings.json's own, every other key kept, 0600 as
#   the CLI writes it (antigravity.google/docs/settings.md "How the CLI reads and saves", read 2026-11-08).
# - dsh: config/dsh/hard-lines linked into the acp, headless and dsh-tui profiles with dsh's own
#   `dsh plugin --profile <name> add`, from the main checkout, as setup.sh links the research bundle.
#   The sandbox lock's dsh runs it directly: ~/.local/bin/dsh would inject a key it does not need.
set -Eeuo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/../../.." && pwd)
main=$(git -C "$repo" worktree list --porcelain | sed -n '1s/^worktree //p')
dsh=${DSH_BIN:-$HOME/.local/share/sextant-agents/node_modules/.bin/dsh}
export PATH="$HOME/.local/share/sextant-host-tools/node_modules/.bin:$PATH"
temp=()
trap 'rm -f -- "${temp[@]}"' EXIT

rules="$HOME/.codex/rules"
mkdir -p "$rules"
temp+=("$(mktemp "$rules/.sextant-hard-lines.XXXXXX")")
install -m 644 "$repo/.codex/rules/default.rules" "${temp[-1]}"
mv -f -- "${temp[-1]}" "$rules/sextant-hard-lines.rules"

settings="$HOME/.gemini/antigravity-cli/settings.json"
mkdir -p "$(dirname "$settings")"
temp+=("$(mktemp "$settings.XXXXXX")")
if [[ -s "$settings" ]]; then cat -- "$settings"; else echo '{}'; fi |
  jq --slurpfile ours "$here/antigravity.json" \
    '.permissions.deny = ((.permissions.deny // []) + ($ours[0].permissions.deny - (.permissions.deny // [])))' \
    > "${temp[-1]}"
chmod 600 "${temp[-1]}"
mv -f -- "${temp[-1]}" "$settings"

[[ -x "$dsh" ]] || { echo "dsh not found at $dsh; set DSH_BIN to the sandbox lock's dsh" >&2; exit 1; }
for profile in acp headless dsh-tui; do
  "$dsh" plugin --profile "$profile" add "$main/config/dsh/hard-lines"
done
echo "Hard-line rules installed for Codex, Antigravity and dsh. Restart running sessions to load them."
