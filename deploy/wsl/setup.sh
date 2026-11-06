#!/usr/bin/env bash
# Loads the clean Sextant environment from this checkout, then starts its Orca. Safe to run again.
# Each tool comes from its upstream's documented installer, at the pin this repo already holds.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

dockerfile=.devcontainer/Dockerfile
agents="$HOME/.local/share/sextant-agents"
fnm_dir="$HOME/.fnm"
export PATH="$agents/node_modules/.bin:$fnm_dir/aliases/default/bin:$fnm_dir:$HOME/.local/bin:$PATH"

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

claude_version=$(sed -n 's/^RUN claude install //p' "$dockerfile")
curl -fsSL https://claude.ai/install.sh | bash -s "$claude_version"

mkdir -p "$agents"
cp .devcontainer/agents/package.json .devcontainer/agents/package-lock.json "$agents/"
(cd "$agents" && npm ci --no-audit --no-fund)

uv sync --frozen
}
install_tools 2>&1 | tee -a "$log"

# No prompt anywhere in this distro. Orca already launches every agent with its bypass flag
# (stablyai/orca@a162e08b29b2883b02d8a0dfcc99e26c80b2cfe7:docs/site/content/docs/agents/supported.mdx). These answer Claude's own
# dialog up front, for plain tabs and for Orca's managed accounts, whose settings live apart.
no_prompts() {
  mkdir -p "$1"
  [ -f "$1/settings.json" ] || echo '{}' > "$1/settings.json"
  jq '.permissions.defaultMode = "bypassPermissions" | .skipDangerousModePermissionPrompt = true' \
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
  env "${limits[@]}" orca-ide serve --port "$port" --pairing-address "$address" || true
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
just accept 2>&1 | tee -a "$log" || echo "Some acceptance checks failed. The lead reads them first."
note "starting the lead"
orca-ide agent launch --agent claude --surface terminal --worktree "path:$PWD" --json \
  --prompt 'You are the Sextant lead, in the clean distro. Read AGENTS.md and docs/start.md, run just accept, then take the next step there.' \
  > /dev/null
note "done"
echo "Sextant is up. In the Orca app, switch to the sextant server: its Claude lead is already working in a tab."
