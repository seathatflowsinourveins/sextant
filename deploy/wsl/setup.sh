#!/usr/bin/env bash
# Loads the clean Sextant environment from this checkout, then starts its Orca. Safe to run again.
# Each tool comes from its upstream's documented installer, at the pin this repo already holds; Claude Code
# takes its official latest channel instead (ADR-0030).
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

dockerfile=.devcontainer/Dockerfile
agents="$HOME/.local/share/sextant-agents"
host_tools="$HOME/.local/share/sextant-host-tools"
qmd="$HOME/.local/share/sextant-qmd"
fnm_dir="$HOME/.fnm"
export PATH="$agents/node_modules/.bin:$host_tools/node_modules/.bin:$qmd/node_modules/.bin:$fnm_dir/aliases/default/bin:$fnm_dir:$HOME/.local/bin:$PATH"

# The login window is the one place nobody else can see, so progress and failures go where another
# session can read them and fix them on GitHub. Never the pairing step or a sign-in.
log=/mnt/wsl/sextant/first-login.log
sudo install -d -o sextant -g sextant /mnt/wsl/sextant
note() { printf '%s %s\n' "$(date '+%H:%M:%S %Z')" "$*" >> "$log"; }
trap 'note "stopped at line $LINENO: $BASH_COMMAND"' ERR
note "setup started at $(git rev-parse --short HEAD)"

install_tools() {

uv_version=$(sed -n 's|^FROM ghcr.io/astral-sh/uv:\([0-9.]*\)@.*|\1|p' "$dockerfile")
curl -LsSf "https://astral.sh/uv/$uv_version/install.sh" | sh

node_version=$(sed -n 's/^ARG NODE_VERSION=//p' "$dockerfile")
curl -fsSL https://fnm.vercel.app/install | bash -s -- --install-dir "$fnm_dir" --skip-shell
eval "$(fnm env)"
fnm install "$node_version"
fnm default "$node_version"

just_version=$(sed -n 's/^ARG JUST_VERSION=//p' "$dockerfile")
uv tool install --force "rust-just==$just_version"

# Claude Code floats on its latest channel on the host, which the installer also makes the updater's default
# (ADR-0030, 2026-11-09 amendment; code.claude.com/docs/en/setup, "Install a specific version", read
# 2026-11-09). The devcontainer image keeps its own pin.
curl -fsSL https://claude.ai/install.sh | bash -s latest

mkdir -p "$agents"
cp .devcontainer/agents/package.json .devcontainer/agents/package-lock.json "$agents/"
(cd "$agents" && npm ci --no-audit --no-fund)
mkdir -p "$qmd"
cp .devcontainer/qmd/package.json .devcontainer/qmd/package-lock.json "$qmd/"
(cd "$qmd" && npm ci --no-audit --no-fund)
# Every runtime's shell, not only this script's PATH, runs the lexical CLI the manifest names.
mkdir -p "$HOME/.local/bin"
ln -sfn "$qmd/node_modules/.bin/qmd" "$HOME/.local/bin/qmd"

# pnpm for dsh's profile installs and the Dev Containers CLI, in their own lock.
mkdir -p "$host_tools"
cp deploy/wsl/dsh/package.json deploy/wsl/dsh/package-lock.json "$host_tools/"
(cd "$host_tools" && npm ci --ignore-scripts --no-audit --no-fund)

# Docker alone cannot run the template: its documented self-install supplies devc.
devc_template="$HOME/.local/share/sextant-devcontainer"
template_repo=$(jq -r '.devcontainer_template.repository' deploy/wsl/host-tools.json)
template_pin=$(jq -r '.devcontainer_template.commit' deploy/wsl/host-tools.json)
[ -d "$devc_template/.git" ] || git clone --no-checkout "$template_repo" "$devc_template"
git -C "$devc_template" fetch --depth 1 origin "$template_pin"
git -C "$devc_template" checkout --detach "$template_pin"
bash "$devc_template/install.sh" self-install

# Rootless Docker, the user's own daemon (docs.docker.com/engine/security/rootless/, read 2026-11-06).
docker context inspect rootless > /dev/null 2>&1 || dockerd-rootless-setuptool.sh install
docker context use rootless > /dev/null

# dsh-tui's documented profile install, with the hook packages Orca's dsh row loads from each profile.
mapfile -t plugins < <(jq -r '.devDependencies | to_entries[] | .key + "@" + .value' config/dsh/package.json)
profile_dir="$HOME/.dsh/profiles/dsh-tui"
mkdir -p "$profile_dir"
[ -f "$profile_dir/pnpm-workspace.yaml" ] || cp deploy/wsl/dsh/pnpm-workspace.yaml "$profile_dir/"
dsh plugin --profile dsh-tui add --save-exact "${plugins[@]}" "$PWD/config/dsh"
# Orca's dsh agent runs this launcher; keep it on PATH without a local wrapper.
ln -sfn "$profile_dir/node_modules/@deepseek-harness-tui/dsh-tui/bin/dsh-tui.js" "$HOME/.local/bin/dsh-tui"

# Exactly the release checksums already reviewed in the sandbox Dockerfile.
tool_archive=$(mktemp)
arch_pins=$(sed -n '/^    amd64) /,/;;/p' "$dockerfile")
for tool in gitleaks actionlint; do
  case "$tool" in
    gitleaks) repo=gitleaks/gitleaks; key=gl; pin=GITLEAKS_VERSION ;;
    actionlint) repo=rhysd/actionlint; key=al; pin=ACTIONLINT_VERSION ;;
  esac
  version=$(sed -n "s/^ARG $pin=//p" "$dockerfile")
  arch=$(sed -n "s/.*${key}_arch=\\([^;]*\\);.*/\\1/p" <<< "$arch_pins")
  checksum=$(sed -n "s/.*${key}_sha=\\([a-f0-9]*\\).*/\\1/p" <<< "$arch_pins")
  curl -fsSL "https://github.com/$repo/releases/download/v$version/${tool}_${version}_${arch}.tar.gz" -o "$tool_archive"
  printf '%s  %s\n' "$checksum" "$tool_archive" | sha256sum -c -
  tar -xzf "$tool_archive" -C "$HOME/.local/bin" "$tool"
