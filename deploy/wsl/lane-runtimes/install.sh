#!/usr/bin/env bash
# Native installs only; sources and artifact digests are in pins.json.
# Release digest checks follow update-orca.sh; the router follows the OmniRoute lock in router/.
set -euo pipefail
set +x
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
prefix="$HOME/.local/share/sextant-lane-runtimes"
python3 -I "$here/parity.py" --check-roots
[[ $(uname -sm) == 'Linux x86_64' ]] || { echo 'Linux x86_64 only' >&2; exit 2; }
# Owner's issue #62 floor: 20 GB available, not total or merely free RAM.
awk '/^MemAvailable:/ {exit ($2 * 1024 < 20000000000)}' /proc/meminfo || {
  echo 'Keep 20 GB MemAvailable; defer installation' >&2; exit 3;
}
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
mkdir -p "$prefix/bin" "$HOME/.local/bin"
url=$(jq -r '.runtimes.antigravity.url' "$here/pins.json")
digest=$(jq -r '.runtimes.antigravity.sha256' "$here/pins.json")
curl -fsSL "$url" -o "$work/antigravity"
printf '%s  %s\n' "$digest" "$work/antigravity" | sha256sum -c -
mkdir -p "$prefix/bin/antigravity"
tar -xzf "$work/antigravity" -C "$prefix/bin/antigravity"
mkdir -p "$prefix/router"
cp "$here/router/package.json" "$here/router/package-lock.json" "$prefix/router/"
npm ci --ignore-scripts --no-audit --no-fund --prefix "$prefix/router"
npm rebuild --prefix "$prefix/router" better-sqlite3 omniroute
# Remove only upstream's public first-boot password placeholder; the owner sets the dashboard password.
python3 - <<'PY'
from pathlib import Path
env_file = Path.home() / '.local/share/sextant-lane-runtimes/router/node_modules/omniroute/.env'
if env_file.exists():
    lines = ['INITIAL_PASSWORD=' if line.strip() == 'INITIAL_PASSWORD=CHANGEME' else line
             for line in env_file.read_text().splitlines()]
    env_file.write_text('\n'.join(lines) + '\n')
PY
install -m 755 "$here/antigravity-launch.sh" "$prefix/antigravity-launch.sh"
install -m 755 "$here/codex-launch.sh" "$prefix/codex-launch.sh"
install -m 755 "$here/router-start.sh" "$prefix/router-start.sh"
cp "$here/routing.json" "$here/model-policy.json" "$prefix/"
repository=$(git -C "$here" rev-parse --path-format=absolute --git-common-dir)
printf '%s\n' "${repository%/.git}" > "$prefix/repository-path"
for name in OMNIROUTE_API_KEY OMNIROUTE_JWT_SECRET OMNIROUTE_API_KEY_SECRET OMNIROUTE_STORAGE_ENCRYPTION_KEY OMNIROUTE_CLI_SALT; do
  if [[ ! -e "$HOME/.config/sextant/credentials/$name" ]]; then
    { openssl rand -hex 32; printf '%s\n' NS_SEALED_TRANSFER_COMPLETE; } |
      "$here/../../../scripts/keys.sh" set "$name" --sealed-stdin
  fi
done
ln -sfn "$prefix/antigravity-launch.sh" "$HOME/.local/bin/agy"
# Codex on the router: one launcher, a writer's and a reviewer's default sandbox (README, Codex).
ln -sfn "$prefix/codex-launch.sh" "$HOME/.local/bin/sextant-codex"
ln -sfn "$prefix/codex-launch.sh" "$HOME/.local/bin/sextant-codex-review"
echo 'Installed; use just omniroute for the durable server, then its combo create command from routing.json.'
echo 'Provider/Google browser sign-ins are owner-only.'
bash "$here/service.sh" install
# Runtime parity: Muse, the dsh and Antigravity launchers, the MCP bridge, the shelf and MCP set (parity.json).
bash "$here/parity.sh"
