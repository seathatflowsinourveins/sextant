#!/usr/bin/env bash
# Native installs only; sources and artifact digests are in pins.json.
# npm ci follows deploy/wsl/setup.sh; release digest checks follow update-orca.sh.
set -euo pipefail
set +x
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
prefix="$HOME/.local/share/sextant-lane-runtimes"
[[ $(uname -sm) == 'Linux x86_64' ]] || { echo 'Linux x86_64 only' >&2; exit 2; }
# Owner's issue #62 floor: 20 GB available, not total or merely free RAM.
awk '/^MemAvailable:/ {exit ($2 * 1024 < 20000000000)}' /proc/meminfo || {
  echo 'Keep 20 GB MemAvailable; defer installation' >&2; exit 3;
}
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
mkdir -p "$prefix/bin" "$HOME/.local/bin"
cp "$here/package.json" "$here/package-lock.json" "$prefix/"
npm ci --ignore-scripts --no-audit --no-fund --prefix "$prefix"
# The pinned OpenCode postinstall selects and verifies its exact-version optional binary.
npm rebuild --prefix "$prefix" @opencode/cli
for runtime in omp antigravity; do
  url=$(jq -r --arg r "$runtime" '.runtimes[$r].url' "$here/pins.json")
  digest=$(jq -r --arg r "$runtime" '.runtimes[$r].sha256' "$here/pins.json")
  curl -fsSL "$url" -o "$work/$runtime"
  printf '%s  %s\n' "$digest" "$work/$runtime" | sha256sum -c -
done
install -m 755 "$work/omp" "$prefix/bin/omp"
mkdir -p "$prefix/bin/antigravity"
tar -xzf "$work/antigravity" -C "$prefix/bin/antigravity"
commit=$(jq -r '.runtimes.hermes.commit' "$here/pins.json")
if [[ ! -x "$prefix/hermes-source/.hermes/bin/hermes" ]] ||
   [[ $(git -C "$prefix/hermes-source" rev-parse HEAD) != "$commit" ]]; then
  curl -fsSL "https://raw.githubusercontent.com/NousResearch/hermes-agent/$commit/scripts/install.sh" -o "$work/hermes"
  digest=$(jq -r '.runtimes.hermes.installer_sha256' "$here/pins.json")
  printf '%s  %s\n' "$digest" "$work/hermes" | sha256sum -c -
  bash "$work/hermes" --commit "$commit" --non-interactive --skip-browser --skip-computer-use \
    --dir "$prefix/hermes-source" --hermes-home "$prefix/hermes-home"
fi
if [[ ! -x "$prefix/openhands/bin/python" ]]; then uv venv "$prefix/openhands" --python 3.13; fi
uv pip sync --require-hashes --python "$prefix/openhands/bin/python" "$here/openhands-requirements.txt"
mkdir -p "$prefix/router"
cp "$here/router/package.json" "$here/router/package-lock.json" "$prefix/router/"
npm ci --ignore-scripts --no-audit --no-fund --prefix "$prefix/router"
npm rebuild --prefix "$prefix/router" better-sqlite3 omniroute
# Upstream Hermes supports disabling adoption of external CLI logins (ADR-0056).
"$prefix/openhands/bin/python" - <<'PY'
from pathlib import Path
import yaml
config = Path.home() / '.local/share/sextant-lane-runtimes/hermes-home/config.yaml'
data = yaml.safe_load(config.read_text()) or {}
data.setdefault('auth', {})['adopt_external_logins'] = False
data.setdefault('updates', {})['check'] = False
config.write_text(yaml.safe_dump(data, sort_keys=False))
# Remove only upstream's public first-boot password placeholder; the owner sets the dashboard password.
env_file = Path.home() / '.local/share/sextant-lane-runtimes/router/node_modules/omniroute/.env'
if env_file.exists():
    lines = ['INITIAL_PASSWORD=' if line.strip() == 'INITIAL_PASSWORD=CHANGEME' else line
             for line in env_file.read_text().splitlines()]
    env_file.write_text('\n'.join(lines) + '\n')
PY
install -m 755 "$here/api-launch.sh" "$prefix/api-launch.sh"
install -m 755 "$here/antigravity-launch.sh" "$prefix/antigravity-launch.sh"
install -m 755 "$here/codex-launch.sh" "$prefix/codex-launch.sh"
install -m 755 "$here/router-start.sh" "$prefix/router-start.sh"
cp "$here/configure.py" "$here/routing.json" "$here/model-policy.json" "$here/openhands-lane.py" "$prefix/"
python3 "$prefix/configure.py" "$prefix"
repository=$(git -C "$here" rev-parse --path-format=absolute --git-common-dir)
printf '%s\n' "${repository%/.git}" > "$prefix/repository-path"
for name in OMNIROUTE_API_KEY OMNIROUTE_JWT_SECRET OMNIROUTE_API_KEY_SECRET OMNIROUTE_STORAGE_ENCRYPTION_KEY OMNIROUTE_CLI_SALT; do
  if [[ ! -e "$HOME/.config/sextant/credentials/$name" ]]; then
    { openssl rand -hex 32; printf '%s\n' NS_SEALED_TRANSFER_COMPLETE; } |
      "$here/../../../scripts/keys.sh" set "$name" --sealed-stdin
  fi
done
for runtime in pi omp opencode opencode2 hermes openhands-sdk; do
  ln -sfn "$prefix/api-launch.sh" "$HOME/.local/bin/$runtime"
done
ln -sfn "$prefix/antigravity-launch.sh" "$HOME/.local/bin/agy"
# Codex on the router: one launcher, a writer's and a reviewer's default sandbox (README, Codex).
ln -sfn "$prefix/codex-launch.sh" "$HOME/.local/bin/sextant-codex"
ln -sfn "$prefix/codex-launch.sh" "$HOME/.local/bin/sextant-codex-review"
echo 'Installed; use just omniroute for the durable server, then its combo create command from routing.json.'
echo 'Provider/Google browser sign-ins are owner-only; OpenHands has no native Orca agent ID.'
bash "$here/service.sh" install