done
rm -f "$tool_archive"
git config core.hooksPath .githooks

# Disposable research retrieval: checksum-bound wheels, the pinned embedding model and image, a user service.
python_version=$(sed -n 's/^requires-python = ">=\([^,]*\),.*/\1/p' pyproject.toml)
pins=deploy/openviking/pins.json
uv tool install --python "$python_version" "$(jq -r '.openviking | .wheel + "#sha256=" + .sha256' "$pins")"
# The same full-SHA source the Claude shelf's .mcp.json runs; the tagged wheel resolves an incompatible mcp 2.
uv tool install --python "$python_version" "$(jq -r '."paper-search-mcp".source' "$pins")"
# Its CLI README: non-interactive shells need a saved display language (~/.openviking/ovcli.settings.conf).
ov language en
model_dir="$HOME/.local/share/sextant-openviking/models"
mkdir -p "$model_dir" "$HOME/.config/systemd/user"
model=$(jq -r '.embedding.file' "$pins")
model_sha=$(jq -r '.embedding.sha256' "$pins")
if ! printf '%s  %s\n' "$model_sha" "$model_dir/$model" | sha256sum --check --status; then
  model_url=$(jq -r '.embedding | "https://huggingface.co/" + .repository + "/resolve/" + .revision + "/" + .file' "$pins")
  curl -fL "$model_url" -o "$model_dir/$model.download"
  printf '%s  %s\n' "$model_sha" "$model_dir/$model.download" | sha256sum -c -
  mv "$model_dir/$model.download" "$model_dir/$model"
fi
docker compose -f deploy/openviking/compose.yaml up -d
bash deploy/openviking/install-units.sh
# An installed-but-failed service is not a completed setup.
embedding_url=$(jq -r '.embedding.dense.api_base' deploy/openviking/ov.conf)
curl -fsS --retry 30 --retry-all-errors --retry-delay 2 "${embedding_url%/v1}/health" -o /dev/null
retrieval_url=$(jq -r '.url' deploy/openviking/ovcli.conf)
curl -fsS --retry 30 --retry-all-errors --retry-delay 2 "$retrieval_url/health" | jq -e '.healthy == true' > /dev/null

uv sync --frozen
just index
}
install_tools 2>&1 | tee -a "$log"

