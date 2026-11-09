#!/usr/bin/env bash
# AO (OrchestratorInc/agent-orchestrator) runs one job here: a lane PR's fix-CI and answer-review loop,
# after its lane worker has handed the PR off. Orca stays the cockpit and the only lane dispatcher.
# Sources, all OrchestratorInc/agent-orchestrator@v0.14.10 033d597032e448a0ea16c298350e36b099f74106:
#   - install: scripts/setup-self-hosted.sh --install-only, AO's own path for "another service manager".
#     It downloads the latest stable release and checks its published sha256; we refuse any but the pin.
#   - daemon: docs/cli/README.md, `ao daemon` under a service manager (here, an Orca tab) and AO_PORT.
#     Its default port, 3001, is taken in the namespace the old lanes share.
#   - claim: docs/cli/README.md and docs/scm-observer.md, `ao spawn --claim-pr`, AO's own PR ownership,
#     with --no-takeover so a second owner is refused. The lifecycle manager then sends that session
#     each failed check and review comment (backend/internal/lifecycle/reactions.go). It never merges.
#   - harness ids: backend/internal/adapters/agent/deepseekharness/deepseekharness.go:59 defines
#     deepseek-harness, resolving dsh (:228-246) and launching its headless profile (:144);
#     backend/internal/adapters/agent/codex/codex.go:95 defines codex.
#     backend/internal/cli/spawn.go:224 aliases --agent to --harness: one harness per spawn.
#     claim stays Codex; select DeepSeek only with an explicit ao spawn --harness deepseek-harness.
# usage: ao.sh install | daemon | project | credential | claim <pr-number>
set -Eeuo pipefail

pin_version=0.14.10
pin_commit=033d597032e448a0ea16c298350e36b099f74106
port=3301
project=sextant
clone="$HOME/.ao/repos/sextant-next"
repo_url=https://github.com/seathatflowsinourveins/sextant-next
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

install() {
  local setup
  setup=$(mktemp "${TMPDIR:-/tmp}/ao-setup.XXXXXX")
  trap 'rm -f "$setup"' RETURN
  curl -fsSL "https://raw.githubusercontent.com/OrchestratorInc/agent-orchestrator/$pin_commit/scripts/setup-self-hosted.sh" -o "$setup"
  AO_PORT=$port bash "$setup" --install-only
  check_pin
}

check_pin() {
  local have
  have=$(ao version)
  [[ "$have" == "$pin_version commit ${pin_commit:0:12} "* ]] || {
    echo "AO is '$have', not the pin $pin_version ${pin_commit:0:12}. Move the pin by PR first." >&2
    exit 1
  }
}

daemon() {
  check_pin
  # Daemons started directly send no remote telemetry by default (docs/telemetry.md); this makes it explicit.
  AO_PORT=$port AO_TELEMETRY_REMOTE=off exec ao daemon
}

# AO works in its own clone, so its worktrees never hold a branch an Orca worktree has checked out.
project() {
  [[ -d "$clone/.git" ]] || git clone -q "$repo_url" "$clone"
  credential
  if ! ao project get "$project" > /dev/null 2>&1; then
    ao project add --path "$clone" --id "$project" --name "Sextant (AO fix-CI/review)" --worker-agent codex
  fi
}

# AO's sessions outlive the App's one-hour installation token, which each inherits at spawn. So git in
# AO's clone, which every AO worktree shares, asks bin/gh, and bin/gh mints a fresh token per call. The
# empty helper first resets the user's global helper list (git/git@v2.56.0
# a018953688f1b10bddf91bff8747068f5f4746a4:Documentation/gitcredentials.adoc:199-201).
credential() {
  git -C "$clone" config --local --replace-all credential.https://github.com.helper ''
  git -C "$clone" config --local --add credential.https://github.com.helper "!$here/github-app/bin/gh auth git-credential"
}

claim() {
  local pr=${1:?usage: ao.sh claim <pr-number>} view head sha
  [[ "$pr" =~ ^[0-9]+$ ]] || { echo "PR must be a number." >&2; exit 2; }
  view=$(gh pr view "$pr" --repo "$repo_url" --json state,isDraft,baseRefName,headRefName,headRefOid,autoMergeRequest,statusCheckRollup,body)
  # One writer per branch: AO takes a PR only once its worker has handed it off, open, landing by squash
  # auto-merge on main, and with `ci` settled green or red.
  jq -e '.state == "OPEN" and (.isDraft | not) and .baseRefName == "main"
    and .autoMergeRequest.mergeMethod == "SQUASH"
    and ([.statusCheckRollup[] | select(.name == "ci" and .status == "COMPLETED")] | length > 0)' <<< "$view" > /dev/null || {
    echo "PR #$pr is not handed off: it must be open, not a draft, on main, set to squash auto-merge, with ci settled." >&2
    exit 1
  }
  # Match the workflows' case-insensitive, whole-body contains, including comments.
  jq -e '(.body // "" | ascii_downcase | contains("review-family codex")) | not' <<< "$view" > /dev/null || {
    echo "PR #$pr requests a Codex reviewer; AO's Codex worker cannot claim it. Set another reviewer before hand-off." >&2
    exit 1
  }
  head=$(jq -r .headRefName <<< "$view")
  sha=$(jq -r .headRefOid <<< "$view")
  # Codex's interface is named as well as its agent, so AO's daemon default, which a setting changes
  # (backend/internal/storage/sqlite/migrations/0105_default_session_mode_chat.sql), never picks it.
  # Codex keeps chat, its own app-server (backend/internal/adapters/chatdriver/registry/registry.go:76).
  # A Claude worker would name tui, the claude CLI itself (backend/internal/domain/sessionmode.go:11-13),
  # never chat: AO's chat runs Claude Code through claude-agent-acp, the Agent SDK in AO's runtime, with
  # the owner's Claude sign-in (registry.go:76-77; the lead, 2026-11-08).
  ao spawn --project "$project" --agent codex --mode chat --branch "$head" --claim-pr "$pr" --no-takeover \
    --name "PR #$pr fix-CI/review" --prompt "$(prompt "$pr" "$head" "$sha")"
}

prompt() {
  cat << EOF
You own PR #$1 (branch $2) for one job: its fix-CI and answer-review loop. Its lane worker has handed it off.
First make your worktree the PR head: git fetch origin $2 && git checkout -B $2 origin/$2, and check that
git rev-parse HEAD is $3. Then wait for AO's messages. For a failed check, reproduce it with just ci and push
a fix to $2 with plain git push, its upstream; the Codex rules forbid an explicit push to origin. For a
review comment, fix it or answer it on the PR with your reason. Follow AGENTS.md: every change keeps the
PR's Upstream references and manifest row true.
Never alter the PR body's Agent-Family or Review-Family markers.
Never merge (no ao pr merge, no gh pr merge), never disable auto-merge, never force-push, and never edit
.github/ or dangerfile.js. A PR lands only by squash auto-merge once ci, source and review pass.
If a fix needs a new source or the owner's decision, stop and say so with ao report --needs-input.
EOF
}

case "${1:-}" in
  install) install ;;
  daemon) daemon ;;
  project) project ;;
  credential) credential ;;
  claim) claim "${2:-}" ;;
  *)
    echo "usage: ao.sh install | daemon | project | credential | claim <pr-number>" >&2
    exit 2
    ;;
esac
