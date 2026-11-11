#!/usr/bin/env bash
# Runtime parity (parity.json): the Muse binary and launcher, the dsh and Antigravity launchers, the keyed MCP
# bridge, then parity.py's shelf and MCP set. install.sh ends with it; run it alone to apply only this layer.
# Release digest checks follow install.sh; npm ci follows deploy/wsl/setup.sh.
set -euo pipefail
set +x
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
prefix="$HOME/.local/share/sextant-lane-runtimes"
python3 -I "$here/parity.py" --check-roots
# dsh plugin runs pnpm from PATH (dsh-plugin-manager). Its source is the host-tools lock, pnpm 11.21.0 in
# deploy/wsl/dsh/package-lock.json (manifest "Native profile package manager"), which setup.sh installs here.
export PATH="$HOME/.local/share/sextant-host-tools/node_modules/.bin:$PATH"
if ! command -v pnpm > /dev/null; then
  echo 'parity: pnpm is not on PATH. dsh plugin add needs the host-tools lock (deploy/wsl/dsh/package-lock.json, pnpm 11.21.0); install it with deploy/wsl/setup.sh, then rerun.' >&2
  exit 4
fi
mkdir -p "$prefix" "$HOME/.local/bin"
# Muse Code from Meta's release manifest, checked against the manifest's sha256 (pins.json muse).
muse="$HOME/.local/share/muse-code/muse-$(jq -r .muse.version "$here/pins.json")"
digest=$(jq -r .muse.sha256 "$here/pins.json")
if ! printf '%s  %s\n' "$digest" "$muse" | sha256sum --check --status - 2> /dev/null; then
  work=$(mktemp -d)
  trap 'rm -rf -- "$work"' EXIT
  curl -fsSL "$(jq -r .muse.url "$here/pins.json")" -o "$work/muse"
  printf '%s  %s\n' "$digest" "$work/muse" | sha256sum -c -
  install -D -m 755 "$work/muse" "$muse"
fi
# punkpeye/mcp-remote 0.15.2 (published 2026-10-20; pins.json release_cooldown_days 14, lock resolved --before that cutoff), the header bridge Antigravity's keyed Context7 and Exa entries run.
mkdir -p "$prefix/mcp-bridge"
cp "$here/mcp-bridge/package.json" "$here/mcp-bridge/package-lock.json" "$prefix/mcp-bridge/"
npm ci --prefix "$prefix/mcp-bridge" --omit=dev --ignore-scripts --no-audit --no-fund
for runtime in claude antigravity dsh dsh-tui muse; do
  install -m 755 "$here/$runtime-launch.sh" "$prefix/$runtime-launch.sh"
done
cp "$here/pins.json" "$here/model-policy.json" "$prefix/"
repository=$(git -C "$here" rev-parse --path-format=absolute --git-common-dir)
printf '%s\n' "${repository%/.git}" > "$prefix/repository-path"
ln -sfn "$prefix/antigravity-launch.sh" "$HOME/.local/bin/agy"
# sextant-dsh is the name every Sextant dsh launch calls, so it needs no PATH order (#255's pattern).
# The bare dsh stays for AO 0.14.10, whose deepseek-harness adapter resolves only that name.
ln -sfn "$prefix/dsh-launch.sh" "$HOME/.local/bin/sextant-dsh"
ln -sfn "$prefix/dsh-launch.sh" "$HOME/.local/bin/dsh"
# Plain dsh-tui, Orca's dsh agent launch, is the keyed launcher on the enhanced home (dsh-tui-launch.sh).
ln -sfn "$prefix/dsh-tui-launch.sh" "$HOME/.local/bin/dsh-tui"
ln -sfn "$prefix/muse-launch.sh" "$HOME/.local/bin/muse"
python3 -I "$here/parity.py" "$@"