# No prompt anywhere in this distro. Orca already launches every agent with its bypass flag
# (stablyai/orca@a162e08b29b2883b02d8a0dfcc99e26c80b2cfe7:docs/site/content/docs/agents/supported.mdx). These answer Claude's own
# dialog up front, for plain tabs and for Orca's managed accounts, whose settings live apart.
# Claude Code updates itself in the background on its latest channel, so a newly launched model runs at the
# next start (ADR-0030, 2026-11-09 amendment): remove the updater switch an earlier run wrote and name the
# channel. code.claude.com/docs/en/setup, "Update Claude Code", read 2026-11-09.
no_prompts() {
  mkdir -p "$1"
  [ -f "$1/settings.json" ] || echo '{}' > "$1/settings.json"
  jq '.permissions.defaultMode = "bypassPermissions" | .skipDangerousModePermissionPrompt = true
    | del(.env.DISABLE_AUTOUPDATER) | .autoUpdatesChannel = "latest"' \
    "$1/settings.json" > "$1/settings.json.new"
  mv "$1/settings.json.new" "$1/settings.json"
}
no_prompts "$HOME/.claude"

# Orca's server, by its own pairing flow: serve once in the foreground while the service is stopped, add
# it in the Orca app, then run it as Orca's own service, which never prints a pairing link
# (stablyai/orca@a162e08b29b2883b02d8a0dfcc99e26c80b2cfe7:src/cli/specs/serve.ts).
note "Orca server"
# This distro's own port: distros share one network, 6768 and 6769 belong to the old hosts, and mirrored
# networking also shares Windows' ports, which is why 6770 refused with no Linux listener on it.
port=6771
paired="$HOME/.config/orca/.sextant-paired"
if [ ! -e "$paired" ]; then
  systemctl --user disable --now orca-serve 2> /dev/null || true
  # Mirrored networking shows Windows' tailnet address here. Tailscale's range: tailscale.com/kb/1015.
  address=$(ip -4 -o addr | awk '{split($4, a, "/"); split(a[1], o, "."); if (o[1] == 100 && o[2] >= 64 && o[2] <= 127) {print a[1]; exit}}')
  echo "If your Orca app runs on this Windows PC, type 127.0.0.1. From another computer, Windows must admit"
  echo "port $port first: see docs/start.md."
  read -r -p "Address your Orca app reaches this PC on [${address:-none found}]: " typed
  address=${typed:-$address}
  echo "In the Orca app: Settings > Remote Orca Servers > Add Server, name it sextant, and paste the link printed below."
  echo "With 127.0.0.1, the app says the link points back to this device: tick \"I reach this address through"
  echo "an SSH tunnel\". WSL's localhost is the tunnel here, and Orca still checks the server before saving it."
  echo "When the app says connected, press Ctrl-C once here."
  # Ctrl-C stops the server, and without this trap it would stop this script too.
  trap ':' INT
  began=$SECONDS
  # The terminal host starts with this first server and outlives it, so it takes the limits now.
  mapfile -t limits < <(sed -n 's/^Environment=//p' deploy/wsl/orca-serve-limits.conf)
  env "${limits[@]}" PATH="$HOME/.local/bin:$PATH" orca-ide serve --port "$port" --pairing-address "$address" || true
  trap - INT
  # Ctrl-C ends this step whatever the exit code. A server that stops at once never printed a link.
  if ((SECONDS - began < 10)); then
    note "Orca server stopped at once on port $port"
    echo "Orca did not start, so no link was printed. Nothing to add in the app yet." >&2
    exit 1
  fi
  touch "$paired"
fi
bash deploy/wsl/update-orca.sh "$port" 2>&1 | tee -a "$log"

timeout 120 bash -c 'until orca-ide repo list --json > /dev/null 2>&1; do sleep 2; done'
repo_id=$(orca-ide repo add --path "$PWD" --json | jq -r '.result.repo.id // .result.id')
orca-ide repo set-base-ref --repo "id:$repo_id" --ref origin/main --json > /dev/null
note "sign-ins"
have_account() { orca-ide account list --json | jq -e --arg agent "$1" '.result[$agent].accounts | length > 0' > /dev/null; }
have_account claude || orca-ide account add --agent claude
have_account codex || orca-ide account add --agent codex
for profile in "$HOME"/.config/orca/claude-profiles/*/home; do
  [ -d "$profile" ] && no_prompts "$profile"
done
bash deploy/wsl/lifecycle.sh 2>&1 | tee -a "$log"
note "Claude shelf"
bash deploy/wsl/shelf.sh 2>&1 | tee -a "$log"
just accept 2>&1 | tee -a "$log" || echo "Some acceptance checks failed. The lead reads them first."
note "starting the lead"
orca-ide agent launch --agent claude --surface terminal --worktree "path:$PWD" --json \
  --prompt 'You are the Sextant lead, in the clean distro. Read AGENTS.md and docs/start.md, run just accept, then take the next step there.' \
  > /dev/null
note "done"
echo "Sextant is up. In the Orca app, switch to the sextant server: its Claude lead is already working in a tab."
