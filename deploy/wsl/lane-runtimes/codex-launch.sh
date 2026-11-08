#!/usr/bin/env bash
# sextant-codex: Codex CLI 0.167.0 on OmniRoute's sextant-gpt pool, on the Responses wire, at max.
# The shape is OmniRoute's own Codex launcher, cheaper-inference/OmniRoute@191dce8d534ceb56c28a08e71381284a9a87838f
# bin/cli/commands/launch-codex.mjs: buildCodexProviderArgs's -c provider block, buildCodexEnv with
# --inherit-env, and a child whose signals are passed on; the key comes in as api-launch.sh's does.
# Config keys: openai/codex@rust-v0.167.0 086ccc833bc9cf01024ad2dd6af7dbd421b6bf9a. Rows: docs/manifest.md.
# Installed once, linked as sextant-codex (writers) and sextant-codex-review (reviewers), for Orca
# and native workers. Never as `codex`: AO 0.14.10 reconciles its Codex accounts by running the
# codex it resolves, so that one must stay AO's own (#258).
set -euo pipefail
set +x
prefix=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
case "$(basename "$0")" in
  sextant-codex) sandbox=workspace-write ;;
  sextant-codex-review) sandbox=read-only ;;
  *) echo 'sextant-codex: unsupported identity' >&2; exit 2 ;;
esac
# The pinned CLI deploy/wsl/setup.sh installs from .devcontainer/agents, by path, never by PATH.
codex="$HOME/.local/share/sextant-agents/node_modules/.bin/codex"

# A lane home of its own: never ~/.codex or an Orca account home, where Codex's ChatGPT logins
# live (Orca docs/site/content/docs/agents/codex.mdx). Orca marks its pane's home ORCA_CODEX_HOME.
home="$prefix/codex-home"
case "$(readlink -m "$home")/" in
  "$(readlink -m "$HOME/.codex")"/* | "$(readlink -m "$HOME/.config/orca")"/* | \
    "$(readlink -m "$HOME/.local/share/orca")"/*)
    echo 'sextant-codex: the lane CODEX_HOME resolves into a Codex login home; refusing' >&2
    exit 3
    ;;
esac
mkdir -p "$home"
chmod 700 "$home" # it keeps each session's transcript
export CODEX_HOME="$home"
unset ORCA_CODEX_HOME OMNIROUTE_API_KEY CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_AUTH_TOKEN
# launch-codex.mjs STRIPPED_CODEX_ENV_KEYS: no stale OpenAI key or base URL shadows the router.
unset OPENAI_API_KEY OPENAI_BASE_URL OPENAI_API_BASE OPENAI_ORG_ID OPENAI_ORGANIZATION CODEX_API_KEY

# Probes need no credential and make no call to attest (api-launch.sh's version probe): version and
# help, and Codex's subcommands that manage it rather than run a session (codex-rs/cli/src/main.rs:145-245).
offline=0
case "${1:-}" in login | logout | features | completion | doctor | debug) offline=1 ;; esac
for arg in "$@"; do
  [[ "$arg" == -- ]] && break
  [[ "$arg" =~ ^(--version|-V|--help|-h)$ ]] && offline=1
done
if ((offline)); then exec "$codex" "$@"; fi

# A caller's own sandbox choice stands, as a subcommand's beats the root's in Codex
# (codex-rs/utils/cli/src/shared_options.rs:95-145); otherwise this name's default applies.
chosen=0 previous=
for arg in "$@"; do
  [[ "$arg" == -- ]] && break
  case "$arg" in
    -s | -s?* | --sandbox | --sandbox=* | --dangerously-bypass-approvals-and-sandbox | --yolo | \
      --approve-for-me | --not-so-yolo | --config=sandbox_mode=*) chosen=1 ;;
    sandbox_mode=*) [[ "$previous" == -c || "$previous" == --config ]] && chosen=1 ;;
  esac
  previous=$arg
done

# Orca trusts worktrees only in the homes it selects; trust the launch folder for this run alone,
# as AO's Codex launch does (backend/pkg/agentruntime/command.go:362-376, CodexWorkspaceTrustArgs).
logical=$PWD physical=$(pwd -P)
projects="'$logical'={trust_level=\"trusted\"}"
[[ "$physical" == "$logical" ]] || projects+=",'$physical'={trust_level=\"trusted\"}"
case "$logical$physical" in *"'"* | *[[:cntrl:]]*) projects= ;; esac

IFS= read -r repository < "$prefix/repository-path"
base_url=$(jq -er .base_url "$prefix/routing.json")
pool=$(jq -er .combo "$prefix/routing.json")
effort=$(jq -er .gpt.effort "$prefix/model-policy.json")
# OmniRoute records this header as the call's client session, so the receipt finds this run only.
run=$(< /proc/sys/kernel/random/uuid)
args=(
  -c 'model_provider="omniroute"'
  -c 'model_providers.omniroute.name="OmniRoute"'
  -c "model_providers.omniroute.base_url=\"$base_url\""
  -c 'model_providers.omniroute.env_key="OMNIROUTE_API_KEY"'
  -c 'model_providers.omniroute.wire_api="responses"'
  -c 'model_providers.omniroute.requires_openai_auth=false'
  -c "model_providers.omniroute.http_headers.session_id=\"$run\""
  -c "model=\"$pool\""
  -c "model_reasoning_effort=\"$effort\""
  -c 'check_for_update_on_startup=false'
)
[[ -z "$projects" ]] || args+=(-c "projects={$projects}")
((chosen)) || args+=(-s "$sandbox")

# A child rather than exec, so the receipt can follow it. The terminal's own Ctrl-C reaches Codex
# directly; a TERM or HUP sent to this launcher is passed on, as launch-codex.mjs does. Bash makes
# a background child ignore INT and QUIT, so the child resets them before Codex starts.
trap ':' INT
(
  trap - INT QUIT
  # The same strict hop carries the lane MCP set's Context7 and Exa keys: the lane home's config.toml
  # (parity.py) names them by bearer_token_env_var and env_http_headers, as antigravity-launch.sh does.
  exec "$repository/scripts/with-keys.sh" --strict -k OMNIROUTE_KEY_CODEX:OMNIROUTE_API_KEY \
    -k CONTEXT7_API_KEY -k EXA_API_KEY -- \
    "$codex" "${args[@]}" "$@"
) <&0 &
child=$!
trap 'kill -TERM "$child" 2> /dev/null || true' TERM
trap 'kill -HUP "$child" 2> /dev/null || true' HUP
status=0
wait "$child" || status=$?
while kill -0 "$child" 2> /dev/null; do
  status=0
  wait "$child" || status=$?
done
trap - INT TERM HUP
python3 -I "$repository/scripts/omni_receipt.py" "$run" --write "$prefix/codex-receipts/$run.json" ||
  true
exit "$status"
