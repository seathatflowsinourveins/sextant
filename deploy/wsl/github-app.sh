#!/usr/bin/env bash
# The Sextant GitHub App gives AO and the lane tabs their own rate budget, apart from the owner's login,
# which the lead and the owner keep for their own posts. Tokens come from deploy/wsl/github-app/token.mjs
# (@octokit/auth-app, pinned) and live only in a child's environment. See docs/manifest.md and issue #103.
#   install                 npm ci of the pinned @octokit/auth-app, scripts off
#   ids                     App ID from the public GET /apps/{slug}; installation ID with the App's JWT
#   run -- CMD...           CMD once, with GH_TOKEN and AO_GITHUB_TOKEN set to a fresh installation token
#   daemon                  `ao.sh daemon` under the App, restarted on a new token before each expires,
#                           with bin/gh first on PATH so its long-lived sessions mint per gh call too
#   tab -- CMD...           a lane tab: `run`, with bin/gh first on PATH so every gh call gets a fresh token
set -Eeuo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/../.." && pwd)
app="$here/github-app"
config="$here/github-app.json"
key=SEXTANT_GITHUB_APP_KEY_B64

installed() {
  [[ -d "$app/node_modules/@octokit/auth-app" ]] || {
    echo "github-app: run \`just gh-app install\` first" >&2
    exit 1
  }
}

minted() {
  installed
  "$repo/scripts/with-keys.sh" --strict -k "$key" -- node "$app/token.mjs" "$@"
}

ids() {
  local slug app_id installation tmp
  slug=$(jq -r .app_slug "$config")
  app_id=$(gh api "/apps/$slug" --jq .id)
  installation=$(minted installation)
  [[ "$installation" =~ ^[0-9]+$ ]] || { echo "github-app: no installation ID" >&2; exit 1; }
  tmp=$(mktemp "$config.XXXXXX")
  jq --argjson a "$app_id" --argjson i "$installation" '.app_id = $a | .installation_id = $i' "$config" > "$tmp"
  mv "$tmp" "$config"
  jq . "$config"
}

case "${1:-}" in
  install) npm ci --prefix "$app" --ignore-scripts --no-audit --no-fund ;;
  ids) ids ;;
  run) shift; minted run "$@" ;;
  daemon) PATH="$app/bin:$PATH" minted supervise -- bash "$here/ao.sh" daemon ;;
  tab) shift; PATH="$app/bin:$PATH" minted run "$@" ;;
  *)
    sed -n '2,/^set -/{/^set -/!p;}' "$0" >&2
    exit 2
    ;;
esac
